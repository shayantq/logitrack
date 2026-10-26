"""
انبارگردانی (مرحله ۱۲، تکمیل فصل ۱۶).

گردش کار: ایجاد ← شمارش ← ارسال برای بررسی ← بررسی مغایرت (شمارش مجدد اقلام مشکوک) ← تأیید ← اصلاحیه انبارگردانی.

نوع شمارش:
  • کامل (full) — همه موجودی سالم انبار؛ ممیزی کامل دوره‌ای
  • بخشی (partial) — کالاهای انتخابی
  • دوره‌ای (cycle) — کالاهایی که طبق کلاس ABC سررسید شمارش‌شان رسیده (A هر ۳۰، B هر ۹۰، C هر ۱۸۰ روز)
شمارش کور (blind): عدد سیستم تا مرحله بررسی به هیچ‌کس نشان داده نمی‌شود؛ شمارش راهنما (blind=False) عدد سیستم را
به شمارنده هم نشان می‌دهد (برای شمارش سریع محل‌های کم‌ریسک).

شمارش در سطح محل (by_location): هر کالا × محل یک سطر (موجودی «بدون محل» هم سطر جدا)؛ اصلاحیه دقیقاً روی همان
محل ثبت می‌شود. همزمانی با عملیات انبار دو حالت دارد:
  • عکس لحظه‌ای (snapshot) — عملیات متوقف نمی‌شود؛ موجودی سیستم «در لحظه شمارش هر قلم» ذخیره می‌شود و
    اصلاحیه = شمرده‌شده − همان عدد، پس گردش‌های بعد از شمارش دست نمی‌خورند.
  • قفل محل (lock) — محل‌های محدوده تا تأیید/لغو هیچ ورود و خروجی نمی‌پذیرند (stock_ledger._ensure_not_counting)،
    برداشت و جانمایی هم آن‌ها را پیشنهاد نمی‌دهد.

تأیید: اگر ارزش کل مغایرت از «سقف تأیید» سازمان (control_settings) بیشتر باشد مجوز «تأیید بالای سقف» لازم است،
وگرنه مجوز «تأیید زیر سقف» کافی است. تفکیک وظایف: مدیر انبار شمارشی را که خودش شمرده تأیید نمی‌کند.
موجودی هرگز کمتر از رزرو سفارش‌های باز نمی‌شود (اختلاف باقی‌مانده در ستون «اصلاح‌شده» دیده می‌شود).
"""
from __future__ import annotations

import secrets
import string
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.iran import fa_digits
from app.core.wms import ABC_COUNT_DAYS, AVAILABLE
from app.models import Inventory, Location, Product, StockBalance, Stocktake, StocktakeLine, User, Warehouse
from app.services import audit_service, control_settings, location_service, notification_service, permission_service, stock_ledger
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError

ACTIVE = ("counting", "review")
REASON_LABELS = {
    "damage": "خرابی و آسیب", "loss": "مفقودی یا سرقت", "entry_error": "خطای ثبت قبلی",
    "unrecorded": "ورود/خروج ثبت‌نشده", "unknown": "نامشخص",
}
COUNT_TYPE_LABELS = {"full": "کامل", "partial": "بخشی", "cycle": "دوره‌ای (ABC)"}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _role(user: User) -> str:
    return getattr(user.role, "value", user.role)


def _new_code(db: Session) -> str:
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = "ST-" + "".join(secrets.choice(alphabet) for _ in range(6))
        if not db.query(Stocktake.id).filter(Stocktake.code == code).first():
            return code


def _ensure_staff(user: User) -> None:
    if _role(user) not in ("org_admin", "warehouse_manager"):
        raise ForbiddenError("انبارگردانی فقط برای ادمین سازمان و مدیر انبار است.")


def _can_review(db: Session, user: User) -> bool:
    return permission_service.allowed(db, user, "stocktake.approve") or permission_service.allowed(db, user, "stocktake.approve_minor")


def _ensure_reviewer(db: Session, user: User) -> None:
    if not _can_review(db, user):
        raise ForbiddenError("بررسی و تأیید انبارگردانی با ادمین سازمان (یا نقشی که مجوز تأیید دارد) است.")


