"""کاتالوگ کالا (مرحله ۱۳)."""
from datetime import date, datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.product import Barcode, UomName

Str = lambda n: Annotated[str, StringConstraints(strip_whitespace=True, max_length=n)]  # noqa: E731
Origin = Literal["domestic", "imported"]


class PriceOut(BaseModel):
    id: int
    effective_from: date
    base_price: float
    subsidy_percent: float
    final_price: float
    cost_price: Optional[float] = None
    note: Optional[str] = None
    created_by: Optional[str] = None
    is_current: bool
    is_future: bool


class VariantOut(BaseModel):
    id: int
    name: str
    sku: str
    variant_label: Optional[str] = None
    origin: str
    origin_country: Optional[str] = None
    price: float
    stock: int


class ProductRef(BaseModel):
    id: int
    name: str
    sku: str


class StockRow(BaseModel):
    warehouse_id: Optional[int] = None
    warehouse_name: str
    quantity: int
    reorder_point: Optional[int] = None
    stock_status: str = "available"
    reserved: int = 0
    free: int = 0


class UomOut(BaseModel):
    id: int
    name: str
    factor: int
    barcode: Optional[str] = None
    is_purchase_default: bool = False
    is_sales_default: bool = False


class UomIn(BaseModel):
    name: UomName
    factor: int = Field(ge=2, le=1_000_000, description="چند واحد پایه")
    barcode: Optional[Barcode] = None
    is_purchase_default: bool = False
    is_sales_default: bool = False


class SupplierLinkOut(BaseModel):
    id: int
    partner_id: int
    partner_code: str
    partner_name: str
    supplier_sku: Optional[str] = None
    lead_time_days: Optional[int] = None
    min_order_qty: Optional[int] = None
    last_price: Optional[float] = None
    is_preferred: bool = False


class SupplierLinkIn(BaseModel):
    partner_id: int = Field(gt=0)
    supplier_sku: Optional[Str(64)] = None
    lead_time_days: Optional[int] = Field(None, ge=0, le=365)
    min_order_qty: Optional[int] = Field(None, gt=0)
    last_price: Optional[float] = Field(None, ge=0)
    is_preferred: bool = False


class ProductDetail(BaseModel):
    id: int
    name: str
    short_name: Optional[str] = None
    sku: str
    weight_kg: Optional[float] = None
    net_weight_kg: Optional[float] = None
    length_cm: Optional[float] = None
    width_cm: Optional[float] = None
    height_cm: Optional[float] = None
    volume_m3: Optional[float] = None
    lot_tracked: bool = False
    serial_tracked: bool = False
    expiry_tracked: bool = False
    inspection_required: bool = False
    units_per_pallet: Optional[int] = None
    shelf_life_days: Optional[int] = None
    min_stock: Optional[int] = None
    max_stock: Optional[int] = None
    reorder_point: Optional[int] = None
    price: float
    category: Optional[str] = None
    brand: Optional[str] = None
    unit: str
    barcode: Optional[str] = None
    description: Optional[str] = None
    origin: str
    origin_country: Optional[str] = None
    export_eligible: bool
    hs_code: Optional[str] = None
    specs: list[list[str]] = []
    parent_id: Optional[int] = None
    variant_label: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    current_price: float
    current_base_price: float
    current_subsidy_percent: float
    prices: list[PriceOut]
    parent: Optional[ProductRef] = None
    variants: list[VariantOut]
    stock: list[StockRow]
    uoms: list[UomOut] = []
    suppliers: list[SupplierLinkOut] = []


class ProductUpdate(BaseModel):
    """ویرایش جزئی. SKU تغییرناپذیر است (اگر فرستاده شود باید همان کد فعلی باشد)."""
    name: Optional[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]] = None
    sku: Optional[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]] = None
    short_name: Optional[Str(60)] = None
    weight_kg: Optional[float] = Field(None, gt=0)
    net_weight_kg: Optional[float] = Field(None, gt=0)
    length_cm: Optional[float] = Field(None, gt=0, le=10000)
    width_cm: Optional[float] = Field(None, gt=0, le=10000)
    height_cm: Optional[float] = Field(None, gt=0, le=10000)
    lot_tracked: Optional[bool] = None
    serial_tracked: Optional[bool] = None
    expiry_tracked: Optional[bool] = None
    inspection_required: Optional[bool] = None
    units_per_pallet: Optional[int] = Field(None, gt=0, le=1_000_000)
    shelf_life_days: Optional[int] = Field(None, gt=0, le=36500)
    min_stock: Optional[int] = Field(None, ge=0)
    max_stock: Optional[int] = Field(None, ge=0)
    reorder_point: Optional[int] = Field(None, ge=0)
    category: Optional[Str(100)] = None
    brand: Optional[Str(100)] = None
    unit: Optional[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]] = None
    barcode: Optional[Barcode] = None
    description: Optional[Str(3000)] = None
    origin: Optional[Origin] = None
    origin_country: Optional[Str(64)] = None
    export_eligible: Optional[bool] = None
    hs_code: Optional[Str(16)] = None
    specs: Optional[list[Annotated[list[Str(120)], Field(min_length=2, max_length=2)]]] = Field(None, max_length=50)
    variant_label: Optional[Str(100)] = None
    is_active: Optional[bool] = None


class PriceIn(BaseModel):
    effective_from: date
    base_price: float = Field(ge=0)
    subsidy_percent: float = Field(0, ge=0, lt=100)
    cost_price: Optional[float] = Field(None, ge=0)
    note: Optional[Str(300)] = None


class VariantIn(BaseModel):
    sku: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    variant_label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100)]
    name: Optional[Str(200)] = None
    origin: Optional[Origin] = None
    origin_country: Optional[Str(64)] = None
    base_price: float = Field(ge=0)
    subsidy_percent: float = Field(0, ge=0, lt=100)
    effective_from: Optional[date] = None
    specs: Optional[list[Annotated[list[Str(120)], Field(min_length=2, max_length=2)]]] = None


class ImportError_(BaseModel):
    line: int
    sku: Optional[str] = None
    messages: list[str]


class ImportPreviewRow(BaseModel):
    line: int
    sku: Optional[str] = None
    name: Optional[str] = None
    action: str
    price: Optional[float] = None
    warehouse: Optional[str] = None
    quantity: Optional[int] = None
    ok: bool


class ImportReport(BaseModel):
    rows: int
    create: int
    update: int
    stock_rows: int
    errors: list[ImportError_]
    error_count: int
    applied: bool
    stock_mode: str
    preview: list[ImportPreviewRow]
