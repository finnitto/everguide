"""Idempotent, review-only identity and branch assessment helpers."""
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
from difflib import SequenceMatcher
from sqlalchemy import func
from app.models import (CompaniesHouseCandidate, CompanyWebsiteCandidate,
    CompanyIdentityReview, CompanyBranchProposal, AuditEvent)

DIRECTORY_DOMAINS = {
    "thebusinesslisting.co.uk", "ashesregister.com", "funeralguide.co.uk",
    "funeral-directory.co.uk", "funeralfinder.org", "localfuneral.co.uk",
    "funeralchoice.co.uk", "yourfuneralchoice.com", "192.com",
}
NON_PROVIDER_TERMS = (
    "pet cremation", "pet crematorium", "animal cremation", "funeral plan",
    "funeral plans", "pre-paid funeral", "prepaid funeral", "comparison",
    "directory",
)
ADJACENT_SERVICE_IDENTITY_TERMS = (
    "cemetery", "cemeteries", "cemetary", "cemetaries", "crematorium",
    "crematoria", "burial ground", "council", "celebrant", "memorial",
    "headstone", "monumental mason", "stonemason", "stone mason",
)
NAME_MAX_LENGTH = 240

def _clean_business_name(*values):
    """Return a concise identity label, never a paragraph or page description."""
    for value in values:
        if not isinstance(value, str):
            continue
        candidate = " ".join(value.split()).strip(" |–—-•·")
        if not candidate or len(candidate) > NAME_MAX_LENGTH:
            continue
        words = candidate.split()
        lowered = candidate.lower()
        if len(words) > 12 or len(candidate) > 100:
            continue
        if any(term in lowered for term in (" is a ", " are a ", " providing ", " we offer ", " serving ", "specialise in", "specialize in")):
            continue
        if candidate.startswith(("http://", "https://", "www.")):
            continue
        return candidate
    return None

def _non_provider_signal(lead, data):
    host = domain(lead.final_url or lead.result_url)
    identity_text = " ".join(
        str(data.get(k) or "")
        for k in ("name", "type", "category", "business_type")
    )
    identity_text = f"{identity_text} {lead.page_title or ''} {lead.result_title or ''} {host}".lower()
    # Strong identity/category signals for adjacent services are checked against
    # the candidate identity and page title, not promotional body copy. This
    # avoids excluding a genuine funeral director merely for mentioning a
    # memorial service in a paragraph.
    if any(term in identity_text for term in ADJACENT_SERVICE_IDENTITY_TERMS):
        return True
    context_text = f"{identity_text} {data.get('description') or ''}".lower()
    return any(term in context_text for term in NON_PROVIDER_TERMS)
# Postcode areas wholly/overwhelmingly associated with Scotland, Wales or NI,
# plus cross-border/ambiguous areas that must be reviewed rather than inferred.
ENGLAND_POSTCODE_AREAS = set("AL B BA BB BD BH BL BN BR BS CA CB CM CO CR CT CV CW DA DE DH DL DN DT DY E EC EN EX FY GL GU HA HD HG HP HR HU HX IG IP KT L LA LE LN LS LU M ME MK N NE NG NN NR NW OL OX PE PL PO PR RG RH RM S SE SG SK SL SM SN SO SP SR SS ST SW TA TF TN TQ TR TS TW UB W WC WD WF WN WR WS WV YO".split())
AMBIGUOUS_OR_NON_ENGLAND_AREAS = set("AB DD DG EH FK G HS IV KA KW KY ML PA PH TD ZE CF LD LL NP SA BT CH SY WA".split())
UK_POSTCODE_RE = re.compile(r"^(GIR0AA|[A-Z]{1,2}[0-9][A-Z0-9]?\s*[0-9][A-Z]{2})$", re.I)

def domain(url):
    return (urlsplit(url or "").hostname or "").lower().removeprefix("www.")

def is_directory(lead):
    host = domain(lead.final_url or lead.result_url)
    return any(host == d or host.endswith("." + d) for d in DIRECTORY_DOMAINS)

def _normalise_name(value):
    words = re.findall(r"[a-z0-9]+", str(value or "").lower())
    ignored = {"limited", "ltd", "plc", "the", "and", "funeral", "director", "directors", "services", "service", "son"}
    return {w for w in words if w not in ignored and len(w) > 1}

