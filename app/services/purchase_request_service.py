"""
درخواست خرید و تأیید آن (CEO-03، ت۲۲). پرداخت، سقف مبلغ و ساخت خودکار رسید ندارد.
تأیید با ادمین سازمان است و درخواست‌دهنده درخواست خودش را تأیید نمی‌کند. تغییر وضعیت UPDATE شرطی است، پس از دو تصمیم همزمان یکی رد می‌شود.
بهای واحد برآورد است و از آخرین بهای ثبت‌شده کالا می‌آید.
"""
import secrets
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Product, ProductPrice, User, Warehouse
from app.models_productivity import PurchaseRequest, PurchaseRequestEvent, PurchaseRequestLine
from app.services import audit_service, location_service, notification_service, permission_service
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError

STATUS_LABELS = {"pending": "منتظر تصمیم", "approved": "تأیید شد", "rejected": "رد شد", "canceled": "لغو شد"}
ACTION_LABELS = {"created": "ثبت درخواست", "approved": "تأیید", "rejected": "رد", "canceled": "لغو"}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _name(db: Session, user_id: int | None) -> str | None:
    user = db.get(User, user_id) if user_id else None
    return (user.full_name or user.username) if user else None


def _out(db: Session, row: PurchaseRequest) -> dict:
    warehouse = db.get(Warehouse, row.warehouse_id)
    lines = db.query(PurchaseRequestLine).filter(PurchaseRequestLine.request_id == row.id).order_by(PurchaseRequestLine.id).all()
    events = db.query(PurchaseRequestEvent).filter(PurchaseRequestEvent.request_id == row.id).order_by(PurchaseRequestEvent.id).all()
    known = [line.estimated_unit_cost * line.quantity for line in lines if line.estimated_unit_cost is not None]
    return {
        "id": row.id, "code": row.code, "warehouse_id": row.warehouse_id, "warehouse_name": warehouse.name if warehouse else None,
        "status": row.status, "status_label": STATUS_LABELS[row.status], "note": row.note, "requested_by_id": row.requested_by_id,
        "requested_by": _name(db, row.requested_by_id), "created_at": row.created_at,
        "estimated_total": round(sum(known)) if known else None, "estimate_complete": len(known) == len(lines),
        "lines": [{"product_id": line.product_id, "product_name": line.product_name, "quantity": line.quantity, "estimated_unit_cost": line.estimated_unit_cost} for line in lines],
        "events": [{"action": e.action, "action_label": ACTION_LABELS[e.action], "note": e.note, "actor": _name(db, e.actor_id), "at": e.at} for e in events],
    }


def _get(db: Session, user: User, request_id: int) -> PurchaseRequest:
    row = db.query(PurchaseRequest).filter(PurchaseRequest.id == request_id).first()
    if row is None:
        raise NotFoundError("این درخواست خرید یافت نشد.")
    location_service.scope_warehouse(user, row.warehouse_id)
    return row


def list_requests(db: Session, user: User, status: str | None = None, limit: int = 200) -> list[dict]:
    warehouse_id = location_service.scope_warehouse(user, None)
    query = db.query(PurchaseRequest)
    if warehouse_id is not None:
        query = query.filter(PurchaseRequest.warehouse_id == warehouse_id)
    if status:
        query = query.filter(PurchaseRequest.status == status)
    return [_out(db, r) for r in query.order_by(PurchaseRequest.id.desc()).limit(limit).all()]


