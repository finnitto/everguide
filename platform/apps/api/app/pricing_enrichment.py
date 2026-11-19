"""Deterministic price extraction for verified Overture provider candidates.

Queueing, extraction and verification are separate states. Rule extraction only
captures explicit GBP amounts and source-backed descriptions from verified
provider-owned website pages. It does not estimate prices, publish providers,
or mark price evidence verified.
"""
from __future__ import annotations

import hashlib
import html
import re
import time
from difflib import SequenceMatcher
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from io import BytesIO
from urllib.robotparser import RobotFileParser

from pypdf import PdfReader
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.config import settings
from app.database import SessionLocal
from app.models import (
    AuditEvent,
    Branch,
    OvertureCandidate,
    OvertureImportRun,
    PricingEvidence,
    Provider,
    SourcePermission,
)
from app.candidate_quality import OVERTURE_IMPORT_SERVICE_TYPES
from app.website_checks import USER_AGENT, _get, _validate_public_https, verify_candidate
from app.candidate_quality import normalise_identity_name, normalise_postcode


PRICING_ENRICHMENT_KEY = "pricing_enrichment"
PRICING_ENRICHMENT_VERSION = "pricing-enrichment-v3"
# Keep each response bounded while allowing ordinary media-rich funeral sites
# (many return >1 MB of HTML). PDF parsing remains bounded by both this cap and
# MAX_PDF_PAGES/MAX_TEXT_PER_PAGE below.
MAX_PAGE_BYTES = 4_000_000
MAX_PDF_PAGES = 50
MAX_TEXT_PER_PAGE = 8_000
MAX_TOTAL_TEXT = 24_000
MAX_PAGES_HARD_LIMIT = 10
PRICE_PAGE_HINT = re.compile(
    r"(price|pricing|cost|standardis[se]d[-_ ]price|funeral[-_ ]prices|price[-_ ]list)",
    re.I,
)
ACCESS_CHALLENGE_HINT = re.compile(
    r"(pardon our interruption|verify you are human|checking your browser|"
    r"captcha|unusual traffic|access denied|automated requests)",
    re.I,
)
GBP_AMOUNT = re.compile(
    r"(?:£\s*|\bGBP\s*)(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)",
    re.I,
)

# These states must not be reset by repeated approval events and backfills.
NON_REQUEUEABLE_STATES = {
    "queued",
    "in_progress",
    "completed",
    "no_prices_found",
    "blocked",
}


class PricePageBlocked(RuntimeError):
    """A website did not pass the conservative price-page access checks."""


