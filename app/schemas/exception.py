from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.base import BaseModelWithDateFormatting

ExceptionTeam = Literal["warehouse", "fleet", "support", "management"]
ExceptionSeverity = Literal["low", "medium", "high", "critical"]
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


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


class ExceptionEventOut(BaseModelWithDateFormatting):
    at: datetime
    actor: str
    action: str
    note: Optional[str] = None


class ExceptionDetailOut(ExceptionOut):
    events: list[ExceptionEventOut]


class ExceptionUpdate(BaseModel):
    owner_id: Optional[int] = Field(None, gt=0)
    status: Optional[Literal["open", "in_progress", "waiting", "resolved"]] = None
    note: Optional[Text] = None
    resolution: Optional[Text] = None
    merged_into_id: Optional[int] = Field(None, gt=0)


class ExceptionScanOut(BaseModel):
    found: int
    created: int
    closed: int
