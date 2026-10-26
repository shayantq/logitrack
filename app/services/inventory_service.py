"""
لایه سرویس انبار (Inventory Service)
منطق تجاری کالاها و موجودی: محدوده‌ی دید و اختیار مدیر انبار (فقط انبار خودش)، داده پایه کالا،
و عملیات انبار. هر عملیاتی که موجودی را عوض کند یک سند انبار قطعی می‌سازد (app/services/stock_ledger.py):

  رسید (receipt) · ضایعات (write_off) · اصلاحیه (adjustment) · انتقال (transfer) · تغییر وضعیت کیفی (status_change)

درخواست‌های ثبت سند کلید یکتایی (Idempotency-Key) می‌پذیرند تا تکرار درخواست سند دوم نسازد.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.wms import AVAILABLE, STOCK_STATUS_LABELS
from app.models import (
    ACTIVE_ORDER_STATUSES, Inventory, Order, OrderItem, Partner, Product, StockDocument, StockMovement, StockReservation,
    User, Warehouse,
)
from app.schemas.product import (
    LocationMoveCreate, ProductCreate, StatusChangeCreate, StockMovementCreate, StockTransferCreate, StockUpdate,
)
from app.services import (
    allocation_service, audit_service, catalog_service, location_service, permission_service, quality_service, receiving_service,
    stock_document_service, stock_ledger, warehouse_service,
)
from app.services.stock_ledger import StockKey
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError


def _role(user: User) -> str:
    return getattr(user.role, "value", user.role)


def list_products(db: Session, user: User) -> list[dict]:
    products = db.query(Product).options(selectinload(Product.stock_rows)).order_by(Product.id).all()
    is_manager = _role(user) == 'warehouse_manager'
    if is_manager and not user.warehouse_id:
        return []

    warehouses = {w.id: w for w in db.query(Warehouse).all()}
    current = catalog_service.prices_at(db, [p.id for p in products], catalog_service.today_local())
    # موجودی تأییدشده‌ای که قابل تخصیص نیست (محل تخلیه/قرنطینه، منقضی، امانی) از «آزاد» کم می‌شود
    unallocatable = allocation_service.unallocatable_map(db)

    def free(inv: Inventory) -> int:
        return max((inv.quantity or 0) - unallocatable.get(inv.id, 0) - (inv.reserved_quantity or 0), 0)
    result = []
    for p in products:
        rows = [inv for inv in p.stock_rows if not is_manager or inv.warehouse_id == user.warehouse_id]
        if is_manager and not rows:
            # مدیر انبار فقط کالاها و موجودی انبار اختصاصی خودش را می‌بیند
            continue
        available = [inv for inv in rows if inv.stock_status == AVAILABLE]
        held: dict[str, int] = defaultdict(int)
        for inv in rows:
            if inv.stock_status != AVAILABLE and inv.quantity:
                held[inv.stock_status] += inv.quantity
        stock = sum(inv.quantity or 0 for inv in available)
        reserved = sum(inv.reserved_quantity or 0 for inv in available)
        free_total = sum(free(inv) for inv in available)
        result.append({
            "id": p.id, "name": p.name, "sku": p.sku,
            "weight_kg": p.weight_kg, "price": current[p.id].final_price if p.id in current else p.price, "stock": stock,
            "reserved": reserved, "free_stock": free_total, "held_stock": dict(held),
            "ever_high_stock": any(inv.ever_exceeded_reorder for inv in available),
            "category": p.category, "unit": p.unit or "عدد", "origin": p.origin or "domestic", "origin_country": p.origin_country,
            "parent_id": p.parent_id, "variant_label": p.variant_label, "is_active": p.is_active is not False,
            "barcode": p.barcode,
            "subsidy_percent": current[p.id].subsidy_percent if p.id in current else 0,
            "stock_by_warehouse": [
                {"warehouse_id": inv.warehouse_id,
                 "warehouse_name": warehouses[inv.warehouse_id].name if inv.warehouse_id in warehouses else "بدون انبار",
                 "city": warehouses[inv.warehouse_id].city if inv.warehouse_id in warehouses else None,
                 "quantity": inv.quantity or 0, "reserved": inv.reserved_quantity or 0, "free": free(inv),
                 "ships_orders": inv.warehouse_id in warehouses and warehouse_service.type_of(warehouses[inv.warehouse_id]).ships_orders
                 and warehouses[inv.warehouse_id].is_active is not False}
                for inv in sorted(available, key=lambda i: i.warehouse_id)
            ],
        })
    return result


def _require_stock_role(user: User) -> None:
    if _role(user) not in ['org_admin', 'warehouse_manager']:
        raise ForbiddenError("⚠️ خطا: شما اجازه تغییر در موجودی انبار را ندارید.")


def _manager_warehouse(user: User) -> int:
    if not user.warehouse_id:
        raise ConflictError("حساب کاربری شما به هیچ انباری متصل نشده است.")
    return user.warehouse_id


def _get_product(db: Session, product_id: int) -> Product:
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise NotFoundError("محصول یافت نشد")
    return product


# ---------------------------------------------------------------------------
# کالا
# ---------------------------------------------------------------------------
def create_product(db: Session, user: User, product_data: ProductCreate) -> Product:
    if _role(user) not in ['org_admin', 'warehouse_manager']:
        raise ForbiddenError("⚠️ خطا: حساب کاربری شما سطح دسترسی لازم (ادمین/مدیر انبار) برای ثبت کالا را ندارد.")
    permission_service.ensure(db, user, "masterdata.products")

    target_warehouse_id = product_data.warehouse_id
    if _role(user) == 'warehouse_manager':
        target_warehouse_id = _manager_warehouse(user)
    if target_warehouse_id is None:
        default = warehouse_service.default_stock_warehouse(db)
        target_warehouse_id = default.id if default else None
    if target_warehouse_id is not None:
        warehouse_service.for_stock_in(db, target_warehouse_id)
    elif product_data.initial_quantity > 0:
        raise ConflictError("برای ثبت موجودی اولیه، انبار را انتخاب کنید.")

    catalog_service.ensure_unique_sku(db, product_data.sku)
    catalog_service.ensure_unique_barcode(db, product_data.barcode)

    try:
        master = product_data.model_dump(include=set(catalog_service.MASTER_FIELDS))
        new_product = Product(sku=product_data.sku, price=product_data.price)
        catalog_service.apply_fields(new_product, {
            **master, "origin_country": product_data.origin_country if product_data.origin == "imported" else None,
        })
        catalog_service.validate_master(new_product)
        db.add(new_product)
        db.flush()  # گرفتن id بدون commit — کالا و موجودی‌اش در یک تراکنش ثبت می‌شوند
        catalog_service.set_price(db, user, new_product, effective_from=catalog_service.today_local(),
                                  base_price=product_data.price, subsidy_percent=product_data.subsidy_percent)

        if target_warehouse_id is not None:
            inventory = stock_ledger.lock_bucket(
                db, new_product.id, target_warehouse_id,
                reorder_point=new_product.reorder_point if new_product.reorder_point is not None else 10)
            if product_data.initial_quantity > 0:
                stock_ledger.record(db, inventory, product_data.initial_quantity, "initial", user=user,
                                    reason="موجودی اولیه هنگام تعریف کالا")
        db.commit()
        db.refresh(new_product)
        return new_product
    except Exception:
        db.rollback()
        raise


def _has_history(db: Session, product_id: int) -> bool:
    return any(q.first() is not None for q in (
        db.query(StockMovement.id).filter(StockMovement.product_id == product_id),
        db.query(OrderItem.id).filter(OrderItem.product_id == product_id),
        db.query(StockReservation.id).filter(StockReservation.product_id == product_id),
    ))


def delete_product(db: Session, user: User, product_id: int) -> None:
    """
    حذف فقط برای کالای بی‌سابقه (مثلاً اشتباه ثبت‌شده). کالایی که گردش انبار یا سفارش دارد حذف نمی‌شود
    تا سوابق دست نخورند؛ به‌جای آن غیرفعال (بایگانی) می‌شود.
    """
    if _role(user) not in ['org_admin', 'warehouse_manager']:
        raise ForbiddenError("⚠️ خطا: شما اجازه حذف کالا را ندارید.")
    permission_service.ensure(db, user, "masterdata.products")

    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise NotFoundError("محصول یافت نشد")

    if _role(user) == 'warehouse_manager':
        warehouse_ids = {inv.warehouse_id for inv in product.stock_rows}
        if not user.warehouse_id or warehouse_ids - {user.warehouse_id}:
            raise ForbiddenError("این کالا در انبارهای دیگر هم موجودی دارد یا متعلق به انبار شما نیست؛ حذف آن فقط توسط ادمین ممکن است.")

    has_active_orders = db.query(OrderItem).join(Order, OrderItem.order_id == Order.id).filter(
        OrderItem.product_id == product_id,
        Order.status.in_(ACTIVE_ORDER_STATUSES),
    ).first()
    if has_active_orders:
        raise ConflictError("این کالا سفارش فعال (در انتظار/در حال حمل) دارد و فعلاً قابل حذف نیست.")
    if db.query(Product.id).filter(Product.parent_id == product.id).first():
        raise ConflictError("این کالا تنوع دارد؛ ابتدا تنوع‌ها را حذف یا بایگانی کنید.")
    if _has_history(db, product_id):
        raise ConflictError("این کالا سابقه گردش انبار یا سفارش دارد و برای حفظ سوابق حذف نمی‌شود؛ "
                            "به‌جای حذف، آن را در مشخصات کالا غیرفعال (بایگانی) کنید.")

    for inv in list(product.stock_rows):
        for balance in list(inv.balances):
            db.delete(balance)
        db.delete(inv)
    audit_service.log(db, user, "catalog.delete", f"کالای «{product.name}» حذف شد", target_type="product",
                      target_id=product.id, target_label=product.sku)
    db.delete(product)
    db.commit()


# ---------------------------------------------------------------------------
# ردیف هدف عملیات
# ---------------------------------------------------------------------------
def _resolve_warehouse(db: Session, user: User, product_id: int, warehouse_id: int | None, stock_status: str) -> int:
    """مدیر انبار همیشه انبار خودش؛ ادمین اگر انبار نداده و کالا فقط در یک انبار است، همان انبار."""
    if _role(user) == 'warehouse_manager':
        return _manager_warehouse(user)
    if warehouse_id is not None:
        return warehouse_id
    candidates = {wid for (wid,) in db.query(Inventory.warehouse_id).filter(
        Inventory.product_id == product_id, Inventory.stock_status == stock_status).all()}
    if len(candidates) == 1:
        return candidates.pop()
    default = warehouse_service.default_stock_warehouse(db)
    if not candidates and default is not None:
        return default.id
    raise ConflictError("این کالا در چند انبار موجودی دارد (یا هنوز در هیچ انباری نیست)؛ لطفاً انبار (warehouse_id) را مشخص کنید.")


def _stock_status(inventory: Inventory) -> dict:
    status_msg = "🟢 وضعیت موجودی نرمال است"
    if inventory.quantity <= inventory.reorder_point:
        status_msg = "🚨 هشدار: موجودی انبار به حد بحرانی رسیده! نیاز به شارژ مجدد فوری."
    return {"message": "✅ موجودی انبار بروزرسانی شد", "status": status_msg, "current_stock": inventory.quantity}


def update_stock(db: Session, user: User, product_id: int, stock_data: StockUpdate) -> dict:
    """موجودی سالم را به یک عدد شمارش‌شده می‌رساند؛ اختلاف به‌عنوان سند «اصلاحیه موجودی» ثبت می‌شود."""
    _require_stock_role(user)
    _get_product(db, product_id)
    try:
        warehouse_id = _resolve_warehouse(db, user, product_id, stock_data.warehouse_id, AVAILABLE)
        warehouse_service.get(db, warehouse_id)
        inventory = stock_ledger.lock_bucket(db, product_id, warehouse_id, reorder_point=stock_data.reorder_point)
        inventory.reorder_point = stock_data.reorder_point
        if stock_data.quantity < (inventory.reserved_quantity or 0):
            raise ConflictError(f"{inventory.reserved_quantity} عدد از این کالا برای سفارش‌های باز رزرو است؛ "
                                "موجودی نمی‌تواند کمتر از رزرو شود.")
        stock_ledger.set_balance(db, inventory, stock_data.quantity, "adjustment", user=user,
                                 reason=stock_data.reason or "اصلاح موجودی به عدد شمارش‌شده")
        if inventory.quantity > inventory.reorder_point:
            inventory.ever_exceeded_reorder = True
            inventory.low_alerted = False
        db.commit()
        db.refresh(inventory)
        return _stock_status(inventory)
    except Exception:
        db.rollback()
        raise


# ---------------------------------------------------------------------------
# اسناد: رسید، ضایعات، اصلاحیه، انتقال، تغییر وضعیت کیفی
# ---------------------------------------------------------------------------
MOVEMENT_SIGN = {"receipt": 1, "damage": -1}
DEFAULT_REASONS = {"receipt": "ورود کالا به انبار", "damage": "ضایعات / کسری"}


def _supplier(db: Session, partner_id: int | None) -> Partner | None:
    if partner_id is None:
        return None
    partner = db.get(Partner, partner_id)
    if partner is None:
        raise NotFoundError("تأمین‌کننده یافت نشد.")
    if not partner.is_supplier or partner.is_active is False:
        raise ConflictError(f"«{partner.name}» تأمین‌کننده فعال نیست.")
    return partner


def record_movement(db: Session, user: User, data: StockMovementCreate, idempotency_key: str | None = None) -> StockMovement:
    _require_stock_role(user)
    if data.movement_type != "receipt":
        permission_service.ensure(db, user, "stock.adjust")
    product = _get_product(db, data.product_id)

    def create(key, digest):
        try:
            if data.movement_type != "receipt" and data.partner_id is not None:
                raise ConflictError("تأمین‌کننده فقط برای رسید ورود کالا ثبت می‌شود.")
            partner = _supplier(db, data.partner_id)
            status = data.stock_status
            if data.movement_type == "receipt":
                warehouse_id = _resolve_warehouse(db, user, product.id, data.warehouse_id, status or AVAILABLE)
                warehouse = warehouse_service.for_stock_in(db, warehouse_id, direct_receipt=True)
                status = status or warehouse_service.type_of(warehouse).receipt_status
            else:
                status = status or AVAILABLE
                warehouse_id = _resolve_warehouse(db, user, product.id, data.warehouse_id, status)
                warehouse_service.get(db, warehouse_id)
            quantity = catalog_service.to_base(product, abs(data.quantity), data.uom)
            change = quantity * MOVEMENT_SIGN.get(data.movement_type, 1) * (1 if data.quantity > 0 else -1)
            location_service.resolve(db, warehouse_id, data.location_id)
            inventory = stock_ledger.lock_bucket(db, product.id, warehouse_id, status, create=change > 0,
                                                 reorder_point=product.reorder_point)
            if inventory is None:
                raise ConflictError(f"این کالا در این انبار موجودی «{STOCK_STATUS_LABELS[status]}» ندارد.")
            lines, match = None, {k: v for k, v in (("location_id", data.location_id), ("lot_number", data.lot_number)) if v}
            if change > 0:
                if data.movement_type == "receipt":
                    receiving_service.check_tracking(product, quantity, data.lot_number, data.expiry_date,
                                                     data.serial_numbers, damaged=status != AVAILABLE)
                base = StockKey(location_id=data.location_id, lot_number=data.lot_number, expiry_date=data.expiry_date)
                lines = [(base.with_(serial_number=s), 1) for s in data.serial_numbers] or [(base, quantity)]
            reason = data.reason or DEFAULT_REASONS.get(data.movement_type)
            document = stock_ledger.new_document(
                db, {"receipt": "receipt", "damage": "write_off", "adjustment": "adjustment"}[data.movement_type],
                organization_id=product.organization_id, user=user, warehouse_id=warehouse_id,
                partner_id=partner.id if partner else None, external_ref=data.external_ref, note=reason,
                idempotency_key=key, request_hash=digest,
            )
            movement = stock_ledger.record(db, inventory, change, data.movement_type, document=document, user=user,
                                           reason=reason, lines=lines, match=match or None)
            db.commit()
            db.refresh(movement)
            return movement
        except Exception:
            db.rollback()
            raise

    result, replayed = stock_document_service.idempotent(
        db, StockDocument, idempotency_key, "movement", data.model_dump(), create)
    return result.movements[0] if replayed else result


def transfer_stock(db: Session, user: User, data: StockTransferCreate, idempotency_key: str | None = None) -> list[StockMovement]:
    """انتقال بین دو انبار همان سازمان: یک سند با یک گردش خروج و یک گردش ورود (همان وضعیت کیفی)."""
    _require_stock_role(user)
    if _role(user) == 'warehouse_manager' and data.from_warehouse_id != _manager_warehouse(user):
        raise ForbiddenError("مدیر انبار فقط از انبار خودش می‌تواند کالا منتقل کند.")
    product = _get_product(db, data.product_id)
    warehouse_service.get(db, data.from_warehouse_id)
    warehouse_service.for_stock_in(db, data.to_warehouse_id)
    location_service.resolve(db, data.from_warehouse_id, data.from_location_id)
    location_service.resolve(db, data.to_warehouse_id, data.to_location_id)
    quantity = catalog_service.to_base(product, data.quantity, data.uom)
    match = {k: v for k, v in (("location_id", data.from_location_id), ("lot_number", data.lot_number)) if v}

    def create(key, digest):
        try:
            # هر دو ردیف به ترتیب id قفل می‌شوند تا دو انتقال هم‌زمانِ معکوس به deadlock نخورند
            rows = db.query(Inventory).filter(
                Inventory.product_id == product.id, Inventory.stock_status == data.stock_status,
                Inventory.warehouse_id.in_([data.from_warehouse_id, data.to_warehouse_id]),
            ).order_by(Inventory.id).with_for_update().all()
            by_warehouse = {inv.warehouse_id: inv for inv in rows}

            source = by_warehouse.get(data.from_warehouse_id)
            if source is None or source.free_quantity < quantity:
                available = source.free_quantity if source else 0
                raise ConflictError(
                    f"موجودی آزاد انبار مبدأ کافی نیست. موجودی آزاد: {available} عدد — مقدار انتقال: {quantity} عدد."
                )
            target = by_warehouse.get(data.to_warehouse_id) or stock_ledger.lock_bucket(
                db, product.id, data.to_warehouse_id, data.stock_status, reorder_point=product.reorder_point)

            reason = data.reason or "انتقال بین انبارها"
            document = stock_ledger.new_document(
                db, "transfer", organization_id=product.organization_id, user=user, warehouse_id=data.from_warehouse_id,
                note=reason, idempotency_key=key, request_hash=digest,
            )
            db.flush()
            # همان بچ/سریال/انقضا/مالک به انبار مقصد می‌رود (محل مقصد انتخاب‌شده یا بدون محل)
            moves = stock_ledger.move(db, source, quantity, document=document, target=target, out_type="transfer_out",
                                      in_type="transfer_in", match=match or None,
                                      overrides={"location_id": data.to_location_id}, user=user, reason=reason,
                                      reference_type="transfer", reference_id=document.id)
            db.commit()
            for m in moves:
                db.refresh(m)
            return document
        except Exception:
            db.rollback()
            raise

    document, _ = stock_document_service.idempotent(db, StockDocument, idempotency_key, "transfer", data.model_dump(), create)
    return list(document.movements)


def change_status(db: Session, user: User, data: StatusChangeCreate, idempotency_key: str | None = None) -> dict:
    """تغییر وضعیت کیفی بخشی از موجودی (مثلاً آزادسازی از قرنطینه پس از بازرسی): یک سند با دو گردش."""
    _require_stock_role(user)
    permission_service.ensure(db, user, "stock.status_change")
    product = _get_product(db, data.product_id)
    quality_service.ensure_transition(user, data.from_status, data.to_status)

    def create(key, digest):
        try:
            warehouse_id = _resolve_warehouse(db, user, product.id, data.warehouse_id, data.from_status)
            warehouse_service.for_stock_in(db, warehouse_id)
            location_service.resolve(db, warehouse_id, data.location_id)
            match = {k: v for k, v in (("location_id", data.location_id), ("lot_number", data.lot_number)) if v}
            quantity = catalog_service.to_base(product, data.quantity, data.uom)
            source = stock_ledger.lock_bucket(db, product.id, warehouse_id, data.from_status, create=False)
            if source is None or source.free_quantity < quantity:
                available = source.free_quantity if source else 0
                raise ConflictError(f"موجودی «{STOCK_STATUS_LABELS[data.from_status]}» کافی نیست. "
                                    f"موجودی قابل تغییر: {available} عدد — درخواستی: {quantity} عدد.")
            target = stock_ledger.lock_bucket(db, product.id, warehouse_id, data.to_status, reorder_point=product.reorder_point)
            document = stock_ledger.new_document(
                db, "status_change", organization_id=product.organization_id, user=user, warehouse_id=warehouse_id,
                note=data.reason, idempotency_key=key, request_hash=digest,
            )
            label = f"{STOCK_STATUS_LABELS[data.from_status]} ← {STOCK_STATUS_LABELS[data.to_status]}: {data.reason}"
            # وضعیت کیفی مستقل از محل است: همان محل/بچ/سریال، فقط ردیف وضعیت عوض می‌شود
            stock_ledger.move(db, source, quantity, document=document, target=target, out_type="status_out",
                              in_type="status_in", match=match or None, user=user, reason=label)
            db.commit()
            return document
        except Exception:
            db.rollback()
            raise

    document, _ = stock_document_service.idempotent(db, StockDocument, idempotency_key, "status", data.model_dump(), create)
    return stock_document_service.get_document(db, user, document.id)


def move_between_locations(db: Session, user: User, data: LocationMoveCreate, idempotency_key: str | None = None) -> dict:
    """جابه‌جایی دستی داخل یک انبار (محل به محل، یا از «بدون محل» به یک محل) — سند MV با ظرفیت و قاعده اختلاط مقصد."""
    _require_stock_role(user)
    product = _get_product(db, data.product_id)
    warehouse_id = location_service.scope_warehouse(user, data.warehouse_id)
    if warehouse_id is None:
        raise ConflictError("انبار را انتخاب کنید.")

    def create(key, digest):
        try:
            location_service.resolve(db, warehouse_id, data.from_location_id)
            destination = location_service.resolve(db, warehouse_id, data.to_location_id)
            if data.from_location_id == data.to_location_id:
                raise ConflictError("محل مبدأ و مقصد یکی است.")
            quantity = catalog_service.to_base(product, data.quantity, data.uom)
            inventory = stock_ledger.lock_bucket(db, product.id, warehouse_id, data.stock_status, create=False)
            if inventory is None:
                raise ConflictError(f"این کالا در این انبار موجودی «{STOCK_STATUS_LABELS[data.stock_status]}» ندارد.")
            reason = data.reason or f"جابه‌جایی به محل {destination.code}"
            document = stock_ledger.new_document(
                db, "location_move", organization_id=product.organization_id, user=user, warehouse_id=warehouse_id,
                note=reason, idempotency_key=key, request_hash=digest,
            )
            match = {"location_id": data.from_location_id}
            if data.lot_number:
                match["lot_number"] = data.lot_number
            stock_ledger.move(db, inventory, quantity, document=document, match=match,
                              overrides={"location_id": destination.id}, user=user, reason=reason)
            db.commit()
            return document
        except Exception:
            db.rollback()
            raise

    document, _ = stock_document_service.idempotent(db, StockDocument, idempotency_key, "location_move",
                                                    data.model_dump(mode="json"), create)
    return stock_document_service.get_document(db, user, document.id)


# ---------------------------------------------------------------------------
# خواندن: گردش‌ها، ردیف‌های موجودی، رزروها
# ---------------------------------------------------------------------------
def list_movements(db: Session, user: User, product_id: int | None = None, warehouse_id: int | None = None,
                   movement_type: str | None = None, date_from: datetime | None = None,
                   date_to: datetime | None = None, skip: int = 0, limit: int = 100, *,
                   document_id: int | None = None, stock_status: str | None = None) -> list[StockMovement]:
    if _role(user) not in ['org_admin', 'warehouse_manager']:
        raise ForbiddenError("شما مجوز مشاهده گردش کالا را ندارید.")
    if _role(user) == 'warehouse_manager':
        warehouse_id = _manager_warehouse(user)

    query = db.query(StockMovement).options(
        joinedload(StockMovement.product), joinedload(StockMovement.warehouse), joinedload(StockMovement.created_by),
        joinedload(StockMovement.document),
    )
    if product_id is not None:
        query = query.filter(StockMovement.product_id == product_id)
    if warehouse_id is not None:
        query = query.filter(StockMovement.warehouse_id == warehouse_id)
    if movement_type is not None:
        query = query.filter(StockMovement.movement_type == movement_type)
    if document_id is not None:
        query = query.filter(StockMovement.document_id == document_id)
    if stock_status is not None:
        query = query.filter(StockMovement.stock_status == stock_status)
    if date_from is not None:
        query = query.filter(StockMovement.created_at >= date_from)
    if date_to is not None:
        query = query.filter(StockMovement.created_at < date_to)
    return query.order_by(StockMovement.id.desc()).offset(skip).limit(limit).all()


def stock_buckets(db: Session, user: User, product_id: int | None = None, warehouse_id: int | None = None,
                  stock_status: str | None = None, include_empty: bool = False) -> list[dict]:
    """موجودی به تفکیک کالا × انبار × وضعیت کیفی، با رزرو و موجودی آزاد."""
    _require_stock_role(user)
    if _role(user) == 'warehouse_manager':
        warehouse_id = _manager_warehouse(user)
    query = db.query(Inventory).options(joinedload(Inventory.product), joinedload(Inventory.warehouse))
    if product_id is not None:
        query = query.filter(Inventory.product_id == product_id)
    if warehouse_id is not None:
        query = query.filter(Inventory.warehouse_id == warehouse_id)
    if stock_status is not None:
        query = query.filter(Inventory.stock_status == stock_status)
    rows = []
    for inv in query.order_by(Inventory.product_id, Inventory.warehouse_id, Inventory.id).all():
        if inv.product is None or (not include_empty and not inv.quantity):
            continue
        rows.append({
            "inventory_id": inv.id, "product_id": inv.product_id, "product_name": inv.product.name,
            "product_sku": inv.product.sku, "unit": inv.product.unit or "عدد", "warehouse_id": inv.warehouse_id,
            "warehouse_name": inv.warehouse.name if inv.warehouse else "—", "stock_status": inv.stock_status,
            "stock_status_label": STOCK_STATUS_LABELS.get(inv.stock_status, inv.stock_status),
            "quantity": inv.quantity or 0, "reserved": inv.reserved_quantity or 0, "free": inv.free_quantity,
        })
    return rows


def list_reservations(db: Session, user: User, status: str | None = "active", product_id: int | None = None,
                      warehouse_id: int | None = None, limit: int = 200) -> list[dict]:
    _require_stock_role(user)
    if _role(user) == 'warehouse_manager':
        warehouse_id = _manager_warehouse(user)
    query = db.query(StockReservation).options(joinedload(StockReservation.product))
    if status:
        query = query.filter(StockReservation.status == status)
    if product_id is not None:
        query = query.filter(StockReservation.product_id == product_id)
    if warehouse_id is not None:
        query = query.filter(StockReservation.warehouse_id == warehouse_id)
    reservations = query.order_by(StockReservation.id.desc()).limit(limit).all()
    warehouses = {w.id: w.name for w in db.query(Warehouse).all()}
    order_ids = [r.reference_id for r in reservations if r.reference_type == "order"]
    codes = dict(db.query(Order.id, Order.tracking_code).filter(Order.id.in_(order_ids or [-1])).all())
    return [{
        "id": r.id, "product_id": r.product_id, "product_name": r.product.name if r.product else None,
        "product_sku": r.product.sku if r.product else None, "warehouse_id": r.warehouse_id,
        "warehouse_name": warehouses.get(r.warehouse_id), "quantity": r.quantity, "status": r.status,
        "reference_type": r.reference_type, "reference_id": r.reference_id,
        "reference_label": codes.get(r.reference_id) if r.reference_type == "order" else None,
        "created_at": r.created_at, "closed_at": r.closed_at, "close_reason": r.close_reason,
    } for r in reservations]


def ledger_check(db: Session, user: User) -> dict:
    if _role(user) != 'org_admin':
        raise ForbiddenError("فقط ادمین سازمان می‌تواند صحت دفتر گردش کالا را بررسی کند.")
    mismatches = stock_ledger.find_mismatches(db)
    return {"ok": not mismatches, "mismatches": mismatches}
