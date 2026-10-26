"""
شناسایی هر بارکد/QR اسکن‌شده (فصل ۲۷): کالا (بارکد یا کد کالا)، محل، بسته (LPN)، سفارش، فهرست برداشت، رسید،
سفارش انتقال، انبارگردانی، سند انبار و بچ — تا اسکنر موبایل یا دستی کاربر را مستقیم به همان مورد ببرد.
لینک رهگیری عمومی (…/track/LT-…) هم پذیرفته می‌شود. فقط داده‌های سازمان خود کاربر جست‌وجو می‌شود.
"""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    InboundReceipt, Location, Order, Package, PickList, Product, StockBalance, StockDocument, Stocktake, TransferOrder, User,
    Warehouse,
)
from app.services import location_service
from app.services.exceptions import ConflictError, NotFoundError


def _clean(raw: str) -> str:
    value = (raw or "").strip()
    if "/track/" in value:
        value = value.rsplit("/track/", 1)[1].split("?")[0].strip("/")
    return value


def resolve(db: Session, user: User, raw: str) -> dict:
    location_service.ensure_staff(user)
    value = _clean(raw)
    if not value:
        raise ConflictError("کد اسکن‌شده خالی است.")
    upper = value.upper()
    manager_wh = user.warehouse_id if getattr(user.role, "value", user.role) == "warehouse_manager" else None

    product = db.query(Product).filter((func.upper(Product.barcode) == upper) | (func.upper(Product.sku) == upper)).first()
    if product is not None:
        return {"kind": "product", "id": product.id, "code": product.sku, "title": product.name,
                "subtitle": f"کد کالا {product.sku}" + (f" — بارکد {product.barcode}" if product.barcode else ""),
                "path": f"/app/stock-card?product={product.id}"}
    loc_query = db.query(Location).filter((func.upper(Location.barcode) == upper) | (func.upper(Location.code) == upper))
    if manager_wh:
        loc_query = loc_query.filter(Location.warehouse_id == manager_wh)
    location = loc_query.first()
    if location is not None:
        warehouse = db.get(Warehouse, location.warehouse_id)
        return {"kind": "location", "id": location.id, "code": location.code, "title": f"محل {location.code}",
                "subtitle": warehouse.name if warehouse else None,
                "path": f"/app/locations?warehouse={location.warehouse_id}&location={location.id}"}
    package = db.query(Package).filter(func.upper(Package.code) == upper).first()
    if package is not None:
        order = db.get(Order, package.order_id)
        return {"kind": "package", "id": package.id, "code": package.code, "title": f"بسته {package.code}",
                "subtitle": f"سفارش {order.tracking_code}" if order else None, "path": "/app/shipping"}
    order = db.query(Order).filter(func.upper(Order.tracking_code) == upper).first()
    if order is not None:
        return {"kind": "order", "id": order.id, "code": order.tracking_code, "title": f"سفارش {order.tracking_code}",
                "subtitle": order.destination_city, "path": f"/app/orders?q={order.tracking_code}"}
    for model, kind, label, path in (
        (PickList, "pick_list", "فهرست برداشت", "/app/picking"),
        (InboundReceipt, "receipt", "رسید", "/app/receipts"),
        (TransferOrder, "transfer", "سفارش انتقال", "/app/transfers"),
        (StockDocument, "document", "سند انبار", "/app/documents"),
    ):
        row = db.query(model).filter(func.upper(model.code) == upper).first()
        if row is not None:
            return {"kind": kind, "id": row.id, "code": row.code, "title": f"{label} {row.code}", "subtitle": None,
                    "path": f"{path}?code={row.code}"}
    stocktake = db.query(Stocktake).filter(func.upper(Stocktake.code) == upper).first()
    if stocktake is not None:
        return {"kind": "stocktake", "id": stocktake.id, "code": stocktake.code, "title": stocktake.title or stocktake.code,
                "subtitle": None, "path": f"/app/stocktakes/{stocktake.id}"}
    lot = db.query(StockBalance).filter(func.upper(StockBalance.lot_number) == upper, StockBalance.quantity > 0).first()
    if lot is not None:
        product = db.get(Product, lot.product_id)
        return {"kind": "lot", "id": lot.product_id, "code": lot.lot_number, "title": f"بچ {lot.lot_number}",
                "subtitle": product.name if product else None, "path": f"/app/stock-card?product={lot.product_id}"}
    raise NotFoundError(f"کد «{value}» در کالاها، محل‌ها، بسته‌ها، سفارش‌ها و اسناد سازمان پیدا نشد.")
