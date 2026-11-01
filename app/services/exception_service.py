"""
مرکز استثنا (docs/productivity.md، B1): کارهایی که از روند عادی خارج شده‌اند، با مسئول، مهلت و تاریخچه.

تشخیص (detect) هر ۱۵ دقیقه برای هر سازمان اجرا می‌شود و دکمه «بررسی دوباره» هم آن را صدا می‌زند:
  - برای هر مورد فقط یک استثنای باز هست (ایندکس یکتای جزئی)؛ تکرار تشخیص مورد تازه نمی‌سازد.
  - موردی که دیگر صادق نیست خودکار «حل‌شده (سیستم)» می‌شود.
  - موردی که کاربر بسته دوباره باز نمی‌شود؛ تصمیم انسان نسبت به تشخیص خودکار اولویت دارد.
  - مورد تازه در یک اعلان خلاصه به هر انبار خبر داده می‌شود، نه یک اعلان برای هر مورد.

آستانه‌ها طبق تصمیم ۷ سند ثابت در کد هستند. این‌ها با داده فعلی قابل تشخیص نیستند: تأخیر واقعی در مسیر و خرابی
خودرو (GPS نداریم)، و مهلت پاسخ تیکت بر اساس SLA زمانی (SLA تعریف نشده است).
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.iran import fa_digits
from app.core.wms import PENDING
from app.models import (
    ACTIVE_ORDER_STATUSES, DriverProfile, Inventory, Order, StockMovement, Stocktake, StocktakeLine, Ticket, User,
)
from app.models_fulfillment import Backorder, PickLine, TransferOrder
from app.models_operations import InboundReceipt, InboundReceiptLine, PutawayTask
from app.models_productivity import ACTIVE_EXCEPTION_STATUSES, OperationException, OperationExceptionEvent
from app.services import assignee_service, dispatch_service, eta_service, notification_service
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError

STAFF = ("org_admin", "warehouse_manager")
UNASSIGNED_SOON = timedelta(hours=2)
FAILED_UNRESOLVED = timedelta(hours=2)
BACKORDER_OPEN = timedelta(hours=24)
QUARANTINE_STUCK = timedelta(hours=48)
TRANSFER_OVERDUE = timedelta(hours=48)
TICKET_WAITING = timedelta(hours=8)
DISCREPANCY_WINDOW = timedelta(days=30)

KINDS = {
    "order_unassigned_soon": ("سفارش بی‌خودرو نزدیک بازه تحویل", "fleet", "high", "برای سفارش خودرو تعیین کنید."),
    "order_at_risk": ("سفارش در خطر تأخیر", "fleet", "high", "با راننده هماهنگ کنید یا زمان تازه را به مشتری خبر دهید."),
    "order_failed_unresolved": ("تحویل ناموفق بی‌تکلیف", "fleet", "high", "تحویل دوباره، برگشت به انبار یا اختلاف را ثبت کنید."),
    "backorder_open": ("سفارش معوق باز", "warehouse", "medium", "موجودی را تأمین یا معوق را تعیین تکلیف کنید."),
    "receipt_discrepancy": ("مغایرت رسید", "warehouse", "medium", "مغایرت را با تأمین‌کننده پیگیری کنید."),
    "quarantine_stuck": ("کالای مانده در قرنطینه یا بازرسی", "warehouse", "medium", "بازرسی را انجام دهید و کالا را تعیین تکلیف کنید."),
    "putaway_problem": ("مشکل در جانمایی", "warehouse", "medium", "مقصد تازه انتخاب کنید یا مشکل محل را رفع کنید."),
    "pick_short": ("کسری برداشت", "warehouse", "high", "موجودی محل را بررسی و برداشت را از محل دیگر تکمیل کنید."),
    "transfer_overdue": ("انتقال دیرکرده", "warehouse", "medium", "رسیدن کالا را با انبار مقصد پیگیری کنید."),
    "driver_ineligible": ("راننده یا خودرو دیگر واجد شرایط نیست", "fleet", "critical", "سفارش را به راننده دیگری بسپارید."),
    "ticket_escalated_waiting": ("تیکت ارجاع‌شده منتظر پاسخ", "support", "medium", "با پشتیبانی پسینه پیگیری کنید."),
    "stocktake_variance": ("انبارگردانی با اختلاف منتظر تأیید", "management", "medium", "اختلاف‌ها را بررسی و تأیید کنید."),
}
TEAM_LABELS = {"warehouse": "انبار", "fleet": "ناوگان", "support": "پشتیبانی", "management": "مدیریت"}
SEVERITY_LABELS = {"low": "کم", "medium": "متوسط", "high": "زیاد", "critical": "بحرانی"}
STATUS_LABELS = {"open": "باز", "in_progress": "در حال رسیدگی", "waiting": "منتظر", "resolved": "حل‌شده", "merged": "ادغام‌شده"}
URGENT = ("high", "critical")
LIST_LIMIT = 500


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hours(delta: timedelta) -> str:
    return fa_digits(str(int(delta.total_seconds() // 3600)))


@dataclass
class Found:
    kind: str
    entity_type: str
    entity_id: int
    warehouse_id: int | None
    reason: str
    due_at: datetime | None = None


def _orders(db: Session, now: datetime) -> list[Found]:
    found = []
    for o in db.query(Order).filter(Order.status == "pending", Order.delivery_window_start <= now + UNASSIGNED_SOON).all():
        found.append(Found("order_unassigned_soon", "order", o.id, o.warehouse_id,
                           f"سفارش {o.tracking_code} هنوز خودرو ندارد و بازه تحویلش تا {_hours(UNASSIGNED_SOON)} ساعت دیگر شروع می‌شود.",
                           o.delivery_window_start))
    at_risk = eta_service.at_risk_ids(db, now)
    for o in db.query(Order).filter(Order.id.in_(at_risk or [-1])).all():
        info = eta_service.estimate(db, o, now=now)
        found.append(Found("order_at_risk", "order", o.id, o.warehouse_id,
                           f"سفارش {o.tracking_code}: {info['reason'] if info else 'برآورد رسیدن بعد از پایان بازه است'}.", o.delivery_window_end))
    for o in db.query(Order).filter(Order.status == "failed", Order.failure_resolution.is_(None)).all():
        if (o.updated_at or now) <= now - FAILED_UNRESOLVED:
            found.append(Found("order_failed_unresolved", "order", o.id, o.warehouse_id,
                               f"تحویل سفارش {o.tracking_code} ناموفق بود و بیش از {_hours(FAILED_UNRESOLVED)} ساعت بی‌تکلیف مانده است.",
                               now))
    active = db.query(Order).filter(Order.status.in_(ACTIVE_ORDER_STATUSES), Order.driver_id.is_not(None)).all()
    driver_ids = {o.driver_id for o in active}
    drivers = {u.id: u for u in db.query(User).filter(User.id.in_(driver_ids or {-1})).all()}
    profiles = {p.user_id: p for p in db.query(DriverProfile).filter(DriverProfile.user_id.in_(driver_ids or {-1})).all()}
    today = dispatch_service.to_local(now).date()
    for o in active:
        driver, profile = drivers.get(o.driver_id), profiles.get(o.driver_id)
        problem = None
        if driver is None or driver.is_active is False:
            problem = "حساب راننده غیرفعال است"
        elif driver.driver_status != "approved":
            problem = "راننده دیگر تأییدشده نیست"
        elif profile is not None and profile.inspection_expiry and profile.inspection_expiry < today:
            problem = "معاینه فنی خودروی راننده منقضی شده است"
        if problem:
            found.append(Found("driver_ineligible", "order", o.id, o.warehouse_id, f"سفارش {o.tracking_code}: {problem}.", o.delivery_window_start))
    return found


def _warehouse(db: Session, now: datetime) -> list[Found]:
    found = []
    for b in db.query(Backorder).filter(Backorder.status == "open", Backorder.created_at <= now - BACKORDER_OPEN).all():
        found.append(Found("backorder_open", "backorder", b.id, b.warehouse_id,
                           f"سفارش معوق بیش از {_hours(BACKORDER_OPEN)} ساعت باز مانده است ({fa_digits(str(b.quantity))} عدد).", b.due_at))
    receipts = db.query(InboundReceipt).filter(
        InboundReceipt.status == "closed", InboundReceipt.closed_at >= now - DISCREPANCY_WINDOW,
        InboundReceipt.id.in_(db.query(InboundReceiptLine.receipt_id).filter(InboundReceiptLine.discrepancy_type.is_not(None)))).all()
    for r in receipts:
        found.append(Found("receipt_discrepancy", "receipt", r.id, r.warehouse_id, f"رسید {r.code} با مغایرت بسته شده است."))
    stuck = db.query(Inventory).filter(Inventory.stock_status.in_(("quarantine", PENDING)), Inventory.quantity > 0).all()
    if stuck:
        rows = db.query(StockMovement.inventory_id, StockMovement.created_at).filter(
            StockMovement.inventory_id.in_([i.id for i in stuck])).all()
        last: dict[int, datetime] = {}
        for inventory_id, at in rows:
            last[inventory_id] = max(at, last.get(inventory_id, at))
        for inv in stuck:
            if last.get(inv.id, now) <= now - QUARANTINE_STUCK:
                found.append(Found("quarantine_stuck", "inventory", inv.id, inv.warehouse_id,
                                   f"{fa_digits(str(inv.quantity))} عدد کالا بیش از {_hours(QUARANTINE_STUCK)} ساعت در قرنطینه یا منتظر بازرسی مانده است."))
    for t in db.query(PutawayTask).filter(PutawayTask.status.in_(("open", "partial")), PutawayTask.last_problem.is_not(None)).all():
        found.append(Found("putaway_problem", "putaway", t.id, t.warehouse_id, f"وظیفه {t.code} با مشکل گزارش شده است: {t.last_error or t.last_problem}."))
    shorts = db.query(PickLine).join(Order, Order.id == PickLine.order_id).filter(
        PickLine.status == "short", Order.status.in_(ACTIVE_ORDER_STATUSES)).all()
    for line in shorts:
        found.append(Found("pick_short", "pick_line", line.id, line.warehouse_id, f"کسری برداشت: {line.short_reason or 'بدون توضیح'}."))
    for t in db.query(TransferOrder).filter(TransferOrder.status == "in_transit", TransferOrder.shipped_at <= now - TRANSFER_OVERDUE).all():
        found.append(Found("transfer_overdue", "transfer", t.id, t.to_warehouse_id, f"انتقال {t.code} بیش از {_hours(TRANSFER_OVERDUE)} ساعت در راه است."))
    return found


def _others(db: Session, now: datetime) -> list[Found]:
    found = []
    tickets = db.query(Ticket).filter(Ticket.escalated_at.is_not(None), Ticket.status == "open",
                                      Ticket.last_activity_at <= now - TICKET_WAITING).all()
    for t in tickets:
        found.append(Found("ticket_escalated_waiting", "ticket", t.id, None, f"تیکت {t.code} ارجاع شده و بیش از {_hours(TICKET_WAITING)} ساعت بی‌پاسخ مانده است."))
    # زیرپرس‌وجو به‌جای DISTINCT: جدول ستون JSON دارد و PostgreSQL روی آن DISTINCT نمی‌زند
    reviews = db.query(Stocktake).filter(Stocktake.status == "review", Stocktake.id.in_(
        db.query(StocktakeLine.stocktake_id).filter(StocktakeLine.counted_qty != StocktakeLine.expected_qty))).all()
    for s in reviews:
        found.append(Found("stocktake_variance", "stocktake", s.id, s.warehouse_id, f"انبارگردانی {s.code} اختلاف دارد و منتظر تأیید است."))
    return found


def _add_event(db: Session, item: OperationException, actor: User | None, action: str, note: str | None = None) -> None:
    db.add(OperationExceptionEvent(organization_id=item.organization_id, exception_id=item.id, actor_id=actor.id if actor else None,
                                   action=action[:120], note=note, at=_now()))


def detect(db: Session, organization_id: int, now: datetime | None = None) -> dict:
    """همه انواع را بررسی می‌کند و باز/بسته می‌کند؛ commit می‌زند."""
    now = now or _now()
    found = {(f.kind, f.entity_type, f.entity_id): f for f in _orders(db, now) + _warehouse(db, now) + _others(db, now)}
    active = db.query(OperationException).filter(OperationException.status.in_(ACTIVE_EXCEPTION_STATUSES)).all()
    active_keys = {(e.kind, e.entity_type, e.entity_id) for e in active}
    decided = {(e.kind, e.entity_type, e.entity_id) for e in db.query(OperationException).filter(
        OperationException.status.in_(("resolved", "merged")), OperationException.resolved_by_id.is_not(None)).all()}

    closed = 0
    for item in active:
        if (item.kind, item.entity_type, item.entity_id) not in found:
            item.status, item.closed_at, item.resolution = "resolved", now, "رفع خودکار: شرط دیگر برقرار نیست."
            _add_event(db, item, None, "حل‌شده (سیستم)")
            closed += 1

    created: dict[int | None, int] = {}
    for key, f in found.items():
        if key in active_keys or key in decided:
            continue
        _, team, severity, action = KINDS[f.kind]
        try:
            with db.begin_nested():       # اجرای هم‌زمان: ایندکس یکتا مورد تکراری را رد می‌کند
                item = OperationException(
                    organization_id=organization_id, kind=f.kind, entity_type=f.entity_type, entity_id=f.entity_id,
                    warehouse_id=f.warehouse_id, severity=severity, team=team, status="open", opened_at=now, due_at=f.due_at,
                    trigger_reason=f.reason[:300], suggested_action=action)
                db.add(item)
                db.flush()
                _add_event(db, item, None, "ثبت خودکار")
        except IntegrityError:
            continue
        created[f.warehouse_id] = created.get(f.warehouse_id, 0) + 1

    for warehouse_id, count in created.items():
        notification_service.notify(
            db, organization_id=organization_id, kind="exception_opened", title="استثنای تازه در عملیات",
            message=f"{fa_digits(str(count))} مورد تازه از روند عادی خارج شده و مسئول می‌خواهد.", link="/app/exceptions?status=active",
            warehouse_id=warehouse_id, dedupe_key=f"exceptions:{warehouse_id or 'org'}")
    db.commit()
    return {"found": len(found), "created": sum(created.values()), "closed": closed}


# ---------------------------------------------------------------------------
# فهرست و رسیدگی
# ---------------------------------------------------------------------------
def _link(item: OperationException) -> str | None:
    return {
        "order": f"/app/orders?order={item.entity_id}", "backorder": "/app/backorders", "receipt": f"/app/receipts?receipt={item.entity_id}",
        "inventory": "/app/quality", "putaway": "/app/putaway", "pick_line": "/app/picking", "transfer": "/app/transfers?status=in_transit",
        "ticket": f"/app/tickets/{item.entity_id}", "stocktake": "/app/stocktakes",
    }.get(item.entity_type)


def _ensure_staff(user: User) -> None:
    if user.role not in STAFF:
        raise ForbiddenError("فقط کارکنان سازمان به مرکز استثنا دسترسی دارند.")


def _scoped(query, user: User):
    """مدیر انبار فقط استثناهای انبار خودش را می‌بیند؛ موردهای بدون انبار (پشتیبانی) برای ادمین است."""
    return query.filter(OperationException.warehouse_id == user.warehouse_id) if user.role == "warehouse_manager" else query


def _serialize(db: Session, item: OperationException, names: dict[int, str], suggest) -> dict:
    label, _, _, _ = KINDS.get(item.kind, (item.kind, None, None, None))
    return {
        "id": item.id, "kind": item.kind, "kind_label": label, "entity_type": item.entity_type, "entity_id": item.entity_id,
        "warehouse_id": item.warehouse_id, "severity": item.severity, "severity_label": SEVERITY_LABELS[item.severity],
        "team": item.team, "team_label": TEAM_LABELS[item.team], "owner_id": item.owner_id, "owner_name": names.get(item.owner_id),
        "status": item.status, "status_label": STATUS_LABELS[item.status], "opened_at": item.opened_at, "due_at": item.due_at,
        "closed_at": item.closed_at, "overdue": bool(item.due_at and item.due_at < _now() and item.status in ACTIVE_EXCEPTION_STATUSES),
        "trigger_reason": item.trigger_reason, "suggested_action": item.suggested_action, "resolution": item.resolution,
        "merged_into_id": item.merged_into_id, "link": _link(item),
        "suggested_owner": suggest(item) if item.owner_id is None and item.status in ACTIVE_EXCEPTION_STATUSES else None,
    }


def _people(db: Session, ids) -> dict[int, str]:
    ids = {i for i in ids if i}
    return {u.id: u.full_name or u.username for u in db.query(User).filter(User.id.in_(ids)).all()} if ids else {}


def list_exceptions(db: Session, user: User, *, status: str = "active", team: str | None = None, severity: str | None = None,
                    urgent: bool = False, owner_id: int | None = None, kind: str | None = None) -> list[dict]:
    _ensure_staff(user)
    query = _scoped(db.query(OperationException), user)
    if status == "active":
        query = query.filter(OperationException.status.in_(ACTIVE_EXCEPTION_STATUSES))
    elif status != "all":
        query = query.filter(OperationException.status == status)
    if team:
        query = query.filter(OperationException.team == team)
    if severity:
        query = query.filter(OperationException.severity == severity)
    if urgent:
        query = query.filter(OperationException.severity.in_(URGENT))
    if owner_id:
        query = query.filter(OperationException.owner_id == owner_id)
    if kind:
        query = query.filter(OperationException.kind == kind)
    items = query.order_by(OperationException.opened_at.desc(), OperationException.id.desc()).limit(LIST_LIMIT).all()
    names = _people(db, [i.owner_id for i in items])
    suggest = assignee_service.exception_suggester(db)
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    items.sort(key=lambda i: (i.status not in ACTIVE_EXCEPTION_STATUSES, rank.get(i.severity, 9)))
    return [_serialize(db, i, names, suggest) for i in items]


def _get(db: Session, user: User, exception_id: int) -> OperationException:
    _ensure_staff(user)
    item = _scoped(db.query(OperationException), user).filter(OperationException.id == exception_id).first()
    if item is None:
        raise NotFoundError("این استثنا یافت نشد.")
    return item


def get_exception(db: Session, user: User, exception_id: int) -> dict:
    item = _get(db, user, exception_id)
    events = db.query(OperationExceptionEvent).filter(OperationExceptionEvent.exception_id == item.id) \
        .order_by(OperationExceptionEvent.id).all()
    names = _people(db, [item.owner_id] + [e.actor_id for e in events])
    return {**_serialize(db, item, names, assignee_service.exception_suggester(db)),
            "events": [{"at": e.at, "actor": names.get(e.actor_id) or "سیستم", "action": e.action, "note": e.note} for e in events]}


def update(db: Session, user: User, exception_id: int, data) -> dict:
    """تعیین مسئول، تغییر وضعیت، یادداشت، ادغام. بستن و ادغام نتیجه می‌خواهد و هر تغییر در تاریخچه می‌ماند."""
    item = _get(db, user, exception_id)
    if item.status not in ACTIVE_EXCEPTION_STATUSES:
        raise ConflictError("این استثنا بسته شده است.")
    fields = data.model_fields_set
    actions = []
    if "owner_id" in fields:
        if data.owner_id is not None:
            owner = db.get(User, data.owner_id)
            if owner is None or owner.role not in STAFF or owner.is_active is False:
                raise ConflictError("مسئول باید از کارکنان فعال سازمان باشد.")
            actions.append(f"مسئول: {owner.full_name or owner.username}")
        else:
            actions.append("مسئول برداشته شد")
        item.owner_id = data.owner_id
    if data.merged_into_id is not None:
        target = _get(db, user, data.merged_into_id)
        if target.id == item.id or target.status not in ACTIVE_EXCEPTION_STATUSES:
            raise ConflictError("فقط در یک استثنای باز دیگر می‌توان ادغام کرد.")
        item.status, item.merged_into_id, item.closed_at, item.resolved_by_id = "merged", target.id, _now(), user.id
        actions.append(f"ادغام در #{target.id}")
    elif data.status:
        if data.status == "resolved":
            if not (data.resolution or "").strip():
                raise ConflictError("برای بستن، نتیجه را بنویسید.")
            item.resolution, item.closed_at, item.resolved_by_id = data.resolution.strip(), _now(), user.id
        item.status = data.status
        actions.append(f"وضعیت: {STATUS_LABELS[data.status]}")
    if not actions and not data.note:
        raise ConflictError("تغییری ثبت نشد.")
    _add_event(db, item, user, "؛ ".join(actions) or "یادداشت", data.note)
    db.commit()
    return get_exception(db, user, item.id)


def scan(db: Session, user: User) -> dict:
    _ensure_staff(user)
    return detect(db, user.organization_id)


def active_for_order(db: Session, order_id: int) -> list[OperationException]:
    return db.query(OperationException).filter(
        OperationException.entity_type == "order", OperationException.entity_id == order_id).order_by(OperationException.id).all()