def _warehouse_allowed(user: User, warehouse_id: int) -> None:
    if _role(user) == "warehouse_manager" and user.warehouse_id != warehouse_id:
        raise ForbiddenError("فقط انبار خودتان را می‌توانید انبارگردانی کنید.")


def _load(db: Session, user: User, stocktake_id: int) -> Stocktake:
    _ensure_staff(user)
    st = db.get(Stocktake, stocktake_id)
    if st is None or (_role(user) == "warehouse_manager" and st.warehouse_id != user.warehouse_id):
        raise NotFoundError("انبارگردانی یافت نشد.")
    return st


def _inventory(db: Session, product_id: int, warehouse_id: int, lock: bool = False) -> Inventory | None:
    query = db.query(Inventory).filter(Inventory.product_id == product_id, Inventory.warehouse_id == warehouse_id,
                                       Inventory.stock_status == AVAILABLE)
    if lock:
        query = query.with_for_update()
    return query.order_by(Inventory.id).first()


def _location_qty(db: Session, warehouse_id: int, product_id: int, location_id: int | None) -> int:
    db.flush()
    query = db.query(func.coalesce(func.sum(StockBalance.quantity), 0)).filter(
        StockBalance.warehouse_id == warehouse_id, StockBalance.product_id == product_id,
        StockBalance.stock_status == AVAILABLE,
        StockBalance.location_id.is_(None) if location_id is None else StockBalance.location_id == location_id)
    return int(query.scalar() or 0)


def _expected(db: Session, st: Stocktake, line: StocktakeLine) -> int:
    """موجودی سیستم همین لحظه برای یک سطر: در سطح محل، مانده همان محل؛ وگرنه کل موجودی سالم انبار."""
    if st.by_location:
        return _location_qty(db, st.warehouse_id, line.product_id, line.location_id)
    inv = _inventory(db, line.product_id, st.warehouse_id)
    return (inv.quantity or 0) if inv else 0


def _names(db: Session, ids: set[int | None]) -> dict[int, str]:
    ids = {i for i in ids if i}
    return {u.id: u.full_name or u.username for u in db.query(User).filter(User.id.in_(ids or {-1})).all()}


def _variance_value(st: Stocktake) -> float:
    return sum(abs((l.counted_qty or 0) - (l.expected_qty or 0)) * (l.unit_price or 0)
               for l in st.lines if l.counted_qty is not None and l.expected_qty is not None)


# ---------------------------------------------------------------------------
# خروجی
# ---------------------------------------------------------------------------
def _summary(st: Stocktake, warehouse_names: dict[int, str]) -> dict:
    counted = sum(1 for l in st.lines if l.counted_qty is not None)
    return {
        "id": st.id, "code": st.code, "title": st.title, "scope": st.scope, "status": st.status,
        "count_type": st.count_type or ("full" if st.scope == "full" else "partial"),
        "blind": st.blind is not False, "freeze_mode": st.freeze_mode or "snapshot", "by_location": bool(st.by_location),
        "warehouse_id": st.warehouse_id, "warehouse_name": warehouse_names.get(st.warehouse_id, ""),
        "created_at": st.created_at, "submitted_at": st.submitted_at, "approved_at": st.approved_at,
        "lines_total": len(st.lines), "lines_counted": counted,
    }


def detail(db: Session, user: User, stocktake_id: int) -> dict:
    st = _load(db, user, stocktake_id)
    return _detail(db, user, st)


