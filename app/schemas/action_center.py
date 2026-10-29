"""مرکز اقدام، جستجوی سراسری و نماهای ذخیره‌شده."""
from datetime import datetime
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, Field, StringConstraints


class ActionItem(BaseModel):
    id: int
    label: str
    sub: str = ""
    link: str


class ActionCard(BaseModel):
    key: str
    tone: Literal["danger", "warning", "info"]
    weight: int
    count: int
    title: str
    why: str
    owner: str
    next_action: str
    action_label: str
    link: str
    items: list[ActionItem] = []


class ActionCenterOut(BaseModel):
    cards: list[ActionCard]


class SearchHit(BaseModel):
    id: int
    label: str
    sub: str = ""
    link: str


class SearchGroup(BaseModel):
    type: str
    title: str
    hits: list[SearchHit]


class SearchOut(BaseModel):
    query: str
    exact: Optional[SearchHit] = None
    groups: list[SearchGroup]


SavedViewPage = Literal["orders", "receipts", "inventory", "transfers", "tickets"]
SharedRole = Literal["org_admin", "warehouse_manager"]


class SavedViewIn(BaseModel):
    page_key: SavedViewPage
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    filters: dict[str, Any] = Field(default_factory=dict)
    shared_role: Optional[SharedRole] = None


class SavedViewOut(BaseModel):
    id: int
    page_key: str
    name: str
    filters: dict[str, Any]
    shared_role: Optional[str] = None
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None
    mine: bool
    created_at: Optional[datetime] = None


class BulkIn(BaseModel):
    action: str = Field(..., max_length=16)
    ids: list[Annotated[int, Field(gt=0)]] = Field(..., min_length=1, max_length=200)
    params: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = True


class BulkRow(BaseModel):
    id: int
    label: str
    status: Literal["ok", "invalid", "unauthorized", "done", "failed"]
    reason: Optional[str] = None


class BulkOut(BaseModel):
    action: str
    dry_run: bool
    total: int
    valid: int
    invalid: int
    unauthorized: int
    results: list[BulkRow]


class TimelineEvent(BaseModel):
    at: datetime
    area: Literal["order", "warehouse", "fleet", "finance", "support"]
    area_label: str
    title: str
    actor: str
    outcome: Optional[str] = None
    link: Optional[str] = None
    source: str = "status"      # status | reservation | document | pick | package | shipment | checkpoint | backorder | finance | ticket | rating


class OrderTimelineOut(BaseModel):
    order_id: int
    tracking_code: str
    stage: str
    last_action: Optional[str] = None
    last_action_at: Optional[datetime] = None
    blocker: Optional[str] = None
    events: list[TimelineEvent]


class PriorityIn(BaseModel):
    priority: bool
