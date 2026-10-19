"""
مسیر سفارش روی نقشه ایران (مرحله ۱۰).

- مسیر: کوتاه‌ترین مسیر جاده‌ای از شهر انبار تا شهر مقصد روی گراف `app/core/geo.py`؛ با شروع حرکت
  («در مسیر مقصد») روی سفارش ثابت می‌شود.
- پیشرفت (بدون GPS): ترکیب وضعیت سفارش، گزارش راننده و زمان.
  * قبل از حرکت: ۰ — تحویل‌شده: ۱.
  * در مسیر: از آخرین شهری که راننده گزارش داده (یا مبدأ، از لحظه شروع حرکت) با سرعت متوسط جلو می‌رود،
    اما هرگز از شهر بعدیِ گزارش‌نشده عبور نمی‌کند؛ پس تا راننده «رسیدم به X» را نزند، کمان پشت X می‌ایستد.
  * ناموفق/لغو/منقضی: روی آخرین نقطه گزارش‌شده متوقف می‌ماند.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session, joinedload

from app.core import geo
from app.core.iran import fa_digits
from app.models import (
    ACTIVE_ORDER_STATUSES, Order, OrderCheckpoint, OrderStatusHistory, User, Vehicle, Warehouse,
)
from app.services import commission_service, dispatch_service, order_service
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError

BEFORE_DEPARTURE = ("pending", "assigned", "picking_up", "picked_up")
STOPPED = ("failed", "canceled", "expired")
# سهم پیمودنی از یک قطعه تا شهر بعدی، قبل از گزارش راننده
MAX_SEGMENT_SHARE = 0.92
UNDO_WINDOW = timedelta(minutes=30)
MAP_LIMIT = 300


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# برنامه مسیر
# ---------------------------------------------------------------------------
def plan(warehouse: Warehouse | None, destination_city: str | None, destination_province: str | None) -> dict | None:
    """مسیر پیشنهادی؛ None اگر مبدأ یا مقصد روی نقشه معلوم نباشد."""
    if warehouse is None:
        return None
    origin, origin_exact = geo.resolve(warehouse.city or warehouse.location, warehouse.province)
    dest, dest_exact = geo.resolve(destination_city, destination_province)
    if origin is None or dest is None:
        return None
    path = geo.route(origin, dest)
    if not path:
        return None
    points = [{"seq": i, "city": c.name, "province": c.province, "lat": c.lat, "lon": c.lon, "km": km,
               "label": c.name, "approx": False} for i, (c, km) in enumerate(path)]
    if not origin_exact and warehouse.city:
        points[0].update(label=warehouse.city, approx=True)
    if not dest_exact and destination_city:
        points[-1].update(label=destination_city, approx=True)
    return {"points": points, "total_km": path[-1][1], "warehouse_name": warehouse.name,
            "planned_at": _now().isoformat()}


def route_of(db: Session, order: Order) -> dict | None:
    if order.route:
        return order.route
    warehouse = db.get(Warehouse, order.warehouse_id) if order.warehouse_id else None
    return plan(warehouse, order.destination_city, order.destination_province)


def freeze_route(db: Session, order: Order) -> None:
    """با شروع حرکت صدا زده می‌شود (order_service)."""
    if order.route is None:
        order.route = route_of(db, order)


# ---------------------------------------------------------------------------
# پیشرفت
# ---------------------------------------------------------------------------
def progress(order: Order, route: dict | None, checkpoints: list[OrderCheckpoint],
             departed_at: datetime | None, now: datetime | None = None) -> dict:
    now = now or _now()
    status = order.status
    if not route:
        return {"fraction": 1.0 if status == "delivered" else 0.0, "km_done": 0, "remaining_km": None,
                "passed_seq": -1, "next_seq": None, "estimated": False, "eta": None, "last_report": None}

    points = route["points"]
    total = route["total_km"] or 0
    last = max(checkpoints, key=lambda c: c.seq) if checkpoints else None
    base_seq = last.seq if last else 0
    base_km = points[base_seq]["km"] if base_seq < len(points) else 0
    base_time = last.reached_at if last else departed_at
    last_report = {"seq": last.seq, "city": last.city, "at": last.reached_at} if last else None

    estimated, eta = False, None
    if status == "delivered":
        km, passed = total, len(points) - 1
    elif status == "in_transit":
        passed = base_seq
        km = base_km
        if base_seq < len(points) - 1:
            next_km = points[base_seq + 1]["km"]
            hours = max(0.0, (now - base_time).total_seconds() / 3600) if base_time else 0.0
            km = min(base_km + geo.AVERAGE_SPEED_KMH * hours, base_km + (next_km - base_km) * MAX_SEGMENT_SHARE)
            estimated = km > base_km
        eta = now + timedelta(hours=max(0.0, total - km) / geo.AVERAGE_SPEED_KMH)
    elif status in STOPPED:
        km, passed = (base_km, base_seq) if (last or departed_at) else (0, -1)
    else:  # قبل از حرکت
        km, passed = 0, -1

    if total:
        fraction = km / total
    else:  # مبدأ و مقصد در یک شهر
        fraction = {"delivered": 1.0, "in_transit": 0.5}.get(status, 0.0)
        if status == "in_transit":
            eta = None
    next_seq = passed + 1 if status == "in_transit" and passed + 1 < len(points) else None
    return {"fraction": round(min(1.0, max(0.0, fraction)), 4), "km_done": round(km),
            "remaining_km": round(max(0, total - km)), "passed_seq": passed, "next_seq": next_seq,
            "estimated": estimated, "eta": eta, "last_report": last_report}


def _departures(db: Session, order_ids: list[int]) -> dict[int, datetime]:
    rows = db.query(OrderStatusHistory.order_id, OrderStatusHistory.changed_at).filter(
        OrderStatusHistory.order_id.in_(order_ids or [-1]), OrderStatusHistory.to_status == "in_transit",
    ).order_by(OrderStatusHistory.changed_at).all()
    result: dict[int, datetime] = {}
    for oid, at in rows:
        result[oid] = at          # آخرین شروع حرکت
    return result


def _checkpoints(db: Session, order_ids: list[int]) -> dict[int, list[OrderCheckpoint]]:
    result: dict[int, list[OrderCheckpoint]] = {}
    for cp in db.query(OrderCheckpoint).filter(OrderCheckpoint.order_id.in_(order_ids or [-1])) \
            .order_by(OrderCheckpoint.seq).all():
        result.setdefault(cp.order_id, []).append(cp)
    return result


def _unavailable_reason(db: Session, order: Order) -> str:
    warehouse = db.get(Warehouse, order.warehouse_id) if order.warehouse_id else None
    if warehouse is None:
        return "انبار مبدأ این سفارش مشخص نیست."
    if geo.resolve(warehouse.city or warehouse.location, warehouse.province)[0] is None:
        return f"شهر انبار «{warehouse.name}» ثبت نشده است؛ از بخش انبارها، استان و شهر آن را مشخص کنید."
    return "شهر یا استان مقصد این سفارش روی نقشه شناخته نشد."


def describe(db: Session, order: Order, *, with_reporters: bool = True,
             checkpoints: list[OrderCheckpoint] | None = None, departed_at: datetime | None = None) -> dict:
    """مسیر + پیشرفت + گزارش‌ها برای یک سفارش."""
    route = route_of(db, order)
    if checkpoints is None:
        checkpoints = _checkpoints(db, [order.id]).get(order.id, [])
    if departed_at is None:
        departed_at = _departures(db, [order.id]).get(order.id)
    reporters = {}
    if with_reporters:
        ids = {c.reported_by_id for c in checkpoints if c.reported_by_id}
        reporters = {u.id: u.full_name or u.username for u in db.query(User).filter(User.id.in_(ids or [-1])).all()}
    return {
        "order_id": order.id, "tracking_code": order.tracking_code, "status": order.status,
        "available": route is not None, "reason": None if route else _unavailable_reason(db, order),
        "frozen": order.route is not None,
        "total_km": route["total_km"] if route else None,
        "points": route["points"] if route else [],
        "warehouse_name": route.get("warehouse_name") if route else None,
        "departed_at": departed_at,
        "progress": progress(order, route, checkpoints, departed_at),
        "checkpoints": [{"seq": c.seq, "city": c.city, "reached_at": c.reached_at,
                         "reported_by": reporters.get(c.reported_by_id) if with_reporters else None}
                        for c in checkpoints],
        "speed_kmh": geo.AVERAGE_SPEED_KMH,
    }


# ---------------------------------------------------------------------------
# دسترسی و گزارش راننده
# ---------------------------------------------------------------------------
def get_order_route(db: Session, user: User, order_id: int) -> dict:
    order = order_service.get_order(db, user, order_id)   # راننده فقط سفارش خودش
    return describe(db, order)


def _reportable_order(db: Session, user: User, order_id: int) -> Order:
    if user.role not in ("driver", "org_admin"):
        raise ForbiddenError("فقط راننده سفارش یا ادمین سازمان می‌تواند موقعیت را گزارش کند.")
    order = order_service.get_order(db, user, order_id)
    if order.status != "in_transit":
        raise ConflictError("گزارش موقعیت فقط وقتی سفارش «در مسیر مقصد» است ممکن است.")
    return order


def report_checkpoint(db: Session, user: User, order_id: int, seq: int) -> dict:
    order = _reportable_order(db, user, order_id)
    freeze_route(db, order)
    route = order.route
    if not route:
        raise ConflictError(_unavailable_reason(db, order))
    points = route["points"]
    if not 1 <= seq < len(points):
        raise ConflictError("این شهر در مسیر سفارش نیست.")
    last = db.query(OrderCheckpoint).filter(OrderCheckpoint.order_id == order.id) \
        .order_by(OrderCheckpoint.seq.desc()).first()
    if last and seq <= last.seq:
        raise ConflictError(f"رسیدن به «{points[last.seq]['label']}» قبلاً گزارش شده است؛ فقط شهرهای بعدی را می‌توانید گزارش کنید.")
    point = points[seq]
    db.add(OrderCheckpoint(organization_id=order.organization_id, order_id=order.id, seq=seq,
                           city=point["label"], province=point["province"], reached_at=_now(),
                           reported_by_id=user.id))
    db.commit()
    return describe(db, order)


def undo_checkpoint(db: Session, user: User, order_id: int) -> dict:
    order = _reportable_order(db, user, order_id)
    last = db.query(OrderCheckpoint).filter(OrderCheckpoint.order_id == order.id) \
        .order_by(OrderCheckpoint.seq.desc()).first()
    if last is None:
        raise ConflictError("گزارشی برای برگرداندن وجود ندارد.")
    if user.role == "driver" and (last.reported_by_id != user.id or _now() - last.reached_at > UNDO_WINDOW):
        raise ConflictError(f"فقط آخرین گزارش خودتان را تا {fa_digits(str(int(UNDO_WINDOW.total_seconds() // 60)))} دقیقه بعد می‌توانید برگردانید.")
    db.delete(last)
    db.commit()
    return describe(db, order)


# ---------------------------------------------------------------------------
# نقشه ارسال‌ها
# ---------------------------------------------------------------------------
def map_orders(db: Session, user: User, scope: str = "active") -> dict:
    query = db.query(Order).options(joinedload(Order.vehicle))
    if user.role == "driver":
        vehicle_ids = [v.id for v in db.query(Vehicle).filter(Vehicle.driver_id == user.id).all()]
        query = query.filter(Order.vehicle_id.in_(vehicle_ids or [-1]))
    if scope == "in_transit":
        query = query.filter(Order.status == "in_transit")
    elif scope == "today":
        today = dispatch_service.to_local(_now()).date()
        start = dispatch_service.local_to_utc(datetime.combine(today, datetime.min.time()))
        query = query.filter(Order.delivery_window_start >= start, Order.delivery_window_start < start + timedelta(days=1))
    else:
        query = query.filter(Order.status.in_(ACTIVE_ORDER_STATUSES))
    orders = query.order_by(Order.priority.desc(), Order.delivery_window_start).limit(MAP_LIMIT).all()

    ids = [o.id for o in orders]
    checkpoints, departures = _checkpoints(db, ids), _departures(db, ids)
    driver_ids = {commission_service.driver_of(db, o) for o in orders} - {None}
    drivers = {u.id: u.full_name or u.username for u in db.query(User).filter(User.id.in_(driver_ids or [-1])).all()}
    warehouses = {w.id: w for w in db.query(Warehouse).all()}

    items, unmapped = [], 0
    for o in orders:
        info = describe(db, o, with_reporters=False, checkpoints=checkpoints.get(o.id, []),
                        departed_at=departures.get(o.id))
        if not info["available"]:
            unmapped += 1
        driver_id = commission_service.driver_of(db, o)
        warehouse = warehouses.get(o.warehouse_id)
        items.append({
            **info, "priority": o.priority, "destination_city": o.destination_city,
            "destination_province": o.destination_province,
            "delivery_window_start": o.delivery_window_start, "delivery_window_end": o.delivery_window_end,
            "driver_name": drivers.get(driver_id), "plate": o.vehicle.license_plate if o.vehicle else None,
            "warehouse_name": warehouse.name if warehouse else info["warehouse_name"],
        })
    return {"orders": items, "unmapped": unmapped, "speed_kmh": geo.AVERAGE_SPEED_KMH}
