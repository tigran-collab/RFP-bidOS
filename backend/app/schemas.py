from datetime import datetime

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


class OpportunityCreate(BaseModel):
    title: str
    agency: str | None = None
    solicitation_number: str | None = None
    source: str | None = None
    source_url: str | None = None
    portal_url: str | None = None
    location: str | None = None
    due_date: datetime | None = None
    pre_bid_date: datetime | None = None
    pre_bid_mandatory: bool = False
    q_and_a_deadline: datetime | None = None
    service_type: str | None = None
    contract_type: str | None = None
    estimated_value: float | None = None
    bid_decision: str | None = None
    bid_score: float | None = None
    bid_reason: str | None = None
    status: str = "new"


class OpportunityUpdate(BaseModel):
    title: str | None = None
    agency: str | None = None
    solicitation_number: str | None = None
    source: str | None = None
    source_url: str | None = None
    portal_url: str | None = None
    location: str | None = None
    due_date: datetime | None = None
    pre_bid_date: datetime | None = None
    pre_bid_mandatory: bool | None = None
    q_and_a_deadline: datetime | None = None
    service_type: str | None = None
    contract_type: str | None = None
    estimated_value: float | None = None
    bid_decision: str | None = None
    bid_score: float | None = None
    bid_reason: str | None = None
    status: str | None = None


class OpportunityRead(OpportunityCreate):
    id: int
    created_at: datetime
    updated_at: datetime


class DocumentRead(BaseModel):
    id: int
    opportunity_id: int
    filename: str
    path: str
    file_type: str | None = None
    sha256: str | None = None
    source_url: str | None = None
    downloaded_at: datetime | None = None
    parsed_status: str


class RequirementRead(BaseModel):
    id: int
    opportunity_id: int
    document_id: int | None = None
    requirement_text: str
    source_file: str | None = None
    source_page: int | None = None
    source_section: str | None = None
    mandatory: bool
    response_location: str | None = None
    evidence_needed: str | None = None
    owner: str | None = None
    status: str
    risk: str | None = None


class SourceConfigCreate(BaseModel):
    name: str
    source_type: str
    base_url: str | None = None
    login_url: str | None = None
    enabled: bool = True
    notes: str | None = None


class SourceConfigUpdate(BaseModel):
    name: str | None = None
    source_type: str | None = None
    base_url: str | None = None
    login_url: str | None = None
    enabled: bool | None = None
    notes: str | None = None


class SourceConfigRead(SourceConfigCreate):
    id: int
    created_at: datetime
