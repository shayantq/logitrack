from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, StringConstraints

from app.schemas.base import BaseModelWithDateFormatting


class MessageFailureOut(BaseModelWithDateFormatting):
    id: int
    channel: Literal["sms", "email"]
    recipient: str
    organization_id: Optional[int] = None
    status: str
    attempts: int
    last_error: Optional[str] = None
    created_at: datetime
    first_attempt_at: Optional[datetime] = None
    sensitive: bool = False
    replayable: bool
    conflict: bool = False
    # پذیرش سرویس‌دهنده (status=sent) با رسیدن به گیرنده یکی نیست؛ این کد خام کاوه‌نگار است
    provider_status: Optional[int] = None
    provider_status_label: Optional[str] = None


class TaskFailureOut(BaseModelWithDateFormatting):
    id: int
    task_name: str
    organization_id: Optional[int] = None
    error: str
    created_at: datetime
    status: str
    replayable: bool


class OperationsOverview(BaseModel):
    pending: int
    oldest_pending_seconds: int = 0
    queue_depth: Optional[int] = None
    messages: list[MessageFailureOut]
    unconfirmed: list[MessageFailureOut] = []
    tasks: list[TaskFailureOut]


Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class ReplayIn(BaseModel):
    reason: Reason
    conflict_reviewed: bool = False


class ResolveIn(BaseModel):
    action: Literal["confirm_accepted", "resend"]
    reason: Reason
    accept_duplicate_risk: bool = False