class _VisiblePageParser(HTMLParser):
    _BLOCK_TAGS = {
        "address", "article", "blockquote", "br", "dd", "div", "dl", "dt", "h1", "h2",
        "h3", "h4", "h5", "h6", "header", "li", "main", "p", "section", "ul", "ol",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.lines: list[str] = []
        self._line_parts: list[str] = []
        self._table_row = False
        self._table_cells: list[str] = []
        self._cell_parts: list[str] | None = None
        self.links: list[dict[str, str]] = []
        self.title_parts: list[str] = []
        self._in_title = False
        self._current_link: int | None = None
        self._skip_depth = 0
        self._skip_tags = {"script", "style", "noscript", "svg", "iframe", "template"}

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        values = dict(attrs)
        if tag in self._skip_tags:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag == "a" and values.get("href"):
            self.links.append({"href": str(values["href"]), "text": ""})
            self._current_link = len(self.links) - 1
        if tag == "tr":
            self._flush_line()
            self._table_row = True
            self._table_cells = []
        elif tag in {"td", "th"} and self._table_row:
            self._cell_parts = []
        elif tag in self._BLOCK_TAGS and not self._table_row:
            self._flush_line()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        if tag == "a":
            self._current_link = None
        if tag in {"td", "th"} and self._table_row:
            cell = _normalise_space(" ".join(self._cell_parts or []))
            if cell:
                self._table_cells.append(cell)
            self._cell_parts = None
        elif tag == "tr" and self._table_row:
            if self._cell_parts:
                cell = _normalise_space(" ".join(self._cell_parts))
                if cell:
                    self._table_cells.append(cell)
            row = _normalise_space(" | ".join(self._table_cells))
            if row:
                self.lines.append(row)
                self.text_parts.append(row)
            self._table_row = False
            self._cell_parts = None
            self._table_cells = []
        elif tag in self._BLOCK_TAGS and not self._table_row:
            self._flush_line()
        if tag in self._skip_tags and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        value = re.sub(r"\s+", " ", data or "").strip()
        if not value:
            return
        if self._in_title:
            self.title_parts.append(value)
        if self._current_link is not None:
            link = self.links[self._current_link]
            link["text"] = _normalise_space(link["text"] + " " + value)
        if not self._skip_depth:
            self.text_parts.append(value)
            if self._table_row:
                if self._cell_parts is not None:
                    self._cell_parts.append(value)
            else:
                self._line_parts.append(value)

    def close(self):
        super().close()
        if self._table_row:
            row = _normalise_space(" | ".join(self._table_cells + [" ".join(self._cell_parts or [])]))
            if row:
                self.lines.append(row)
                self.text_parts.append(row)
            self._table_row = False
        self._flush_line()

    def _flush_line(self):
        line = _normalise_space(" ".join(self._line_parts))
        if line:
            self.lines.append(line)
        self._line_parts = []

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalise_space(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _candidate_matches_verified_site(candidate: OvertureCandidate, extracted: dict | None) -> bool:
    if not extracted:
        return False
    raw = dict(candidate.raw_data or {})
    source_name = normalise_identity_name(raw.get("name") or candidate.candidate_name)
    page_name = normalise_identity_name(extracted.get("name"))
    if not source_name or not page_name:
        return False
    name_match = source_name == page_name or (
        min(len(source_name), len(page_name)) >= 6
        and (
            source_name in page_name
            or page_name in source_name
            or SequenceMatcher(None, source_name, page_name).ratio() >= 0.88
        )
    )
    if not name_match:
        source_tokens = set(source_name.split())
        page_tokens = set(page_name.split())
        if source_tokens and page_tokens:
            name_match = len(source_tokens & page_tokens) / min(len(source_tokens), len(page_tokens)) >= 0.8
    postcode_match = normalise_postcode(raw.get("postcode") or candidate.postcode) == normalise_postcode(
        extracted.get("postcode")
    )
    return bool(name_match and postcode_match)


def _verified_site_has_explicit_branch_conflict(
    candidate: OvertureCandidate, extracted: dict | None,
) -> bool:
    """Only block price retrieval for positive contradictions at this branch.

    Overture-supplied URLs are permitted for enrichment by default. Missing
    page identity fields are therefore unknown, not a reason to block. A
    closed-branch signal, a different postcode, or a different operator is
    material only when the page identifies the same street and locality.
    """
    if not isinstance(extracted, dict) or extracted.get("has_complete_branch_address") is not True:
        return False
    raw = dict(candidate.raw_data or {})
    source_street = normalise_identity_name(raw.get("address_line_1") or raw.get("address"))
    page_street = normalise_identity_name(extracted.get("street"))
    source_town = normalise_identity_name(raw.get("town_city") or raw.get("town") or raw.get("locality"))
    page_town = normalise_identity_name(extracted.get("town"))
    same_location = bool(source_street and page_street and source_street == page_street
        and source_town and page_town and source_town == page_town)
    if not same_location:
        return False

    branch_status = str(extracted.get("branch_status") or extracted.get("business_status") or "").strip().lower()
    if branch_status in {"closed", "permanently_closed", "permanently closed", "temporarily_closed", "temporarily closed"}:
        return True

    source_postcode = normalise_postcode(raw.get("postcode") or candidate.postcode)
    page_postcode = normalise_postcode(extracted.get("postcode"))
    if source_postcode and page_postcode and source_postcode != page_postcode:
        return True

    source_name = normalise_identity_name(raw.get("name") or candidate.candidate_name)
    page_name = normalise_identity_name(extracted.get("name"))
    if source_name and page_name:
        name_match = source_name == page_name or (
            min(len(source_name), len(page_name)) >= 6
            and (source_name in page_name or page_name in source_name
                 or SequenceMatcher(None, source_name, page_name).ratio() >= 0.88)
        )
        if not name_match:
            source_tokens = set(source_name.split())
            page_tokens = set(page_name.split())
            name_match = bool(source_tokens and page_tokens
                and len(source_tokens & page_tokens) / min(len(source_tokens), len(page_tokens)) >= 0.8)
        if not name_match:
            return True
    return False


def queue_overture_candidate_for_pricing(
    db: Session,
    candidate: OvertureCandidate,
    *,
    trigger: str,
    requested_by: str,
    run_id: int | None = None,
    force_retry: bool = False,
) -> bool:
    """Queue a linked Overture candidate with a verified first-party site for enrichment.

    This is independent of provider publication status; exceptions still require
    identity review before a provider can be linked to the candidate.
    """
    evidence = dict(candidate.first_party_evidence or {})
    if not (
        evidence.get("website_url")
        and evidence.get("verification_status") == "reachable"
        and evidence.get("robots_allowed") is True
    ):
        return False
    current = evidence.get(PRICING_ENRICHMENT_KEY)
    current = dict(current) if isinstance(current, dict) else {}
    if current.get("status") in NON_REQUEUEABLE_STATES and not (
            force_retry and current.get("status") == "no_prices_found"):
        return False

    now = _now()
    current.update({
        "status": "queued",
        "version": PRICING_ENRICHMENT_VERSION,
        "trigger": trigger,
        "requested_by": requested_by or "system",
        "requested_at": now.isoformat(),
        "attempt_count": max(0, int(current.get("attempt_count") or 0)),
        "last_error": None,
    })
    if run_id is not None:
        current["overture_run_id"] = int(run_id)
        current.pop("run_terminal_status", None)
    evidence[PRICING_ENRICHMENT_KEY] = current
    candidate.first_party_evidence = evidence

    db.add(AuditEvent(
        entity_type="overture_candidate",
        entity_id=candidate.id,
        action="pricing_enrichment_queued",
        detail={
            "gers_id": candidate.gers_id,
            "provider_id": candidate.provider_id,
            "branch_id": candidate.branch_id,
            "status": "queued",
            "trigger": trigger,
            "queue_version": PRICING_ENRICHMENT_VERSION,
        },
        actor=requested_by or "system",
    ))
    return True


def queue_approved_overture_candidates_for_pricing(
    db: Session,
    *,
    requested_by: str,
) -> dict:
    """Backfill verified Overture websites linked to any funeral-director provider.

    Enrichment eligibility does not require provider publication. Only candidates
    with a reachable, robots-permitted first-party URL are queued.
    """
    candidates = (
        db.query(OvertureCandidate)
        .join(Provider, Provider.id == OvertureCandidate.provider_id)
        .filter(
            Provider.provider_type.in_(set(OVERTURE_IMPORT_SERVICE_TYPES.values())),
            OvertureCandidate.provider_id.is_not(None),
        )
        .order_by(OvertureCandidate.id.asc())
        .all()
    )

    queued = 0
    already_marked = 0
    queued_ids = []
    for candidate in candidates:
        if queue_overture_candidate_for_pricing(
            db,
            candidate,
            trigger="approved_candidate_backfill",
            requested_by=requested_by,
        ):
            queued += 1
            queued_ids.append(candidate.id)
        else:
            already_marked += 1

    return {
        "matched_candidates": len(candidates),
        "queued": queued,
        "already_marked": already_marked,
        "queued_candidate_ids": queued_ids,
    }


def dispatch_queued_price_enrichment(candidate_ids: list[int], *, max_tasks: int = 20) -> int:
    """Dispatch a bounded batch only after the caller has committed queue markers."""
    if not settings.price_enrichment_enabled:
        return 0
    limit = min(max(int(max_tasks), 0), 100)
    dispatched = 0
    for candidate_id in sorted({int(value) for value in candidate_ids if value})[:limit]:
        enrich_overture_candidate_prices.delay(candidate_id)
        dispatched += 1
    return dispatched


def _read_robots(origin: str) -> RobotFileParser:
    status, _, body, redirect = _get(origin + "/robots.txt", 65_536)
    if redirect:
        raise PricePageBlocked("robots.txt redirects; price extraction stopped.")
    if status >= 400:
        raise PricePageBlocked(f"robots.txt could not be checked (HTTP {status}).")
    parser = RobotFileParser()
    parser.set_url(origin + "/robots.txt")
    parser.parse(body.decode("utf-8", errors="replace").splitlines())
    return parser


def _fetch_price_pages(
    website_url: str,
    max_pages: int = 6,
    *,
    diagnostics: dict | None = None,
) -> list[dict]:
    """Fetch a small number of same-host price pages after HTTPS/robots checks."""
    diagnostics = diagnostics if diagnostics is not None else {}
    diagnostics.update({"pages_attempted": 0, "pages_fetched": 0, "pages_skipped": {},
                        "access_challenge_pages": 0})
    parsed, host = _validate_public_https(website_url)
    if parsed.port not in (None, 443):
        raise PricePageBlocked("Only standard HTTPS provider website pages are eligible.")
    origin = f"https://{host}"
    robots = _read_robots(origin)

    limit = min(max(int(max_pages), 1), MAX_PAGES_HARD_LIMIT)
    candidates = [urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))]
    pages: list[dict] = []
    seen: set[str] = set()
    total_chars = 0

    while candidates and len(pages) < limit and total_chars < MAX_TOTAL_TEXT:
        url = candidates.pop(0)
        if url in seen:
            continue
        seen.add(url)
        page_parsed, page_host = _validate_public_https(url)
        if page_host != host or page_parsed.port not in (None, 443):
            continue
        if not robots.can_fetch(USER_AGENT, url):
            diagnostics["pages_skipped"]["robots_disallowed"] = diagnostics["pages_skipped"].get("robots_disallowed", 0) + 1
            continue

        diagnostics["pages_attempted"] += 1
        try:
            status, headers, body, redirect = _get(url, MAX_PAGE_BYTES)
        except ValueError as exc:
            if "Response exceeded the configured safety size limit" not in str(exc):
                raise
            diagnostics["pages_skipped"]["response_size_limit"] = diagnostics["pages_skipped"].get("response_size_limit", 0) + 1
            continue
        if redirect or status < 200 or status >= 300:
            reason = "redirect" if redirect else f"http_{status}"
            diagnostics["pages_skipped"][reason] = diagnostics["pages_skipped"].get(reason, 0) + 1
            continue
        diagnostics["pages_fetched"] += 1
        content_type = str(headers.get("Content-Type", "")).lower()
        is_pdf = "application/pdf" in content_type or urllib.parse.urlsplit(url).path.lower().endswith(".pdf")
        page_texts = []
        page_links = []
        if is_pdf:
            if not body.startswith(b"%PDF-"):
                diagnostics["pages_skipped"]["invalid_pdf"] = diagnostics["pages_skipped"].get("invalid_pdf", 0) + 1
                continue
            try:
                pdf = PdfReader(BytesIO(body), strict=True)
                if pdf.is_encrypted or not pdf.pages:
                    continue
                for page_number, pdf_page in enumerate(pdf.pages[:MAX_PDF_PAGES], start=1):
                    extracted = pdf_page.extract_text() or ""
                    lines = _bounded_price_lines(extracted.splitlines())
                    if lines:
                        page_texts.append((page_number, lines))
            except Exception:
                diagnostics["pages_skipped"]["pdf_parse_error"] = diagnostics["pages_skipped"].get("pdf_parse_error", 0) + 1
                continue
            title = "PDF price list"
        elif "text/html" in content_type:
            decoded = body.decode(headers.get_content_charset() or "utf-8", errors="replace")
            parser = _VisiblePageParser()
            parser.feed(decoded)
            parser.close()
            page_links = parser.links
            lines = _bounded_price_lines(parser.lines or parser.text_parts)
            if lines:
                page_texts.append((None, lines))
            title = _normalise_space(" ".join(parser.title_parts))[:300]
            visible_text = _normalise_space(" ".join(parser.text_parts))
            if ACCESS_CHALLENGE_HINT.search(title + " " + visible_text[:2_000]):
                diagnostics["access_challenge_pages"] += 1
                diagnostics["pages_skipped"]["access_challenge"] = diagnostics["pages_skipped"].get("access_challenge", 0) + 1
                continue
        else:
            diagnostics["pages_skipped"]["unsupported_content_type"] = diagnostics["pages_skipped"].get("unsupported_content_type", 0) + 1
            continue

        source_sha256 = hashlib.sha256(body).hexdigest()
        for page_number, lines in page_texts:
            text = _normalise_space(" ".join(lines))
            if _explicit_gbp_amounts(text):
                pages.append({
                    "url": url,
                    "title": title,
                    "text": text,
                    "lines": lines,
                    "sha256": source_sha256,
                    "source_format": "pdf" if is_pdf else "html",
                    "source_page_number": page_number,
                })
                total_chars += len(text)
                if len(pages) >= limit or total_chars >= MAX_TOTAL_TEXT:
                    break

        # The homepage can be only a navigation page. Follow its price-list
        # links even when it contains no GBP amounts of its own.
        if len(seen) == 1:
            for link in page_links:
                href = link["href"]
                absolute = urllib.parse.urljoin(url, href)
                linked = urllib.parse.urlsplit(absolute)
                if (linked.scheme.lower() != "https" or linked.hostname is None
                        or linked.hostname.lower() != host or linked.port not in (None, 443)
                        or (not linked.path.lower().endswith(".pdf")
                            and not PRICE_PAGE_HINT.search(linked.path + " " + href + " " + link["text"]))):
                    continue
                clean_path = urllib.parse.quote(linked.path, safe="/%:@!$&'()*+,;=-._~%")
                clean_query = urllib.parse.quote(linked.query, safe="/?@!$&'()*+,;=:%-._~")
                clean = urllib.parse.urlunsplit((linked.scheme, linked.netloc, clean_path, clean_query, ""))
                if clean not in seen and clean not in candidates:
                    candidates.append(clean)
        if candidates and len(pages) < limit:
            time.sleep(0.2)

    return pages