def _detail(db: Session, user: User, st: Stocktake) -> dict:
    reviewer = _can_review(db, user)
    reveal = reviewer and st.status in ("review", "approved")     # شمارش کور: عدد سیستم فقط هنگام بررسی
    guided = st.blind is False and st.status == "counting"         # شمارش راهنما: عدد لحظه‌ای سیستم به شمارنده
    warehouse = db.get(Warehouse, st.warehouse_id)
    names = _names(db, {l.counted_by_id for l in st.lines} | {st.created_by_id, st.submitted_by_id, st.approved_by_id})
    lines, totals = [], {"variance_lines": 0, "shortage_qty": 0, "surplus_qty": 0, "shortage_value": 0.0, "surplus_value": 0.0}
    for l in st.lines:
        row = {
            "id": l.id, "product_id": l.product_id, "product_name": l.product_name, "product_sku": l.product_sku,
            "location_id": l.location_id, "location_code": l.location_code if st.by_location else None,
            "added_during_count": l.added_during_count, "counted_qty": l.counted_qty, "counted_at": l.counted_at,
            "counted_by": names.get(l.counted_by_id), "previous_count": l.previous_count, "recount_note": l.recount_note,
            "expected_qty": None, "system_qty": _expected(db, st, l) if guided else None,
            "variance": None, "variance_value": None, "variance_reason": l.variance_reason, "adjustment": l.adjustment,
        }
        if reveal and l.counted_qty is not None and l.expected_qty is not None:
            variance = l.counted_qty - l.expected_qty
            row.update(expected_qty=l.expected_qty, variance=variance, variance_value=round(variance * (l.unit_price or 0)))
            if variance:
                totals["variance_lines"] += 1
                key = "shortage" if variance < 0 else "surplus"
                totals[f"{key}_qty"] += abs(variance)
                totals[f"{key}_value"] += abs(variance) * (l.unit_price or 0)
        lines.append(row)
    counted = sum(1 for l in st.lines if l.counted_qty is not None)
    data = _summary(st, {st.warehouse_id: warehouse.name if warehouse else ""})
    can_count = st.status == "counting" and (_role(user) == "org_admin" or user.warehouse_id == st.warehouse_id)
    counters = {l.counted_by_id for l in st.lines if l.counted_by_id}
    threshold = control_settings.of(db, st.organization_id)["count_approval_value"]
    variance_value = _variance_value(st) if reveal else None
    needs_full = variance_value is not None and variance_value > threshold
    can_approve = st.status == "review" and (permission_service.allowed(db, user, "stocktake.approve") or (
        not needs_full and permission_service.allowed(db, user, "stocktake.approve_minor")))
    segregation = _role(user) != "org_admin" and user.id in counters
    data.update(
        note=st.note, lines=lines, revealed=reveal, approval_note=st.approval_note,
        created_by=names.get(st.created_by_id), submitted_by=names.get(st.submitted_by_id), approved_by=names.get(st.approved_by_id),
        accuracy=round(100 * (counted - totals["variance_lines"]) / counted, 1) if reveal and counted else None,
        **({k: (round(v) if isinstance(v, float) else v) for k, v in totals.items()} if reveal else
           {k: None for k in totals}),
        variance_value_total=round(variance_value) if variance_value is not None else None,
        approval_threshold=threshold, needs_full_approval=needs_full,
        locked_locations=db.query(Location).filter(Location.count_lock_id == st.id).count() if st.status in ACTIVE else 0,
        can_count=can_count,
        can_submit=can_count and counted == len(st.lines) and len(st.lines) > 0,
        can_review=reviewer and st.status == "review",
        can_approve=bool(can_approve) and not segregation,
        can_cancel=permission_service.allowed(db, user, "stocktake.approve") and st.status in ACTIVE,
        # تفکیک وظایف: هشدار وقتی تأییدکننده خودش هم شمرده است (مدیر انبار اصلاً نمی‌تواند تأیید کند)
        self_review=reviewer and st.status == "review" and user.id in counters,
    )
    return data


def list_stocktakes(db: Session, user: User, status: str | None = None, warehouse_id: int | None = None) -> list[dict]:
    _ensure_staff(user)
    query = db.query(Stocktake)
    if _role(user) == "warehouse_manager":
        query = query.filter(Stocktake.warehouse_id == user.warehouse_id)
    if status:
        query = query.filter(Stocktake.status == status)
    if warehouse_id:
        query = query.filter(Stocktake.warehouse_id == warehouse_id)
    names = {w.id: w.name for w in db.query(Warehouse).all()}
    return [_summary(st, names) for st in query.order_by(Stocktake.created_at.desc(), Stocktake.id.desc()).limit(200).all()]


