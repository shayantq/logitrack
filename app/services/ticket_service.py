"""
تیکت پشتیبانی (مرحله ۱۱): مشتری ← سازمان ← پشتیبانی پلتفرم.

سه نقش در هر تیکت:
- درخواست‌کننده (requester): مشتری بدون حساب (با لینک محرمانه)، راننده، یا خود سازمان (تیکت به پشتیبانی پلتفرم).
- سازمان (org): ادمین سازمان و مدیر انبار.
- پلتفرم (platform): ادمین و پشتیبان پسینه — فقط تیکت‌هایی را می‌بیند که سازمان به او ارجاع داده یا خود سازمان باز کرده.

پیام‌ها سه سطح دید دارند: all (همه طرف‌ها از جمله درخواست‌کننده)، staff (سازمان و پلتفرم؛ مشتری نمی‌بیند)،
side (یادداشت داخلی؛ فقط سمت نویسنده). «نوبت پاسخ» (waiting_on) بعد از هر پیام خودکار تعیین می‌شود تا هر طرف
بداند کدام تیکت‌ها منتظر اوست.
"""
from __future__ import annotations

import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core import storage
from app.core.iran import latin_digits
from app.core.tenancy import SKIP_TENANT_FILTER, set_tenant
from app.models import Customer, Order, Organization, Ticket, TicketMessage, User, Vehicle
from app.services import notification_service
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError

ORG_STAFF = ("org_admin", "warehouse_manager")
PLATFORM = ("platform_admin", "platform_support")
CATEGORIES = {
    "customer": ("delay", "damaged", "wrong_item", "driver", "address", "other"),
    "driver": ("order_issue", "vehicle", "payment", "app", "other"),
    "org": ("technical", "account", "billing", "feature", "data", "other"),
}
CATEGORY_LABELS = {
    "delay": "تأخیر در ارسال", "damaged": "آسیب‌دیدگی کالا", "wrong_item": "کالای اشتباه یا ناقص",
    "driver": "رفتار راننده", "address": "تغییر نشانی یا زمان تحویل", "order_issue": "مشکل سفارش",
    "vehicle": "خودرو", "payment": "پورسانت و تسویه", "app": "مشکل در سامانه", "technical": "مشکل فنی",
    "account": "حساب کاربری و دسترسی", "billing": "مالی و صورتحساب", "feature": "پیشنهاد قابلیت",
    "data": "اطلاعات و گزارش‌ها", "other": "سایر",
}
MAX_IMAGE = 5 * 1024 * 1024
MAX_OPEN_PER_ORDER = 3
PLATFORM_NAME = "پشتیبانی پسینه"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _new_code(db: Session) -> str:
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = "TK-" + "".join(secrets.choice(alphabet) for _ in range(7))
        if not db.query(Ticket.id).filter(Ticket.code == code).execution_options(**SKIP_TENANT_FILTER).first():
            return code


def _display_name(user: User | None) -> str | None:
    return (user.full_name or user.username) if user else None


# ---------------------------------------------------------------------------
# نقش بیننده و دسترسی
# ---------------------------------------------------------------------------
def side_of(user: User) -> str:
    role = getattr(user.role, "value", user.role)
    if role in PLATFORM:
        return "platform"
    if role in ORG_STAFF:
        return "org"
    if role == "driver":
        return "requester"
    raise ForbiddenError()


def _platform_visible(ticket: Ticket) -> bool:
    return ticket.source == "org" or ticket.escalated_at is not None


def _check_access(user: User, ticket: Ticket) -> str:
    side = side_of(user)
    if side == "platform" and not _platform_visible(ticket):
        raise NotFoundError("تیکت یافت نشد.")
    if side == "requester" and ticket.requester_user_id != user.id:
        raise NotFoundError("تیکت یافت نشد.")
    return side


def _visible(message: TicketMessage, side: str) -> bool:
    if message.visibility == "all":
        return True
    if side == "requester":
        return False
    if message.visibility == "staff":
        return True
    return message.author_side == side          # یادداشت داخلی