def _bounded_price_lines(lines: list[str]) -> list[str]:
    """Keep source row boundaries while respecting the per-page text limit."""
    bounded = []
    remaining = MAX_TEXT_PER_PAGE
    for raw in lines:
        line = _normalise_space(raw)
        if not line or remaining <= 0:
            continue
        line = line[:remaining]
        bounded.append(line)
        remaining -= len(line) + 1
    return bounded


def _option_heading(line: str) -> str | None:
    """Return a short, explicit funeral-option heading from visible source text."""
    cleaned = _normalise_space(line)
    if len(cleaned) > 140:
        return None
    if re.search(r"\b(?:fees you must pay|additional funeral director products|crematoria fees|cemeteries fees)\b", cleaned, re.I):
        return None
    if re.search(r"\b(?:package|option)\b", cleaned, re.I):
        label = re.split(r"[|:;(£]", cleaned, maxsplit=1)[0].strip(" -–—")
        return label[:120] if len(label) >= 4 else None
    known = re.match(
        r"((?:(?:attended|unattended|traditional|classic|bespoke|premium|simple|intimate|direct)\s+)"
        r"(?:funeral|cremation|burial)(?:\s+(?:service|funeral))?)\b",
        cleaned,
        re.I,
    )
    if known:
        return known.group(1)[:120]
    meet = re.match(r"(meet at (?:the )?crematorium)\b", cleaned, re.I)
    return meet.group(1)[:120] if meet else None


