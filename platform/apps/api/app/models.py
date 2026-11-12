from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Float, String, Text, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

def now_utc(): return datetime.now(timezone.utc)

class Provider(Base):
    __tablename__ = "providers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trading_name: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(240))
    registered_name: Mapped[str | None] = mapped_column(String(240))
    website: Mapped[str | None] = mapped_column(String(500))
    provider_type: Mapped[str] = mapped_column(String(40), default="funeral_director")
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    verification_status: Mapped[str] = mapped_column(String(30), default="unverified")
    quality_status: Mapped[str] = mapped_column(String(24), default="unassessed", index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    branches: Mapped[list["Branch"]] = relationship(back_populates="provider", cascade="all, delete-orphan")

class Branch(Base):
    __tablename__ = "branches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id", ondelete="CASCADE"), index=True)
    branch_name: Mapped[str] = mapped_column(String(240), nullable=False)
    address_line_1: Mapped[str] = mapped_column(String(240), nullable=False)
    address_line_2: Mapped[str | None] = mapped_column(String(240))
    town_city: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    county: Mapped[str | None] = mapped_column(String(120))
    postcode: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    telephone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(254))
    website: Mapped[str | None] = mapped_column(String(500))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    services: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    provider: Mapped[Provider] = relationship(back_populates="branches")

class SourceObservation(Base):
    __tablename__ = "source_observations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("providers.id", ondelete="SET NULL"), index=True)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id", ondelete="SET NULL"), index=True)
    source_type: Mapped[str] = mapped_column(String(60), nullable=False)
    source_name: Mapped[str] = mapped_column(String(240), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    confidence: Mapped[float | None] = mapped_column(Float)
    observed_data: Mapped[dict] = mapped_column(JSON, default=dict)
    review_status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    notes: Mapped[str | None] = mapped_column(Text)

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    actor: Mapped[str] = mapped_column(String(120), default="local-admin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

Index("ix_branches_location", Branch.town_city, Branch.postcode)


class DiscoveryRun(Base):
    __tablename__ = "discovery_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str | None] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    scope: Mapped[str] = mapped_column(String(40), default="england")
    source: Mapped[str] = mapped_column(String(60), default="google_places")
    locations_attempted: Mapped[int] = mapped_column(Integer, default=0)
    places_found: Mapped[int] = mapped_column(Integer, default=0)
    observations_created: Mapped[int] = mapped_column(Integer, default=0)
    duplicates_flagged: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class SourcePermission(Base):
    __tablename__ = "source_permissions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id", ondelete="CASCADE"), index=True)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    permission_status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    permission_basis: Mapped[str] = mapped_column(Text, nullable=False)
    permission_reference: Mapped[str | None] = mapped_column(String(500))
    approved_by: Mapped[str | None] = mapped_column(String(120))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

class WebsiteEvidenceCheck(Base):
    __tablename__ = "website_evidence_checks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_permission_id: Mapped[int] = mapped_column(ForeignKey("source_permissions.id", ondelete="CASCADE"), index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id", ondelete="CASCADE"), index=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    page_title: Mapped[str | None] = mapped_column(String(500))
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[str | None] = mapped_column(Text)


class WebsiteDiscoveryResult(Base):
    __tablename__ = "website_discovery_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    query_region: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    query_text: Mapped[str] = mapped_column(String(500), nullable=False)
    result_title: Mapped[str] = mapped_column(String(500), nullable=False)
    result_url: Mapped[str] = mapped_column(String(1000), nullable=False, index=True)
    result_domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    result_snippet: Mapped[str | None] = mapped_column(Text)
    source_provider: Mapped[str] = mapped_column(String(40), default="brave_search")
    status: Mapped[str] = mapped_column(String(80), default="candidate", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

class WebsiteVerification(Base):
    __tablename__ = "website_verifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("website_discovery_results.id", ondelete="CASCADE"), index=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    final_url: Mapped[str | None] = mapped_column(String(1000))
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(160))
    page_title: Mapped[str | None] = mapped_column(String(500))
    robots_allowed: Mapped[bool | None] = mapped_column(Boolean)
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[str | None] = mapped_column(Text)
    extracted_data: Mapped[dict | None] = mapped_column(JSON)


class WebsiteVerificationRun(Base):
    __tablename__ = "website_verification_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    requested_limit: Mapped[int] = mapped_column(Integer, default=50)
    total: Mapped[int] = mapped_column(Integer, default=0)
    checked: Mapped[int] = mapped_column(Integer, default=0)
    outcomes: Mapped[dict] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class ProviderQualityAction(Base):
    __tablename__ = "provider_quality_actions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id", ondelete="CASCADE"), index=True)
    action_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    proposed_value: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[str] = mapped_column(String(20), default="review")
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    decision_note: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[str | None] = mapped_column(String(120))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

