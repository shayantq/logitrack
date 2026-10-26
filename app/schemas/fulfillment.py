"""اسکیماهای اجرای سفارش و جابه‌جایی (فصل‌های ۱۱ تا ۱۵)."""
from datetime import date, datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.core.wms import DISPOSITION_ACTIONS, PICK_STRATEGIES, STOCK_STATUSES, TRANSFER_RESOLUTIONS
from app.schemas.product import LotNumber, UomName

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Scan = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


# ---------------------------------------------------------------------------
# سفارش معوق
# ---------------------------------------------------------------------------
class BackorderOut(BaseModel):
    id: int
    order_id: int
    order_tracking_code: Optional[str] = None
    customer_name: Optional[str] = None
    product_id: int
    product_name: str
    product_sku: str
    warehouse_id: int
    quantity: int
    status: str
    status_label: str
    priority: bool
    due_at: datetime
    created_at: Optional[datetime] = None
    allocated_at: Optional[datetime] = None
    fulfilled_order_id: Optional[int] = None
    note: Optional[str] = None


class AllocateIn(BaseModel):
    warehouse_id: Optional[int] = Field(None, gt=0)
    product_id: Optional[int] = Field(None, gt=0)


class AllocateOut(BaseModel):
    allocated_quantity: int
    split: int


class FulfillIn(BaseModel):
    delivery_window_start: datetime
    delivery_window_end: datetime

    @model_validator(mode="after")
    def _window(self):
        if self.delivery_window_end <= self.delivery_window_start:
            raise ValueError("پایان بازه تحویل باید بعد از شروع آن باشد.")
        return self


class ReasonIn(BaseModel):
    reason: Reason


# ---------------------------------------------------------------------------
# سفارش انتقال
# ---------------------------------------------------------------------------
class TransferLineIn(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=10_000_000)
    uom: Optional[UomName] = None
    lot_number: Optional[LotNumber] = None


class TransferCreate(BaseModel):
    from_warehouse_id: int = Field(gt=0)
    to_warehouse_id: int = Field(gt=0)
    from_location_id: Optional[int] = Field(None, gt=0)
    to_location_id: Optional[int] = Field(None, gt=0)
    note: Optional[Note] = None
    lines: list[TransferLineIn] = Field(min_length=1, max_length=200)


class TransferReceiveLineIn(BaseModel):
    line_id: int = Field(gt=0)
    received_quantity: int = Field(0, ge=0)
    damaged_quantity: int = Field(0, ge=0)
    reason: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]] = None


class TransferReceiveIn(BaseModel):
    location_id: Optional[int] = Field(None, gt=0)
    note: Optional[Note] = None
    lines: list[TransferReceiveLineIn] = Field(min_length=1, max_length=200)


class TransferCloseIn(BaseModel):
    resolution: Literal[TRANSFER_RESOLUTIONS] = "write_off"
    reason: Optional[Reason] = None


class TransferLineOut(BaseModel):
    id: int
    product_id: int
    product_name: str
    product_sku: str
    lot_number: Optional[str] = None
    quantity: int
    shipped_quantity: int
    received_quantity: int
    damaged_quantity: int
    resolved_quantity: int
    in_transit: int
    discrepancy_reason: Optional[str] = None


class TransferOut(BaseModel):
    id: int
    code: str
    status: str
    status_label: str
    from_warehouse_id: int
    from_warehouse_name: str
    to_warehouse_id: int
    to_warehouse_name: str
    from_location_code: Optional[str] = None
    to_location_id: Optional[int] = None
    to_location_code: Optional[str] = None
    internal: bool
    note: Optional[str] = None
    created_at: Optional[datetime] = None
    shipped_at: Optional[datetime] = None
    received_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    close_note: Optional[str] = None
    resolution: Optional[str] = None
    lines: list[TransferLineOut]


# ---------------------------------------------------------------------------
# تأمین مجدد و ABC
# ---------------------------------------------------------------------------
class ReplenishmentRuleIn(BaseModel):
    location_id: int = Field(gt=0)
    product_id: int = Field(gt=0)
    min_quantity: int = Field(ge=0, le=10_000_000)
    max_quantity: int = Field(gt=0, le=10_000_000)
    is_active: bool = True

    @model_validator(mode="after")
    def _range(self):
        if self.max_quantity <= self.min_quantity:
            raise ValueError("حداکثر باید بیشتر از حداقل باشد.")
        return self


class ReplenishmentRuleOut(BaseModel):
    id: int
    warehouse_id: int
    location_id: int
    location_code: str
    product_id: int
    product_name: str
    product_sku: str
    min_quantity: int
    max_quantity: int
    is_active: bool
    current_quantity: int
    pending_quantity: int
    needs_replenishment: bool


class GenerateOut(BaseModel):
    quantity: int


class AbcRunIn(BaseModel):
    days: int = Field(365, ge=30, le=1095)


class AbcRunOut(BaseModel):
    days: int
    total_value: float
    A: int
    B: int
    C: int


class AbcRowOut(BaseModel):
    product_id: int
    product_name: str
    product_sku: str
    abc_class: Optional[str] = None
    consumption_value: float
    share: float
    count_every_days: int
    last_counted_at: Optional[datetime] = None
    next_count_due: date
    count_due: bool
    classified_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# پیکینگ
# ---------------------------------------------------------------------------
class PickListCreate(BaseModel):
    warehouse_id: Optional[int] = Field(None, gt=0)
    strategy: Literal[PICK_STRATEGIES] = "single"
    order_ids: Optional[list[int]] = Field(None, max_length=200)
    wave_date: Optional[date] = None
    zone_location_id: Optional[int] = Field(None, gt=0)
    staging_location_id: Optional[int] = Field(None, gt=0)


