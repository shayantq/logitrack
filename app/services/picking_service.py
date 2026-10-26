"""
برداشت (پیکینگ) سفارش‌ها — فصل ۱۴

روش‌ها:
  single  تک‌سفارشی: یک سفارش، یک فهرست.
  batch   دسته‌ای: چند سفارش انتخابی در یک فهرست؛ سطرهای هم‌محل پشت سر هم.
  wave    موجی: همه سفارش‌های آماده یک انبار با یک روز تحویل.
  zone    منطقه‌ای: فقط سطرهایی که محلشان زیر یک منطقه است (هر منطقه فهرست خودش را دارد).

برنامه‌ریزی: برای هر قلم سفارش، از موجودی «قابل تخصیص» (تأییدشده، محل نگهداری/برداشت یا بدون محل، منقضی‌نشده،
مال سازمان) به ترتیب FEFO و سپس مسیر کد محل برداشت می‌شود؛ مقداری که سطرهای باز دیگر برداشته‌اند کم می‌شود.
اجرا: اسکن محل (یا کد انبار برای بدون محل)، کالا و بچ؛ کالا به محل آماده‌سازی فهرست منتقل می‌شود (سند PK) و
رزرو سفارش دست نمی‌خورد تا حواله خروج دقیقاً از همان محل/بچ برداشت‌شده صادر شود.
کمبود در محل: سطر «کسری» می‌شود و باقی‌مانده از محل‌های دیگر دوباره برنامه‌ریزی می‌شود.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.core.wms import (
    ALLOCATABLE_LOCATION_TYPES, AVAILABLE, FULFILLMENT_LABELS, PICK_LIST_STATUS_LABELS, PICK_STRATEGY_LABELS,
)
from app.models import (
    Location, Order, PickLine, PickList, Product, StockBalance, StockReservation, User, Warehouse,
)
from app.services import (
    catalog_service, dispatch_service, event_bus, location_service, stock_document_service, stock_ledger,
)
from app.services.exceptions import ConflictError, NotFoundError
from app.services.putaway_service import ScanMismatchError, matches_product

PICKABLE_ORDER_STATUSES = ("pending", "assigned", "picking_up")
STAGING_TYPES = ("staging", "shipping")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _local_day(value: datetime) -> date:
    return dispatch_service.to_local(dispatch_service.to_utc_naive(value)).date()


# ---------------------------------------------------------------------------
# برنامه‌ریزی
# ---------------------------------------------------------------------------
def zone_leaves(db: Session, zone_id: int) -> set[int]:
    """همه محل‌های زیرمجموعه یک منطقه (خود منطقه هم اگر انتهایی باشد)."""
    children = defaultdict(list)
    zone = db.get(Location, zone_id)
    for loc_id, parent_id in db.query(Location.id, Location.parent_id).filter(Location.warehouse_id == zone.warehouse_id).all():
        children[parent_id].append(loc_id)
    result, stack = set(), [zone_id]
    while stack:
        current = stack.pop()
        result.add(current)
        stack.extend(children.get(current, []))
    return result


def _planned(db: Session, warehouse_id: int, product_id: int) -> dict[tuple, int]:
    """مقداری از هر محل/بچ که سطرهای برداشتِ باز (هنوز برداشت‌نشده) برای خودشان نگه داشته‌اند."""
    rows = db.query(PickLine.location_id, PickLine.lot_number, PickLine.expiry_date,
                    func.sum(PickLine.quantity - PickLine.picked_quantity)).filter(
        PickLine.warehouse_id == warehouse_id, PickLine.product_id == product_id, PickLine.status == "open",
    ).group_by(PickLine.location_id, PickLine.lot_number, PickLine.expiry_date).all()
    return {(loc, lot, exp): int(q or 0) for loc, lot, exp, q in rows}


def _plan(db: Session, warehouse_id: int, product_id: int, quantity: int, *, zone: set[int] | None = None,
          exclude_location: int | None = None) -> list[tuple[int | None, str | None, date | None, int, str]]:
    """[(محل، بچ، انقضا، مقدار، کد مسیر)] به ترتیب FEFO و مسیر."""
    db.flush()
    today = catalog_service.today_local()
    query = db.query(StockBalance, Location).outerjoin(Location, StockBalance.location_id == Location.id).filter(
        StockBalance.warehouse_id == warehouse_id, StockBalance.product_id == product_id,
        StockBalance.stock_status == AVAILABLE, StockBalance.quantity > 0, StockBalance.owner_id.is_(None),
        (StockBalance.expiry_date.is_(None)) | (StockBalance.expiry_date >= today),
    )
    taken = _planned(db, warehouse_id, product_id)
    groups: dict[tuple, int] = defaultdict(int)
    codes: dict[int | None, str] = {}
    for balance, location in query.all():
        if location is not None and not location_service.is_allocatable(location):
            continue
        if location is not None and location.location_type not in ALLOCATABLE_LOCATION_TYPES:
            continue
        if zone is not None and (location is None or location.id not in zone):
            continue
        if exclude_location is not None and balance.location_id == exclude_location:
            continue
        groups[(balance.location_id, balance.lot_number, balance.expiry_date)] += balance.quantity
        codes[balance.location_id] = location.code if location else ""
    plan, remaining = [], quantity
    # FEFO، سپس محل‌های مشخص به ترتیب مسیر و موجودی «بدون محل» در آخر
    for key in sorted(groups, key=lambda k: (k[2] or date.max, k[0] is None, codes[k[0]], k[1] or "")):
        free = groups[key] - taken.get(key, 0)
        if free <= 0 or remaining <= 0:
            continue
        take = min(free, remaining)
        plan.append((key[0], key[1], key[2], take, codes[key[0]]))
        remaining -= take
    return plan


def _needed(db: Session, order: Order) -> dict[int, int]:
    """مقدار هر کالای سفارش که هنوز سطر برداشت ندارد."""
    planned = _planned_for_order(db, order.id)
    needed = {}
    for item in order.items:
        if item.product_id is None:
            continue
        rest = item.quantity - planned.get(item.product_id, 0)
        if rest > 0:
            needed[item.product_id] = needed.get(item.product_id, 0) + rest
    return needed


def _planned_for_order(db: Session, order_id: int) -> dict[int, int]:
    """سطرهای باز و برداشت‌شده کامل حساب می‌شوند؛ سطر کسری فقط به اندازه برداشت‌شده‌اش."""
    result: dict[int, int] = defaultdict(int)
    for line in db.query(PickLine).filter(PickLine.order_id == order_id, PickLine.status != "canceled").all():
        result[line.product_id] += line.picked_quantity if line.status == "short" else line.quantity
    return result


def _eligible_orders(db: Session, warehouse_id: int, order_ids=None, wave_date: date | None = None) -> list[Order]:
    query = db.query(Order).options(selectinload(Order.items)).filter(
        Order.warehouse_id == warehouse_id, Order.stock_state == "reserved", Order.status.in_(PICKABLE_ORDER_STATUSES),
        Order.fulfillment_state.in_(("open", "picking")),
    )
    if order_ids is not None:
        query = query.filter(Order.id.in_(list(order_ids) or [-1]))
    orders = query.order_by(Order.priority.desc(), Order.delivery_window_start, Order.id).with_for_update().all()
    if wave_date is not None:
        orders = [o for o in orders if _local_day(o.delivery_window_start) == wave_date]
    return orders


def candidates(db: Session, user: User, warehouse_id: int | None) -> list[dict]:
    warehouse_id = location_service.scope_warehouse(user, warehouse_id)
    if warehouse_id is None:
        raise ConflictError("انبار را انتخاب کنید.")
    orders = db.query(Order).options(selectinload(Order.items)).filter(
        Order.warehouse_id == warehouse_id, Order.stock_state == "reserved", Order.status.in_(PICKABLE_ORDER_STATUSES),
        Order.fulfillment_state.in_(("open", "picking")),
    ).order_by(Order.priority.desc(), Order.delivery_window_start, Order.id).limit(300).all()
    result = []
    for o in orders:
        needed = _needed(db, o)
        if not needed:
            continue
        result.append({"id": o.id, "tracking_code": o.tracking_code, "status": o.status, "priority": o.priority,
                       "delivery_day": _local_day(o.delivery_window_start), "recipient_name": o.recipient_name,
                       "destination_city": o.destination_city, "fulfillment_state": o.fulfillment_state,
                       "items": sum(needed.values())})
    return result


def create_pick_list(db: Session, user: User, data) -> dict:
    warehouse_id = location_service.scope_warehouse(user, data.warehouse_id)
    if warehouse_id is None:
        raise ConflictError("انبار را انتخاب کنید.")
    try:
        if db.get(Warehouse, warehouse_id) is None:
            raise NotFoundError("انبار یافت نشد.")
        zone = None
        if data.strategy == "zone":
            if data.zone_location_id is None:
                raise ConflictError("برای برداشت منطقه‌ای، منطقه را انتخاب کنید.")
            location_service.resolve(db, warehouse_id, data.zone_location_id)
            zone = zone_leaves(db, data.zone_location_id)
        staging = None
        if data.staging_location_id is not None:
            staging = location_service.resolve(db, warehouse_id, data.staging_location_id)
            if staging.location_type not in STAGING_TYPES:
                raise ConflictError("محل تحویل برداشت باید از نوع «آماده‌سازی» یا «بارگیری» باشد.")
        if data.strategy == "single" and len(data.order_ids or []) != 1:
            raise ConflictError("برداشت تک‌سفارشی دقیقاً یک سفارش می‌خواهد.")
        if data.strategy in ("single", "batch") and not data.order_ids:
            raise ConflictError("سفارش‌ها را انتخاب کنید.")
        if data.strategy == "wave" and data.wave_date is None:
            raise ConflictError("برای برداشت موجی، روز تحویل را انتخاب کنید.")
        orders = _eligible_orders(db, warehouse_id, data.order_ids if data.strategy != "wave" else None,
                                  data.wave_date if data.strategy == "wave" else None)
        if data.strategy in ("single", "batch") and len(orders) != len(set(data.order_ids)):
            raise ConflictError("بعضی سفارش‌ها قابل برداشت نیستند (رزرو ندارند، ارسال شده‌اند یا از انبار دیگری‌اند).")

        pick_list = PickList(code=stock_ledger.new_code(db, PickList, "PL"), strategy=data.strategy, status="open",
                             warehouse_id=warehouse_id, zone_location_id=data.zone_location_id if zone else None,
                             staging_location_id=staging.id if staging else None,
                             wave_date=data.wave_date if data.strategy == "wave" else None,
                             created_at=_now(), created_by_id=user.id)
        db.add(pick_list)
        db.flush()
        lines, skipped = [], []
        for order in orders:
            needed = _needed(db, order)
            plans = {pid: _plan(db, warehouse_id, pid, qty, zone=zone) for pid, qty in needed.items()}
            short = {pid: needed[pid] - sum(p[3] for p in plan) for pid, plan in plans.items()}
            if zone is None and any(short.values()):
                # بدون منطقه: سفارشی که کامل قابل برداشت نیست وارد فهرست نمی‌شود (رزروش محفوظ می‌ماند)
                skipped.append(order.tracking_code)
                continue
            added = False
            for pid, plan in plans.items():
                for location_id, lot, expiry, qty, code in plan:
                    line = PickLine(pick_list_id=pick_list.id, order_id=order.id, product_id=pid, warehouse_id=warehouse_id,
                                    location_id=location_id, lot_number=lot, expiry_date=expiry, quantity=qty,
                                    picked_quantity=0, status="open")
                    line._route = code
                    db.add(line)
                    db.flush()
                    lines.append(line)
                    added = True
            if added:
                order.fulfillment_state = "picking"
        if not lines:
            raise ConflictError("هیچ سطری برای برداشت نیست؛ " + (
                f"موجودی قابل تخصیص سفارش‌های {', '.join(skipped)} در محل‌های برداشت کافی نیست." if skipped
                else "سفارش آماده‌ای (یا موجودی در این منطقه) پیدا نشد."))
        # ترتیب مسیر: کد محل، سپس کالا (در دسته‌ای/موجی سطرهای هم‌محل کنار هم)
        for sequence, line in enumerate(sorted(lines, key=lambda ln: (ln._route, ln.product_id, ln.order_id)), start=1):
            line.sequence = sequence
        event_bus.emit(db, "pick.list.created", "pick_list", pick_list.id,
                       {"code": pick_list.code, "strategy": pick_list.strategy, "orders": len({ln.order_id for ln in lines}),
                        "lines": len(lines), "skipped": skipped}, organization_id=pick_list.organization_id, actor=user)
        db.commit()
    except Exception:
        db.rollback()
        raise
    result = get_pick_list(db, user, pick_list.id)
    result["skipped_orders"] = skipped
    return result


# ---------------------------------------------------------------------------
# اجرا
# ---------------------------------------------------------------------------
def _refresh_order(db: Session, order_id: int) -> None:
    order = db.get(Order, order_id)
    if order is None or order.fulfillment_state not in ("picking", "picked"):
        return
    db.flush()
    lines = db.query(PickLine).filter(PickLine.order_id == order_id, PickLine.status != "canceled").all()
    picked: dict[int, int] = defaultdict(int)
    for line in lines:
        picked[line.product_id] += line.picked_quantity
    complete = all(picked.get(item.product_id, 0) >= item.quantity for item in order.items if item.product_id)
    order.fulfillment_state = "picked" if complete else "picking"


def _refresh_list(pick_list: PickList) -> None:
    if all(line.status != "open" for line in pick_list.lines):
        pick_list.status, pick_list.completed_at = "picked", _now()
    elif any(line.picked_quantity or line.status != "open" for line in pick_list.lines):
        pick_list.status = "in_progress"
        pick_list.started_at = pick_list.started_at or _now()


def _lock_line(db: Session, user: User, line_id: int) -> PickLine:
    line = db.query(PickLine).filter(PickLine.id == line_id).with_for_update().first()
    if line is None:
        raise NotFoundError("سطر برداشت یافت نشد.")
    location_service.scope_warehouse(user, line.warehouse_id)
    if line.status != "open":
        raise ConflictError("این سطر قبلاً بسته شده است.")
    return line


def pick(db: Session, user: User, line_id: int, data, idempotency_key: str | None = None) -> dict:
    def create(key, digest):
        try:
            line = _lock_line(db, user, line_id)
            product = db.get(Product, line.product_id)
            remaining = line.quantity - line.picked_quantity
            if data.quantity > remaining:
                raise ConflictError(f"باقی‌مانده این سطر {remaining} عدد است.")
            if not matches_product(db, product, data.product_scan):
                raise ScanMismatchError(f"کالای اسکن‌شده «{data.product_scan}» با کالای سطر ({product.sku}) یکی نیست.")
            if line.location_id is not None:
                source = location_service.find_by_scan(db, line.warehouse_id, data.source_scan)
                if source is None or source.id != line.location_id:
                    raise ScanMismatchError(f"محل اسکن‌شده «{data.source_scan}» محل این سطر ({db.get(Location, line.location_id).code}) نیست.")
            else:
                warehouse = db.get(Warehouse, line.warehouse_id)
                if (data.source_scan or "").strip().upper() != (warehouse.code or "").upper():
                    raise ScanMismatchError(f"کالای این سطر بدون محل است؛ کد انبار ({warehouse.code}) را اسکن کنید.")
            if line.lot_number and (data.lot_scan or "").strip().upper() != line.lot_number.upper():
                raise ScanMismatchError(f"بچ اسکن‌شده با بچ سطر ({line.lot_number}) یکی نیست؛ FEFO این بچ را تعیین کرده است.")
            pick_list = db.get(PickList, line.pick_list_id)
            document = None
            line.picked_quantity += data.quantity
            line.picked_at, line.picked_by_id = _now(), user.id
            if pick_list.staging_location_id is not None:
                line.staged_location_id = pick_list.staging_location_id
                db.flush()
                inventory = stock_ledger.lock_bucket(db, line.product_id, line.warehouse_id, AVAILABLE, create=False)
                document = stock_ledger.new_document(
                    db, "pick", organization_id=line.organization_id, user=user, warehouse_id=line.warehouse_id,
                    reference_type="pick_list", reference_id=pick_list.id, note=f"برداشت {pick_list.code}",
                    idempotency_key=key, request_hash=digest)
                stock_ledger.move(db, inventory, data.quantity, document=document,
                                  match={"location_id": line.location_id, "lot_number": line.lot_number,
                                         "expiry_date": line.expiry_date, "owner_id": None},
                                  overrides={"location_id": pick_list.staging_location_id}, user=user,
                                  reason=f"برداشت {pick_list.code}", reference_type="order", reference_id=line.order_id)
            if line.picked_quantity == line.quantity:
                line.status = "picked"
            _refresh_list(pick_list)
            _refresh_order(db, line.order_id)
            event_bus.emit(db, "pick.line.picked", "pick_list", pick_list.id,
                           {"line_id": line.id, "order_id": line.order_id, "product_id": line.product_id,
                            "location_id": line.location_id, "quantity": data.quantity}, organization_id=line.organization_id,
                           actor=user)
            if pick_list.status == "picked":
                event_bus.emit(db, "pick.list.completed", "pick_list", pick_list.id, {"code": pick_list.code},
                               organization_id=pick_list.organization_id, actor=user)
            if line.location_id is not None:
                from app.services import replenishment_rule_service
                replenishment_rule_service.check(db, user, [line.location_id])
            db.commit()
            return document or line
        except Exception:
            db.rollback()
            raise

    if idempotency_key:
        from app.models import StockDocument
        stock_document_service.idempotent(db, StockDocument, idempotency_key, f"pick:{line_id}", data.model_dump(mode="json"),
                                          create)
    else:
        create(None, None)
    line = db.get(PickLine, line_id)
    return get_pick_list(db, user, line.pick_list_id)


def short(db: Session, user: User, line_id: int, data) -> dict:
    """کمبود در محل: سطر بسته و باقی‌مانده از محل‌های دیگر دوباره برنامه‌ریزی می‌شود (اختلاف موجودی با انبارگردانی)."""
    try:
        line = _lock_line(db, user, line_id)
        pick_list = db.get(PickList, line.pick_list_id)
        missing = line.quantity - line.picked_quantity
        line.status, line.short_reason = "short", data.reason[:300]
        zone = zone_leaves(db, pick_list.zone_location_id) if pick_list.zone_location_id else None
        plan = _plan(db, line.warehouse_id, line.product_id, missing, zone=zone, exclude_location=line.location_id)
        added = 0
        for location_id, lot, expiry, qty, _code in plan:
            db.add(PickLine(pick_list_id=pick_list.id, order_id=line.order_id, product_id=line.product_id,
                            warehouse_id=line.warehouse_id, location_id=location_id, lot_number=lot, expiry_date=expiry,
                            quantity=qty, picked_quantity=0, status="open", sequence=line.sequence))
            added += qty
        db.flush()
        _refresh_list(pick_list)
        _refresh_order(db, line.order_id)
        event_bus.emit(db, "pick.line.short", "pick_list", pick_list.id,
                       {"line_id": line.id, "order_id": line.order_id, "product_id": line.product_id, "missing": missing,
                        "replanned": added, "reason": data.reason}, organization_id=line.organization_id, actor=user)
        db.commit()
    except Exception:
        db.rollback()
        raise
    result = get_pick_list(db, user, pick_list.id)
    result["replanned"] = added
    result["unresolved"] = missing - added
    return result


def cancel_list(db: Session, user: User, pick_list_id: int, reason: str) -> dict:
    try:
        pick_list = db.query(PickList).filter(PickList.id == pick_list_id).with_for_update().first()
        if pick_list is None:
            raise NotFoundError("فهرست برداشت یافت نشد.")
        location_service.scope_warehouse(user, pick_list.warehouse_id)
        if pick_list.status in ("picked", "canceled"):
            raise ConflictError("این فهرست بسته شده است.")
        if any(line.picked_quantity for line in pick_list.lines):
            raise ConflictError("بخشی از این فهرست برداشت شده است؛ سطرهای باقی‌مانده را «کسری» بزنید یا تکمیل کنید.")
        for line in pick_list.lines:
            line.status = "canceled"
        pick_list.status, pick_list.completed_at = "canceled", _now()
        db.flush()
        for order_id in {line.order_id for line in pick_list.lines}:
            order = db.get(Order, order_id)
            if order is not None and not db.query(PickLine.id).filter(PickLine.order_id == order_id,
                                                                       PickLine.status != "canceled").first():
                order.fulfillment_state = "open"
        event_bus.emit(db, "pick.list.completed", "pick_list", pick_list.id, {"code": pick_list.code, "canceled": reason},
                       organization_id=pick_list.organization_id, actor=user)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_pick_list(db, user, pick_list_id)


# ---------------------------------------------------------------------------
# اتصال به حواله خروج سفارش
# ---------------------------------------------------------------------------
def issue_lines(db: Session, order: Order, reservations: list[StockReservation]) -> dict[int, list]:
    """
    حواله خروج سفارش پیکینگ‌شده دقیقاً از همان محل/بچ برداشت‌شده: {شناسه رزرو: ردیف‌های ریز}.
    سفارش بدون پیکینگ: {} (برداشت خودکار FEFO). سفارشی که برداشتش ناتمام است خارج نمی‌شود.
    """
    lines = db.query(PickLine).filter(PickLine.order_id == order.id, PickLine.status != "canceled",
                                      PickLine.issued.is_(False)).all()
    if not lines:
        return {}
    if any(line.status == "open" for line in lines) or order.fulfillment_state not in ("picked", "packed"):
        raise ConflictError(f"برداشت سفارش {order.tracking_code} کامل نشده است؛ ابتدا همه سطرهای پیکینگ را تمام کنید.")
    per_product: dict[int, list] = defaultdict(list)
    for line in lines:
        if not line.picked_quantity:
            continue
        inventory = stock_ledger.lock_bucket(db, line.product_id, line.warehouse_id, AVAILABLE, create=False)
        where = line.staged_location_id if line.staged_location_id is not None else line.location_id
        per_product[line.product_id].extend(stock_ledger.pick_lines(
            db, inventory, line.picked_quantity,
            match={"location_id": where, "lot_number": line.lot_number, "expiry_date": line.expiry_date, "owner_id": None}))
    result: dict[int, list] = {}
    for reservation in reservations:
        pool, need, take = per_product.get(reservation.product_id, []), reservation.quantity, []
        while need > 0 and pool:
            key, qty = pool[0]
            used = min(qty, need)
            take.append((key, used))
            need -= used
            if used == qty:
                pool.pop(0)
            else:
                pool[0] = (key, qty - used)
        if need > 0:
            raise ConflictError(f"مقدار برداشت‌شده «{reservation.product.name}» از رزرو سفارش کمتر است.")
        merged: dict = {}
        for key, qty in take:
            merged[key] = merged.get(key, 0) + qty
        result[reservation.id] = list(merged.items())
    return result


def mark_issued(db: Session, order: Order) -> None:
    for line in db.query(PickLine).filter(PickLine.order_id == order.id, PickLine.issued.is_(False)).all():
        line.issued = True


def cancel_for_order(db: Session, user: User | None, order: Order) -> None:
    """لغو سفارش پیش از خروج: سطرهای باز لغو و کالای منتقل‌شده به آماده‌سازی با وظیفه جانمایی به قفسه برمی‌گردد."""
    from app.services import putaway_service
    staged: dict[tuple, int] = defaultdict(int)
    for line in db.query(PickLine).filter(PickLine.order_id == order.id, PickLine.issued.is_(False)).all():
        if line.status == "open":
            line.status = "canceled"
        if line.staged_location_id is not None and line.picked_quantity:
            staged[(line.product_id, line.warehouse_id, line.staged_location_id, line.lot_number, line.expiry_date)] += line.picked_quantity
        line.issued = True
    db.flush()
    for (product_id, warehouse_id, location_id, lot, expiry), quantity in staged.items():
        putaway_service.create_internal(db, user, warehouse_id=warehouse_id, product=db.get(Product, product_id),
                                        quantity=quantity, stock_status=AVAILABLE,
                                        scope={"location_id": location_id, "owner_id": None, "lot_number": lot,
                                               "expiry_date": expiry},
                                        note=f"برگشت به قفسه: سفارش {order.tracking_code} لغو شد")
    order.fulfillment_state = "open"


# ---------------------------------------------------------------------------
# خواندن
# ---------------------------------------------------------------------------
def _serialize(pick_list: PickList, orders: dict[int, Order], codes: dict[int, str], warehouse_code: str | None) -> dict:
    lines = pick_list.lines
    return {
        "id": pick_list.id, "code": pick_list.code, "strategy": pick_list.strategy,
        "strategy_label": PICK_STRATEGY_LABELS[pick_list.strategy], "status": pick_list.status,
        "status_label": PICK_LIST_STATUS_LABELS[pick_list.status], "warehouse_id": pick_list.warehouse_id,
        "warehouse_code": warehouse_code, "zone_code": codes.get(pick_list.zone_location_id),
        "staging_location_id": pick_list.staging_location_id, "staging_code": codes.get(pick_list.staging_location_id),
        "wave_date": pick_list.wave_date, "created_at": pick_list.created_at, "completed_at": pick_list.completed_at,
        "orders": sorted({orders[ln.order_id].tracking_code for ln in lines if ln.order_id in orders}),
        "total_quantity": sum(ln.quantity for ln in lines if ln.status != "canceled"),
        "picked_quantity": sum(ln.picked_quantity for ln in lines),
        "lines": [{
            "id": ln.id, "sequence": ln.sequence, "order_id": ln.order_id,
            "order_tracking_code": orders[ln.order_id].tracking_code if ln.order_id in orders else None,
            "order_fulfillment": FULFILLMENT_LABELS.get(orders[ln.order_id].fulfillment_state) if ln.order_id in orders else None,
            "product_id": ln.product_id, "product_name": ln.product.name, "product_sku": ln.product.sku,
            "product_barcode": ln.product.barcode, "location_id": ln.location_id,
            "location_code": codes.get(ln.location_id), "lot_number": ln.lot_number, "expiry_date": ln.expiry_date,
            "quantity": ln.quantity, "picked_quantity": ln.picked_quantity, "status": ln.status,
            "short_reason": ln.short_reason,
        } for ln in sorted(lines, key=lambda x: (x.sequence, x.id))],
    }


def _context(db: Session, lists: list[PickList]) -> tuple[dict, dict, dict]:
    order_ids = {ln.order_id for pl in lists for ln in pl.lines}
    orders = {o.id: o for o in db.query(Order).filter(Order.id.in_(order_ids or {-1})).all()}
    loc_ids = {ln.location_id for pl in lists for ln in pl.lines} | {pl.zone_location_id for pl in lists} \
        | {pl.staging_location_id for pl in lists}
    codes = {loc.id: loc.code for loc in db.query(Location).filter(Location.id.in_({i for i in loc_ids if i} or {-1})).all()}
    warehouses = {w.id: w.code for w in db.query(Warehouse).all()}
    return orders, codes, warehouses


def get_pick_list(db: Session, user: User, pick_list_id: int) -> dict:
    pick_list = db.query(PickList).options(selectinload(PickList.lines).joinedload(PickLine.product)) \
        .filter(PickList.id == pick_list_id).first()
    if pick_list is None:
        raise NotFoundError("فهرست برداشت یافت نشد.")
    location_service.scope_warehouse(user, pick_list.warehouse_id)
    orders, codes, warehouses = _context(db, [pick_list])
    return _serialize(pick_list, orders, codes, warehouses.get(pick_list.warehouse_id))


def list_pick_lists(db: Session, user: User, *, warehouse_id: int | None = None, status: str | None = None) -> list[dict]:
    warehouse_id = location_service.scope_warehouse(user, warehouse_id)
    query = db.query(PickList).options(selectinload(PickList.lines).joinedload(PickLine.product))
    if warehouse_id is not None:
        query = query.filter(PickList.warehouse_id == warehouse_id)
    if status == "active":
        query = query.filter(PickList.status.in_(("open", "in_progress")))
    elif status:
        query = query.filter(PickList.status == status)
    lists = query.order_by(PickList.id.desc()).limit(100).all()
    orders, codes, warehouses = _context(db, lists)
    return [_serialize(pl, orders, codes, warehouses.get(pl.warehouse_id)) for pl in lists]

