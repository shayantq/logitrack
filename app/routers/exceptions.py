"""مرکز استثنا: فهرست، جزئیات با تاریخچه، رسیدگی و بررسی دوباره."""
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Path, Query

from app.database import db_dependency
from app.dependencies import user_dependency
from app.schemas.exception import (
    ExceptionDetailOut, ExceptionOut, ExceptionScanOut, ExceptionSeverity, ExceptionTeam, ExceptionUpdate,
)
from app.services import exception_service
from app.services.exceptions import DomainError

router = APIRouter(prefix="/exceptions", tags=["🚨 مرکز استثنا"])


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get("/", response_model=list[ExceptionOut], summary="📋 استثناها (پیش‌فرض: باز)")
def list_exceptions(db: db_dependency, user: user_dependency,
                    status: Literal["active", "all", "open", "in_progress", "waiting", "resolved", "merged"] = Query("active"),
                    team: Optional[ExceptionTeam] = None, severity: Optional[ExceptionSeverity] = None, urgent: bool = False,
                    owner_id: Optional[int] = Query(None, gt=0), kind: Optional[str] = Query(None, max_length=32)):
    return _call(exception_service.list_exceptions, db, user, status=status, team=team, severity=severity, urgent=urgent,
                 owner_id=owner_id, kind=kind)


@router.post("/scan", response_model=ExceptionScanOut, summary="🔎 بررسی دوباره همین حالا")
def scan(db: db_dependency, user: user_dependency):
    return _call(exception_service.scan, db, user)


@router.get("/{exception_id}", response_model=ExceptionDetailOut, summary="🔍 جزئیات و تاریخچه استثنا")
def get_exception(db: db_dependency, user: user_dependency, exception_id: int = Path(gt=0)):
    return _call(exception_service.get_exception, db, user, exception_id)


@router.patch("/{exception_id}", response_model=ExceptionDetailOut, summary="✏️ تعیین مسئول، تغییر وضعیت، یادداشت یا ادغام")
def update(data: ExceptionUpdate, db: db_dependency, user: user_dependency, exception_id: int = Path(gt=0)):
    return _call(exception_service.update, db, user, exception_id, data)
