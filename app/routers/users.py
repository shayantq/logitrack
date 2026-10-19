from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from starlette import status
from app.database import db_dependency
from app.dependencies import current_user_dependency, require_role, user_dependency
from app.core.security import ACCESS_TOKEN_EXPIRE_MINUTES, create_access_token
from app.models import RoleEnum
from app.schemas.user import (
    ActivityItem, AuditLogPage, MeResponse, PasswordResetResponse, TokenResponse, TourStateIn, UpdateUserRequest,
    UserDetailResponse, UserResponse, UserUpdateRequest,
)
from app.services import audit_service, user_service
from app.services.exceptions import DomainError

router = APIRouter(
    prefix='/users',
    tags=['👥 مدیریت کاربران سیستم']
)
org_admin = require_role([RoleEnum.ORG_ADMIN])


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get('/me', status_code=status.HTTP_200_OK, response_model=MeResponse, summary="👤 دریافت اطلاعات کاربر لاگین‌شده")
def get_current_user_info(user: current_user_dependency):
    return user


@router.put('/me/tours/{tour_id}', response_model=dict[str, str], summary="🧭 ثبت دیده/رد شدن یک راهنمای تعاملی (دیگر خودکار باز نمی‌شود)")
def set_tour_state(data: TourStateIn, db: db_dependency, user: current_user_dependency,
                   tour_id: str = Path(pattern=r"^[a-z0-9_-]{1,40}$")):
    return _call(user_service.set_tour_state, db, user, tour_id, data.state)


@router.delete('/me/tours', response_model=dict[str, str], summary="🧭 شروع دوباره همه راهنماها (بار بعد دوباره خودکار باز می‌شوند)")
def reset_tours(db: db_dependency, user: current_user_dependency):
    return _call(user_service.set_tour_state, db, user, None, None)


@router.put('/me/password', response_model=TokenResponse, summary="🔑 تغییر رمز عبور خودم (نشست‌های دیگر بسته می‌شوند؛ توکن تازه برمی‌گردد)")
def change_my_password(data: UpdateUserRequest, db: db_dependency, user: current_user_dependency):
    user = _call(user_service.change_own_password, db, user, data.old_password, data.new_password)
    token = create_access_token(user.username, user.id, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES), user.token_version)
    return {"access_token": token, "token_type": "bearer"}


@router.get('/', status_code=status.HTTP_200_OK, response_model=list[UserResponse], summary="📋 دریافت لیست تمامی کاربران سیستم")
def get_all_users(db: db_dependency, user: user_dependency):
    """
    **سطح دسترسی:** فقط نقش **ادمین (Admin)**.
    """
    return _call(user_service.list_users, db, user)


@router.get('/activity-log', response_model=AuditLogPage, summary="🕵️ گزارش فعالیت سازمان (ادمین سازمان)")
def activity_log(db: db_dependency, user=Depends(org_admin), actor_id: int | None = Query(None, gt=0),
                 category: str | None = None, q: str | None = Query(None, max_length=100),
                 date_from: date | None = None, date_to: date | None = None,
                 limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    return _call(audit_service.list_logs, db, user, actor_id=actor_id, category=category, q=q,
                 date_from=date_from, date_to=date_to, limit=limit, offset=offset)


@router.get('/{user_id}', response_model=UserDetailResponse, summary="👤 جزئیات و آمار یک کاربر (ادمین سازمان)")
def user_detail(db: db_dependency, user=Depends(org_admin), user_id: int = Path(gt=0)):
    return _call(user_service.user_detail, db, user, user_id)


@router.get('/{user_id}/activity', response_model=list[ActivityItem], summary="🕓 خط زمانی فعالیت یک کاربر")
def user_activity(db: db_dependency, user=Depends(org_admin), user_id: int = Path(gt=0), limit: int = Query(60, ge=1, le=200)):
    return _call(audit_service.user_activity, db, user, user_id, limit)


@router.put('/{user_id}', response_model=UserResponse, summary="✏️ ویرایش کاربر (نام، ایمیل، موبایل، نقش، انبار، شهر)")
def update_user(data: UserUpdateRequest, db: db_dependency, user=Depends(org_admin), user_id: int = Path(gt=0)):
    return _call(user_service.update_user, db, user, user_id, data.model_dump(exclude_unset=True))


@router.post('/{user_id}/deactivate', response_model=UserResponse, summary="⛔ غیرفعال‌سازی حساب (خروج فوری از همه دستگاه‌ها)")
def deactivate_user(db: db_dependency, user=Depends(org_admin), user_id: int = Path(gt=0)):
    return _call(user_service.set_active, db, user, user_id, False)


@router.post('/{user_id}/activate', response_model=UserResponse, summary="✅ فعال‌سازی دوباره حساب")
def activate_user(db: db_dependency, user=Depends(org_admin), user_id: int = Path(gt=0)):
    return _call(user_service.set_active, db, user, user_id, True)


@router.post('/{user_id}/reset-password', response_model=PasswordResetResponse, summary="🔑 بازنشانی رمز با رمز موقت (یک‌بار نمایش)")
def reset_password(db: db_dependency, user=Depends(org_admin), user_id: int = Path(gt=0)):
    target, password = _call(user_service.reset_password, db, user, user_id)
    return {"user": target, "temporary_password": password}


@router.post('/{user_id}/unlock', response_model=UserResponse, summary="🔓 برداشتن قفل ورود پس از تلاش‌های ناموفق")
def unlock_user(db: db_dependency, user=Depends(org_admin), user_id: int = Path(gt=0)):
    return _call(user_service.unlock, db, user, user_id)


@router.delete('/{user_id}', status_code=status.HTTP_204_NO_CONTENT, summary="🗑️ حذف کاربر بدون سابقه (کاربر دارای سابقه غیرفعال می‌شود)")
def delete_user(db: db_dependency, user: user_dependency, user_id: int = Path(gt=0)):
    _call(user_service.delete_user, db, user, user_id)