def overview(db: Session, user: User) -> list[dict]:
    """وضعیت انبارگردانی هر انبار: آخرین انبارگردانی، دوره، سررسید، انبارگردانی فعال و کالاهای سررسید شمارش دوره‌ای."""
    _ensure_staff(user)
    query = db.query(Warehouse)
    if _role(user) == "warehouse_manager":
        query = query.filter(Warehouse.id == user.warehouse_id)
    today = _now()
    result = []
    for w in query.order_by(Warehouse.id).all():
        last = db.query(Stocktake).filter(Stocktake.warehouse_id == w.id, Stocktake.status == "approved") \
            .order_by(Stocktake.approved_at.desc()).first()
        active = db.query(Stocktake).filter(Stocktake.warehouse_id == w.id, Stocktake.status.in_(ACTIVE)).first()
        due = None
        if w.stocktake_interval_days:
            due = (last.approved_at if last else None)
            due = due + timedelta(days=w.stocktake_interval_days) if due else today
        result.append({
            "warehouse_id": w.id, "warehouse_name": w.name, "city": w.city, "interval_days": w.stocktake_interval_days,
            "last_approved_at": last.approved_at if last else None, "last_code": last.code if last else None,
            "next_due_at": due, "overdue": bool(due and due <= today and not active),
            "active": _summary(active, {w.id: w.name}) if active else None,
            "items": db.query(Inventory).filter(Inventory.warehouse_id == w.id, Inventory.stock_status == AVAILABLE).count(),
            "cycle_due": sum(1 for c in _cycle_rows(db, w.id) if c["due"]),
            "has_locations": db.query(Location.id).filter(Location.warehouse_id == w.id).first() is not None,
        })
    return result


def summary(db: Session, user: User) -> dict:
    """نشان منو: مدیر انبار ← انبارگردانی‌های در حال شمارش؛ تأییدکننده ← منتظر بررسی + سررسیدگذشته."""
    _ensure_staff(user)
    if _role(user) == "warehouse_manager" and not _can_review(db, user):
        return {"count": db.query(Stocktake).filter(Stocktake.warehouse_id == user.warehouse_id, Stocktake.status == "counting").count()}
    query = db.query(Stocktake).filter(Stocktake.status == "review")
    if _role(user) == "warehouse_manager":
        query = query.filter(Stocktake.warehouse_id == user.warehouse_id)
    overdue = sum(1 for w in overview(db, user) if w["overdue"])
    return {"count": query.count() + overdue}


# ---------------------------------------------------------------------------
# شمارش دوره‌ای بر اساس ABC
# ---------------------------------------------------------------------------
def _cycle_rows(db: Session, warehouse_id: int) -> list[dict]:
    today = _now()
    stocked = db.query(Product).join(Inventory, Inventory.product_id == Product.id).filter(
        Inventory.warehouse_id == warehouse_id, Inventory.stock_status == AVAILABLE, Inventory.quantity > 0).all()
    if not stocked:
        return []
    last = dict(db.query(StocktakeLine.product_id, func.max(Stocktake.approved_at)).join(
        Stocktake, Stocktake.id == StocktakeLine.stocktake_id).filter(
        Stocktake.warehouse_id == warehouse_id, Stocktake.status == "approved",
        StocktakeLine.product_id.in_({p.id for p in stocked}), StocktakeLine.counted_qty.is_not(None),
    ).group_by(StocktakeLine.product_id).all())
    rows = []
    for p in stocked:
        cls = p.abc_class or "C"
        counted_at = last.get(p.id)
        due_at = counted_at + timedelta(days=ABC_COUNT_DAYS[cls]) if counted_at else None
        rows.append({"product_id": p.id, "product_name": p.name, "product_sku": p.sku, "abc_class": cls,
                     "last_counted_at": counted_at, "due_at": due_at, "due": due_at is None or due_at <= today,
                     "interval_days": ABC_COUNT_DAYS[cls]})
    rows.sort(key=lambda r: (not r["due"], "ABC".index(r["abc_class"]), r["due_at"] or datetime.min, r["product_name"]))
    return rows


def cycle_candidates(db: Session, user: User, warehouse_id: int) -> list[dict]:
    _ensure_staff(user)
    _warehouse_allowed(user, warehouse_id)
    return _cycle_rows(db, warehouse_id)


