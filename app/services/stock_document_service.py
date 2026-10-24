"""
اسناد انبار: فهرست، جزئیات، سند برگشت و یکتایی درخواست (Idempotency).

سند برگشت: برای هر گردش سند اصلی، گردش قرینه با همان نوع و reversal_of_id ثبت می‌شود و سند اصلی
«برگشت‌خورده» می‌شود — هیچ ردیفی حذف یا بازنویسی نمی‌شود. اگر بعد از سند اصلی کالا خارج یا رزرو شده
باشد و موجودی آزاد برای برگشت کافی نباشد، برگشت رد می‌شود.

یکتایی درخواست: کلاینت در هدر Idempotency-Key یک کلید یکتا می‌فرستد؛ تکرار همان درخواست (مثلاً
بعد از قطع شبکه) همان سند قبلی را برمی‌گرداند و سند دوم نمی‌سازد. همان کلید با محتوای دیگر = خطای ۴۰۹.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import TypeVar

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.wms import DOCUMENT_TYPES
from app.models import StockDocument, StockMovement, StockMovementLine, User
from app.services import allocation_service, stock_ledger
from app.services.exceptions import ConflictError, DomainError, ForbiddenError, NotFoundError

T = TypeVar("T")
STAFF = ("org_admin", "warehouse_manager")


class IdempotencyConflictError(DomainError):
    def __init__(self):
        super().__init__("این کلید یکتایی (Idempotency-Key) قبلاً برای درخواست دیگری استفاده شده است.", status_code=409)


def _role(user: User) -> str:
    return getattr(user.role, "value", user.role)


# ---------------------------------------------------------------------------
# یکتایی درخواست
# ---------------------------------------------------------------------------
def request_hash(scope: str, payload: dict) -> str:
    raw = json.dumps({"scope": scope, **payload}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _find(db: Session, model, key: str, digest: str):
    existing = db.query(model).filter(model.idempotency_key == key).first()
    if existing is not None and existing.request_hash != digest:
        raise IdempotencyConflictError()
    return existing


def idempotent(db: Session, model, key: str | None, scope: str, payload: dict,
               create: Callable[[str | None, str | None], T]) -> tuple[T, bool]:
    """
    create(key, digest) شیء تازه را می‌سازد و commit می‌کند. خروجی: (شیء، تکراری بود؟).
    دو درخواست هم‌زمان با یک کلید: دومی به قید یکتای (organization_id, idempotency_key) می‌خورد و همان اولی را می‌گیرد.
    """
    if not key:
        return create(None, None), False
    digest = request_hash(scope, payload)
    existing = _find(db, model, key, digest)
    if existing is not None:
        return existing, True
    try:
        return create(key, digest), False
    except IntegrityError:
        db.rollback()
        existing = _find(db, model, key, digest)
        if existing is None:
            raise
        return existing, True


# ---------------------------------------------------------------------------
# خواندن
# ---------------------------------------------------------------------------
def _ensure_staff(user: User) -> None:
    if _role(user) not in STAFF:
        raise ForbiddenError("اسناد انبار فقط برای ادمین سازمان و مدیر انبار است.")


def _visible_to(user: User, doc: StockDocument) -> bool:
    if _role(user) == "org_admin":
        return True
    wid = user.warehouse_id
    return bool(wid) and (doc.warehouse_id == wid or any(m.warehouse_id == wid for m in doc.movements))


def can_reverse(user: User, doc: StockDocument) -> bool:
    kind = DOCUMENT_TYPES.get(doc.doc_type)
    if kind is None or not kind.reversible or doc.status != "posted":
        return False
    if _role(user) == "org_admin":
        return True
    # مدیر انبار فقط سندی را برمی‌گرداند که همه گردش‌هایش در انبار خودش است (انتقال بین دو انبار با ادمین)
    return _role(user) == "warehouse_manager" and bool(user.warehouse_id) and \
        all(m.warehouse_id == user.warehouse_id for m in doc.movements)


def _options(query):
    return query.options(
        selectinload(StockDocument.movements).joinedload(StockMovement.product),
        selectinload(StockDocument.movements).joinedload(StockMovement.warehouse),
        selectinload(StockDocument.movements).joinedload(StockMovement.created_by),
        selectinload(StockDocument.movements).selectinload(StockMovement.lines).joinedload(StockMovementLine.location),
        joinedload(StockDocument.warehouse), joinedload(StockDocument.partner), joinedload(StockDocument.created_by),
        joinedload(StockDocument.reversal_of),
    )


def serialize(db: Session, user: User, doc: StockDocument, reversals: dict[int, StockDocument] | None = None,
              with_movements: bool = True) -> dict:
    from app.schemas.product import StockMovementResponse
    if reversals is None:
        rev = db.query(StockDocument).filter(StockDocument.reversal_of_id == doc.id).first()
    else:
        rev = reversals.get(doc.id)
    changes = [m.quantity_change for m in doc.movements]
    return {
        "id": doc.id, "code": doc.code, "doc_type": doc.doc_type,
        "doc_type_label": DOCUMENT_TYPES[doc.doc_type].label if doc.doc_type in DOCUMENT_TYPES else doc.doc_type,
        "status": doc.status, "warehouse_id": doc.warehouse_id, "warehouse_name": doc.warehouse.name if doc.warehouse else None,
        "partner_id": doc.partner_id, "partner_name": doc.partner.name if doc.partner else None,
        "reference_type": doc.reference_type, "reference_id": doc.reference_id, "external_ref": doc.external_ref,
        "note": doc.note, "created_at": doc.created_at,
        "created_by_name": (doc.created_by.full_name or doc.created_by.username) if doc.created_by else None,
        "reversal_of_id": doc.reversal_of_id, "reversal_of_code": doc.reversal_of.code if doc.reversal_of else None,
        "reversed_by_id": rev.id if rev else None, "reversed_by_code": rev.code if rev else None,
        "can_reverse": can_reverse(user, doc),
        "total_in": sum(c for c in changes if c > 0), "total_out": -sum(c for c in changes if c < 0),
        "movements": [StockMovementResponse.from_movement(m) for m in doc.movements] if with_movements else [],
    }


def list_documents(db: Session, user: User, *, doc_type: str | None = None, status: str | None = None,
                   warehouse_id: int | None = None, product_id: int | None = None, q: str | None = None,
                   date_from: datetime | None = None, date_to: datetime | None = None,
                   skip: int = 0, limit: int = 50) -> list[dict]:
    _ensure_staff(user)
    query = _options(db.query(StockDocument))
    if _role(user) == "warehouse_manager":
        warehouse_id = user.warehouse_id or -1
    if warehouse_id:
        query = query.filter(StockDocument.movements.any(StockMovement.warehouse_id == warehouse_id))
    if product_id:
        query = query.filter(StockDocument.movements.any(StockMovement.product_id == product_id))
    if doc_type:
        query = query.filter(StockDocument.doc_type == doc_type)
    if status:
        query = query.filter(StockDocument.status == status)
    if q:
        term = f"%{q.strip()}%"
        query = query.filter(StockDocument.code.ilike(term) | StockDocument.external_ref.ilike(term))
    if date_from:
        query = query.filter(StockDocument.created_at >= date_from)
    if date_to:
        query = query.filter(StockDocument.created_at < date_to)
    docs = query.order_by(StockDocument.id.desc()).offset(skip).limit(limit).all()
    reversals = {d.reversal_of_id: d for d in db.query(StockDocument).filter(
        StockDocument.reversal_of_id.in_([d.id for d in docs] or [-1])).all()}
    return [serialize(db, user, d, reversals) for d in docs]


def get_document(db: Session, user: User, document_id: int) -> dict:
    _ensure_staff(user)
    doc = _options(db.query(StockDocument)).filter(StockDocument.id == document_id).first()
    if doc is None or not _visible_to(user, doc):
        raise NotFoundError("سند انبار یافت نشد.")
    return serialize(db, user, doc)


# ---------------------------------------------------------------------------
# سند برگشت
# ---------------------------------------------------------------------------
def reverse_document(db: Session, user: User, document_id: int, reason: str, idempotency_key: str | None = None) -> dict:
    _ensure_staff(user)

    def create(key, digest):
        try:
            doc = db.query(StockDocument).filter(StockDocument.id == document_id).with_for_update().first()
            if doc is None or not _visible_to(user, doc):
                raise NotFoundError("سند انبار یافت نشد.")
            if doc.status == "reversed":
                raise ConflictError(f"سند {doc.code} قبلاً برگشت خورده است.")
            if not can_reverse(user, doc):
                kind = DOCUMENT_TYPES.get(doc.doc_type)
                if kind is not None and not kind.reversible:
                    raise ConflictError(f"«{kind.label}» از مسیر خودش اصلاح می‌شود (سفارش یا انبارگردانی)، نه با سند برگشت.")
                raise ForbiddenError("این سند گردش انبار دیگری را هم دارد؛ برگشت آن با ادمین سازمان است.")
            inventories = allocation_service.lock_inventories(db, [m.inventory_id for m in doc.movements])
            reversal = stock_ledger.new_document(
                db, "reversal", organization_id=doc.organization_id, user=user, warehouse_id=doc.warehouse_id,
                partner_id=doc.partner_id, reference_type="stock_document", reference_id=doc.id,
                note=reason, idempotency_key=key, request_hash=digest, reversal_of=doc,
            )
            # اول افزایش‌ها و بعد کاهش‌ها تا وسط کار موجودی موقتاً منفی نشود. هر گردش دقیقاً از همان
            # محل/بچ/سریال برمی‌گردد؛ اگر کالا بعداً جابه‌جا شده باشد، برگشت رد می‌شود.
            for m in sorted(doc.movements, key=lambda m: m.quantity_change > 0):
                stock_ledger.record(db, inventories[m.inventory_id], -m.quantity_change, m.movement_type,
                                    document=reversal, user=user, reversal_of=m,
                                    lines=[(stock_ledger.key_of(line), abs(line.quantity_change)) for line in m.lines],
                                    reason=f"برگشت سند {doc.code}: {reason}")
            doc.status = "reversed"
            db.commit()
            return reversal
        except Exception:
            db.rollback()
            raise

    reversal, _ = idempotent(db, StockDocument, idempotency_key, "reverse", {"document_id": document_id, "reason": reason}, create)
    return get_document(db, user, reversal.id)

