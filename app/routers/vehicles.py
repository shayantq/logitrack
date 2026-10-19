from typing import Optional
from app.schemas.vehicle import VehicleResponse, VehicleRequest, VehicleStatusRequest, VehicleDriverRequest, VehicleType, VehicleStatus
from fastapi import APIRouter, HTTPException, Path, Query
from app.database import db_dependency
from starlette import status
from app.dependencies import user_dependency
from app.services import vehicle_service
from app.services.exceptions import DomainError

router = APIRouter(
    prefix='/vehicles',
    tags=['🚚 مدیریت لجستیک و ناوگان حمل و نقل']
)


@router.get('/', status_code=status.HTTP_200_OK, response_model=list[VehicleResponse], summary="📋 دریافت لیست ناوگان با فیلترهای پیشرفته")
def get_all_vehicles(
        db: db_dependency,
        user: user_dependency,
        driver_id: Optional[int] = Query(None, description='فیلتر بر اساس آیدی راننده خودرو'),
        vehicle_type: Optional[VehicleType] = Query(None, description='فیلتر بر اساس نوع خودرو (کامیون، وانت و...)'),
        capacity_kg: Optional[int] = Query(None, description='فیلتر ظرفیت مجاز باربری به کیلوگرم'),
        vehicle_status: Optional[VehicleStatus] = Query(None, description='فیلتر وضعیت عملیاتی خودرو (available, busy و...)'),
):
    return vehicle_service.list_vehicles(db, user, driver_id, vehicle_type, capacity_kg, vehicle_status)


@router.get('/{vehicle_id}', status_code=status.HTTP_200_OK, response_model=VehicleResponse, summary="🔍 مشاهده جزییات فنی یک خودرو")
def get_vehicle_by_id(db: db_dependency, user: user_dependency, vehicle_id: int = Path(gt=0)):
    """
    **سطح دسترسی:** ادمین و مدیر انبار همه خودروها؛ راننده فقط خودروی خودش.
    """
    try:
        return vehicle_service.get_vehicle(db, user, vehicle_id)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post('/', status_code=status.HTTP_201_CREATED, response_model=VehicleResponse, summary="➕ افزودن خودروی جدید به ناوگان")
def add_vehicle(db: db_dependency, user: user_dependency, vehicle_request: VehicleRequest):
    """
    **سطح دسترسی:** فقط **ادمین (Admin)**. افزودن وسیله با پلاک غیرتکراری و تخصیص مستقیم به یک راننده معتبر سیستم.
    """
    try:
        return vehicle_service.create_vehicle(db, user, vehicle_request)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.put('/{vehicle_id}/status', status_code=status.HTTP_200_OK, response_model=VehicleResponse, summary="⚙️ تغییر وضعیت عملیاتی وسیله نقلیه")
def update_vehicle_status(
        db: db_dependency,
        user: user_dependency,
        status_request: VehicleStatusRequest,
        vehicle_id: int = Path(gt=0)
    ):
    """
    **سطح دسترسی:** **ادمین (Admin)** برای همه خودروها، یا **راننده** فقط برای خودروی اختصاصی خودش.
    """
    try:
        return vehicle_service.update_vehicle_status(db, user, vehicle_id, status_request)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.put('/{vehicle_id}/driver', status_code=status.HTTP_200_OK, response_model=VehicleResponse, summary="🔄 تغییر و تعویض راننده خودرو")
def change_vehicle_driver(
        db: db_dependency,
        user: user_dependency,
        driver_request: VehicleDriverRequest,
        vehicle_id: int = Path(gt=0)
    ):
    """
    **سطح دسترسی:** فقط **ادمین (Admin)**. جابجایی راننده‌های فلیت بدون نیاز به حذف و بازتعریف خودرو.
    """
    try:
        return vehicle_service.change_vehicle_driver(db, user, vehicle_id, driver_request)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.delete('/{vehicle_id}', status_code=status.HTTP_204_NO_CONTENT, summary="🗑️ حذف کامل وسیله نقلیه از ناوگان")
def delete_vehicle(db: db_dependency, user: user_dependency, vehicle_id: int = Path(gt=0)):
    """
    **سطح دسترسی:** فقط **ادمین (Admin)**. خروج کامل و فیزیکی وسیله نقلیه فرسوده از پایگاه داده فلیت لوجستیک.
    """
    try:
        vehicle_service.delete_vehicle(db, user, vehicle_id)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