class CompaniesHouseRun(Base):
    __tablename__ = "companies_house_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    sic_codes: Mapped[list] = mapped_column(JSON, default=list)
    total_results: Mapped[int] = mapped_column(Integer, default=0)
    imported: Mapped[int] = mapped_column(Integer, default=0)
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0)
    api_items_per_page: Mapped[int] = mapped_column(Integer, default=0)
    unique_companies_seen: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class CompaniesHouseCandidate(Base):
    __tablename__ = "companies_house_candidates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_number: Mapped[str] = mapped_column(String(16), index=True)
    company_name: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    company_status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    company_type: Mapped[str | None] = mapped_column(String(60))
    sic_codes: Mapped[list] = mapped_column(JSON, default=list)
    registered_office_address: Mapped[dict] = mapped_column(JSON, default=dict)
    date_of_creation: Mapped[str | None] = mapped_column(String(20))
    company_profile_url: Mapped[str | None] = mapped_column(String(500))
    source_run_id: Mapped[int | None] = mapped_column(ForeignKey("companies_house_runs.id", ondelete="SET NULL"), index=True)
    classification: Mapped[str] = mapped_column(String(40), default="unclassified", index=True)
    classification_reason: Mapped[str | None] = mapped_column(Text)
    classification_confidence: Mapped[str] = mapped_column(String(16), default="unassessed")
    classified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_status: Mapped[str] = mapped_column(String(24), default="candidate", index=True)
    raw_company_record: Mapped[dict] = mapped_column(JSON, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    profile_status: Mapped[str] = mapped_column(String(24), default="not_requested", index=True)
    profile_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    profile_error: Mapped[str | None] = mapped_column(Text)
    company_profile: Mapped[dict] = mapped_column(JSON, default=dict)
    previous_company_names: Mapped[list] = mapped_column(JSON, default=list)
    website_discovery_status: Mapped[str] = mapped_column(String(24), default="not_requested", index=True)
    website_discovery_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    website_discovery_error: Mapped[str | None] = mapped_column(Text)
    company_website_candidates: Mapped[list["CompanyWebsiteCandidate"]] = relationship(backref="companies_house_candidate", cascade="all, delete-orphan")


class CompanyWebsiteDiscoveryRun(Base):
    __tablename__ = "company_website_discovery_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    scope: Mapped[str] = mapped_column(String(24), default="england")
    include_uncertain: Mapped[bool] = mapped_column(Boolean, default=True)
    batch_size: Mapped[int] = mapped_column(Integer, default=25)
    total_candidates: Mapped[int] = mapped_column(Integer, default=0)
    processed_candidates: Mapped[int] = mapped_column(Integer, default=0)
    results_found: Mapped[int] = mapped_column(Integer, default=0)
    websites_checked: Mapped[int] = mapped_column(Integer, default=0)
    identity_signals: Mapped[int] = mapped_column(Integer, default=0)
    no_results: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class CompanyWebsiteCandidate(Base):
    __tablename__ = "company_website_candidates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    companies_house_candidate_id: Mapped[int] = mapped_column(ForeignKey("companies_house_candidates.id", ondelete="CASCADE"), index=True)
    discovery_run_id: Mapped[int] = mapped_column(ForeignKey("company_website_discovery_runs.id", ondelete="CASCADE"), index=True)
    result_title: Mapped[str] = mapped_column(String(500), nullable=False)
    result_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    result_domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    result_snippet: Mapped[str | None] = mapped_column(String(1500))
    search_provider: Mapped[str] = mapped_column(String(40), nullable=False)
    match_score: Mapped[float] = mapped_column(Float, default=0.0)
    verification_status: Mapped[str] = mapped_column(String(32), default="not_checked", index=True)
    final_url: Mapped[str | None] = mapped_column(String(1000))
    http_status: Mapped[int | None] = mapped_column(Integer)
    robots_allowed: Mapped[bool | None] = mapped_column(Boolean)
    page_title: Mapped[str | None] = mapped_column(String(500))
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    extracted_data: Mapped[dict | None] = mapped_column(JSON)
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CompanyIdentityReview(Base):
    __tablename__ = "company_identity_reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    companies_house_candidate_id: Mapped[int] = mapped_column(ForeignKey("companies_house_candidates.id", ondelete="CASCADE"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    suggested_trading_name: Mapped[str | None] = mapped_column(String(240))
    suggested_website: Mapped[str | None] = mapped_column(String(1000))
    suggested_domain: Mapped[str | None] = mapped_column(String(255), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    duplicate_leads_collapsed: Mapped[int] = mapped_column(Integer, default=0)
    review_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

class CompanyBranchProposal(Base):
    __tablename__ = "company_branch_proposals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    companies_house_candidate_id: Mapped[int] = mapped_column(ForeignKey("companies_house_candidates.id", ondelete="CASCADE"), index=True)
    website_candidate_id: Mapped[int] = mapped_column(ForeignKey("company_website_candidates.id", ondelete="CASCADE"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    proposed_branch_name: Mapped[str | None] = mapped_column(String(240))
    address_line: Mapped[str | None] = mapped_column(String(500))
    town_city: Mapped[str | None] = mapped_column(String(120))
    postcode: Mapped[str | None] = mapped_column(String(12), index=True)
    telephone: Mapped[str | None] = mapped_column(String(40))
    website: Mapped[str | None] = mapped_column(String(1000))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    review_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class IdentityAssessmentRun(Base):
    __tablename__ = "identity_assessment_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    total_companies: Mapped[int] = mapped_column(Integer, default=0)
    processed_companies: Mapped[int] = mapped_column(Integer, default=0)
    identity_reviews_created: Mapped[int] = mapped_column(Integer, default=0)
    branch_proposals_created: Mapped[int] = mapped_column(Integer, default=0)
    branch_evidence_skipped: Mapped[int] = mapped_column(Integer, default=0)
    last_company_candidate_id: Mapped[int] = mapped_column(Integer, default=0)
    celery_task_id: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