def _is_non_option_price_section(line: str) -> bool:
    return bool(re.search(
        r"\b(?:fees you must pay|additional funeral director products and services|"
        r"crematoria fees|cemeteries fees|local authority fees)\b",
        line,
        re.I,
    ))


def _line_fee_type(line: str, option_group_name: str | None) -> str:
    folded = line.casefold()
    if option_group_name and "package" in option_group_name.casefold():
        if re.search(r"\b(?:package price|total cost|package total)\b", folded):
            return "package"
    if re.search(r"\b(?:total cost|package price|funeral package|cremation package|burial package)\b", folded):
        return "package"
    if re.search(r"\b(?:disbursement|third[- ]party|crematorium fee|burial fee|interment fee|minister fee|celebrant fee)\b", folded):
        return "disbursement"
    if re.search(r"\b(?:professional service|professional fee|arrangement fee|funeral director costs)\b", folded):
        return "professional_fee"
    if re.search(r"\b(?:standardised price list|standardized price list|charges only)\b", folded):
        return "standardised_price_list"
    if re.search(r"\b(?:coffin|casket|urn|flowers|limousine|hearse|bearers)\b", folded):
        return "item"
    return "other"


def _line_service_category(line: str) -> str:
    folded = line.casefold()
    if "cremat" in folded:
        return "cremation"
    if "burial" in folded or "interment" in folded:
        return "burial"
    if "coffin" in folded:
        return "coffin"
    if "professional" in folded or "arrangement" in folded:
        return "professional_fee"
    if "funeral" in folded or "hearse" in folded:
        return "funeral"
    return "other"


