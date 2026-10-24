"""اسکیماهای عملیات انبار (فصل‌های ۶ تا ۱۰): محل، رسید دریافت، بازرسی کیفی، جانمایی، موجودی چندبعدی و کاردکس."""
from datetime import date, datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.core.wms import (
    LOCATION_LEVELS, LOCATION_TYPES, PUTAWAY_PROBLEMS, RECEIPT_CONDITIONS, RECEIPT_TYPES, STOCK_STATUSES,
)
from app.schemas.product import LotNumber, SerialNumber, UomName, _unique_serials

StockStatus = Literal[STOCK_STATUSES]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]
Ref = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
LocationCode = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=32,
                                                pattern=r"^[0-9A-Za-z._/-]+$")]
Scan = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


# ---------------------------------------------------------------------------
# محل
# ---------------------------------------------------------------------------
class LocationIn(BaseModel):
    parent_id: Optional[int] = Field(None, gt=0)
    level: Literal[LOCATION_LEVELS] = "bin"
    code: LocationCode
    barcode: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=64, pattern=r"^[0-9A-Za-z._/-]*$")]] = None
    name: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]] = None
    location_type: Literal[tuple(LOCATION_TYPES)] = "storage"
    max_weight_kg: Optional[float] = Field(None, gt=0, le=1_000_000)
    max_volume_m3: Optional[float] = Field(None, gt=0, le=100_000)
    max_pallets: Optional[int] = Field(None, gt=0, le=10_000)
    allow_mixed_products: bool = True
    allow_mixed_lots: bool = True
    allow_mixed_owners: bool = True
    is_active: bool = True
    is_blocked: bool = False
    block_reason: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]] = None


class LocationContentOut(BaseModel):
    balance_id: int
    product_id: int
    product_name: str
    product_sku: str
    stock_status: str
    stock_status_label: str
    lot_number: Optional[str] = None
    serial_number: Optional[str] = None
    expiry_date: Optional[date] = None
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None
    quantity: int


class LocationOut(BaseModel):
    id: int
    warehouse_id: int
    parent_id: Optional[int] = None
    depth: int = 0
    level: str
    level_label: str
    code: str
    barcode: str
    name: Optional[str] = None
    location_type: str
    location_type_label: str
    allocatable: bool
    is_leaf: bool
    max_weight_kg: Optional[float] = None
    max_volume_m3: Optional[float] = None
    max_pallets: Optional[int] = None
    allow_mixed_products: bool
    allow_mixed_lots: bool
    allow_mixed_owners: bool
    is_active: bool
    is_blocked: bool
    block_reason: Optional[str] = None
    quantity: int
    products: int
    weight_kg: float
    volume_m3: float
    pallets: int
    weight_pct: Optional[float] = None
    volume_pct: Optional[float] = None
    pallets_pct: Optional[float] = None
    contents: list[LocationContentOut] = []


# ---------------------------------------------------------------------------
# رسید دریافت
# ---------------------------------------------------------------------------
class ReceiptLineIn(BaseModel):
    product_id: int = Field(gt=0)
    expected_quantity: int = Field(gt=0, le=10_000_000)
    uom: Optional[UomName] = None
    lot_number: Optional[LotNumber] = None
    note: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]] = None


class ReceiptCreate(BaseModel):
    receipt_type: Literal[RECEIPT_TYPES] = "purchase"
    warehouse_id: Optional[int] = Field(None, gt=0)
    partner_id: Optional[int] = Field(None, gt=0)
    owner_id: Optional[int] = Field(None, gt=0)
    source_warehouse_id: Optional[int] = Field(None, gt=0)
    order_id: Optional[int] = Field(None, gt=0)
    reference_number: Optional[Ref] = None
    external_ref: Optional[Ref] = None
    expected_date: Optional[date] = None
    receiving_location_id: Optional[int] = Field(None, gt=0)
    over_tolerance_pct: float = Field(0, ge=0, le=100)
    note: Optional[Text] = None
    lines: list[ReceiptLineIn] = Field(default_factory=list, max_length=500)


class ReceiveLineIn(BaseModel):
    line_id: Optional[int] = Field(None, gt=0)
    product_id: Optional[int] = Field(None, gt=0, description="کالای خارج از برنامه یا رسید پیش‌بینی‌نشده")
    quantity: int = Field(gt=0, le=10_000_000)
    uom: Optional[UomName] = None
    lot_number: Optional[LotNumber] = None
    expiry_date: Optional[date] = None
    serial_numbers: list[SerialNumber] = Field(default_factory=list, max_length=1000)
    condition: Literal[RECEIPT_CONDITIONS] = "good"
    over_reason: Optional[Reason] = None

    @model_validator(mode="after")
    def _check(self):
        if self.line_id is None and self.product_id is None:
            raise ValueError("سطر رسید یا کالا را مشخص کنید.")
        _unique_serials(self.serial_numbers)
        return self


