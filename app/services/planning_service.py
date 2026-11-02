"""
مقایسه انبارها و تیم‌ها (CEO-09، ت۲۳) و نمای ظرفیت (CEO-14، ت۲۴). هر دو فقط می‌خوانند و چیزی را تغییر نمی‌دهند.
شاخص انبار همان analytics_service است تا تعریف و مخرج یکی بماند. رتبه‌بندی فردی نداریم.
ظرفیت فقط از سفارش ثبت‌شده و سقف تعریف‌شده می‌آید؛ جایی که سقف نیست هشدار هم نیست.
"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import ACTIVE_ORDER_STATUSES, DriverProfile, DriverTimeOff, Order, Product, User, Vehicle, Warehouse
from app.models_fulfillment import PickLine, PickList
from app.models_operations import InboundReceipt, Location, PutawayTask
from app.models_productivity import ACTIVE_EXCEPTION_STATUSES, OperationException
from app.services import analytics_service, capacity_service, dispatch_service, location_service, permission_service
from app.services.exception_service import TEAM_LABELS
from app.services.exceptions import ForbiddenError
from app.services.stock_position_service import OPEN_RECEIPT_STATUSES

COMPARE_KPIS = ("order_fulfillment", "on_time_delivery", "fill_rate", "picking_accuracy", "inventory_accuracy", "dock_to_stock")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _role(user: User) -> str:
    return getattr(user.role, "value", user.role)


def comparison(db: Session, user: User, date_from: date | None, date_to: date | None) -> dict:
    if _role(user) != "org_admin":
        raise ForbiddenError("مقایسه انبارها فقط برای ادمین سازمان است.")
    permission_service.ensure(db, user, "analytics.view")
    warehouses = [w for w in db.query(Warehouse).filter(Warehouse.is_active.is_not(False)).order_by(Warehouse.id).all()]
    definitions: dict[str, dict] = {}
    rows = []
    period = None
    for warehouse in warehouses:
        result = analytics_service.kpis(db, user, date_from=date_from, date_to=date_to, warehouse_id=warehouse.id)
        period = (result["date_from"], result["date_to"])
        values = {}
        for kpi in result["kpis"]:
            if kpi["key"] not in COMPARE_KPIS:
                continue
            definitions[kpi["key"]] = {"key": kpi["key"], "label": kpi["label"], "unit": kpi["unit"], "definition": kpi["hint"], "target": kpi["target"], "higher_better": kpi["higher_better"]}
            values[kpi["key"]] = {"value": kpi["value"], "status": kpi["status"], "detail": kpi["detail"], "insufficient": kpi["value"] is None}
        rows.append({"warehouse_id": warehouse.id, "name": warehouse.name, "values": values, "link": f"/app/analytics?warehouse={warehouse.id}"})
    start, end = period if period else (date_from, date_to)
    lo = dispatch_service.local_to_utc(datetime.combine(start, time.min)) if start else None
    hi = dispatch_service.local_to_utc(datetime.combine(end + timedelta(days=1), time.min)) if end else None
    now = _now()
    teams = []
    for team, label in TEAM_LABELS.items():
        items = db.query(OperationException).filter(OperationException.team == team).all()
        opened = [i for i in items if (lo is None or i.opened_at >= lo) and (hi is None or i.opened_at < hi)]
        closed = [i for i in items if i.closed_at and (lo is None or i.closed_at >= lo) and (hi is None or i.closed_at < hi)]
        active = [i for i in items if i.status in ACTIVE_EXCEPTION_STATUSES]
        hours = [(i.closed_at - i.opened_at).total_seconds() / 3600 for i in closed]
        teams.append({"team": team, "label": label, "opened": len(opened), "closed": len(closed), "open_now": len(active),
                      "overdue_now": sum(1 for i in active if i.due_at and i.due_at < now), "avg_close_hours": round(sum(hours) / len(hours), 1) if hours else None,
                      "link": f"/app/exceptions?status=active&team={team}"})
    return {"date_from": start, "date_to": end, "generated_at": now, "metrics": [definitions[k] for k in COMPARE_KPIS if k in definitions], "warehouses": rows, "teams": teams,
            "notes": ["«داده کافی نیست» یعنی در این بازه مخرجی برای این شاخص نبوده است؛ این انبار با صفر مقایسه نمی‌شود.",
                      "زمان بستن تیم‌ها فقط از استثناهای بسته‌شده در این بازه است و نوع کار تیم‌ها یکسان نیست."]}


def capacity(db: Session, user: User, day: date) -> dict:
    role = _role(user)
    if role not in ("org_admin", "warehouse_manager", "fleet_manager"):
        raise ForbiddenError("این نما برای نقش شما باز نیست.")
    warehouse_id = user.warehouse_id if role == "warehouse_manager" else None
    lo = dispatch_service.local_to_utc(datetime.combine(day, time.min))
    hi = dispatch_service.local_to_utc(datetime.combine(day + timedelta(days=1), time.min))
    query = db.query(Order).filter(Order.status.in_(ACTIVE_ORDER_STATUSES), Order.delivery_window_start >= lo, Order.delivery_window_start < hi)
    if warehouse_id:
        query = query.filter(Order.warehouse_id == warehouse_id)
    orders = query.all()
    volumes = capacity_service.order_volumes(db, [o.id for o in orders])
    warnings: list[dict] = []

    by_vehicle: dict[int, list[Order]] = defaultdict(list)
    for order in orders:
        if order.vehicle_id:
            by_vehicle[order.vehicle_id].append(order)
    vehicles = []
    for vehicle in db.query(Vehicle).filter(Vehicle.id.in_(list(by_vehicle) or [-1])).all():
        loads = by_vehicle[vehicle.id]
        known = [volumes.get(o.id) for o in loads]
        check = capacity_service.check(vehicle, sum(o.total_weight_kg or 0 for o in loads), None if any(v is None for v in known) else sum(known))
        vehicles.append({"vehicle_id": vehicle.id, "plate": vehicle.license_plate, "orders": len(loads), "weight_kg": round(check.weight_kg, 1), "max_weight_kg": check.max_weight_kg,
                         "weight_pct": check.weight_pct, "volume_m3": check.volume_m3, "max_volume_m3": check.max_volume_m3, "volume_pct": check.volume_pct, "over": not check.ok})
        if not check.ok:
            warnings.append({"kind": "vehicle", "severity": "warning", "text": f"خودروی {vehicle.license_plate}: مجموع بار این روز از سقف یک سفر بیشتر است ({round(check.weight_kg)} کیلوگرم).", "link": "/app/map"})

    by_driver: dict[int, int] = defaultdict(int)
    for order in orders:
        if order.driver_id:
            by_driver[order.driver_id] += 1
    drivers = []
    if by_driver:
        people = {u.id: u.full_name or u.username for u in db.query(User).filter(User.id.in_(list(by_driver))).all()}
        limits = {p.user_id: p.max_daily_orders for p in db.query(DriverProfile).filter(DriverProfile.user_id.in_(list(by_driver))).all()}
        off = {t.user_id for t in db.query(DriverTimeOff).filter(DriverTimeOff.user_id.in_(list(by_driver)), DriverTimeOff.starts_at < hi, DriverTimeOff.ends_at > lo).all()}
        for driver_id, count in by_driver.items():
            limit = limits.get(driver_id)
            over = bool(limit) and count > limit
            drivers.append({"driver_id": driver_id, "name": people.get(driver_id, "—"), "orders": count, "max_daily_orders": limit, "over": over, "time_off": driver_id in off})
            if over:
                warnings.append({"kind": "driver", "severity": "warning", "text": f"{people.get(driver_id)}: {count} سفارش از سقف {limit} بیشتر است.", "link": "/app/schedules"})
            if driver_id in off:
                warnings.append({"kind": "driver", "severity": "danger", "text": f"{people.get(driver_id)} در این روز مرخصی دارد و {count} سفارش به او خورده است.", "link": "/app/schedules"})

    unassigned = [o for o in orders if not o.vehicle_id]
    if unassigned:
        warnings.append({"kind": "orders", "severity": "warning", "text": f"{len(unassigned)} سفارش این روز هنوز خودرو ندارد.", "link": "/app/orders?order_status=pending"})

    locations = db.query(Location).filter((Location.max_weight_kg.is_not(None)) | (Location.max_volume_m3.is_not(None)))
    if warehouse_id:
        locations = locations.filter(Location.warehouse_id == warehouse_id)
    locations = locations.all()
    contents = location_service.contents(db, [loc.id for loc in locations])
    product_ids = {c.product_id for items in contents.values() for c in items}
    products = {p.id: p for p in db.query(Product).filter(Product.id.in_(product_ids or {-1})).all()}
    full = []
    for location in locations:
        used = location_service.usage(contents.get(location.id, []), products)
        if (location.max_weight_kg and used["weight_kg"] >= location.max_weight_kg) or (location.max_volume_m3 and used["volume_m3"] >= location.max_volume_m3):
            full.append({"location_id": location.id, "code": location.code, "weight_kg": used["weight_kg"], "max_weight_kg": location.max_weight_kg, "volume_m3": used["volume_m3"], "max_volume_m3": location.max_volume_m3})
    if full:
        warnings.append({"kind": "storage", "severity": "warning", "text": f"{len(full)} محل به سقف ظرفیت رسیده است.", "link": "/app/locations"})

    def scoped(q, column):
        return q.filter(column == warehouse_id) if warehouse_id else q
    workload = [
        {"key": "receipts", "label": "رسید باز", "count": scoped(db.query(InboundReceipt).filter(InboundReceipt.status.in_(OPEN_RECEIPT_STATUSES)), InboundReceipt.warehouse_id).count()},
        {"key": "putaway", "label": "جانمایی منتظر", "count": scoped(db.query(PutawayTask).filter(PutawayTask.status.in_(("open", "partial"))), PutawayTask.warehouse_id).count()},
        {"key": "picks", "label": "سطر برداشت باز", "count": scoped(db.query(PickLine).join(PickList, PickLine.pick_list_id == PickList.id).filter(PickLine.status == "open"), PickList.warehouse_id).count()},
    ]
    return {
        "day": day, "generated_at": _now(), "orders": len(orders), "unassigned_orders": len(unassigned), "vehicles": vehicles, "drivers": drivers, "full_locations": full,
        "workload": workload, "warnings": warnings,
        "assumptions": ["فقط سفارش‌های ثبت‌شده این روز حساب شده‌اند؛ پیش‌بینی تقاضا در این نما نیست.",
                        "بار خودرو جمع کل روز است، در حالی که خودرو ممکن است چند سفر برود؛ پس هشدار خودرو نشانه بررسی است، نه خطای قطعی.",
                        "برای کار انبار سقف و نرخ کار تعریف نشده است؛ این عددها فقط شمار کارند و هشدار نمی‌دهند.",
                        "این نما هیچ سفارش، تخصیص، موجودی یا برنامه‌ای را تغییر نمی‌دهد."],
    }
