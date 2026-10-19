"""پروفایل و لوگوی سازمان کاربر جاری (برای کاربران سازمان‌ها)."""
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette import status

from app.database import db_dependency
from app.dependencies import require_role, user_dependency
from app.models import RoleEnum
from app.schemas.organization import OrganizationProfileResponse, OrganizationProfileUpdate
from app.services import organization_service
from app.services.exceptions import DomainError
from app.services import audit_service

router = APIRouter(
    prefix="/organization",
    tags=["🏢 پروفایل سازمان"]
)

org_admin = require_role([RoleEnum.ORG_ADMIN])


@router.get("/profile", response_model=OrganizationProfileResponse, summary="🏢 مشاهده پروفایل سازمان")
def get_profile(db: db_dependency, user: user_dependency):
    return organization_service.get_profile(db, user.organization_id)


@router.put("/profile", response_model=OrganizationProfileResponse, summary="✏️ ویرایش پروفایل سازمان (ادمین سازمان)")
def update_profile(data: OrganizationProfileUpdate, db: db_dependency, user=Depends(org_admin)):
    try:
        result = organization_service.update_profile(db, user.organization_id, data)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    fields = set(data.model_dump(exclude_unset=True))
    if fields == {"brand_color"}:
        audit_service.record(db, user, "org.brand", f"رنگ سربرگ گزارش‌ها {'به ' + data.brand_color if data.brand_color else 'به پیش‌فرض'} تغییر کرد")
    elif fields:
        audit_service.record(db, user, "org.profile", "پروفایل سازمان ویرایش شد", details={"fields": sorted(fields)})
    return result


@router.post("/logo", response_model=OrganizationProfileResponse, summary="🖼️ آپلود لوگوی سازمان (PNG/JPG/WEBP، حداکثر ۲ مگابایت)")
async def upload_logo(file: UploadFile, db: db_dependency, user=Depends(org_admin)):
    # یک بایت بیشتر از سقف می‌خوانیم تا فایل‌های بزرگ‌تر کامل در حافظه نیایند
    data = await file.read(organization_service.MAX_LOGO_BYTES + 1)
    try:
        result = organization_service.set_logo(db, user.organization_id, data)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    audit_service.record(db, user, "org.logo", "لوگوی سازمان عوض شد")
    return result


@router.get("/logo", summary="🖼️ دریافت لوگوی سازمان")
def get_logo(db: db_dependency, user: user_dependency):
    try:
        path, media_type = organization_service.logo_file(db, user.organization_id)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, no-cache"})


@router.delete("/logo", status_code=status.HTTP_204_NO_CONTENT, summary="🗑️ حذف لوگوی سازمان")
def delete_logo(db: db_dependency, user=Depends(org_admin)):
    organization_service.delete_logo(db, user.organization_id)
    audit_service.record(db, user, "org.logo", "لوگوی سازمان حذف شد")