def _extract_rule_based_prices(pages: list[dict]) -> dict:
    """Extract only explicit GBP price rows from preserved HTML/PDF line text.

    Rows with ambiguous multiple amounts or no descriptive text are skipped.
    Option grouping is conservative: the exact heading and price row must fit in
    the retained source quote, which is checked again by _validate_extracted_prices.
    """
    extracted = []
    for page in pages:
        lines = page.get("lines") or str(page.get("text") or "").splitlines()
        lines = [_normalise_space(line) for line in lines if _normalise_space(line)]
        active_group = None
        group_start = None
        for index, line in enumerate(lines):
            if _is_non_option_price_section(line):
                active_group = None
                group_start = None
            heading = _option_heading(line)
            matches = list(GBP_AMOUNT.finditer(line))
            if not matches:
                if heading:
                    active_group = heading
                    group_start = index
                continue
            if heading and active_group is None:
                active_group = heading
                group_start = index
            if len(matches) > 2:
                continue

            values = []
            try:
                values = [Decimal(match.group(1).replace(",", "")).quantize(Decimal("0.01")) for match in matches]
            except (InvalidOperation, TypeError, ValueError):
                continue
            amount = values[0]
            amount_upper = None
            price_basis = "fixed"
            if len(values) == 2:
                prefix = line[:matches[0].start()].casefold()
                connector = line[matches[0].end():matches[1].start()].strip().casefold()
                suffix = line[matches[1].end():].casefold()
                explicit_range = (
                    ("from" in prefix and re.search(r"\bto\b", connector + " " + suffix))
                    or ("between" in prefix and re.search(r"\band\b", connector + " " + suffix))
                    or connector == "to"
                    or connector in {"-", "–", "—"}
                )
                if not explicit_range or values[1] < values[0]:
                    continue
                amount_upper = values[1]
                price_basis = "range"
            elif re.search(r"\bfrom\b", line[:matches[0].start()], re.I):
                price_basis = "from"

            service_name = GBP_AMOUNT.sub(" ", line)
            service_name = re.sub(r"\b(?:from|to|between|and)\b", " ", service_name, flags=re.I)
            service_name = _normalise_space(re.sub(r"[|:–—-]+", " ", service_name)).strip()
            if not service_name or not re.search(r"[A-Za-z]{2,}", service_name):
                continue

            quote_lines = lines[group_start:index + 1] if active_group is not None and group_start is not None else [line]
            quote = _normalise_space(" ".join(quote_lines))
            option_group_name = active_group
            if len(quote) > 400 or (option_group_name and option_group_name.casefold() not in quote.casefold()):
                quote = line
                option_group_name = None
            if len(quote) > 400:
                continue

            extracted.append({
                "service_name": service_name[:240],
                "option_group_name": option_group_name,
                "service_category": _line_service_category(line),
                "fee_type": _line_fee_type(line, option_group_name),
                "amount": amount,
                "amount_upper": amount_upper,
                "currency": "GBP",
                "price_basis": price_basis,
                "includes": [],
                "excludes": [],
                "source_page_url": page["url"],
                "source_page_number": page.get("source_page_number"),
                "source_quote": quote,
                "confidence": 0.85,
            })
    return {"has_explicit_prices": bool(extracted), "prices": extracted, "notes": "deterministic_rule_parser_v1"}


def _explicit_gbp_amounts(text: str) -> set[Decimal]:
    amounts = set()
    for raw in GBP_AMOUNT.findall(str(text or "")):
        try:
            amounts.add(Decimal(raw.replace(",", "")).quantize(Decimal("0.01")))
        except InvalidOperation:
            continue
    return amounts


def _validate_extracted_prices(payload: dict, pages: list[dict]) -> list[dict]:
    """Reject any amount that cannot be proven in its own short source quotation."""
    pages_by_source = {(page["url"], page.get("source_page_number")): page for page in pages}
    validated = []
    seen = set()
    for item in payload.get("prices") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("source_page_url") or "")
        raw_page_number = item.get("source_page_number")
        try:
            page_number = int(raw_page_number) if raw_page_number is not None else None
        except (TypeError, ValueError):
            continue
        page = pages_by_source.get((url, page_number))
        quote = _normalise_space(item.get("source_quote") or "")
        if not page or not quote or len(quote) > 400:
            continue
        if quote.casefold() not in _normalise_space(page["text"]).casefold():
            continue
        quote_amounts = _explicit_gbp_amounts(quote)
        try:
            amount = Decimal(str(item.get("amount"))).quantize(Decimal("0.01"))
            upper_raw = item.get("amount_upper")
            amount_upper = Decimal(str(upper_raw)).quantize(Decimal("0.01")) if upper_raw is not None else None
        except (InvalidOperation, TypeError, ValueError):
            continue
        if amount < 0 or amount not in quote_amounts:
            continue
        if amount_upper is not None and (amount_upper < amount or amount_upper not in quote_amounts):
            continue
        if item.get("currency") != "GBP":
            continue
        price_basis = str(item.get("price_basis") or "fixed")
        if price_basis not in {"fixed", "from", "range"}:
            continue
        if amount_upper is not None:
            price_basis = "range"
        if price_basis == "range" and amount_upper is None:
            continue
        service_name = _normalise_space(item.get("service_name") or "")[:240]
        if not service_name:
            continue
        option_group_name = _normalise_space(item.get("option_group_name") or "")[:240] or None
        page_text = _normalise_space(page["text"]).casefold()
        if option_group_name and (
            option_group_name.casefold() not in page_text
            or option_group_name.casefold() not in quote.casefold()
        ):
            # A page-wide mention is insufficient: the cited passage must tie the price to this option.
            option_group_name = None
        service_category = str(item.get("service_category") or "other")
        fee_type = str(item.get("fee_type") or "other")
        key = (url, service_name.casefold(), str(amount), str(amount_upper))
        if key in seen:
            continue
        seen.add(key)
        confidence = item.get("confidence", 0)
        try:
            confidence = min(1.0, max(0.0, float(confidence)))
        except (TypeError, ValueError):
            confidence = 0.0
        validated.append({
            "service_name": service_name,
            "option_group_name": option_group_name,
            "service_category": service_category,
            "fee_type": fee_type,
            "amount": amount,
            "amount_upper": amount_upper,
            "currency": "GBP",
            "price_basis": price_basis,
            "includes": [str(v)[:160] for v in item.get("includes", [])[:20] if str(v).strip()],
            "excludes": [str(v)[:160] for v in item.get("excludes", [])[:20] if str(v).strip()],
            "source_page_url": url,
            "source_page_number": page_number,
            "source_format": page.get("source_format", "html"),
            "source_quote": quote,
            "confidence": confidence,
            "source_page_sha256": page["sha256"],
        })
    return validated


