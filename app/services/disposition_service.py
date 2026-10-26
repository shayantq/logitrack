"""
تعیین تکلیف کالای نگه‌داشته — فصل ۱۵

کالای مردود، معیوب، آسیب‌دیده، قرنطینه یا در تعمیر یکی از این تصمیم‌ها را می‌گیرد (هر تصمیم یک سند انبار و یک
ردیف غیرقابل‌حذف Disposition با دلیل و انجام‌دهنده):
  scrap               امحا: کالا با سند «امحا» (SC) از موجودی خارج می‌شود.
  repair              ارسال به تعمیر: وضعیت «در تعمیر» در همان محل (سند DP).
  reinspect           بازرسی دوباره: وضعیت «در انتظار بازرسی» — فقط بازرسی کیفی آن را دوباره قابل تخصیص می‌کند.
  return_to_supplier  برگشت به تأمین‌کننده: خروج با سند «برگشت به تأمین‌کننده» (SR)، اختیاری با ارجاع به رسید
                      خرید اصلی (مقدار برگشتی از دریافتیِ همان کالا در آن رسید بیشتر نمی‌شود).
تغییر وضعیت‌ها از جدول مجوز کیفی (app/core/wms.QUALITY_TRANSITIONS) پیروی می‌کنند. کالای مرجوعی مشتری همیشه
«در انتظار بازرسی» وارد می‌شود و پیش از بازرسی هرگز قابل تخصیص نیست (receiving_service و order_service).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.wms import DISPOSITION_LABELS, HELD_STATUSES, PENDING, STOCK_STATUS_LABELS
from app.models import Disposition, InboundReceipt, InboundReceiptLine, Partner, Product, User
from app.services import event_bus, location_service, quality_service, stock_ledger
from app.services.exceptions import ConflictError, NotFoundError

TARGET_STATUS = {"repair": "repair", "reinspect": PENDING}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _check_supplier_return(db: Session, data, product: Product, warehouse_id: int) -> Partner:
    partner = db.get(Partner, data.partner_id) if data.partner_id else None
    if partner is None or not partner.is_supplier:
        raise ConflictError("برای برگشت به تأمین‌کننده، تأمین‌کننده را انتخاب کنید.")
    if data.receipt_id is not None:
        receipt = db.get(InboundReceipt, data.receipt_id)
        if receipt is None or receipt.warehouse_id != warehouse_id or receipt.receipt_type != "purchase":
            raise NotFoundError("رسید خرید مرجع در این انبار یافت نشد.")
        if receipt.partner_id != partner.id:
            raise ConflictError("رسید مرجع از تأمین‌کننده دیگری است.")
        received = db.query(func.coalesce(func.sum(InboundReceiptLine.received_quantity), 0)).filter(
            InboundReceiptLine.receipt_id == receipt.id, InboundReceiptLine.product_id == product.id).scalar() or 0
        returned = db.query(func.coalesce(func.sum(Disposition.quantity), 0)).filter(
            Disposition.receipt_id == receipt.id, Disposition.product_id == product.id,
            Disposition.action == "return_to_supplier").scalar() or 0
        if data.quantity > received - returned:
            raise ConflictError(f"از رسید {receipt.code} فقط {received - returned} عدد «{product.name}» قابل برگشت است.")
    return partner


def dispose(db: Session, user: User, data) -> dict:
    location_service.ensure_staff(user)
    if data.action in ("scrap", "return_to_supplier"):
        from app.services import permission_service
        permission_service.ensure(db, user, "stock.scrap")
    product = db.get(Product, data.product_id)
    if product is None:
        raise NotFoundError("کالا یافت نشد.")
    if data.from_status not in HELD_STATUSES:
        raise ConflictError("تعیین تکلیف فقط برای کالای نگه‌داشته (قرنطینه، توقیف، مردود، معیوب، آسیب‌دیده، در تعمیر) است.")
    target = TARGET_STATUS.get(data.action)
    if target is not None:
        quality_service.ensure_transition(user, data.from_status, target)
    warehouse_id = quality_service.resolve_warehouse(db, user, product.id, data.warehouse_id, data.from_status)
    try:
        location_service.resolve(db, warehouse_id, data.location_id)
        partner = _check_supplier_return(db, data, product, warehouse_id) if data.action == "return_to_supplier" else None
        source = stock_ledger.lock_bucket(db, product.id, warehouse_id, data.from_status, create=False)
        if source is None or (source.quantity or 0) < data.quantity:
            raise ConflictError(f"موجودی «{STOCK_STATUS_LABELS[data.from_status]}» این کالا کافی نیست "
                                f"(موجود: {source.quantity if source else 0}).")
        doc_type = {"scrap": "scrap", "return_to_supplier": "supplier_return"}.get(data.action, "disposition")
        disposition = Disposition(
            code=stock_ledger.new_code(db, Disposition, "DS"), action=data.action, warehouse_id=warehouse_id,
            product_id=product.id, location_id=data.location_id, lot_number=data.lot_number, from_status=data.from_status,
            quantity=data.quantity, partner_id=partner.id if partner else None, receipt_id=data.receipt_id,
            reason=data.reason, created_at=_now(), created_by_id=user.id)
        db.add(disposition)
        db.flush()
        document = stock_ledger.new_document(
            db, doc_type, organization_id=product.organization_id, user=user, warehouse_id=warehouse_id,
            partner_id=partner.id if partner else None, reference_type="disposition", reference_id=disposition.id,
            note=f"{DISPOSITION_LABELS[data.action]}: {data.reason}")
        disposition.document = document
        match = {k: v for k, v in (("location_id", data.location_id), ("lot_number", data.lot_number)) if v is not None}
        label = f"{DISPOSITION_LABELS[data.action]} ({STOCK_STATUS_LABELS[data.from_status]}): {data.reason}"
        if target is None:
            movement_type = "damage" if data.action == "scrap" else "supplier_return"
            stock_ledger.record(db, source, -data.quantity, movement_type, document=document, user=user, reason=label,
                                match=match or None)
        else:
            to_bucket = stock_ledger.lock_bucket(db, product.id, warehouse_id, target)
            stock_ledger.move(db, source, data.quantity, document=document, target=to_bucket, out_type="status_out",
                              in_type="status_in", match=match or None, user=user, reason=label)
        event_bus.emit(db, "disposition.recorded", "disposition", disposition.id,
                       {"code": disposition.code, "action": data.action, "product_id": product.id, "quantity": data.quantity,
                        "from_status": data.from_status, "document_code": document.code},
                       organization_id=product.organization_id, actor=user)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get(db, user, disposition.id)


def _serialize(d: Disposition) -> dict:
    return {
        "id": d.id, "code": d.code, "action": d.action, "action_label": DISPOSITION_LABELS[d.action],
        "warehouse_id": d.warehouse_id, "warehouse_name": d.warehouse.name if d.warehouse else None,
        "product_id": d.product_id, "product_name": d.product.name, "product_sku": d.product.sku,
        "location_code": d.location.code if d.location else None, "lot_number": d.lot_number,
        "from_status": d.from_status, "from_status_label": STOCK_STATUS_LABELS[d.from_status], "quantity": d.quantity,
        "partner_name": d.partner.name if d.partner else None, "receipt_id": d.receipt_id, "reason": d.reason,
        "document_id": d.document_id, "document_code": d.document.code if d.document else None,
        "created_at": d.created_at, "created_by_name": (d.created_by.full_name or d.created_by.username) if d.created_by else None,
    }


def _options(query):
    return query.options(joinedload(Disposition.product), joinedload(Disposition.warehouse), joinedload(Disposition.location),
                         joinedload(Disposition.partner), joinedload(Disposition.document), joinedload(Disposition.created_by))


def get(db: Session, user: User, disposition_id: int) -> dict:
    d = _options(db.query(Disposition)).filter(Disposition.id == disposition_id).first()
    if d is None:
        raise NotFoundError("تعیین تکلیف یافت نشد.")
    location_service.scope_warehouse(user, d.warehouse_id)
    return _serialize(d)


def list_dispositions(db: Session, user: User, *, warehouse_id: int | None = None, action: str | None = None) -> list[dict]:
    warehouse_id = location_service.scope_warehouse(user, warehouse_id)
    query = _options(db.query(Disposition))
    if warehouse_id is not None:
        query = query.filter(Disposition.warehouse_id == warehouse_id)
    if action:
        query = query.filter(Disposition.action == action)
    return [_serialize(d) for d in query.order_by(Disposition.id.desc()).limit(200).all()]
