"""اسکیماهای پنل راننده: برنامه و کارنامه، پروفایل، درخواست مرخصی و تغییر خودرو."""
from datetime import date, datetime, timedelta
from typing import Any, Literal, Optional

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.schemas.driver import Plate, VehicleType
from app.schemas.geo_fields import city_in_province
from app.schemas.organization import Mobile, PostalCode, Province, Text

LeaveType = Literal["urgent", "normal"]
LeaveCategory = Literal["sickness", "family", "personal", "vehicle_repair", "other"]
MAX_LEAVE_DAYS = 30


class AgendaOrder(BaseModel):
    id: int
    tracking_code: str
    status: str
    priority: bool
    delivery_window_start: datetime
    delivery_window_end: datetime
    destination_city: str
    destination_address: Optional[str] = None
    recipient_name: Optional[str] = None
    total_weight_kg: float


class AgendaDay(BaseModel):
    date: date
    shifts: list[str]
    off: bool
    off_reason: Optional[str] = None
    orders: list[AgendaOrder]


class AgendaSummary(BaseModel):
    delivered: int
    failed: int
    active: int
    canceled: int
    delivered_kg: float


class AgendaResponse(BaseModel):
    days: list[AgendaDay]
    summary: AgendaSummary


class DriverProfileUpdate(BaseModel):
    """فقط اطلاعات تماس و سکونت؛ مشخصات هویتی و خودرو با درخواست/ادمین تغییر می‌کند."""
    mobile: Optional[Mobile] = None
    email: Optional[EmailStr] = None
    province: Optional[Province] = None
    city: Optional[Text(2, 64)] = None
    address: Optional[Text(10, 500)] = None
    postal_code: Optional[PostalCode] = None

    @model_validator(mode="after")
    def _known_city(self):
        city_in_province(self, "city", "province")
        return self


class LeaveRequestCreate(BaseModel):
    leave_type: LeaveType = Field(examples=["normal"])
    category: LeaveCategory = Field(examples=["family"])
    starts_at: datetime = Field(examples=["2026-10-20T00:00:00+03:30"])
    ends_at: datetime = Field(examples=["2026-10-21T00:00:00+03:30"])
    reason: Text(3, 500) = Field(examples=["مراسم خانوادگی"])

    @model_validator(mode="after")
    def check(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("پایان مرخصی باید بعد از شروع آن باشد.")
        if self.ends_at - self.starts_at > timedelta(days=MAX_LEAVE_DAYS):
            raise ValueError(f"هر درخواست مرخصی حداکثر {MAX_LEAVE_DAYS} روز است.")
        return self


class VehicleChangeCreate(BaseModel):
    vehicle_type: VehicleType
    vehicle_model: Text(2, 64)
    vehicle_color: Optional[Text(2, 32)] = None
    license_plate: Plate
    max_weight_kg: int = Field(gt=0, le=40000)
    inspection_expiry: Optional[date] = None
    note: Optional[Text(0, 500)] = None


class ReviewDecision(BaseModel):
    note: Optional[Text(0, 500)] = None


class RequestOrder(BaseModel):
    id: int
    tracking_code: str
    status: str
    delivery_window_start: datetime
    destination_city: str


class RequestDocument(BaseModel):
    kind: str
    content_type: str
    size_bytes: int
    uploaded_at: Optional[datetime] = None


class DriverRequestResponse(BaseModel):
    id: int
    kind: str
    status: str
    created_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    driver_id: int
    driver_name: str
    driver_code: Optional[str] = None

    leave_type: Optional[str] = None
    category: Optional[str] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    reason: Optional[str] = None
    # سفارش‌های راننده که با این مرخصی تداخل دارند (برای تصمیم ادمین)
    affected_orders: list[RequestOrder] = []

    vehicle_data: Optional[dict[str, Any]] = None
    current_vehicle: Optional[dict[str, Any]] = None
    documents: list[RequestDocument] = []
    required_documents: list[str] = []
    missing: list[str] = []

    reviewed_at: Optional[datetime] = None
    review_note: Optional[str] = None
