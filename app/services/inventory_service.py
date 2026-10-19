"""
لایه سرویس انبار (Inventory Service)
منطق تجاری مربوط به کالاها و موجودی: محدوده‌ی دید و اختیار مدیر انبار (فقط
انبار خودش)، بررسی تکراری نبودن SKU، و پایش خودکار سطح بحرانی موجودی
(Reorder Point).
"""
from datetime import datetime

from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import User, Product, Inventory, Order, OrderItem, Warehouse, StockMovement, ACTIVE_ORDER_STATUSES
from app.schemas.product import ProductCreate, StockUpdate, StockMovementCreate, StockTransferCreate
from app.services import catalog_service, stock_ledger
from app.services.exceptions import NotFoundError, ForbiddenError, ConflictError


def list_products(db: Session, user: User) -> list[dict]:
    products = db.query(Product).options(selectinload(Product.inventories)).order_by(Product.id).all()
    is_manager = user.role == 'warehouse_manager'
    if is_manager and not user.warehouse_id:
        return []

    warehouses = {w.id: w for w in db.query(Warehouse).all()}
    current = catalog_service.prices_at(db, [p.id for p in products], catalog_service.today_local())
    result = []
    for p in products:
        if is_manager:
            # مدیر انبار فقط کالاها و موجودی انبار اختصاصی خودش را می‌بیند
            relevant_invs = [inv for inv in p.inventories if inv.warehouse_id == user.warehouse_id]
            if not relevant_invs:
                continue
        else:
            relevant_invs = p.inventories
        stock = sum(inv.quantity or 0 for inv in relevant_invs)
        ever_high_stock = any(inv.ever_exceeded_reorder for inv in relevant_invs)
        result.append({
            "id": p.id, "name": p.name, "sku": p.sku,
            "weight_kg": p.weight_kg, "price": current[p.id].final_price if p.id in current else p.price, "stock": stock,
            "ever_high_stock": ever_high_stock,
            "category": p.category, "unit": p.unit or "عدد", "origin": p.origin or "domestic", "origin_country": p.origin_country,
            "parent_id": p.parent_id, "variant_label": p.variant_label, "is_active": p.is_active is not False,
            "subsidy_percent": current[p.id].subsidy_percent if p.id in current else 0,
            "stock_by_warehouse": [
                {"warehouse_id": inv.warehouse_id,
                 "warehouse_name": warehouses[inv.warehouse_id].name if inv.warehouse_id in warehouses else "بدون انبار",
                 "city": warehouses[inv.warehouse_id].city if inv.warehouse_id in warehouses else None,
                 "quantity": inv.quantity or 0}
                for inv in sorted(relevant_invs, key=lambda i: (i.warehouse_id is None, i.warehouse_id or 0))
            ],
        })
    return result


def _ensure_warehouse_exists(db: Session, warehouse_id: int | None) -> None:
    if warehouse_id is not None and db.get(Warehouse, warehouse_id) is None:
        raise NotFoundError("انبار انتخاب‌شده یافت نشد.")


def create_product(db: Session, user: User, product_data: ProductCreate) -> Product:
    if user.role not in ['org_admin', 'warehouse_manager']:
        raise ForbiddenError("⚠️ خطا: حساب کاربری شما سطح دسترسی لازم (ادمین/مدیر انبار) برای ثبت کالا را ندارد.")

    target_warehouse_id = product_data.warehouse_id
    if user.role == 'warehouse_manager':
        if not user.warehouse_id:
            raise ConflictError("حساب کاربری شما به هیچ انباری متصل نشده است.")
        target_warehouse_id = user.warehouse_id
    _ensure_warehouse_exists(db, target_warehouse_id)

    existing = db.query(Product).filter(Product.sku == product_data.sku).first()
    if existing:
        raise ConflictError("کد کالا (SKU) تکراری است")

    try:
        new_product = Product(
            name=product_data.name,
            sku=product_data.sku,
            price=product_data.price,
            weight_kg=product_data.weight_kg,
            category=product_data.category, brand=product_data.brand, unit=product_data.unit,
            origin=product_data.origin, origin_country=product_data.origin_country if product_data.origin == "imported" else None,
        )
        db.add(new_product)
        db.flush()  # گرفتن id بدون commit — کالا و موجودی‌اش در یک تراکنش ثبت می‌شوند
        catalog_service.set_price(db, user, new_product, effective_from=catalog_service.today_local(),
                                  base_price=product_data.price, subsidy_percent=product_data.subsidy_percent)

        inventory = Inventory(product_id=new_product.id, quantity=0, reorder_point=10, warehouse_id=target_warehouse_id)
        db.add(inventory)
        if product_data.initial_quantity > 0:
            stock_ledger.record(db, inventory, product_data.initial_quantity, "initial", user=user,
                                reason="موجودی اولیه هنگام تعریف کالا")
        db.commit()
        db.refresh(new_product)
        return new_product
    except Exception:
        db.rollback()
        raise


