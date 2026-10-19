"""برنامه کاری رانندگان: شیفت هفتگی، نوع همکاری، سقف سفارش روزانه، بار بین‌شهری و مرخصی (مرحله ۷)."""
from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from app.models import DriverProfile, DriverShift, DriverTimeOff, Order, User, Vehicle
from app.schemas.dispatch import ScheduleUpdate, TimeOffCreate
from app.services.dispatch_service import COUNTED_STATUSES, local_to_utc, to_local, to_utc_naive
from app.services.exceptions import ForbiddenError, NotFoundError


def _require_staff(user: User) -> None:
    if user.role not in ("org_admin", "warehouse_manager"):
        raise ForbiddenError()


def _require_admin(user: User) -> None:
    if user.role != "org_admin":
        raise ForbiddenError("فقط ادمین سازمان برنامه رانندگان را تغییر می‌دهد.")


def _driver(db: Session, driver_id: int) -> User:
    driver = db.query(User).filter(User.id == driver_id, User.role == "driver").first()
    if driver is None:
        raise NotFoundError("راننده یافت نشد.")
    return driver


def _profile(db: Session, driver: User) -> DriverProfile:
    profile = db.query(DriverProfile).filter(DriverProfile.user_id == driver.id).first()
    if profile is None:
        profile = DriverProfile(user_id=driver.id, organization_id=driver.organization_id)
        db.add(profile)
        db.flush()
    return profile


def _shift_dict(s: DriverShift) -> dict:
    return {"id": s.id, "weekday": s.weekday, "start_time": s.start_time, "end_time": s.end_time}


def _off_dict(t: DriverTimeOff) -> dict:
    return {"id": t.id, "starts_at": t.starts_at, "ends_at": t.ends_at, "reason": t.reason}


def _upcoming_off(db: Session, driver_ids: list[int]) -> dict[int, list[DriverTimeOff]]:
    now = to_utc_naive(datetime.now().astimezone())
    result: dict[int, list[DriverTimeOff]] = {}
    for t in db.query(DriverTimeOff).filter(DriverTimeOff.user_id.in_(driver_ids), DriverTimeOff.ends_at > now) \
            .order_by(DriverTimeOff.starts_at).all():
        result.setdefault(t.user_id, []).append(t)
    return result


def list_schedules(db: Session, user: User, day: date) -> list[dict]:
    """همه رانندگان با برنامه هفتگی، مرخصی‌های پیش‌رو و بار روز انتخاب‌شده."""
    _require_staff(user)
    drivers = db.query(User).filter(User.role == "driver").order_by(User.full_name, User.id).all()
    ids = [d.id for d in drivers]
    if not ids:
        return []
    profiles = {p.user_id: p for p in db.query(DriverProfile).filter(DriverProfile.user_id.in_(ids)).all()}
    shifts: dict[int, list[DriverShift]] = {}
    for s in db.query(DriverShift).filter(DriverShift.user_id.in_(ids)).order_by(DriverShift.weekday, DriverShift.start_time).all():
        shifts.setdefault(s.user_id, []).append(s)
    vehicles: dict[int, Vehicle] = {}
    for v in db.query(Vehicle).filter(Vehicle.driver_id.in_(ids)).order_by(Vehicle.id.desc()).all():   # جدیدترین خودرو
        vehicles.setdefault(v.driver_id, v)
    off = _upcoming_off(db, ids)

    day_start = local_to_utc(datetime.combine(day, time.min))
    day_end = day_start + timedelta(days=1)
    vehicle_driver = {v.id: driver_id for driver_id, v in vehicles.items()}
    load: dict[int, list[Order]] = {}
    if vehicle_driver:
        for o in db.query(Order).filter(Order.vehicle_id.in_(list(vehicle_driver)), Order.status.in_(COUNTED_STATUSES),
                                        Order.delivery_window_start >= day_start, Order.delivery_window_start < day_end).all():
            load.setdefault(vehicle_driver[o.vehicle_id], []).append(o)
    off_today = {t.user_id for t in db.query(DriverTimeOff).filter(
        DriverTimeOff.user_id.in_(ids), DriverTimeOff.starts_at < day_end, DriverTimeOff.ends_at > day_start).all()}

    result = []
    for d in drivers:
        profile = profiles.get(d.id)
        vehicle = vehicles.get(d.id)
        day_orders = load.get(d.id, [])
        result.append({
            "driver_id": d.id, "driver_name": d.full_name or d.username, "driver_code": d.driver_code,
            "driver_status": d.driver_status, "city": (vehicle.city if vehicle else None) or d.city,
            "employment_type": profile.employment_type if profile else "full_time",
            "max_daily_orders": profile.max_daily_orders if profile else None,
            "intercity": bool(profile.intercity) if profile else False,
            "vehicle": {"id": vehicle.id, "license_plate": vehicle.license_plate, "type": vehicle.type, "model": vehicle.model,
                        "capacity_kg": vehicle.capacity_kg, "status": vehicle.status} if vehicle else None,
            "shifts": [_shift_dict(s) for s in shifts.get(d.id, [])],
            "time_off": [_off_dict(t) for t in off.get(d.id, [])],
            "day": {
                "date": day, "orders": len(day_orders), "load_kg": round(sum(o.total_weight_kg or 0 for o in day_orders), 2),
                "shifts": [f"{s.start_time:%H:%M}–{s.end_time:%H:%M}" for s in shifts.get(d.id, []) if s.weekday == day.weekday()],
                "off": d.id in off_today,
            },
        })
    return result