def reply_options(ticket: Ticket, side: str) -> list[dict]:
    """گزینه‌های ارسال پیام برای این بیننده (کلید سطح دید + برچسب)."""
    if ticket.status == "closed":
        return []
    if side == "requester":
        return [{"visibility": "all", "label": "ارسال پیام"}]
    if side == "org":
        if ticket.source == "org":
            return [{"visibility": "all", "label": "پیام به پشتیبانی پسینه"}, {"visibility": "side", "label": "یادداشت داخلی"}]
        options = [{"visibility": "all", "label": "پاسخ به مشتری" if ticket.source == "customer" else "پاسخ به راننده"}]
        if ticket.escalated_at is not None:
            options.append({"visibility": "staff", "label": "پیام به پشتیبانی پسینه"})
        options.append({"visibility": "side", "label": "یادداشت داخلی"})
        return options
    if ticket.source == "org":
        return [{"visibility": "all", "label": "پاسخ به سازمان"}, {"visibility": "side", "label": "یادداشت داخلی پلتفرم"}]
    return [{"visibility": "staff", "label": "پاسخ به سازمان"}, {"visibility": "side", "label": "یادداشت داخلی پلتفرم"}]


# ---------------------------------------------------------------------------
# خروجی
# ---------------------------------------------------------------------------
def _summary(db: Session, ticket: Ticket, org_names: dict[int, str] | None = None) -> dict:
    order = db.get(Order, ticket.order_id) if ticket.order_id else None
    assignee = db.get(User, ticket.assignee_id) if ticket.assignee_id else None
    return {
        "id": ticket.id, "code": ticket.code, "subject": ticket.subject, "category": ticket.category,
        "category_label": CATEGORY_LABELS.get(ticket.category, ticket.category), "priority": ticket.priority,
        "source": ticket.source, "handler": ticket.handler, "status": ticket.status, "waiting_on": ticket.waiting_on,
        "created_at": ticket.created_at, "last_activity_at": ticket.last_activity_at,
        "order_id": ticket.order_id, "order_tracking_code": order.tracking_code if order else None,
        "requester_name": ticket.requester_name, "assignee_id": ticket.assignee_id, "assignee_name": _display_name(assignee),
        "escalated_at": ticket.escalated_at, "resolved_at": ticket.resolved_at,
        "organization_name": (org_names or {}).get(ticket.organization_id),
        # بیش از ۲۴ ساعت بدون پاسخ سمتی که نوبت اوست (برای نشان «دیرکرد»)
        "overdue": ticket.status == "open" and ticket.waiting_on in ("org", "platform")
                   and ticket.last_activity_at is not None and ticket.last_activity_at < _now() - timedelta(hours=24),
    }


def _detail(db: Session, ticket: Ticket, side: str) -> dict:
    org = db.get(Organization, ticket.organization_id)
    data = _summary(db, ticket, {ticket.organization_id: org.name if org else ""})
    messages = [m for m in ticket.messages if _visible(m, side)]
    data.update(
        escalation_reason=ticket.escalation_reason if side != "requester" else None,
        requester_mobile=ticket.requester_mobile if side == "org" else None,
        messages=[{
            "id": m.id, "created_at": m.created_at, "author_side": m.author_side, "author_name": m.author_name,
            "body": m.body, "visibility": m.visibility, "has_attachment": bool(m.attachment_path),
            "attachment_type": m.attachment_type,
        } for m in messages],
        viewer_side=side,
        reply_options=reply_options(ticket, side),
        can_escalate=side == "org" and ticket.source != "org" and ticket.escalated_at is None and ticket.status != "closed",
        can_resolve=ticket.status == "open" and (
            (side == "org" and ticket.handler == "org") or (side == "platform" and ticket.handler == "platform")
            or (side == "requester") or (side == "org" and ticket.source == "org")),
        can_close=side in ("org", "platform") and ticket.status != "closed" and (
            (side == "org" and ticket.source != "org") or (side == "platform" and ticket.source == "org")),
        can_manage=side == "org" and ticket.source != "org",
    )
    return data


