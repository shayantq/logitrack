"""
موجودی چندبعدی و کاردکس (فصل ۱۰) — فقط خواندن؛ همه اعداد از دفتر گردش کالا و ردیف‌های ریز می‌آیند.

وضعیت‌های مقدار برای هر کالا × انبار:
  on_hand              موجودی فیزیکی (همه وضعیت‌های کیفی، شامل رزروشده)
  approved             تأییدشده (سالم)
  allocatable          قابل تخصیص: تأییدشده، در محل نگهداری/برداشت، منقضی‌نشده، مال خود سازمان
  reserved             رزرو سفارش‌های باز
  available            قابل وعده = قابل تخصیص − رزرو
  pending_inspection   در انتظار بازرسی
  quarantine           نگه‌داشته: قرنطینه، توقیف، مردود، معیوب، آسیب‌دیده
  not_put_away         تأییدشده ولی هنوز در محل تخلیه/آماده‌سازی/ارسال یا قرنطینه
  expired · consigned  تأییدشده‌ی منقضی · کالای امانی مالک دیگر
  in_transit           انبار «در راه»: کل موجودی آن؛ انبارهای دیگر: باقی‌مانده رسیدهای انتقالِ باز به این انبار
  inbound_expected     باقی‌مانده رسیدهای خرید/مرجوعیِ باز

کاردکس: کارت گردش یک کالا (اختیاری: یک انبار، محل، بچ یا وضعیت) با مانده اول دوره، ورود، خروج و مانده
پس از هر سند. گردش‌های داخلی که در محدوده انتخاب‌شده خالص صفرند (مثلاً جانمایی در کاردکس کل انبار) حذف می‌شوند.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time

from sqlalchemy.orm import Session, joinedload

from app.core.wms import (
    AVAILABLE, DOCUMENT_TYPES, HELD_STATUSES, IN_TRANSIT, PENDING, STOCK_STATUS_LABELS, WAREHOUSE_TYPES,
)
from app.models import (
    InboundReceipt, InboundReceiptLine, Inventory, Location, Product, StockBalance, StockDocument, StockMovement,
    StockMovementLine, User, Warehouse,
)
from app.services import allocation_service, catalog_service, dispatch_service, location_service
from app.services.exceptions import NotFoundError

OPEN_RECEIPT_STATUSES = ("open", "receiving")
KARDEX_LIMIT = 1000


def _local_start(day: date) -> datetime:
    return dispatch_service.local_to_utc(datetime.combine(day, time()))


def _outstanding(db: Session, product_ids, warehouse_id: int | None) -> dict[tuple[int, int, str], int]:
    """باقی‌مانده رسیدهای باز به تفکیک (کالا، انبار، نوع رسید)."""
    query = db.query(InboundReceiptLine, InboundReceipt).join(InboundReceipt, InboundReceiptLine.receipt_id == InboundReceipt.id) \
        .filter(InboundReceipt.status.in_(OPEN_RECEIPT_STATUSES))
    if product_ids is not None:
        query = query.filter(InboundReceiptLine.product_id.in_(list(product_ids) or [-1]))
    if warehouse_id is not None:
        query = query.filter(InboundReceipt.warehouse_id == warehouse_id)
    result: dict[tuple[int, int, str], int] = defaultdict(int)
    for line, receipt in query.all():
        result[(line.product_id, receipt.warehouse_id, receipt.receipt_type)] += line.outstanding
    return result


def positions(db: Session, user: User, *, product_id: int | None = None, warehouse_id: int | None = None) -> list[dict]:
    warehouse_id = location_service.scope_warehouse(user, warehouse_id)
    db.flush()
    query = db.query(Inventory).options(joinedload(Inventory.product), joinedload(Inventory.warehouse))
    if product_id is not None:
        query = query.filter(Inventory.product_id == product_id)
    if warehouse_id is not None:
        query = query.filter(Inventory.warehouse_id == warehouse_id)
    inventories = query.all()
    by_id = {inv.id: inv for inv in inventories}
    balances = db.query(StockBalance).filter(StockBalance.inventory_id.in_(list(by_id) or [-1]), StockBalance.quantity > 0).all()
    locations = {loc.id: loc for loc in db.query(Location).filter(
        Location.id.in_({b.location_id for b in balances if b.location_id} or {-1})).all()}
    outstanding = _outstanding(db, {inv.product_id for inv in inventories}, warehouse_id)
    today = catalog_service.today_local()

    groups: dict[tuple[int, int], dict] = {}
    for inv in sorted(inventories, key=lambda i: (i.product_id, i.warehouse_id)):
        key = (inv.product_id, inv.warehouse_id)
        if key not in groups:
            wh = inv.warehouse
            kind = WAREHOUSE_TYPES.get(wh.type if wh else "general", WAREHOUSE_TYPES["general"])
            groups[key] = {
                "product_id": inv.product_id, "product_name": inv.product.name, "product_sku": inv.product.sku,
                "unit": inv.product.unit or "عدد", "warehouse_id": inv.warehouse_id,
                "warehouse_name": wh.name if wh else "—", "warehouse_type": kind.code,
                "on_hand": 0, "approved": 0, "allocatable": 0, "reserved": 0, "available": 0, "pending_inspection": 0,
                "quarantine": 0, "not_put_away": 0, "expired": 0, "consigned": 0, "in_transit": 0,
                "inbound_expected": 0, "by_status": {}, "picked": 0, "transit_status": 0,
            }
        row = groups[key]
        qty = inv.quantity or 0
        row["on_hand"] += qty
        if qty:
            row["by_status"][inv.stock_status] = row["by_status"].get(inv.stock_status, 0) + qty
        if inv.stock_status == AVAILABLE:
            row["approved"] += qty
            row["reserved"] += inv.reserved_quantity or 0
        elif inv.stock_status == PENDING:
            row["pending_inspection"] += qty
        elif inv.stock_status in HELD_STATUSES:
            row["quarantine"] += qty
        elif inv.stock_status == IN_TRANSIT:
            row["transit_status"] += qty

    for b in balances:
        if b.stock_status != AVAILABLE:
            continue
        row = groups[(b.product_id, b.warehouse_id)]
        location = locations.get(b.location_id)
        expired = b.expiry_date is not None and b.expiry_date < today
        if b.owner_id is not None:
            row["consigned"] += b.quantity
        elif expired:
            row["expired"] += b.quantity
        elif not location_service.is_allocatable(location):
            row["not_put_away"] += b.quantity
        else:
            row["allocatable"] += b.quantity

    # برداشت‌شده و منتقل‌شده به آماده‌سازی: پوشش رزرو همان سفارش (از «در انتظار جانمایی» به «برداشت‌شده»)
    staged = allocation_service.staged_map(db, [inv.id for inv in inventories])
    for inv in inventories:
        if inv.id in staged:
            row = groups[(inv.product_id, inv.warehouse_id)]
            row["picked"] += staged[inv.id]
            row["not_put_away"] = max(row["not_put_away"] - staged[inv.id], 0)
    for row in groups.values():
        row["available"] = max(row["allocatable"] + row["picked"] - row["reserved"], 0)
        if row["warehouse_type"] == "transit":
            row["in_transit"] = row["on_hand"]
        else:
            # سفارش انتقال (وضعیت «در راه» در همین انبار) + رسید انتقالِ باز از انبار در راه
            row["in_transit"] = row["transit_status"] + outstanding.get((row["product_id"], row["warehouse_id"], "transfer"), 0)
        row.pop("transit_status")
        row["inbound_expected"] = sum(v for (p, w, t), v in outstanding.items()
                                      if p == row["product_id"] and w == row["warehouse_id"] and t != "transfer")
    return list(groups.values())


def balances(db: Session, user: User, *, product_id: int | None = None, warehouse_id: int | None = None,
             location_id: int | None = None, stock_status: str | None = None, lot_number: str | None = None,
             limit: int = 500) -> list[dict]:
    """ردیف‌های ریز موجودی (محل × بچ × سریال × مالک × انقضا) — مبنای جانمایی، بازرسی و برداشت."""
    warehouse_id = location_service.scope_warehouse(user, warehouse_id)
    query = db.query(StockBalance).options(
        joinedload(StockBalance.product), joinedload(StockBalance.location), joinedload(StockBalance.owner),
    ).filter(StockBalance.quantity > 0)
    for column, value in ((StockBalance.product_id, product_id), (StockBalance.warehouse_id, warehouse_id),
                          (StockBalance.location_id, location_id), (StockBalance.stock_status, stock_status),
                          (StockBalance.lot_number, lot_number)):
        if value is not None:
            query = query.filter(column == value)
    rows = query.order_by(StockBalance.product_id, StockBalance.warehouse_id, StockBalance.expiry_date, StockBalance.id) \
        .limit(limit).all()
    warehouses = {w.id: w.name for w in db.query(Warehouse).all()}
    today = catalog_service.today_local()
    return [{
        "balance_id": b.id, "inventory_id": b.inventory_id, "product_id": b.product_id, "product_name": b.product.name,
        "product_sku": b.product.sku, "unit": b.product.unit or "عدد", "warehouse_id": b.warehouse_id,
        "warehouse_name": warehouses.get(b.warehouse_id), "stock_status": b.stock_status,
        "stock_status_label": STOCK_STATUS_LABELS.get(b.stock_status, b.stock_status),
        "location_id": b.location_id, "location_code": b.location.code if b.location else None,
        "location_type": b.location.location_type if b.location else None,
        "lot_number": b.lot_number, "serial_number": b.serial_number, "expiry_date": b.expiry_date,
        "owner_id": b.owner_id, "owner_name": b.owner.name if b.owner else None, "quantity": b.quantity,
        "expired": b.expiry_date is not None and b.expiry_date < today,
        "allocatable": b.stock_status == AVAILABLE and b.owner_id is None
        and not (b.expiry_date is not None and b.expiry_date < today) and location_service.is_allocatable(b.location),
    } for b in rows]


def stock_card(db: Session, user: User, *, product_id: int, warehouse_id: int | None = None,
               location_id: int | None = None, lot_number: str | None = None, stock_status: str | None = None,
               date_from: date | None = None, date_to: date | None = None, include_internal: bool = False) -> dict:
    """کاردکس: ردیف به ازای هر سند در محدوده، با مانده اول دوره و مانده پس از هر سند."""
    warehouse_id = location_service.scope_warehouse(user, warehouse_id)
    product = db.get(Product, product_id)
    if product is None:
        raise NotFoundError("کالا یافت نشد.")
    location = None
    if location_id is not None:
        location = db.get(Location, location_id)
        if location is None or (warehouse_id is not None and location.warehouse_id != warehouse_id):
            raise NotFoundError("محل یافت نشد.")
        warehouse_id = location.warehouse_id

    query = db.query(StockMovementLine, StockMovement).join(StockMovement, StockMovementLine.movement_id == StockMovement.id) \
        .filter(StockMovementLine.product_id == product_id)
    for column, value in ((StockMovementLine.warehouse_id, warehouse_id), (StockMovementLine.location_id, location_id),
                          (StockMovementLine.lot_number, lot_number), (StockMovementLine.stock_status, stock_status)):
        if value is not None:
            query = query.filter(column == value)

    opening = 0
    start = _local_start(date_from) if date_from else None
    end = _local_start(date_to) if date_to else None
    if start is not None:
        opening = sum(line.quantity_change for line, m in query.filter(StockMovement.created_at < start).all())
        query = query.filter(StockMovement.created_at >= start)
    if end is not None:
        query = query.filter(StockMovement.created_at < end)
    pairs = query.order_by(StockMovement.created_at, StockMovement.id, StockMovementLine.id).all()

    grouped: dict[int, dict] = {}
    order: list[int] = []
    for line, movement in pairs:
        group = grouped.get(movement.document_id)
        if group is None:
            group = grouped[movement.document_id] = {"net": 0, "in": 0, "out": 0, "first": movement, "types": [],
                                                     "locations": set(), "lots": set(), "location_ids": set()}
            order.append(movement.document_id)
        group["net"] += line.quantity_change
        group["in" if line.quantity_change > 0 else "out"] += abs(line.quantity_change)
        if movement.movement_type not in group["types"]:
            group["types"].append(movement.movement_type)
        if line.location_id:
            group["location_ids"].add(line.location_id)
        if line.lot_number:
            group["lots"].add(line.lot_number)

    documents = {d.id: d for d in db.query(StockDocument).options(
        joinedload(StockDocument.partner), joinedload(StockDocument.created_by)).filter(
        StockDocument.id.in_(order or [-1])).all()}
    codes = {loc.id: loc.code for loc in db.query(Location).filter(
        Location.id.in_({i for g in grouped.values() for i in g["location_ids"]} or {-1})).all()}

    rows, running, total_in, total_out = [], opening, 0, 0
    for doc_id in order:
        group = grouped[doc_id]
        if group["net"] == 0 and not include_internal:
            continue
        doc, movement = documents.get(doc_id), group["first"]
        quantity_in = group["in"] if include_internal else max(group["net"], 0)
        quantity_out = group["out"] if include_internal else max(-group["net"], 0)
        running += group["net"]
        total_in += quantity_in
        total_out += quantity_out
        rows.append({
            "date": movement.created_at, "document_id": doc_id, "document_code": doc.code if doc else None,
            "doc_type": doc.doc_type if doc else None,
            "doc_type_label": DOCUMENT_TYPES[doc.doc_type].label if doc and doc.doc_type in DOCUMENT_TYPES else None,
            "document_status": doc.status if doc else None, "partner_name": doc.partner.name if doc and doc.partner else None,
            "description": (doc.note if doc and doc.note else movement.reason) or "",
            "movement_types": group["types"], "locations": sorted(codes.get(i, str(i)) for i in group["location_ids"]),
            "lots": sorted(group["lots"]), "quantity_in": quantity_in, "quantity_out": quantity_out, "balance": running,
            "created_by_name": (doc.created_by.full_name or doc.created_by.username) if doc and doc.created_by else None,
        })
    truncated = len(rows) > KARDEX_LIMIT
    warehouse = db.get(Warehouse, warehouse_id) if warehouse_id else None
    return {
        "product_id": product.id, "product_name": product.name, "product_sku": product.sku, "unit": product.unit or "عدد",
        "warehouse_id": warehouse_id, "warehouse_name": warehouse.name if warehouse else None,
        "location_id": location_id, "location_code": location.code if location else None, "lot_number": lot_number,
        "stock_status": stock_status, "date_from": date_from, "date_to": date_to,
        "opening_balance": opening, "total_in": total_in, "total_out": total_out, "closing_balance": running,
        "rows": rows[-KARDEX_LIMIT:] if truncated else rows, "truncated": truncated,
    }
