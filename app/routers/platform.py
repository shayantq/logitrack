from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import FileResponse
from starlette import status

from app.database import db_dependency
from app.dependencies import require_role
from app.models import RoleEnum
from app.schemas.organization import (
    OrganizationApproved, OrganizationCreate, OrganizationProfileResponse, OrganizationRequestApprove,
    OrganizationRequestReject, OrganizationRequestResponse, OrganizationStats, OrganizationUpdate,
)
from app.schemas.operations_health import MessageFailureOut, OperationsOverview, ReplayIn, ResolveIn, TaskFailureOut
from app.schemas.platform_ops import DeprovisionOut, ExportOut, FlagIn, FlagOut, GrantIn, GrantOut, PlanIn, PlanSummary, ReasonIn, SupportView, SuspendIn
from app.schemas.user import UserResponse
from app.services import organization_request_service, organization_service, outbox_service, platform_service
from app.services.exceptions import DomainError

router = APIRouter(
    prefix="/platform",
    tags=["🛰️ پنل پلتفرم (مدیریت سازمان‌ها)"]
)

# خواندن: ادمین و پشتیبان پلتفرم — نوشتن: فقط ادمین پلتفرم
platform_staff = require_role([RoleEnum.PLATFORM_ADMIN, RoleEnum.PLATFORM_SUPPORT])
platform_admin = require_role([RoleEnum.PLATFORM_ADMIN])


@router.get("/organizations", response_model=list[OrganizationStats], summary="🏢 لیست سازمان‌ها همراه با آمار")
def list_organizations(db: db_dependency, _=Depends(platform_staff)):
    return organization_service.list_organizations(db)


@router.get("/organizations/{organization_id}", response_model=OrganizationStats, summary="🔍 جزئیات و آمار یک سازمان")
def get_organization(db: db_dependency, organization_id: int = Path(gt=0), _=Depends(platform_staff)):
    try:
        return organization_service.get_organization(db, organization_id)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post("/organizations", status_code=status.HTTP_201_CREATED, response_model=OrganizationStats,
             summary="➕ ساخت سازمان جدید همراه با اولین ادمین آن")
def create_organization(data: OrganizationCreate, db: db_dependency, _=Depends(platform_admin)):
    try:
        return organization_service.create_organization(db, data)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.patch("/organizations/{organization_id}", response_model=OrganizationStats,
              summary="✏️ ویرایش نام یا فعال/غیرفعال کردن سازمان")
def update_organization(data: OrganizationUpdate, db: db_dependency, organization_id: int = Path(gt=0),
                        _=Depends(platform_admin)):
    try:
        return organization_service.update_organization(db, organization_id, data)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get("/organizations/{organization_id}/users", response_model=list[UserResponse],
            summary="👥 کاربران یک سازمان")
def list_organization_users(db: db_dependency, organization_id: int = Path(gt=0), _=Depends(platform_staff)):
    try:
        return organization_service.list_organization_users(db, organization_id)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get("/organizations/{organization_id}/profile", response_model=OrganizationProfileResponse,
            summary="🏢 پروفایل کامل یک سازمان")
def get_organization_profile(db: db_dependency, organization_id: int = Path(gt=0), _=Depends(platform_staff)):
    try:
        return organization_service.get_profile(db, organization_id)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get("/organizations/{organization_id}/logo", summary="🖼️ لوگوی یک سازمان")
def get_organization_logo(db: db_dependency, organization_id: int = Path(gt=0), _=Depends(platform_staff)):
    try:
        path, media_type = organization_service.logo_file(db, organization_id)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, no-cache"})


# ---------------------------------------------------------------------------
# درخواست‌های ثبت سازمان (از لندینگ پیج)
# ---------------------------------------------------------------------------

@router.get("/organization-requests", response_model=list[OrganizationRequestResponse],
            summary="📥 لیست درخواست‌های ثبت سازمان")
def list_organization_requests(
    db: db_dependency,
    request_status: Optional[Literal["pending", "approved", "rejected"]] = Query(None, alias="status"),
    _=Depends(platform_staff),
):
    return organization_request_service.list_requests(db, request_status)


@router.get("/organization-requests/{request_id}", response_model=OrganizationRequestResponse,
            summary="🔍 جزئیات یک درخواست")
