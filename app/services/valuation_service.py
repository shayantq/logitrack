"""
ارزش‌گذاری موجودی و سلامت انبار (فصل ۱۷).

قاعده برداشت فیزیکی (FEFO/FIFO در picking_service و stock_ledger.pick_lines) و روش ارزش‌گذاری مالی دو تصمیم جدا هستند:
کالا ممکن است فیزیکی «اول‌منقضی» برداشت شود ولی بهای تمام‌شده‌اش با «میانگین موزون» حساب شود. این سرویس فقط
دفتر گردش را می‌خواند و هیچ موجودی‌ای را تغییر نمی‌دهد.

  • FIFO — هر ورود یک لایه بها؛ خروج از قدیمی‌ترین لایه مصرف می‌شود.
  • میانگین موزون متحرک — بعد از هر ورود، بهای واحد = ارزش کل ÷ تعداد.
  • استاندارد — آخرین بهای تمام‌شده ثبت‌شده (یا قیمت فروش به‌عنوان تخمین).
بهای هر ورود از جدول قیمت‌های تاریخ‌دار کالا (cost_price در همان روز) می‌آید؛ اگر بهای تمام‌شده‌ای ثبت نشده باشد
قیمت فروش همان روز جایگزین می‌شود و ردیف «تخمینی» علامت می‌خورد. ارزش‌گذاری در سطح سازمان است (انتقال بین انبارها،
تغییر وضعیت کیفی و جابه‌جایی محل اثر مالی ندارند) و کالای امانی (مالک دیگر) دارایی سازمان نیست و حساب نمی‌شود.
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import date, datetime, time, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.iran import fa_digits
from app.models import Product, StockBalance, StockMovement, StockMovementLine, User, Warehouse
from app.services import catalog_service, control_settings, dispatch_service, location_service, permission_service
from app.services.replenishment_service import cost_book

# گردش‌هایی که در سطح سازمان اثر مالی ندارند
NEUTRAL_TYPES = ("transfer_out", "transfer_in", "status_out", "status_in", "move_out", "move_in")
OUTBOUND_SALES = ("order_out",)
METHODS = tuple(control_settings.VALUATION_METHODS)


def _local_day(dt: datetime) -> date:
    return dispatch_service.to_local(dt).date() if dt else catalog_service.today_local()


def _owned_events(db: Session, product_ids: list[int] | None = None) -> dict[int, list[tuple[datetime, str, int]]]:
    """گردش‌های مالکیت خود سازمان (ردیف‌های ریز بدون مالک) به ترتیب زمان: {کالا: [(زمان، نوع، مقدار)]}."""
    db.flush()
    query = db.query(StockMovement.product_id, StockMovement.id, StockMovement.created_at, StockMovement.movement_type,
                     func.sum(StockMovementLine.quantity_change)).join(
        StockMovementLine, StockMovementLine.movement_id == StockMovement.id).filter(
        StockMovementLine.owner_id.is_(None), StockMovement.movement_type.notin_(NEUTRAL_TYPES))
    if product_ids is not None:
        query = query.filter(StockMovement.product_id.in_(product_ids or [-1]))
    rows = query.group_by(StockMovement.product_id, StockMovement.id, StockMovement.created_at, StockMovement.movement_type) \
        .order_by(StockMovement.created_at, StockMovement.id).all()
    events: dict[int, list] = defaultdict(list)
    for product_id, _, created_at, movement_type, qty in rows:
        if qty:
            events[product_id].append((created_at, movement_type, int(qty)))
    return events


def _run(events: list[tuple[datetime, str, int]], unit_cost, period: tuple[datetime, datetime] | None = None) -> dict:
    """هر دو روش را روی گردش‌های یک کالا اجرا می‌کند؛ بهای تمام‌شده خروجی‌های بازه (period) را هم برمی‌گرداند."""
    layers: deque = deque()                 # FIFO: [مقدار، بها]
    avg_qty, avg_value = 0, 0.0
    cogs = {"fifo": 0.0, "weighted_average": 0.0}
    issued_qty = 0
    for at, movement_type, qty in events:
        in_period = period is None or period[0] <= at < period[1]
        if qty > 0:
            cost = unit_cost(at)
            layers.append([qty, cost])
            avg_qty, avg_value = avg_qty + qty, avg_value + qty * cost
            continue
        out = -qty
        # FIFO
        remaining, fifo_cost = out, 0.0
        while remaining and layers:
            take = min(layers[0][0], remaining)
            fifo_cost += take * layers[0][1]
            layers[0][0] -= take
            remaining -= take
            if layers[0][0] == 0:
                layers.popleft()
        # میانگین موزون
        avg_unit = avg_value / avg_qty if avg_qty > 0 else 0.0
        take = min(out, max(avg_qty, 0))
        avg_qty -= take
        avg_value = max(0.0, avg_value - take * avg_unit) if avg_qty else 0.0
        if in_period and movement_type in OUTBOUND_SALES:
            cogs["fifo"] += fifo_cost
            cogs["weighted_average"] += out * avg_unit
            issued_qty += out
    fifo_qty = sum(q for q, _ in layers)
    return {"qty": fifo_qty, "fifo": sum(q * c for q, c in layers), "weighted_average": avg_value if avg_qty > 0 else 0.0,
            "avg_qty": avg_qty, "cogs": cogs, "issued_qty": issued_qty}


def _owned_on_hand(db: Session, warehouse_id: int | None = None) -> dict[int, int]:
    db.flush()
    query = db.query(StockBalance.product_id, func.sum(StockBalance.quantity)).filter(StockBalance.owner_id.is_(None))
    if warehouse_id:
        query = query.filter(StockBalance.warehouse_id == warehouse_id)
    return {pid: int(q or 0) for pid, q in query.group_by(StockBalance.product_id).all()}


def _bounds(date_from: date | None, date_to: date | None) -> tuple[date, date, datetime, datetime]:
    today = catalog_service.today_local()
    start = date_from or (today - timedelta(days=30))
    end = date_to or today
    lo = dispatch_service.local_to_utc(datetime.combine(start, time.min))
    hi = dispatch_service.local_to_utc(datetime.combine(end + timedelta(days=1), time.min))
    return start, end, lo, hi


def valuation(db: Session, user: User, *, warehouse_id: int | None = None, date_from: date | None = None,
              date_to: date | None = None, compute: bool = True) -> dict:
    permission_service.ensure(db, user, "valuation.view")
    warehouse_id = location_service.scope_warehouse(user, warehouse_id)
    settings = control_settings.of(db, user.organization_id)
    method = settings["valuation_method"]
    start, end, lo, hi = _bounds(date_from, date_to)
    org_on_hand = _owned_on_hand(db)
    scoped_on_hand = _owned_on_hand(db, warehouse_id) if warehouse_id else org_on_hand
    product_ids = sorted(set(org_on_hand) | set(scoped_on_hand))
    products = {p.id: p for p in db.query(Product).filter(Product.id.in_(product_ids or [-1])).all()}
    book = cost_book(db, product_ids, 0.0)
    events = _owned_events(db, product_ids)
    today = catalog_service.today_local()
    rows, totals = [], {m: 0.0 for m in METHODS}
    cogs_total = {"fifo": 0.0, "weighted_average": 0.0, "standard": 0.0}
    for pid in product_ids:
        product = products.get(pid)
        if product is None:
            continue
        result = _run(events.get(pid, []), lambda at, pid=pid: book.at(pid, _local_day(at)), (lo, hi))
        org_qty = org_on_hand.get(pid, 0)
        qty = scoped_on_hand.get(pid, 0)
        standard_unit = book.at(pid, today)
        units = {
            "fifo": result["fifo"] / result["qty"] if result["qty"] else standard_unit,
            "weighted_average": result["weighted_average"] / result["avg_qty"] if result["avg_qty"] else standard_unit,
            "standard": standard_unit,
        }
        # ارزش در سطح سازمان حساب می‌شود؛ برای یک انبار به نسبت مقدار همان انبار
        values = {m: round(units[m] * qty) for m in METHODS}
        for m in METHODS:
            totals[m] += values[m]
        cogs_total["fifo"] += result["cogs"]["fifo"]
        cogs_total["weighted_average"] += result["cogs"]["weighted_average"]
        cogs_total["standard"] += result["issued_qty"] * standard_unit
        if qty <= 0 and not result["issued_qty"]:
            continue
        rows.append({
            "product_id": pid, "product_name": product.name, "sku": product.sku, "category": product.category,
            "abc_class": product.abc_class, "quantity": qty, "org_quantity": org_qty,
            "unit_cost": {m: round(units[m]) for m in METHODS}, "value": values,
            "selected_value": values[method], "issued_qty": result["issued_qty"],
            "estimated": book.estimated(pid), "reconciled": result["qty"] == org_qty,
        })
    rows.sort(key=lambda r: -r["selected_value"])
    return {
        "method": method, "method_label": control_settings.VALUATION_METHODS[method],
        "methods": [{"code": k, "label": v} for k, v in control_settings.VALUATION_METHODS.items()],
        "date_from": start, "date_to": end, "warehouse_id": warehouse_id,
        "totals": {m: round(v) for m, v in totals.items()}, "cogs": {m: round(v) for m, v in cogs_total.items()},
        "selected_total": round(totals[method]), "estimated_items": sum(1 for r in rows if r["estimated"]),
        "items": rows,
    }


def health(db: Session, user: User, *, warehouse_id: int | None = None) -> dict:
    """کالای کم‌گردش، راکد و بی‌فروش + اقلام نزدیک به انقضا و منقضی، با ارزش (میانگین موزون)."""
    permission_service.ensure(db, user, "valuation.view")
    warehouse_id = location_service.scope_warehouse(user, warehouse_id)
    settings = control_settings.of(db, user.organization_id)
    today = catalog_service.today_local()
    on_hand = _owned_on_hand(db, warehouse_id)
    product_ids = [pid for pid, q in on_hand.items() if q > 0]
    products = {p.id: p for p in db.query(Product).filter(Product.id.in_(product_ids or [-1])).all()}
    book = cost_book(db, product_ids, 0.0)
    move_query = db.query(StockMovement.product_id, StockMovement.movement_type, func.max(StockMovement.created_at),
                          func.min(StockMovement.created_at)).filter(StockMovement.product_id.in_(product_ids or [-1]))
    if warehouse_id:
        move_query = move_query.filter(StockMovement.warehouse_id == warehouse_id)
    last_out, first_in = {}, {}
    for pid, mtype, last_at, first_at in move_query.group_by(StockMovement.product_id, StockMovement.movement_type).all():
        if mtype in OUTBOUND_SALES:
            last_out[pid] = max(last_out.get(pid, last_at), last_at)
        if mtype in ("initial", "receipt"):
            first_in[pid] = min(first_in.get(pid, first_at), first_at)
    items, buckets = [], {"active": [0, 0.0], "slow": [0, 0.0], "dead": [0, 0.0], "no_sales": [0, 0.0]}
    for pid in product_ids:
        product = products.get(pid)
        if product is None:
            continue
        qty = on_hand[pid]
        value = round(qty * book.at(pid, today))
        sold = last_out.get(pid)
        since = sold or first_in.get(pid)
        idle = (today - _local_day(since)).days if since else None
        if sold is None:
            status = "no_sales" if idle is None or idle >= settings["slow_days"] else "active"
        elif idle >= settings["dead_days"]:
            status = "dead"
        elif idle >= settings["slow_days"]:
            status = "slow"
        else:
            status = "active"
        buckets[status][0] += 1
        buckets[status][1] += value
        if status != "active":
            items.append({"product_id": pid, "product_name": product.name, "sku": product.sku, "abc_class": product.abc_class,
                          "quantity": qty, "value": value, "last_sale_at": sold, "idle_days": idle, "status": status})
    items.sort(key=lambda r: (-(r["idle_days"] or 10_000), -r["value"]))

    horizon = today + timedelta(days=settings["expiry_warning_days"])
    exp_query = db.query(StockBalance).filter(StockBalance.quantity > 0, StockBalance.expiry_date.is_not(None),
                                              StockBalance.expiry_date <= horizon, StockBalance.owner_id.is_(None))
    if warehouse_id:
        exp_query = exp_query.filter(StockBalance.warehouse_id == warehouse_id)
    balances = exp_query.order_by(StockBalance.expiry_date).limit(500).all()
    names = {p.id: p for p in db.query(Product).filter(Product.id.in_({b.product_id for b in balances} or {-1})).all()}
    whs = {w.id: w.name for w in db.query(Warehouse).all()}
    from app.models import Location
    codes = dict(db.query(Location.id, Location.code).filter(Location.id.in_({b.location_id for b in balances if b.location_id} or {-1})).all())
    expiring = []
    for b in balances:
        days_left = (b.expiry_date - today).days
        expiring.append({"product_id": b.product_id, "product_name": names[b.product_id].name if b.product_id in names else "",
                         "sku": names[b.product_id].sku if b.product_id in names else None,
                         "warehouse_name": whs.get(b.warehouse_id, ""), "location_code": codes.get(b.location_id),
                         "lot_number": b.lot_number, "expiry_date": b.expiry_date, "days_left": days_left,
                         "stock_status": b.stock_status, "quantity": b.quantity,
                         "value": round(b.quantity * book.at(b.product_id, today)),
                         "expired": days_left < 0})
    return {
        "settings": {k: settings[k] for k in ("slow_days", "dead_days", "expiry_warning_days")},
        "buckets": [{"status": k, "count": v[0], "value": round(v[1])} for k, v in buckets.items()],
        "items": items, "expiring": expiring,
        "expired_value": sum(e["value"] for e in expiring if e["expired"]),
        "expiring_value": sum(e["value"] for e in expiring if not e["expired"]),
        "summary": f"{fa_digits(str(len(items)))} کالای کم‌گردش/راکد و {fa_digits(str(len(expiring)))} ردیف نزدیک به انقضا",
    }
