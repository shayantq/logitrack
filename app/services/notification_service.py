"""
لایه سرویس اعلان‌ها

  • notify(): ساخت اعلان برای یک رویداد سیستم (کمبود موجودی، سفارش ناموفق/منقضی، تیکت، انبارگردانی،
    درخواست‌ها و پرونده رانندگان، امتیاز پایین...) — هر اعلان عنوان، توضیح، جزئیات کوتاه و مسیر صفحه مقصد دارد
  • خواندن/بستن اعلان برای هر کاربر جداگانه (NotificationReceipt)
  • توابع رویداد (low_stock, order_event, ...) که از سرویس‌های دیگر صدا زده می‌شوند

اعلان در همان تراکنشِ رویداد ثبت می‌شود؛ اگر عملیات اصلی rollback شود، اعلانش هم ثبت نمی‌شود.
"""
from datetime import timedelta

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core.iran import fa_date, fa_digits
from app.models import Inventory, Order, Stocktake, Ticket, User
from app.models_notification import Notification, NotificationReceipt, _now
from app.services.exceptions import ForbiddenError, NotFoundError

# نوع اعلان ← (دسته برای فیلتر/آیکن پنل، شدت پیش‌فرض)
KINDS = {
    "low_stock": ("inventory", "warning"),
    "out_of_stock": ("inventory", "danger"),
    "order_failed": ("orders", "danger"),
    "order_expired": ("orders", "warning"),
    "order_assigned": ("orders", "info"),
    "ticket_new": ("tickets", "info"),
    "ticket_reply": ("tickets", "info"),
    "stocktake_review": ("stocktakes", "info"),
    "stocktake_recount": ("stocktakes", "warning"),
    "stocktake_approved": ("stocktakes", "success"),
    "driver_application": ("drivers", "info"),
    "driver_request": ("drivers", "info"),
    "application_result": ("drivers", "success"),
    "request_result": ("drivers", "success"),
    "low_rating": ("drivers", "danger"),
}
RETENTION_DAYS = 90
LIST_LIMIT = 60
DEFAULT_REORDER_POINT = 10          # همان پیش‌فرض بررسی دوره‌ای قبلی


def fa_num(value) -> str:
    if isinstance(value, float):
        value = round(value, 1)
        value = int(value) if value == int(value) else value
    return fa_digits(f"{value:,}")


def _local_time(value) -> str:
    from app.services import dispatch_service          # جلوگیری از import چرخه‌ای
    local = dispatch_service.to_local(dispatch_service.to_utc_naive(value))
    return f"{fa_date(local)} ساعت {fa_digits(local.strftime('%H:%M'))}"


def _preview(text: str | None, limit: int = 140) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _name(user: User | None) -> str | None:
    if user is None:
        return None
    return user.full_name or user.username


# ---------------------------------------------------------------------------
# ساخت اعلان
# ---------------------------------------------------------------------------
def notify(db: Session, *, organization_id: int, kind: str, title: str, message: str, link: str | None = None,
           severity: str | None = None, details: list[tuple[str, object]] | None = None,
           warehouse_id: int | None = None, product_id: int | None = None, audience: str = "staff",
           user_id: int | None = None, dedupe_key: str | None = None, actor: User | None = None) -> Notification:
    """
    actor: کسی که خودش رویداد را انجام داده — اعلان برای او نمایش داده نمی‌شود.
    dedupe_key: اگر اعلانی با همین کلید هست، همان تازه و برای همه دوباره «خوانده‌نشده» می‌شود.
    """
    note = None
    if dedupe_key:
        note = db.query(Notification).filter(Notification.organization_id == organization_id,
                                              Notification.dedupe_key == dedupe_key).first()
    if note is None:
        note = Notification(organization_id=organization_id, dedupe_key=dedupe_key)
        db.add(note)
    elif note.id is not None:
        db.query(NotificationReceipt).filter(NotificationReceipt.notification_id == note.id).delete(synchronize_session=False)
    note.kind, note.title, note.message, note.link = kind, title, message, link
    note.severity = severity or KINDS.get(kind, ("system", "info"))[1]
    note.details = [{"label": label, "value": str(value)} for label, value in (details or []) if value not in (None, "")] or None
    note.warehouse_id, note.product_id = warehouse_id, product_id
    note.audience, note.user_id = ("user", user_id) if user_id else (audience, None)
    note.created_at = _now()
    if actor is not None and actor.organization_id == organization_id:
        db.flush()
        now = _now()
        db.add(NotificationReceipt(organization_id=organization_id, notification_id=note.id, user_id=actor.id,
                                   read_at=now, dismissed_at=now))
    return note