class ReceiveIn(BaseModel):
    location_id: Optional[int] = Field(None, gt=0, description="محل تخلیه (خالی = محل پیش‌فرض رسید/انبار)")
    note: Optional[Text] = None
    lines: list[ReceiveLineIn] = Field(min_length=1, max_length=500)


class ReceiptCloseIn(BaseModel):
    note: Optional[Text] = None
    reasons: dict[int, Reason] = Field(default_factory=dict, description="دلیل مغایرت هر سطر: {شناسه سطر: دلیل}")


class ReasonIn(BaseModel):
    reason: Reason


class ReceiptLineOut(BaseModel):
    id: int
    line_no: int
    product_id: int
    product_name: str
    product_sku: str
    unit: str
    lot_tracked: bool
    expiry_tracked: bool
    serial_tracked: bool
    inspection_required: bool
    expected_quantity: int
    received_quantity: int
    accepted_quantity: int
    rejected_quantity: int
    pending_inspection: int
    outstanding: int
    lot_number: Optional[str] = None
    note: Optional[str] = None
    over_reason: Optional[str] = None
    discrepancy_type: Optional[str] = None
    discrepancy_label: Optional[str] = None
    discrepancy_quantity: Optional[int] = None
    discrepancy_reason: Optional[str] = None


class ReceiptDocumentOut(BaseModel):
    id: int
    code: str
    created_at: Optional[datetime] = None
    total: int


class ReceiptTaskOut(BaseModel):
    id: int
    code: str
    status: str
    product_name: str
    quantity: int
    quantity_done: int
    stock_status_label: str


class ReceiptOut(BaseModel):
    id: int
    code: str
    receipt_type: str
    receipt_type_label: str
    status: str
    status_label: str
    warehouse_id: int
    warehouse_name: Optional[str] = None
    partner_id: Optional[int] = None
    partner_name: Optional[str] = None
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None
    source_warehouse_id: Optional[int] = None
    source_warehouse_name: Optional[str] = None
    order_id: Optional[int] = None
    reference_number: Optional[str] = None
    external_ref: Optional[str] = None
    expected_date: Optional[date] = None
    receiving_location_id: Optional[int] = None
    receiving_location_code: Optional[str] = None
    over_tolerance_pct: float
    note: Optional[str] = None
    created_at: Optional[datetime] = None
    created_by_name: Optional[str] = None
    received_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    close_note: Optional[str] = None
    total_expected: int
    total_received: int
    total_accepted: int
    total_rejected: int
    total_pending_inspection: int
    total_outstanding: int
    has_discrepancy: bool
    lines: list[ReceiptLineOut] = []
    documents: list[ReceiptDocumentOut] = []
    putaway_tasks: list[ReceiptTaskOut] = []


# ---------------------------------------------------------------------------
# بازرسی کیفی
# ---------------------------------------------------------------------------
class InspectionResultIn(BaseModel):
    status: StockStatus
    quantity: int = Field(gt=0, le=10_000_000)
    reason: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]] = None


class InspectionCreate(BaseModel):
    product_id: int = Field(gt=0)
    warehouse_id: Optional[int] = Field(None, gt=0)
    from_status: StockStatus = "pending"
    location_id: Optional[int] = Field(None, gt=0)
    lot_number: Optional[LotNumber] = None
    receipt_id: Optional[int] = Field(None, gt=0)
    note: Optional[Text] = None
    results: list[InspectionResultIn] = Field(min_length=1, max_length=7)

    @model_validator(mode="after")
    def _check(self):
        statuses = [r.status for r in self.results]
        if len(set(statuses)) != len(statuses):
            raise ValueError("هر وضعیت نتیجه فقط یک بار می‌آید؛ مقدارها را جمع کنید.")
        for r in self.results:
            if r.status not in ("available",) and not r.reason:
                raise ValueError("برای نتیجه غیر از «تأییدشده» دلیل (مثلاً نوع ایراد) را بنویسید.")
        return self


class InspectionResultOut(BaseModel):
    status: str
    status_label: str
    quantity: int
    reason: Optional[str] = None