class PickIn(BaseModel):
    source_scan: Scan
    product_scan: Scan
    lot_scan: Optional[Scan] = None
    quantity: int = Field(gt=0, le=10_000_000)


class ShortIn(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]


class PickLineOut(BaseModel):
    id: int
    sequence: int
    order_id: int
    order_tracking_code: Optional[str] = None
    order_fulfillment: Optional[str] = None
    product_id: int
    product_name: str
    product_sku: str
    product_barcode: Optional[str] = None
    location_id: Optional[int] = None
    location_code: Optional[str] = None
    lot_number: Optional[str] = None
    expiry_date: Optional[date] = None
    quantity: int
    picked_quantity: int
    status: str
    short_reason: Optional[str] = None


class PickListOut(BaseModel):
    id: int
    code: str
    strategy: str
    strategy_label: str
    status: str
    status_label: str
    warehouse_id: int
    warehouse_code: Optional[str] = None
    zone_code: Optional[str] = None
    staging_location_id: Optional[int] = None
    staging_code: Optional[str] = None
    wave_date: Optional[date] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    orders: list[str]
    total_quantity: int
    picked_quantity: int
    lines: list[PickLineOut]
    skipped_orders: list[str] = []
    replanned: Optional[int] = None
    unresolved: Optional[int] = None


class PickCandidateOut(BaseModel):
    id: int
    tracking_code: str
    status: str
    priority: bool
    delivery_day: date
    recipient_name: Optional[str] = None
    destination_city: Optional[str] = None
    fulfillment_state: str
    items: int


# ---------------------------------------------------------------------------
# بسته‌بندی و محموله
# ---------------------------------------------------------------------------
class PackageItemIn(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0)


class PackageIn(BaseModel):
    length_cm: float = Field(gt=0, le=1000)
    width_cm: float = Field(gt=0, le=1000)
    height_cm: float = Field(gt=0, le=1000)
    weight_kg: Optional[float] = Field(None, gt=0, le=50_000)
    items: list[PackageItemIn] = Field(min_length=1, max_length=200)


class PackIn(BaseModel):
    packages: list[PackageIn] = Field(min_length=1, max_length=100)


class PackageItemOut(BaseModel):
    product_id: int
    product_name: str
    product_sku: str
    quantity: int


class PackageOut(BaseModel):
    id: int
    code: str
    sequence: int
    length_cm: float
    width_cm: float
    height_cm: float
    weight_kg: float
    volume_m3: float
    items: list[PackageItemOut]


class PackingSlipOut(BaseModel):
    order_id: int
    tracking_code: str
    fulfillment_state: str
    recipient_name: Optional[str] = None
    recipient_mobile: Optional[str] = None
    destination: str
    delivery_window_start: Optional[datetime] = None
    shipment_id: Optional[int] = None
    total_weight_kg: float
    total_volume_m3: float
    packages: list[PackageOut]


class QueueItemOut(BaseModel):
    product_id: int
    product_name: str
    product_sku: Optional[str] = None
    quantity: int
    unit_weight_kg: float


class PackingQueueOut(BaseModel):
    id: int
    tracking_code: str
    status: str
    fulfillment_state: str
    fulfillment_label: str
    recipient_name: Optional[str] = None
    destination_city: Optional[str] = None
    delivery_window_start: Optional[datetime] = None
    shipment_id: Optional[int] = None
    packed_weight_kg: float
    packed_volume_m3: float
    items: list[QueueItemOut]


class ShipmentCreate(BaseModel):
    warehouse_id: Optional[int] = Field(None, gt=0)
    vehicle_id: int = Field(gt=0)
    order_ids: list[int] = Field(min_length=1, max_length=200)
    note: Optional[Note] = None


class DispatchIn(BaseModel):
    note: Optional[Note] = None


class ShipmentOrderOut(BaseModel):
    id: int
    tracking_code: str
    status: str
    recipient_name: Optional[str] = None
    destination_city: Optional[str] = None
    fulfillment_state: str


class ShipmentOut(BaseModel):
    id: int
    code: str
    status: str
    status_label: str
    warehouse_id: int
    vehicle_id: Optional[int] = None
    vehicle_plate: Optional[str] = None
    driver_name: Optional[str] = None
    weight_kg: float
    volume_m3: float
    max_weight_kg: Optional[float] = None
    max_volume_m3: Optional[float] = None
    note: Optional[str] = None
    created_at: Optional[datetime] = None
    dispatched_at: Optional[datetime] = None
    orders: list[ShipmentOrderOut]


# ---------------------------------------------------------------------------
# تعیین تکلیف
# ---------------------------------------------------------------------------
class DispositionCreate(BaseModel):
    product_id: int = Field(gt=0)
    warehouse_id: Optional[int] = Field(None, gt=0)
    from_status: Literal[STOCK_STATUSES]
    action: Literal[DISPOSITION_ACTIONS]
    quantity: int = Field(gt=0, le=10_000_000)
    location_id: Optional[int] = Field(None, gt=0)
    lot_number: Optional[LotNumber] = None
    partner_id: Optional[int] = Field(None, gt=0)
    receipt_id: Optional[int] = Field(None, gt=0)
    reason: Reason


class DispositionOut(BaseModel):
    id: int
    code: str
    action: str
    action_label: str
    warehouse_id: int
    warehouse_name: Optional[str] = None
    product_id: int
    product_name: str
    product_sku: str
    location_code: Optional[str] = None
    lot_number: Optional[str] = None
    from_status: str
    from_status_label: str
    quantity: int
    partner_name: Optional[str] = None
    receipt_id: Optional[int] = None
    reason: str
    document_id: Optional[int] = None
    document_code: Optional[str] = None
    created_at: Optional[datetime] = None
    created_by_name: Optional[str] = None
