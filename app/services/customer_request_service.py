"""
درخواست‌های مشتری از صفحه رهگیری (تصمیم ت۸، مرحله ۲): تغییر نشانی، لغو، مرجوعی و اختلاف تحویل.

مشتری فقط بعد از ورود ۴ رقم موبایل درخواست می‌دهد و چیزی مستقیم تغییر نمی‌کند: سازمان تأیید یا رد می‌کند.
اختلاف تحویل هیچ مدرکی را حذف یا عوض نمی‌کند؛ یک پرونده کنار تلاش تحویل است.
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session, selectinload

from app.core.iran import latin_digits
from app.core.tenancy import SKIP_TENANT_FILTER, set_tenant
from app.models import Customer, Order, User
from app.models_productivity import CustomerRequest
from app.schemas.operations import ReceiptCreate
from app.services import notification_service, order_service, platform_service, receiving_service
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError

STAFF = ("org_admin", "warehouse_manager")
KIND_LABELS = {"address_change": "تغییر نشانی", "cancel": "لغو سفارش", "return": "مرجوعی", "dispute": "اختلاف تحویل"}
STATUS_LABELS = {"pending": "در انتظار بررسی", "approved": "تأیید شد", "rejected": "رد شد"}
ADDRESS_STATUSES = ("pending", "assigned", "picking_up")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def public_out(row: CustomerRequest) -> dict:
    """برای مشتری: یادداشت داخلی نمی‌آید، فقط پاسخ سازمان."""
    return {"id": row.id, "kind": row.kind, "kind_label": KIND_LABELS[row.kind], "status": row.status, "status_label": STATUS_LABELS[row.status],
            "created_at": row.created_at, "decision_note": row.decision_note}


def staff_out(db: Session, row: CustomerRequest) -> dict:
    decider = db.get(User, row.decided_by_id) if row.decided_by_id else None
    return {**public_out(row), "order_id": row.order_id, "note": row.note, "payload": row.payload or {},
            "decided_by": (decider.full_name or decider.username) if decider else None, "decided_at": row.decided_at}


def _check_kind(order: Order, kind: str) -> None:
    if kind == "address_change" and order.status not in ADDRESS_STATUSES:
        raise ConflictError("نشانی فقط پیش از بارگیری قابل تغییر است؛ با پشتیبانی تماس بگیرید.")
    if kind == "cancel" and order.status not in ("pending", "assigned", "picking_up"):
        raise ConflictError("این سفارش دیگر قابل لغو نیست؛ پس از تحویل می‌توانید درخواست مرجوعی بدهید.")
    if kind == "return" and order.status != "delivered":
        raise ConflictError("مرجوعی فقط برای سفارش تحویل‌شده ثبت می‌شود.")
    if kind == "dispute" and order.status != "delivered":
        raise ConflictError("اختلاف فقط برای سفارشی ثبت می‌شود که تحویل‌شده اعلام شده است.")


def submit(db: Session, code: str, data) -> dict:
    from app.services.tracking_service import verify_phone
    normalized = latin_digits(code.strip()).upper()
    order = db.query(Order).options(selectinload(Order.items)).filter(Order.tracking_code == normalized).execution_options(**SKIP_TENANT_FILTER).first()
    if order is None:
        raise NotFoundError("سفارشی با این کد پیگیری یافت نشد.")
    set_tenant(db, order.organization_id)
    if not platform_service.feature_enabled(db, "customer_requests", order.organization_id):
        raise ConflictError("ثبت درخواست از این صفحه فعلاً ممکن نیست؛ از پشتیبانی کمک بگیرید.")
    customer = db.get(Customer, order.customer_id) if order.customer_id else None
    last4 = latin_digits((data.phone or "").strip())
    if len(last4) != 4 or not last4.isdigit() or not verify_phone(order, customer, last4):
        raise ForbiddenError("۴ رقم آخر موبایل با اطلاعات این سفارش مطابقت ندارد.")
    _check_kind(order, data.kind)
    if db.query(CustomerRequest.id).filter(CustomerRequest.order_id == order.id, CustomerRequest.kind == data.kind,
                                           CustomerRequest.status == "pending").first():
        raise ConflictError("درخواست قبلی شما از همین نوع هنوز در حال بررسی است.")
    payload = {}
    if data.kind == "address_change":
        if not data.address:
            raise ConflictError("نشانی تازه را وارد کنید.")
        payload = data.address.model_dump()
    if data.kind == "return":
        ordered = {i.product_id: i.quantity for i in order.items if i.product_id}
        lines = {line.product_id: line.quantity for line in data.items or []}
        if not lines or any(pid not in ordered or qty > ordered[pid] for pid, qty in lines.items()):
            raise ConflictError("اقلام مرجوعی با اقلام سفارش نمی‌خواند.")
        payload = {"items": [{"product_id": pid, "quantity": qty} for pid, qty in lines.items()]}
    row = CustomerRequest(organization_id=order.organization_id, order_id=order.id, kind=data.kind, status="pending", note=data.note, payload=payload, created_at=_now())
    db.add(row)
    notification_service.notify(db, organization_id=order.organization_id, kind="customer_request", title=f"درخواست مشتری: {KIND_LABELS[data.kind]}",
                                message=f"مشتری سفارش {order.tracking_code} درخواست «{KIND_LABELS[data.kind]}» داده است.",
                                link=f"/app/orders?order={order.id}", warehouse_id=order.warehouse_id,
                                severity="danger" if data.kind == "dispute" else "info", dedupe_key=f"order:{order.id}:customer_request:{data.kind}")
    db.commit()
    return public_out(row)


def for_public(db: Session, order: Order) -> list[dict]:
    rows = db.query(CustomerRequest).filter(CustomerRequest.order_id == order.id).order_by(CustomerRequest.id.desc()).limit(10).all()
    return [public_out(r) for r in rows]


def for_order(db: Session, user: User, order_id: int) -> list[dict]:
    if user.role not in STAFF:
        raise ForbiddenError()
    order = order_service.get_order(db, user, order_id)
    rows = db.query(CustomerRequest).filter(CustomerRequest.order_id == order.id).order_by(CustomerRequest.id.desc()).all()
    return [staff_out(db, r) for r in rows]


def decide(db: Session, user: User, request_id: int, data) -> dict:
    """تأیید هر نوع، همان عملیات عادی را با همان قواعد اجرا می‌کند. اختلاف فقط پرونده را می‌بندد و مدرک را دست نمی‌زند."""
    if user.role not in STAFF:
        raise ForbiddenError()
    try:
        row = db.query(CustomerRequest).filter(CustomerRequest.id == request_id).with_for_update().first()
        if row is None:
            raise NotFoundError("این درخواست یافت نشد.")
        if row.status != "pending":
            raise ConflictError("این درخواست قبلاً بررسی شده است.")
        if not data.approve and not (data.note or "").strip():
            raise ConflictError("برای رد درخواست دلیل را بنویسید؛ مشتری آن را می‌بیند.")
        order = db.query(Order).options(selectinload(Order.items)).filter(Order.id == row.order_id).with_for_update().first()
        if user.role == "warehouse_manager" and order.warehouse_id != user.warehouse_id:
            raise ForbiddenError("این سفارش از انبار شما ارسال نمی‌شود.")
        if data.approve:
            _check_kind(order, row.kind)
            if row.kind == "address_change":
                payload = row.payload
                order.destination_province, order.destination_city = payload["destination_province"], payload["destination_city"]
                order.destination_address, order.destination_postal_code = payload["destination_address"], payload.get("destination_postal_code")
                order.route = None
                order_service.record_history(db, order, order.status, order.status, user, "نشانی به درخواست مشتری تغییر کرد")
            elif row.kind == "cancel":
                order_service.apply_status(db, order, "canceled", user, "لغو به درخواست مشتری")
        row.status, row.decided_by_id, row.decided_at, row.decision_note = "approved" if data.approve else "rejected", user.id, _now(), data.note
        db.commit()
        if data.approve and row.kind == "return":
            lines = [{"product_id": i["product_id"], "expected_quantity": i["quantity"]} for i in row.payload["items"]]
            receiving_service.create_receipt(db, user, ReceiptCreate(receipt_type="return", warehouse_id=order.warehouse_id, order_id=order.id,
                                                                     note="مرجوعی به درخواست مشتری", lines=lines))
    except Exception:
        db.rollback()
        raise
    return staff_out(db, row)