def delete_product(db: Session, user: User, product_id: int) -> None:
    if user.role not in ['org_admin', 'warehouse_manager']:
        raise ForbiddenError("⚠️ خطا: شما اجازه حذف کالا را ندارید.")

    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise NotFoundError("محصول یافت نشد")

    if user.role == 'warehouse_manager':
        warehouse_ids = {inv.warehouse_id for inv in product.inventories}
        if not user.warehouse_id or warehouse_ids != {user.warehouse_id}:
            raise ForbiddenError("این کالا در انبارهای دیگر هم موجودی دارد یا متعلق به انبار شما نیست؛ حذف آن فقط توسط ادمین ممکن است.")

    has_active_orders = db.query(OrderItem).join(Order, OrderItem.order_id == Order.id).filter(
        OrderItem.product_id == product_id,
        Order.status.in_(ACTIVE_ORDER_STATUSES),
    ).first()
    if has_active_orders:
        raise ConflictError("این کالا سفارش فعال (در انتظار/در حال حمل) دارد و فعلاً قابل حذف نیست.")

    db.delete(product)
    db.commit()


def _require_stock_role(user: User) -> None:
    if user.role not in ['org_admin', 'warehouse_manager']:
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


def _lock_target_inventory(db: Session, user: User, product_id: int, warehouse_id: int | None, *,
                           reorder_point: int | None = None) -> Inventory:
    """
    ردیف موجودی هدف را (با قفل) پیدا می‌کند یا اگر کالا در آن انبار ردیفی ندارد، با موجودی صفر می‌سازد.
    مدیر انبار همیشه فقط انبار خودش؛ ادمین اگر کالا در چند انبار باشد باید انبار را مشخص کند.
    """
    if user.role == 'warehouse_manager':
        warehouse_id = _manager_warehouse(user)
    _ensure_warehouse_exists(db, warehouse_id)

    query = db.query(Inventory).filter(Inventory.product_id == product_id)
    if warehouse_id is not None:
        query = query.filter(Inventory.warehouse_id == warehouse_id)
    records = query.order_by(Inventory.id).with_for_update().all()

    if warehouse_id is None and len(records) > 1:
        raise ConflictError("این کالا در چند انبار موجودی دارد؛ لطفاً انبار (warehouse_id) را مشخص کنید.")
    if records:
        return records[0]

    inventory = Inventory(product_id=product_id, warehouse_id=warehouse_id, quantity=0,
                          reorder_point=10 if reorder_point is None else reorder_point)
    db.add(inventory)
    return inventory


def _stock_status(inventory: Inventory) -> dict:
    status_msg = "🟢 وضعیت موجودی نرمال است"
    if inventory.quantity <= inventory.reorder_point:
        status_msg = "🚨 هشدار: موجودی انبار به حد بحرانی رسیده! نیاز به شارژ مجدد فوری."
    return {"message": "✅ موجودی انبار بروزرسانی شد", "status": status_msg, "current_stock": inventory.quantity}


def update_stock(db: Session, user: User, product_id: int, stock_data: StockUpdate) -> dict:
    """موجودی را به یک عدد مشخص می‌رساند؛ اختلاف به‌عنوان گردش «اصلاح موجودی» ثبت می‌شود."""
    _require_stock_role(user)
    _get_product(db, product_id)
    try:
        inventory = _lock_target_inventory(db, user, product_id, stock_data.warehouse_id,
                                           reorder_point=stock_data.reorder_point)
        inventory.reorder_point = stock_data.reorder_point
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
# گردش کالا: ورود، اصلاح، ضایعات، انتقال، تاریخچه
# ---------------------------------------------------------------------------
MOVEMENT_SIGN = {"receipt": 1, "damage": -1}
DEFAULT_REASONS = {"receipt": "ورود کالا به انبار", "damage": "ضایعات / کسری"}


