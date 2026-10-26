"""کنترل، تحلیل و آمادگی راه‌اندازی (فصل‌های ۱۷، ۲۰، ۲۲، ۲۶ تا ۲۸ و ۳۰ تا ۳۵)."""
from datetime import date, datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, StringConstraints

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]
Note = Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]]


# ---------------------------------------------------------------- مجوزها
class RoleCell(BaseModel):
    allowed: bool
    editable: bool
    customized: bool


class PermissionRow(BaseModel):
    key: str
    label: str
    group: str
    max_roles: list[str]
    default_roles: list[str]
    sensitive: bool
    roles: dict[str, RoleCell]


class CodeLabel(BaseModel):
    code: str
    label: str


class PermissionMatrix(BaseModel):
    roles: list[CodeLabel]
    permissions: list[PermissionRow]


class PermissionUpdate(BaseModel):
    allowed: bool
    reason: Reason


class ReasonBody(BaseModel):
    reason: Reason


# ---------------------------------------------------------------- تنظیمات و ارزش‌گذاری
class ControlSettings(BaseModel):
    valuation_method: str
    count_approval_value: int
    slow_days: int
    dead_days: int
    expiry_warning_days: int
    valuation_methods: list[CodeLabel] = []


class ControlSettingsIn(BaseModel):
    valuation_method: Optional[Literal["fifo", "weighted_average", "standard"]] = None
    count_approval_value: Optional[int] = Field(None, ge=0)
    slow_days: Optional[int] = Field(None, ge=7, le=720)
    dead_days: Optional[int] = Field(None, ge=14, le=1460)
    expiry_warning_days: Optional[int] = Field(None, ge=1, le=365)
    reason: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]] = None


class MethodValues(BaseModel):
    fifo: float
    weighted_average: float
    standard: float


class ValuationRow(BaseModel):
    product_id: int
    product_name: str
    sku: str
    category: Optional[str] = None
    abc_class: Optional[str] = None
    quantity: int
    org_quantity: int
    unit_cost: MethodValues
    value: MethodValues
    selected_value: float
    issued_qty: int
    estimated: bool
    reconciled: bool


class ValuationOut(BaseModel):
    method: str
    method_label: str
    methods: list[CodeLabel]
    date_from: date
    date_to: date
    warehouse_id: Optional[int] = None
    totals: MethodValues
    cogs: MethodValues
    selected_total: float
    estimated_items: int
    items: list[ValuationRow]


class HealthBucket(BaseModel):
    status: str
    count: int
    value: float


class HealthItem(BaseModel):
    product_id: int
    product_name: str
    sku: str
    abc_class: Optional[str] = None
    quantity: int
    value: float
    last_sale_at: Optional[datetime] = None
    idle_days: Optional[int] = None
    status: str


class ExpiringItem(BaseModel):
    product_id: int
    product_name: str
    sku: Optional[str] = None
    warehouse_name: str
    location_code: Optional[str] = None
    lot_number: Optional[str] = None
    expiry_date: date
    days_left: int
    stock_status: str
    quantity: int
    value: float
    expired: bool


class HealthOut(BaseModel):
    settings: dict[str, int]
    buckets: list[HealthBucket]
    items: list[HealthItem]
    expiring: list[ExpiringItem]
    expired_value: float
    expiring_value: float
    summary: str


# ---------------------------------------------------------------- شاخص‌ها
class KpiOut(BaseModel):
    key: str
    label: str
    value: Optional[float] = None
    unit: str
    target: float
    hint: str
    higher_better: bool
    status: Literal["good", "warn", "bad", "none"]
    detail: Optional[str] = None


class TrendPoint(BaseModel):
    day: date
    orders: int
    delivered: int
    shipped_units: int
    received_units: int


class AlertOut(BaseModel):
    level: Literal["danger", "warning", "info"]
    text: str


class KpiDashboard(BaseModel):
    date_from: date
    date_to: date
    warehouse_id: Optional[int] = None
    kpis: list[KpiOut]
    trend: list[TrendPoint]
    snapshot: dict[str, int]
    alerts: list[AlertOut]


# ---------------------------------------------------------------- برچسب و اسکن
class LabelPrintIn(BaseModel):
    label_type: Literal["product", "location", "package"]
    ids: list[int] = Field(min_length=1, max_length=500)
    copies: int = Field(1, ge=1, le=50)
    reason: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]] = None


class LabelPrintOut(BaseModel):
    id: int
    label_type: str
    target_id: int
    target_code: str
    copies: int
    is_reprint: bool
    reason: Optional[str] = None
    printed_at: datetime
    printed_by: Optional[str] = None


class ScanResult(BaseModel):
    kind: str
    id: int
    code: str
    title: str
    subtitle: Optional[str] = None
    path: str


# ---------------------------------------------------------------- گردش‌کار
class WorkflowState(BaseModel):
    code: str
    label: str
    final: bool


class WorkflowTransition(BaseModel):
    from_: str = Field(alias="from", serialization_alias="from")
    to: str
    action: str
    actor: str

    model_config = {"populate_by_name": True}


class WorkflowOut(BaseModel):
    code: str
    label: str
    note: Optional[str] = None
    states: list[WorkflowState]
    transitions: list[WorkflowTransition]


# ---------------------------------------------------------------- آمادگی و ورود داده
class ReadinessCheck(BaseModel):
    key: str
    group: str
    label: str
    status: Literal["pass", "warn", "fail"]
    detail: str
    path: Optional[str] = None


class ManualCheck(BaseModel):
    key: str
    label: str
    group: str
    done: bool
    note: Optional[str] = None
    updated_at: Optional[datetime] = None
    updated_by: Optional[str] = None


class ReadinessOut(BaseModel):
    checks: list[ReadinessCheck]
    manual: list[ManualCheck]
    score: int
    passed: int
    total: int
    blockers: list[str]
    ready: bool
    checked_at: datetime


class ManualCheckIn(BaseModel):
    done: bool
    note: Note = None


class ImportError_(BaseModel):
    line: int
    message: str


class ImportPreview(BaseModel):
    line: int
    summary: str
    ok: bool


class DataImportReport(BaseModel):
    kind: str
    rows: int
    valid: int
    error_count: int
    errors: list[ImportError_]
    applied: bool
    preview: list[ImportPreview]
    create: Optional[int] = None
    skip: Optional[int] = None
    units: Optional[int] = None
    document_code: Optional[str] = None
