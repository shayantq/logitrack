"""
برآورد رسیدن و ریسک تأخیر (docs/productivity.md، B4).

این یک «برآورد برنامه‌ای» از زمان مسیر با سرعت میانگین است، نه موقعیت واقعی خودرو. ستون ذخیره‌شده ندارد و هر بار
حساب می‌شود. شماره سفارش‌های فعال کم است؛ آزمون شمار کوئری (tests/api/test_query_budget.py) آن را زیر نظر دارد.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core import geo
from app.models import ACTIVE_ORDER_STATUSES, Order, OrderCheckpoint
from app.services import dispatch_service, route_service

LABEL = "برآورد برنامه‌ای"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def estimate(db: Session, order: Order, *, checkpoints: list[OrderCheckpoint] | None = None,
             departed_at: datetime | None = None, now: datetime | None = None) -> dict | None:
    """برای سفارش فعال: eta، زمان محاسبه، دلیل و پرچم at_risk (eta بعد از پایان بازه). سفارش پایان‌یافته None است."""
    if order.status not in ACTIVE_ORDER_STATUSES:
        return None
    now = now or _now()
    start, end = dispatch_service.to_utc_naive(order.delivery_window_start), dispatch_service.to_utc_naive(order.delivery_window_end)
    route = route_service.route_of(db, order)
    hours = timedelta(hours=(route["total_km"] or 0) / geo.AVERAGE_SPEED_KMH) if route else None
    late = "در مسیر کمتر از برنامه پیش رفته"

    if order.status == "in_transit":
        if checkpoints is None:
            checkpoints = route_service._checkpoints(db, [order.id]).get(order.id, [])
        if departed_at is None:
            departed_at = route_service._departures(db, [order.id]).get(order.id)
        eta = route_service.progress(order, route, checkpoints, departed_at, now)["eta"]
    elif hours is None:
        eta = None
    elif order.status == "picked_up":
        eta, late = now + hours, "بارگیری شده ولی زمان باقی‌مانده بازه برای طول مسیر کافی نیست"
    elif start <= now:
        eta, late = now + hours, "شروع بازه گذشته و هنوز بارگیری نشده"
    else:
        eta, late = start + hours, "زمان مسیر از طول بازه تحویل بیشتر است"

    at_risk = eta > end if eta is not None else end < now
    if end < now:
        late = "از پایان بازه تحویل گذشته"
    return {"eta": eta, "computed_at": now, "label": LABEL, "at_risk": at_risk, "reason": late if at_risk else None}


def at_risk_ids(db: Session, now: datetime | None = None) -> list[int]:
    """سفارش‌هایی که هنوز از بازه نگذشته‌اند ولی برآورد رسیدنشان بعد از پایان بازه است (گذشته‌ها در نمای «دیرکرد» هستند)."""
    now = now or _now()
    orders = db.query(Order).filter(Order.status.in_(ACTIVE_ORDER_STATUSES), Order.delivery_window_end >= now).all()
    transit = [o.id for o in orders if o.status == "in_transit"]
    checkpoints, departures = route_service._checkpoints(db, transit), route_service._departures(db, transit)
    result = []
    for order in orders:
        info = estimate(db, order, checkpoints=checkpoints.get(order.id, []), departed_at=departures.get(order.id), now=now)
        if info and info["at_risk"]:
            result.append(order.id)
    return result
