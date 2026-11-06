from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Float, String, Text, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

def now_utc(): return datetime.now(timezone.utc)

class Provider(Base):
    __tablename__ = "providers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trading_name: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    registered_name: Mapped[str | None] = mapped_column(String(240))
    website: Mapped[str | None] = mapped_column(String(500))
    provider_type: Mapped[str] = mapped_column(String(40), default="funeral_director")
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    verification_status: Mapped[str] = mapped_column(String(30), default="unverified")
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
