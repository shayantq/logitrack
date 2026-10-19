"""تیکت پشتیبانی (مرحله ۱۱)."""
from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, StringConstraints

Priority = Literal["normal", "high", "urgent"]
Visibility = Literal["all", "staff", "side"]


class TicketSummary(BaseModel):
    id: int
    code: str
    subject: str
    category: str
    category_label: str
    priority: str
    source: str
    handler: str
    status: str
    waiting_on: str
    created_at: Optional[datetime] = None
    last_activity_at: Optional[datetime] = None
    order_id: Optional[int] = None
    order_tracking_code: Optional[str] = None
    requester_name: Optional[str] = None
    assignee_id: Optional[int] = None
    assignee_name: Optional[str] = None
    escalated_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    organization_name: Optional[str] = None
    overdue: bool = False


class TicketMessageOut(BaseModel):
    id: int
    created_at: Optional[datetime] = None
    author_side: str
    author_name: Optional[str] = None
    body: str
    visibility: str
    has_attachment: bool
    attachment_type: Optional[str] = None


class ReplyOption(BaseModel):
    visibility: str
    label: str


class TicketDetail(TicketSummary):
    escalation_reason: Optional[str] = None
    requester_mobile: Optional[str] = None
    messages: list[TicketMessageOut]
    viewer_side: str
    reply_options: list[ReplyOption]
    can_escalate: bool
    can_resolve: bool
    can_close: bool
    can_manage: bool


class PublicTicketCreated(TicketDetail):
    access_token: str


class TicketsSummary(BaseModel):
    needs_action: int


class EscalateIn(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class TicketUpdate(BaseModel):
    priority: Optional[Priority] = None
    assignee_id: Optional[int] = Field(None, gt=0)
    unassign: bool = False