def _name_relationship(company_name, observed_name):
    a, b = _normalise_name(company_name), _normalise_name(observed_name)
    if not a or not b:
        return 0.0
    shared = a & b
    # Fuzzy character similarity alone can produce misleading matches between
    # unrelated funeral-sector names. Require at least one meaningful token
    # overlap before allowing the fuzzy component to raise the relationship.
    if not shared:
        return 0.0
    overlap = len(shared) / max(1, len(a | b))
    compact_a = re.sub(r"[^a-z0-9]", "", str(company_name or "").lower())
    compact_b = re.sub(r"[^a-z0-9]", "", str(observed_name or "").lower())
    fuzzy = SequenceMatcher(None, compact_a, compact_b).ratio() * 0.65
    return max(overlap, fuzzy)

def confidence(lead, company=None):
    """Identity evidence score for triage; never a probability or approval."""
    data = lead.extracted_data or {}
    score = min(max(float(lead.match_score or 0), 0.0), 1.0) * 0.10
    if lead.http_status == 200 and lead.robots_allowed is True:
        score += 0.05
    if lead.verification_status == "identity_signals_found":
        score += 0.10
    structured = str(data.get("source_type") or "").lower().startswith("schema_org_")
    if structured:
        score += 0.05
    host = domain(lead.final_url or lead.result_url)
    declared_host = domain(data.get("website"))
    official = bool(host and declared_host and host == declared_host and not is_directory(lead))
    if official:
        score += 0.10
    if company is not None:
        observed = data.get("name") or lead.page_title or lead.result_title
        relation = _name_relationship(company.company_name, observed)
        score += min(relation, 1.0) * 0.35
        # A company-name mismatch is a strong warning; unrelated directory
        # profiles must not inherit the candidate company's identity.
        if relation < 0.20:
            score = min(score, 0.20)
    if is_directory(lead) or _non_provider_signal(lead, data):
        return round(min(score, 0.10), 3)
    return round(min(score, 0.75), 3)

def england_address(data):
    """Require positive England evidence; ambiguous and devolved-nation areas are excluded."""
    country = str(data.get("country") or "").strip().lower()
    if country in {"scotland", "wales", "northern ireland", "ni"}:
        return False, "explicit_non_england"
    postcode = re.sub(r"\s+", "", str(data.get("postcode") or "").upper())
    if not UK_POSTCODE_RE.match(postcode):
        return False, "postcode_missing_or_invalid"
    m = re.match(r"([A-Z]{1,2})", postcode)
    area = m.group(1) if m else ""
    if area in AMBIGUOUS_OR_NON_ENGLAND_AREAS:
        return False, "non_england_or_ambiguous_postcode_area"
    if country in {"england", "gb-eng", "eng"}:
        return True, "explicit_england_and_postcode"
    if area in ENGLAND_POSTCODE_AREAS:
        return True, "english_postcode_area_inferred"
    return False, "geography_unconfirmed"

def branch_eligible(lead, data):
    complete = bool(data.get("has_complete_branch_address") and data.get("street") and data.get("town") and data.get("postcode"))
    country_ok, geo_reason = england_address(data)
    structured = str(data.get("source_type") or "").lower().startswith("schema_org_")
    source_host = domain(lead.final_url or lead.result_url)
    declared_site_host = domain(data.get("website"))
    # A branch address is eligible only when the page carrying the structured
    # data is on the same domain as the business website declared in that data.
    official_source = bool(source_host and declared_site_host and source_host == declared_site_host and not is_directory(lead))
    non_provider = _non_provider_signal(lead, data)
    if non_provider:
        geo_reason = "adjacent_sector_or_non_provider_signal"
    return complete and country_ok and structured and official_source and not non_provider, geo_reason

def _normalise_postcode(value):
    return re.sub(r"\s+", "", str(value or "").upper())


def _normalise_address_text(value):
    """Normalise address punctuation and common UK road-type abbreviations."""
    words = re.findall(r"[a-z0-9]+", str(value or "").lower())
    if not words:
        return ""
    suffixes = {
        "rd": "road", "st": "street", "ave": "avenue", "av": "avenue",
        "ln": "lane", "dr": "drive", "cres": "crescent", "ct": "court",
        "cl": "close", "gdns": "gardens", "sq": "square", "ter": "terrace",
    }
    words[-1] = suffixes.get(words[-1], words[-1])
    return " ".join(words)


