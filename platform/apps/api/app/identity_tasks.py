"""Chunked, resumable Overture-provenance-scoped identity assessment."""
from datetime import datetime, timezone

from sqlalchemy import distinct

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models import (
    IdentityAssessmentRun,
    CompaniesHouseCandidate,
    CompanyWebsiteCandidate,
    OvertureCompanyLink,
    AuditEvent,
)
from app.identity_assessment import process_company

BATCH_SIZE = 25


def _verified_link(link) -> bool:
    return bool(
        link
        and link.status == "verified"
        and link.reviewed_at is not None
        and (link.reviewed_by or "").strip()
        and isinstance(link.evidence_json, dict)
        and link.evidence_json
    )


def verified_overture_company_query(db):
    """Return active CH candidates with a formally reviewed Overture link."""
    return (
        db.query(CompaniesHouseCandidate.id)
        .join(
            OvertureCompanyLink,
            OvertureCompanyLink.companies_house_candidate_id == CompaniesHouseCandidate.id,
        )
        .filter(
            OvertureCompanyLink.status == "verified",
            OvertureCompanyLink.reviewed_at.isnot(None),
            OvertureCompanyLink.reviewed_by.isnot(None),
            OvertureCompanyLink.evidence_json.isnot(None),
            OvertureCompanyLink.evidence_json != {},
            CompaniesHouseCandidate.company_status == "active",
        )
    )


def _company_has_verified_overture_link(db, company_id: int) -> bool:
    link = (
        db.query(OvertureCompanyLink)
        .filter(
            OvertureCompanyLink.companies_house_candidate_id == company_id,
            OvertureCompanyLink.status == "verified",
        )
        .first()
    )
    return _verified_link(link)


@celery_app.task(name="everguide.identity_assessment.run", bind=True, acks_late=True)
def run_identity_assessment(self, run_id: int):
    db = SessionLocal()
    try:
        run = db.get(IdentityAssessmentRun, run_id)
        if not run:
            return {"status": "missing", "run_id": run_id}
        if run.status == "completed":
            return {"status": "completed", "run_id": run_id}

        run.status = "running"
        run.started_at = run.started_at or datetime.now(timezone.utc)
        run.celery_task_id = self.request.id
        db.commit()

        while True:
            eligible_ids = verified_overture_company_query(db).subquery()
            ids = [
                row[0]
                for row in (
                    db.query(distinct(CompanyWebsiteCandidate.companies_house_candidate_id))
                    .join(
                        eligible_ids,
                        eligible_ids.c.id == CompanyWebsiteCandidate.companies_house_candidate_id,
                    )
                    .filter(
                        CompanyWebsiteCandidate.companies_house_candidate_id > run.last_company_candidate_id,
                        CompanyWebsiteCandidate.verification_status != "auto_approved_published",
                    )
                    .order_by(CompanyWebsiteCandidate.companies_house_candidate_id)
                    .limit(BATCH_SIZE)
                    .all()
                )
            ]
            if not ids:
                run.status = "completed_with_errors" if run.error_message else "completed"
                run.completed_at = datetime.now(timezone.utc)
                db.add(
                    AuditEvent(
                        entity_type="identity_assessment_run",
                        entity_id=run.id,
                        action="completed",
                        detail={
                            "processed_companies": run.processed_companies,
                            "identity_reviews_created": run.identity_reviews_created,
                            "branch_proposals_created": run.branch_proposals_created,
                            "branch_evidence_skipped": run.branch_evidence_skipped,
                            "provenance_scope": "verified_overture_company_links_only",
                        },
                    )
                )
                db.commit()
                break

            for company_id in ids:
                try:
                    # Re-check provenance at the write boundary; links may have changed
                    # after the batch was selected.
                    if not _company_has_verified_overture_link(db, company_id):
                        run.processed_companies += 1
                        run.last_company_candidate_id = company_id
                        db.add(
                            AuditEvent(
                                entity_type="identity_assessment_company",
                                entity_id=company_id,
                                action="assessment_skipped_unverified_overture_provenance",
                                detail={"run_id": run_id},
                            )
                        )
                        db.commit()
                        continue

                    with db.begin_nested():
                        result = process_company(db, company_id)
                    run.identity_reviews_created += result["identity"]
                    run.branch_proposals_created += result["branch"]
                    run.branch_evidence_skipped += result["skipped"]
                except Exception as company_error:
                    db.rollback()
                    run = db.get(IdentityAssessmentRun, run_id)
                    run.error_message = f"Company candidate {company_id}: {str(company_error)[:1500]}"
                    db.add(
                        AuditEvent(
                            entity_type="identity_assessment_company",
                            entity_id=company_id,
                            action="assessment_company_failed",
                            detail={"run_id": run_id, "error": str(company_error)[:1500]},
                        )
                    )
                run.processed_companies += 1
                run.last_company_candidate_id = company_id
                db.commit()

        return {
            "status": run.status,
            "run_id": run.id,
            "processed_companies": run.processed_companies,
        }
    except Exception as exc:
        db.rollback()
        run = db.get(IdentityAssessmentRun, run_id)
        if run:
            run.status = "failed"
            run.error_message = str(exc)[:2000]
            db.add(
                AuditEvent(
                    entity_type="identity_assessment_run",
                    entity_id=run.id,
                    action="failed",
                    detail={"error": run.error_message},
                )
            )
            db.commit()
        raise
    finally:
        db.close()
