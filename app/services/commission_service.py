"""
کرایه، سطح راننده و پورسانت پلکانی (مرحله ۸) — مثل اسنپ:

  پورسانت = کرایه × درصد سطح راننده × ضریب پله روزانه

- سطح (مثلاً D ← C ← B ← A): بالاترین سطحی که راننده همه شرط‌هایش را دارد —
  تعداد تحویل موفق «قبل از این سفارش»، روزهای همکاری، و میانگین وزنی امتیاز.
- پله روزانه: چندمین تحویل راننده در همان روز (به وقت ایران). مثلاً سفر ۱ تا ۵ کامل،
  ۶ تا ۱۰ نصف، از ۱۱ به بعد بدون پورسانت.
- تسویه در لحظه تحویل روی خود سفارش ذخیره (منجمد) می‌شود؛ تغییر بعدی قوانین گذشته را عوض نمی‌کند.
"""
import secrets
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.iran import fa_digits
from app.models import CommissionPlan, DriverRating, Order, User, Vehicle
from app.services.dispatch_service import local_to_utc, to_local

DEFAULT_LEVELS = [
    {"code": "D", "name": "تازه‌کار", "min_deliveries": 0, "min_days": 0, "min_rating": None, "commission_percent": 15},
    {"code": "C", "name": "نقره‌ای", "min_deliveries": 50, "min_days": 30, "min_rating": 4.0, "commission_percent": 12},
    {"code": "B", "name": "طلایی", "min_deliveries": 200, "min_days": 90, "min_rating": 4.4, "commission_percent": 10},
    {"code": "A", "name": "الماس", "min_deliveries": 500, "min_days": 180, "min_rating": 4.7, "commission_percent": 8},
]
DEFAULT_TIERS = [
    {"from_trip": 1, "multiplier_percent": 100},
    {"from_trip": 6, "multiplier_percent": 50},
    {"from_trip": 11, "multiplier_percent": 0},
]
DEFAULT_BASE_FARE = 500_000     # ریال
DEFAULT_FARE_PER_KG = 5_000
# وزن هر منبع در میانگین امتیاز (بین منابعی که امتیاز دارند نرمال می‌شود)
RATING_WEIGHTS = {"organization": 0.5, "customer": 0.35, "platform": 0.15}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# قوانین
# ---------------------------------------------------------------------------
def get_plan(db: Session) -> dict:
    row = db.query(CommissionPlan).first()
    if row is None:
        return {"base_fare": DEFAULT_BASE_FARE, "fare_per_kg": DEFAULT_FARE_PER_KG, "levels": DEFAULT_LEVELS,
                "tiers": DEFAULT_TIERS, "updated_at": None, "is_default": True}
    return {"base_fare": row.base_fare, "fare_per_kg": row.fare_per_kg, "levels": row.levels, "tiers": row.tiers,
            "updated_at": row.updated_at, "is_default": False}


def save_plan(db: Session, user: User, data: dict) -> dict:
    row = db.query(CommissionPlan).first()
    if row is None:
        row = CommissionPlan(organization_id=user.organization_id)
        db.add(row)
    row.base_fare, row.fare_per_kg = data["base_fare"], data["fare_per_kg"]
    row.levels, row.tiers, row.updated_by_id = data["levels"], data["tiers"], user.id
    db.commit()
    return get_plan(db)


def default_fee(plan: dict, weight_kg: float) -> float:
    """کرایه پیش‌فرض: پایه + هر کیلو — گرد به هزار ریال."""
    return float(round((plan["base_fare"] + plan["fare_per_kg"] * (weight_kg or 0)) / 1000) * 1000)


# ---------------------------------------------------------------------------
# توابع خالص (بدون دیتابیس) — قلب قانون؛ مستقیم تست می‌شوند
# ---------------------------------------------------------------------------
def qualifies(level: dict, deliveries: int, days: int, rating: float | None) -> bool:
    if deliveries < level["min_deliveries"] or days < level["min_days"]:
        return False
    return level.get("min_rating") is None or (rating is not None and rating >= level["min_rating"])


def level_for(levels: list[dict], deliveries: int, days: int, rating: float | None) -> int:
    """اندیس بالاترین سطحی که همه شرط‌هایش برقرار است (سطح اول همیشه)."""
    current = 0
    for i, level in enumerate(levels):
        if qualifies(level, deliveries, days, rating):
            current = i
    return current


def tier_multiplier(tiers: list[dict], trip_number: int) -> float:
    """ضریب پله روزانه برای Nامین تحویل روز (بزرگ‌ترین from_trip ≤ N)."""
    multiplier = 100.0
    for tier in sorted(tiers, key=lambda t: t["from_trip"]):
        if trip_number >= tier["from_trip"]:
            multiplier = float(tier["multiplier_percent"])
    return multiplier


def compute(plan: dict, fee: float, deliveries_before: int, days: int, rating: float | None, trip_number: int) -> dict:
    index = level_for(plan["levels"], deliveries_before, days, rating)
    level = plan["levels"][index]
    multiplier = tier_multiplier(plan["tiers"], trip_number)
    percent = round(level["commission_percent"] * multiplier / 100, 4)
    commission = float(round(fee * percent / 100))
    return {"level": level, "level_index": index, "multiplier": multiplier, "percent": percent,
            "commission": commission, "earning": float(fee - commission)}