# ---------------------------------------------------------------------------
# ایجاد و شمارش
# ---------------------------------------------------------------------------
def _scope_lines(db: Session, st: Stocktake, products: list[Product], location_ids: list[int] | None) -> list[tuple[Product, int | None, str | None]]:
    """سطرهای شمارش: بدون محل ← یک سطر برای هر کالا؛ در سطح محل ← هر کالا × محل دارای موجودی سالم."""
    if not st.by_location:
        return [(p, None, None) for p in products]
    db.flush()
    leaves = location_service.leaf_ids(db, st.warehouse_id, location_ids) if location_ids else None
    query = db.query(StockBalance.product_id, StockBalance.location_id).filter(
        StockBalance.warehouse_id == st.warehouse_id, StockBalance.stock_status == AVAILABLE, StockBalance.quantity > 0)
    if products:
        query = query.filter(StockBalance.product_id.in_({p.id for p in products}))
    if leaves is not None:
        query = query.filter(StockBalance.location_id.in_(leaves or [-1]))
    pairs = sorted(set(query.all()), key=lambda x: (x[1] is None, x[1] or 0, x[0]))
    by_id = {p.id: p for p in products} if products else {p.id: p for p in db.query(Product).filter(
        Product.id.in_({pid for pid, _ in pairs} or {-1})).all()}
    codes = {loc.id: loc.code for loc in db.query(Location).filter(Location.id.in_({lid for _, lid in pairs if lid} or {-1})).all()}
    return [(by_id[pid], lid, codes.get(lid)) for pid, lid in pairs if pid in by_id]


def create(db: Session, user: User, *, warehouse_id: int, scope: str, product_ids: list[int] | None,
           title: str | None, note: str | None, count_type: str | None = None, blind: bool = True,
           freeze_mode: str = "snapshot", by_location: bool = False, location_ids: list[int] | None = None,
           abc_classes: list[str] | None = None, limit: int | None = None) -> dict:
    _ensure_staff(user)
    permission_service.ensure(db, user, "stocktake.create")
    warehouse = db.get(Warehouse, warehouse_id)
    if warehouse is None:
        raise NotFoundError("انبار یافت نشد.")
    _warehouse_allowed(user, warehouse_id)
    if db.query(Stocktake).filter(Stocktake.warehouse_id == warehouse_id, Stocktake.status.in_(ACTIVE)).first():
        raise ConflictError(f"برای «{warehouse.name}» یک انبارگردانی فعال وجود دارد؛ ابتدا آن را تمام یا لغو کنید.")
    count_type = count_type or ("full" if scope == "full" else "partial")
    if location_ids:
        by_location = True
        found = db.query(Location.id).filter(Location.id.in_(set(location_ids)), Location.warehouse_id == warehouse_id).count()
        if found != len(set(location_ids)):
            raise NotFoundError("بعضی از محل‌های انتخاب‌شده در این انبار یافت نشدند.")
    if freeze_mode == "lock" and not by_location:
        raise ConflictError("قفل محل فقط در شمارش «در سطح محل» ممکن است.")

    if count_type == "full":
        products = [inv.product for inv in db.query(Inventory).filter(Inventory.warehouse_id == warehouse_id,
                                                                       Inventory.stock_status == AVAILABLE)
                    .order_by(Inventory.id).all() if inv.product is not None]
        products = [] if location_ids else products        # محدوده محل‌ها: همه کالاهای داخل آن محل‌ها
    elif count_type == "cycle":
        rows = [r for r in _cycle_rows(db, warehouse_id) if r["due"] and (not abc_classes or r["abc_class"] in abc_classes)]
        if limit:
            rows = rows[:limit]
        if not rows:
            raise ConflictError("هیچ کالایی سررسید شمارش دوره‌ای ندارد.")
        products = db.query(Product).filter(Product.id.in_({r["product_id"] for r in rows})).order_by(Product.name).all()
    else:
        if not product_ids:
            raise ConflictError("برای انبارگردانی بخشی، دست‌کم یک کالا انتخاب کنید.")
        products = db.query(Product).filter(Product.id.in_(set(product_ids))).order_by(Product.name).all()
        if len(products) != len(set(product_ids)):
            raise NotFoundError("بعضی از کالاهای انتخاب‌شده یافت نشدند.")
    if not products and not location_ids:
        raise ConflictError("این انبار کالایی برای شمارش ندارد.")
    st = Stocktake(organization_id=warehouse.organization_id, code=_new_code(db), warehouse_id=warehouse_id,
                   scope="full" if count_type == "full" else "partial", count_type=count_type, blind=blind,
                   freeze_mode=freeze_mode, by_location=by_location, location_ids=sorted(set(location_ids)) if location_ids else None,
                   title=(title or "").strip() or f"انبارگردانی {COUNT_TYPE_LABELS[count_type]} {warehouse.name}",
                   note=(note or "").strip() or None, status="counting", created_by_id=user.id)
    db.add(st)
    db.flush()
    seen = set()
    for p, location_id, location_code in _scope_lines(db, st, products, location_ids):
        if (p.id, location_id) in seen:
            continue
        seen.add((p.id, location_id))
        inv = _inventory(db, p.id, warehouse_id)
        db.add(StocktakeLine(organization_id=st.organization_id, stocktake_id=st.id, product_id=p.id,
                             location_id=location_id, location_code=location_code,
                             inventory_id=inv.id if inv else None, product_name=p.name, product_sku=p.sku, unit_price=p.price or 0))
    if not seen and not location_ids:
        raise ConflictError("در محدوده انتخابی موجودی سالمی برای شمارش نیست.")
    if freeze_mode == "lock":
        _lock_locations(db, st, location_ids)
    audit_service.log(db, user, "stocktake.create",
                      f"انبارگردانی {COUNT_TYPE_LABELS[count_type]} {st.code} در «{warehouse.name}» شروع شد"
                      f"{' با قفل محل‌ها' if freeze_mode == 'lock' else ''}",
                      target_type="stocktake", target_id=st.id, target_label=st.code,
                      details={"count_type": count_type, "blind": blind, "freeze_mode": freeze_mode, "lines": len(seen)})
    db.commit()
    db.refresh(st)
    return _detail(db, user, st)