# ---------------------------------------------------------------------------
# خواندن / بستن (برای هر کاربر)
# ---------------------------------------------------------------------------
def _visible(query, user: User):
    own = Notification.user_id == user.id
    shared = Notification.user_id.is_(None)
    if user.role == "org_admin":
        return query.filter(or_(own, and_(shared, Notification.audience.in_(("staff", "admin")))))
    if user.role == "warehouse_manager":
        warehouse = (or_(Notification.warehouse_id.is_(None), Notification.warehouse_id == user.warehouse_id)
                     if user.warehouse_id else Notification.warehouse_id.is_(None))
        return query.filter(or_(own, and_(shared, Notification.audience == "staff", warehouse)))
    if user.role == "driver":
        return query.filter(own)
    raise ForbiddenError("شما مجوز مشاهده این اعلان‌ها را ندارید.")


def _rows(db: Session, user: User):
    query = db.query(Notification, NotificationReceipt).outerjoin(
        NotificationReceipt,
        and_(NotificationReceipt.notification_id == Notification.id, NotificationReceipt.user_id == user.id),
    )
    return _visible(query, user).filter(NotificationReceipt.dismissed_at.is_(None))


def serialize(note: Notification, receipt: NotificationReceipt | None) -> dict:
    category = KINDS.get(note.kind, ("system", "info"))[0]
    link = note.link or (f"/app/inventory?product={note.product_id}" if note.product_id else None)
    return {
        "id": note.id, "kind": note.kind, "category": category, "severity": note.severity,
        "title": note.title or ("هشدار موجودی" if category == "inventory" else "اعلان"),
        "message": note.message, "link": link, "details": note.details or [], "created_at": note.created_at,
        "is_read": receipt is not None and receipt.read_at is not None,
        "product_id": note.product_id, "warehouse_id": note.warehouse_id,
    }


def list_for(db: Session, user: User, unread_only: bool = False, limit: int = LIST_LIMIT) -> dict:
    query = _rows(db, user)
    unread = query.filter(NotificationReceipt.read_at.is_(None))
    unread_count = unread.count()
    rows = (unread if unread_only else query).order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit).all()
    return {"items": [serialize(n, r) for n, r in rows], "unread_count": unread_count}


def _one(db: Session, user: User, notification_id: int) -> tuple[Notification, NotificationReceipt]:
    note = _visible(db.query(Notification).filter(Notification.id == notification_id), user).first()
    if note is None:
        raise NotFoundError("اعلان مورد نظر یافت نشد.")
    receipt = db.query(NotificationReceipt).filter(NotificationReceipt.notification_id == note.id,
                                                   NotificationReceipt.user_id == user.id).first()
    if receipt is None:
        receipt = NotificationReceipt(organization_id=note.organization_id, notification_id=note.id, user_id=user.id)
        db.add(receipt)
    return note, receipt


def mark_read(db: Session, user: User, notification_id: int) -> None:
    _, receipt = _one(db, user, notification_id)
    receipt.read_at = receipt.read_at or _now()
    db.commit()


def dismiss(db: Session, user: User, notification_id: int) -> None:
    _, receipt = _one(db, user, notification_id)
    now = _now()
    receipt.read_at, receipt.dismissed_at = receipt.read_at or now, now
    db.commit()


def _bulk(db: Session, user: User, rows, dismiss_too: bool) -> int:
    now = _now()
    for note, receipt in rows:
        if receipt is None:
            receipt = NotificationReceipt(organization_id=note.organization_id, notification_id=note.id, user_id=user.id)
            db.add(receipt)
        receipt.read_at = receipt.read_at or now
        if dismiss_too:
            receipt.dismissed_at = now
    db.commit()
    return len(rows)


def mark_all_read(db: Session, user: User) -> int:
    return _bulk(db, user, _rows(db, user).filter(NotificationReceipt.read_at.is_(None)).all(), dismiss_too=False)


