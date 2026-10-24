"""
بازرسی کیفی و قرنطینه (فصل ۸)

وضعیت کیفی مستقل از محل است: بازرسی و تغییر وضعیت کالا را جابه‌جا نمی‌کند — همان مقدار در همان محل، با همان
بچ/سریال/مالک، از ردیف یک وضعیت به ردیف وضعیت دیگر می‌رود (سند QI با گردش‌های status_out/status_in).
جابه‌جایی فیزیکی بعدی (مثلاً به قفسه نگهداری یا محل قرنطینه) با وظیفه جانمایی انجام می‌شود که همین‌جا ساخته می‌شود.

مجوزها از جدول app/core/wms.QUALITY_TRANSITIONS: مثلاً «در انتظار بازرسی ← تأییدشده» برای مدیر انبار و ادمین،
ولی آزادسازی کالای «توقیف» یا «مردود» فقط با ادمین سازمان. مدیر انبار فقط کالای انبار خودش را بازرسی می‌کند.
فقط موجودی «تأییدشده» قابل تخصیص است؛ پس کالای قرنطینه/توقیف/مردود هیچ‌وقت به سفارش نمی‌رسد.

نتیجه بازرسی کالای «در انتظار بازرسی» به سطرهای رسید (پذیرفته/مردود) نسبت داده می‌شود.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.wms import AVAILABLE, PENDING, STOCK_STATUS_LABELS, quality_roles
from app.models import InboundReceipt, Inventory, Product, QualityInspection, QualityInspectionResult, StockDocument, User
from app.services import (
    event_bus, location_service, putaway_service, receiving_service, stock_document_service, stock_ledger,
)
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError

REJECTED_RESULTS = ("rejected", "defective", "damaged")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _role(user: User) -> str:
    return getattr(user.role, "value", user.role)


def ensure_transition(user: User, from_status: str, to_status: str) -> None:
    if from_status == to_status:
        raise ConflictError("وضعیت مبدأ و مقصد نمی‌توانند یکی باشند.")
    roles = quality_roles(from_status, to_status)
    if not roles:
        raise ConflictError(f"تغییر وضعیت «{STOCK_STATUS_LABELS[from_status]}» به «{STOCK_STATUS_LABELS[to_status]}» مجاز نیست.")
    if _role(user) not in roles:
        raise ForbiddenError(f"تغییر «{STOCK_STATUS_LABELS[from_status]}» به «{STOCK_STATUS_LABELS[to_status]}» فقط با ادمین سازمان است.")


def resolve_warehouse(db: Session, user: User, product_id: int, warehouse_id: int | None, stock_status: str) -> int:
    warehouse_id = location_service.scope_warehouse(user, warehouse_id)
    if warehouse_id is not None:
        return warehouse_id
    candidates = {w for (w,) in db.query(Inventory.warehouse_id).filter(
        Inventory.product_id == product_id, Inventory.stock_status == stock_status, Inventory.quantity > 0).all()}
    if len(candidates) == 1:
        return candidates.pop()
    raise ConflictError("این کالا در چند انبار (یا هیچ انباری) با این وضعیت موجودی دارد؛ انبار را مشخص کنید.")


def inspect(db: Session, user: User, data, idempotency_key: str | None = None) -> dict:
    product = db.get(Product, data.product_id)
    if product is None:
        raise NotFoundError("کالا یافت نشد.")
    for result in data.results:
        ensure_transition(user, data.from_status, result.status)
    warehouse_id = resolve_warehouse(db, user, product.id, data.warehouse_id, data.from_status)
    total = sum(r.quantity for r in data.results)

    def create(key, digest):
        try:
            if data.location_id is not None:
                location_service.resolve(db, warehouse_id, data.location_id)
            if data.receipt_id is not None:
                receipt = db.get(InboundReceipt, data.receipt_id)
                if receipt is None or receipt.warehouse_id != warehouse_id:
                    raise NotFoundError("رسید مرجع در این انبار یافت نشد.")
            source = stock_ledger.lock_bucket(db, product.id, warehouse_id, data.from_status, create=False)
            if source is None or source.free_quantity < total:
                raise ConflictError(f"موجودی «{STOCK_STATUS_LABELS[data.from_status]}» این کالا کافی نیست "
                                    f"(موجود: {source.free_quantity if source else 0}، بازرسی‌شده: {total}).")
            inspection = QualityInspection(
                code=stock_ledger.new_code(db, QualityInspection, "QC"), warehouse_id=warehouse_id, product_id=product.id,
                location_id=data.location_id, lot_number=data.lot_number, from_status=data.from_status, quantity=total,
                receipt_id=data.receipt_id, note=data.note, inspector_id=user.id, created_at=_now(),
            )
            db.add(inspection)
            db.flush()
            document = stock_ledger.new_document(
                db, "inspection", organization_id=product.organization_id, user=user, warehouse_id=warehouse_id,
                reference_type="quality_inspection", reference_id=inspection.id, note=data.note or f"بازرسی {inspection.code}",
                idempotency_key=key, request_hash=digest,
            )
            inspection.document = document
            match = {k: v for k, v in (("location_id", data.location_id), ("lot_number", data.lot_number)) if v is not None}
            moved = []
            for result in data.results:
                target = stock_ledger.lock_bucket(db, product.id, warehouse_id, result.status, reorder_point=product.reorder_point)
                label = (f"بازرسی {inspection.code}: {STOCK_STATUS_LABELS[data.from_status]} ← "
                         f"{STOCK_STATUS_LABELS[result.status]}" + (f" — {result.reason}" if result.reason else ""))
                _, movement_in = stock_ledger.move(db, source, result.quantity, document=document, target=target,
                                                   out_type="status_out", in_type="status_in", match=match or None,
                                                   user=user, reason=label)
                moved.append(movement_in)
                inspection.results.append(QualityInspectionResult(
                    organization_id=product.organization_id, to_status=result.status, quantity=result.quantity,
                    reason=result.reason))
            if data.from_status == PENDING or data.receipt_id is not None:
                receiving_service.attribute_inspection(
                    db, product_id=product.id, warehouse_id=warehouse_id, receipt_id=data.receipt_id,
                    accepted=sum(r.quantity for r in data.results if r.status == AVAILABLE),
                    rejected=sum(r.quantity for r in data.results if r.status in REJECTED_RESULTS))
            db.flush()
            for movement in moved:
                putaway_service.tasks_for_movement(db, user, movement, receipt_id=data.receipt_id, inspection_id=inspection.id)
            event_bus.emit(db, "quality.inspected", "quality_inspection", inspection.id,
                           {"code": inspection.code, "product_id": product.id, "warehouse_id": warehouse_id,
                            "from_status": data.from_status, "document_code": document.code,
                            "results": [{"status": r.status, "quantity": r.quantity, "reason": r.reason} for r in data.results]},
                           organization_id=product.organization_id, actor=user)
            db.commit()
            return document
        except Exception:
            db.rollback()
            raise

    document, _ = stock_document_service.idempotent(db, StockDocument, idempotency_key, "inspection",
                                                    data.model_dump(mode="json"), create)
    inspection = db.query(QualityInspection).filter(QualityInspection.document_id == document.id).first()
    return get_inspection(db, user, inspection.id)


def _serialize(i: QualityInspection) -> dict:
    return {
        "id": i.id, "code": i.code, "warehouse_id": i.warehouse_id, "warehouse_name": i.warehouse.name if i.warehouse else None,
        "product_id": i.product_id, "product_name": i.product.name, "product_sku": i.product.sku,
        "location_id": i.location_id, "location_code": i.location.code if i.location else None, "lot_number": i.lot_number,
        "from_status": i.from_status, "from_status_label": STOCK_STATUS_LABELS[i.from_status], "quantity": i.quantity,
        "receipt_id": i.receipt_id, "document_id": i.document_id, "document_code": i.document.code if i.document else None,
        "note": i.note, "inspector_name": (i.inspector.full_name or i.inspector.username) if i.inspector else None,
        "created_at": i.created_at,
        "results": [{"status": r.to_status, "status_label": STOCK_STATUS_LABELS[r.to_status], "quantity": r.quantity,
                     "reason": r.reason} for r in i.results],
    }


def _options(query):
    return query.options(selectinload(QualityInspection.results), joinedload(QualityInspection.product),
                         joinedload(QualityInspection.warehouse), joinedload(QualityInspection.location),
                         joinedload(QualityInspection.document), joinedload(QualityInspection.inspector))


def get_inspection(db: Session, user: User, inspection_id: int) -> dict:
    inspection = _options(db.query(QualityInspection)).filter(QualityInspection.id == inspection_id).first()
    if inspection is None:
        raise NotFoundError("بازرسی یافت نشد.")
    location_service.scope_warehouse(user, inspection.warehouse_id)
    return _serialize(inspection)


def list_inspections(db: Session, user: User, *, warehouse_id: int | None = None, product_id: int | None = None,
                     receipt_id: int | None = None, limit: int = 100) -> list[dict]:
    warehouse_id = location_service.scope_warehouse(user, warehouse_id)
    query = _options(db.query(QualityInspection))
    for column, value in ((QualityInspection.warehouse_id, warehouse_id), (QualityInspection.product_id, product_id),
                          (QualityInspection.receipt_id, receipt_id)):
        if value is not None:
            query = query.filter(column == value)
    return [_serialize(i) for i in query.order_by(QualityInspection.id.desc()).limit(limit).all()]


def transitions_for(user: User) -> list[dict]:
    from app.core.wms import QUALITY_TRANSITIONS
    role = _role(user)
    return [{"from": f, "to": t, "allowed": role in roles}
            for f, targets in QUALITY_TRANSITIONS.items() for t, roles in targets.items()]