def _lock_locations(db: Session, st: Stocktake, location_ids: list[int] | None) -> None:
    targets = set(location_service.leaf_ids(db, st.warehouse_id, location_ids)) if location_ids else set()
    targets |= {l.location_id for l in db.query(StocktakeLine).filter(StocktakeLine.stocktake_id == st.id,
                                                                       StocktakeLine.location_id.is_not(None)).all()}
    if not targets:
        return
    db.query(Location).filter(Location.id.in_(targets)).update({Location.count_lock_id: st.id}, synchronize_session=False)


def _unlock(db: Session, st: Stocktake) -> None:
    db.query(Location).filter(Location.count_lock_id == st.id).update({Location.count_lock_id: None}, synchronize_session=False)


def _counting(db: Session, user: User, stocktake_id: int) -> Stocktake:
    st = _load(db, user, stocktake_id)
    if st.status != "counting":
        raise ConflictError("این انبارگردانی در مرحله شمارش نیست.")
    if _role(user) == "warehouse_manager" and user.warehouse_id != st.warehouse_id:
        raise ForbiddenError()
    return st


def count(db: Session, user: User, stocktake_id: int, line_id: int, counted_qty: int) -> dict:
    st = _counting(db, user, stocktake_id)
    line = next((l for l in st.lines if l.id == line_id), None)
    if line is None:
        raise NotFoundError("این قلم در انبارگردانی نیست.")
    # موجودی سیستم در همین لحظه — مبنای مغایرت (در شمارش کور به شمارنده نمایش داده نمی‌شود)
    line.counted_qty, line.expected_qty = counted_qty, _expected(db, st, line)
    line.counted_at, line.counted_by_id = _now(), user.id
    inv = _inventory(db, line.product_id, st.warehouse_id)
    if inv is not None:
        line.inventory_id = inv.id
    db.commit()
    db.refresh(st)
    return _detail(db, user, st)


def add_line(db: Session, user: User, stocktake_id: int, product_id: int, counted_qty: int,
             location_id: int | None = None) -> dict:
    """کالایی که در فهرست نبود ولی در انبار (یا در یک محل) پیدا شد."""
    st = _counting(db, user, stocktake_id)
    if not st.by_location:
        location_id = None
    if any(l.product_id == product_id and l.location_id == location_id for l in st.lines):
        raise ConflictError("این کالا از قبل در فهرست شمارش هست.")
    product = db.get(Product, product_id)
    if product is None:
        raise NotFoundError("کالا یافت نشد.")
    location = location_service.resolve(db, st.warehouse_id, location_id)
    if location is not None and location_service.has_children(db, location.id):
        raise ConflictError("کالا فقط در محل انتهایی (خانه) شمرده می‌شود.")
    inv = _inventory(db, product_id, st.warehouse_id)
    line = StocktakeLine(organization_id=st.organization_id, stocktake_id=st.id, product_id=product.id,
                         location_id=location_id, location_code=location.code if location else None,
                         inventory_id=inv.id if inv else None, product_name=product.name, product_sku=product.sku,
                         unit_price=product.price or 0, added_during_count=True, counted_qty=counted_qty,
                         counted_at=_now(), counted_by_id=user.id)
    line.expected_qty = _expected(db, st, line)
    db.add(line)
    if st.freeze_mode == "lock" and location is not None and location.count_lock_id is None:
        location.count_lock_id = st.id
    db.commit()
    db.refresh(st)
    return _detail(db, user, st)


