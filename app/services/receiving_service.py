"""
رسید و دریافت کالا (فصل ۷)

چرخه: باز ← در حال دریافت ← بسته؛ لغو فقط پیش از اولین دریافت.
  • خرید (purchase)        از تأمین‌کننده؛ شماره بارنامه/حواله هر تأمین‌کننده یکتاست (جلوگیری از رسید تکراری).
  • انتقال (transfer)      از انبار «در راه»: کالا با سند رسید از انبار در راه برداشته و در مقصد ثبت می‌شود.
  • مرجوعی (return)       از مشتری (اختیاری: سفارش تحویل‌شده مرجع)؛ همیشه «در انتظار بازرسی».
  • پیش‌بینی‌نشده (unexpected) بدون سطر مورد انتظار؛ سطرها هنگام دریافت ساخته می‌شوند.

هر دریافت فیزیکی (receive) یک سند «رسید دریافت کالا» (GR) با گردش‌های ریز (محل، بچ، انقضا، سریال، مالک)
می‌سازد و شمارنده‌های سطر را جلو می‌برد: دریافت‌شده، پذیرفته (تأییدشده)، مردود (آسیب‌دیده هنگام تخلیه).
کالای نیازمند بازرسی «در انتظار بازرسی» می‌ماند تا quality_service نتیجه را ثبت کند.
اضافه تحویل بیش از تلورانس رسید و کالای خارج از برنامه فقط با ذکر دلیل پذیرفته می‌شود؛ هنگام بستن
مغایرت هر سطر (کسری، اضافه، خارج از برنامه) ثبت می‌شود و کسری دلیل می‌خواهد.
تکرار یک درخواست با همان Idempotency-Key رسید یا سند دوم نمی‌سازد؛ دو دریافت هم‌زمان یک رسید با قفل ردیف رسید پشت سر هم اجرا می‌شوند.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.wms import (
    AVAILABLE, DISCREPANCY_LABELS, LOCATION_TYPES, PENDING, RECEIPT_STATUS_LABELS, RECEIPT_TYPE_LABELS,
    STOCK_STATUS_LABELS,
)
from app.models import (
    InboundReceipt, InboundReceiptLine, Location, Order, OrderItem, Partner, Product, PutawayTask, StockBalance,
    StockDocument, User, Warehouse,
)
from app.services import (
    catalog_service, event_bus, location_service, putaway_service, stock_document_service, stock_ledger,
    warehouse_service,
)
from app.services.exceptions import ConflictError, NotFoundError
from app.services.stock_ledger import StockKey


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# اعتبارسنجی
# ---------------------------------------------------------------------------
def _partner(db: Session, partner_id: int | None, *, role: str, label: str, required: bool = False) -> Partner | None:
    if partner_id is None:
        if required:
            raise ConflictError(f"{label} را انتخاب کنید.")
        return None
    partner = db.get(Partner, partner_id)
    if partner is None:
        raise NotFoundError(f"{label} یافت نشد.")
    if not getattr(partner, f"is_{role}") or partner.is_active is False:
        raise ConflictError(f"«{partner.name}» {label} فعال نیست.")
    return partner


def _receiving_location(db: Session, warehouse: Warehouse, location_id: int | None) -> Location | None:
    """محل تخلیه: انتخاب‌شده، یا اولین محل «تخلیه و دریافت» انبار؛ انبار بدون محل تخلیه = بدون محل."""
    if location_id is not None:
        location = location_service.resolve(db, warehouse.id, location_id)
        if not LOCATION_TYPES[location.location_type].receives:
            raise ConflictError(f"محل {location.code} از نوع «{LOCATION_TYPES[location.location_type].label}» است؛ "
                                "رسید فقط در محل تخلیه، آماده‌سازی یا قرنطینه ثبت می‌شود.")
        return location
    return db.query(Location).filter(
        Location.warehouse_id == warehouse.id, Location.location_type == "receiving", Location.is_active.is_not(False),
        Location.is_blocked.is_not(True),
    ).order_by(Location.code).first()


def _needs_inspection(product: Product, receipt: InboundReceipt, warehouse: Warehouse) -> bool:
    if warehouse_service.type_of(warehouse).receipt_status != AVAILABLE:
        return True
    if receipt.receipt_type == "transfer":
        return False                       # کالای انبار خود سازمان قبلاً بازرسی شده است
    return bool(product.inspection_required) or receipt.receipt_type == "return"


def check_tracking(product: Product, quantity: int, lot: str | None, expiry, serials: list[str], *, damaged: bool) -> None:
    if product.lot_tracked and not lot:
        raise ConflictError(f"کالای «{product.name}» بچ‌دار است؛ شماره بچ را وارد کنید.")
    if lot and not product.lot_tracked:
        raise ConflictError(f"کالای «{product.name}» با بچ ردیابی نمی‌شود؛ شماره بچ را خالی بگذارید.")
    if product.expiry_tracked and expiry is None:
        raise ConflictError(f"تاریخ انقضای کالای «{product.name}» را وارد کنید.")
    if expiry is not None and not product.expiry_tracked:
        raise ConflictError(f"کالای «{product.name}» تاریخ انقضا ندارد.")
    if expiry is not None and expiry < catalog_service.today_local() and not damaged:
        raise ConflictError(f"تاریخ انقضای {expiry} گذشته است؛ کالای منقضی را با وضعیت «آسیب‌دیده» دریافت کنید یا نپذیرید.")
    if product.serial_tracked:
        if len(serials) != quantity:
            raise ConflictError(f"کالای «{product.name}» سریال‌دار است؛ برای {quantity} واحد دقیقاً {quantity} شماره سریال لازم است.")
        if len(set(serials)) != len(serials):
            raise ConflictError("شماره سریال تکراری در همین دریافت وارد شده است.")
    elif serials:
        raise ConflictError(f"کالای «{product.name}» سریال‌دار نیست.")


def _check_duplicate(db: Session, partner_id: int | None, external_ref: str | None, receipt_id: int | None = None) -> None:
    if not external_ref:
        return
    query = db.query(InboundReceipt).filter(func.upper(InboundReceipt.external_ref) == external_ref.upper(),
                                            InboundReceipt.status != "canceled")
    query = query.filter(InboundReceipt.partner_id.is_(None) if partner_id is None else InboundReceipt.partner_id == partner_id)
    if receipt_id is not None:
        query = query.filter(InboundReceipt.id != receipt_id)
    existing = query.first()
    if existing is not None:
        raise ConflictError(f"رسید {existing.code} قبلاً با شماره بارنامه/حواله «{existing.external_ref}» برای همین طرف ثبت شده است.")


def _return_order(db: Session, order_id: int | None, warehouse_id: int) -> Order | None:
    if order_id is None:
        return None
    order = db.get(Order, order_id)
    if order is None:
        raise NotFoundError("سفارش مرجع یافت نشد.")
    if order.status != "delivered":
        raise ConflictError("مرجوعی فقط برای سفارش تحویل‌شده ثبت می‌شود (سفارش ناموفق خودکار به انبار برمی‌گردد).")
    return order


# ---------------------------------------------------------------------------
# ساخت رسید
# ---------------------------------------------------------------------------
def create_receipt(db: Session, user: User, data, idempotency_key: str | None = None) -> dict:
    warehouse_id = location_service.scope_warehouse(user, data.warehouse_id)
    if warehouse_id is None:
        raise ConflictError("انبار مقصد را انتخاب کنید.")

    def create(key, digest):
        try:
            warehouse = warehouse_service.for_stock_in(db, warehouse_id, direct_receipt=data.receipt_type != "transfer")
            if data.receipt_type == "purchase":
                partner = _partner(db, data.partner_id, role="supplier", label="تأمین‌کننده", required=True)
            elif data.receipt_type == "return":
                partner = _partner(db, data.partner_id, role="customer", label="مشتری")
            else:
                partner = _partner(db, data.partner_id, role="supplier", label="تأمین‌کننده")
            owner = _partner(db, data.owner_id, role="owner", label="مالک کالا")
            source = None
            if data.receipt_type == "transfer":
                if data.source_warehouse_id is None:
                    raise ConflictError("برای رسید انتقال، انبار در راه (مبدأ) را انتخاب کنید.")
                source = warehouse_service.get(db, data.source_warehouse_id)
                if warehouse_service.type_of(source).code != "transit" or source.id == warehouse.id:
                    raise ConflictError("مبدأ رسید انتقال باید یک «انبار در راه» دیگر باشد؛ کالا ابتدا با انتقال به آن فرستاده می‌شود.")
            elif data.source_warehouse_id is not None:
                raise ConflictError("انبار مبدأ فقط برای رسید انتقال است.")
            order = _return_order(db, data.order_id, warehouse.id) if data.receipt_type == "return" else None
            if data.order_id is not None and data.receipt_type != "return":
                raise ConflictError("سفارش مرجع فقط برای رسید مرجوعی است.")
            _check_duplicate(db, partner.id if partner else None, data.external_ref)
            location = _receiving_location(db, warehouse, data.receiving_location_id) if data.receiving_location_id else None

            if data.receipt_type != "unexpected" and not data.lines:
                raise ConflictError("حداقل یک سطر کالای مورد انتظار وارد کنید.")
            receipt = InboundReceipt(
                code=stock_ledger.new_code(db, InboundReceipt, "IR"), receipt_type=data.receipt_type, status="open",
                warehouse_id=warehouse.id, partner_id=partner.id if partner else None, owner_id=owner.id if owner else None,
                source_warehouse_id=source.id if source else None, order_id=order.id if order else None,
                reference_number=data.reference_number, external_ref=data.external_ref, expected_date=data.expected_date,
                receiving_location_id=location.id if location else None, over_tolerance_pct=data.over_tolerance_pct,
                note=data.note, idempotency_key=key, request_hash=digest, created_at=_now(),
                created_by_id=user.id,
            )
            db.add(receipt)
            ordered = {}
            if order is not None:
                ordered = defaultdict(int)
                for item in db.query(OrderItem).filter(OrderItem.order_id == order.id).all():
                    ordered[item.product_id] += item.quantity
                # مرجوعی‌های قبلی همین سفارش (رسیدهای لغونشده) از سقف کم می‌شوند
                for line, _ in db.query(InboundReceiptLine, InboundReceipt).join(
                        InboundReceipt, InboundReceiptLine.receipt_id == InboundReceipt.id).filter(
                        InboundReceipt.order_id == order.id, InboundReceipt.receipt_type == "return",
                        InboundReceipt.status != "canceled").all():
                    ordered[line.product_id] -= line.expected_quantity
            seen = set()
            for number, entry in enumerate(data.lines, start=1):
                product = db.get(Product, entry.product_id)
                if product is None:
                    raise NotFoundError(f"کالای سطر {number} یافت نشد.")
                if product.is_active is False:
                    raise ConflictError(f"کالای «{product.name}» بایگانی شده است.")
                if (product.id, entry.lot_number) in seen:
                    raise ConflictError(f"کالای «{product.name}» دو بار در رسید آمده است؛ مقدارها را در یک سطر جمع کنید.")
                seen.add((product.id, entry.lot_number))
                expected = catalog_service.to_base(product, entry.expected_quantity, entry.uom)
                if order is not None and expected > ordered.get(product.id, 0):
                    raise ConflictError(f"مقدار مرجوعی «{product.name}» بیشتر از مقدار ارسال‌شده و هنوز برنگشته سفارش "
                                        f"({max(ordered.get(product.id, 0), 0)}) است.")
                receipt.lines.append(InboundReceiptLine(
                    organization_id=user.organization_id, line_no=number, product_id=product.id, expected_quantity=expected,
                    lot_number=entry.lot_number, note=entry.note,
                ))
            db.flush()
            event_bus.emit(db, "inbound.receipt.created", "inbound_receipt", receipt.id,
                           {"code": receipt.code, "receipt_type": receipt.receipt_type, "warehouse_id": receipt.warehouse_id,
                            "partner_id": receipt.partner_id, "external_ref": receipt.external_ref,
                            "lines": [{"product_id": line.product_id, "expected": line.expected_quantity} for line in receipt.lines]},
                           organization_id=receipt.organization_id, actor=user)
            db.commit()
            return receipt
        except Exception:
            db.rollback()
            raise

    receipt, _ = stock_document_service.idempotent(db, InboundReceipt, idempotency_key, "inbound_receipt",
                                                   data.model_dump(mode="json"), create)
    return get_receipt(db, user, receipt.id)


# ---------------------------------------------------------------------------
# دریافت فیزیکی
# ---------------------------------------------------------------------------
def _lock_receipt(db: Session, user: User, receipt_id: int) -> InboundReceipt:
    receipt = db.query(InboundReceipt).filter(InboundReceipt.id == receipt_id).with_for_update().first()
    if receipt is None:
        raise NotFoundError("رسید یافت نشد.")
    location_service.scope_warehouse(user, receipt.warehouse_id)
    return receipt


def _line_for(db: Session, receipt: InboundReceipt, entry) -> InboundReceiptLine:
    if entry.line_id is not None:
        line = next((ln for ln in receipt.lines if ln.id == entry.line_id), None)
        if line is None:
            raise NotFoundError("سطر رسید یافت نشد.")
        return line
    if entry.product_id is None:
        raise ConflictError("برای هر ردیف دریافت، سطر رسید یا کالا را مشخص کنید.")
    existing = next((ln for ln in receipt.lines if ln.product_id == entry.product_id
                     and (ln.lot_number in (None, entry.lot_number))), None)
    if existing is not None:
        return existing
    product = db.get(Product, entry.product_id)
    if product is None or product.is_active is False:
        raise NotFoundError("کالای دریافتی یافت نشد یا بایگانی شده است.")
    if receipt.receipt_type in ("transfer",):
        raise ConflictError("در رسید انتقال فقط کالاهای اعلام‌شده دریافت می‌شوند.")
    if receipt.receipt_type != "unexpected" and not entry.over_reason:
        raise ConflictError(f"«{product.name}» در این رسید نیست؛ برای پذیرش کالای خارج از برنامه، دلیل را بنویسید.")
    line = InboundReceiptLine(organization_id=receipt.organization_id, line_no=len(receipt.lines) + 1,
                              product_id=product.id, expected_quantity=0, over_reason=entry.over_reason)
    receipt.lines.append(line)
    db.flush()
    return line


def _check_over(receipt: InboundReceipt, line: InboundReceiptLine, quantity: int, over_reason: str | None) -> None:
    if receipt.receipt_type == "unexpected" or line.expected_quantity == 0:
        return
    limit = int(line.expected_quantity * (1 + (receipt.over_tolerance_pct or 0) / 100))
    total = line.received_quantity + quantity
    if total > limit:
        if not over_reason:
            raise ConflictError(
                f"اضافه تحویل «{line.product.name}»: مورد انتظار {line.expected_quantity}، با این دریافت {total} "
                f"(حد مجاز {limit}). برای پذیرش اضافه تحویل دلیل را بنویسید یا مقدار اضافه را نپذیرید."
            )
        line.over_reason = over_reason


def _transfer_lines(db: Session, source, product: Product, quantity: int, entry) -> list:
    """رسید انتقال: کالا با همان بچ/سریال/انقضا از انبار در راه برداشته می‌شود."""
    if entry.serial_numbers:
        lines = []
        db.flush()
        for serial in entry.serial_numbers:
            balance = db.query(StockBalance).filter(StockBalance.inventory_id == source.id, StockBalance.serial_number == serial,
                                                    StockBalance.quantity > 0).first()
            if balance is None:
                raise ConflictError(f"سریال {serial} در انبار در راه نیست.")
            lines.append((stock_ledger.key_of(balance), 1))
        return lines
    return stock_ledger.pick_lines(db, source, quantity, match={"lot_number": entry.lot_number} if entry.lot_number else None)


def receive(db: Session, user: User, receipt_id: int, data, idempotency_key: str | None = None) -> dict:
    def create(key, digest):
        try:
            receipt = _lock_receipt(db, user, receipt_id)
            if receipt.status not in ("open", "receiving"):
                raise ConflictError(f"رسید {receipt.code} {RECEIPT_STATUS_LABELS[receipt.status]} است و دریافت جدید نمی‌پذیرد.")
            warehouse = warehouse_service.for_stock_in(db, receipt.warehouse_id, direct_receipt=receipt.receipt_type != "transfer")
            location = _receiving_location(db, warehouse, data.location_id or receipt.receiving_location_id)
            document = stock_ledger.new_document(
                db, "inbound_receipt", organization_id=receipt.organization_id, user=user, warehouse_id=warehouse.id,
                partner_id=receipt.partner_id, reference_type="inbound_receipt", reference_id=receipt.id,
                external_ref=receipt.external_ref, note=data.note or f"دریافت رسید {receipt.code}",
                idempotency_key=key, request_hash=digest,
            )
            movements = []
            for entry in data.lines:
                line = _line_for(db, receipt, entry)
                product = line.product or db.get(Product, line.product_id)
                quantity = catalog_service.to_base(product, entry.quantity, entry.uom)
                damaged = entry.condition == "damaged"
                lot = entry.lot_number or line.lot_number
                _check_over(receipt, line, quantity, entry.over_reason)
                status = "damaged" if damaged else (PENDING if _needs_inspection(product, receipt, warehouse) else AVAILABLE)
                target = stock_ledger.lock_bucket(db, product.id, warehouse.id, status, reorder_point=product.reorder_point)
                reason = f"دریافت رسید {receipt.code}" + (" — آسیب‌دیده هنگام تخلیه" if damaged else "")
                if receipt.receipt_type == "transfer":
                    source = stock_ledger.lock_bucket(db, product.id, receipt.source_warehouse_id, AVAILABLE, create=False)
                    if source is None or source.free_quantity < quantity:
                        raise ConflictError(f"موجودی «{product.name}» در انبار در راه کافی نیست "
                                            f"(موجود: {source.free_quantity if source else 0}، دریافتی: {quantity}).")
                    lines = _transfer_lines(db, source, product, quantity, entry)
                    _, movement = stock_ledger.move(
                        db, source, quantity, document=document, target=target, out_type="transfer_out",
                        in_type="transfer_in", lines=lines,
                        overrides={"location_id": location.id if location else None}, user=user, reason=reason,
                    )
                else:
                    check_tracking(product, quantity, lot, entry.expiry_date, entry.serial_numbers, damaged=damaged)
                    base = StockKey(location_id=location.id if location else None, owner_id=receipt.owner_id,
                                    lot_number=lot, expiry_date=entry.expiry_date)
                    lines = [(base.with_(serial_number=s), 1) for s in entry.serial_numbers] or [(base, quantity)]
                    movement = stock_ledger.record(db, target, quantity, "receipt", document=document, lines=lines,
                                                   user=user, reason=reason)
                line.received_quantity += quantity
                if status == AVAILABLE:
                    line.accepted_quantity += quantity
                elif damaged:
                    line.rejected_quantity += quantity
                movements.append(movement)
            if receipt.status == "open":
                receipt.status, receipt.received_at = "receiving", _now()
            db.flush()
            for movement in movements:
                putaway_service.tasks_for_movement(db, user, movement, receipt_id=receipt.id)
            event_bus.emit(db, "inbound.receipt.received", "inbound_receipt", receipt.id,
                           {"code": receipt.code, "document_code": document.code,
                            "lines": [{"product_id": m.product_id, "stock_status": m.stock_status, "quantity": m.quantity_change}
                                      for m in movements]},
                           organization_id=receipt.organization_id, actor=user)
            db.commit()
            return document
        except Exception:
            db.rollback()
            raise

    stock_document_service.idempotent(db, StockDocument, idempotency_key, f"receive:{receipt_id}",
                                      data.model_dump(mode="json"), create)
    return get_receipt(db, user, receipt_id)


# ---------------------------------------------------------------------------
# بستن و لغو
# ---------------------------------------------------------------------------
def close(db: Session, user: User, receipt_id: int, data) -> dict:
    try:
        receipt = _lock_receipt(db, user, receipt_id)
        if receipt.status not in ("open", "receiving"):
            raise ConflictError(f"رسید {receipt.code} {RECEIPT_STATUS_LABELS[receipt.status]} است.")
        reasons = {int(k): v for k, v in (data.reasons or {}).items()}
        discrepancies = []
        for line in receipt.lines:
            diff = line.received_quantity - line.expected_quantity
            if line.expected_quantity == 0 and line.received_quantity > 0 and receipt.receipt_type != "unexpected":
                kind, amount = "unexpected_item", line.received_quantity
            elif diff < 0:
                kind, amount = "shortage", -diff
            elif diff > 0 and receipt.receipt_type != "unexpected":
                kind, amount = "over", diff
            else:
                continue
            reason = reasons.get(line.id) or line.over_reason or data.note
            if kind == "shortage" and not reason:
                raise ConflictError(f"کسری «{line.product.name}» ({amount} عدد) دلیل می‌خواهد؛ دلیل سطر یا توضیح کلی بستن را بنویسید.")
            line.discrepancy_type, line.discrepancy_quantity, line.discrepancy_reason = kind, amount, (reason or "")[:300] or None
            discrepancies.append({"line_id": line.id, "product_id": line.product_id, "type": kind, "quantity": amount})
        receipt.status, receipt.closed_at, receipt.closed_by_id, receipt.close_note = "closed", _now(), user.id, data.note
        event_bus.emit(db, "inbound.receipt.closed", "inbound_receipt", receipt.id,
                       {"code": receipt.code, "discrepancies": discrepancies},
                       organization_id=receipt.organization_id, actor=user)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_receipt(db, user, receipt_id)


def cancel(db: Session, user: User, receipt_id: int, reason: str) -> dict:
    try:
        receipt = _lock_receipt(db, user, receipt_id)
        if receipt.status != "open" or any(line.received_quantity for line in receipt.lines):
            raise ConflictError("فقط رسیدی که هنوز هیچ کالایی از آن دریافت نشده لغو می‌شود؛ رسید در حال دریافت را با ثبت کسری ببندید.")
        receipt.status, receipt.closed_at, receipt.closed_by_id, receipt.close_note = "canceled", _now(), user.id, reason
        event_bus.emit(db, "inbound.receipt.canceled", "inbound_receipt", receipt.id, {"code": receipt.code, "reason": reason},
                       organization_id=receipt.organization_id, actor=user)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_receipt(db, user, receipt_id)


# ---------------------------------------------------------------------------
# خواندن
# ---------------------------------------------------------------------------
def _serialize(receipt: InboundReceipt, documents: list[StockDocument] | None = None, tasks: list[PutawayTask] | None = None,
               with_lines: bool = True) -> dict:
    lines = receipt.lines
    return {
        "id": receipt.id, "code": receipt.code, "receipt_type": receipt.receipt_type,
        "receipt_type_label": RECEIPT_TYPE_LABELS[receipt.receipt_type], "status": receipt.status,
        "status_label": RECEIPT_STATUS_LABELS[receipt.status], "warehouse_id": receipt.warehouse_id,
        "warehouse_name": receipt.warehouse.name if receipt.warehouse else None,
        "partner_id": receipt.partner_id, "partner_name": receipt.partner.name if receipt.partner else None,
        "owner_id": receipt.owner_id, "owner_name": receipt.owner.name if receipt.owner else None,
        "source_warehouse_id": receipt.source_warehouse_id,
        "source_warehouse_name": receipt.source_warehouse.name if receipt.source_warehouse else None,
        "order_id": receipt.order_id, "reference_number": receipt.reference_number, "external_ref": receipt.external_ref,
        "expected_date": receipt.expected_date, "receiving_location_id": receipt.receiving_location_id,
        "receiving_location_code": receipt.receiving_location.code if receipt.receiving_location else None,
        "over_tolerance_pct": receipt.over_tolerance_pct, "note": receipt.note, "created_at": receipt.created_at,
        "created_by_name": (receipt.created_by.full_name or receipt.created_by.username) if receipt.created_by else None,
        "received_at": receipt.received_at, "closed_at": receipt.closed_at, "close_note": receipt.close_note,
        "total_expected": sum(ln.expected_quantity for ln in lines), "total_received": sum(ln.received_quantity for ln in lines),
        "total_accepted": sum(ln.accepted_quantity for ln in lines), "total_rejected": sum(ln.rejected_quantity for ln in lines),
        "total_pending_inspection": sum(ln.pending_inspection for ln in lines),
        "total_outstanding": sum(ln.outstanding for ln in lines),
        "has_discrepancy": any(ln.discrepancy_type for ln in lines),
        "lines": [{
            "id": ln.id, "line_no": ln.line_no, "product_id": ln.product_id, "product_name": ln.product.name,
            "product_sku": ln.product.sku, "unit": ln.product.unit or "عدد", "lot_tracked": bool(ln.product.lot_tracked),
            "expiry_tracked": bool(ln.product.expiry_tracked), "serial_tracked": bool(ln.product.serial_tracked),
            "inspection_required": bool(ln.product.inspection_required),
            "expected_quantity": ln.expected_quantity, "received_quantity": ln.received_quantity,
            "accepted_quantity": ln.accepted_quantity, "rejected_quantity": ln.rejected_quantity,
            "pending_inspection": ln.pending_inspection, "outstanding": ln.outstanding, "lot_number": ln.lot_number,
            "note": ln.note, "over_reason": ln.over_reason, "discrepancy_type": ln.discrepancy_type,
            "discrepancy_label": DISCREPANCY_LABELS.get(ln.discrepancy_type) if ln.discrepancy_type else None,
            "discrepancy_quantity": ln.discrepancy_quantity, "discrepancy_reason": ln.discrepancy_reason,
        } for ln in lines] if with_lines else [],
        "documents": [{"id": d.id, "code": d.code, "created_at": d.created_at,
                       "total": sum(m.quantity_change for m in d.movements if m.quantity_change > 0 and m.warehouse_id == receipt.warehouse_id)}
                      for d in (documents or [])],
        "putaway_tasks": [{"id": t.id, "code": t.code, "status": t.status, "product_name": t.product.name,
                           "quantity": t.quantity, "quantity_done": t.quantity_done,
                           "stock_status_label": STOCK_STATUS_LABELS.get(t.stock_status, t.stock_status)}
                          for t in (tasks or [])],
    }


def _options(query):
    return query.options(
        selectinload(InboundReceipt.lines).joinedload(InboundReceiptLine.product), joinedload(InboundReceipt.warehouse),
        joinedload(InboundReceipt.partner), joinedload(InboundReceipt.owner), joinedload(InboundReceipt.source_warehouse),
        joinedload(InboundReceipt.receiving_location), joinedload(InboundReceipt.created_by),
    )


def get_receipt(db: Session, user: User, receipt_id: int) -> dict:
    receipt = _options(db.query(InboundReceipt)).filter(InboundReceipt.id == receipt_id).first()
    if receipt is None:
        raise NotFoundError("رسید یافت نشد.")
    location_service.scope_warehouse(user, receipt.warehouse_id)
    documents = db.query(StockDocument).options(selectinload(StockDocument.movements)).filter(
        StockDocument.reference_type == "inbound_receipt", StockDocument.reference_id == receipt.id,
        StockDocument.doc_type == "inbound_receipt").order_by(StockDocument.id).all()
    tasks = db.query(PutawayTask).options(joinedload(PutawayTask.product)).filter(
        PutawayTask.receipt_id == receipt.id).order_by(PutawayTask.id).all()
    return _serialize(receipt, documents, tasks)


def list_receipts(db: Session, user: User, *, status: str | None = None, receipt_type: str | None = None,
                  warehouse_id: int | None = None, q: str | None = None, skip: int = 0, limit: int = 50) -> list[dict]:
    warehouse_id = location_service.scope_warehouse(user, warehouse_id)
    query = _options(db.query(InboundReceipt))
    if warehouse_id is not None:
        query = query.filter(InboundReceipt.warehouse_id == warehouse_id)
    if status:
        query = query.filter(InboundReceipt.status == status)
    if receipt_type:
        query = query.filter(InboundReceipt.receipt_type == receipt_type)
    if q:
        term = f"%{q.strip()}%"
        query = query.filter(InboundReceipt.code.ilike(term) | InboundReceipt.external_ref.ilike(term)
                             | InboundReceipt.reference_number.ilike(term))
    receipts = query.order_by(InboundReceipt.id.desc()).offset(skip).limit(limit).all()
    return [_serialize(r, with_lines=False) for r in receipts]


def attribute_inspection(db: Session, *, product_id: int, warehouse_id: int, receipt_id: int | None,
                         accepted: int, rejected: int) -> None:
    """نتیجه بازرسی را (به ترتیب قدیمی‌ترین) به سطرهای رسیدِ در انتظار بازرسی همان کالا و انبار نسبت می‌دهد."""
    query = db.query(InboundReceiptLine).join(InboundReceipt, InboundReceiptLine.receipt_id == InboundReceipt.id).filter(
        InboundReceiptLine.product_id == product_id, InboundReceipt.warehouse_id == warehouse_id,
        InboundReceipt.status != "canceled",
    )
    if receipt_id is not None:
        query = query.filter(InboundReceipt.id == receipt_id)
    for line in query.order_by(InboundReceipt.id, InboundReceiptLine.id).with_for_update().all():
        room = line.pending_inspection
        if room <= 0:
            continue
        take = min(room, accepted)
        line.accepted_quantity += take
        accepted -= take
        room -= take
        take = min(room, rejected)
        line.rejected_quantity += take
        rejected -= take
        if accepted <= 0 and rejected <= 0:
            break