def _option_group_id(provider_id: int, branch_id: int | None, group_name: str | None) -> str | None:
    """Return a deterministic group key scoped to one provider branch."""
    if not group_name:
        return None
    scope = f"{provider_id}:{branch_id or 0}:{_normalise_space(group_name).casefold()}"
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()


def _overture_source_permission(
    db: Session, provider: Provider, candidate: OvertureCandidate, website_url: str,
) -> tuple[SourcePermission | None, bool]:
    """Automatically permit a verified Overture first-party URL unless explicitly blocked."""
    host = (urllib.parse.urlsplit(website_url).hostname or "").lower().removeprefix("www.")
    permissions = (
        db.query(SourcePermission)
        .filter(SourcePermission.provider_id == provider.id)
        .order_by(SourcePermission.id.desc())
        .all()
    )
    matching = [
        row for row in permissions
        if host == (row.source_domain or "").lower().removeprefix("www.")
        or host.endswith("." + (row.source_domain or "").lower().removeprefix("www."))
    ]
    blocked = next((row for row in matching if row.permission_status in {"blocked", "rejected"}), None)
    if blocked:
        return blocked, True
    permission = next((row for row in matching if row.permission_status == "approved"), None)
    if permission:
        return permission, False

    permission = next(iter(matching), None)
    basis = (
        "Overture-supplied website URL independently verified as first-party for this funeral-director candidate. "
        "Automatically permitted by Everguide policy for factual price retrieval and evidence capture. "
        "HTTPS, robots.txt and explicit same-branch conflicts or source blocks remain enforced; missing page identity fields are not a conflict."
    )
    if permission is None:
        permission = SourcePermission(
            provider_id=provider.id,
            source_url=website_url,
            source_domain=host,
            permission_status="approved",
            permission_basis=basis,
            approved_by="system:overture_verified_website",
            approved_at=_now(),
        )
        db.add(permission)
        db.flush()
    else:
        permission.source_url = website_url
        permission.permission_status = "approved"
        permission.permission_basis = basis
        permission.approved_by = "system:overture_verified_website"
        permission.approved_at = _now()
    db.add(AuditEvent(
        entity_type="source_permission",
        entity_id=permission.id,
        action="auto_approved_overture_website_for_price_enrichment",
        detail={"provider_id": provider.id, "candidate_id": candidate.id, "source_domain": host},
        actor="system:overture_verified_website",
    ))
    return permission, False


def _set_candidate_pricing_status(
    db: Session,
    candidate: OvertureCandidate,
    status: str,
    *,
    extra: dict | None = None,
) -> None:
    evidence = dict(candidate.first_party_evidence or {})
    marker = dict(evidence.get(PRICING_ENRICHMENT_KEY) or {})
    marker.update({"status": status, "updated_at": _now().isoformat()})
    if extra:
        marker.update(extra)
    terminal_statuses = {"completed", "no_prices_found", "blocked", "needs_source", "awaiting_permission", "awaiting_provider", "failed"}
    run_id = marker.get("overture_run_id")
    if status in terminal_statuses and run_id and marker.get("run_terminal_status") != status:
        # Serialize terminal-counter updates for tasks belonging to the same
        # tracked run. Each worker commits its candidate and run counters in
        # one transaction, so concurrent completions cannot overwrite a newer
        # JSON aggregate with a stale snapshot.
        run = (db.query(OvertureImportRun)
            .filter(OvertureImportRun.id == int(run_id))
            .with_for_update()
            .populate_existing()
            .one_or_none())
        if run:
            metadata = dict(((run.outcomes or {}).get("_meta") or {}))
            if metadata.get("run_type") in {"enrichment_retry", "price_retry"}:
                outcomes = dict(metadata.get("pricing_enrichment_outcomes") or {})
                prior_status = marker.get("run_terminal_status")
                if prior_status:
                    outcomes[prior_status] = max(0, int(outcomes.get(prior_status) or 0) - 1)
                outcomes[status] = int(outcomes.get(status) or 0) + 1
                metadata["pricing_enrichment_outcomes"] = outcomes
                metadata["pricing_enrichment_terminal"] = sum(outcomes.values())
                run.outcomes = {**(run.outcomes or {}), "_meta": metadata}
                if metadata.get("run_type") == "price_retry":
                    run.records_processed = int(metadata.get("pricing_enrichment_terminal") or 0)
                    if int(metadata.get("pricing_enrichment_terminal") or 0) >= int(metadata.get("pricing_enrichment_queued") or 0):
                        run.status = "completed"
                        run.completed_at = _now()
                    else:
                        run.status = "price_enrichment"
                        run.completed_at = None
                elif int(run.records_processed or 0) >= int(run.records_received or 0):
                    if int(metadata.get("pricing_enrichment_terminal") or 0) >= int(metadata.get("pricing_enrichment_queued") or 0):
                        run.status = "completed"
                        run.completed_at = _now()
                    else:
                        run.status = "price_enrichment"
                        run.completed_at = None
                marker["run_terminal_status"] = status
    evidence[PRICING_ENRICHMENT_KEY] = marker
    candidate.first_party_evidence = evidence


