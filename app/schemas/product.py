from datetime import date, datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, constr, model_validator

from app.core.wms import STOCK_STATUSES

StockStatus = Literal[STOCK_STATUSES]
# SKU: کد یکتا و تغییرناپذیر، بدون فاصله
Sku = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64, pattern=r"^\S+$")]
Barcode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=4, max_length=64, pattern=r"^[0-9A-Za-z-]+$")]
UomName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
IdempotencyKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{8,64}$")]
# بچ و سریال: بدون فاصله، حروف بزرگ (اسکن و جست‌وجو بدون حساسیت به حروف)
LotNumber = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=64,
                                             pattern=r"^[0-9A-Za-z._/-]+$")]
SerialNumber = LotNumber


def _unique_serials(values: list[str]) -> list[str]:
    if len(set(values)) != len(values):
        raise ValueError("شماره سریال تکراری وارد شده است.")
    return values


class ProductMasterFields(BaseModel):
    """مشخصات پایه کالا (Master Data) — مشترک بین ثبت و ویرایش؛ قواعد بین فیلدها در catalog_service.validate_master."""
    short_name: Optional[constr(max_length=60, strip_whitespace=True)] = None
    barcode: Optional[Barcode] = None
    net_weight_kg: Optional[float] = Field(None, gt=0)
    length_cm: Optional[float] = Field(None, gt=0, le=10000)
    width_cm: Optional[float] = Field(None, gt=0, le=10000)
    height_cm: Optional[float] = Field(None, gt=0, le=10000)
    lot_tracked: bool = False
    serial_tracked: bool = False
    expiry_tracked: bool = False
    shelf_life_days: Optional[int] = Field(None, gt=0, le=36500)
    min_stock: Optional[int] = Field(None, ge=0)
    max_stock: Optional[int] = Field(None, ge=0)
    reorder_point: Optional[int] = Field(None, ge=0)
    inspection_required: bool = False
    units_per_pallet: Optional[int] = Field(None, gt=0, le=1_000_000)


class ProductCreate(ProductMasterFields):
    name: constr(min_length=1, max_length=200, strip_whitespace=True)
    sku: Sku
    price: float = Field(ge=0, description="قیمت پایه (ریال)")
    weight_kg: float = Field(1.0, gt=0, examples=[1.5], description="وزن ناخالص هر واحد پایه")
    initial_quantity: int = Field(0, ge=0)
    warehouse_id: Optional[int] = None
    # مرحله ۱۳ — همه اختیاری
    subsidy_percent: float = Field(0, ge=0, lt=100)
    category: Optional[constr(max_length=100, strip_whitespace=True)] = None
    brand: Optional[constr(max_length=100, strip_whitespace=True)] = None
    unit: constr(min_length=1, max_length=32, strip_whitespace=True) = "عدد"
    origin: Literal["domestic", "imported"] = "domestic"
    origin_country: Optional[constr(max_length=64, strip_whitespace=True)] = None


class WarehouseStock(BaseModel):
    warehouse_id: Optional[int] = None
    warehouse_name: str
    city: Optional[str] = None
    quantity: int                    # موجودی سالم (فیزیکی)
    reserved: int = 0                # رزرو سفارش‌های باز
    free: int = 0                    # موجودی آزاد = موجودی سالم − رزرو
    ships_orders: bool = True        # از این انبار سفارش ارسال می‌شود؟


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    sku: str
    weight_kg: Optional[float] = None
    price: float
    stock: int = 0                   # موجودی سالم (فیزیکی، شامل رزرو)
    reserved: int = 0
    free_stock: int = 0
    # موجودی غیرقابل‌فروش به تفکیک وضعیت کیفی، مثل {"quarantine": 4}
    held_stock: dict[str, int] = {}
    ever_high_stock: bool = False
    # موجودی به تفکیک انبار (برای انتخاب کالا در فرم سفارش)
    stock_by_warehouse: list[WarehouseStock] = []
    # مرحله ۱۳
    category: Optional[str] = None
    unit: str = "عدد"
    origin: str = "domestic"
    origin_country: Optional[str] = None
    parent_id: Optional[int] = None
    variant_label: Optional[str] = None
    subsidy_percent: float = 0
    is_active: bool = True
    barcode: Optional[str] = None


class StockUpdate(BaseModel):
    quantity: int = Field(ge=0)
    reorder_point: int = Field(10, ge=0)
    # برای ادمین وقتی کالا در چند انبار موجودی دارد الزامی است؛ مدیر انبار همیشه انبار خودش
    warehouse_id: Optional[int] = Field(None, gt=0)
    reason: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]] = None


Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class StockMovementCreate(BaseModel):
    """
    ثبت دستی گردش (هر درخواست یک سند انبار):
      receipt   = رسید ورود کالا (quantity مثبت) — وضعیت کیفی پیش‌فرض از نوع انبار (مثلاً قرنطینه)
      damage    = ضایعات/کسری (quantity مثبت، از موجودی کم می‌شود) — دلیل الزامی
      adjustment = اصلاح (quantity مثبت یا منفی) — دلیل الزامی
    quantity به واحد uom است (خالی = واحد پایه) و به واحد پایه تبدیل می‌شود.
    """
    product_id: int = Field(gt=0)
    warehouse_id: Optional[int] = Field(None, gt=0)
    movement_type: Literal["receipt", "damage", "adjustment"]
    quantity: int
    reason: Optional[Reason] = None
    stock_status: Optional[StockStatus] = None
    uom: Optional[UomName] = None
    partner_id: Optional[int] = Field(None, gt=0, description="تأمین‌کننده (فقط رسید)")
    external_ref: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=64)]] = None
    # محل و بچ: ورود به همین محل/بچ؛ خروج (ضایعات/اصلاح منفی) فقط از همین محل/بچ (خالی = برداشت خودکار FEFO)
    location_id: Optional[int] = Field(None, gt=0)
    lot_number: Optional[LotNumber] = None
    expiry_date: Optional[date] = None
    serial_numbers: list[SerialNumber] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def check_quantity_and_reason(self):
        _unique_serials(self.serial_numbers)
        if self.quantity == 0:
            raise ValueError("مقدار گردش نمی‌تواند صفر باشد.")
        if self.movement_type in ("receipt", "damage") and self.quantity < 0:
            raise ValueError("برای ورود کالا و ضایعات، مقدار را مثبت وارد کنید.")
        if self.movement_type in ("damage", "adjustment") and not self.reason:
            raise ValueError("برای ضایعات و اصلاح موجودی، ذکر دلیل الزامی است.")
        return self


