"""Conservative, explainable triage for Companies House SIC 96030 candidates.

This is a screening aid only. It does not verify operating status or publish providers.
"""
from datetime import datetime, timezone

DIRECTORY_TERMS = ("directory", "funeral finder", "compare funeral", "comparison", "marketplace", "listing portal")
RELATED_TERMS = ("crematorium", "crematoria", "cemetery", "cemeteries", "burial ground", "memorial park", "borough council", "district council", "city council", "parish council")
GROUP_TERMS = ("holdings", "holding company", "investments", "group plc")
FUNERAL_TERMS = ("funeral director", "funeral directors", "funeral service", "funeral services", "funeralcare", "undertaker", "undertakers", "funerals", "funeral home")

def classify_name(name: str):
    value = (name or "").casefold()
    if any(term in value for term in DIRECTORY_TERMS):
        return "directory_or_comparison", "high", "Company name contains a directory/comparison indicator; verify website before exclusion."
    if any(term in value for term in RELATED_TERMS):
        return "related_service", "medium", "Company name suggests a cemetery, crematorium or public authority; verify actual activity."
    if any(term in value for term in GROUP_TERMS):
        return "holding_or_group", "medium", "Company name suggests a holding or group entity; identify operating subsidiaries and branches."
    if any(term in value for term in FUNERAL_TERMS):
        return "likely_funeral_director", "medium", "Company name contains funeral-sector wording; operating funeral-director activity is not yet verified."
    return "uncertain", "low", "Company name alone does not establish the operating activity."

def run_classification(db):
    from app.models import CompaniesHouseCandidate, AuditEvent
    candidates = db.query(CompaniesHouseCandidate).filter(CompaniesHouseCandidate.company_status == "active").all()
    counts = {}
    now = datetime.now(timezone.utc)
    for item in candidates:
        category, confidence, reason = classify_name(item.company_name)
        item.classification = category
        item.classification_confidence = confidence
        item.classification_reason = reason
        item.classified_at = now
        # This is triage only. Every record remains a candidate and none is published.
        item.review_status = "candidate"
        counts[category] = counts.get(category, 0) + 1
    db.add(AuditEvent(entity_type="companies_house_candidates", entity_id=0, action="bulk_classification_completed", detail={"active_candidates": len(candidates), "counts": counts, "method": "company_name_rules_v1", "publication_changes": 0}, actor="system-classifier"))
    db.commit()
    return {"classified": len(candidates), "counts": counts, "method": "company_name_rules_v1", "published": 0}

def classification_summary(db):
    from sqlalchemy import func
    from app.models import CompaniesHouseCandidate
    rows = db.query(CompaniesHouseCandidate.classification, func.count(CompaniesHouseCandidate.id)).filter(CompaniesHouseCandidate.company_status == "active").group_by(CompaniesHouseCandidate.classification).all()
    return {"total_active": sum(count for _, count in rows), "counts": {key or "unclassified": count for key, count in rows}}
