"""
عملیات گروهی با پیش‌نمایش (سفارش‌ها و تیکت‌ها).

دو گام: dry_run=true فقط بررسی می‌کند و برای هر سطر «قابل اجرا / نامعتبر با دلیل / بدون دسترسی» برمی‌گرداند؛
اجرا هر سطر را جدا با **همان تابع عملیات تکی** انجام می‌دهد (همان قواعد، همان تاریخچه و اعلان) و شکست
یک سطر بقیه را برنمی‌گرداند. بستن تیکت (غیرقابل‌بازگشت) تأیید تایپی می‌خواهد.
"""
from sqlalchemy.orm import Session

from app.models import ACTIVE_ORDER_STATUSES, Order, Ticket, User
from app.schemas.order import OrderAssignRequest
from app.services import dispatch_service, order_service, ticket_service
from app.services.exceptions import ConflictError, DomainError, ForbiddenError, NotFoundError

MAX_ROWS = 200
CONFIRM_TEXT = "تأیید"
ORDER_ACTIONS = ("assign", "priority")
TICKET_ACTIONS = ("assign", "priority", "resolve", "close")


def _role(user: User) -> str:
    return getattr(user.role, "value", user.role)


class _Invalid(Exception):
    def __init__(self, reason: str, unauthorized: bool = False):
        super().__init__(reason)
        self.reason, self.unauthorized = reason, unauthorized


def _run(ids: list[int], label, check, execute, dry_run: bool) -> dict:
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise ConflictError("هیچ سطری انتخاب نشده است.")
    if len(ids) > MAX_ROWS:
        raise ConflictError(f"در هر اجرا حداکثر {MAX_ROWS} سطر.")
    results = []
    for row_id in ids:
        try:
            name = label(row_id)
        except _Invalid as e:
            results.append({"id": row_id, "label": str(row_id), "status": "unauthorized", "reason": e.reason})
            continue
        try:
            check(row_id)
        except _Invalid as e:
            results.append({"id": row_id, "label": name, "status": "unauthorized" if e.unauthorized else "invalid",
                            "reason": e.reason})
            continue
        if dry_run:
            results.append({"id": row_id, "label": name, "status": "ok", "reason": None})
            continue
        try:
            execute(row_id)
            results.append({"id": row_id, "label": name, "status": "done", "reason": None})
        except (NotFoundError, ForbiddenError) as e:
            results.append({"id": row_id, "label": name, "status": "unauthorized", "reason": e.message})
        except DomainError as e:
            results.append({"id": row_id, "label": name, "status": "failed", "reason": e.message})
    count = lambda *s: sum(1 for r in results if r["status"] in s)  # noqa: E731
    return {"dry_run": dry_run, "total": len(results), "valid": count("ok", "done"), "invalid": count("invalid", "failed"),
            "unauthorized": count("unauthorized"), "results": results}


