"""Idempotent, review-only identity and branch assessment helpers."""
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
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
    "directory", "cemetery", "crematorium", "burial ground", "council",
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
    text = " ".join(str(data.get(k) or "") for k in ("name", "description", "type", "category"))
    text = f"{text} {lead.page_title or ''} {lead.result_title or ''}".lower()
    return any(term in text or term in host for term in NON_PROVIDER_TERMS)
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

def confidence(lead):
    """Conservative review-priority score, not a probability of provider identity.

    Search relevance is deliberately not treated as identity proof. A reachable
    page and extracted structured identity add limited evidence; directories and
    adjacent sectors are capped at a low score.
    """
    score = min(max(float(lead.match_score or 0), 0.0), 1.0) * 0.35
    if lead.http_status == 200 and lead.robots_allowed is True:
        score += 0.15
    if lead.verification_status == "identity_signals_found":
        score += 0.15
    data = lead.extracted_data or {}
    if str(data.get("source_type") or "").lower().startswith("schema_org_"):
        score += 0.10
    if is_directory(lead) or _non_provider_signal(lead, data):
        return min(score, 0.20)
    # Scores are triage aids only; no website candidate can reach 100% identity.
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

def process_company(db, company_id):
    company = db.get(CompaniesHouseCandidate, company_id)
    if not company or company.company_status != "active": return {"identity":0,"branch":0,"skipped":0}
    leads = (db.query(CompanyWebsiteCandidate)
        .filter(CompanyWebsiteCandidate.companies_house_candidate_id == company_id)
        .order_by(CompanyWebsiteCandidate.match_score.desc(), CompanyWebsiteCandidate.id.asc()).all())
    unique = {}
    for lead in leads:
        host = domain(lead.final_url or lead.result_url)
        if not host: continue
        if host not in unique or confidence(lead) > confidence(unique[host]): unique[host] = lead
    ranked = sorted(unique.values(), key=lambda x:(confidence(x),x.match_score or 0), reverse=True)
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
            review.confidence = confidence(best)
            review.duplicate_leads_collapsed = max(0,len(leads)-len(unique))
            review.evidence = {"source_url":best.final_url or best.result_url,"search_title":best.result_title,
                "verification_status":best.verification_status,"http_status":best.http_status,
                "robots_allowed":best.robots_allowed,"extracted_fields":extracted,
                "lead_ids":[x.id for x in leads],"distinct_domains":len(unique),
                "same_domain_leads":{d:[x.id for x in leads if domain(x.final_url or x.result_url)==d] for d in unique},
                "assessment_version":"identity_rules_v2",
                "confidence_note":"Conservative evidence-priority score; not a probability or proof of funeral-director identity.",
                "name_rejected_as_description": bool(extracted.get("name") and not _clean_business_name(extracted.get("name")))}
            review.updated_at = now
    for lead in leads:
        data = lead.extracted_data or {}
        eligible, geo_reason = branch_eligible(lead,data)
        proposal = db.query(CompanyBranchProposal).filter_by(website_candidate_id=lead.id).first()
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
        if proposal is None:
            proposal=CompanyBranchProposal(companies_house_candidate_id=company_id,website_candidate_id=lead.id,status="pending")
            db.add(proposal); created_branches += 1
        if proposal.status == "pending":
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
            proposal.confidence = confidence(lead)
            proposal.evidence = {"source_url":lead.final_url or lead.result_url,"verification_status":lead.verification_status,
                "http_status":lead.http_status,"robots_allowed":lead.robots_allowed,"extracted_data":data,
                "registered_office_used_as_branch":False,"source_domain":domain(lead.final_url or lead.result_url),
                "source_type":data.get("source_type"),"geography_assessment":geo_reason,
                "branch_eligibility_rule":"complete structured address; England-only postcode/country evidence; source page domain must match declared business website; non-directory domain; adjacent sectors excluded",
                "assessment_version":"identity_rules_v2",
                "telephone_omitted_numeric_source": isinstance(data.get("telephone"), float)}
            proposal.updated_at=now
    return {"identity":created_identity,"branch":created_branches,"skipped":skipped}
