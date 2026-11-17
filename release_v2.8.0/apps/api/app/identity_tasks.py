"""Chunked, resumable background identity and branch assessment."""
from datetime import datetime, timezone
from app.celery_app import celery_app
from app.database import SessionLocal
from app.models import IdentityAssessmentRun, CompaniesHouseCandidate, CompanyWebsiteCandidate, AuditEvent
from app.identity_assessment import process_company

BATCH_SIZE = 25

@celery_app.task(name="everguide.identity_assessment.run", bind=True, acks_late=True)
def run_identity_assessment(self, run_id: int):
    db = SessionLocal()
    try:
        run = db.get(IdentityAssessmentRun, run_id)
        if not run:
            return {"status":"missing","run_id":run_id}
        if run.status == "completed":
            return {"status":"completed","run_id":run_id}
        run.status = "running"
        run.started_at = run.started_at or datetime.now(timezone.utc)
        run.celery_task_id = self.request.id
        db.commit()
        while True:
            ids = [r[0] for r in db.query(CompanyWebsiteCandidate.companies_house_candidate_id)
                .join(CompaniesHouseCandidate, CompaniesHouseCandidate.id == CompanyWebsiteCandidate.companies_house_candidate_id)
                .filter(CompaniesHouseCandidate.id > run.last_company_candidate_id,
                        CompaniesHouseCandidate.company_status == "active",
                        CompanyWebsiteCandidate.verification_status != "auto_approved_published")
                .distinct().order_by(CompanyWebsiteCandidate.companies_house_candidate_id).limit(BATCH_SIZE).all()]
            if not ids:
                run.status="completed_with_errors" if run.error_message else "completed"
                run.completed_at=datetime.now(timezone.utc)
                db.add(AuditEvent(entity_type="identity_assessment_run",entity_id=run.id,action="completed",
                    detail={"processed_companies":run.processed_companies,"identity_reviews_created":run.identity_reviews_created,
                            "branch_proposals_created":run.branch_proposals_created,"branch_evidence_skipped":run.branch_evidence_skipped}))
                db.commit(); break
            for company_id in ids:
                try:
                    # A malformed source record must not abort the entire England-wide
                    # assessment. The savepoint rolls back only this company's writes.
                    with db.begin_nested():
                        result=process_company(db,company_id)
                    run.identity_reviews_created += result["identity"]
                    run.branch_proposals_created += result["branch"]
                    run.branch_evidence_skipped += result["skipped"]
                except Exception as company_error:
                    db.rollback()
                    run = db.get(IdentityAssessmentRun, run_id)
                    run.error_message = f"Company candidate {company_id}: {str(company_error)[:1500]}"
                    db.add(AuditEvent(entity_type="identity_assessment_company",entity_id=company_id,
                        action="assessment_company_failed",detail={"run_id":run_id,"error":str(company_error)[:1500]}))
                run.processed_companies += 1
                run.last_company_candidate_id=company_id
                db.commit()
        return {"status":run.status,"run_id":run.id,"processed_companies":run.processed_companies}
    except Exception as exc:
        db.rollback()
        run=db.get(IdentityAssessmentRun,run_id)
        if run:
            run.status="failed"; run.error_message=str(exc)[:2000]
            db.add(AuditEvent(entity_type="identity_assessment_run",entity_id=run.id,action="failed",detail={"error":run.error_message}))
            db.commit()
        raise
    finally:
        db.close()