class StockTransferCreate(BaseModel):
    product_id: int = Field(gt=0)
    from_warehouse_id: int = Field(gt=0)
    to_warehouse_id: int = Field(gt=0)
    quantity: int = Field(gt=0)
    reason: Optional[Reason] = None
    stock_status: StockStatus = "available"
    uom: Optional[UomName] = None
    from_location_id: Optional[int] = Field(None, gt=0)
    to_location_id: Optional[int] = Field(None, gt=0)
    lot_number: Optional[LotNumber] = None

    @model_validator(mode="after")
    def check_different_warehouses(self):
        if self.from_warehouse_id == self.to_warehouse_id:
            raise ValueError("انبار مبدأ و مقصد نمی‌توانند یکی باشند.")
        return self


class StatusChangeCreate(BaseModel):
    """تغییر وضعیت کیفی (مثلاً قرنطینه ← سالم و آزاد پس از بازرسی) — یک سند با دو گردش."""
    product_id: int = Field(gt=0)
    warehouse_id: Optional[int] = Field(None, gt=0)
    from_status: StockStatus
    to_status: StockStatus
    quantity: int = Field(gt=0)
    uom: Optional[UomName] = None
    reason: Reason
    # محدود به یک محل/بچ (خالی = برداشت خودکار)؛ کالا در همان محل می‌ماند
    location_id: Optional[int] = Field(None, gt=0)
    lot_number: Optional[LotNumber] = None

    @model_validator(mode="after")
    def check_statuses(self):
        if self.from_status == self.to_status:
            raise ValueError("وضعیت مبدأ و مقصد نمی‌توانند یکی باشند.")
        return self


class LocationMoveCreate(BaseModel):
    """جابه‌جایی داخل انبار: از یک محل (یا «بدون محل» با from_location_id خالی) به محل دیگر."""
    product_id: int = Field(gt=0)
    warehouse_id: Optional[int] = Field(None, gt=0)
    from_location_id: Optional[int] = Field(None, gt=0)
    to_location_id: int = Field(gt=0)
    quantity: int = Field(gt=0)
    uom: Optional[UomName] = None
    stock_status: StockStatus = "available"
    lot_number: Optional[LotNumber] = None
    reason: Optional[Reason] = None


class MovementLineOut(BaseModel):
    """بخشی از یک گردش: چه مقدار از کدام محل/بچ/سریال/مالک."""
    location_id: Optional[int] = None
    location_code: Optional[str] = None
    lot_number: Optional[str] = None
    serial_number: Optional[str] = None
    expiry_date: Optional[date] = None
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None
    quantity_change: int
    balance_after: int


class StockMovementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: Optional[datetime] = None
    document_id: Optional[int] = None
    document_code: Optional[str] = None
    document_type: Optional[str] = None
    document_status: Optional[str] = None
    product_id: int
    product_name: Optional[str] = None
    product_sku: Optional[str] = None
    warehouse_id: Optional[int] = None
    warehouse_name: Optional[str] = None
    stock_status: str = "available"
    reversal_of_id: Optional[int] = None
    movement_type: str
    quantity_change: int
    balance_after: int
    reason: Optional[str] = None
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None
    created_by_id: Optional[int] = None
    created_by_name: Optional[str] = None
    lines: list[MovementLineOut] = []

    @classmethod
    def from_movement(cls, m) -> "StockMovementResponse":
        doc = m.document
        return cls(
            id=m.id, created_at=m.created_at, product_id=m.product_id,
            document_id=m.document_id, document_code=doc.code if doc else None,
            document_type=doc.doc_type if doc else None, document_status=doc.status if doc else None,
            stock_status=m.stock_status or "available", reversal_of_id=m.reversal_of_id,
            product_name=m.product.name if m.product else None, product_sku=m.product.sku if m.product else None,
            warehouse_id=m.warehouse_id, warehouse_name=m.warehouse.name if m.warehouse else None,
            movement_type=m.movement_type, quantity_change=m.quantity_change, balance_after=m.balance_after,
            reason=m.reason, reference_type=m.reference_type, reference_id=m.reference_id,
            created_by_id=m.created_by_id,
            created_by_name=(m.created_by.full_name or m.created_by.username) if m.created_by else None,
            lines=[MovementLineOut(
                location_id=line.location_id, location_code=line.location.code if line.location else None,
                lot_number=line.lot_number, serial_number=line.serial_number, expiry_date=line.expiry_date,
                owner_id=line.owner_id, owner_name=line.owner.name if line.owner else None,
                quantity_change=line.quantity_change, balance_after=line.balance_after,
            ) for line in m.lines],
        )
