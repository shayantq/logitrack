"""
API عمومی (بدون لاگین) برای فرم «درخواست استفاده از پسینه» در لندینگ پیج.
"""
from fastapi import APIRouter, HTTPException, Request
from starlette import status

from app.core.iran import PROVINCES
from app.core.rate_limit import organization_request_limiter
from app.database import db_dependency
from app.schemas.organization import (
    OrganizationRequestCreate, OrganizationRequestPublicStatus, OrganizationRequestSubmitted,
)
from app.services import organization_request_service
from app.services.exceptions import DomainError

router = APIRouter(
    prefix="/organization-requests",
    tags=["📝 درخواست استفاده از پسینه (عمومی)"]
)


@router.get("/form-options", summary="📋 گزینه‌های فرم درخواست (استان‌ها و ...)")
def form_options():
    return {"provinces": list(PROVINCES)}


@router.post("", status_code=status.HTTP_201_CREATED, response_model=OrganizationRequestSubmitted,
             summary="📝 ثبت درخواست استفاده از پسینه برای یک کسب‌وکار")
def submit_request(data: OrganizationRequestCreate, request: Request, db: db_dependency):
    client_ip = request.client.host if request.client else "unknown"
    if not organization_request_limiter.allow(client_ip):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="تعداد درخواست‌های شما زیاد است؛ لطفاً یک ساعت دیگر دوباره تلاش کنید.")

    success_message = "✅ درخواست شما ثبت شد. کارشناسان پسینه پس از بررسی با شما تماس می‌گیرند."
    if data.company_fax:
        # ربات فیلد مخفی را پر کرده — پاسخ عادی، بدون ذخیره
        return {"tracking_code": organization_request_service.fake_tracking_code(), "message": success_message}

    try:
        created = organization_request_service.submit_request(db, data, client_ip)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return {"tracking_code": created.tracking_code, "message": success_message}


@router.get("/status/{tracking_code}", response_model=OrganizationRequestPublicStatus,
            summary="🔎 پیگیری وضعیت درخواست با کد پیگیری")
def request_status(tracking_code: str, db: db_dependency):
    try:
        return organization_request_service.get_public_status(db, tracking_code)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
