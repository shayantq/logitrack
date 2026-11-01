"""
تأیید دونفره اصلاح موجودی (docs/operations-guide.md، مرحله ۳؛ WH-ST-10، CEO-08).

وقتی سازمان سقف گذاشته باشد (adjustment_approval_units)، اصلاح یا ضایعات بیشتر از سقف اجرا نمی‌شود و یک درخواست
می‌سازد. فقط ادمین سازمانی غیر از درخواست‌کننده می‌تواند تأیید کند و همان عملیات عادی با همان قواعد اجرا می‌شود.
سقف صفر یعنی این قاعده خاموش است.
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Product, User, Warehouse
from app.models_productivity import AdjustmentApproval
from app.services import audit_service, control_settings, notification_service
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError


class ApprovalRequired(ConflictError):
    """اصلاح اجرا نشد و منتظر تأیید است. این پیام خطا نیست؛ راهنمای بعدی کاربر است."""


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def threshold(db: Session, organization_id: int) -> int:
    return control_settings.of(db, organization_id)["adjustment_approval_units"]


def request(db: Session, user: User, *, kind: str, product_id: int, warehouse_id: int | None, quantity: int, payload: dict,
            reason: str | None) -> None:
    """درخواست را ثبت و commit می‌کند و بعد ApprovalRequired می‌دهد تا عملیات اصلی اجرا نشود. درخواست تکراری ساخته نمی‌شود."""
    pending = db.query(AdjustmentApproval).filter(AdjustmentApproval.status == "pending", AdjustmentApproval.kind == kind,
                                                  AdjustmentApproval.product_id == product_id, AdjustmentApproval.requested_by_id == user.id).all()
    existing = next((a for a in pending if a.payload == payload), None)
    if existing is None:
        existing = AdjustmentApproval(organization_id=user.organization_id, kind=kind, product_id=product_id, warehouse_id=warehouse_id,
                                      quantity=quantity, payload=payload, reason=reason, status="pending", requested_by_id=user.id, created_at=_now())
        db.add(existing)
        db.flush()
        notification_service.notify(db, organization_id=user.organization_id, kind="approval_needed", title="اصلاح موجودی منتظر تأیید است",
                                    message=f"یک اصلاح {quantity} واحدی از سقف سازمان بیشتر است و تأیید می‌خواهد.", link="/app/exceptions",
                                    audience="admin", actor=user, dedupe_key=f"approval:{existing.id}")
        db.commit()
    raise ApprovalRequired(f"این اصلاح از سقف سازمان بیشتر است و اجرا نشد؛ درخواست تأیید شماره {existing.id} برای ادمین ثبت شد.")


def _out(db: Session, row: AdjustmentApproval) -> dict:
    product = db.get(Product, row.product_id)
    warehouse = db.get(Warehouse, row.warehouse_id) if row.warehouse_id else None
    requester = db.get(User, row.requested_by_id) if row.requested_by_id else None
    decider = db.get(User, row.decided_by_id) if row.decided_by_id else None
    return {"id": row.id, "kind": row.kind, "product_id": row.product_id, "product_name": product.name if product else "", "warehouse_name": warehouse.name if warehouse else None,
            "quantity": row.quantity, "reason": row.reason, "status": row.status, "requested_by": (requester.full_name or requester.username) if requester else None,
            "requested_by_id": row.requested_by_id, "created_at": row.created_at, "decided_by": (decider.full_name or decider.username) if decider else None,
            "decided_at": row.decided_at, "decision_note": row.decision_note}


def list_approvals(db: Session, user: User, status: str = "pending") -> list[dict]:
    if user.role != "org_admin":
        raise ForbiddenError("فقط ادمین سازمان درخواست‌های تأیید را می‌بیند.")
    query = db.query(AdjustmentApproval)
    if status != "all":
        query = query.filter(AdjustmentApproval.status == status)
    return [_out(db, r) for r in query.order_by(AdjustmentApproval.id.desc()).limit(200).all()]


def decide(db: Session, user: User, approval_id: int, approve: bool, note: str | None) -> dict:
    from app.schemas.product import StockMovementCreate, StockUpdate
    from app.services import inventory_service
    if user.role != "org_admin":
        raise ForbiddenError("فقط ادمین سازمان درخواست تأیید را بررسی می‌کند.")
    row = db.query(AdjustmentApproval).filter(AdjustmentApproval.id == approval_id).with_for_update().first()
    if row is None:
        raise NotFoundError("این درخواست یافت نشد.")
    if row.status != "pending":
        raise ConflictError("این درخواست قبلاً بررسی شده است.")
    if row.requested_by_id == user.id:
        raise ForbiddenError("درخواست خودتان را نمی‌توانید تأیید یا رد کنید؛ ادمین دیگری باید بررسی کند.")
    if not approve and not (note or "").strip():
        raise ConflictError("برای رد درخواست دلیل را بنویسید.")
    row.status, row.decided_by_id, row.decided_at, row.decision_note = "approved" if approve else "rejected", user.id, _now(), note
    audit_service.log(db, user, f"stock.approval_{row.status}", f"درخواست اصلاح شماره {row.id} {'تأیید' if approve else 'رد'} شد",
                      target_type="adjustment_approval", target_id=row.id, reason=note)
    if not approve:
        db.commit()
        return _out(db, row)
    # اگر اجرا شکست بخورد (مثلاً موجودی عوض شده) تأیید هم برمی‌گردد و درخواست باز می‌ماند
    db.flush()
    try:
        if row.kind == "movement":
            inventory_service.record_movement(db, user, StockMovementCreate(**row.payload), approved=True)
        else:
            inventory_service.update_stock(db, user, row.product_id, StockUpdate(**row.payload), approved=True)
    except Exception:
        db.rollback()
        raise
    db.commit()
    return _out(db, row)


def over_limit(db: Session, organization_id: int, change: int) -> bool:
    limit = threshold(db, organization_id)
    return bool(limit) and abs(change) > limit