def get_organization_request(db: db_dependency, request_id: int = Path(gt=0), _=Depends(platform_staff)):
    try:
        return organization_request_service.get_request(db, request_id)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post("/organization-requests/{request_id}/approve", response_model=OrganizationApproved,
             summary="✅ تأیید درخواست: ساخت سازمان و اولین ادمین آن")
def approve_organization_request(data: OrganizationRequestApprove, db: db_dependency,
                                 request_id: int = Path(gt=0), reviewer=Depends(platform_admin)):
    try:
        return organization_request_service.approve_request(db, reviewer, request_id, data)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post("/organization-requests/{request_id}/reject", response_model=OrganizationRequestResponse,
             summary="⛔ رد درخواست با ذکر دلیل")
def reject_organization_request(data: OrganizationRequestReject, db: db_dependency,
                                request_id: int = Path(gt=0), reviewer=Depends(platform_admin)):
    try:
        return organization_request_service.reject_request(db, reviewer, request_id, data)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get("/operations", response_model=OperationsOverview, summary="🩺 پیام‌ها و وظایف پس‌زمینه ناموفق (بدون متن پیام)")
def operations(db: db_dependency, _=Depends(platform_staff)):
    return outbox_service.overview(db)


@router.post("/operations/messages/{message_id}/retry", response_model=MessageFailureOut, summary="🔁 ارسال دوباره پیام ناموفق غیرحساس")
def retry_message(data: ReplayIn, db: db_dependency, message_id: int = Path(gt=0), user=Depends(platform_admin)):
    try:
        return outbox_service.retry_message(db, user, message_id, data.reason, data.conflict_reviewed)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post("/operations/messages/{message_id}/resolve", response_model=MessageFailureOut, summary="⚖️ حل دستی پیام با نتیجه نامعلوم")
def resolve_message(data: ResolveIn, db: db_dependency, message_id: int = Path(gt=0), user=Depends(platform_admin)):
    return _ops(outbox_service.resolve_unconfirmed, db, user, message_id, data.action, data.reason, data.accept_duplicate_risk)


@router.post("/operations/tasks/{failure_id}/replay", response_model=TaskFailureOut, summary="🔁 اجرای دوباره وظیفه دوره‌ای")
def replay_task(data: ReplayIn, db: db_dependency, failure_id: int = Path(gt=0), user=Depends(platform_admin)):
    from app.celery_app import celery_app
    try:
        return outbox_service.replay_task(db, user, failure_id, data.reason, celery_app.send_task)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