# ---------------------------------------------------------------------------
# پیام و پیوست
# ---------------------------------------------------------------------------
def _attach(ticket: Ticket, data: bytes | None) -> tuple[str | None, str | None]:
    if not data:
        return None, None
    if len(data) > MAX_IMAGE:
        raise ConflictError("حجم تصویر نباید بیشتر از ۵ مگابایت باشد.")
    try:
        ext = storage.detect_image(data)
    except storage.InvalidFileError as e:
        raise ConflictError(str(e))
    path = f"tickets/{ticket.organization_id}/{ticket.id}/{uuid.uuid4().hex}.{ext}"
    storage.save(path, data)
    return path, storage.MEDIA_TYPES[ext]


def _add(db: Session, ticket: Ticket, side: str, body: str, visibility: str, user: User | None = None,
         name: str | None = None, attachment: bytes | None = None) -> TicketMessage:
    body = (body or "").strip()
    if not body and not attachment:
        raise ConflictError("متن پیام خالی است.")
    path, media_type = _attach(ticket, attachment)
    message = TicketMessage(organization_id=ticket.organization_id, ticket_id=ticket.id, author_side=side,
                            author_user_id=user.id if user else None, author_name=name or _display_name(user),
                            body=body or "(تصویر)", visibility=visibility, attachment_path=path, attachment_type=media_type)
    db.add(message)
    ticket.last_activity_at = _now()
    return message


def _after_message(ticket: Ticket, side: str, visibility: str) -> None:
    """نوبت پاسخ و بازگشایی تیکت حل‌شده پس از یک پیام."""
    if visibility == "side":
        return                                   # یادداشت داخلی نوبت را عوض نمی‌کند
    if side == "requester":
        ticket.waiting_on = "platform" if ticket.source == "org" else "org"
        if ticket.status == "resolved":
            ticket.status, ticket.resolved_at = "open", None
    elif side == "org":
        if ticket.source == "org" or visibility == "staff":
            ticket.waiting_on = "platform"
        else:
            ticket.waiting_on = "requester"
        if ticket.source == "org" and ticket.status == "resolved":
            ticket.status, ticket.resolved_at = "open", None
    elif side == "platform":
        ticket.waiting_on = "org" if ticket.source != "org" else "requester"


def _system(db: Session, ticket: Ticket, text: str, visibility: str = "all") -> None:
    db.add(TicketMessage(organization_id=ticket.organization_id, ticket_id=ticket.id, author_side="system",
                         author_name="سیستم", body=text, visibility=visibility))
    ticket.last_activity_at = _now()


# ---------------------------------------------------------------------------
# ساخت تیکت
# ---------------------------------------------------------------------------
def _validate(source: str, category: str, subject: str | None) -> str:
    if category not in CATEGORIES[source]:
        raise ConflictError("موضوع انتخاب‌شده برای این نوع تیکت معتبر نیست.")
    subject = (subject or "").strip()
    return subject or CATEGORY_LABELS[category]


def create_ticket(db: Session, user: User, *, category: str, subject: str | None, body: str, priority: str = "normal",
                  order_id: int | None = None, attachment: bytes | None = None) -> dict:
    """راننده ← سازمان؛ کارکنان سازمان ← پشتیبانی پلتفرم."""
    side = side_of(user)
    if side == "platform":
        raise ForbiddenError("کارکنان پلتفرم تیکت باز نمی‌کنند؛ به تیکت‌های سازمان‌ها پاسخ می‌دهند.")
    source = "driver" if side == "requester" else "org"
    subject = _validate(source, category, subject)
    if order_id is not None:
        order = db.get(Order, order_id)
        if order is None:
            raise NotFoundError("سفارش یافت نشد.")
        if source == "driver":
            vehicle = db.get(Vehicle, order.vehicle_id) if order.vehicle_id else None
            if order.driver_id != user.id and not (vehicle and vehicle.driver_id == user.id):
                raise NotFoundError("سفارش یافت نشد.")
    ticket = Ticket(organization_id=user.organization_id, code=_new_code(db), subject=subject, category=category,
                    priority=priority if source == "org" else "normal", source=source,
                    handler="platform" if source == "org" else "org", status="open",
                    waiting_on="platform" if source == "org" else "org", order_id=order_id,
                    requester_user_id=user.id, requester_name=_display_name(user))
    db.add(ticket)
    db.flush()
    _add(db, ticket, "org" if source == "org" else "requester", body, "all", user=user, attachment=attachment)
    if source == "driver":
        notification_service.ticket_event(db, ticket, "requester", body, actor=user, new=True)
    db.commit()
    db.refresh(ticket)
    return _detail(db, ticket, side)