def _overture_address_matches(candidate, branch_data):
    """Require street, locality and postcode agreement against Overture address data.

    Freeform addresses are only usable when the first comma-delimited component
    is an exact street-line match. Incomplete or differently formatted addresses
    fail closed rather than falling back to postcode-only matching.
    """
    data = candidate.raw_data or {}
    addresses = data.get("addresses_json")
    if not isinstance(addresses, list) or not addresses:
        return None
    website_street = _normalise_address_text(branch_data.get("street"))
    website_town = _normalise_address_text(branch_data.get("town"))
    website_postcode = _normalise_postcode(branch_data.get("postcode"))
    if not all((website_street, website_town, website_postcode)):
        return None
    matches = []
    for address in addresses:
        if not isinstance(address, dict):
            continue
        street = next((address.get(key) for key in ("street", "street_address", "address_line_1")
                       if isinstance(address.get(key), str) and address.get(key).strip()), None)
        freeform = address.get("freeform")
        if not street and isinstance(freeform, str):
            street = freeform.split(",", 1)[0].strip()
        locality = next((address.get(key) for key in ("locality", "town", "city")
                         if isinstance(address.get(key), str) and address.get(key).strip()), None)
        postcode = address.get("postcode")
        if (_normalise_address_text(street) == website_street
                and _normalise_address_text(locality) == website_town
                and _normalise_postcode(postcode) == website_postcode):
            matches.append({
                "street": str(street).strip(),
                "locality": str(locality).strip(),
                "postcode": str(postcode).strip(),
            })
    return matches[0] if len(matches) == 1 else None


def matched_overture_company_link(db, company_id, branch_data):
    """Return one verified Overture link only when its branch address matches.

    A postcode match alone is insufficient. Street line, locality and postcode
    must all match one address on one uniquely linked Overture candidate.
    Ambiguity, missing address detail and unreviewed links return no match.
    """
    postcode_key = _normalise_postcode(branch_data.get("postcode"))
    if not postcode_key:
        return None
    from app.models import OvertureCandidate, OvertureCompanyLink
    rows = (
        db.query(OvertureCompanyLink, OvertureCandidate)
        .join(OvertureCandidate, OvertureCandidate.id == OvertureCompanyLink.overture_candidate_id)
        .filter(
            OvertureCompanyLink.companies_house_candidate_id == company_id,
            OvertureCompanyLink.status == "verified",
            OvertureCompanyLink.reviewed_at.isnot(None),
            OvertureCompanyLink.reviewed_by.isnot(None),
            OvertureCompanyLink.evidence_json.isnot(None),
            OvertureCompanyLink.evidence_json != {},
        )
        .all()
    )
    matches = []
    for link, candidate in rows:
        if _normalise_postcode(candidate.postcode) != postcode_key:
            continue
        address_match = _overture_address_matches(candidate, branch_data)
        if address_match:
            matches.append((link, candidate, address_match))
    return matches[0] if len(matches) == 1 else None


