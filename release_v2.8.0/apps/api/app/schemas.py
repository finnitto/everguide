from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

class BranchInput(BaseModel):
    branch_name: str = Field(min_length=1, max_length=240)
    address_line_1: str = Field(min_length=1, max_length=240)
    address_line_2: str | None = None
    town_city: str = Field(min_length=1, max_length=120)
    county: str | None = None
    postcode: str = Field(min_length=2, max_length=12)
    telephone: str | None = None
    email: str | None = None
    website: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    services: list[str] = Field(default_factory=list)
    status: str = "draft"

class ProviderCreate(BaseModel):
    trading_name: str = Field(min_length=1, max_length=240)
    registered_name: str | None = None
    website: str | None = None
    provider_type: str = "funeral_director"
    notes: str | None = None
    branches: list[BranchInput] = Field(default_factory=list)

class ProviderUpdate(BaseModel):
    trading_name: str | None = None
    registered_name: str | None = None
    website: str | None = None
    provider_type: str | None = None
    notes: str | None = None

class ProviderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    trading_name: str
    registered_name: str | None
    website: str | None
    provider_type: str
    status: str
    verification_status: str
    notes: str | None
    created_at: datetime
    updated_at: datetime

class BranchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    provider_id: int
    branch_name: str
    address_line_1: str
    address_line_2: str | None
    town_city: str
    county: str | None
    postcode: str
    telephone: str | None
    email: str | None
    website: str | None
    latitude: float | None
    longitude: float | None
    services: list
    status: str

class ObservationCreate(BaseModel):
    provider_id: int | None = None
    branch_id: int | None = None
    source_type: str = "manual"
    source_name: str = Field(min_length=1, max_length=240)
    source_url: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    observed_data: dict = Field(default_factory=dict)
    notes: str | None = None

class ObservationDecision(BaseModel):
    review_status: str
    notes: str | None = None
    provider_id: int | None = None
    branch_id: int | None = None
