"""
تأمین مجدد محل برداشت و طبقه‌بندی ABC — فصل ۱۳

تأمین مجدد (min/max): برای هر کالا در هر محل برداشت یک حداقل و حداکثر. وقتی موجودی تأییدشده آن محل به‌اضافه
وظایف تأمینِ باز به حداقل (یا کمتر) برسد، تا حداکثر از محل‌های نگهداری همان انبار (FEFO) وظیفه «تأمین مجدد»
ساخته می‌شود؛ اجرای آن همان اجرای اسکنی جانمایی است (سند RP). بررسی خودکار پس از هر برداشت از آن محل،
و دستی/زمان‌بندی‌شده با generate. (نقطه سفارش پویای خرید انبار در replenishment_service است.)

ABC: سهم هر کالا از ارزش مصرف (خروج سفارش × قیمت) در بازه اخیر؛ تا ۸۰٪ تجمعی = A، تا ۹۵٪ = B، بقیه C.
دوره شمارش هر کلاس از app/core/wms.ABC_COUNT_DAYS و فهرست کالاهای «سررسید شمارش» از آخرین انبارگردانی.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.wms import ABC_COUNT_DAYS, ABC_THRESHOLDS, AVAILABLE
from app.models import (
    Location, Product, PutawayTask, ReplenishmentRule, StockBalance, StockMovement, Stocktake, StocktakeLine, User,
)
from app.services import catalog_service, event_bus, location_service, putaway_service
from app.services.exceptions import ConflictError, NotFoundError


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# قواعد حداقل/حداکثر
# ---------------------------------------------------------------------------
def _serialize(rule: ReplenishmentRule, current: int = 0, pending: int = 0) -> dict:
    return {
        "id": rule.id, "warehouse_id": rule.warehouse_id, "location_id": rule.location_id,
        "location_code": rule.location.code, "product_id": rule.product_id, "product_name": rule.product.name,
        "product_sku": rule.product.sku, "min_quantity": rule.min_quantity, "max_quantity": rule.max_quantity,
        "is_active": rule.is_active, "current_quantity": current, "pending_quantity": pending,
        "needs_replenishment": rule.is_active and current + pending <= rule.min_quantity,
    }


def _levels(db: Session, rules: list[ReplenishmentRule]) -> tuple[dict, dict]:
    db.flush()
    pairs = {(r.location_id, r.product_id) for r in rules}
    current: dict = defaultdict(int)
    pending: dict = defaultdict(int)
    if not pairs:
        return current, pending
    locs = {lid for lid, _ in pairs}
    for loc, pid, qty in db.query(StockBalance.location_id, StockBalance.product_id, func.sum(StockBalance.quantity)).filter(
            StockBalance.location_id.in_(locs), StockBalance.stock_status == AVAILABLE)\
            .group_by(StockBalance.location_id, StockBalance.product_id).all():
        current[(loc, pid)] = int(qty or 0)
    for task in db.query(PutawayTask).filter(PutawayTask.task_type == "replenishment",
                                             PutawayTask.status.in_(("open", "partial")),
                                             PutawayTask.suggested_location_id.in_(locs)).all():
        pending[(task.suggested_location_id, task.product_id)] += task.remaining
    return current, pending


def list_rules(db: Session, user: User, warehouse_id: int | None) -> list[dict]:
    warehouse_id = location_service.scope_warehouse(user, warehouse_id)
    query = db.query(ReplenishmentRule).options(joinedload(ReplenishmentRule.location), joinedload(ReplenishmentRule.product))
    if warehouse_id is not None:
        query = query.filter(ReplenishmentRule.warehouse_id == warehouse_id)
    rules = query.order_by(ReplenishmentRule.id).all()
    current, pending = _levels(db, rules)
    return [_serialize(r, current[(r.location_id, r.product_id)], pending[(r.location_id, r.product_id)]) for r in rules]


def save_rule(db: Session, user: User, data, rule_id: int | None = None) -> dict:
    try:
        location = db.get(Location, data.location_id)
        if location is None:
            raise NotFoundError("محل یافت نشد.")
        location_service.scope_warehouse(user, location.warehouse_id)
        if location.location_type != "picking" or location_service.has_children(db, location.id):
            raise ConflictError("قاعده تأمین مجدد فقط برای محل انتهایی از نوع «برداشت» است.")
        if db.get(Product, data.product_id) is None:
            raise NotFoundError("کالا یافت نشد.")
        if rule_id is not None:
            rule = db.get(ReplenishmentRule, rule_id)
            if rule is None:
                raise NotFoundError("قاعده یافت نشد.")
        else:
            rule = db.query(ReplenishmentRule).filter_by(location_id=location.id, product_id=data.product_id).first()
            if rule is not None:
                raise ConflictError("برای این کالا در این محل قبلاً قاعده تعریف شده است.")
            rule = ReplenishmentRule(created_at=_now())
            db.add(rule)
        rule.warehouse_id, rule.location_id, rule.product_id = location.warehouse_id, location.id, data.product_id
        rule.min_quantity, rule.max_quantity, rule.is_active = data.min_quantity, data.max_quantity, data.is_active
        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        raise
    return next(r for r in list_rules(db, user, location.warehouse_id) if r["id"] == rule.id)


def delete_rule(db: Session, user: User, rule_id: int) -> None:
    rule = db.get(ReplenishmentRule, rule_id)
    if rule is None:
        raise NotFoundError("قاعده یافت نشد.")
    location_service.scope_warehouse(user, rule.warehouse_id)
    db.delete(rule)
    db.commit()


def _sources(db: Session, rule: ReplenishmentRule) -> list[tuple[StockBalance, int]]:
    """موجودی قابل برداشت همان کالا در محل‌های نگهداری انبار، FEFO؛ منهای وظایف باز همان محدوده."""
    today = catalog_service.today_local()
    rows = db.query(StockBalance, Location).join(Location, StockBalance.location_id == Location.id).filter(
        StockBalance.warehouse_id == rule.warehouse_id, StockBalance.product_id == rule.product_id,
        StockBalance.stock_status == AVAILABLE, StockBalance.quantity > 0, StockBalance.owner_id.is_(None),
        Location.location_type == "storage", Location.is_active.is_not(False), Location.is_blocked.is_not(True),
        (StockBalance.expiry_date.is_(None)) | (StockBalance.expiry_date >= today),
    ).all()
    taken: dict = defaultdict(int)
    for task in db.query(PutawayTask).filter(PutawayTask.product_id == rule.product_id,
                                             PutawayTask.status.in_(("open", "partial"))).all():
        taken[(task.source_location_id, task.lot_number, task.expiry_date)] += task.remaining
    result = []
    for balance, _location in sorted(rows, key=lambda r: (r[0].expiry_date or datetime.max.date(), r[1].code)):
        key = (balance.location_id, balance.lot_number, balance.expiry_date)
        free = balance.quantity - taken[key]
        if free > 0:
            taken[key] += free
            result.append((balance, free))
    return result


def _replenish(db: Session, user: User | None, rule: ReplenishmentRule, current: int, pending: int) -> int:
    need = rule.max_quantity - current - pending
    created = 0
    for balance, free in _sources(db, rule):
        if need <= 0:
            break
        take = min(free, need)
        putaway_service.create_internal(
            db, user, warehouse_id=rule.warehouse_id, product=rule.product, quantity=take, stock_status=AVAILABLE,
            scope={"location_id": balance.location_id, "owner_id": None, "lot_number": balance.lot_number,
                   "expiry_date": balance.expiry_date},
            task_type="replenishment", destination_id=rule.location_id,
            note=f"تأمین مجدد {rule.location.code} (حداقل {rule.min_quantity}، حداکثر {rule.max_quantity})")
        need -= take
        created += take
    if created:
        event_bus.emit(db, "replenishment.triggered", "replenishment_rule", rule.id,
                       {"location_id": rule.location_id, "product_id": rule.product_id, "quantity": created},
                       organization_id=rule.organization_id, actor=user)
    return created


def check(db: Session, user: User | None, location_ids) -> int:
    """پس از برداشت از محل‌ها: قواعد فعال آن محل‌ها را بررسی و در صورت نیاز وظیفه تأمین می‌سازد (بدون commit)."""
    rules = db.query(ReplenishmentRule).options(joinedload(ReplenishmentRule.location), joinedload(ReplenishmentRule.product))\
        .filter(ReplenishmentRule.location_id.in_(list(location_ids) or [-1]), ReplenishmentRule.is_active.is_(True)).all()
    current, pending = _levels(db, rules)
    total = 0
    for rule in rules:
        key = (rule.location_id, rule.product_id)
        if current[key] + pending[key] <= rule.min_quantity:
            total += _replenish(db, user, rule, current[key], pending[key])
    return total


def generate(db: Session, user: User, warehouse_id: int | None) -> dict:
    warehouse_id = location_service.scope_warehouse(user, warehouse_id)
    try:
        query = db.query(ReplenishmentRule.location_id).filter(ReplenishmentRule.is_active.is_(True))
        if warehouse_id is not None:
            query = query.filter(ReplenishmentRule.warehouse_id == warehouse_id)
        quantity = check(db, user, {lid for (lid,) in query.all()})
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"quantity": quantity}


# ---------------------------------------------------------------------------
# ABC و دوره شمارش
# ---------------------------------------------------------------------------
def classify(db: Session, user: User | None, days: int = 365) -> dict:
    """ارزش مصرف هر کالا در days روز اخیر ← کلاس ABC (روی خود کالا ذخیره می‌شود)."""
    since = _now() - timedelta(days=days)
    usage = dict(db.query(StockMovement.product_id, func.sum(-StockMovement.quantity_change)).filter(
        StockMovement.movement_type == "order_out", StockMovement.created_at >= since,
    ).group_by(StockMovement.product_id).all())
    products = db.query(Product).all()
    prices = catalog_service.prices_at(db, [p.id for p in products], catalog_service.today_local())
    values = {p.id: float(usage.get(p.id, 0) or 0) * (prices[p.id].final_price if p.id in prices else (p.price or 0))
              for p in products}
    total = sum(values.values())
    cumulative, counts = 0.0, {"A": 0, "B": 0, "C": 0}
    now = _now()
    for product in sorted(products, key=lambda p: (-values[p.id], p.id)):
        value = values[product.id]
        share_before = cumulative / total if total else 1
        cumulative += value
        if value <= 0 or not total:
            klass = "C"
        elif share_before < ABC_THRESHOLDS[0]:
            klass = "A"
        elif share_before < ABC_THRESHOLDS[1]:
            klass = "B"
        else:
            klass = "C"
        product.abc_class, product.abc_value, product.abc_updated_at = klass, round(value, 2), now
        counts[klass] += 1
    org_id = user.organization_id if user else (products[0].organization_id if products else None)
    if org_id is not None:
        event_bus.emit(db, "abc.classified", "organization", org_id, {"days": days, **counts}, organization_id=org_id, actor=user)
    db.commit()
    return {"days": days, "total_value": round(total, 2), **counts}


def abc_report(db: Session, user: User, warehouse_id: int | None = None) -> list[dict]:
    """کلاس، ارزش مصرف، آخرین شمارش و سررسید شمارش بعدی هر کالا (اختیاری: فقط کالاهای یک انبار)."""
    warehouse_id = location_service.scope_warehouse(user, warehouse_id)
    last_counts = dict(db.query(StocktakeLine.product_id, func.max(Stocktake.approved_at)).join(
        Stocktake, StocktakeLine.stocktake_id == Stocktake.id).filter(Stocktake.status == "approved",
        *( [Stocktake.warehouse_id == warehouse_id] if warehouse_id is not None else [])).group_by(StocktakeLine.product_id).all())
    query = db.query(Product).filter(Product.is_active.is_not(False))
    if warehouse_id is not None:
        query = query.filter(Product.id.in_(db.query(StockBalance.product_id).filter(StockBalance.warehouse_id == warehouse_id)))
    total = sum(p.abc_value or 0 for p in query.all()) or 0
    today = catalog_service.today_local()
    rows = []
    for p in sorted(query.all(), key=lambda p: (p.abc_class or "Z", -(p.abc_value or 0), p.id)):
        last = last_counts.get(p.id)
        days = ABC_COUNT_DAYS.get(p.abc_class or "C", ABC_COUNT_DAYS["C"])
        next_due = (last.date() + timedelta(days=days)) if last else today
        rows.append({
            "product_id": p.id, "product_name": p.name, "product_sku": p.sku, "abc_class": p.abc_class,
            "consumption_value": p.abc_value or 0, "share": round((p.abc_value or 0) / total * 100, 2) if total else 0,
            "count_every_days": days, "last_counted_at": last, "next_count_due": next_due, "count_due": next_due <= today,
            "classified_at": p.abc_updated_at,
        })
    return rows