def create_customer_ticket(db: Session, tracking_code: str, phone_last4: str, *, category: str, body: str,
                           attachment: bytes | None = None) -> dict:
    from app.services.tracking_service import verify_phone    # جلوگیری از import چرخه‌ای
    code = latin_digits(tracking_code.strip()).upper()
    order = db.query(Order).filter(Order.tracking_code == code).execution_options(**SKIP_TENANT_FILTER).first()
    if order is None:
        raise NotFoundError("سفارشی با این کد پیگیری یافت نشد.")
    set_tenant(db, order.organization_id)
    customer = db.get(Customer, order.customer_id) if order.customer_id else None
    last4 = latin_digits((phone_last4 or "").strip())
    if len(last4) != 4 or not last4.isdigit() or not verify_phone(order, customer, last4):
        raise ForbiddenError("۴ رقم آخر موبایل با اطلاعات این سفارش مطابقت ندارد.")
    open_count = db.query(Ticket).filter(Ticket.order_id == order.id, Ticket.source == "customer", Ticket.status == "open").count()
    if open_count >= MAX_OPEN_PER_ORDER:
        raise ConflictError("برای این سفارش چند درخواست باز دارید؛ لطفاً در همان درخواست‌ها پیگیری کنید.")
    subject = _validate("customer", category, None)
    ticket = Ticket(organization_id=order.organization_id, code=_new_code(db), subject=f"{subject} — سفارش {order.tracking_code}",
                    category=category, source="customer", handler="org", status="open", waiting_on="org", order_id=order.id,
                    requester_name=order.recipient_name or (customer.name if customer else "مشتری"),
                    requester_mobile=order.recipient_mobile or (customer.mobile if customer else None),
                    access_token=secrets.token_urlsafe(24), priority="high" if category == "damaged" else "normal")
    db.add(ticket)
    db.flush()
    _add(db, ticket, "requester", body, "all", name=ticket.requester_name, attachment=attachment)
    notification_service.ticket_event(db, ticket, "requester", body, new=True)
    db.commit()
    db.refresh(ticket)
    return {**_detail(db, ticket, "requester"), "access_token": ticket.access_token}


# ---------------------------------------------------------------------------
# خواندن
# ---------------------------------------------------------------------------
def list_tickets(db: Session, user: User, *, status: str | None = None, waiting: bool = False,
                 source: str | None = None, q: str | None = None) -> list[dict]:
    side = side_of(user)
    query = db.query(Ticket)
    if side == "requester":
        query = query.filter(Ticket.requester_user_id == user.id)
    elif side == "platform":
        query = query.filter(or_(Ticket.source == "org", Ticket.escalated_at.isnot(None)))
    if status:
        query = query.filter(Ticket.status == status)
    if waiting:
        query = query.filter(Ticket.status == "open", Ticket.waiting_on == ("org" if side == "org" else side))
    if source:
        query = query.filter(Ticket.source == source)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(Ticket.code.ilike(f"%{latin_digits(q.strip()).upper()}%"), Ticket.subject.ilike(like),
                                 Ticket.requester_name.ilike(like)))
    tickets = query.order_by(Ticket.last_activity_at.desc(), Ticket.id.desc()).limit(300).all()
    org_names = {o.id: o.name for o in db.query(Organization).all()} if side == "platform" else None
    return [_summary(db, t, org_names) for t in tickets]


