"""
سفارش انتقال دومرحله‌ای — فصل ۱۲

  ساخت (open)      مبدأ، مقصد و اقلام؛ هنوز اثری روی موجودی ندارد.
  ارسال (ship)     کالا از مبدأ (محل/بچ انتخابی یا FEFO) کم و در انبار مقصد با وضعیت «در راه» ثبت می‌شود (سند TS):
                   همیشه معلوم است کالا کجاست و قابل تخصیص نیست.
  دریافت (receive) مقدار سالم به وضعیت تأییدشده در محل مقصد و مقدار آسیب‌دیده به «آسیب‌دیده» (سند TV)؛
                   ظرفیت و قاعده اختلاط محل مقصد در دفتر گردش کنترل می‌شود. دریافت چندمرحله‌ای مجاز است.
  بستن (close)     کسری باقی‌مانده در راه با دلیل یا ضایعات (کسری حمل) می‌شود یا به مبدأ برمی‌گردد.

انتقال داخلی دومرحله‌ای (مبدأ و مقصد یک انبار، دو محل) هم با همین چرخه انجام می‌شود؛ انتقال تک‌مرحله‌ای همان
POST /inventory/transfers و جابه‌جایی بین محل‌ها (MV) است.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.wms import AVAILABLE, IN_TRANSIT, TRANSFER_STATUS_LABELS
from app.models import Product, StockDocument, TransferOrder, TransferOrderLine, User
from app.services import (
    catalog_service, event_bus, location_service, stock_document_service, stock_ledger, warehouse_service,
)
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _role(user: User) -> str:
    return getattr(user.role, "value", user.role)


def _ensure_side(user: User, warehouse_id: int) -> None:
    """مدیر انبار ارسال را فقط از انبار خودش و دریافت را فقط در انبار خودش انجام می‌دهد."""
    location_service.ensure_staff(user)
    if _role(user) == "warehouse_manager" and user.warehouse_id != warehouse_id:
        raise ForbiddenError("این مرحله مربوط به انبار دیگری است.")


def create(db: Session, user: User, data, idempotency_key: str | None = None) -> dict:
    location_service.ensure_staff(user)
    if _role(user) == "warehouse_manager" and data.from_warehouse_id != user.warehouse_id:
        raise ForbiddenError("مدیر انبار فقط از انبار خودش سفارش انتقال می‌سازد.")

    def build(key, digest):
        try:
            warehouse_service.get(db, data.from_warehouse_id)
            target = warehouse_service.for_stock_in(db, data.to_warehouse_id)
            if warehouse_service.type_of(target).code == "transit":
                raise ConflictError("مقصد سفارش انتقال نمی‌تواند «انبار در راه» باشد؛ وضعیت «در راه» خودکار است.")
            location_service.resolve(db, data.from_warehouse_id, data.from_location_id)
            location_service.resolve(db, data.to_warehouse_id, data.to_location_id)
            if data.from_warehouse_id == data.to_warehouse_id and (
                    data.from_location_id is None or data.to_location_id is None or data.from_location_id == data.to_location_id):
                raise ConflictError("انتقال داخلی دومرحله‌ای به محل مبدأ و مقصدِ متفاوت نیاز دارد.")
            transfer = TransferOrder(
                code=stock_ledger.new_code(db, TransferOrder, "TO"), status="open", from_warehouse_id=data.from_warehouse_id,
                to_warehouse_id=data.to_warehouse_id, from_location_id=data.from_location_id, to_location_id=data.to_location_id,
                note=data.note, idempotency_key=key, request_hash=digest, created_at=_now(), created_by_id=user.id)
            db.add(transfer)
            seen = set()
            for entry in data.lines:
                product = db.get(Product, entry.product_id)
                if product is None:
                    raise NotFoundError("کالا یافت نشد.")
                if (product.id, entry.lot_number) in seen:
                    raise ConflictError(f"«{product.name}» دو بار آمده است.")
                seen.add((product.id, entry.lot_number))
                transfer.lines.append(TransferOrderLine(
                    organization_id=user.organization_id, product_id=product.id, lot_number=entry.lot_number,
                    quantity=catalog_service.to_base(product, entry.quantity, entry.uom)))
            db.flush()
            event_bus.emit(db, "transfer.created", "transfer_order", transfer.id,
                           {"code": transfer.code, "from": transfer.from_warehouse_id, "to": transfer.to_warehouse_id},
                           organization_id=transfer.organization_id, actor=user)
            db.commit()
            return transfer
        except Exception:
            db.rollback()
            raise

    transfer, _ = stock_document_service.idempotent(db, TransferOrder, idempotency_key, "transfer_order",
                                                    data.model_dump(mode="json"), build)
    return get(db, user, transfer.id)


def _lock(db: Session, transfer_id: int) -> TransferOrder:
    transfer = db.query(TransferOrder).filter(TransferOrder.id == transfer_id).with_for_update().first()
    if transfer is None:
        raise NotFoundError("سفارش انتقال یافت نشد.")
    return transfer


def ship(db: Session, user: User, transfer_id: int, idempotency_key: str | None = None) -> dict:
    def run(key, digest):
        try:
            transfer = _lock(db, transfer_id)
            _ensure_side(user, transfer.from_warehouse_id)
            if transfer.status != "open":
                raise ConflictError(f"سفارش انتقال {transfer.code} «{TRANSFER_STATUS_LABELS[transfer.status]}» است.")
            document = stock_ledger.new_document(
                db, "transfer_ship", organization_id=transfer.organization_id, user=user,
                warehouse_id=transfer.from_warehouse_id, reference_type="transfer_order", reference_id=transfer.id,
                note=f"ارسال {transfer.code}", idempotency_key=key, request_hash=digest)
            for line in transfer.lines:
                source = stock_ledger.lock_bucket(db, line.product_id, transfer.from_warehouse_id, AVAILABLE, create=False)
                if source is None or source.free_quantity < line.quantity:
                    raise ConflictError(f"موجودی آزاد «{line.product.name}» در مبدأ کافی نیست "
                                        f"(آزاد: {source.free_quantity if source else 0}، انتقال: {line.quantity}).")
                target = stock_ledger.lock_bucket(db, line.product_id, transfer.to_warehouse_id, IN_TRANSIT)
                match = {k: v for k, v in (("location_id", transfer.from_location_id), ("lot_number", line.lot_number)) if v}
                stock_ledger.move(db, source, line.quantity, document=document, target=target, out_type="transfer_out",
                                  in_type="transfer_in", match=match or None, overrides={"location_id": None},
                                  user=user, reason=f"ارسال {transfer.code}", reference_type="transfer_order",
                                  reference_id=transfer.id)
                line.shipped_quantity = line.quantity
            transfer.status, transfer.shipped_at = "in_transit", _now()
            event_bus.emit(db, "transfer.shipped", "transfer_order", transfer.id,
                           {"code": transfer.code, "document_code": document.code},
                           organization_id=transfer.organization_id, actor=user)
            db.commit()
            return document
        except Exception:
            db.rollback()
            raise

    stock_document_service.idempotent(db, StockDocument, idempotency_key, f"transfer_ship:{transfer_id}", {}, run)
    return get(db, user, transfer_id)


def receive(db: Session, user: User, transfer_id: int, data, idempotency_key: str | None = None) -> dict:
    def run(key, digest):
        try:
            transfer = _lock(db, transfer_id)
            _ensure_side(user, transfer.to_warehouse_id)
            if transfer.status != "in_transit":
                raise ConflictError(f"سفارش انتقال {transfer.code} در راه نیست.")
            location_id = data.location_id or transfer.to_location_id
            location_service.resolve(db, transfer.to_warehouse_id, location_id)
            document = stock_ledger.new_document(
                db, "transfer_receive", organization_id=transfer.organization_id, user=user,
                warehouse_id=transfer.to_warehouse_id, reference_type="transfer_order", reference_id=transfer.id,
                note=data.note or f"دریافت {transfer.code}", idempotency_key=key, request_hash=digest)
            lines = {line.id: line for line in transfer.lines}
            for entry in data.lines:
                line = lines.get(entry.line_id)
                if line is None:
                    raise NotFoundError("سطر سفارش انتقال یافت نشد.")
                total = entry.received_quantity + entry.damaged_quantity
                if total == 0:
                    continue
                if total > line.in_transit:
                    raise ConflictError(f"از «{line.product.name}» فقط {line.in_transit} عدد در راه است.")
                transit = stock_ledger.lock_bucket(db, line.product_id, transfer.to_warehouse_id, IN_TRANSIT, create=False)
                for status, quantity in ((AVAILABLE, entry.received_quantity), ("damaged", entry.damaged_quantity)):
                    if not quantity:
                        continue
                    target = stock_ledger.lock_bucket(db, line.product_id, transfer.to_warehouse_id, status)
                    stock_ledger.move(db, transit, quantity, document=document, target=target, out_type="status_out",
                                      in_type="status_in", match={"lot_number": line.lot_number} if line.lot_number else None,
                                      overrides={"location_id": location_id}, user=user,
                                      reason=f"دریافت {transfer.code}" + (" — آسیب‌دیده در حمل" if status == "damaged" else ""),
                                      reference_type="transfer_order", reference_id=transfer.id)
                line.received_quantity += entry.received_quantity
                line.damaged_quantity += entry.damaged_quantity
                if entry.damaged_quantity and entry.reason:
                    line.discrepancy_reason = entry.reason[:300]
            if all(line.in_transit == 0 for line in transfer.lines):
                transfer.status = "received"
            transfer.received_at = _now()
            event_bus.emit(db, "transfer.received", "transfer_order", transfer.id,
                           {"code": transfer.code, "document_code": document.code,
                            "lines": [{"line_id": e.line_id, "received": e.received_quantity, "damaged": e.damaged_quantity}
                                      for e in data.lines]}, organization_id=transfer.organization_id, actor=user)
            db.commit()
            return document
        except Exception:
            db.rollback()
            raise

    stock_document_service.idempotent(db, StockDocument, idempotency_key, f"transfer_receive:{transfer_id}",
                                      data.model_dump(mode="json"), run)
    return get(db, user, transfer_id)


def close(db: Session, user: User, transfer_id: int, data) -> dict:
    """کسری باقی‌مانده در راه: ضایعات (کسری حمل) یا برگشت به مبدأ؛ سپس سفارش بسته می‌شود."""
    try:
        transfer = _lock(db, transfer_id)
        location_service.ensure_staff(user)
        if _role(user) == "warehouse_manager" and user.warehouse_id not in (transfer.from_warehouse_id, transfer.to_warehouse_id):
            raise ForbiddenError("این سفارش انتقال مربوط به انبار شما نیست.")
        if transfer.status not in ("in_transit", "received"):
            raise ConflictError(f"سفارش انتقال {transfer.code} «{TRANSFER_STATUS_LABELS[transfer.status]}» است.")
        open_lines = [line for line in transfer.lines if line.in_transit > 0]
        if open_lines and not data.reason:
            raise ConflictError("برای کسری در راه دلیل بنویسید.")
        if open_lines:
            doc_type = "write_off" if data.resolution == "write_off" else "transfer_ship"
            document = stock_ledger.new_document(
                db, doc_type, organization_id=transfer.organization_id, user=user, warehouse_id=transfer.to_warehouse_id,
                reference_type="transfer_order", reference_id=transfer.id, note=f"کسری {transfer.code}: {data.reason}")
            for line in open_lines:
                missing = line.in_transit
                transit = stock_ledger.lock_bucket(db, line.product_id, transfer.to_warehouse_id, IN_TRANSIT, create=False)
                if data.resolution == "write_off":
                    stock_ledger.record(db, transit, -missing, "damage", document=document, user=user,
                                        reason=f"کسری حمل {transfer.code}: {data.reason}",
                                        match={"lot_number": line.lot_number} if line.lot_number else None)
                else:
                    origin = stock_ledger.lock_bucket(db, line.product_id, transfer.from_warehouse_id, AVAILABLE)
                    stock_ledger.move(db, transit, missing, document=document, target=origin, out_type="transfer_out",
                                      in_type="transfer_in", match={"lot_number": line.lot_number} if line.lot_number else None,
                                      overrides={"location_id": transfer.from_location_id}, user=user,
                                      reason=f"برگشت کسری {transfer.code} به مبدأ: {data.reason}")
                line.resolved_quantity += missing
                line.discrepancy_reason = (line.discrepancy_reason or data.reason)[:300]
        transfer.status, transfer.closed_at = "closed", _now()
        transfer.close_note, transfer.resolution = data.reason, data.resolution if open_lines else None
        event_bus.emit(db, "transfer.closed", "transfer_order", transfer.id,
                       {"code": transfer.code, "resolution": transfer.resolution,
                        "shortages": [{"product_id": ln.product_id, "quantity": ln.resolved_quantity} for ln in open_lines]},
                       organization_id=transfer.organization_id, actor=user)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get(db, user, transfer_id)


def cancel(db: Session, user: User, transfer_id: int) -> dict:
    try:
        transfer = _lock(db, transfer_id)
        _ensure_side(user, transfer.from_warehouse_id)
        if transfer.status != "open":
            raise ConflictError("فقط سفارش انتقالی که هنوز ارسال نشده لغو می‌شود.")
        transfer.status, transfer.closed_at = "canceled", _now()
        event_bus.emit(db, "transfer.canceled", "transfer_order", transfer.id, {"code": transfer.code},
                       organization_id=transfer.organization_id, actor=user)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get(db, user, transfer_id)


def _serialize(t: TransferOrder) -> dict:
    return {
        "id": t.id, "code": t.code, "status": t.status, "status_label": TRANSFER_STATUS_LABELS[t.status],
        "from_warehouse_id": t.from_warehouse_id, "from_warehouse_name": t.from_warehouse.name,
        "to_warehouse_id": t.to_warehouse_id, "to_warehouse_name": t.to_warehouse.name,
        "from_location_code": t.from_location.code if t.from_location else None,
        "to_location_id": t.to_location_id, "to_location_code": t.to_location.code if t.to_location else None,
        "internal": t.from_warehouse_id == t.to_warehouse_id, "note": t.note, "created_at": t.created_at,
        "shipped_at": t.shipped_at, "received_at": t.received_at, "closed_at": t.closed_at, "close_note": t.close_note,
        "resolution": t.resolution,
        "lines": [{"id": ln.id, "product_id": ln.product_id, "product_name": ln.product.name, "product_sku": ln.product.sku,
                   "lot_number": ln.lot_number, "quantity": ln.quantity, "shipped_quantity": ln.shipped_quantity,
                   "received_quantity": ln.received_quantity, "damaged_quantity": ln.damaged_quantity,
                   "resolved_quantity": ln.resolved_quantity, "in_transit": ln.in_transit,
                   "discrepancy_reason": ln.discrepancy_reason} for ln in t.lines],
    }


def _options(query):
    return query.options(selectinload(TransferOrder.lines).joinedload(TransferOrderLine.product),
                         joinedload(TransferOrder.from_warehouse), joinedload(TransferOrder.to_warehouse),
                         joinedload(TransferOrder.from_location), joinedload(TransferOrder.to_location))


def get(db: Session, user: User, transfer_id: int) -> dict:
    location_service.ensure_staff(user)
    transfer = _options(db.query(TransferOrder)).filter(TransferOrder.id == transfer_id).first()
    if transfer is None or (_role(user) == "warehouse_manager"
                            and user.warehouse_id not in (transfer.from_warehouse_id, transfer.to_warehouse_id)):
        raise NotFoundError("سفارش انتقال یافت نشد.")
    return _serialize(transfer)


def list_transfers(db: Session, user: User, *, status: str | None = None) -> list[dict]:
    location_service.ensure_staff(user)
    query = _options(db.query(TransferOrder))
    if _role(user) == "warehouse_manager":
        query = query.filter((TransferOrder.from_warehouse_id == user.warehouse_id) | (TransferOrder.to_warehouse_id == user.warehouse_id))
    if status:
        query = query.filter(TransferOrder.status == status)
    return [_serialize(t) for t in query.order_by(TransferOrder.id.desc()).limit(200).all()]
