"""انبارگردانی دوره‌ای (مرحله ۱۲)."""
from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, StringConstraints

VarianceReason = Literal["damage", "loss", "entry_error", "unrecorded", "unknown"]


class StocktakeSummary(BaseModel):
    id: int
    code: str
    title: Optional[str] = None
    scope: str
    status: str
    count_type: str = "full"
    blind: bool = True
    freeze_mode: str = "snapshot"
    by_location: bool = False
    warehouse_id: int
    warehouse_name: str
    created_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    lines_total: int
    lines_counted: int


class StocktakeLineOut(BaseModel):
    id: int
    product_id: int
    product_name: str
    product_sku: Optional[str] = None
    location_id: Optional[int] = None
    location_code: Optional[str] = None
    added_during_count: bool
    counted_qty: Optional[int] = None
    counted_at: Optional[datetime] = None
    counted_by: Optional[str] = None
    previous_count: Optional[int] = None
    recount_note: Optional[str] = None
    # فقط برای ادمین و از مرحله بررسی به بعد (شمارش کور)
    expected_qty: Optional[int] = None
    # شمارش راهنما (غیرکور): موجودی لحظه‌ای سیستم برای شمارنده
    system_qty: Optional[int] = None
    variance: Optional[int] = None
    variance_value: Optional[float] = None
    variance_reason: Optional[str] = None
    adjustment: Optional[int] = None


class StocktakeDetail(StocktakeSummary):
    note: Optional[str] = None
    lines: list[StocktakeLineOut]
    revealed: bool
    created_by: Optional[str] = None
    submitted_by: Optional[str] = None
    approved_by: Optional[str] = None
    accuracy: Optional[float] = None
    variance_lines: Optional[int] = None
    shortage_qty: Optional[int] = None
    surplus_qty: Optional[int] = None
    shortage_value: Optional[float] = None
    surplus_value: Optional[float] = None
    variance_value_total: Optional[float] = None
    approval_threshold: float = 0
    needs_full_approval: bool = False
    approval_note: Optional[str] = None
    locked_locations: int = 0
    can_count: bool
    can_submit: bool
    can_review: bool
    can_approve: bool = False
    can_cancel: bool
    self_review: bool


class CycleCandidate(BaseModel):
    product_id: int
    product_name: str
    product_sku: Optional[str] = None
    abc_class: str
    last_counted_at: Optional[datetime] = None
    due_at: Optional[datetime] = None
    due: bool
    interval_days: int


class WarehouseStocktakeStatus(BaseModel):
    warehouse_id: int
    warehouse_name: str
    city: Optional[str] = None
    interval_days: Optional[int] = None
    last_approved_at: Optional[datetime] = None
    last_code: Optional[str] = None
    next_due_at: Optional[datetime] = None
    overdue: bool
    active: Optional[StocktakeSummary] = None
    items: int
    cycle_due: int = 0
    has_locations: bool = False


class StocktakeCreate(BaseModel):
    warehouse_id: int = Field(gt=0)
    scope: Literal["full", "partial"] = "full"
    # کامل / بخشی / دوره‌ای (ABC)؛ خالی = از روی scope
    count_type: Optional[Literal["full", "partial", "cycle"]] = None
    blind: bool = True
    freeze_mode: Literal["snapshot", "lock"] = "snapshot"
    by_location: bool = False
    location_ids: Optional[list[int]] = Field(None, max_length=500)
    abc_classes: Optional[list[Literal["A", "B", "C"]]] = None
    limit: Optional[int] = Field(None, ge=1, le=1000)
    product_ids: Optional[list[int]] = None
    title: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]] = None
    note: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]] = None


class CountIn(BaseModel):
    counted_qty: int = Field(ge=0, le=10_000_000)


class AddLineIn(CountIn):
    product_id: int = Field(gt=0)
    location_id: Optional[int] = Field(None, gt=0)


class RecountIn(BaseModel):
    line_ids: list[int] = Field(min_length=1)
    note: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]] = None


class ApproveIn(BaseModel):
    # دلیل مغایرت هر قلم (کلید: شناسه قلم)؛ خالی = «نامشخص»
    reasons: dict[int, VarianceReason] = {}
    note: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]] = None


class CancelIn(BaseModel):
    reason: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]] = None


class IntervalIn(BaseModel):
    days: Optional[int] = Field(None, ge=7, le=365)


class StocktakeCount(BaseModel):
    count: int