def submit(db: Session, user: User, stocktake_id: int) -> dict:
    st = _counting(db, user, stocktake_id)
    missing = [l.product_name for l in st.lines if l.counted_qty is None]
    if missing:
        raise ConflictError(f"{fa_digits(str(len(missing)))} قلم هنوز شمرده نشده است (مثلاً «{missing[0]}»).")
    if not st.lines:
        raise ConflictError("هیچ قلمی شمرده نشده است.")
    st.status, st.submitted_at, st.submitted_by_id = "review", _now(), user.id
    notification_service.stocktake_event(db, st, "submitted", user)
    db.commit()
    db.refresh(st)
    return _detail(db, user, st)


# ---------------------------------------------------------------------------
# بررسی و تأیید
# ---------------------------------------------------------------------------
def _review(db: Session, user: User, stocktake_id: int) -> Stocktake:
    _ensure_reviewer(db, user)
    st = _load(db, user, stocktake_id)
    if st.status != "review":
        raise ConflictError("این انبارگردانی در مرحله بررسی نیست.")
    return st


def recount(db: Session, user: User, stocktake_id: int, line_ids: list[int], note: str | None) -> dict:
    st = _review(db, user, stocktake_id)
    targets = [l for l in st.lines if l.id in set(line_ids)]
    if not targets:
        raise ConflictError("اقلام شمارش مجدد را انتخاب کنید.")
    for l in targets:
        l.previous_count, l.counted_qty, l.expected_qty = l.counted_qty, None, None
        l.counted_at, l.counted_by_id, l.recount_note = None, None, (note or "").strip() or "شمارش مجدد"
    st.status, st.submitted_at, st.submitted_by_id = "counting", None, None
    notification_service.stocktake_event(db, st, "recount", user, note)
    audit_service.log(db, user, "stocktake.recount", f"شمارش مجدد {fa_digits(str(len(targets)))} قلم از {st.code} خواسته شد",
                      target_type="stocktake", target_id=st.id, target_label=st.code, reason=(note or "").strip() or None)
    db.commit()
    db.refresh(st)
    return _detail(db, user, st)


