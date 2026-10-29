"""
خط زمانی یکپارچه سفارش: از ثبت تا تحویل یا برگشت، از همه بخش‌ها در یک فهرست مرتب.

منبع‌ها: تاریخچه وضعیت، رزرو و اسناد انبار، برداشت، بسته‌بندی، محموله، عبور از شهرها، سفارش معوق،
تسویه کرایه (فقط ادمین)، تیکت‌ها و نظر مشتری. هر رویداد ناحیه (سفارش/انبار/ناوگان/مالی/پشتیبانی)،
انجام‌دهنده، نتیجه و پیوند به سند منبع دارد. سرآیند: مرحله فعلی، آخرین اقدام و مانع فعلی (اگر هست).
دسترسی همان جزئیات سفارش است (راننده فقط سفارش خودش).
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.iran import fa_digits
from app.core.wms import DOCUMENT_TYPES, RESERVATION_STATUS_LABELS
from app.models import (
    ACTIVE_ORDER_STATUSES, DriverRating, OrderCheckpoint, Product, Ticket, User, Vehicle,
)
from app.models_fulfillment import Backorder, Package, PickLine, PickList, Shipment
from app.models_wms import StockDocument, StockReservation
from app.services import order_service

AREAS = {"order": "سفارش", "warehouse": "انبار", "fleet": "ناوگان", "finance": "مالی", "support": "پشتیبانی"}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _names(db: Session, ids) -> dict[int, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {u.id: u.full_name or u.username for u in db.query(User).filter(User.id.in_(ids)).all()}


def _event(at, area: str, title: str, actor: str | None = None, outcome: str | None = None, link: str | None = None,
           source: str = "status") -> dict:
    return {"at": at, "area": area, "area_label": AREAS[area], "title": title, "actor": actor or "سیستم",
            "outcome": outcome, "link": link, "source": source}


def _money(value) -> str:
    return fa_digits(f"{int(round(value or 0)):,}") + " ریال"


def timeline(db: Session, user, order_id: int) -> dict:
    order = order_service.get_order(db, user, order_id)
    role = getattr(user.role, "value", user.role)
    events: list[dict] = []
    labels = order_service.STATUS_LABELS

    for h in order.history:
        title = f"وضعیت: {labels.get(h.to_status, h.to_status)}"
        area = "fleet" if h.to_status in ("assigned", "picking_up", "picked_up", "in_transit", "delivered", "failed") else "order"
        note = h.note
        if h.from_status is None:
            title, area = "سفارش ثبت شد", "order"
        elif h.from_status == h.to_status:          # تغییر بدون تغییر وضعیت (مثل اولویت)
            title, area, note = h.note or "به‌روزرسانی سفارش", "order", None
        actor = (h.changed_by.full_name or h.changed_by.username) if h.changed_by else None
        events.append(_event(h.changed_at, area, title, actor, note))

    reservations = db.query(StockReservation).filter(StockReservation.reference_type == "order",
                                                     StockReservation.reference_id == order.id).all()
    documents = db.query(StockDocument).filter(StockDocument.reference_type == "order",
                                               StockDocument.reference_id == order.id).all()
    pick_lines = db.query(PickLine).filter(PickLine.order_id == order.id).all()
    packages = db.query(Package).filter(Package.order_id == order.id).order_by(Package.sequence).all()
    checkpoints = db.query(OrderCheckpoint).filter(OrderCheckpoint.order_id == order.id).order_by(OrderCheckpoint.seq).all()
    backorders = db.query(Backorder).filter(Backorder.order_id == order.id).all()
    tickets = db.query(Ticket).filter(Ticket.order_id == order.id).all()
    ratings = db.query(DriverRating).filter(DriverRating.order_id == order.id).all()
    products = {p.id: p.name for p in db.query(Product).filter(
        Product.id.in_({r.product_id for r in reservations} | {b.product_id for b in backorders} | {p.product_id for p in pick_lines}
                       or {-1})).all()}
    people = _names(db, [r.created_by_id for r in reservations] + [d.created_by_id for d in documents]
                    + [p.picked_by_id for p in pick_lines] + [p.packed_by_id for p in packages]
                    + [c.reported_by_id for c in checkpoints])

    for r in reservations:
        events.append(_event(r.created_at, "warehouse", f"رزرو موجودی: {products.get(r.product_id, '')}",
                             people.get(r.created_by_id), f"{fa_digits(str(r.quantity))} عدد", "/app/inventory", source="reservation"))
        if r.closed_at:
            events.append(_event(r.closed_at, "warehouse", f"رزرو {RESERVATION_STATUS_LABELS.get(r.status, r.status)}: "
                                 f"{products.get(r.product_id, '')}", None, r.close_reason, "/app/inventory", source="reservation"))
    for d in documents:
        kind = DOCUMENT_TYPES.get(d.doc_type)
        events.append(_event(d.posted_at or d.created_at, "warehouse", f"{kind.label if kind else d.doc_type} {d.code}",
                             people.get(d.created_by_id), d.note, f"/app/documents?doc={d.id}", source="document"))
    lists = {p.id: p for p in db.query(PickList).filter(PickList.id.in_({line.pick_list_id for line in pick_lines} or {-1})).all()}
    for line in pick_lines:
        pick_list = lists.get(line.pick_list_id)
        code = pick_list.code if pick_list else ""
        if line.status in ("picked", "short") and line.picked_at:
            outcome = (f"کسری: {line.short_reason}" if line.status == "short"
                       else f"{fa_digits(str(line.picked_quantity))} از {fa_digits(str(line.quantity))}")
            events.append(_event(line.picked_at, "warehouse", f"برداشت {products.get(line.product_id, '')} ({code})",
                                 people.get(line.picked_by_id), outcome, "/app/picking", source="pick"))
        elif pick_list is not None:
            events.append(_event(pick_list.created_at, "warehouse", f"در فهرست برداشت {code}", None,
                                 products.get(line.product_id, ""), "/app/picking", source="pick"))
    for p in packages:
        events.append(_event(p.created_at, "warehouse", f"بسته {p.code}", people.get(p.packed_by_id),
                             f"{fa_digits(f'{p.weight_kg:g}')} کیلوگرم", "/app/shipping", source="package"))
    if order.shipment_id:
        shipment = db.get(Shipment, order.shipment_id)
        if shipment is not None:
            vehicle = db.get(Vehicle, shipment.vehicle_id) if shipment.vehicle_id else None
            events.append(_event(shipment.created_at, "fleet", f"در محموله {shipment.code}", None,
                                 vehicle.license_plate if vehicle else None, "/app/shipping", source="shipment"))
            if shipment.dispatched_at:
                events.append(_event(shipment.dispatched_at, "fleet", f"محموله {shipment.code} به راننده تحویل شد",
                                     None, None, "/app/shipping", source="shipment"))
    for c in checkpoints:
        events.append(_event(c.reached_at, "fleet", f"رسیدن به {c.city}", people.get(c.reported_by_id), source="checkpoint"))
    for b in backorders:
        events.append(_event(b.created_at, "warehouse", f"معوق: {products.get(b.product_id, '')}", None,
                             f"{fa_digits(str(b.quantity))} عدد", "/app/backorders", source="backorder"))
        if b.allocated_at:
            events.append(_event(b.allocated_at, "warehouse", f"تخصیص معوق: {products.get(b.product_id, '')}", None, None,
                                 "/app/backorders", source="backorder"))
    if role == "org_admin" and order.status == "delivered" and order.delivered_at and order.delivery_fee is not None:
        events.append(_event(order.delivered_at, "finance", "تسویه کرایه",
                             None, f"کرایه {_money(order.delivery_fee)} · سهم راننده {_money(order.driver_earning)}", "/app/finance", source="finance"))
    if role != "driver":
        for t in tickets:
            events.append(_event(t.created_at, "support", f"تیکت {t.code}: {t.subject}", t.requester_name, None,
                                 f"/app/tickets/{t.id}", source="ticket"))
        for r in ratings:
            events.append(_event(r.created_at, "support", "نظر مشتری", None, f"امتیاز {fa_digits(str(r.score))} از ۵", source="rating"))

    events = [e for e in events if e["at"] is not None]
    events.sort(key=lambda e: e["at"])
    blocker = _blocker(order, backorders, tickets)
    return {
        "order_id": order.id, "tracking_code": order.tracking_code, "stage": labels.get(order.status, order.status),
        "last_action": events[-1]["title"] if events else None, "last_action_at": events[-1]["at"] if events else None,
        "blocker": blocker, "events": events,
    }


def _blocker(order, backorders, tickets) -> str | None:
    open_backorders = [b for b in backorders if b.status in ("open", "allocated")]
    if open_backorders:
        return f"کمبود موجودی: {fa_digits(str(len(open_backorders)))} قلم معوق"
    if order.status == "failed":
        return "تحویل ناموفق؛ منتظر تصمیم"
    if order.status == "pending" and not order.vehicle_id:
        return "هنوز خودرو تعیین نشده"
    if order.status in ACTIVE_ORDER_STATUSES and order.delivery_window_end < _now():
        return "از بازه تحویل گذشته و هنوز تحویل نشده"
    if any(t.status == "open" for t in tickets):
        return "تیکت باز پشتیبانی"
    return None