def record_movement(db: Session, user: User, data: StockMovementCreate) -> StockMovement:
    _require_stock_role(user)
    _get_product(db, data.product_id)
    try:
        inventory = _lock_target_inventory(db, user, data.product_id, data.warehouse_id)
        change = data.quantity * MOVEMENT_SIGN.get(data.movement_type, 1)
        movement = stock_ledger.record(
            db, inventory, change, data.movement_type, user=user,
            reason=data.reason or DEFAULT_REASONS.get(data.movement_type),
        )
        db.commit()
        db.refresh(movement)
        return movement
    except Exception:
        db.rollback()
        raise


def transfer_stock(db: Session, user: User, data: StockTransferCreate) -> list[StockMovement]:
    """انتقال بین دو انبار همان سازمان: یک گردش خروج و یک گردش ورود با مرجع مشترک."""
    _require_stock_role(user)
    if user.role == 'warehouse_manager' and data.from_warehouse_id != _manager_warehouse(user):
        raise ForbiddenError("مدیر انبار فقط از انبار خودش می‌تواند کالا منتقل کند.")
    _get_product(db, data.product_id)
    _ensure_warehouse_exists(db, data.from_warehouse_id)
    _ensure_warehouse_exists(db, data.to_warehouse_id)

    try:
        # هر دو ردیف به ترتیب id قفل می‌شوند تا دو انتقال هم‌زمانِ معکوس به deadlock نخورند
        rows = db.query(Inventory).filter(
            Inventory.product_id == data.product_id,
            Inventory.warehouse_id.in_([data.from_warehouse_id, data.to_warehouse_id]),
        ).order_by(Inventory.id).with_for_update().all()
        by_warehouse = {inv.warehouse_id: inv for inv in rows}

        source = by_warehouse.get(data.from_warehouse_id)
        if source is None or (source.quantity or 0) < data.quantity:
            available = source.quantity if source else 0
            raise ConflictError(
                f"موجودی انبار مبدأ کافی نیست. موجودی فعلی: {available} عدد — مقدار انتقال: {data.quantity} عدد."
            )
        target = by_warehouse.get(data.to_warehouse_id)
        if target is None:
            target = Inventory(product_id=data.product_id, warehouse_id=data.to_warehouse_id, quantity=0, reorder_point=10)
            db.add(target)

        reason = data.reason or "انتقال بین انبارها"
        out_move = stock_ledger.record(db, source, -data.quantity, "transfer_out", user=user, reason=reason,
                                       reference_type="transfer")
        db.flush()
        out_move.reference_id = out_move.id
        in_move = stock_ledger.record(db, target, data.quantity, "transfer_in", user=user, reason=reason,
                                      reference_type="transfer", reference_id=out_move.id)
        db.commit()
        db.refresh(out_move)
        db.refresh(in_move)
        return [out_move, in_move]
    except Exception:
        db.rollback()
        raise


def list_movements(db: Session, user: User, product_id: int | None = None, warehouse_id: int | None = None,
                   movement_type: str | None = None, date_from: datetime | None = None,
                   date_to: datetime | None = None, skip: int = 0, limit: int = 100) -> list[StockMovement]:
    if user.role not in ['org_admin', 'warehouse_manager']:
        raise ForbiddenError("شما مجوز مشاهده گردش کالا را ندارید.")
    if user.role == 'warehouse_manager':
        warehouse_id = _manager_warehouse(user)

    query = db.query(StockMovement).options(
        joinedload(StockMovement.product), joinedload(StockMovement.warehouse), joinedload(StockMovement.created_by),
    )
    if product_id is not None:
        query = query.filter(StockMovement.product_id == product_id)
    if warehouse_id is not None:
        query = query.filter(StockMovement.warehouse_id == warehouse_id)
    if movement_type is not None:
        query = query.filter(StockMovement.movement_type == movement_type)
    if date_from is not None:
        query = query.filter(StockMovement.created_at >= date_from)
    if date_to is not None:
        query = query.filter(StockMovement.created_at < date_to)
    return query.order_by(StockMovement.id.desc()).offset(skip).limit(limit).all()


def ledger_check(db: Session, user: User) -> dict:
    if user.role != 'org_admin':
        raise ForbiddenError("فقط ادمین سازمان می‌تواند صحت دفتر گردش کالا را بررسی کند.")
    mismatches = stock_ledger.find_mismatches(db)
    return {"ok": not mismatches, "mismatches": mismatches}
