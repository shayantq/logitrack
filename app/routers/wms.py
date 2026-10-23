"""واژه‌نامه و برچسب‌های واحد انبارداری، و جریان رویدادهای دامنه (برای یکپارچه‌سازی)."""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.core.wms import vocabulary
from app.database import db_dependency
from app.dependencies import user_dependency
from app.models import DomainEvent
from app.schemas.wms import DomainEventOut

router = APIRouter(prefix="/wms", tags=["📚 واژه‌نامه و رویدادهای انبار"])


@router.get("/vocabulary", summary="📚 واژه‌نامه، وضعیت‌ها، انواع سند و انبار با برچسب فارسی")
def get_vocabulary(user: user_dependency):
    return vocabulary()


@router.get("/events", response_model=list[DomainEventOut], summary="📡 رویدادهای دامنه به ترتیب (برای دنبال کردن با after_id)")
def list_events(db: db_dependency, user: user_dependency,
                after_id: int = Query(0, ge=0, description="فقط رویدادهای بعد از این شناسه"),
                event_type: Optional[str] = Query(None, max_length=48),
                aggregate_type: Optional[str] = Query(None, max_length=32),
                aggregate_id: Optional[int] = Query(None, gt=0),
                limit: int = Query(100, ge=1, le=500)):
    if getattr(user.role, "value", user.role) != "org_admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "رویدادهای سازمان فقط برای ادمین سازمان است.")
    query = db.query(DomainEvent).filter(DomainEvent.id > after_id)
    if event_type:
        query = query.filter(DomainEvent.event_type == event_type)
    if aggregate_type:
        query = query.filter(DomainEvent.aggregate_type == aggregate_type)
    if aggregate_id:
        query = query.filter(DomainEvent.aggregate_id == aggregate_id)
    return query.order_by(DomainEvent.id).limit(limit).all()
