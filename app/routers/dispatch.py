"""زمان‌بندی رانندگان و پیشنهاد هوشمند راننده برای سفارش (مرحله ۷)."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from starlette import status

from app.database import db_dependency
from app.dependencies import require_role
from app.models import Order, RoleEnum
from app.schemas.dispatch import (
    DriverScheduleResponse, MyScheduleResponse, ScheduleUpdate, SuggestRequest, SuggestResponse, TimeOffCreate, TimeOffOut,
)
from app.services import dispatch_service, schedule_service
from app.services.exceptions import DomainError

router = APIRouter(prefix="/dispatch", tags=["🗓️ زمان‌بندی و تخصیص هوشمند"])

staff = require_role([RoleEnum.ORG_ADMIN, RoleEnum.WAREHOUSE_MANAGER])
org_admin = require_role([RoleEnum.ORG_ADMIN])
driver_only = require_role([RoleEnum.DRIVER])


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post("/suggest", response_model=SuggestResponse,
             summary="🧭 پیشنهاد راننده برای سفارشی که هنوز ثبت نشده (وزن، بازه، مقصد)")
def suggest(data: SuggestRequest, db: db_dependency, user=Depends(staff)):
    return dispatch_service.suggest(
        db, weight=data.total_weight_kg, window_start=data.delivery_window_start, window_end=data.delivery_window_end,
        destination_city=data.destination_city, destination_province=data.destination_province,
    )


@router.get("/orders/{order_id}/suggestions", response_model=SuggestResponse, summary="🧭 پیشنهاد راننده برای یک سفارش")
def order_suggestions(db: db_dependency, order_id: int = Path(gt=0), user=Depends(staff)):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="سفارش یافت نشد.")
    if user.role == "warehouse_manager" and order.warehouse_id != user.warehouse_id:
        raise HTTPException(status_code=403, detail="این سفارش از انبار شما ارسال نمی‌شود.")
    return dispatch_service.suggest(
        db, weight=order.total_weight_kg, window_start=order.delivery_window_start, window_end=order.delivery_window_end,
        destination_city=order.destination_city, destination_province=order.destination_province, exclude_order_id=order.id,
    )


@router.get("/schedules", response_model=list[DriverScheduleResponse], summary="🗓️ برنامه کاری و بار روزانه رانندگان")
def schedules(db: db_dependency, day: Optional[date] = None, user=Depends(staff)):
    return _call(schedule_service.list_schedules, db, user, day or schedule_service.today_local())


@router.put("/schedules/{driver_id}", response_model=MyScheduleResponse, summary="✏️ تنظیم شیفت‌ها و ظرفیت راننده")
def update_schedule(data: ScheduleUpdate, db: db_dependency, driver_id: int = Path(gt=0), user=Depends(org_admin)):
    return _call(schedule_service.update_schedule, db, user, driver_id, data)


@router.post("/schedules/{driver_id}/time-off", response_model=TimeOffOut, status_code=201, summary="🏖️ ثبت مرخصی راننده")
def add_time_off(data: TimeOffCreate, db: db_dependency, driver_id: int = Path(gt=0), user=Depends(org_admin)):
    return _call(schedule_service.add_time_off, db, user, driver_id, data)


@router.delete("/schedules/{driver_id}/time-off/{time_off_id}", status_code=status.HTTP_204_NO_CONTENT, summary="🗑️ حذف مرخصی")
def delete_time_off(db: db_dependency, driver_id: int = Path(gt=0), time_off_id: int = Path(gt=0), user=Depends(org_admin)):
    _call(schedule_service.delete_time_off, db, user, driver_id, time_off_id)


@router.get("/my-schedule", response_model=MyScheduleResponse, summary="🗓️ برنامه کاری من (راننده)")
def my_schedule(db: db_dependency, user=Depends(driver_only)):
    return _call(schedule_service.my_schedule, db, user)