def summary(db: Session, user: User) -> dict:
    side = side_of(user)
    query = db.query(Ticket).filter(Ticket.status == "open")
    if side == "requester":
        query = query.filter(Ticket.requester_user_id == user.id, Ticket.waiting_on == "requester")
    elif side == "org":
        query = query.filter(Ticket.waiting_on == "org")
    else:
        query = query.filter(Ticket.waiting_on == "platform")
    return {"needs_action": query.count()}


def _load(db: Session, ticket_id: int) -> Ticket:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise NotFoundError("تیکت یافت نشد.")
    return ticket


def get_ticket(db: Session, user: User, ticket_id: int) -> dict:
    ticket = _load(db, ticket_id)
    return _detail(db, ticket, _check_access(user, ticket))


# ---------------------------------------------------------------------------
# پاسخ و تغییر وضعیت
# ---------------------------------------------------------------------------
def post_message(db: Session, user: User, ticket_id: int, body: str, visibility: str = "all",
                 attachment: bytes | None = None) -> dict:
    ticket = _load(db, ticket_id)
    side = _check_access(user, ticket)
    if visibility not in {o["visibility"] for o in reply_options(ticket, side)}:
        raise ConflictError("این نوع پیام برای این تیکت مجاز نیست." if ticket.status != "closed" else "این تیکت بسته شده است.")
    _add(db, ticket, side, body, visibility, user=user, attachment=attachment)
    _after_message(ticket, side, visibility)
    if visibility == "all":
        notification_service.ticket_event(db, ticket, side, body or "(تصویر)", actor=user)
    db.commit()
    db.refresh(ticket)
    return _detail(db, ticket, side)


def escalate(db: Session, user: User, ticket_id: int, reason: str) -> dict:
    ticket = _load(db, ticket_id)
    side = _check_access(user, ticket)
    if side != "org" or ticket.source == "org":
        raise ForbiddenError("فقط سازمان می‌تواند تیکت مشتری یا راننده را به پشتیبانی پسینه ارجاع دهد.")
    if ticket.escalated_at is not None:
        raise ConflictError("این تیکت قبلاً ارجاع شده است.")
    if ticket.status == "closed":
        raise ConflictError("این تیکت بسته شده است.")
    ticket.escalated_at, ticket.escalation_reason = _now(), reason.strip()
    ticket.handler, ticket.waiting_on, ticket.status = "platform", "platform", "open"
    _system(db, ticket, f"ارجاع به پشتیبانی پسینه توسط {_display_name(user)}: {reason.strip()}", visibility="staff")
    db.commit()
    db.refresh(ticket)
    return _detail(db, ticket, side)


def resolve(db: Session, user: User, ticket_id: int) -> dict:
    ticket = _load(db, ticket_id)
    side = _check_access(user, ticket)
    detail = _detail(db, ticket, side)
    if not detail["can_resolve"]:
        raise ForbiddenError("اجازه تغییر وضعیت این تیکت را ندارید.")
    if side == "platform" and ticket.source != "org":
        # بررسی پلتفرم تمام شد؛ پاسخ نهایی به مشتری/راننده با سازمان است
        ticket.handler, ticket.waiting_on = "org", "org"
        _system(db, ticket, "پشتیبانی پسینه بررسی را تمام کرد و تیکت به سازمان برگشت.", visibility="staff")
    else:
        ticket.status, ticket.waiting_on, ticket.resolved_at = "resolved", "none", _now()
        who = "درخواست‌کننده" if side == "requester" else (PLATFORM_NAME if side == "platform" else _display_name(user))
        _system(db, ticket, f"تیکت توسط {who} «حل‌شده» اعلام شد. با ارسال پیام جدید دوباره باز می‌شود.")
    db.commit()
    db.refresh(ticket)
    return _detail(db, ticket, side)


