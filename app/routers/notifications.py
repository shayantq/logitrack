from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel
from starlette import status

from app.database import db_dependency
from app.dependencies import user_dependency
from app.services import notification_service
from app.services.exceptions import DomainError

router = APIRouter(
    prefix="/notifications",
    tags=["🔔 اعلان‌ها"]
)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


class NotificationDetail(BaseModel):
    label: str
    value: str


class NotificationResponse(BaseModel):
    id: int
    kind: str
    category: str
    severity: str
    title: str
    message: str
    link: Optional[str] = None
    details: list[NotificationDetail] = []
    created_at: Optional[datetime] = None
    is_read: bool
    product_id: Optional[int] = None
    warehouse_id: Optional[int] = None


class NotificationList(BaseModel):
    items: list[NotificationResponse]
    unread_count: int


@router.get("/", response_model=NotificationList, summary="🔔 اعلان‌های من (خوانده و خوانده‌نشده)")
def list_notifications(db: db_dependency, user: user_dependency, unread_only: bool = False,
                       limit: int = Query(notification_service.LIST_LIMIT, ge=1, le=200)):
    """
    **سطح دسترسی:** ادمین، مدیر انبار (فقط انبار خودش) و راننده (فقط اعلان‌های خودش).
    هر اعلان عنوان، توضیح، جزئیات کوتاه و مسیر صفحه مقصد (link) دارد؛ اعلان‌های بسته‌شده برنمی‌گردند.
    """
    return _call(notification_service.list_for, db, user, unread_only=unread_only, limit=limit)


@router.get("/unread", response_model=list[NotificationResponse], summary="🔔 اعلان‌های خوانده‌نشده")
def get_unread_notifications(db: db_dependency, user: user_dependency):
    return _call(notification_service.list_for, db, user, unread_only=True, limit=200)["items"]


@router.put("/read-all", summary="✅ خواندن همه اعلان‌ها")
def mark_all_read(db: db_dependency, user: user_dependency):
    return {"count": _call(notification_service.mark_all_read, db, user)}


@router.put("/{notification_id}/read", status_code=status.HTTP_200_OK, summary="✅ علامت‌گذاری اعلان به‌عنوان خوانده‌شده")
def mark_notification_read(db: db_dependency, user: user_dependency, notification_id: int = Path(gt=0)):
    _call(notification_service.mark_read, db, user, notification_id)
    return {"message": "✅ اعلان خوانده‌شده علامت‌گذاری شد."}


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT, summary="✖️ بستن (حذف) یک اعلان")
def dismiss_notification(db: db_dependency, user: user_dependency, notification_id: int = Path(gt=0)):
    """فقط از فهرست همین کاربر حذف می‌شود؛ بقیه کارکنان همچنان آن را می‌بینند."""
    _call(notification_service.dismiss, db, user, notification_id)


@router.delete("/", summary="🧹 پاک کردن همه اعلان‌ها")
def dismiss_all(db: db_dependency, user: user_dependency):
    return {"count": _call(notification_service.dismiss_all, db, user)}
