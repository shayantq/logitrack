"""
زمان‌بندی و تخصیص هوشمند (مرحله ۷)

برای یک سفارش (وزن، بازه تحویل، شهر/استان مقصد) همه خودروهای سازمان بررسی می‌شوند و
هر کدام یا «پیشنهاد» می‌شود (با امتیاز و دلیل) یا «کنار گذاشته» می‌شود (با دلیل روشن).

یک خودرو فقط وقتی پیشنهاد می‌شود که همه این شرط‌ها برقرار باشد:
  - راننده دارد و راننده‌اش احراز هویت شده است
  - خودرو در تعمیر یا غیرفعال نیست
  - ظرفیت خودرو برای وزن سفارش کافی است
  - مقصد در محدوده کاری راننده است (هم‌شهر/هم‌استان، یا راننده بار بین‌شهری می‌برد)
  - بازه تحویل با شیفت راننده هم‌پوشانی کافی دارد (اگر برنامه کاری ثبت شده باشد)
  - راننده در آن بازه مرخصی نیست
  - سقف سفارش روزانه راننده پر نشده است
  - وزن سفارش‌های هم‌پوشان آن خودرو + این سفارش از ظرفیتش بیشتر نمی‌شود

همه زمان‌ها در دیتابیس UTC هستند؛ شیفت‌ها به وقت ایران تعریف می‌شوند (ایران از ۱۴۰۱ ساعت تابستانی ندارد).
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.iran import fa_digits

from app.models import (
    ACTIVE_ORDER_STATUSES, DriverProfile, DriverShift, DriverTimeOff, Order, User, Vehicle,
)

IRAN_TZ = timezone(timedelta(hours=3, minutes=30))
MIN_SHIFT_OVERLAP = timedelta(minutes=30)
DEFAULT_DAILY_REFERENCE = 8   # برای متعادل‌سازی بار، وقتی راننده سقف روزانه ندارد
WEEKDAYS_FA = {5: "شنبه", 6: "یکشنبه", 0: "دوشنبه", 1: "سه‌شنبه", 2: "چهارشنبه", 3: "پنجشنبه", 4: "جمعه"}
# سفارش‌هایی که ظرفیت/سهمیه روز را مصرف می‌کنند (لغو/ناموفق/منقضی آزاد شده‌اند)
COUNTED_STATUSES = (*ACTIVE_ORDER_STATUSES, "delivered")


def to_utc_naive(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def to_local(value: datetime) -> datetime:
    """UTC (naive) ← وقت ایران (naive)"""
    return value.replace(tzinfo=timezone.utc).astimezone(IRAN_TZ).replace(tzinfo=None)


def local_to_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=IRAN_TZ).astimezone(timezone.utc).replace(tzinfo=None)


def _fmt_time(value: time) -> str:
    return value.strftime("%H:%M")


def _fa_kg(value: float) -> str:
    return f"{value:,.0f}"


@dataclass
class Evaluation:
    vehicle: Vehicle
    driver: User | None
    eligible: bool = True
    reason: str | None = None            # دلیل کنار گذاشته شدن
    score: float = 0
    reasons: list[str] = field(default_factory=list)   # دلایل پیشنهاد
    load_kg: float = 0                   # وزن سفارش‌های هم‌پوشان فعلی
    day_orders: int = 0
    same_city: bool = False
    has_schedule: bool = False

    def exclude(self, reason: str) -> "Evaluation":
        if self.eligible:
            self.eligible, self.reason = False, reason
        return self

    def as_dict(self) -> dict:
        v, d = self.vehicle, self.driver
        capacity = v.capacity_kg or 0
        return {
            "vehicle_id": v.id, "license_plate": v.license_plate, "vehicle_type": v.type, "vehicle_model": v.model,
            "vehicle_status": v.status, "capacity_kg": v.capacity_kg, "city": v.city,
            "driver_id": d.id if d else None, "driver_name": (d.full_name or d.username) if d else None,
            "driver_code": d.driver_code if d else None,
            "score": round(self.score, 1), "reasons": [fa_digits(r) for r in self.reasons],
            "reason": fa_digits(self.reason) if self.reason else None,
            "load_kg": round(self.load_kg, 2), "free_kg": round(max(capacity - self.load_kg, 0), 2),
            "day_orders": self.day_orders, "same_city": self.same_city, "has_schedule": self.has_schedule,
        }


def _overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> timedelta:
    return max(min(a_end, b_end) - max(a_start, b_start), timedelta(0))


def shift_overlap(shifts: list[DriverShift], start_local: datetime, end_local: datetime) -> timedelta:
    """بیشترین هم‌پوشانی بازه (به وقت ایران) با یکی از شیفت‌های هفتگی در روزهای همان بازه."""
    best = timedelta(0)
    day = start_local.date()
    while day <= end_local.date():
        for s in shifts:
            if s.weekday == day.weekday():
                best = max(best, _overlap(start_local, end_local,
                                          datetime.combine(day, s.start_time), datetime.combine(day, s.end_time)))
        day += timedelta(days=1)
    return best


def evaluate(db: Session, *, weight: float, window_start: datetime, window_end: datetime,
             destination_city: str, destination_province: str | None = None,
             exclude_order_id: int | None = None, vehicle_ids: list[int] | None = None) -> list[Evaluation]:
    """همه خودروها (یا خودروهای مشخص) را برای این سفارش ارزیابی می‌کند؛ پیشنهادها مرتب بر اساس امتیاز."""
    start, end = to_utc_naive(window_start), to_utc_naive(window_end)
    start_local, end_local = to_local(start), to_local(end)

    vq = db.query(Vehicle)
    if vehicle_ids is not None:
        vq = vq.filter(Vehicle.id.in_(vehicle_ids))
    vehicles = vq.order_by(Vehicle.id).all()
    driver_ids = [v.driver_id for v in vehicles if v.driver_id]
    drivers = {u.id: u for u in db.query(User).filter(User.id.in_(driver_ids)).all()} if driver_ids else {}
    profiles = {p.user_id: p for p in db.query(DriverProfile).filter(DriverProfile.user_id.in_(driver_ids)).all()} if driver_ids else {}
    shifts: dict[int, list[DriverShift]] = {}
    for s in db.query(DriverShift).filter(DriverShift.user_id.in_(driver_ids)).all() if driver_ids else []:
        shifts.setdefault(s.user_id, []).append(s)
    off = {t.user_id for t in db.query(DriverTimeOff).filter(
        DriverTimeOff.user_id.in_(driver_ids), DriverTimeOff.starts_at < end, DriverTimeOff.ends_at > start,
    ).all()} if driver_ids else set()

    # سفارش‌های همین خودروها در روز(های) این بازه — برای ظرفیت هم‌پوشان و سهمیه روزانه
    day_start = local_to_utc(datetime.combine(start_local.date(), time.min))
    day_end = local_to_utc(datetime.combine(start_local.date() + timedelta(days=1), time.min))
    oq = db.query(Order).filter(
        Order.vehicle_id.in_([v.id for v in vehicles]), Order.status.in_(COUNTED_STATUSES),
        Order.delivery_window_start < max(end, day_end), Order.delivery_window_end > min(start, day_start),
    )
    if exclude_order_id:
        oq = oq.filter(Order.id != exclude_order_id)
    orders_by_vehicle: dict[int, list[Order]] = {}
    for o in oq.all() if vehicles else []:
        orders_by_vehicle.setdefault(o.vehicle_id, []).append(o)

    window_len = end - start
    required_overlap = min(MIN_SHIFT_OVERLAP, window_len)
    results = []
    for v in vehicles:
        driver = drivers.get(v.driver_id)
        ev = Evaluation(vehicle=v, driver=driver)
        results.append(ev)
        profile = profiles.get(driver.id) if driver else None
        orders = orders_by_vehicle.get(v.id, [])
        overlapping = [o for o in orders if o.status in ACTIVE_ORDER_STATUSES
                       and o.delivery_window_start < end and o.delivery_window_end > start]
        ev.load_kg = sum(o.total_weight_kg or 0 for o in overlapping)
        ev.day_orders = sum(1 for o in orders if day_start <= o.delivery_window_start < day_end)
        base_city = v.city or (driver.city if driver else None) or (profile.city if profile else None)
        ev.same_city = bool(base_city) and base_city == destination_city
        same_province = bool(profile and profile.province and destination_province and profile.province == destination_province)
        driver_shifts = shifts.get(driver.id, []) if driver else []
        ev.has_schedule = bool(driver_shifts)

        if driver is None:
            ev.exclude("خودرو راننده ندارد")
        elif driver.driver_status != "approved":
            ev.exclude("راننده هنوز احراز هویت نشده است")
        elif driver.is_active is False:
            ev.exclude("حساب راننده غیرفعال است")
        if v.status in ("maintenance", "inactive"):
            ev.exclude("خودرو در تعمیر است" if v.status == "maintenance" else "خودرو غیرفعال است")
        if not v.capacity_kg:
            ev.exclude("ظرفیت خودرو ثبت نشده است")
        elif weight > v.capacity_kg:
            ev.exclude(f"ظرفیت خودرو ({_fa_kg(v.capacity_kg)} کیلوگرم) برای این سفارش کافی نیست")
        if driver and base_city and not ev.same_city and not same_province and not (profile and profile.intercity):
            ev.exclude("مقصد خارج از شهر راننده است و راننده بار بین‌شهری نمی‌برد")
        if driver and driver_shifts and shift_overlap(driver_shifts, start_local, end_local) < required_overlap:
            ev.exclude(f"خارج از شیفت راننده ({WEEKDAYS_FA[start_local.weekday()]} "
                       f"{start_local:%H:%M} تا {end_local:%H:%M})")
        if driver and driver.id in off:
            ev.exclude("راننده در این بازه مرخصی است")
        if profile and profile.max_daily_orders and ev.day_orders >= profile.max_daily_orders:
            ev.exclude(f"سقف سفارش روزانه راننده ({profile.max_daily_orders}) پر شده است")
        if v.capacity_kg and weight <= v.capacity_kg and ev.load_kg + weight > v.capacity_kg:
            ev.exclude(f"ظرفیت خودرو در این بازه پر است ({_fa_kg(ev.load_kg)} از {_fa_kg(v.capacity_kg)} کیلوگرم رزرو شده)")
        if not ev.eligible:
            continue

        # ---------------- امتیاز (هرچه بیشتر، مناسب‌تر)
        free = v.capacity_kg - ev.load_kg
        if ev.same_city:
            ev.score += 40
            ev.reasons.append("هم‌شهر با مقصد")
        elif same_province:
            ev.score += 20
            ev.reasons.append("هم‌استان با مقصد")
        elif not base_city:
            ev.score += 10
            ev.reasons.append("شهر مبدأ راننده ثبت نشده")
        else:
            ev.reasons.append("بار بین‌شهری می‌برد")
        fit = weight / free if free else 0
        ev.score += 25 * fit   # خودروی متناسب با بار؛ کامیون برای بسته ۵ کیلویی امتیاز کمی می‌گیرد
        ev.reasons.append(f"ظرفیت آزاد در این بازه: {_fa_kg(free)} کیلوگرم")
        if any(o.destination_city == destination_city for o in overlapping):
            ev.score += 15
            ev.reasons.append("در همین بازه بار دیگری به همین شهر دارد (تجمیع)")
        reference = (profile.max_daily_orders if profile and profile.max_daily_orders else DEFAULT_DAILY_REFERENCE)
        ev.score += 20 * max(0.0, 1 - ev.day_orders / reference)
        ev.reasons.append(f"{ev.day_orders} سفارش دیگر در این روز" if ev.day_orders else "در این روز سفارش دیگری ندارد")
        if ev.has_schedule:
            ev.reasons.append("در شیفت کاری است")
        else:
            ev.score -= 10
            ev.reasons.append("برنامه کاری ثبت نشده (همیشه در دسترس فرض شد)")
        if v.status == "on_route":
            ev.score -= 5

    return sorted(results, key=lambda e: (not e.eligible, -e.score, e.vehicle.id))


def suggest(db: Session, **kwargs) -> dict:
    evaluations = evaluate(db, **kwargs)
    return {
        "candidates": [e.as_dict() for e in evaluations if e.eligible],
        "excluded": [e.as_dict() for e in evaluations if not e.eligible],
    }


def check_vehicle(db: Session, vehicle_id: int, **kwargs) -> Evaluation | None:
    found = evaluate(db, vehicle_ids=[vehicle_id], **kwargs)
    return found[0] if found else None


def week_dates(day: date) -> list[date]:
    return [day + timedelta(days=i) for i in range(7)]