# ---------------------------------------------------------------------------
# سفارش‌ها: تخصیص خودرو (خودکار یا خودروی مشخص) و تغییر اولویت
# ---------------------------------------------------------------------------
def orders(db: Session, user: User, action: str, ids: list[int], params: dict, dry_run: bool) -> dict:
    role = _role(user)
    if role not in ("org_admin", "warehouse_manager"):
        raise ForbiddenError("عملیات گروهی فقط برای ادمین سازمان و مدیر انبار است.")
    if action not in ORDER_ACTIONS:
        raise ConflictError("عملیات نامعتبر است.")
    if action == "priority" and role != "org_admin":
        raise ForbiddenError("فقط ادمین سازمان اولویت سفارش را تغییر می‌دهد.")
    if action == "priority" and not isinstance(params.get("priority"), bool):
        raise ConflictError("اولویت (فوری یا عادی) را مشخص کنید.")
    vehicle_id = params.get("vehicle_id")
    if action == "assign" and vehicle_id is not None and (not isinstance(vehicle_id, int) or vehicle_id <= 0):
        raise ConflictError("خودرو نامعتبر است.")
    loaded: dict[int, Order] = {}

    def label(order_id: int) -> str:
        order = db.get(Order, order_id)
        if order is None:
            raise _Invalid("سفارش یافت نشد.")
        loaded[order_id] = order
        return order.tracking_code

    def check(order_id: int) -> None:
        order = loaded[order_id]
        if action == "assign":
            if role == "warehouse_manager" and order.warehouse_id != user.warehouse_id:
                raise _Invalid("این سفارش از انبار شما ارسال نمی‌شود.", unauthorized=True)
            if order.status != "pending":
                raise _Invalid("فقط سفارش «در انتظار تخصیص» خودرو می‌گیرد.")
            dispatch = order_service._dispatch_args(order.total_weight_kg, order.delivery_window_start, order.delivery_window_end,
                                                    order.destination_city, order.destination_province, exclude_order_id=order.id)
            if vehicle_id:
                ev = dispatch_service.check_vehicle(db, vehicle_id, **dispatch)
                if ev is None or not ev.eligible:
                    raise _Invalid(f"این خودرو مناسب نیست: {ev.reason if ev else 'یافت نشد'}")
            elif not any(e.eligible for e in dispatch_service.evaluate(db, **dispatch)):
                raise _Invalid("خودروی مناسبی در دسترس نیست.")
        else:
            if order.status not in ACTIVE_ORDER_STATUSES:
                raise _Invalid("سفارش پایان‌یافته است.")
            if order.priority == params["priority"]:
                raise _Invalid("اولویت از قبل همین است.")

    def execute(order_id: int) -> None:
        if action == "assign":
            order_service.assign_vehicle(db, user, order_id, OrderAssignRequest(vehicle_id=vehicle_id))
        else:
            order_service.set_priority(db, user, order_id, params["priority"])

    return {"action": action, **_run(ids, label, check, execute, dry_run)}


# ---------------------------------------------------------------------------
# تیکت‌ها: مسئول، اولویت، حل‌شده، بستن
# ---------------------------------------------------------------------------
def tickets(db: Session, user: User, action: str, ids: list[int], params: dict, dry_run: bool) -> dict:
    if ticket_service.side_of(user) != "org":
        raise ForbiddenError("عملیات گروهی تیکت فقط برای کارکنان سازمان است.")
    if action not in TICKET_ACTIONS:
        raise ConflictError("عملیات نامعتبر است.")
    if action == "priority" and params.get("priority") not in ("normal", "high", "urgent"):
        raise ConflictError("اولویت نامعتبر است.")
    if action == "assign" and not (isinstance(params.get("assignee_id"), int) and params["assignee_id"] > 0):
        raise ConflictError("مسئول را انتخاب کنید.")
    if action == "close" and not dry_run and (params.get("confirm") or "").strip() != CONFIRM_TEXT:
        raise ConflictError(f"برای بستن گروهی تیکت‌ها عبارت «{CONFIRM_TEXT}» را تایپ کنید.")
    flags: dict[int, dict] = {}

    def label(ticket_id: int) -> str:
        ticket = db.get(Ticket, ticket_id)
        if ticket is None:
            raise _Invalid("تیکت یافت نشد.")
        try:
            flags[ticket_id] = ticket_service.get_ticket(db, user, ticket_id)
        except DomainError as e:
            raise _Invalid(e.message)
        return ticket.code

    def check(ticket_id: int) -> None:
        detail = flags[ticket_id]
        if action in ("assign", "priority") and not detail["can_manage"]:
            raise _Invalid("مسئول و اولویت تیکت‌های داخلی سازمان را پلتفرم تعیین می‌کند.", unauthorized=True)
        if action == "resolve" and not detail["can_resolve"]:
            raise _Invalid("این تیکت باز نیست یا اجازه اعلام حل آن را ندارید.")
        if action == "close" and not detail["can_close"]:
            raise _Invalid("این تیکت بسته است یا اجازه بستن آن را ندارید.")

    def execute(ticket_id: int) -> None:
        if action == "assign":
            ticket_service.update(db, user, ticket_id, assignee_id=params["assignee_id"])
        elif action == "priority":
            ticket_service.update(db, user, ticket_id, priority=params["priority"])
        elif action == "resolve":
            ticket_service.resolve(db, user, ticket_id)
        else:
            ticket_service.close(db, user, ticket_id)

    return {"action": action, **_run(ids, label, check, execute, dry_run)}
