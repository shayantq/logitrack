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
from app.schemas.user import UserResponse
from app.services import organization_request_service, organization_service
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
