from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from starlette import status

from app.database import db_dependency
from app.dependencies import require_role, user_dependency
from app.models import ACTIVE_ORDER_STATUSES, Order, RoleEnum, Vehicle
from app.schemas.order import (
    OrderAssignRequest, OrderDetailResponse, OrderRequest, OrderResponse, OrderStatus, OrderStatusRequest,
)
from app.services import order_service
from app.services.exceptions import DomainError

router = APIRouter(
    prefix='/orders',
    tags=['🛒 مدیریت و تخصیص سفارشات']
)


@router.get('/stats/summary', summary="📊 دریافت آمار واقعی برای داشبورد")
def get_dashboard_stats(
    db: db_dependency,
    user=Depends(require_role([RoleEnum.ORG_ADMIN, RoleEnum.WAREHOUSE_MANAGER]))
):
    total_orders = db.query(Order).count()
    active_orders = db.query(Order).filter(Order.status.in_(ACTIVE_ORDER_STATUSES)).count()
    available_vehicles = db.query(Vehicle).filter(Vehicle.status == 'available').count()
    # خودروهایی که الان سفارش فعال دارند (از مرحله ۷ وضعیت «مشغول» تنظیم نمی‌شود)
    busy_vehicles = db.query(Order.vehicle_id).filter(Order.status.in_(ACTIVE_ORDER_STATUSES), Order.vehicle_id.isnot(None)).distinct().count()
    recent_orders = db.query(Order).order_by(Order.id.desc()).limit(5).all()

    return {
        "metrics": {
            "total_orders": total_orders,
            "active_orders": active_orders,
            "available_vehicles": available_vehicles,
            "busy_vehicles": busy_vehicles
        },
        "recent_orders": [OrderResponse.model_validate(o).model_dump(mode="json") for o in recent_orders]
    }


@router.get('/', status_code=status.HTTP_200_OK, response_model=list[OrderResponse], summary="📋 دریافت لیست فیلتر شده سفارشات")
def get_all_orders(
        db: db_dependency,
        user: user_dependency,
        order_status: Optional[OrderStatus] = Query(None, description='وضعیت'),
        province: Optional[str] = Query(None, description='استان مقصد'),
        city: Optional[str] = Query(None, description='شهر مقصد'),
        q: Optional[str] = Query(None, min_length=2, description='جستجوی سراسری: کد، مشتری، تحویل‌گیرنده، شهر، کالا، راننده، پلاک'),
        vehicle_id: Optional[int] = Query(None, gt=0, description='خودرو'),
        date_from: Optional[datetime] = Query(None, description='ثبت‌شده از تاریخ'),
        date_to: Optional[datetime] = Query(None, description='ثبت‌شده تا تاریخ'),
        skip: int = Query(0, ge=0, description='تعداد عبور از اول (Pagination)'),
        limit: int = Query(100, ge=1, le=500, description='حداکثر تعداد دریافت'),
        tracking_code: Optional[str] = Query(None, min_length=2, description='کد سفارش (بخشی از کد هم کافی است)'),
        product: Optional[str] = Query(None, min_length=2, description='نام یا کد کالا'),
        driver_id: Optional[int] = Query(None, gt=0, description='راننده'),
        driver: Optional[str] = Query(None, min_length=2, description='نام، نام کاربری یا کد راننده'),
        plate: Optional[str] = Query(None, min_length=2, description='پلاک (با ارقام فارسی یا لاتین)'),
        delivery_from: Optional[date] = Query(None, description='روز تحویل از (وقت ایران، شامل)'),
        delivery_to: Optional[date] = Query(None, description='روز تحویل تا (وقت ایران، شامل)'),
        priority: Optional[bool] = Query(None, description='فقط فوری‌ها'),
    ):
    return order_service.list_orders(
        db, user, order_status, province, city, q, vehicle_id, date_from, date_to, skip, limit,
        tracking_code=tracking_code, product=product, driver_id=driver_id, driver=driver, plate=plate,
        delivery_from=delivery_from, delivery_to=delivery_to, priority=priority,
    )


@router.get('/{order_id}', status_code=status.HTTP_200_OK, response_model=OrderDetailResponse, summary="🔍 جزئیات کامل سفارش + تاریخچه وضعیت")
def get_order_by_id(db: db_dependency, user: user_dependency, order_id: int = Path(gt=0)):
    """
    **سطح دسترسی:** ادمین و مدیر انبار همه سفارش‌ها؛ راننده فقط سفارش‌های خودروی خودش.
    """
    try:
        return OrderDetailResponse.from_order(order_service.get_order(db, user, order_id))
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post('/', status_code=status.HTTP_201_CREATED, response_model=OrderDetailResponse, summary="⚡ ثبت سفارش چندقلمی + تخصیص هوشمند ناوگان")
def add_order(db: db_dependency, user: user_dependency, order_request: OrderRequest):
    try:
        return OrderDetailResponse.from_order(order_service.create_order(db, user, order_request))
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.put('/{order_id}/assign', status_code=status.HTTP_200_OK, response_model=OrderDetailResponse, summary="🚚 تخصیص خودرو به سفارش «در انتظار تخصیص»")
def assign_vehicle(db: db_dependency, user: user_dependency, request: OrderAssignRequest, order_id: int = Path(gt=0)):
    """بدون vehicle_id: انتخاب خودکار بر اساس شهر مقصد و ظرفیت."""
    try:
        return OrderDetailResponse.from_order(order_service.assign_vehicle(db, user, order_id, request))
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.put('/{order_id}/status', status_code=status.HTTP_200_OK, response_model=OrderDetailResponse, summary="🛠️ تغییر وضعیت مرسوله")
def update_order_status(db: db_dependency, user: user_dependency, status_request: OrderStatusRequest, order_id: int = Path(gt=0)):
    try:
        return OrderDetailResponse.from_order(order_service.update_order_status(db, user, order_id, status_request))
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.delete('/{order_id}', status_code=status.HTTP_204_NO_CONTENT, summary="❌ حذف کامل سفارش")
def delete_order(db: db_dependency, user: user_dependency, order_id: int = Path(gt=0)):
    try:
        order_service.delete_order(db, user, order_id)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
