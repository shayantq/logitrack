"""
انبارگردانی دوره‌ای (مرحله ۱۲).

گردش کار: ایجاد (کامل یا بخشی از کالاها) ← شمارش کور توسط مدیر انبار ← ارسال برای بررسی ←
ادمین مغایرت‌ها را می‌بیند، برای اقلام مشکوک شمارش مجدد می‌خواهد ← تأیید ← اصلاح موجودی با گردش «انبارگردانی».

- شمارش کور: موجودی سیستم تا مرحله بررسی به هیچ‌کس نشان داده نمی‌شود (حتی ادمین)، تا عدد سیستم کپی نشود.
- عملیات انبار متوقف نمی‌شود: موجودی سیستم «در لحظه شمارش هر قلم» ذخیره می‌شود و اصلاح نهایی برابر
  (شمرده‌شده − همان عدد) است؛ گردش‌های بعد از شمارش دست نمی‌خورند.
- در هر انبار فقط یک انبارگردانی فعال.
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.iran import fa_digits
from app.models import Inventory, Product, Stocktake, StocktakeLine, User, Warehouse
from app.services import notification_service, stock_ledger
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError

ACTIVE = ("counting", "review")
REASON_LABELS = {
    "damage": "خرابی و آسیب", "loss": "مفقودی یا سرقت", "entry_error": "خطای ثبت قبلی",
    "unrecorded": "ورود/خروج ثبت‌نشده", "unknown": "نامشخص",
}


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


def _ensure_admin(user: User) -> None:
    if _role(user) != "org_admin":
        raise ForbiddenError("بررسی و تأیید انبارگردانی با ادمین سازمان است.")


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
    query = db.query(Inventory).filter(Inventory.product_id == product_id, Inventory.warehouse_id == warehouse_id)
    if lock:
        query = query.with_for_update()
    return query.order_by(Inventory.id).first()


def _names(db: Session, ids: set[int | None]) -> dict[int, str]:
    ids = {i for i in ids if i}
    return {u.id: u.full_name or u.username for u in db.query(User).filter(User.id.in_(ids or {-1})).all()}


# ---------------------------------------------------------------------------
# خروجی
# ---------------------------------------------------------------------------
def _summary(st: Stocktake, warehouse_names: dict[int, str]) -> dict:
    counted = sum(1 for l in st.lines if l.counted_qty is not None)
    return {
        "id": st.id, "code": st.code, "title": st.title, "scope": st.scope, "status": st.status,
        "warehouse_id": st.warehouse_id, "warehouse_name": warehouse_names.get(st.warehouse_id, ""),
        "created_at": st.created_at, "submitted_at": st.submitted_at, "approved_at": st.approved_at,
        "lines_total": len(st.lines), "lines_counted": counted,
    }


def detail(db: Session, user: User, stocktake_id: int) -> dict:
    st = _load(db, user, stocktake_id)
    return _detail(db, user, st)


def _detail(db: Session, user: User, st: Stocktake) -> dict:
    admin = _role(user) == "org_admin"
    reveal = admin and st.status in ("review", "approved")       # شمارش کور: عدد سیستم فقط هنگام بررسی
    warehouse = db.get(Warehouse, st.warehouse_id)
    names = _names(db, {l.counted_by_id for l in st.lines} | {st.created_by_id, st.submitted_by_id, st.approved_by_id})
    lines, totals = [], {"variance_lines": 0, "shortage_qty": 0, "surplus_qty": 0, "shortage_value": 0.0, "surplus_value": 0.0}
    for l in st.lines:
        row = {
            "id": l.id, "product_id": l.product_id, "product_name": l.product_name, "product_sku": l.product_sku,
            "added_during_count": l.added_during_count, "counted_qty": l.counted_qty, "counted_at": l.counted_at,
            "counted_by": names.get(l.counted_by_id), "previous_count": l.previous_count, "recount_note": l.recount_note,
            "expected_qty": None, "variance": None, "variance_value": None, "variance_reason": l.variance_reason,
            "adjustment": l.adjustment,
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
    can_count = st.status == "counting" and (admin or user.warehouse_id == st.warehouse_id)
    counters = {l.counted_by_id for l in st.lines if l.counted_by_id}
    data.update(
        note=st.note, lines=lines, revealed=reveal,
        created_by=names.get(st.created_by_id), submitted_by=names.get(st.submitted_by_id), approved_by=names.get(st.approved_by_id),
        accuracy=round(100 * (counted - totals["variance_lines"]) / counted, 1) if reveal and counted else None,
        **({k: (round(v) if isinstance(v, float) else v) for k, v in totals.items()} if reveal else
           {k: None for k in totals}),
        can_count=can_count,
        can_submit=can_count and counted == len(st.lines) and len(st.lines) > 0,
        can_review=admin and st.status == "review",
        can_cancel=admin and st.status in ACTIVE,
        # تفکیک وظایف: هشدار وقتی تأییدکننده خودش هم شمرده است
        self_review=admin and st.status == "review" and user.id in counters,
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
    """وضعیت انبارگردانی هر انبار: آخرین انبارگردانی، دوره، سررسید و انبارگردانی فعال."""
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
            "items": db.query(Inventory).filter(Inventory.warehouse_id == w.id).count(),
        })
    return result


def summary(db: Session, user: User) -> dict:
    """نشان منو: مدیر انبار ← انبارگردانی‌های در حال شمارش؛ ادمین ← منتظر بررسی + سررسیدگذشته."""
    _ensure_staff(user)
    if _role(user) == "warehouse_manager":
        return {"count": db.query(Stocktake).filter(Stocktake.warehouse_id == user.warehouse_id, Stocktake.status == "counting").count()}
    review = db.query(Stocktake).filter(Stocktake.status == "review").count()
    overdue = sum(1 for w in overview(db, user) if w["overdue"])
    return {"count": review + overdue}


# ---------------------------------------------------------------------------
# ایجاد و شمارش
# ---------------------------------------------------------------------------
def create(db: Session, user: User, *, warehouse_id: int, scope: str, product_ids: list[int] | None,
           title: str | None, note: str | None) -> dict:
    _ensure_staff(user)
    warehouse = db.get(Warehouse, warehouse_id)
    if warehouse is None:
        raise NotFoundError("انبار یافت نشد.")
    _warehouse_allowed(user, warehouse_id)
    if db.query(Stocktake).filter(Stocktake.warehouse_id == warehouse_id, Stocktake.status.in_(ACTIVE)).first():
        raise ConflictError(f"برای «{warehouse.name}» یک انبارگردانی فعال وجود دارد؛ ابتدا آن را تمام یا لغو کنید.")
    if scope == "full":
        products = [inv.product for inv in db.query(Inventory).filter(Inventory.warehouse_id == warehouse_id)
                    .order_by(Inventory.id).all() if inv.product is not None]
    else:
        if not product_ids:
            raise ConflictError("برای انبارگردانی بخشی، دست‌کم یک کالا انتخاب کنید.")
        products = db.query(Product).filter(Product.id.in_(set(product_ids))).order_by(Product.name).all()
        if len(products) != len(set(product_ids)):
            raise NotFoundError("بعضی از کالاهای انتخاب‌شده یافت نشدند.")
    if not products:
        raise ConflictError("این انبار کالایی برای شمارش ندارد.")
    st = Stocktake(organization_id=warehouse.organization_id, code=_new_code(db), warehouse_id=warehouse_id, scope=scope,
                   title=(title or "").strip() or f"انبارگردانی {warehouse.name}", note=(note or "").strip() or None,
                   status="counting", created_by_id=user.id)
    db.add(st)
    db.flush()
    seen = set()
    for p in products:
        if p.id in seen:
            continue
        seen.add(p.id)
        inv = _inventory(db, p.id, warehouse_id)
        db.add(StocktakeLine(organization_id=st.organization_id, stocktake_id=st.id, product_id=p.id,
                             inventory_id=inv.id if inv else None, product_name=p.name, product_sku=p.sku, unit_price=p.price or 0))
    db.commit()
    db.refresh(st)
    return _detail(db, user, st)


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
    inv = _inventory(db, line.product_id, st.warehouse_id)
    # موجودی سیستم در همین لحظه — مبنای مغایرت (به شمارنده نمایش داده نمی‌شود)
    line.counted_qty, line.expected_qty = counted_qty, (inv.quantity or 0) if inv else 0
    line.counted_at, line.counted_by_id = _now(), user.id
    if inv is not None:
        line.inventory_id = inv.id
    db.commit()
    db.refresh(st)
    return _detail(db, user, st)


def add_line(db: Session, user: User, stocktake_id: int, product_id: int, counted_qty: int) -> dict:
    """کالایی که در فهرست نبود ولی در انبار پیدا شد."""
    st = _counting(db, user, stocktake_id)
    if any(l.product_id == product_id for l in st.lines):
        raise ConflictError("این کالا از قبل در فهرست شمارش هست.")
    product = db.get(Product, product_id)
    if product is None:
        raise NotFoundError("کالا یافت نشد.")
    inv = _inventory(db, product_id, st.warehouse_id)
    db.add(StocktakeLine(organization_id=st.organization_id, stocktake_id=st.id, product_id=product.id,
                         inventory_id=inv.id if inv else None, product_name=product.name, product_sku=product.sku,
                         unit_price=product.price or 0, added_during_count=True, counted_qty=counted_qty,
                         expected_qty=(inv.quantity or 0) if inv else 0, counted_at=_now(), counted_by_id=user.id))
    db.commit()
    db.refresh(st)
    return _detail(db, user, st)


def submit(db: Session, user: User, stocktake_id: int) -> dict:
    st = _counting(db, user, stocktake_id)
    missing = [l.product_name for l in st.lines if l.counted_qty is None]
    if missing:
        raise ConflictError(f"{fa_digits(str(len(missing)))} قلم هنوز شمرده نشده است (مثلاً «{missing[0]}»).")
    st.status, st.submitted_at, st.submitted_by_id = "review", _now(), user.id
    notification_service.stocktake_event(db, st, "submitted", user)
    db.commit()
    db.refresh(st)
    return _detail(db, user, st)


# ---------------------------------------------------------------------------
# بررسی و تأیید (ادمین)
# ---------------------------------------------------------------------------
def _review(db: Session, user: User, stocktake_id: int) -> Stocktake:
    _ensure_admin(user)
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
    db.commit()
    db.refresh(st)
    return _detail(db, user, st)


def approve(db: Session, user: User, stocktake_id: int, reasons: dict[int, str]) -> dict:
    st = _review(db, user, stocktake_id)
    for l in st.lines:
        variance = (l.counted_qty or 0) - (l.expected_qty or 0)
        if variance == 0:
            l.adjustment = 0
            continue
        l.variance_reason = reasons.get(l.id) or "unknown"
        inv = _inventory(db, l.product_id, st.warehouse_id, lock=True)
        if inv is None:
            inv = Inventory(organization_id=st.organization_id, product_id=l.product_id, warehouse_id=st.warehouse_id, quantity=0)
            db.add(inv)
            db.flush()
        # اگر بعد از شمارش کالا خارج شده و اصلاح منفی به زیر صفر می‌رسد، فقط تا صفر اصلاح می‌شود
        change = max(variance, -(inv.quantity or 0))
        if change:
            stock_ledger.record(db, inv, change, "stocktake", user=user,
                                reason=f"انبارگردانی {st.code}: {REASON_LABELS.get(l.variance_reason, l.variance_reason)}",
                                reference_type="stocktake", reference_id=st.id)
        l.adjustment, l.inventory_id = change, inv.id
    st.status, st.approved_at, st.approved_by_id = "approved", _now(), user.id
    notification_service.stocktake_event(db, st, "approved", user)
    db.commit()
    db.refresh(st)
    return _detail(db, user, st)


def cancel(db: Session, user: User, stocktake_id: int) -> dict:
    _ensure_admin(user)
    st = _load(db, user, stocktake_id)
    if st.status not in ACTIVE:
        raise ConflictError("فقط انبارگردانی در حال انجام لغو می‌شود.")
    st.status, st.canceled_at = "canceled", _now()
    db.commit()
    db.refresh(st)
    return _detail(db, user, st)


def set_interval(db: Session, user: User, warehouse_id: int, days: int | None) -> list[dict]:
    _ensure_admin(user)
    warehouse = db.get(Warehouse, warehouse_id)
    if warehouse is None:
        raise NotFoundError("انبار یافت نشد.")
    warehouse.stocktake_interval_days = days
    db.commit()
    return overview(db, user)
