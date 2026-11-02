from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.base import BaseModelWithDateFormatting

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
Slug = Annotated[str, StringConstraints(strip_whitespace=True, max_length=64)]
PlanId = Literal["trial", "basic", "pro", "enterprise"]


class ReasonIn(BaseModel):
    reason: Reason


class SuspendIn(BaseModel):
    reason: Reason
    confirm_slug: Slug


class PlanIn(BaseModel):
    plan_id: PlanId
    reason: Reason


class PlanResource(BaseModel):
    key: str
    label: str
    used: int
    limit: int
    near_limit: bool


class PlanSummary(BaseModelWithDateFormatting):
    plan_id: str
    label: str
    version: int
    grace_until: Optional[datetime] = None
    modules: list[str]
    resources: list[PlanResource]


class GrantIn(BaseModel):
    user_id: int = Field(gt=0)
    reason: Reason
    minutes: int = Field(60, ge=1, le=240)


class GrantOut(BaseModelWithDateFormatting):
    id: int
    organization_id: int
    user_id: int
    user_name: Optional[str] = None
    reason: str
    expires_at: datetime
    revoked_at: Optional[datetime] = None
    created_at: datetime
    active: bool


class SupportOrder(BaseModelWithDateFormatting):
    id: int
    tracking_code: str
    status: str
    stock_state: Optional[str] = None
    destination_city: Optional[str] = None
    created_at: Optional[datetime] = None


class SupportView(BaseModelWithDateFormatting):
    organization_id: int
    expires_at: datetime
    orders: list[SupportOrder]


class FlagIn(BaseModel):
    enabled: bool = True
    kill_switch: bool = False
    allowlist: list[int] = Field(default_factory=list, max_length=500)
    reason: Reason


class FlagOut(BaseModel):
    key: str
    label: str
    enabled: bool
    kill_switch: bool
    allowlist: list[int]


class ExportOut(BaseModelWithDateFormatting):
    id: int
    organization_id: int
    status: str
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    retry_of_id: Optional[int] = None
    retried: bool = False
    stale: bool = False
    waiting_too_long: bool = False
    message: Optional[str] = None
    error: Optional[str] = Field(None, description="جزئیات فنی شکست؛ فقط برای ادمین پلتفرم")
    can_retry: bool = False


class DeprovisionOut(BaseModelWithDateFormatting):
    requested_at: Optional[datetime] = None
    erase_after: Optional[datetime] = None
    erased_at: Optional[datetime] = None