def approve(db: Session, user: User, stocktake_id: int, reasons: dict[int, str], note: str | None = None) -> dict:
    st = _review(db, user, stocktake_id)
    threshold = control_settings.of(db, st.organization_id)["count_approval_value"]
    total = _variance_value(st)
    needed = "stocktake.approve" if total > threshold else "stocktake.approve_minor"
    if not (permission_service.allowed(db, user, needed) or permission_service.allowed(db, user, "stocktake.approve")):
        raise ForbiddenError(f"ارزش مغایرت ({fa_digits(f'{round(total):,}')} ریال) از سقف تأیید شما بیشتر است؛ "
                             "تأیید با ادمین سازمان است.")
    if _role(user) != "org_admin" and any(l.counted_by_id == user.id for l in st.lines):
        raise ForbiddenError("تفکیک وظایف: شمارشی را که خودتان انجام داده‌اید نمی‌توانید تأیید کنید.")
    document = None
    adjusted = 0
    for l in sorted(st.lines, key=lambda l: (l.product_id, l.location_id or 0)):
        variance = (l.counted_qty or 0) - (l.expected_qty or 0)
        if variance == 0:
            l.adjustment = 0
            continue
        l.variance_reason = reasons.get(l.id) or "unknown"
        inv = stock_ledger.lock_bucket(db, l.product_id, st.warehouse_id, organization_id=st.organization_id)
        # اگر بعد از شمارش کالا خارج یا رزرو شده، اصلاح منفی فقط تا مقدار رزرو سفارش‌های باز انجام می‌شود
        change = max(variance, (inv.reserved_quantity or 0) - (inv.quantity or 0))
        if st.by_location and change < 0:
            change = max(change, -_location_qty(db, st.warehouse_id, l.product_id, l.location_id))
        if change:
            if document is None:
                document = stock_ledger.new_document(
                    db, "stocktake", organization_id=st.organization_id, user=user, warehouse_id=st.warehouse_id,
                    reference_type="stocktake", reference_id=st.id, note=f"اصلاحیه انبارگردانی {st.code}",
                )
            stock_ledger.record(db, inv, change, "stocktake", document=document, user=user,
                                reason=f"انبارگردانی {st.code}: {REASON_LABELS.get(l.variance_reason, l.variance_reason)}",
                                reference_type="stocktake", reference_id=st.id,
                                match={"location_id": l.location_id} if st.by_location else None)
            adjusted += 1
        l.adjustment, l.inventory_id = change, inv.id
    st.status, st.approved_at, st.approved_by_id = "approved", _now(), user.id
    st.approval_note = (note or "").strip() or None
    _unlock(db, st)
    notification_service.stocktake_event(db, st, "approved", user)
    audit_service.log(db, user, "stocktake.approve",
                      f"انبارگردانی {st.code} تأیید شد ({fa_digits(str(adjusted))} قلم اصلاح، ارزش مغایرت "
                      f"{fa_digits(f'{round(total):,}')} ریال)",
                      target_type="stocktake", target_id=st.id, target_label=st.code, reason=st.approval_note,
                      details={"variance_value": round(total), "threshold": threshold, "adjusted_lines": adjusted,
                               "document": document.code if document else None})
    db.commit()
    db.refresh(st)
    return _detail(db, user, st)


def cancel(db: Session, user: User, stocktake_id: int, reason: str | None = None) -> dict:
    permission_service.ensure(db, user, "stocktake.approve", "لغو انبارگردانی با ادمین سازمان است.")
    st = _load(db, user, stocktake_id)
    if st.status not in ACTIVE:
        raise ConflictError("فقط انبارگردانی در حال انجام لغو می‌شود.")
    st.status, st.canceled_at = "canceled", _now()
    _unlock(db, st)
    audit_service.log(db, user, "stocktake.cancel", f"انبارگردانی {st.code} لغو شد", target_type="stocktake",
                      target_id=st.id, target_label=st.code, reason=(reason or "").strip() or None)
    db.commit()
    db.refresh(st)
    return _detail(db, user, st)


def set_interval(db: Session, user: User, warehouse_id: int, days: int | None) -> list[dict]:
    if _role(user) != "org_admin":
        raise ForbiddenError("دوره انبارگردانی را ادمین سازمان تعیین می‌کند.")
    warehouse = db.get(Warehouse, warehouse_id)
    if warehouse is None:
        raise NotFoundError("انبار یافت نشد.")
    warehouse.stocktake_interval_days = days
    db.commit()
    return overview(db, user)


def accuracy_stats(db: Session, start: datetime, end: datetime, warehouse_id: int | None = None) -> dict:
    """دقت موجودی انبارگردانی‌های تأییدشده بازه — برای داشبورد شاخص‌ها (فصل ۲۸)."""
    query = db.query(StocktakeLine).join(Stocktake, Stocktake.id == StocktakeLine.stocktake_id).filter(
        Stocktake.status == "approved", Stocktake.approved_at >= start, Stocktake.approved_at < end,
        StocktakeLine.counted_qty.is_not(None))
    if warehouse_id:
        query = query.filter(Stocktake.warehouse_id == warehouse_id)
    lines = query.all()
    exact = sum(1 for l in lines if l.counted_qty == l.expected_qty)
    by_value = defaultdict(float)
    for l in lines:
        by_value["expected"] += (l.expected_qty or 0) * (l.unit_price or 0)
        by_value["variance"] += abs((l.counted_qty or 0) - (l.expected_qty or 0)) * (l.unit_price or 0)
    return {"lines": len(lines), "exact": exact,
            "accuracy": round(100 * exact / len(lines), 1) if lines else None,
            "value_accuracy": round(100 * (1 - by_value["variance"] / by_value["expected"]), 1) if by_value["expected"] else None}
