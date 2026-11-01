"""
بسته‌بندی و ارسال — فصل ۱۴

بسته‌بندی (pack): اقلام سفارش برداشت‌شده (یا سفارش بدون پیکینگ) در یک یا چند بسته با ابعاد و وزن واقعی؛
مجموع اقلام بسته‌ها باید دقیقاً با اقلام سفارش برابر باشد. بسته‌بندی دوباره تا پیش از ارسال مجاز است.
برگه بسته‌بندی (packing slip): محتوای هر بسته برای چاپ و چسباندن روی بسته.

محموله (shipment): سفارش‌های بسته‌بندی‌شده یک انبار روی یک خودرو. مجموع وزن و حجم بسته‌ها (همراه محموله‌های
باز دیگر همان خودرو) از ظرفیت وزنی و حجمی خودرو بیشتر نمی‌شود. «تحویل به راننده» همه سفارش‌ها را «بارگیری شد»
می‌کند: حواله خروج دقیقاً از همان محل/بچ برداشت‌شده صادر و رزرو مصرف می‌شود.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy.orm import Session, selectinload

from app.core.wms import FULFILLMENT_LABELS, SHIPMENT_STATUS_LABELS
from app.models import Order, Package, PackageItem, PickLine, Product, Shipment, User, Vehicle
from app.services import capacity_service, dispatch_service, event_bus, location_service, stock_ledger
from app.services.exceptions import ConflictError, NotFoundError


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _order(db: Session, user: User, order_id: int, *, lock: bool = True) -> Order:
    query = db.query(Order).options(selectinload(Order.items)).filter(Order.id == order_id)
    order = (query.with_for_update() if lock else query).first()
    if order is None:
        raise NotFoundError("سفارش یافت نشد.")
    location_service.scope_warehouse(user, order.warehouse_id)
    return order


# ---------------------------------------------------------------------------
# بسته‌بندی
# ---------------------------------------------------------------------------
def pack(db: Session, user: User, order_id: int, data) -> dict:
    try:
        order = _order(db, user, order_id)
        if order.stock_state != "reserved":
            raise ConflictError("فقط سفارشی که کالایش رزرو و هنوز خارج نشده بسته‌بندی می‌شود.")
        if order.shipment_id is not None and db.get(Shipment, order.shipment_id).status == "dispatched":
            raise ConflictError("این سفارش ارسال شده است.")
        has_picking = db.query(PickLine.id).filter(PickLine.order_id == order.id, PickLine.status != "canceled").first()
        if order.fulfillment_state not in ("picked", "packed") and (has_picking or order.fulfillment_state != "open"):
            raise ConflictError(f"سفارش {order.tracking_code} هنوز «{FULFILLMENT_LABELS[order.fulfillment_state]}» است؛ "
                                "ابتدا برداشت را کامل کنید.")
        expected: dict[int, int] = defaultdict(int)
        for item in order.items:
            if item.product_id:
                expected[item.product_id] += item.quantity
        packed: dict[int, int] = defaultdict(int)
        for package in data.packages:
            for entry in package.items:
                packed[entry.product_id] += entry.quantity
        if dict(packed) != dict(expected):
            diff = [f"«{db.get(Product, pid).name}»: سفارش {expected.get(pid, 0)}، بسته‌ها {packed.get(pid, 0)}"
                    for pid in sorted(set(expected) | set(packed)) if expected.get(pid, 0) != packed.get(pid, 0)]
            raise ConflictError("اقلام بسته‌ها با اقلام سفارش برابر نیست: " + "؛ ".join(diff))
        weights = {item.product_id: item.unit_weight_kg or 0 for item in order.items}
        for old in db.query(Package).filter(Package.order_id == order.id).all():
            db.delete(old)
        db.flush()
        for number, spec in enumerate(data.packages, start=1):
            content_weight = sum(weights.get(e.product_id, 0) * e.quantity for e in spec.items)
            package = Package(organization_id=order.organization_id, code=f"{order.tracking_code}-{number}", order_id=order.id,
                              sequence=number, length_cm=spec.length_cm, width_cm=spec.width_cm, height_cm=spec.height_cm,
                              weight_kg=spec.weight_kg or max(round(content_weight, 3), 0.01), created_at=_now(),
                              packed_by_id=user.id)
            for entry in spec.items:
                package.items.append(PackageItem(organization_id=order.organization_id, product_id=entry.product_id,
                                                 quantity=entry.quantity))
            db.add(package)
        order.fulfillment_state = "packed"
        db.flush()
        event_bus.emit(db, "order.packed", "order", order.id,
                       {"tracking_code": order.tracking_code, "packages": len(data.packages)},
                       organization_id=order.organization_id, actor=user)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return packing_slip(db, user, order_id)


def packing_slip(db: Session, user: User, order_id: int) -> dict:
    order = _order(db, user, order_id, lock=False)
    packages = db.query(Package).options(selectinload(Package.items).selectinload(PackageItem.product)) \
        .filter(Package.order_id == order.id).order_by(Package.sequence).all()
    return {
        "order_id": order.id, "tracking_code": order.tracking_code, "fulfillment_state": order.fulfillment_state,
        "recipient_name": order.recipient_name, "recipient_mobile": order.recipient_mobile,
        "destination": " / ".join(filter(None, [order.destination_province, order.destination_city, order.destination_address])),
        "delivery_window_start": order.delivery_window_start, "shipment_id": order.shipment_id,
        "total_weight_kg": round(sum(p.weight_kg for p in packages), 3),
        "total_volume_m3": round(sum(p.volume_m3 for p in packages), 4),
        "packages": [{
            "id": p.id, "code": p.code, "sequence": p.sequence, "length_cm": p.length_cm, "width_cm": p.width_cm,
            "height_cm": p.height_cm, "weight_kg": p.weight_kg, "volume_m3": round(p.volume_m3, 4),
            "items": [{"product_id": i.product_id, "product_name": i.product.name, "product_sku": i.product.sku,
                       "quantity": i.quantity} for i in p.items],
        } for p in packages],
    }


# ---------------------------------------------------------------------------
# محموله
# ---------------------------------------------------------------------------
def _load(db: Session, order_ids) -> tuple[float, float]:
    packages = db.query(Package).filter(Package.order_id.in_(list(order_ids) or [-1])).all()
    return sum(p.weight_kg for p in packages), sum(p.volume_m3 for p in packages)


def _other_load(db: Session, vehicle: Vehicle, shipment: Shipment | None) -> tuple[float, float]:
    others = db.query(Order.id).join(Shipment, Order.shipment_id == Shipment.id).filter(
        Shipment.vehicle_id == vehicle.id, Shipment.status == "open",
        Shipment.id != (shipment.id if shipment else -1)).all()
    return _load(db, [o for (o,) in others])


def _capacity_message(result: capacity_service.CapacityCheck) -> str | None:
    if result.weight_over:
        return f"ظرفیت وزنی خودرو {result.max_weight_kg:g} کیلوگرم است؛ بار محموله {result.weight_kg:g} کیلوگرم می‌شود."
    if result.volume_over:
        return f"ظرفیت حجمی خودرو {result.max_volume_m3:g} مترمکعب است؛ بار محموله {result.volume_m3:.3f} مترمکعب می‌شود."
    return None


def _check_capacity(db: Session, vehicle: Vehicle, shipment: Shipment | None, order_ids: list[int]) -> tuple[float, float]:
    """وزن و حجم محموله + محموله‌های باز دیگر همان خودرو ≤ ظرفیت خودرو."""
    weight, volume = _load(db, order_ids)
    other_weight, other_volume = _other_load(db, vehicle, shipment)
    message = _capacity_message(capacity_service.check(vehicle, weight, volume, other_weight, other_volume))
    if message:
        raise ConflictError(message)
    return weight, volume


def preview_shipment(db: Session, user: User, data) -> dict:
    """پیش از ساخت محموله: درصد استفاده از ظرفیت و سفارش‌هایی که سبب اضافه‌بار می‌شوند (چیزی ذخیره نمی‌شود)."""
    warehouse_id = location_service.scope_warehouse(user, data.warehouse_id)
    vehicle = db.get(Vehicle, data.vehicle_id)
    if vehicle is None:
        raise NotFoundError("خودرو یافت نشد.")
    orders = db.query(Order).filter(Order.id.in_(data.order_ids)).order_by(Order.id).all()
    if len(orders) != len(set(data.order_ids)):
        raise NotFoundError("بعضی سفارش‌ها یافت نشدند.")
    if warehouse_id is not None and any(o.warehouse_id != warehouse_id for o in orders):
        raise ConflictError("همه سفارش‌های محموله باید از همین انبار باشند.")
    other_weight, other_volume = _other_load(db, vehicle, None)
    running_weight, running_volume, over = 0.0, 0.0, []
    for order in orders:
        weight, volume = _load(db, [order.id])
        running_weight, running_volume = running_weight + weight, running_volume + volume
        if not capacity_service.check(vehicle, running_weight, running_volume, other_weight, other_volume).ok:
            over.append({"id": order.id, "tracking_code": order.tracking_code, "weight_kg": round(weight, 3), "volume_m3": round(volume, 4)})
    result = capacity_service.check(vehicle, running_weight, running_volume, other_weight, other_volume)
    return {
        "weight_kg": round(running_weight, 3), "volume_m3": round(running_volume, 4), "other_weight_kg": round(other_weight, 3),
        "other_volume_m3": round(other_volume, 4), "max_weight_kg": result.max_weight_kg, "max_volume_m3": result.max_volume_m3,
        "weight_pct": result.weight_pct, "volume_pct": result.volume_pct, "ok": result.ok,
        "message": _capacity_message(result), "over_orders": over,
    }


def _attach(db: Session, user: User, shipment: Shipment, orders: list[Order], vehicle: Vehicle) -> None:
    from app.services import order_service
    for order in orders:
        if order.warehouse_id != shipment.warehouse_id:
            raise ConflictError(f"سفارش {order.tracking_code} از انبار دیگری است.")
        if order.fulfillment_state != "packed":
            raise ConflictError(f"سفارش {order.tracking_code} هنوز بسته‌بندی نشده است.")
        if order.shipment_id not in (None, shipment.id):
            raise ConflictError(f"سفارش {order.tracking_code} در محموله دیگری است.")
        if order.status not in ("pending", "assigned", "picking_up"):
            raise ConflictError(f"سفارش {order.tracking_code} «{order.status}» است و قابل بارگیری نیست.")
        order.shipment_id = shipment.id
        if order.vehicle_id != vehicle.id:
            order.vehicle_id, order.driver_id = vehicle.id, vehicle.driver_id
        if order.status == "pending":
            order.status = "assigned"
            order_service.record_history(db, order, "pending", "assigned", user,
                                         f"تخصیص به محموله {shipment.code} (خودرو {vehicle.license_plate or vehicle.id})")


def create_shipment(db: Session, user: User, data) -> dict:
    warehouse_id = location_service.scope_warehouse(user, data.warehouse_id)
    if warehouse_id is None:
        raise ConflictError("انبار را انتخاب کنید.")
    try:
        vehicle = db.query(Vehicle).filter(Vehicle.id == data.vehicle_id).with_for_update().first()
        if vehicle is None:
            raise NotFoundError("خودرو یافت نشد.")
        if vehicle.is_active is False or vehicle.status in ("maintenance", "inactive"):
            raise ConflictError("این خودرو فعال نیست.")
        orders = db.query(Order).filter(Order.id.in_(data.order_ids)).order_by(Order.id).with_for_update().all()
        if len(orders) != len(set(data.order_ids)):
            raise NotFoundError("بعضی سفارش‌ها یافت نشدند.")
        shipment = Shipment(code=stock_ledger.new_code(db, Shipment, "SH"), status="open", warehouse_id=warehouse_id,
                            vehicle_id=vehicle.id, driver_id=vehicle.driver_id, note=data.note, created_at=_now(),
                            created_by_id=user.id)
        db.add(shipment)
        db.flush()
        _attach(db, user, shipment, orders, vehicle)
        weight, volume = _check_capacity(db, vehicle, shipment, [o.id for o in orders])
        event_bus.emit(db, "shipment.created", "shipment", shipment.id,
                       {"code": shipment.code, "vehicle_id": vehicle.id, "orders": [o.id for o in orders],
                        "weight_kg": round(weight, 3), "volume_m3": round(volume, 4)},
                       organization_id=shipment.organization_id, actor=user)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_shipment(db, user, shipment.id)


def _lock_shipment(db: Session, user: User, shipment_id: int) -> Shipment:
    shipment = db.query(Shipment).filter(Shipment.id == shipment_id).with_for_update().first()
    if shipment is None:
        raise NotFoundError("محموله یافت نشد.")
    location_service.scope_warehouse(user, shipment.warehouse_id)
    if shipment.status != "open":
        raise ConflictError(f"محموله {shipment.code} {SHIPMENT_STATUS_LABELS[shipment.status]} است.")
    return shipment


def remove_order(db: Session, user: User, shipment_id: int, order_id: int) -> dict:
    try:
        shipment = _lock_shipment(db, user, shipment_id)
        order = _order(db, user, order_id)
        if order.shipment_id != shipment.id:
            raise ConflictError("این سفارش در این محموله نیست.")
        order.shipment_id = None
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_shipment(db, user, shipment_id)


def dispatch(db: Session, user: User, shipment_id: int, note: str | None = None) -> dict:
    """تحویل به راننده: همه سفارش‌های محموله «بارگیری شد» و حواله خروجشان صادر می‌شود (همه یا هیچ)."""
    from app.services import order_service
    try:
        shipment = _lock_shipment(db, user, shipment_id)
        orders = db.query(Order).filter(Order.shipment_id == shipment.id).order_by(Order.id).with_for_update().all()
        if not orders:
            raise ConflictError("این محموله سفارشی ندارد.")
        vehicle = db.get(Vehicle, shipment.vehicle_id) if shipment.vehicle_id else None
        if vehicle is None:
            raise ConflictError("خودروی این محموله حذف شده است.")
        _check_capacity(db, vehicle, shipment, [o.id for o in orders])
        today = dispatch_service.to_local(_now()).date()
        for order in orders:
            day = dispatch_service.to_local(dispatch_service.to_utc_naive(order.delivery_window_start)).date()
            if today < day:
                raise ConflictError(f"سفارش {order.tracking_code} برای تحویل در روز دیگری است و امروز بارگیری نمی‌شود.")
            if order.fulfillment_state != "packed":
                raise ConflictError(f"سفارش {order.tracking_code} بسته‌بندی نشده است.")
            order_service.apply_status(db, order, "picked_up", user, note or f"تحویل محموله {shipment.code} به راننده")
        shipment.status, shipment.dispatched_at, shipment.dispatched_by_id = "dispatched", _now(), user.id
        shipment.driver_id = vehicle.driver_id
        event_bus.emit(db, "shipment.dispatched", "shipment", shipment.id,
                       {"code": shipment.code, "orders": [o.id for o in orders], "driver_id": shipment.driver_id},
                       organization_id=shipment.organization_id, actor=user)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_shipment(db, user, shipment_id)


def close(db: Session, user: User, shipment_id: int) -> dict:
    """بستن سفر: فقط وقتی همه سفارش‌ها پایان یافته‌اند و هیچ برگشتی از راننده باز نیست."""
    from app.models_productivity import DriverReturn
    try:
        shipment = db.query(Shipment).filter(Shipment.id == shipment_id).with_for_update().first()
        if shipment is None:
            raise NotFoundError("محموله یافت نشد.")
        location_service.scope_warehouse(user, shipment.warehouse_id)
        if shipment.status != "dispatched":
            raise ConflictError(f"محموله {shipment.code} {SHIPMENT_STATUS_LABELS[shipment.status]} است و بسته نمی‌شود.")
        orders = db.query(Order).filter(Order.shipment_id == shipment.id).all()
        open_orders = [o.tracking_code for o in orders if o.status in ("picked_up", "in_transit", "assigned", "picking_up")
                       or (o.status == "failed" and o.failure_resolution in (None, "dispute"))]
        if open_orders:
            raise ConflictError("این سفارش‌ها هنوز تمام نشده‌اند: " + "، ".join(open_orders))
        ids = [o.id for o in orders] or [-1]
        pending = db.query(Order.tracking_code).join(DriverReturn, DriverReturn.order_id == Order.id).filter(
            DriverReturn.order_id.in_(ids), DriverReturn.status == "open").all()
        if pending:
            raise ConflictError("پیش از بستن سفر، برگشت این سفارش‌ها را در انبار ثبت کنید: " + "، ".join(c for (c,) in pending))
        shipment.status, shipment.closed_at, shipment.closed_by_id = "closed", _now(), user.id
        event_bus.emit(db, "shipment.closed", "shipment", shipment.id, {"code": shipment.code},
                       organization_id=shipment.organization_id, actor=user)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_shipment(db, user, shipment_id)


def cancel(db: Session, user: User, shipment_id: int) -> dict:
    try:
        shipment = _lock_shipment(db, user, shipment_id)
        for order in db.query(Order).filter(Order.shipment_id == shipment.id).all():
            order.shipment_id = None
        shipment.status = "canceled"
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_shipment(db, user, shipment_id)


def _serialize(db: Session, shipment: Shipment) -> dict:
    orders = db.query(Order).filter(Order.shipment_id == shipment.id).order_by(Order.id).all()
    weight, volume = _load(db, [o.id for o in orders])
    vehicle = shipment.vehicle
    limit_weight = capacity_service.weight_limit(vehicle) if vehicle else None
    return {
        "id": shipment.id, "code": shipment.code, "status": shipment.status,
        "status_label": SHIPMENT_STATUS_LABELS[shipment.status], "warehouse_id": shipment.warehouse_id,
        "vehicle_id": shipment.vehicle_id, "vehicle_plate": vehicle.license_plate if vehicle else None,
        "driver_name": (shipment.driver.full_name or shipment.driver.username) if shipment.driver else None,
        "weight_kg": round(weight, 3), "volume_m3": round(volume, 4),
        "max_weight_kg": limit_weight, "max_volume_m3": vehicle.max_volume_m3 if vehicle else None,
        "note": shipment.note, "created_at": shipment.created_at, "dispatched_at": shipment.dispatched_at,
        "orders": [{"id": o.id, "tracking_code": o.tracking_code, "status": o.status, "recipient_name": o.recipient_name,
                    "destination_city": o.destination_city, "fulfillment_state": o.fulfillment_state} for o in orders],
    }


def get_shipment(db: Session, user: User, shipment_id: int) -> dict:
    shipment = db.get(Shipment, shipment_id)
    if shipment is None:
        raise NotFoundError("محموله یافت نشد.")
    location_service.scope_warehouse(user, shipment.warehouse_id)
    return _serialize(db, shipment)


def list_shipments(db: Session, user: User, *, warehouse_id: int | None = None, status: str | None = None) -> list[dict]:
    warehouse_id = location_service.scope_warehouse(user, warehouse_id)
    query = db.query(Shipment)
    if warehouse_id is not None:
        query = query.filter(Shipment.warehouse_id == warehouse_id)
    if status:
        query = query.filter(Shipment.status == status)
    return [_serialize(db, s) for s in query.order_by(Shipment.id.desc()).limit(100).all()]


def packing_queue(db: Session, user: User, warehouse_id: int | None) -> list[dict]:
    """سفارش‌های آماده بسته‌بندی/ارسال یک انبار (برداشت‌شده، بسته‌بندی‌شده بدون محموله، یا بدون پیکینگ)."""
    warehouse_id = location_service.scope_warehouse(user, warehouse_id)
    if warehouse_id is None:
        raise ConflictError("انبار را انتخاب کنید.")
    orders = db.query(Order).options(selectinload(Order.items)).filter(
        Order.warehouse_id == warehouse_id, Order.stock_state == "reserved",
        Order.status.in_(("pending", "assigned", "picking_up")),
        Order.fulfillment_state.in_(("open", "picked", "packed")),
    ).order_by(Order.priority.desc(), Order.delivery_window_start, Order.id).limit(300).all()
    picking = {oid for (oid,) in db.query(PickLine.order_id).filter(
        PickLine.order_id.in_([o.id for o in orders] or [-1]), PickLine.status != "canceled").distinct().all()}
    result = []
    for o in orders:
        if o.fulfillment_state == "open" and o.id in picking:
            continue
        weight, volume = _load(db, [o.id])
        result.append({
            "id": o.id, "tracking_code": o.tracking_code, "status": o.status, "fulfillment_state": o.fulfillment_state,
            "fulfillment_label": FULFILLMENT_LABELS[o.fulfillment_state], "recipient_name": o.recipient_name,
            "destination_city": o.destination_city, "delivery_window_start": o.delivery_window_start,
            "shipment_id": o.shipment_id, "packed_weight_kg": round(weight, 3), "packed_volume_m3": round(volume, 4),
            "items": [{"product_id": i.product_id, "product_name": i.product_name, "product_sku": i.product_sku,
                       "quantity": i.quantity, "unit_weight_kg": i.unit_weight_kg} for i in o.items if i.product_id],
        })
    return result
