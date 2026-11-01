from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.base import BaseModelWithDateFormatting

ExceptionTeam = Literal["warehouse", "fleet", "support", "management"]
ExceptionSeverity = Literal["low", "medium", "high", "critical"]
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
ResolutionCode = Literal["fixed", "stock_corrected", "rescheduled", "customer_contacted", "supplier_followup", "driver_followup", "no_action", "duplicate", "other"]


class SuggestedOwner(BaseModel):
    id: int
    name: str
    open_count: int


class ExceptionOut(BaseModelWithDateFormatting):
    id: int
    kind: str
    kind_label: str
    entity_type: str
    entity_id: int
    warehouse_id: Optional[int] = None
    severity: ExceptionSeverity
    severity_label: str
    team: ExceptionTeam
    team_label: str
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None
    status: str
    status_label: str
    opened_at: datetime
    due_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    overdue: bool
    trigger_reason: str
    suggested_action: Optional[str] = None
    resolution: Optional[str] = None
    merged_into_id: Optional[int] = None
    link: Optional[str] = None
    suggested_owner: Optional[SuggestedOwner] = None
    occurrence_count: int = 1
    acknowledged_at: Optional[datetime] = None
    evidence_refs: list[str] = []
    resolution_code: Optional[str] = None
    resolution_code_label: Optional[str] = None
    escalated_at: Optional[datetime] = None


class ExceptionEventOut(BaseModelWithDateFormatting):
    at: datetime
    actor: str
    action: str
    note: Optional[str] = None


class ExceptionDetailOut(ExceptionOut):
    events: list[ExceptionEventOut]


class ExceptionUpdate(BaseModel):
    owner_id: Optional[int] = Field(None, gt=0)
    status: Optional[Literal["open", "acknowledged", "in_progress", "waiting", "waiting_external", "resolved"]] = None
    note: Optional[Text] = None
    resolution: Optional[Text] = None
    resolution_code: Optional[ResolutionCode] = None
    evidence_ref: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]] = None
    merged_into_id: Optional[int] = Field(None, gt=0)


class ExceptionScanOut(BaseModel):
    found: int
    created: int
    closed: int


class DriverExceptionOut(BaseModelWithDateFormatting):
    id: int
    kind_label: str
    trigger_reason: str
    suggested_action: Optional[str] = None
    occurrence_count: int
    order_id: int
    opened_at: datetime
    status_label: str


class IncidentIn(BaseModel):
    order_id: int = Field(gt=0)
    issue: Literal["breakdown", "delay", "customer_unavailable", "damage", "discrepancy", "other"]
    note: Optional[Text] = None


class ApprovalOut(BaseModelWithDateFormatting):
    id: int
    kind: str
    product_id: int
    product_name: str
    warehouse_name: Optional[str] = None
    quantity: int
    reason: Optional[str] = None
    status: str
    requested_by: Optional[str] = None
    requested_by_id: Optional[int] = None
    created_at: datetime
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    decision_note: Optional[str] = None


class ApprovalDecisionIn(BaseModel):
    approve: bool
    note: Optional[Text] = None
