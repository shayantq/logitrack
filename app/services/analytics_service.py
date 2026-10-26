"""
داشبورد شاخص‌های کلیدی عملکرد انبار و ارسال (فصل ۲۸) — همه از داده‌های عملیاتی همان لحظه، بدون جدول جدا.

  • دقت موجودی — سطرهای انبارگردانی تأییدشده بازه که با عدد سیستم برابر بودند
  • نرخ تحقق سفارش — تحویل‌شده ÷ سفارش‌های بسته‌شده (تحویل، ناموفق، منقضی)؛ تحویل به‌موقع و تأمین کامل (بدون معوق) جدا
  • دقت برداشت — سطرهای برداشت بدون کسری ÷ همه سطرهای برداشت تمام‌شده
  • زمان رسید تا قفسه (Dock-to-Stock) — میانگین ساعت از اولین دریافت رسید تا پایان جانمایی
  • گردش موجودی — واحدهای خارج‌شده برای سفارش ÷ میانگین موجودی، سالانه‌شده؛ و روزهای پوشش
  • نرخ ضایعات — واحدهای امحا/ضایعات ÷ واحدهای واردشده
  • بهره‌وری ظرفیت — خانه‌های نگهداری/برداشت پر ÷ همه خانه‌های فعال (و حجم اشغال‌شده وقتی ظرفیت حجمی تعریف شده)
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.wms import ALLOCATABLE_LOCATION_TYPES, AVAILABLE, PENDING
from app.models import (
    Backorder, InboundReceipt, Inventory, Location, Order, PickLine, Product, PutawayTask, StockBalance, StockMovement,
    Stocktake, User,
)
from app.services import catalog_service, dispatch_service, location_service, permission_service, stocktake_service
from app.services.exceptions import ConflictError

NEUTRAL = ("transfer_out", "transfer_in", "status_out", "status_in", "move_out", "move_in")
INBOUND = ("initial", "receipt", "order_return")


def _range(date_from: date | None, date_to: date | None) -> tuple[date, date, datetime, datetime]:
    today = catalog_service.today_local()
    start, end = date_from or today - timedelta(days=29), date_to or today
    if end < start:
        raise ConflictError("تاریخ پایان باید بعد از تاریخ شروع باشد.")
    if (end - start).days > 1100:
        raise ConflictError("بازه حداکثر سه سال است.")
    lo = dispatch_service.local_to_utc(datetime.combine(start, time.min))
    hi = dispatch_service.local_to_utc(datetime.combine(end + timedelta(days=1), time.min))
    return start, end, lo, hi


def _pct(part: float, whole: float) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def _status(value: float | None, target: float, higher_better: bool = True) -> str:
    if value is None:
        return "none"
    if higher_better:
        return "good" if value >= target else "warn" if value >= target * 0.9 else "bad"
    return "good" if value <= target else "warn" if value <= target * 1.5 else "bad"


def _kpi(key, label, value, unit, target, hint, higher_better=True, detail=None) -> dict:
    return {"key": key, "label": label, "value": value, "unit": unit, "target": target, "hint": hint,
            "higher_better": higher_better, "status": _status(value, target, higher_better), "detail": detail}


def kpis(db: Session, user: User, *, date_from: date | None = None, date_to: date | None = None,
         warehouse_id: int | None = None) -> dict:
    permission_service.ensure(db, user, "analytics.view")
    warehouse_id = location_service.scope_warehouse(user, warehouse_id)
    start, end, lo, hi = _range(date_from, date_to)
    days = (end - start).days + 1
    db.flush()

    def wh(query, column):
        return query.filter(column == warehouse_id) if warehouse_id else query

    # ---- دقت موجودی ----
    acc = stocktake_service.accuracy_stats(db, lo, hi, warehouse_id)

    # ---- سفارش‌ها ----
    orders = wh(db.query(Order).filter(Order.created_at >= lo, Order.created_at < hi), Order.warehouse_id).all()
    closed = [o for o in orders if o.status in ("delivered", "failed", "expired")]
    delivered = [o for o in closed if o.status == "delivered"]
    on_time = [o for o in delivered if o.delivered_at and o.delivered_at <= o.delivery_window_end]
    backordered = {oid for (oid,) in db.query(Backorder.order_id).filter(Backorder.order_id.in_({o.id for o in orders} or {-1})).all()}

    # ---- برداشت ----
    pick_lines = wh(db.query(PickLine).filter(PickLine.status.in_(("picked", "short")), PickLine.picked_at >= lo,
                                              PickLine.picked_at < hi), PickLine.warehouse_id).all()
    exact_picks = sum(1 for p in pick_lines if p.status == "picked")

    # ---- رسید تا قفسه ----
    tasks = wh(db.query(PutawayTask.completed_at, InboundReceipt.received_at).join(
        InboundReceipt, InboundReceipt.id == PutawayTask.receipt_id).filter(
        PutawayTask.task_type == "putaway", PutawayTask.status == "done", PutawayTask.completed_at >= lo,
        PutawayTask.completed_at < hi, InboundReceipt.received_at.is_not(None)), PutawayTask.warehouse_id).all()
    hours = [(done - received).total_seconds() / 3600 for done, received in tasks if done and received and done >= received]
    dock_to_stock = round(sum(hours) / len(hours), 1) if hours else None

    # ---- گردش موجودی و ضایعات ----
    moves = wh(db.query(StockMovement.movement_type, func.sum(StockMovement.quantity_change)).filter(
        StockMovement.created_at >= lo, StockMovement.created_at < hi, StockMovement.movement_type.notin_(NEUTRAL)),
        StockMovement.warehouse_id).group_by(StockMovement.movement_type).all()
    by_type = {t: int(q or 0) for t, q in moves}
    issued = -by_type.get("order_out", 0)
    inbound = sum(by_type.get(t, 0) for t in INBOUND)
    scrapped = -by_type.get("damage", 0)
    on_hand_now = int(wh(db.query(func.coalesce(func.sum(Inventory.quantity), 0)), Inventory.warehouse_id).scalar() or 0)
    after = wh(db.query(func.coalesce(func.sum(StockMovement.quantity_change), 0)).filter(
        StockMovement.created_at >= hi, StockMovement.movement_type.notin_(NEUTRAL)), StockMovement.warehouse_id).scalar() or 0
    end_on_hand = on_hand_now - int(after)
    start_on_hand = end_on_hand - sum(by_type.values())
    average = max((start_on_hand + end_on_hand) / 2, 0)
    turnover = round(issued / average * 365 / days, 1) if average else None
    cover_days = round(end_on_hand / (issued / days), 0) if issued else None

    # ---- ظرفیت ----
    leaves = set(location_service.leaf_ids(db, warehouse_id)) if warehouse_id else None
    loc_query = db.query(Location).filter(Location.is_active.is_not(False), Location.location_type.in_(ALLOCATABLE_LOCATION_TYPES))
    if warehouse_id:
        loc_query = loc_query.filter(Location.warehouse_id == warehouse_id)
    locations = [loc for loc in loc_query.all() if leaves is None or loc.id in leaves]
    if leaves is None:
        parents = {p for (p,) in db.query(Location.parent_id).filter(Location.parent_id.is_not(None)).all()}
        locations = [loc for loc in locations if loc.id not in parents]
    occupied = {lid for (lid,) in db.query(StockBalance.location_id).filter(
        StockBalance.location_id.in_({loc.id for loc in locations} or {-1}), StockBalance.quantity > 0).distinct().all()}
    with_volume = [loc for loc in locations if loc.max_volume_m3]
    volume_pct = None
    if with_volume:
        groups = location_service.contents(db, [loc.id for loc in with_volume])
        products = {p.id: p for p in db.query(Product).filter(
            Product.id.in_({c.product_id for items in groups.values() for c in items} or {-1})).all()}
        used = sum(location_service.usage(groups.get(loc.id, []), products)["volume_m3"] for loc in with_volume)
        volume_pct = _pct(used, sum(loc.max_volume_m3 for loc in with_volume))

    items = [
        _kpi("inventory_accuracy", "دقت موجودی", acc["accuracy"], "%", 98.0,
             "سطرهای انبارگردانی بدون مغایرت ÷ همه سطرهای شمرده‌شده",
             detail=f"{acc['exact']} از {acc['lines']} سطر؛ دقت ارزشی {acc['value_accuracy'] if acc['value_accuracy'] is not None else '—'}٪"),
        _kpi("order_fulfillment", "نرخ تحقق سفارش", _pct(len(delivered), len(closed)), "%", 95.0,
             "تحویل‌شده ÷ سفارش‌های بسته‌شده (تحویل، ناموفق، منقضی)", detail=f"{len(delivered)} از {len(closed)} سفارش"),
        _kpi("on_time_delivery", "تحویل به‌موقع", _pct(len(on_time), len(delivered)), "%", 90.0,
             "تحویل تا پایان بازه زمانی وعده‌داده‌شده", detail=f"{len(on_time)} از {len(delivered)} تحویل"),
        _kpi("fill_rate", "تأمین کامل سفارش", _pct(len(orders) - len(backordered), len(orders)), "%", 95.0,
             "سفارش‌هایی که بدون سفارش معوق از موجودی تأمین شدند", detail=f"{len(backordered)} سفارش با معوق"),
        _kpi("picking_accuracy", "دقت برداشت", _pct(exact_picks, len(pick_lines)), "%", 99.0,
             "سطرهای برداشت بدون کسری ÷ همه سطرهای برداشت تمام‌شده", detail=f"{exact_picks} از {len(pick_lines)} سطر"),
        _kpi("dock_to_stock", "رسید تا قفسه", dock_to_stock, "ساعت", 24.0,
             "میانگین فاصله اولین دریافت رسید تا پایان جانمایی", higher_better=False, detail=f"{len(hours)} وظیفه جانمایی"),
        _kpi("stock_turnover", "گردش موجودی (سالانه)", turnover, "بار", 6.0,
             "واحدهای خارج‌شده برای سفارش ÷ میانگین موجودی، سالانه‌شده",
             detail=f"پوشش موجودی {int(cover_days) if cover_days is not None else '—'} روز"),
        _kpi("scrap_rate", "نرخ ضایعات", _pct(scrapped, inbound), "%", 1.0,
             "واحدهای امحا/ضایعات ÷ واحدهای واردشده", higher_better=False, detail=f"{scrapped} از {inbound} واحد"),
        _kpi("capacity_utilization", "بهره‌وری ظرفیت", _pct(len(occupied), len(locations)), "%", 85.0,
             "خانه‌های پر نگهداری/برداشت ÷ همه خانه‌های فعال",
             detail=f"{len(occupied)} از {len(locations)} خانه؛ حجم {volume_pct if volume_pct is not None else '—'}٪"),
    ]

    # ---- روند روزانه ----
    def daily(rows):
        result = defaultdict(int)
        for at, qty in rows:
            if at:
                result[dispatch_service.to_local(at).date()] += qty
        return result
    created = daily([(o.created_at, 1) for o in orders])
    delivered_days = daily([(o.delivered_at, 1) for o in delivered])
    move_rows = wh(db.query(StockMovement.created_at, StockMovement.movement_type, StockMovement.quantity_change).filter(
        StockMovement.created_at >= lo, StockMovement.created_at < hi,
        StockMovement.movement_type.in_(("order_out",) + INBOUND)), StockMovement.warehouse_id).all()
    shipped = daily([(at, -q) for at, t, q in move_rows if t == "order_out"])
    received = daily([(at, q) for at, t, q in move_rows if t in INBOUND])
    trend = [{"day": d, "orders": created.get(d, 0), "delivered": delivered_days.get(d, 0),
              "shipped_units": shipped.get(d, 0), "received_units": received.get(d, 0)}
             for d in (start + timedelta(days=i) for i in range(days))]

    # ---- وضعیت لحظه‌ای ----
    snapshot = {
        "open_orders": wh(db.query(Order).filter(Order.status.in_(("pending", "assigned", "picking_up", "picked_up", "in_transit"))),
                          Order.warehouse_id).count(),
        "backorder_units": int(wh(db.query(func.coalesce(func.sum(Backorder.quantity), 0)).filter(
            Backorder.status == "open"), Backorder.warehouse_id).scalar() or 0),
        "open_putaway": wh(db.query(PutawayTask).filter(PutawayTask.status.in_(("open", "partial"))), PutawayTask.warehouse_id).count(),
        "pending_inspection": int(wh(db.query(func.coalesce(func.sum(Inventory.quantity), 0)).filter(
            Inventory.stock_status == PENDING), Inventory.warehouse_id).scalar() or 0),
        "active_stocktakes": wh(db.query(Stocktake).filter(Stocktake.status.in_(("counting", "review"))), Stocktake.warehouse_id).count(),
        "low_stock": wh(db.query(Inventory).filter(Inventory.stock_status == AVAILABLE, Inventory.quantity <= Inventory.reorder_point),
                        Inventory.warehouse_id).count(),
        "on_hand_units": end_on_hand,
    }
    alerts = []
    for k in items:
        if k["status"] == "bad":
            alerts.append({"level": "danger", "text": f"«{k['label']}» ({k['value']}{'٪' if k['unit'] == '%' else ' ' + k['unit']}) "
                                                       f"از هدف {k['target']} دور است."})
    if snapshot["backorder_units"]:
        alerts.append({"level": "warning", "text": f"{snapshot['backorder_units']} واحد سفارش معوق منتظر موجودی است."})
    if snapshot["pending_inspection"]:
        alerts.append({"level": "info", "text": f"{snapshot['pending_inspection']} واحد کالا منتظر بازرسی کیفی است."})
    return {"date_from": start, "date_to": end, "warehouse_id": warehouse_id, "kpis": items, "trend": trend,
            "snapshot": snapshot, "alerts": alerts}