def dismiss_all(db: Session, user: User) -> int:
    return _bulk(db, user, _rows(db, user).all(), dismiss_too=True)


def purge_old(db: Session) -> int:
    cutoff = _now() - timedelta(days=RETENTION_DAYS)
    return db.query(Notification).filter(Notification.created_at < cutoff).delete(synchronize_session=False)


# ---------------------------------------------------------------------------
# رویدادها
# ---------------------------------------------------------------------------
def reorder_point_of(inv: Inventory) -> int:
    return inv.reorder_point if inv.reorder_point is not None else DEFAULT_REORDER_POINT


def low_stock(db: Session, inv: Inventory) -> bool:
    """
    ردیفی که قبلاً بالای نقطه سفارش بوده و حالا به آن رسیده، یک‌بار هشدار می‌گیرد؛
    هشدار بعدی فقط بعد از پر شدن دوباره (low_alerted در دفتر گردش صفر می‌شود).
    """
    stock = inv.quantity or 0
    rop = reorder_point_of(inv)
    if stock > rop or not inv.ever_exceeded_reorder or inv.low_alerted:
        return False
    product = inv.product
    if product is None:
        return False
    inv.low_alerted = True
    unit = product.unit or "عدد"
    warehouse = inv.warehouse
    location = f" در «{warehouse.name}»" if warehouse else ""
    cover = None
    if inv.avg_daily_demand and inv.avg_daily_demand > 0 and stock > 0:
        cover = f"حدود {fa_num(max(1, round(stock / inv.avg_daily_demand)))} روز"
    if stock == 0:
        kind, title = "out_of_stock", "موجودی کالا تمام شد"
        message = f"موجودی کالای «{product.name}»{location} تمام شده است؛ تا خرید بعدی سفارش تازه‌ای از این انبار برای آن ثبت نمی‌شود."
    else:
        kind, title = "low_stock", "کالا به نقطه سفارش رسید"
        message = (f"موجودی کالای «{product.name}»{location} به {fa_num(stock)} {unit} رسیده و رو‌به‌اتمام است؛ "
                   "زمان ثبت سفارش خرید است.")
    notify(db, organization_id=inv.organization_id, kind=kind, title=title, message=message,
           link=f"/app/inventory?product={product.id}", warehouse_id=inv.warehouse_id, product_id=product.id,
           details=[("کد کالا", product.sku), ("انبار", warehouse.name if warehouse else None),
                    ("موجودی فعلی", f"{fa_num(stock)} {unit}"), ("نقطه سفارش", f"{fa_num(rop)} {unit}"),
                    ("پوشش موجودی", cover),
                    ("پیشنهاد خرید", f"{fa_num(inv.suggested_order_qty)} {unit}" if inv.suggested_order_qty else None)])
    return True


def _order_details(db: Session, order: Order) -> list[tuple[str, object]]:
    driver = db.get(User, order.driver_id) if order.driver_id else None
    return [("کد پیگیری", order.tracking_code), ("گیرنده", order.recipient_name),
            ("مقصد", " / ".join(p for p in (order.destination_province, order.destination_city) if p)),
            ("راننده", _name(driver))]


def order_event(db: Session, order: Order, status: str, actor: User | None, note: str | None) -> None:
    """سفارش ناموفق یا منقضی ← ادمین و مدیر انبار مبدأ."""
    if status == "failed":
        kind, title = "order_failed", "تحویل سفارش ناموفق بود"
        message = f"سفارش {order.tracking_code} به «{order.recipient_name or 'گیرنده'}» تحویل داده نشد؛ کالاها به انبار برگشت."
    elif status == "expired":
        kind, title = "order_expired", "سفارش منقضی شد"
        message = f"بازه تحویل سفارش {order.tracking_code} گذشت و سفارش ارسال نشد؛ موجودی به انبار برگشت و خودرو آزاد شد."
    else:
        return
    reason = note if status == "failed" else None
    notify(db, organization_id=order.organization_id, kind=kind, title=title, message=message,
           link=f"/app/orders?order={order.id}", warehouse_id=order.warehouse_id, actor=actor,
           details=_order_details(db, order) + [("علت", _preview(reason, 80) if reason else None)])