def close(db: Session, user: User, ticket_id: int) -> dict:
    ticket = _load(db, ticket_id)
    side = _check_access(user, ticket)
    if not _detail(db, ticket, side)["can_close"]:
        raise ForbiddenError("اجازه بستن این تیکت را ندارید.")
    ticket.status, ticket.waiting_on = "closed", "none"
    ticket.resolved_at = ticket.resolved_at or _now()
    _system(db, ticket, "تیکت بسته شد و پیام جدید پذیرفته نمی‌شود.")
    db.commit()
    db.refresh(ticket)
    return _detail(db, ticket, side)


def update(db: Session, user: User, ticket_id: int, *, priority: str | None = None, assignee_id: int | None = None,
           unassign: bool = False) -> dict:
    ticket = _load(db, ticket_id)
    side = _check_access(user, ticket)
    if side != "org" or ticket.source == "org":
        raise ForbiddenError("فقط سازمان اولویت و مسئول تیکت‌های مشتری و راننده را تعیین می‌کند.")
    if priority:
        ticket.priority = priority
    if unassign:
        ticket.assignee_id = None
    elif assignee_id is not None:
        assignee = db.get(User, assignee_id)
        if assignee is None or getattr(assignee.role, "value", assignee.role) not in ORG_STAFF:
            raise ConflictError("مسئول باید از کارکنان سازمان باشد.")
        ticket.assignee_id = assignee.id
    db.commit()
    db.refresh(ticket)
    return _detail(db, ticket, side)


def attachment_of(db: Session, user: User | None, ticket: Ticket, message_id: int, side: str):
    message = db.get(TicketMessage, message_id)
    if message is None or message.ticket_id != ticket.id or not message.attachment_path or not _visible(message, side):
        raise NotFoundError("فایل یافت نشد.")
    path = storage.path_of(message.attachment_path)
    if path is None:
        raise NotFoundError("فایل یافت نشد.")
    return path, message.attachment_type


def attachment(db: Session, user: User, ticket_id: int, message_id: int):
    ticket = _load(db, ticket_id)
    return attachment_of(db, user, ticket, message_id, _check_access(user, ticket))


# ---------------------------------------------------------------------------
# مشتری با لینک محرمانه
# ---------------------------------------------------------------------------
def _by_token(db: Session, token: str) -> Ticket:
    ticket = db.query(Ticket).filter(Ticket.access_token == token).execution_options(**SKIP_TENANT_FILTER).first()
    if ticket is None:
        raise NotFoundError("درخواستی با این لینک یافت نشد.")
    set_tenant(db, ticket.organization_id)
    return ticket


def public_get(db: Session, token: str) -> dict:
    ticket = _by_token(db, token)
    data = _detail(db, ticket, "requester")
    data["organization_name"] = db.get(Organization, ticket.organization_id).name
    return data


def public_message(db: Session, token: str, body: str, attachment: bytes | None = None) -> dict:
    ticket = _by_token(db, token)
    if ticket.status == "closed":
        raise ConflictError("این درخواست بسته شده است؛ برای مشکل جدید از صفحه پیگیری سفارش درخواست تازه ثبت کنید.")
    _add(db, ticket, "requester", body, "all", name=ticket.requester_name, attachment=attachment)
    _after_message(ticket, "requester", "all")
    notification_service.ticket_event(db, ticket, "requester", body or "(تصویر)")
    db.commit()
    return public_get(db, token)


def public_resolve(db: Session, token: str) -> dict:
    ticket = _by_token(db, token)
    if ticket.status == "open":
        ticket.status, ticket.waiting_on, ticket.resolved_at = "resolved", "none", _now()
        _system(db, ticket, "مشتری اعلام کرد مشکل حل شده است.")
        db.commit()
    return public_get(db, token)


def public_attachment(db: Session, token: str, message_id: int):
    ticket = _by_token(db, token)
    return attachment_of(db, None, ticket, message_id, "requester")
