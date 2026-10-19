"""پنل راننده (برنامه و کارنامه، پروفایل، درخواست‌ها) و بررسی درخواست‌های رانندگان توسط ادمین."""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, UploadFile
from fastapi.responses import FileResponse

from app.database import db_dependency
from app.dependencies import require_role
from app.models import RoleEnum
from app.schemas.driver_portal import (
    AgendaResponse, DriverProfileUpdate, DriverRequestResponse, LeaveRequestCreate, ReviewDecision, VehicleChangeCreate,
)
from app.schemas.driver import DriverApplicationResponse
from app.services import driver_portal_service as portal
from app.services import driver_service
from app.services.exceptions import DomainError
from app.services.schedule_service import today_local

VehicleDocument = Literal["vehicle_photo", "vehicle_card", "technical_inspection"]
driver_only = require_role([RoleEnum.DRIVER])
org_admin = require_role([RoleEnum.ORG_ADMIN])


class DriverProfileResponse(DriverApplicationResponse):
    email: Optional[str] = None
    current_vehicle: Optional[dict] = None


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


def _file(path_and_type):
    path, media_type = path_and_type
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=300"})


# ---------------------------------------------------------------------------
# راننده
# ---------------------------------------------------------------------------
driver_router = APIRouter(prefix="/driver", tags=["🚚 پنل راننده"])


@driver_router.get("/agenda", response_model=AgendaResponse, summary="📅 سفارش‌های من روزبه‌روز (آینده و گذشته)")
def agenda(db: db_dependency, start: Optional[date] = None, days: int = 7, user=Depends(driver_only)):
    return _call(portal.agenda, db, user, start or today_local(), days)


@driver_router.get("/profile", response_model=DriverProfileResponse, summary="👤 پروفایل من")
def profile(db: db_dependency, user=Depends(driver_only)):
    return _call(portal.my_profile, db, user)


@driver_router.put("/profile", response_model=DriverProfileResponse, summary="✏️ ویرایش اطلاعات تماس و سکونت")
def update_profile(data: DriverProfileUpdate, db: db_dependency, user=Depends(driver_only)):
    return _call(portal.update_my_profile, db, user, data)


@driver_router.get("/requests", response_model=list[DriverRequestResponse], summary="📨 درخواست‌های من")
def my_requests(db: db_dependency, user=Depends(driver_only)):
    return _call(portal.my_requests, db, user)


@driver_router.post("/requests/leave", response_model=DriverRequestResponse, status_code=201, summary="🏖️ درخواست مرخصی فوری/عادی")
def request_leave(data: LeaveRequestCreate, db: db_dependency, user=Depends(driver_only)):
    return _call(portal.create_leave, db, user, data)


@driver_router.post("/requests/vehicle", response_model=DriverRequestResponse, status_code=201,
                    summary="🚗 شروع درخواست تغییر خودرو (سپس آپلود مدارک و ارسال)")
def request_vehicle_change(data: VehicleChangeCreate, db: db_dependency, user=Depends(driver_only)):
    return _call(portal.create_vehicle_change, db, user, data)


@driver_router.post("/requests/{request_id}/documents/{kind}", response_model=DriverRequestResponse, summary="📎 مدرک خودروی جدید")
async def upload_request_document(kind: VehicleDocument, file: UploadFile, db: db_dependency,
                                  request_id: int = Path(gt=0), user=Depends(driver_only)):
    data = await file.read(driver_service.MAX_IMAGE_BYTES + 1)
    return _call(portal.upload_request_document, db, user, request_id, kind, data)


@driver_router.get("/requests/{request_id}/documents/{kind}", summary="📎 دریافت مدرک درخواست خودم")
def my_request_document(kind: VehicleDocument, db: db_dependency, request_id: int = Path(gt=0), user=Depends(driver_only)):
    return _file(_call(portal.request_document_file, db, user, request_id, kind))


@driver_router.post("/requests/{request_id}/submit", response_model=DriverRequestResponse, summary="📨 ارسال درخواست تغییر خودرو")
def submit_request(db: db_dependency, request_id: int = Path(gt=0), user=Depends(driver_only)):
    return _call(portal.submit_vehicle_change, db, user, request_id)


@driver_router.post("/requests/{request_id}/cancel", response_model=DriverRequestResponse, summary="↩️ لغو درخواست")
def cancel_request(db: db_dependency, request_id: int = Path(gt=0), user=Depends(driver_only)):
    return _call(portal.cancel_my_request, db, user, request_id)


# ---------------------------------------------------------------------------
# ادمین سازمان
# ---------------------------------------------------------------------------
admin_router = APIRouter(prefix="/driver-requests", tags=["📨 درخواست‌های رانندگان (ادمین سازمان)"])


@admin_router.get("", response_model=list[DriverRequestResponse], summary="📨 درخواست‌های رانندگان")
def list_requests(db: db_dependency, status: Optional[Literal["pending", "approved", "rejected", "canceled"]] = None,
                  kind: Optional[Literal["leave", "vehicle_change"]] = None, user=Depends(org_admin)):
    return _call(portal.list_requests, db, user, status, kind)


@admin_router.get("/pending-count", summary="🔢 تعداد درخواست‌های منتظر (و فوری)")
def pending_count(db: db_dependency, user=Depends(org_admin)):
    return _call(portal.pending_counts, db, user)


@admin_router.post("/{request_id}/approve", response_model=DriverRequestResponse, summary="✅ تأیید درخواست")
def approve(data: ReviewDecision, db: db_dependency, request_id: int = Path(gt=0), user=Depends(org_admin)):
    return _call(portal.approve_request, db, user, request_id, data.note)


@admin_router.post("/{request_id}/reject", response_model=DriverRequestResponse, summary="⛔ رد درخواست (با دلیل)")
def reject(data: ReviewDecision, db: db_dependency, request_id: int = Path(gt=0), user=Depends(org_admin)):
    return _call(portal.reject_request, db, user, request_id, data.note)


@admin_router.get("/{request_id}/documents/{kind}", summary="📎 مدرک درخواست تغییر خودرو")
def request_document(kind: VehicleDocument, db: db_dependency, request_id: int = Path(gt=0), user=Depends(org_admin)):
    return _file(_call(portal.request_document_file, db, user, request_id, kind))
