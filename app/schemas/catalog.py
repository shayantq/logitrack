"""کاتالوگ کالا (مرحله ۱۳)."""
from datetime import date, datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, StringConstraints

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


class ProductDetail(BaseModel):
    id: int
    name: str
    sku: str
    weight_kg: Optional[float] = None
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


class ProductUpdate(BaseModel):
    name: Optional[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]] = None
    sku: Optional[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]] = None
    weight_kg: Optional[float] = Field(None, gt=0)
    category: Optional[Str(100)] = None
    brand: Optional[Str(100)] = None
    unit: Optional[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]] = None
    barcode: Optional[Str(64)] = None
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