def _branch_context(candidate: OvertureCandidate, branch) -> str:
    raw = dict(candidate.raw_data or {})
    return ", ".join(
        str(value).strip()
        for value in (
            raw.get("address_line_1") or raw.get("address"),
            raw.get("town_city") or raw.get("locality"),
            raw.get("postcode") or candidate.postcode,
            getattr(branch, "branch_name", None),
        )
        if value
    )


def _persist_extracted_prices(
    db: Session,
    candidate: OvertureCandidate,
    provider: Provider,
    pages: list[dict],
    prices: list[dict],
    *,
    source_permission: SourcePermission,
) -> tuple[int, int]:
    created = 0
    already_present = 0
    for price in prices:
        group_name = price.get("option_group_name")
        option_group_id = _option_group_id(provider.id, candidate.branch_id, group_name)
        existing = (
            db.query(PricingEvidence)
            .filter(
                PricingEvidence.provider_id == provider.id,
                PricingEvidence.branch_id == candidate.branch_id,
                PricingEvidence.source_url == price["source_page_url"],
                PricingEvidence.service_name == price["service_name"],
                PricingEvidence.amount == price["amount"],
                PricingEvidence.option_group_id == option_group_id,
                PricingEvidence.review_status != "rejected",
            )
            .all()
        )
        if existing:
            already_present += 1
            continue
        db.add(PricingEvidence(
            provider_id=provider.id,
            branch_id=candidate.branch_id,
            service_category=price["service_category"],
            service_name=price["service_name"],
            option_group_id=option_group_id,
            option_group_name=group_name,
            fee_type=price["fee_type"],
            amount=price["amount"],
            amount_upper=price["amount_upper"],
            currency="GBP",
            price_basis=price["price_basis"],
            includes=price["includes"],
            excludes=price["excludes"],
            applicability={
                "overture_candidate_id": candidate.id,
                "gers_id": candidate.gers_id,
            },
            source_name=provider.display_name or provider.trading_name,
            source_url=price["source_page_url"],
            source_rights_basis=(
                f"{source_permission.permission_basis} "
                "A short source quotation and source link are retained for reviewer verification."
            ),
            source_permission_id=source_permission.id,
            source_retrieved_at=_now(),
            evidence_sha256=price["source_page_sha256"],
            evidence_excerpt=price["source_quote"],
            evidence_payload={
                "provenance": {
                    "extraction_method": "deterministic_rules",
                    "verification_status": "unverified",
                    "label": "Rule-extracted \u00b7 Not verified",
                    "parser_version": "deterministic-price-parser-v1",
                    "overture_candidate_id": candidate.id,
                    "gers_id": candidate.gers_id,
                    "source_permission_id": source_permission.id,
                    "source_page_title": next(
                        (page["title"] for page in pages
                         if page["url"] == price["source_page_url"]
                         and page.get("source_page_number") == price["source_page_number"]), ""
                    ),
                    "source_format": price["source_format"],
                    "source_page_number": price["source_page_number"],
                    "extraction_confidence": price["confidence"],
                    "source_page_sha256": price["source_page_sha256"],
                },
            },
            review_status="pending",
        ))
        created += 1
    return created, already_present


