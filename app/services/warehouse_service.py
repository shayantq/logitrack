"""
انبارها: نوع، کد، سلسله‌مراتب و قواعد استفاده (app/core/wms.WAREHOUSE_TYPES).

- «سایت» فقط گروه‌بندی است (مثلاً «مجتمع انبار شمال» با چند انبار زیرمجموعه) و کالا نگه نمی‌دارد.
- سفارش مشتری فقط از انبارهای عمومی/محصول نهایی/مرکز توزیع ارسال می‌شود.
- انبار «در راه» رسید مستقیم ندارد و فقط با سند انتقال پر و خالی می‌شود.
- رسید در انبار قرنطینه یا مرجوعی به‌طور پیش‌فرض با وضعیت «قرنطینه» ثبت می‌شود.
- انبار غیرفعال رسید، انتقال ورودی و سفارش جدید نمی‌گیرد (برداشت باقی‌مانده با انتقال خروجی ممکن است).
"""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.wms import MAX_WAREHOUSE_DEPTH, WAREHOUSE_TYPES, WarehouseType
from app.models import Inventory, StockReservation, User, Warehouse
from app.services.exceptions import ConflictError, NotFoundError


def type_of(warehouse: Warehouse) -> WarehouseType:
    return WAREHOUSE_TYPES.get(warehouse.type or "general", WAREHOUSE_TYPES["general"])


def get(db: Session, warehouse_id: int) -> Warehouse:
    warehouse = db.get(Warehouse, warehouse_id)
    if warehouse is None:
        raise NotFoundError("انبار انتخاب‌شده یافت نشد.")
    return warehouse


def for_stock_in(db: Session, warehouse_id: int, *, direct_receipt: bool = False) -> Warehouse:
    """انبار مقصد ورود کالا (رسید، انتقال ورودی، تغییر وضعیت)."""
    warehouse = get(db, warehouse_id)
    kind = type_of(warehouse)
    if not kind.holds_stock:
        raise ConflictError(f"«{warehouse.name}» یک {kind.label} است و کالا نگه نمی‌دارد؛ یکی از انبارهای زیرمجموعه را انتخاب کنید.")
    if warehouse.is_active is False:
        raise ConflictError(f"انبار «{warehouse.name}» غیرفعال است و کالای جدید نمی‌پذیرد.")
    if direct_receipt and not kind.direct_receipt:
        raise ConflictError(f"«{warehouse.name}» {kind.label} است؛ کالا فقط با سند انتقال وارد آن می‌شود.")
    return warehouse


def shipping_ids(db: Session) -> set[int]:
    """انبارهای فعالی که سفارش مشتری از آن‌ها ارسال می‌شود."""
    return {w.id for w in db.query(Warehouse).all() if type_of(w).ships_orders and w.is_active is not False}


def default_stock_warehouse(db: Session) -> Warehouse | None:
    """اگر سازمان فقط یک انبار کالادار و فعال دارد، همان (برای فرم‌هایی که انبار را نمی‌پرسند)."""
    candidates = [w for w in db.query(Warehouse).order_by(Warehouse.id).all()
                  if type_of(w).holds_stock and w.is_active is not False]
    return candidates[0] if len(candidates) == 1 else None


def depth_map(warehouses: list[Warehouse]) -> dict[int, int]:
    by_id = {w.id: w for w in warehouses}
    depths: dict[int, int] = {}
    for w in warehouses:
        depth, node, seen = 0, w, set()
        while node.parent_id and node.parent_id in by_id and node.id not in seen:
            seen.add(node.id)
            node = by_id[node.parent_id]
            depth += 1
        depths[w.id] = depth
    return depths


def ordered_tree(warehouses: list[Warehouse]) -> list[Warehouse]:
    """ترتیب درختی: هر انبار مادر، بعدش زیرمجموعه‌هایش."""
    children: dict[int | None, list[Warehouse]] = {}
    ids = {w.id for w in warehouses}
    for w in sorted(warehouses, key=lambda w: w.id):
        children.setdefault(w.parent_id if w.parent_id in ids else None, []).append(w)
    result: list[Warehouse] = []

    def walk(parent_id):
        for w in children.get(parent_id, []):
            result.append(w)
            walk(w.id)
    walk(None)
    return result


def next_code(db: Session) -> str:
    codes = {c for (c,) in db.query(Warehouse.code).all()}
    n = len(codes) + 1
    while f"WH-{n:02d}" in codes:
        n += 1
    return f"WH-{n:02d}"


def on_hand(db: Session, warehouse_id: int) -> int:
    return int(db.query(func.coalesce(func.sum(Inventory.quantity), 0)).filter(Inventory.warehouse_id == warehouse_id).scalar() or 0)


def validate(db: Session, data: dict, warehouse: Warehouse | None = None) -> dict:
    """قواعد ساخت/ویرایش؛ data را تکمیل‌شده برمی‌گرداند (کد خودکار)."""
    code = data.get("code") or (warehouse.code if warehouse else None) or next_code(db)
    duplicate = db.query(Warehouse.id).filter(func.upper(Warehouse.code) == code.upper())
    if warehouse is not None:
        duplicate = duplicate.filter(Warehouse.id != warehouse.id)
    if duplicate.first():
        raise ConflictError(f"کد انبار «{code}» تکراری است.")
    data["code"] = code

    kind = WAREHOUSE_TYPES[data.get("type") or "general"]
    parent_id = data.get("parent_id")
    if parent_id is not None:
        parent = db.get(Warehouse, parent_id)
        if parent is None:
            raise NotFoundError("انبار مادر یافت نشد.")
        if warehouse is not None:
            node, seen = parent, set()
            while node is not None and node.id not in seen:
                if node.id == warehouse.id:
                    raise ConflictError("انبار نمی‌تواند زیرمجموعه خودش یا زیرمجموعه‌هایش باشد.")
                seen.add(node.id)
                node = db.get(Warehouse, node.parent_id) if node.parent_id else None
        depth = depth_map(db.query(Warehouse).all()).get(parent.id, 0) + 1
        if depth >= MAX_WAREHOUSE_DEPTH:
            raise ConflictError(f"سلسله‌مراتب انبار حداکثر {MAX_WAREHOUSE_DEPTH} سطح است.")

    if warehouse is not None:
        stock = on_hand(db, warehouse.id)
        if not kind.holds_stock and stock:
            raise ConflictError("این انبار کالا دارد و نمی‌تواند «سایت» (بدون کالا) شود؛ ابتدا کالاها را منتقل کنید.")
        if data.get("is_active") is False and warehouse.is_active is not False:
            if stock:
                raise ConflictError("انبار دارای موجودی را نمی‌توان غیرفعال کرد؛ ابتدا کالاها را منتقل کنید.")
            if db.query(StockReservation.id).filter(StockReservation.warehouse_id == warehouse.id,
                                                    StockReservation.status == "active").first():
                raise ConflictError("این انبار رزرو سفارش باز دارد و فعلاً غیرفعال نمی‌شود.")
            if db.query(User.id).filter(User.warehouse_id == warehouse.id, User.is_active.is_not(False)).first():
                raise ConflictError("مدیر انباری به این انبار متصل است؛ ابتدا او را به انبار دیگری منتقل کنید.")
    return data