def _ops(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post("/organizations/{organization_id}/suspend", response_model=OrganizationStats, summary="⏸️ تعلیق: کار تازه بسته، کار در جریان آزاد")
def suspend(data: SuspendIn, db: db_dependency, organization_id: int = Path(gt=0), user=Depends(platform_admin)):
    _ops(platform_service.suspend, db, user, organization_id, data.reason, data.confirm_slug)
    return organization_service.get_organization(db, organization_id)


@router.post("/organizations/{organization_id}/resume", response_model=OrganizationStats, summary="▶️ برداشتن تعلیق")
def resume(data: ReasonIn, db: db_dependency, organization_id: int = Path(gt=0), user=Depends(platform_admin)):
    _ops(platform_service.resume, db, user, organization_id, data.reason)
    return organization_service.get_organization(db, organization_id)


@router.get("/organizations/{organization_id}/plan", response_model=PlanSummary, summary="📦 پلن و مصرف سازمان")
def plan(db: db_dependency, organization_id: int = Path(gt=0), _=Depends(platform_staff)):
    return _ops(platform_service.plan_summary, db, organization_id)


@router.put("/organizations/{organization_id}/plan", response_model=PlanSummary, summary="📦 تغییر پلن (نسخه‌دار، با مهلت هنگام کاهش)")
def change_plan(data: PlanIn, db: db_dependency, organization_id: int = Path(gt=0), user=Depends(platform_admin)):
    return _ops(platform_service.change_plan, db, user, organization_id, data.plan_id, data.reason)


@router.get("/organizations/{organization_id}/support-access", response_model=list[GrantOut], summary="🛟 دسترسی‌های موقت پشتیبانی")
def support_access(db: db_dependency, organization_id: int = Path(gt=0), _=Depends(platform_staff)):
    return _ops(platform_service.list_grants, db, organization_id)


@router.post("/organizations/{organization_id}/support-access", response_model=GrantOut, summary="🛟 دادن دسترسی موقت (با دلیل و مهلت)")
def grant_support_access(data: GrantIn, db: db_dependency, organization_id: int = Path(gt=0), user=Depends(platform_admin)):
    return _ops(platform_service.grant_access, db, user, organization_id, data.user_id, data.reason, data.minutes)


@router.post("/support-access/{grant_id}/revoke", response_model=GrantOut, summary="🛟 لغو دسترسی موقت")
def revoke_support_access(db: db_dependency, grant_id: int = Path(gt=0), user=Depends(platform_admin)):
    return _ops(platform_service.revoke_access, db, user, grant_id)


@router.get("/organizations/{organization_id}/support-view", response_model=SupportView, summary="🛟 نمای فقط‌خواندنی با دسترسی موقت معتبر")
def support_view(db: db_dependency, organization_id: int = Path(gt=0), user=Depends(platform_staff)):
    return _ops(platform_service.support_view, db, user, organization_id)


@router.get("/feature-flags", response_model=list[FlagOut], summary="🚩 پرچم‌های قابلیت")
def feature_flags(db: db_dependency, _=Depends(platform_staff)):
    return platform_service.list_flags(db)


@router.put("/feature-flags/{key}", response_model=FlagOut, summary="🚩 تنظیم پرچم: فهرست مجاز و توقف اضطراری")
def set_feature_flag(data: FlagIn, db: db_dependency, key: str = Path(max_length=48), user=Depends(platform_admin)):
    return _ops(platform_service.set_flag, db, user, key, data)


@router.get("/organizations/{organization_id}/exports", response_model=list[ExportOut], summary="📤 خروجی‌های داده سازمان")
def exports(db: db_dependency, organization_id: int = Path(gt=0), user=Depends(platform_staff)):
    return platform_service.list_exports(db, organization_id, user)


@router.post("/organizations/{organization_id}/exports", response_model=ExportOut, summary="📤 ساخت خروجی کامل داده سازمان")
def create_export(data: ReasonIn, db: db_dependency, organization_id: int = Path(gt=0), user=Depends(platform_admin)):
    from app.tasks import export_tenant_task
    return _ops(platform_service.request_export, db, user, organization_id, data.reason, export_tenant_task.delay)


@router.post("/organizations/{organization_id}/exports/{export_id}/retry", response_model=ExportOut, summary="🔁 ساخت دوباره خروجی ناموفق (ردیف تازه)")
def retry_export(data: ReasonIn, db: db_dependency, organization_id: int = Path(gt=0), export_id: int = Path(gt=0), user=Depends(platform_admin)):
    from app.tasks import export_tenant_task
    return _ops(platform_service.retry_export, db, user, organization_id, export_id, data.reason, export_tenant_task.delay)


@router.get("/organizations/{organization_id}/exports/{export_id}/download", summary="📤 دریافت فایل خروجی (ثبت در گزارش فعالیت)")
def download_export(db: db_dependency, organization_id: int = Path(gt=0), export_id: int = Path(gt=0), user=Depends(platform_admin)):
    path = _ops(platform_service.export_file, db, user, organization_id, export_id)
    return FileResponse(path, media_type="application/zip", filename=f"organization-{organization_id}-export-{export_id}.zip")


@router.post("/organizations/{organization_id}/deprovision", response_model=DeprovisionOut, summary="🚪 ثبت خروج سازمان (پاک‌سازی پس از ۳۰ روز)")
def deprovision(data: SuspendIn, db: db_dependency, organization_id: int = Path(gt=0), user=Depends(platform_admin)):
    return _ops(platform_service.request_deprovision, db, user, organization_id, data.reason, data.confirm_slug)


@router.post("/organizations/{organization_id}/deprovision/cancel", response_model=DeprovisionOut, summary="🚪 لغو خروج پیش از پاک‌سازی")
def cancel_deprovision(data: ReasonIn, db: db_dependency, organization_id: int = Path(gt=0), user=Depends(platform_admin)):
    return _ops(platform_service.cancel_deprovision, db, user, organization_id, data.reason)
