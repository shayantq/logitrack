"""
سفارش معوق (Backorder) و تخصیص با اولویت (فصل ۱۱)

- ثبت سفارش با «پذیرش معوق»: آنچه موجودی قابل وعده دارد رزرو می‌شود و باقی‌مانده هر قلم یک سفارش معوق
  «در انتظار موجودی» می‌شود — مقدار تأمین‌نشده هیچ‌وقت دور ریخته نمی‌شود.
- تخصیص (allocate): سفارش‌های معوق باز به ترتیب اولویت سفارش، تاریخ تحویل درخواستی و زمان ثبت (FIFO)
  از موجودی قابل وعده رزرو می‌شوند. تخصیص جزئی مجاز است: بخش تخصیص‌یافته جدا می‌شود و باقی در صف می‌ماند.
  هر ردیف موجودی پیش از رزرو قفل می‌شود (همان سد هم‌زمانی ثبت سفارش)، پس دو تخصیص هم‌زمان بیش از موجودی رزرو نمی‌کنند.
- سفارش تکمیلی (fulfill): سفارش‌های معوقِ تخصیص‌یافته یک سفارش با یک سفارش جدید (همان مشتری و مقصد)
  ارسال می‌شوند؛ رزروشان در همان تراکنش به سفارش جدید منتقل می‌شود.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session, joinedload

from app.core.wms import AVAILABLE, BACKORDER_STATUS_LABELS
from app.models import Backorder, Inventory, Order, OrderItem, Product, User
from app.services import allocation_service, event_bus, location_service
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError

OPEN = ("open", "allocated")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _role(user: User | None) -> str | None:
    return getattr(user.role, "value", user.role) if user else None


def open_backorder(db: Session, user: User | None, order: Order, product: Product, quantity: int, unit_price: float) -> Backorder:
    backorder = Backorder(
        organization_id=order.organization_id, order_id=order.id, product_id=product.id, warehouse_id=order.warehouse_id,
        quantity=quantity, unit_price=unit_price or 0, status="open", priority=bool(order.priority),
        due_at=order.delivery_window_start.replace(tzinfo=None) if order.delivery_window_start.tzinfo else order.delivery_window_start,
        created_at=_now(), created_by_id=user.id if user else None,
    )
    db.add(backorder)
    db.flush()
    event_bus.emit(db, "backorder.created", "backorder", backorder.id,
                   {"order_id": order.id, "product_id": product.id, "quantity": quantity}, organization_id=order.organization_id,
                   actor=user)
    return backorder


def _queue(db: Session, warehouse_id: int | None = None, product_id: int | None = None):
    """صف تخصیص: اولویت‌دار، زودتر سررسید، زودتر ثبت‌شده."""
    query = db.query(Backorder).filter(Backorder.status == "open")
    if warehouse_id is not None:
        query = query.filter(Backorder.warehouse_id == warehouse_id)
    if product_id is not None:
        query = query.filter(Backorder.product_id == product_id)
    return query.order_by(Backorder.priority.desc(), Backorder.due_at, Backorder.created_at, Backorder.id)


def allocate(db: Session, user: User | None, *, warehouse_id: int | None = None, product_id: int | None = None) -> dict:
    """موجودی قابل وعده را به ترتیب اولویت به سفارش‌های معوق باز تخصیص (رزرو) می‌دهد."""
    if user is not None:
        warehouse_id = location_service.scope_warehouse(user, warehouse_id)
    try:
        queue = _queue(db, warehouse_id, product_id).with_for_update().all()
        buckets = {}
        allocated, partial = 0, 0
        for backorder in queue:
            key = (backorder.product_id, backorder.warehouse_id)
            if key not in buckets:
                buckets[key] = db.query(Inventory).filter(
                    Inventory.product_id == backorder.product_id, Inventory.warehouse_id == backorder.warehouse_id,
                    Inventory.stock_status == AVAILABLE).with_for_update().first()
            inventory = buckets[key]
            if inventory is None:
                continue
            free = allocation_service.available_to_promise(db, inventory)
            if free <= 0:
                continue
            take = min(free, backorder.quantity)
            if take < backorder.quantity:
                # بخش تخصیص‌یافته جدا می‌شود؛ باقی‌مانده با همان اولویت و سررسید در صف می‌ماند
                rest = Backorder(
                    organization_id=backorder.organization_id, order_id=backorder.order_id, product_id=backorder.product_id,
                    warehouse_id=backorder.warehouse_id, quantity=backorder.quantity - take, unit_price=backorder.unit_price,
                    status="open", priority=backorder.priority, due_at=backorder.due_at, created_at=backorder.created_at,
                    created_by_id=backorder.created_by_id, note=backorder.note,
                )
                db.add(rest)
                backorder.quantity = take
                partial += 1
            db.flush()
            allocation_service.reserve(db, inventory, take, reference_type="backorder", reference_id=backorder.id, user=user)
            backorder.status, backorder.allocated_at = "allocated", _now()
            allocated += take
            event_bus.emit(db, "backorder.allocated", "backorder", backorder.id,
                           {"order_id": backorder.order_id, "product_id": backorder.product_id, "quantity": take},
                           organization_id=backorder.organization_id, actor=user)
        db.commit()
        return {"allocated_quantity": allocated, "split": partial}
    except Exception:
        db.rollback()
        raise


def fulfill(db: Session, user: User, order_id: int, delivery_window_start: datetime, delivery_window_end: datetime) -> Order:
    """سفارش تکمیلی از سفارش‌های معوقِ تخصیص‌یافته یک سفارش؛ رزروها به سفارش جدید منتقل می‌شوند."""
    if _role(user) not in ("org_admin", "warehouse_manager"):
        raise ForbiddenError()
    from app.services import commission_service, order_service
    try:
        source = db.get(Order, order_id)
        if source is None:
            raise NotFoundError("سفارش یافت نشد.")
        location_service.scope_warehouse(user, source.warehouse_id)
        backorders = db.query(Backorder).filter(Backorder.order_id == source.id, Backorder.status == "allocated") \
            .order_by(Backorder.id).with_for_update().all()
        if not backorders:
            raise ConflictError("این سفارش، سفارش معوقِ تخصیص‌یافته‌ای ندارد.")
        quantities: dict[int, int] = {}
        prices: dict[int, float] = {}
        for b in backorders:
            quantities[b.product_id] = quantities.get(b.product_id, 0) + b.quantity
            prices[b.product_id] = b.unit_price
        products = {p.id: p for p in db.query(Product).filter(Product.id.in_(list(quantities))).all()}
        weight = sum((products[pid].weight_kg or 0) * q for pid, q in quantities.items())
        order = Order(
            organization_id=source.organization_id, tracking_code=order_service.new_tracking_code(db), status="pending",
            size=source.size, priority=source.priority, delivery_window_start=delivery_window_start,
            delivery_window_end=delivery_window_end, notes=f"تکمیلی سفارش {source.tracking_code}",
            customer_id=source.customer_id, recipient_name=source.recipient_name, recipient_mobile=source.recipient_mobile,
            destination_province=source.destination_province, destination_city=source.destination_city,
            destination_address=source.destination_address, destination_postal_code=source.destination_postal_code,
            warehouse_id=source.warehouse_id, delivery_fee=commission_service.default_fee(commission_service.get_plan(db), weight),
            total_quantity=sum(quantities.values()), total_weight_kg=weight,
            total_price=sum(prices[pid] * q for pid, q in quantities.items()), stock_state="reserved",
            parent_order_id=source.id,
        )
        db.add(order)
        for pid, q in quantities.items():
            p = products[pid]
            order.items.append(OrderItem(organization_id=source.organization_id, product_id=pid, product_name=p.name,
                                         product_sku=p.sku, quantity=q, unit_price=prices[pid],
                                         unit_weight_kg=p.weight_kg or 0))
        db.flush()
        for b in backorders:
            for reservation in allocation_service.active_for(db, "backorder", b.id):
                allocation_service.transfer(db, reservation, reference_type="order", reference_id=order.id, user=user,
                                            reason=f"سفارش تکمیلی {order.tracking_code}")
            b.status, b.fulfilled_order_id, b.closed_at = "fulfilled", order.id, _now()
            event_bus.emit(db, "backorder.fulfilled", "backorder", b.id, {"order_id": source.id, "fulfilled_order_id": order.id},
                           organization_id=b.organization_id, actor=user)
        order_service.record_history(db, order, None, "pending", user, f"سفارش تکمیلی معوق‌های {source.tracking_code}")
        db.commit()
        return order
    except Exception:
        db.rollback()
        raise


def cancel(db: Session, user: User, backorder_id: int, reason: str) -> dict:
    try:
        backorder = db.query(Backorder).filter(Backorder.id == backorder_id).with_for_update().first()
        if backorder is None:
            raise NotFoundError("سفارش معوق یافت نشد.")
        location_service.scope_warehouse(user, backorder.warehouse_id)
        if backorder.status not in OPEN:
            raise ConflictError("این سفارش معوق بسته شده است.")
        _cancel(db, user, backorder, reason)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return serialize(backorder)


def _cancel(db: Session, user: User | None, backorder: Backorder, reason: str) -> None:
    for reservation in allocation_service.active_for(db, "backorder", backorder.id):
        allocation_service.release(db, reservation, user=user, reason=reason)
    backorder.status, backorder.closed_at, backorder.note = "canceled", _now(), (reason or "")[:300] or None
    event_bus.emit(db, "backorder.canceled", "backorder", backorder.id, {"order_id": backorder.order_id, "reason": reason},
                   organization_id=backorder.organization_id, actor=user)


def cancel_for_order(db: Session, user: User | None, order: Order, reason: str) -> None:
    """لغو/انقضای سفارش اصلی: سفارش‌های معوق باز آن هم لغو و رزروشان آزاد می‌شود."""
    for backorder in db.query(Backorder).filter(Backorder.order_id == order.id, Backorder.status.in_(OPEN)).all():
        _cancel(db, user, backorder, reason)


def serialize(b: Backorder, order: Order | None = None) -> dict:
    order = order or b.order
    return {
        "id": b.id, "order_id": b.order_id, "order_tracking_code": order.tracking_code if order else None,
        "customer_name": order.recipient_name if order else None, "product_id": b.product_id,
        "product_name": b.product.name, "product_sku": b.product.sku, "warehouse_id": b.warehouse_id,
        "quantity": b.quantity, "status": b.status, "status_label": BACKORDER_STATUS_LABELS[b.status],
        "priority": b.priority, "due_at": b.due_at, "created_at": b.created_at, "allocated_at": b.allocated_at,
        "fulfilled_order_id": b.fulfilled_order_id, "note": b.note,
    }


def list_backorders(db: Session, user: User, *, status: str | None = None, order_id: int | None = None,
                    warehouse_id: int | None = None) -> list[dict]:
    warehouse_id = location_service.scope_warehouse(user, warehouse_id)
    query = db.query(Backorder).options(joinedload(Backorder.product), joinedload(Backorder.order))
    if status == "active":
        query = query.filter(Backorder.status.in_(OPEN))
    elif status:
        query = query.filter(Backorder.status == status)
    if order_id is not None:
        query = query.filter(Backorder.order_id == order_id)
    if warehouse_id is not None:
        query = query.filter(Backorder.warehouse_id == warehouse_id)
    rows = query.order_by(Backorder.priority.desc(), Backorder.due_at, Backorder.created_at, Backorder.id).limit(500).all()
    return [serialize(b) for b in rows]