def create(db: Session, user: User, data) -> dict:
    permission_service.ensure(db, user, "purchase.request")
    warehouse_id = location_service.scope_warehouse(user, data.warehouse_id)
    if warehouse_id is None or db.get(Warehouse, warehouse_id) is None:
        raise ConflictError("انبار درخواست را انتخاب کنید.")
    products = {p.id: p for p in db.query(Product).filter(Product.id.in_([line.product_id for line in data.lines])).all()}
    missing = [line.product_id for line in data.lines if line.product_id not in products]
    if missing:
        raise NotFoundError("کالای انتخاب‌شده یافت نشد.")
    if len(products) != len(data.lines):
        raise ConflictError("هر کالا فقط یک بار در درخواست می‌آید.")
    costs: dict[int, float] = {}
    for price in db.query(ProductPrice).filter(ProductPrice.product_id.in_(products), ProductPrice.cost_price.is_not(None)).order_by(ProductPrice.effective_from, ProductPrice.id).all():
        costs[price.product_id] = float(price.cost_price)
    now = _now()
    row = PurchaseRequest(code=f"PR-{secrets.token_hex(4).upper()}", warehouse_id=warehouse_id, status="pending", note=data.note, requested_by_id=user.id, created_at=now)
    db.add(row)
    db.flush()
    for line in data.lines:
        db.add(PurchaseRequestLine(request_id=row.id, product_id=line.product_id, product_name=products[line.product_id].name, quantity=line.quantity, estimated_unit_cost=costs.get(line.product_id)))
    db.add(PurchaseRequestEvent(request_id=row.id, action="created", note=data.note, actor_id=user.id, at=now))
    audit_service.log(db, user, "purchase.request", f"درخواست خرید {row.code} ثبت شد", target_type="purchase_request", target_id=row.id, target_label=row.code)
    notification_service.notify(db, organization_id=user.organization_id, kind="approval_needed", title="درخواست خرید منتظر تصمیم",
                                message=f"درخواست {row.code} ثبت شد و تصمیم می‌خواهد.", link="/app/purchase-requests", audience="admin", actor=user, dedupe_key=f"purchase:{row.id}")
    db.commit()
    return _out(db, row)


def _transition(db: Session, user: User, row: PurchaseRequest, status: str, note: str | None) -> dict:
    """فقط اگر هنوز منتظر تصمیم باشد عوض می‌شود؛ درخواست همزمان دوم چیزی پیدا نمی‌کند."""
    changed = db.query(PurchaseRequest).filter(PurchaseRequest.id == row.id, PurchaseRequest.status == "pending").update({PurchaseRequest.status: status}, synchronize_session=False)
    if not changed:
        db.rollback()
        raise ConflictError("این درخواست قبلاً تصمیم گرفته یا لغو شده است.")
    db.add(PurchaseRequestEvent(request_id=row.id, organization_id=row.organization_id, action=status, note=note, actor_id=user.id, at=_now()))
    audit_service.log(db, user, f"purchase.{status}", f"درخواست خرید {row.code}: {STATUS_LABELS[status]}", target_type="purchase_request", target_id=row.id, target_label=row.code, reason=note)
    if row.requested_by_id and row.requested_by_id != user.id:
        notification_service.notify(db, organization_id=row.organization_id, kind="approval_needed", title=f"درخواست خرید {STATUS_LABELS[status]}",
                                    message=f"درخواست {row.code}: {STATUS_LABELS[status]}.", link="/app/purchase-requests", user_id=row.requested_by_id, actor=user)
    db.commit()
    db.expire(row)
    return _out(db, row)


def decide(db: Session, user: User, request_id: int, approve: bool, note: str | None) -> dict:
    permission_service.ensure(db, user, "purchase.approve")
    row = _get(db, user, request_id)
    if row.requested_by_id == user.id:
        raise ForbiddenError("درخواست‌دهنده نمی‌تواند درخواست خودش را تأیید یا رد کند.")
    if not approve and not (note or "").strip():
        raise ConflictError("برای رد درخواست دلیل بنویسید.")
    return _transition(db, user, row, "approved" if approve else "rejected", note)


def cancel(db: Session, user: User, request_id: int, note: str | None) -> dict:
    row = _get(db, user, request_id)
    if row.requested_by_id != user.id and not permission_service.allowed(db, user, "purchase.approve"):
        raise ForbiddenError("فقط درخواست‌دهنده یا ادمین سازمان می‌تواند درخواست را لغو کند.")
    return _transition(db, user, row, "canceled", note)
