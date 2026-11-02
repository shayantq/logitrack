"""مرکز استثنا: فهرست، جزئیات با تاریخچه، رسیدگی و بررسی دوباره."""
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Path, Query

from app.database import db_dependency
from app.dependencies import user_dependency
from app.schemas.exception import (
    ApprovalDecisionIn, ApprovalOut, DriverExceptionOut, ExceptionDetailOut, ExceptionOut, ExceptionScanOut, ExceptionSeverity, ExceptionTeam,
    ExceptionUpdate, IncidentIn,
)
from app.services import approval_service, exception_service
from app.services.exceptions import DomainError

router = APIRouter(prefix="/exceptions", tags=["🚨 مرکز استثنا"])
approvals = APIRouter(prefix="/adjustment-approvals", tags=["🚨 مرکز استثنا"])


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get("/", response_model=list[ExceptionOut], summary="📋 استثناها (پیش‌فرض: باز)")
def list_exceptions(db: db_dependency, user: user_dependency,
                    status: Literal["active", "all", "open", "acknowledged", "in_progress", "waiting", "waiting_external", "resolved", "merged"] = Query("active"),
                    team: Optional[ExceptionTeam] = None, severity: Optional[ExceptionSeverity] = None, urgent: bool = False,
                    owner_id: Optional[int] = Query(None, gt=0), kind: Optional[str] = Query(None, max_length=32),
                    sort: Literal["severity", "opened_at", "due_at"] = "severity"):
    return _call(exception_service.list_exceptions, db, user, status=status, team=team, severity=severity, urgent=urgent,
                 owner_id=owner_id, kind=kind, sort=sort)


@router.get("/mine", response_model=list[DriverExceptionOut], summary="🚚 مشکل‌های باز سفارش‌های من (راننده)")
def mine(db: db_dependency, user: user_dependency):
    return _call(exception_service.for_driver, db, user)


@router.post("/report", summary="🚚 گزارش مشکل توسط راننده")
def report(data: IncidentIn, db: db_dependency, user: user_dependency) -> dict:
    return _call(exception_service.report_incident, db, user, data)


@router.post("/scan", response_model=ExceptionScanOut, summary="🔎 بررسی دوباره همین حالا")
def scan(db: db_dependency, user: user_dependency):
    return _call(exception_service.scan, db, user)


@router.get("/{exception_id}", response_model=ExceptionDetailOut, summary="🔍 جزئیات و تاریخچه استثنا")
def get_exception(db: db_dependency, user: user_dependency, exception_id: int = Path(gt=0)):
    return _call(exception_service.get_exception, db, user, exception_id)


@router.patch("/{exception_id}", response_model=ExceptionDetailOut, summary="✏️ تعیین مسئول، تغییر وضعیت، یادداشت یا ادغام")
def update(data: ExceptionUpdate, db: db_dependency, user: user_dependency, exception_id: int = Path(gt=0)):
    return _call(exception_service.update, db, user, exception_id, data)


@approvals.get("", response_model=list[ApprovalOut], summary="✅ اصلاح‌های موجودی منتظر تأیید دوم")
def list_approvals(db: db_dependency, user: user_dependency, status: Literal["pending", "approved", "rejected", "all"] = Query("pending")):
    return _call(approval_service.list_approvals, db, user, status)


@approvals.post("/{approval_id}/decide", response_model=ApprovalOut, summary="✅ تأیید یا رد اصلاح موجودی (غیر از درخواست‌کننده)")
def decide_approval(data: ApprovalDecisionIn, db: db_dependency, user: user_dependency, approval_id: int = Path(gt=0)):
    return _call(approval_service.decide, db, user, approval_id, data.approve, data.note)