def process_company(db, company_id):
    company = db.get(CompaniesHouseCandidate, company_id)
    if not company or company.company_status != "active": return {"identity":0,"branch":0,"skipped":0}
    leads = (db.query(CompanyWebsiteCandidate)
        .filter(CompanyWebsiteCandidate.companies_house_candidate_id == company_id,
                CompanyWebsiteCandidate.verification_status != "auto_approved_published")
        .order_by(CompanyWebsiteCandidate.match_score.desc(), CompanyWebsiteCandidate.id.asc()).all())
    unique = {}
    for lead in leads:
        host = domain(lead.final_url or lead.result_url)
        if not host: continue
        if host not in unique or confidence(lead, company) > confidence(unique[host], company): unique[host] = lead
    ranked = sorted(unique.values(), key=lambda x:(confidence(x, company),x.match_score or 0), reverse=True)
    best = ranked[0] if ranked else None
    created_identity = created_branches = skipped = 0
    now = datetime.now(timezone.utc)
    if best:
        extracted = best.extracted_data or {}
        review = db.query(CompanyIdentityReview).filter_by(companies_house_candidate_id=company_id).first()
        if review is None:
            review = CompanyIdentityReview(companies_house_candidate_id=company_id,status="pending")
            db.add(review); created_identity = 1
        # Keep human decisions and notes intact; update only pending proposals.
        if review.status == "pending":
            review.suggested_trading_name = _clean_business_name(
                extracted.get("name"), best.page_title, best.result_title
            )
            review.suggested_website = best.final_url or best.result_url
            review.suggested_domain = domain(review.suggested_website)
            review.confidence = confidence(best, company)
            review.duplicate_leads_collapsed = max(0,len(leads)-len(unique))
            review.evidence = {"source_url":best.final_url or best.result_url,"search_title":best.result_title,
                "verification_status":best.verification_status,"http_status":best.http_status,
                "robots_allowed":best.robots_allowed,"extracted_fields":extracted,
                "lead_ids":[x.id for x in leads],"distinct_domains":len(unique),
                "same_domain_leads":{d:[x.id for x in leads if domain(x.final_url or x.result_url)==d] for d in unique},
                "assessment_version":"identity_rules_v3",
                "confidence_note":"Identity relationship triage score using Companies House name alignment and same-domain structured evidence; not a probability or approval.",
                "company_name_relationship":round(_name_relationship(company.company_name, extracted.get("name") or best.page_title or best.result_title),3),
                "official_domain_match":bool(domain(best.final_url or best.result_url) and domain(best.final_url or best.result_url)==domain(extracted.get("website"))),
                "name_rejected_as_description": bool(extracted.get("name") and not _clean_business_name(extracted.get("name")))}
            review.updated_at = now
    for lead in leads:
        data = lead.extracted_data or {}
        eligible, geo_reason = branch_eligible(lead,data)
        proposal = db.query(CompanyBranchProposal).filter_by(website_candidate_id=lead.id).first()
        overture_match = matched_overture_company_link(db, company_id, data) if eligible else None
        if eligible and overture_match is None:
            eligible = False
            geo_reason = "no_unique_verified_overture_branch_address_match"
        if not eligible:
            skipped += 1
            # Pending proposals are recalculated; never silently retain a proposal
            # that no longer passes the stricter rules. Human decisions are immutable.
            if proposal is not None and proposal.status == "pending":
                proposal.status = "needs_more_evidence"
                proposal.evidence = {**(proposal.evidence or {}), "reassessment_version":"identity_rules_v2",
                    "reassessment_outcome":"downgraded_pending_proposal", "reason":geo_reason}
                proposal.review_notes = (proposal.review_notes or "")
                proposal.updated_at = now
            continue
        link, overture_candidate, matched_address = overture_match
        if proposal is None:
            proposal=CompanyBranchProposal(
                companies_house_candidate_id=company_id,
                website_candidate_id=lead.id,
                overture_company_link_id=link.id,
                status="pending",
            )
            db.add(proposal); created_branches += 1
        if proposal.status == "pending":
            proposal.overture_company_link_id = link.id
            proposal.proposed_branch_name = _clean_business_name(data.get("name"), lead.page_title, lead.result_title)
            proposal.address_line = str(data.get("street"))[:500]
            proposal.town_city = str(data.get("town"))[:120]
            proposal.postcode = str(data.get("postcode"))[:12]
            # Telephone is always treated as text, preserving leading zeroes.
            phone = data.get("telephone")
            # Numeric JSON telephone values may already have lost leading zeroes
            # or precision (e.g. scientific notation); omit rather than corrupt.
            proposal.telephone = str(phone).strip()[:40] if isinstance(phone, str) and phone.strip() else None
            proposal.website = (lead.final_url or lead.result_url)[:1000]
            proposal.confidence = confidence(lead, company)
            proposal.evidence = {"source_url":lead.final_url or lead.result_url,"verification_status":lead.verification_status,
                "http_status":lead.http_status,"robots_allowed":lead.robots_allowed,"extracted_data":data,
                "registered_office_used_as_branch":False,
                "overture_company_link_id":link.id,
                "overture_candidate_id":overture_candidate.id,
                "overture_gers_id":overture_candidate.gers_id,
                "overture_candidate_postcode":overture_candidate.postcode,
                "branch_address_match":"exact_normalised_street_locality_postcode",\n                "overture_matched_address":matched_address,
                "source_domain":domain(lead.final_url or lead.result_url),
                "source_type":data.get("source_type"),"geography_assessment":geo_reason,
                "branch_eligibility_rule":"complete structured address; England-only postcode/country evidence; source page domain must match declared business website; non-directory domain; adjacent sectors excluded; exact Overture street, locality and postcode match",
                "assessment_version":"identity_rules_v3",
                "telephone_omitted_numeric_source": isinstance(data.get("telephone"), float)}
            proposal.updated_at=now
    # Collapse duplicate proposals for the same company and normalized address.
    # Keep every row and its evidence; mark later duplicates for review rather than deleting.
    proposals = (db.query(CompanyBranchProposal)
        .filter(CompanyBranchProposal.companies_house_candidate_id == company_id)
        .order_by(CompanyBranchProposal.id.asc()).all())
    seen_addresses = {}
    for item in proposals:
        key = (re.sub(r"[^a-z0-9]", "", str(item.postcode or "").lower()),
               re.sub(r"[^a-z0-9]", "", str(item.address_line or "").lower()),
               re.sub(r"[^a-z0-9]", "", str(item.town_city or "").lower()))
        if not any(key):
            continue
        if key in seen_addresses and item.status == "pending":
            canonical = seen_addresses[key]
            item.status = "needs_more_evidence"
            item.evidence = {**(item.evidence or {}), "assessment_version":"identity_rules_v3",
                "duplicate_of_proposal_id":canonical.id,
                "duplicate_reason":"Same company and normalized branch address; retained as supporting evidence."}
            item.updated_at = now
        else:
            seen_addresses[key] = item
    return {"identity":created_identity,"branch":created_branches,"skipped":skipped}