def update_schedule(db: Session, user: User, driver_id: int, data: ScheduleUpdate) -> dict:
    _require_admin(user)
    driver = _driver(db, driver_id)
    profile = _profile(db, driver)
    profile.employment_type = data.employment_type
    profile.max_daily_orders = data.max_daily_orders
    profile.intercity = data.intercity
    db.query(DriverShift).filter(DriverShift.user_id == driver.id).delete(synchronize_session=False)
    for s in data.shifts:
        db.add(DriverShift(user_id=driver.id, organization_id=driver.organization_id,
                           weekday=s.weekday, start_time=s.start_time, end_time=s.end_time))
    db.commit()
    return my_schedule_for(db, driver)


def add_time_off(db: Session, user: User, driver_id: int, data: TimeOffCreate) -> dict:
    _require_admin(user)
    driver = _driver(db, driver_id)
    entry = DriverTimeOff(user_id=driver.id, organization_id=driver.organization_id, created_by_id=user.id,
                          starts_at=to_utc_naive(data.starts_at), ends_at=to_utc_naive(data.ends_at), reason=data.reason or None)
    db.add(entry)
    db.commit()
    return _off_dict(entry)


def delete_time_off(db: Session, user: User, driver_id: int, time_off_id: int) -> None:
    _require_admin(user)
    entry = db.query(DriverTimeOff).filter(DriverTimeOff.id == time_off_id, DriverTimeOff.user_id == driver_id).first()
    if entry is None:
        raise NotFoundError("مرخصی یافت نشد.")
    db.delete(entry)
    db.commit()


def my_schedule_for(db: Session, driver: User) -> dict:
    profile = db.query(DriverProfile).filter(DriverProfile.user_id == driver.id).first()
    shifts = db.query(DriverShift).filter(DriverShift.user_id == driver.id).order_by(DriverShift.weekday, DriverShift.start_time).all()
    return {
        "employment_type": profile.employment_type if profile else "full_time",
        "max_daily_orders": profile.max_daily_orders if profile else None,
        "intercity": bool(profile.intercity) if profile else False,
        "shifts": [_shift_dict(s) for s in shifts],
        "time_off": [_off_dict(t) for t in _upcoming_off(db, [driver.id]).get(driver.id, [])],
    }


def my_schedule(db: Session, user: User) -> dict:
    if user.role != "driver":
        raise ForbiddenError("این بخش مخصوص رانندگان است.")
    return my_schedule_for(db, user)


def today_local() -> date:
    return to_local(to_utc_naive(datetime.now().astimezone())).date()

