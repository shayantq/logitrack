"""
ثبت‌نام و احراز هویت رانندگان:
- عمومی (/driver-signup): مشاهده لینک دعوت و ساخت حساب راننده
- راننده (/driver-onboarding): تکمیل پرونده، آپلود مدارک، ارسال برای بررسی
- ادمین سازمان (/drivers): لینک‌های دعوت، بررسی پرونده‌ها، تأیید/رد، مشاهده مدارک
"""
from datetime import timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Request, UploadFile
from fastapi.responses import FileResponse

from app.core.rate_limit import driver_signup_limiter
from app.core.security import ACCESS_TOKEN_EXPIRE_MINUTES, create_access_token
from app.database import db_dependency
from app.dependencies import require_role, user_dependency
from app.models import RoleEnum, User
from app.schemas.driver import (
    DocumentKind, DriverApplicationResponse, DriverApplicationUpdate, DriverInviteCreate, DriverInvitePublic,
    DriverInviteResponse, DriverInviteUpdate, DriverRejectRequest, DriverSignupRequest, DriverSignupResponse,
)
from app.services import driver_service
from app.services.exceptions import DomainError
from app.services import audit_service

DriverStatus = Literal["incomplete", "submitted", "approved", "rejected"]
org_admin = require_role([RoleEnum.ORG_ADMIN])
driver_only = require_role([RoleEnum.DRIVER])


def _call(fn, *args):
    try:
        return fn(*args)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


def _file(path_and_type):
    path, media_type = path_and_type
    # private: فقط مرورگر همان کاربر کش کند، نه پراکسی‌های میانی
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=300"})


# ---------------------------------------------------------------------------
# عمومی — بدون لاگین
# ---------------------------------------------------------------------------
public_router = APIRouter(prefix="/driver-signup", tags=["🚚 ثبت‌نام راننده (عمومی)"])


@public_router.get("/{code}", response_model=DriverInvitePublic, summary="🔗 بررسی لینک دعوت")
def invite_info(code: str, db: db_dependency):
    return _call(driver_service.invite_info, db, code)


@public_router.post("/{code}", response_model=DriverSignupResponse, status_code=201,
                    summary="📝 ساخت حساب راننده با لینک دعوت (خروجی: توکن ورود)")
