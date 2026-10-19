from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import (
    AfterValidator, BaseModel, BeforeValidator, ConfigDict, EmailStr, Field, StringConstraints, model_validator,
)

from app.schemas.geo_fields import city_in_province
from app.core.iran import PROVINCES, normalize_digits, normalize_persian_text
from app.schemas.base import BaseModelWithDateFormatting

PackageSize = Literal["xs", "s", "m", "l", "xl"]
OrderStatus = Literal["pending", "assigned", "picking_up", "picked_up", "in_transit",
                      "delivered", "failed", "canceled", "expired"]


def _check_province(value: str) -> str:
    if value not in PROVINCES:
        raise ValueError("استان انتخاب‌شده معتبر نیست.")
    return value


def _text(min_len: int, max_len: int):
    return Annotated[str, BeforeValidator(normalize_persian_text), StringConstraints(min_length=min_len, max_length=max_len)]


PersonName = _text(2, 150)
CityName = _text(2, 64)
AddressText = _text(5, 500)
Mobile = Annotated[str, BeforeValidator(normalize_digits), StringConstraints(pattern=r"^09\d{9}$")]
PostalCode = Annotated[str, BeforeValidator(normalize_digits), StringConstraints(pattern=r"^\d{10}$")]
Province = Annotated[str, BeforeValidator(normalize_persian_text), AfterValidator(_check_province)]


# ---------------------------------------------------------------------------
# ورودی
# ---------------------------------------------------------------------------
class CustomerIn(BaseModel):
    name: PersonName = Field(examples=['امیرحسین رضایی'])
    mobile: Mobile = Field(examples=['09121234567'])
    email: Optional[EmailStr] = None


class OrderItemIn(BaseModel):
    product_id: int = Field(gt=0, examples=[1])
    quantity: int = Field(gt=0, le=100000, examples=[2])


class OrderRequest(BaseModel):
    items: list[OrderItemIn] = Field(min_length=1, max_length=100)
    customer: CustomerIn
    # اگر خالی باشد همان مشتری تحویل‌گیرنده است
    recipient_name: Optional[PersonName] = None
    recipient_mobile: Optional[Mobile] = None
    destination_province: Province = Field(examples=['قزوین'])
    destination_city: CityName = Field(examples=['قزوین'])
    destination_address: AddressText = Field(examples=['خیابان پیروزی، کوچه ۱۲، پلاک ۴'])
    destination_postal_code: Optional[PostalCode] = None

    size: PackageSize = Field(examples=['m'])
    priority: bool = Field(False, examples=[False])
    delivery_window_start: datetime = Field(examples=['2026-10-15T09:00:00Z'])
    delivery_window_end: datetime = Field(examples=['2026-10-15T13:00:00Z'])
    notes: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]] = None

    @model_validator(mode="after")
    def _known_city(self):
        city_in_province(self, "destination_city", "destination_province")
        return self

    # انبار مبدأ (اختیاری). برای مدیر انبار همیشه انبار خودش استفاده می‌شود.
    warehouse_id: Optional[int] = Field(None, gt=0, examples=[1])
    # خودروی مشخص؛ اگر نباشد و auto_assign=True خودرو خودکار انتخاب می‌شود، وگرنه سفارش «در انتظار تخصیص» می‌ماند
    vehicle_id: Optional[int] = Field(None, gt=0, examples=[1])
    auto_assign: bool = True
    # کرایه حمل (ریال)؛ خالی = محاسبه با فرمول سازمان (پایه + هر کیلو)
    delivery_fee: Optional[float] = Field(None, ge=0, le=10_000_000_000, examples=[750000])

    @model_validator(mode="after")
    def check_order(self):
        if self.delivery_window_end <= self.delivery_window_start:
            raise ValueError("پایان بازه تحویل باید بعد از شروع آن باشد.")
        product_ids = [item.product_id for item in self.items]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("هر کالا فقط یک‌بار در سفارش می‌آید؛ تعداد را در همان ردیف وارد کنید.")
        return self


class OrderStatusRequest(BaseModel):
    order_status: OrderStatus = Field(examples=['in_transit'])
    note: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]] = None


class OrderAssignRequest(BaseModel):
    # خالی = تخصیص خودکار بر اساس شهر مقصد و ظرفیت
    vehicle_id: Optional[int] = Field(None, gt=0)


# ---------------------------------------------------------------------------
# خروجی
# ---------------------------------------------------------------------------
class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    mobile: str
    email: Optional[str] = None


class OrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: Optional[int] = None
    product_name: str
    product_sku: Optional[str] = None
    quantity: int
    unit_price: float
    unit_weight_kg: float


class OrderStatusHistoryResponse(BaseModelWithDateFormatting):
    model_config = ConfigDict(from_attributes=True)

    id: int
    from_status: Optional[str] = None
    to_status: str
    changed_at: datetime
    changed_by_id: Optional[int] = None
    changed_by_name: Optional[str] = None
    note: Optional[str] = None


class OrderResponse(BaseModelWithDateFormatting):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tracking_code: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    status: str
    size: str
    priority: bool
    delivery_window_start: datetime
    delivery_window_end: datetime
    notes: Optional[str] = None

    customer: Optional[CustomerResponse] = None
    recipient_name: Optional[str] = None
    recipient_mobile: Optional[str] = None
    destination_province: Optional[str] = None
    destination_city: str
    destination_address: Optional[str] = None
    destination_postal_code: Optional[str] = None

    warehouse_id: Optional[int] = None
    vehicle_id: Optional[int] = None
    items: list[OrderItemResponse] = []
    total_quantity: int = 0
    total_weight_kg: float = 0
    total_price: float = 0
    # مرحله ۸: کرایه و تسویه منجمدشده در لحظه تحویل
    driver_id: Optional[int] = None
    delivery_fee: Optional[float] = None
    delivered_at: Optional[datetime] = None
    commission_level: Optional[str] = None
    day_trip_number: Optional[int] = None
    commission_percent: Optional[float] = None
    commission_amount: Optional[float] = None
    driver_earning: Optional[float] = None


class OrderDetailResponse(OrderResponse):
    history: list[OrderStatusHistoryResponse] = []

    @classmethod
    def from_order(cls, order) -> "OrderDetailResponse":
        data = OrderResponse.model_validate(order).model_dump()
        data["history"] = [
            OrderStatusHistoryResponse(
                id=h.id, from_status=h.from_status, to_status=h.to_status, changed_at=h.changed_at,
                changed_by_id=h.changed_by_id, note=h.note,
                changed_by_name=(h.changed_by.full_name or h.changed_by.username) if h.changed_by else None,
            )
            for h in order.history
        ]
        return cls(**data)
