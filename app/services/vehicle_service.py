"""
لایه سرویس ناوگان (Vehicle Service)
منطق تجاری مربوط به خودروها: محدودسازی دید راننده به خودروی خودش،
اعتبارسنجی راننده و پلاک تکراری، و کنترل سطح دسترسی تغییر وضعیت.
"""
from sqlalchemy.orm import Session

from app.models import Vehicle, User, Order, ACTIVE_ORDER_STATUSES
from app.schemas.vehicle import VehicleRequest, VehicleStatusRequest, VehicleDriverRequest
from app.services.exceptions import NotFoundError, ForbiddenError, ConflictError


def _has_active_orders(db: Session, vehicle_id: int) -> bool:
    return db.query(Order).filter(
        Order.vehicle_id == vehicle_id,
        Order.status.in_(ACTIVE_ORDER_STATUSES),
    ).first() is not None


def _ensure_approved(driver: User) -> None:
    if driver.driver_status != 'approved':
        raise ConflictError('این راننده هنوز احراز هویت نشده است؛ ابتدا پرونده‌اش را در «احراز هویت رانندگان» تأیید کنید.')


def list_vehicles(db: Session, user: User, driver_id: int = None, vehicle_type: str = None,
                   capacity_kg: int = None, vehicle_status: str = None) -> list[Vehicle]:
    query = db.query(Vehicle)

    if user.role == 'driver':
        query = query.filter(Vehicle.driver_id == user.id)

    filters = {'driver_id': driver_id, 'type': vehicle_type, 'capacity_kg': capacity_kg, 'status': vehicle_status}
    for key, value in filters.items():
        if value is not None:
            query = query.filter(getattr(Vehicle, key) == value)

    # راننده: جدیدترین خودرو اول (پس از تغییر خودرو، خودروی قبلی با سابقه‌اش در فهرست می‌ماند)
    return query.order_by(Vehicle.id.desc() if user.role == 'driver' else Vehicle.id).all()


def get_vehicle(db: Session, user: User, vehicle_id: int) -> Vehicle:
    vehicle = db.get(Vehicle, vehicle_id)
    # راننده فقط خودروی خودش را می‌بیند (404 تا وجود خودروهای دیگر فاش نشود)
    if vehicle is None or (user.role == 'driver' and vehicle.driver_id != user.id):
        raise NotFoundError('خودروی مورد نظر یافت نشد.')
    return vehicle


def create_vehicle(db: Session, user: User, vehicle_request: VehicleRequest) -> Vehicle:
    if user.role != 'org_admin':
        raise ForbiddenError()

    assigned_driver = db.query(User).filter(User.id == vehicle_request.driver_id, User.role == 'driver').first()
    if assigned_driver is None:
        raise NotFoundError('راننده مورد نظر یافت نشد.')
    _ensure_approved(assigned_driver)

    if db.query(Vehicle).filter(Vehicle.license_plate == vehicle_request.license_plate).first():
        raise ConflictError('خودرویی با این شماره پلاک قبلاً ثبت شده است.')

    new_vehicle = Vehicle(
        license_plate=vehicle_request.license_plate,
        type=vehicle_request.vehicle_type,
        model=vehicle_request.vehicle_name,
        capacity_kg=vehicle_request.capacity_kg,
        status=vehicle_request.vehicle_status,
        driver_id=assigned_driver.id,
        city=vehicle_request.city or assigned_driver.city
    )
    db.add(new_vehicle)
    db.commit()
    db.refresh(new_vehicle)
    return new_vehicle


def update_vehicle_status(db: Session, user: User, vehicle_id: int, status_request: VehicleStatusRequest) -> Vehicle:
    target_vehicle = db.get(Vehicle, vehicle_id)
    if target_vehicle is None:
        raise NotFoundError('خودروی مورد نظر یافت نشد.')

    if user.role != 'org_admin' and not (user.role == 'driver' and target_vehicle.driver_id == user.id):
        raise ForbiddenError()

    if target_vehicle.status == status_request.vehicle_status:
        raise ConflictError(f"وضعیت خودرو از قبل روی «{target_vehicle.status}» تنظیم شده است.")

    # از مرحله ۷ «در دسترس» با سفارش فعال مشکلی ندارد: ظرفیت از روی بازه زمانی سفارش‌ها کنترل می‌شود

    target_vehicle.status = status_request.vehicle_status
    db.commit()
    db.refresh(target_vehicle)
    return target_vehicle


def change_vehicle_driver(db: Session, user: User, vehicle_id: int, driver_request: VehicleDriverRequest) -> Vehicle:
    if user.role != 'org_admin':
        raise ForbiddenError()

    target_vehicle = db.get(Vehicle, vehicle_id)
    if target_vehicle is None:
        raise NotFoundError('خودروی مورد نظر یافت نشد.')
    if target_vehicle.driver_id == driver_request.driver_id:
        raise ConflictError("این خودرو از قبل به همین راننده اختصاص داده شده است.")

    new_driver = db.query(User).filter(User.id == driver_request.driver_id, User.role == 'driver').first()
    if new_driver is None:
        raise NotFoundError('راننده مورد نظر یافت نشد.')
    _ensure_approved(new_driver)

    target_vehicle.driver_id = new_driver.id
    db.commit()
    db.refresh(target_vehicle)
    return target_vehicle


def delete_vehicle(db: Session, user: User, vehicle_id: int) -> None:
    if user.role != 'org_admin':
        raise ForbiddenError()

    target_vehicle = db.get(Vehicle, vehicle_id)
    if target_vehicle is None:
        raise NotFoundError('خودروی مورد نظر یافت نشد.')

    if _has_active_orders(db, target_vehicle.id):
        raise ConflictError('این خودرو سفارش فعال دارد و فعلاً قابل حذف نیست.')

    # سفارش‌های قدیمی (تحویل‌شده/ناموفق) حفظ می‌شوند و فقط vehicle_id آن‌ها NULL می‌شود
    db.delete(target_vehicle)
    db.commit()