# ---------------------------------------------------------------------------
# آمار لازم برای محاسبه
# ---------------------------------------------------------------------------
def weighted_rating(db: Session, driver_id: int) -> tuple[float | None, dict]:
    rows = db.query(DriverRating.source, func.avg(DriverRating.score), func.count(DriverRating.id)) \
        .filter(DriverRating.driver_id == driver_id).group_by(DriverRating.source).all()
    by_source = {source: {"average": round(float(avg), 2), "count": count} for source, avg, count in rows}
    weights = {s: RATING_WEIGHTS[s] for s in by_source if s in RATING_WEIGHTS}
    if not weights:
        return None, by_source
    total = sum(weights.values())
    overall = sum(by_source[s]["average"] * w for s, w in weights.items()) / total
    return round(overall, 2), by_source


def delivered_count(db: Session, driver_id: int, exclude_order_id: int | None = None) -> int:
    q = db.query(func.count(Order.id)).filter(Order.driver_id == driver_id, Order.status == "delivered")
    if exclude_order_id:
        q = q.filter(Order.id != exclude_order_id)
    return q.scalar() or 0


def tenure_days(driver: User, now: datetime | None = None) -> int:
    created = driver.created_at.replace(tzinfo=None) if driver.created_at else _now()
    return max(0, ((now or _now()) - created).days)


def local_day_bounds(moment: datetime) -> tuple[datetime, datetime]:
    day = to_local(moment).date()
    start = local_to_utc(datetime.combine(day, time.min))
    return start, start + timedelta(days=1)


def trips_on_day(db: Session, driver_id: int, moment: datetime, exclude_order_id: int | None = None) -> int:
    start, end = local_day_bounds(moment)
    q = db.query(func.count(Order.id)).filter(Order.driver_id == driver_id, Order.status == "delivered",
                                              Order.delivered_at >= start, Order.delivered_at < end)
    if exclude_order_id:
        q = q.filter(Order.id != exclude_order_id)
    return q.scalar() or 0


def driver_of(db: Session, order: Order) -> int | None:
    if order.driver_id:
        return order.driver_id
    vehicle = db.get(Vehicle, order.vehicle_id) if order.vehicle_id else None
    return vehicle.driver_id if vehicle else None


def settle_delivery(db: Session, order: Order, now: datetime | None = None) -> None:
    """هنگام «تحویل داده شد»: زمان تحویل، کد نظرسنجی مشتری و تسویه پورسانت را روی سفارش ثبت می‌کند."""
    now = now or _now()
    order.delivered_at = now
    if not order.rating_token:
        order.rating_token = secrets.token_urlsafe(16)[:22]
    driver_id = driver_of(db, order)
    if driver_id is None:
        return
    order.driver_id = driver_id
    driver = db.get(User, driver_id)
    plan = get_plan(db)
    if order.delivery_fee is None:
        order.delivery_fee = default_fee(plan, order.total_weight_kg)
    rating, _ = weighted_rating(db, driver_id)
    result = compute(plan, order.delivery_fee, delivered_count(db, driver_id, order.id), tenure_days(driver, now),
                     rating, trips_on_day(db, driver_id, now, order.id) + 1)
    order.commission_level = result["level"]["code"]
    order.day_trip_number = trips_on_day(db, driver_id, now, order.id) + 1
    order.commission_percent = result["percent"]
    order.commission_amount = result["commission"]
    order.driver_earning = result["earning"]


def progress(db: Session, driver: User, plan: dict | None = None) -> dict:
    """سطح فعلی، سطح بعدی و آنچه برای رسیدن به آن کم است."""
    plan = plan or get_plan(db)
    deliveries = delivered_count(db, driver.id)
    days = tenure_days(driver)
    rating, by_source = weighted_rating(db, driver.id)
    index = level_for(plan["levels"], deliveries, days, rating)
    nxt = plan["levels"][index + 1] if index + 1 < len(plan["levels"]) else None
    needs = []
    if nxt:
        if deliveries < nxt["min_deliveries"]:
            needs.append(f"{nxt['min_deliveries'] - deliveries} تحویل موفق دیگر")
        if days < nxt["min_days"]:
            needs.append(f"{nxt['min_days'] - days} روز همکاری دیگر")
        if nxt.get("min_rating") is not None and (rating is None or rating < nxt["min_rating"]):
            needs.append(f"میانگین امتیاز دست‌کم {nxt['min_rating']}")
    trips_today = trips_on_day(db, driver.id, _now())
    next_trip = trips_today + 1
    current_multiplier = tier_multiplier(plan["tiers"], next_trip)
    upcoming = [t for t in sorted(plan["tiers"], key=lambda t: t["from_trip"]) if t["from_trip"] > next_trip]
    return {
        "level": plan["levels"][index], "level_index": index, "next_level": nxt, "needs": [fa_digits(n) for n in needs],
        "deliveries": deliveries, "days": days, "rating": rating, "ratings_by_source": by_source,
        "trips_today": trips_today, "next_trip_percent": round(plan["levels"][index]["commission_percent"] * current_multiplier / 100, 4),
        "next_tier": upcoming[0] if upcoming else None, "levels_count": len(plan["levels"]),
    }
