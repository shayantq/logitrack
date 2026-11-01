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
    replayable: bool


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
    tasks: list[TaskFailureOut]


class ReplayIn(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