def order_assigned(db: Session, order: Order) -> None:
    """سفارش تازه به راننده سپرده شد ← خود راننده."""
    if not order.driver_id:
        return
    notify(db, organization_id=order.organization_id, kind="order_assigned", user_id=order.driver_id,
           title="سفارش تازه به شما سپرده شد",
           message=f"سفارش {order.tracking_code} برای تحویل در {order.destination_city} — {_local_time(order.delivery_window_start)}.",
           link="/app/driver", severity="danger" if order.priority else "info",
           details=[("کد پیگیری", order.tracking_code), ("مقصد", order.destination_address or order.destination_city),
                    ("وزن بار", f"{fa_num(order.total_weight_kg or 0)} کیلوگرم"),
                    ("اولویت", "فوری" if order.priority else None)])


def _ticket_warehouse(db: Session, ticket: Ticket) -> int | None:
    order = db.get(Order, ticket.order_id) if ticket.order_id else None
    return order.warehouse_id if order else None


SOURCE_LABELS = {"customer": "مشتری", "driver": "راننده", "org": "سازمان"}


def ticket_event(db: Session, ticket: Ticket, side: str, body: str, actor: User | None = None, new: bool = False) -> None:
    """
    side: سمت نویسنده پیام (requester / org / platform).
    پیام درخواست‌کننده (مشتری/راننده) ← کارکنان سازمان؛ پاسخ سازمان ← راننده؛ پاسخ پلتفرم ← کاربر سازمانیِ درخواست‌کننده.
    """
    common = dict(organization_id=ticket.organization_id, kind="ticket_new" if new else "ticket_reply", actor=actor)
    details = [("کد تیکت", ticket.code), ("موضوع", _preview(ticket.subject, 60)), ("از طرف", ticket.requester_name)]
    if side == "requester" and ticket.handler == "org":
        title = (f"تیکت تازه از {SOURCE_LABELS.get(ticket.source, '')}" if new else "پیام تازه در تیکت").strip()
        notify(db, **common, title=title, message=_preview(body), link=f"/app/tickets/{ticket.id}",
               severity="danger" if ticket.priority in ("high", "urgent") else "info",
               warehouse_id=_ticket_warehouse(db, ticket), dedupe_key=f"ticket:{ticket.id}", details=details)
    elif side == "org" and ticket.source == "driver" and ticket.requester_user_id:
        notify(db, **common, title="پاسخ تازه به تیکت شما", message=_preview(body), user_id=ticket.requester_user_id,
               link=f"/app/driver/support/{ticket.id}", dedupe_key=f"ticket:{ticket.id}:requester", details=details[:2])
    elif side == "platform" and ticket.source == "org" and ticket.requester_user_id:
        notify(db, **common, title="پاسخ پشتیبانی پسینه", message=_preview(body), user_id=ticket.requester_user_id,
               link=f"/app/tickets/{ticket.id}", dedupe_key=f"ticket:{ticket.id}:requester", details=details[:2])


def stocktake_event(db: Session, st: Stocktake, event: str, actor: User | None, note: str | None = None) -> None:
    from app.models import Warehouse
    warehouse = db.get(Warehouse, st.warehouse_id)
    lines = list(st.lines)
    variance = sum(1 for l in lines if l.counted_qty is not None and l.expected_qty is not None and l.counted_qty != l.expected_qty)
    details = [("کد", st.code), ("انبار", warehouse.name if warehouse else None), ("اقلام", fa_num(len(lines)))]
    common = dict(organization_id=st.organization_id, link=f"/app/stocktakes/{st.id}", warehouse_id=st.warehouse_id,
                  actor=actor, dedupe_key=f"stocktake:{st.id}")
    if event == "submitted":
        notify(db, **common, kind="stocktake_review", audience="admin", title="انبارگردانی منتظر تأیید است",
               message=f"شمارش {st.code} در «{warehouse.name if warehouse else 'انبار'}» تمام شد و برای بررسی و تأیید ارسال شد.",
               severity="warning" if variance else "info",
               details=details + [("دارای مغایرت", fa_num(variance) + " قلم" if variance else "ندارد")])
    elif event == "recount":
        count = sum(1 for l in lines if l.counted_qty is None)
        notify(db, **common, kind="stocktake_recount", title="شمارش مجدد خواسته شد",
               message=f"ادمین برای {fa_num(count)} قلم از انبارگردانی {st.code} شمارش دوباره خواسته است.",
               details=details + [("توضیح ادمین", _preview(note, 80) if note else None)])
    elif event == "approved":
        adjusted = sum(1 for l in lines if l.adjustment)
        notify(db, **common, kind="stocktake_approved", title="انبارگردانی تأیید شد",
               message=f"انبارگردانی {st.code} تأیید شد" + (f" و موجودی {fa_num(adjusted)} قلم اصلاح شد." if adjusted else "؛ مغایرتی نبود."),
               details=details)


