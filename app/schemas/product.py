from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, constr, model_validator


class ProductCreate(BaseModel):
    name: constr(min_length=1, max_length=200, strip_whitespace=True)
    sku: constr(min_length=1, max_length=64, strip_whitespace=True)
    price: float = Field(ge=0, description="قیمت پایه (ریال)")
    weight_kg: float = Field(1.0, gt=0, examples=[1.5])
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
    quantity: int


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    sku: str
    weight_kg: Optional[float] = None
    price: float
    stock: int = 0
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


class StockUpdate(BaseModel):
    quantity: int = Field(ge=0)
    reorder_point: int = Field(10, ge=0)
    # برای ادمین وقتی کالا در چند انبار موجودی دارد الزامی است؛ مدیر انبار همیشه انبار خودش
    warehouse_id: Optional[int] = Field(None, gt=0)
    reason: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]] = None


Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class StockMovementCreate(BaseModel):
    """
    ثبت دستی گردش:
      receipt   = ورود کالا (quantity مثبت)
      damage    = ضایعات/کسری (quantity مثبت، از موجودی کم می‌شود) — دلیل الزامی
      adjustment = اصلاح (quantity مثبت یا منفی) — دلیل الزامی
    """
    product_id: int = Field(gt=0)
    warehouse_id: Optional[int] = Field(None, gt=0)
    movement_type: Literal["receipt", "damage", "adjustment"]
    quantity: int
    reason: Optional[Reason] = None

    @model_validator(mode="after")
    def check_quantity_and_reason(self):
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

    @model_validator(mode="after")
    def check_different_warehouses(self):
        if self.from_warehouse_id == self.to_warehouse_id:
            raise ValueError("انبار مبدأ و مقصد نمی‌توانند یکی باشند.")
        return self


class StockMovementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: Optional[datetime] = None
    product_id: int
    product_name: Optional[str] = None
    product_sku: Optional[str] = None
    warehouse_id: Optional[int] = None
    warehouse_name: Optional[str] = None
    movement_type: str
    quantity_change: int
    balance_after: int
    reason: Optional[str] = None
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None
    created_by_id: Optional[int] = None
    created_by_name: Optional[str] = None

    @classmethod
    def from_movement(cls, m) -> "StockMovementResponse":
        return cls(
            id=m.id, created_at=m.created_at, product_id=m.product_id,
            product_name=m.product.name if m.product else None, product_sku=m.product.sku if m.product else None,
            warehouse_id=m.warehouse_id, warehouse_name=m.warehouse.name if m.warehouse else None,
            movement_type=m.movement_type, quantity_change=m.quantity_change, balance_after=m.balance_after,
            reason=m.reason, reference_type=m.reference_type, reference_id=m.reference_id,
            created_by_id=m.created_by_id,
            created_by_name=(m.created_by.full_name or m.created_by.username) if m.created_by else None,
        )