@celery_app.task(
    bind=True,
    name="everguide.enrichment.extract_overture_candidate_prices",
    max_retries=2,
)
def enrich_overture_candidate_prices(self, candidate_id: int):
    """Extract explicit website prices into pending, visibly-unverified evidence."""
    if not settings.price_enrichment_enabled:
        return {"status": "disabled", "candidate_id": candidate_id}
    db = SessionLocal()
    try:
        candidate = db.get(OvertureCandidate, candidate_id)
        if not candidate:
            return {"status": "missing", "candidate_id": candidate_id}
        provider = db.get(Provider, candidate.provider_id) if candidate.provider_id else None
        if not provider or provider.provider_type not in set(OVERTURE_IMPORT_SERVICE_TYPES.values()):
            _set_candidate_pricing_status(
                db, candidate, "awaiting_provider",
                extra={"last_error": "The Overture candidate needs a linked funeral-director record before price evidence can be stored."},
            )
            db.commit()
            return {"status": "awaiting_provider", "candidate_id": candidate_id}
        evidence = dict(candidate.first_party_evidence or {})
        marker = dict(evidence.get(PRICING_ENRICHMENT_KEY) or {})
        if marker.get("status") not in {"queued", "failed"}:
            return {"status": "not_queued", "candidate_id": candidate_id, "queue_status": marker.get("status")}
        attempt_count = int(marker.get("attempt_count") or 0) + 1
        _set_candidate_pricing_status(
            db, candidate, "in_progress",
            extra={"attempt_count": attempt_count, "started_at": _now().isoformat(), "last_error": None},
        )
        db.commit()

        raw = dict(candidate.raw_data or {})
        first_party_url = evidence.get("website_url")
        if not first_party_url:
            _set_candidate_pricing_status(
                db, candidate, "needs_source",
                extra={"last_error": "No verified provider-owned website URL is available; no price source was fetched."},
            )
            db.commit()
            return {"status": "needs_source", "candidate_id": candidate_id}

        # Re-check the Overture-supplied source and robots/HTTPS restrictions
        # immediately before price-page collection; a prior check is not permanent.
        verification = verify_candidate(str(first_party_url))
        extracted = (verification or {}).get("extracted_data")
        if (verification or {}).get("status") != "reachable" or not (verification or {}).get("robots_allowed"):
            _set_candidate_pricing_status(
                db, candidate, "blocked",
                extra={"last_error": "The provider website failed its current HTTPS, robots or reachability check."},
            )
            db.commit()
            return {"status": "blocked", "candidate_id": candidate_id}
        manual_approval = dict(evidence.get("enrichment_approval") or {})
        manually_approved = manual_approval.get("status") == "approved_by_reviewer"
        if _verified_site_has_explicit_branch_conflict(candidate, extracted) and not manually_approved:
            _set_candidate_pricing_status(
                db, candidate, "blocked",
                extra={"last_error": "The current website shows an explicit identity or location conflict at the Overture branch."},
            )
            db.commit()
            return {"status": "blocked", "candidate_id": candidate_id}

        source_permission, source_blocked = _overture_source_permission(
            db, provider, candidate, str(first_party_url)
        )
        if source_blocked:
            _set_candidate_pricing_status(
                db, candidate, "blocked",
                extra={"last_error": "A reviewer has blocked this source; Overture's default permission does not override an explicit block."},
            )
            db.commit()
            return {"status": "blocked", "candidate_id": candidate_id}

        source_url = str((verification or {}).get("final_url") or first_party_url)
        fetch_diagnostics = {}
        pages = _fetch_price_pages(
            source_url, settings.price_enrichment_max_pages, diagnostics=fetch_diagnostics,
        )
        if not pages:
            skipped = fetch_diagnostics.get("pages_skipped") or {}
            if (fetch_diagnostics.get("access_challenge_pages")
                    or skipped.get("robots_disallowed")
                    or skipped.get("http_401") or skipped.get("http_403")):
                _set_candidate_pricing_status(
                    db, candidate, "blocked",
                    extra={"pages_checked": fetch_diagnostics.get("pages_fetched", 0),
                           "fetch_diagnostics": fetch_diagnostics,
                           "last_error": "The source blocked automated access or robots.txt disallowed the requested pages; no access controls were bypassed."},
                )
                db.commit()
                return {"status": "blocked", "candidate_id": candidate_id,
                        "pages_checked": fetch_diagnostics.get("pages_fetched", 0)}
            if (skipped.get("response_size_limit") or skipped.get("redirect")
                    or any(key.startswith("http_") for key in skipped)):
                _set_candidate_pricing_status(
                    db, candidate, "failed",
                    extra={"pages_checked": fetch_diagnostics.get("pages_fetched", 0),
                           "fetch_diagnostics": fetch_diagnostics,
                           "last_error": "Some candidate pages could not be inspected within the bounded fetch policy; see fetch diagnostics."},
                )
                db.commit()
                return {"status": "failed", "candidate_id": candidate_id,
                        "pages_checked": fetch_diagnostics.get("pages_fetched", 0)}
            _set_candidate_pricing_status(
                db, candidate, "no_prices_found",
                extra={"pages_checked": fetch_diagnostics.get("pages_fetched", 0),
                       "fetch_diagnostics": fetch_diagnostics,
                       "last_error": "No explicit GBP prices were found on the fetched same-site HTML or text-based PDF pages."},
            )
            db.commit()
            return {"status": "no_prices_found", "candidate_id": candidate_id,
                    "pages_checked": fetch_diagnostics.get("pages_fetched", 0)}

        payload = _extract_rule_based_prices(pages)
        prices = _validate_extracted_prices(payload, pages)
        created, already_present = _persist_extracted_prices(
            db, candidate, provider, pages, prices,
            source_permission=source_permission,
        )
        _set_candidate_pricing_status(
            db, candidate, "completed" if prices else "no_prices_found",
            extra={
                "completed_at": _now().isoformat(),
                "pages_checked": fetch_diagnostics.get("pages_fetched", 0),
                "pages_with_explicit_prices": len(pages),
                "fetch_diagnostics": fetch_diagnostics,
                "prices_extracted": len(prices),
                "price_records_created": created,
                "price_records_already_present": already_present,
                "extraction_method": "deterministic_rules",
                "parser_version": "deterministic-price-parser-v1",
                "last_error": None if prices else "No explicit GBP prices could be verified in the fetched page quotations.",
            },
        )
        db.add(AuditEvent(
            entity_type="overture_candidate",
            entity_id=candidate.id,
            action="pricing_enrichment_completed",
            detail={
                "provider_id": provider.id,
                "branch_id": candidate.branch_id,
                "pages_checked": len(pages),
                "prices_extracted": len(prices),
                "price_records_created": created,
                "price_records_already_present": already_present,
                "verification_status": "unverified",
                "extraction_method": "deterministic_rules",
            },
        ))
        db.commit()
        return {
            "status": "completed" if prices else "no_prices_found",
            "candidate_id": candidate_id,
            "pages_checked": fetch_diagnostics.get("pages_fetched", 0),
            "prices_extracted": len(prices),
            "price_records_created": created,
        }
    except Exception as exc:
        db.rollback()
        candidate = db.get(OvertureCandidate, candidate_id)
        if candidate:
            next_status = "failed" if self.request.retries >= self.max_retries else "queued"
            _set_candidate_pricing_status(
                db, candidate, next_status,
                extra={"last_error": f"{type(exc).__name__}: {str(exc)[:500]}"},
            )
            db.commit()
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
        raise
    finally:
        db.close()
