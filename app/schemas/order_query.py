"""پارامترهای مشترک فهرست و صفحه‌بندی سفارش؛ هر دو مسیر دقیقاً یک اعتبارسنجی دارند."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.order import OrderResponse, OrderStatus


class OrderListQuery(BaseModel):
    order_status: OrderStatus | None = None
    province: str | None = None
    city: str | None = None
    q: str | None = Field(None, min_length=2)
    vehicle_id: int | None = Field(None, gt=0)
    date_from: datetime | None = None
    date_to: datetime | None = None
    skip: int = Field(0, ge=0)
    limit: int = Field(100, ge=1, le=500)
    tracking_code: str | None = Field(None, min_length=2)
    product: str | None = Field(None, min_length=2)
    driver_id: int | None = Field(None, gt=0)
    driver: str | None = Field(None, min_length=2)
    plate: str | None = Field(None, min_length=2)
    delivery_from: date | None = None
    delivery_to: date | None = None
    priority: bool | None = None
    sort: Literal["tracking_code", "destination_city", "delivery_window_start", "status"] | None = None
    direction: Literal["asc", "desc"] = "desc"
    view: Literal["late", "today", "needs_update", "awaiting_resolution", "at_risk", "driver_returns", "customer_requests"] | None = None


class OrderPage(BaseModel):
    items: list[OrderResponse]
    total: int
    skip: int
    limit: int