class InspectionOut(BaseModel):
    id: int
    code: str
    warehouse_id: int
    warehouse_name: Optional[str] = None
    product_id: int
    product_name: str
    product_sku: str
    location_id: Optional[int] = None
    location_code: Optional[str] = None
    lot_number: Optional[str] = None
    from_status: str
    from_status_label: str
    quantity: int
    receipt_id: Optional[int] = None
    document_id: Optional[int] = None
    document_code: Optional[str] = None
    note: Optional[str] = None
    inspector_name: Optional[str] = None
    created_at: Optional[datetime] = None
    results: list[InspectionResultOut] = []


class QualityTransitionOut(BaseModel):
    from_: str = Field(alias="from")
    to: str
    allowed: bool

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# جانمایی
# ---------------------------------------------------------------------------
class PutawayTaskCreate(BaseModel):
    warehouse_id: Optional[int] = Field(None, gt=0)
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=10_000_000)
    stock_status: StockStatus = "available"
    source_location_id: Optional[int] = Field(None, gt=0)
    lot_number: Optional[LotNumber] = None
    expiry_date: Optional[date] = None
    owner_id: Optional[int] = Field(None, gt=0)
    note: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]] = None


class PutawayExecute(BaseModel):
    """اسکن‌ها (بارکدخوان مثل صفحه‌کلید عمل می‌کند): کالا، محل مبدأ (یا کد انبار برای کالای بدون محل)، محل مقصد."""
    product_scan: Scan
    source_scan: Scan
    destination_scan: Scan
    lot_scan: Optional[Scan] = None
    quantity: int = Field(gt=0, le=10_000_000)


class PutawayProblemIn(BaseModel):
    problem: Literal[PUTAWAY_PROBLEMS]
    location_id: Optional[int] = Field(None, gt=0, description="محل مقصدی که مشکل دارد (خالی = مقصد پیشنهادی)")
    note: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]] = None


class PutawayTaskOut(BaseModel):
    id: int
    code: str
    status: str
    status_label: str
    warehouse_id: int
    warehouse_code: Optional[str] = None
    product_id: int
    product_name: str
    product_sku: str
    product_barcode: Optional[str] = None
    unit: str
    stock_status: str
    stock_status_label: str
    quantity: int
    quantity_done: int
    remaining: int
    source_location_id: Optional[int] = None
    source_location_code: Optional[str] = None
    suggested_location_id: Optional[int] = None
    suggested_location_code: Optional[str] = None
    destination_location_id: Optional[int] = None
    destination_location_code: Optional[str] = None
    lot_number: Optional[str] = None
    expiry_date: Optional[date] = None
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None
    receipt_id: Optional[int] = None
    inspection_id: Optional[int] = None
    failure_count: int
    last_problem: Optional[str] = None
    last_error: Optional[str] = None
    note: Optional[str] = None
    cancel_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# موجودی چندبعدی و کاردکس
# ---------------------------------------------------------------------------
class StockPositionOut(BaseModel):
    product_id: int
    product_name: str
    product_sku: str
    unit: str
    warehouse_id: int
    warehouse_name: str
    warehouse_type: str
    on_hand: int
    approved: int
    allocatable: int
    reserved: int
    available: int
    pending_inspection: int
    quarantine: int
    not_put_away: int
    expired: int
    consigned: int
    in_transit: int
    inbound_expected: int
    by_status: dict[str, int] = {}


class StockBalanceOut(BaseModel):
    balance_id: int
    inventory_id: int
    product_id: int
    product_name: str
    product_sku: str
    unit: str
    warehouse_id: int
    warehouse_name: Optional[str] = None
    stock_status: str
    stock_status_label: str
    location_id: Optional[int] = None
    location_code: Optional[str] = None
    location_type: Optional[str] = None
    lot_number: Optional[str] = None
    serial_number: Optional[str] = None
    expiry_date: Optional[date] = None
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None
    quantity: int
    expired: bool
    allocatable: bool


class StockCardRowOut(BaseModel):
    date: Optional[datetime] = None
    document_id: int
    document_code: Optional[str] = None
    doc_type: Optional[str] = None
    doc_type_label: Optional[str] = None
    document_status: Optional[str] = None
    partner_name: Optional[str] = None
    description: str = ""
    movement_types: list[str] = []
    locations: list[str] = []
    lots: list[str] = []
    quantity_in: int
    quantity_out: int
    balance: int
    created_by_name: Optional[str] = None


class StockCardOut(BaseModel):
    product_id: int
    product_name: str
    product_sku: str
    unit: str
    warehouse_id: Optional[int] = None
    warehouse_name: Optional[str] = None
    location_id: Optional[int] = None
    location_code: Optional[str] = None
    lot_number: Optional[str] = None
    stock_status: Optional[str] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    opening_balance: int
    total_in: int
    total_out: int
    closing_balance: int
    rows: list[StockCardRowOut]
    truncated: bool