def driver_application(db: Session, driver: User, profile) -> None:
    notify(db, organization_id=driver.organization_id, kind="driver_application", audience="admin",
           title="پرونده راننده منتظر بررسی است",
           message=f"{_name(driver)} پرونده و مدارک خود را برای تأیید فرستاد.",
           link=f"/app/drivers?driver={driver.id}", dedupe_key=f"application:{driver.id}",
           details=[("شهر", getattr(profile, "city", None)), ("پلاک", getattr(profile, "license_plate", None))])


def application_result(db: Session, driver: User, approved: bool, reason: str | None, actor: User) -> None:
    notify(db, organization_id=driver.organization_id, kind="application_result", user_id=driver.id, actor=actor,
           severity="success" if approved else "danger", dedupe_key=f"application-result:{driver.id}",
           title="پرونده شما تأیید شد" if approved else "پرونده شما نیاز به اصلاح دارد",
           message=("حساب راننده‌ای شما فعال شد و از این پس سفارش‌ها به شما سپرده می‌شوند." if approved
                    else f"دلیل: {_preview(reason, 120)}"),
           link="/app/driver" if approved else "/app/onboarding")


REQUEST_LABELS = {"leave": "مرخصی", "vehicle_change": "تغییر خودرو"}


def driver_request(db: Session, req, driver: User) -> None:
    label = REQUEST_LABELS.get(req.kind, "درخواست")
    urgent = req.kind == "leave" and req.leave_type == "urgent"
    details = [("نوع", f"{label}{' فوری' if urgent else ''}")]
    if req.kind == "leave" and req.starts_at:
        details += [("از", _local_time(req.starts_at)), ("تا", _local_time(req.ends_at))]
    notify(db, organization_id=driver.organization_id, kind="driver_request", audience="admin",
           title=f"درخواست {label} از راننده", message=f"{_name(driver)} درخواست {label} فرستاد" + (f": {_preview(req.reason, 100)}" if req.reason else "."),
           severity="warning" if urgent else "info", link=f"/app/driver-requests?request={req.id}", details=details)


def request_result(db: Session, req, driver: User, approved: bool, note: str | None, actor: User) -> None:
    label = REQUEST_LABELS.get(req.kind, "درخواست")
    notify(db, organization_id=driver.organization_id, kind="request_result", user_id=driver.id, actor=actor,
           severity="success" if approved else "danger",
           title=f"درخواست {label} {'تأیید' if approved else 'رد'} شد",
           message=f"نظر ادمین: {_preview(note, 120)}" if note else f"درخواست {label} شما بررسی شد.",
           link="/app/driver/requests")


LOW_RATING = 2


def rating_event(db: Session, order: Order, driver_id: int, score: int, comment: str | None, source: str, actor: User | None) -> None:
    if score > LOW_RATING:
        return
    driver = db.get(User, driver_id)
    by = "مشتری" if source == "customer" else "سازمان"
    notify(db, organization_id=order.organization_id, kind="low_rating", title="امتیاز پایین برای راننده",
           message=f"{by} به {_name(driver) or 'راننده'} برای سفارش {order.tracking_code} امتیاز {fa_num(score)} از ۵ داد.",
           link=f"/app/drivers/{driver_id}", warehouse_id=order.warehouse_id, actor=actor,
           dedupe_key=f"rating:{order.id}:{source}",
           details=[("کد پیگیری", order.tracking_code), ("امتیاز", f"{fa_num(score)} از ۵"),
                    ("نظر", _preview(comment, 80) if comment else None)])