def signup(code: str, data: DriverSignupRequest, request: Request, db: db_dependency):
    client_ip = request.client.host if request.client else "unknown"
    if not driver_signup_limiter.allow(client_ip):
        raise HTTPException(status_code=429, detail="تعداد ثبت‌نام‌ها زیاد است؛ لطفاً یک ساعت دیگر تلاش کنید.")
    user = _call(driver_service.signup, db, code, data)
    token = create_access_token(user.username, user.id, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    return {"access_token": token, "token_type": "bearer"}


# ---------------------------------------------------------------------------
# راننده — پرونده خودش
# ---------------------------------------------------------------------------
onboarding_router = APIRouter(prefix="/driver-onboarding", tags=["🪪 احراز هویت راننده (خود راننده)"])


@onboarding_router.get("", response_model=DriverApplicationResponse, summary="🪪 پرونده من")
def my_application(db: db_dependency, user=Depends(driver_only)):
    return _call(driver_service.get_my_application, db, user)


@onboarding_router.put("", response_model=DriverApplicationResponse, summary="✏️ ذخیره اطلاعات یک مرحله")
def update_my_application(data: DriverApplicationUpdate, db: db_dependency, user=Depends(driver_only)):
    return _call(driver_service.update_my_application, db, user, data)


@onboarding_router.post("/documents/{kind}", response_model=DriverApplicationResponse,
                        summary="📎 آپلود مدرک (تصویر تا ۵ مگابایت، ویدیو تا ۳۰ مگابایت و ۱۵ ثانیه)")
async def upload_document(kind: DocumentKind, file: UploadFile, db: db_dependency, user=Depends(driver_only)):
    limit = driver_service.MAX_VIDEO_BYTES if kind == "video" else driver_service.MAX_IMAGE_BYTES
    data = await file.read(limit + 1)
    return _call(driver_service.upload_document, db, user, kind, data)


@onboarding_router.get("/documents/{kind}", summary="📎 دریافت مدرک خودم")
def my_document(kind: DocumentKind, db: db_dependency, user=Depends(driver_only)):
    return _file(_call(driver_service.document_file, db, user, user.id, kind))


@onboarding_router.post("/submit", response_model=DriverApplicationResponse, summary="📨 ارسال پرونده برای بررسی")
def submit(db: db_dependency, user=Depends(driver_only)):
    return _call(driver_service.submit_my_application, db, user)


# ---------------------------------------------------------------------------
# ادمین سازمان
# ---------------------------------------------------------------------------
admin_router = APIRouter(prefix="/drivers", tags=["🛂 بررسی رانندگان (ادمین سازمان)"])


@admin_router.get("/invites", response_model=list[DriverInviteResponse], summary="🔗 لینک‌های دعوت")
def list_invites(db: db_dependency, user=Depends(org_admin)):
    return _call(driver_service.list_invites, db, user)


@admin_router.post("/invites", response_model=DriverInviteResponse, status_code=201, summary="➕ ساخت لینک دعوت")
def create_invite(data: DriverInviteCreate, db: db_dependency, user=Depends(org_admin)):
    invite = _call(driver_service.create_invite, db, user, data)
    audit_service.record(db, user, "driver.invite", f"لینک دعوت راننده {invite['code']} ساخته شد", target_type="invite",
                         target_id=invite["id"], target_label=invite["code"])
    return invite


@admin_router.patch("/invites/{invite_id}", response_model=DriverInviteResponse, summary="⏯️ فعال/غیرفعال کردن لینک دعوت")
def update_invite(data: DriverInviteUpdate, db: db_dependency, invite_id: int = Path(gt=0), user=Depends(org_admin)):
    return _call(driver_service.set_invite_active, db, user, invite_id, data.is_active)


@admin_router.get("/applications", response_model=list[DriverApplicationResponse], summary="🗂️ پرونده‌های رانندگان")
def list_applications(db: db_dependency, status: Optional[DriverStatus] = None, user=Depends(org_admin)):
    return _call(driver_service.list_applications, db, user, status)


@admin_router.get("/applications/pending-count", summary="🔢 تعداد پرونده‌های منتظر بررسی")
def pending_count(db: db_dependency, user=Depends(org_admin)):
    return {"count": _call(driver_service.pending_count, db, user)}


@admin_router.get("/applications/{driver_id}", response_model=DriverApplicationResponse, summary="🪪 جزئیات پرونده")
def get_application(db: db_dependency, driver_id: int = Path(gt=0), user=Depends(org_admin)):
    return _call(driver_service.get_application, db, user, driver_id)


@admin_router.post("/applications/{driver_id}/approve", response_model=DriverApplicationResponse,
                   summary="✅ تأیید راننده (خودرویش به ناوگان اضافه می‌شود)")
def approve(db: db_dependency, driver_id: int = Path(gt=0), user=Depends(org_admin)):
    result = _call(driver_service.approve, db, user, driver_id)
    driver = db.get(User, driver_id)
    audit_service.record(db, user, "driver.approve", f"پرونده راننده «{driver.full_name or driver.username}» تأیید شد", target=driver)
    return result


@admin_router.post("/applications/{driver_id}/reject", response_model=DriverApplicationResponse, summary="⛔ رد پرونده با دلیل")
def reject(data: DriverRejectRequest, db: db_dependency, driver_id: int = Path(gt=0), user=Depends(org_admin)):
    result = _call(driver_service.reject, db, user, driver_id, data.reason)
    driver = db.get(User, driver_id)
    audit_service.record(db, user, "driver.reject", f"پرونده راننده «{driver.full_name or driver.username}» رد شد",
                         target=driver, details={"reason": data.reason})
    return result


@admin_router.get("/{driver_id}/documents/{kind}", summary="📎 مشاهده مدرک راننده (فقط ادمین همان سازمان)")
def driver_document(kind: DocumentKind, db: db_dependency, user: user_dependency, driver_id: int = Path(gt=0)):
    return _file(_call(driver_service.document_file, db, user, driver_id, kind))
