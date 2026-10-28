"""پیگیری عمومی سفارش با کد (مرحله ۹) — بدون ورود."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.core.rate_limit import RateLimiter
from app.database import db_dependency
from app.schemas.route import PublicRoute
from app.services import tracking_service
from app.services.exceptions import DomainError

router = APIRouter(prefix="/public/track", tags=["📍 پیگیری عمومی سفارش"])
# جلوی حدس زدن انبوه کدها از یک IP را می‌گیرد (کاربر عادی با به‌روزرسانی هر ۱۵ ثانیه به این سقف نمی‌رسد)
track_limiter = RateLimiter("track", max_requests=120, window_seconds=600)


class TrackStep(BaseModel):
    key: str
    label: str
    done: bool
    at: Optional[datetime] = None


class TrackDriver(BaseModel):
    first_name: Optional[str] = None
    vehicle_type: Optional[str] = None
    vehicle_model: Optional[str] = None


class TrackItem(BaseModel):
    name: str
    quantity: int


class TrackDetails(BaseModel):
    recipient_name: Optional[str] = None
    destination_address: Optional[str] = None
    items: list[TrackItem]
    total_weight_kg: float
    rating_token: Optional[str] = None


class TrackResponse(BaseModel):
    tracking_code: str
    status: str
    status_text: str
    is_final: bool
    organization_name: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    delivery_window_start: datetime
    delivery_window_end: datetime
    destination_province: Optional[str] = None
    destination_city: str
    recipient_masked: Optional[str] = None
    priority: bool
    steps: list[TrackStep]
    driver: Optional[TrackDriver] = None
    verified: bool
    details: Optional[TrackDetails] = None
    route: Optional[PublicRoute] = None


@router.get("/{code}", response_model=TrackResponse,
            summary="📍 وضعیت سفارش با کد پیگیری (با ۴ رقم آخر موبایل، جزئیات کامل)")
def track(code: str, request: Request, db: db_dependency,
          phone: Optional[str] = Query(None, description="۴ رقم آخر موبایل گیرنده برای دیدن نشانی و اقلام")):
    if not track_limiter.allow(request.client.host if request.client else "unknown"):
        raise HTTPException(status_code=429, detail="تعداد درخواست‌ها زیاد است؛ چند دقیقه دیگر تلاش کنید.")
    try:
        return tracking_service.track(db, code, phone)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
