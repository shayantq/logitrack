"""
کاتالوگ کالا (مرحله ۱۳): مشخصات تکمیلی، تنوع‌ها و قیمت تاریخ‌دار با یارانه.

- قیمت هر کالا تاریخچه دارد؛ «قیمت در روز X» = آخرین قیمتی که effective_from آن ≤ X است.
- سفارش جدید قیمت روز تحویلش را می‌گیرد و روی اقلام سفارش ثبت می‌شود؛ پس تغییر قیمت (حتی برای گذشته)
  سفارش‌ها و صورت‌حساب‌های قبلی را تغییر نمی‌دهد.
- products.price کش «قیمت امروز» است و با هر تغییر قیمت و هر شب (Celery) به‌روز می‌شود.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models import Inventory, Order, OrderItem, Product, ProductPrice, User, Warehouse
from app.services import dispatch_service
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError

EDITORS = ("org_admin", "warehouse_manager")
ORIGINS = ("domestic", "imported")


def _role(user: User) -> str:
    return getattr(user.role, "value", user.role)


def _ensure_editor(user: User) -> None:
    if _role(user) not in EDITORS:
        raise ForbiddenError("ویرایش کاتالوگ فقط برای ادمین سازمان و مدیر انبار است.")


def today_local() -> date:
    return dispatch_service.to_local(datetime.now(timezone.utc).replace(tzinfo=None)).date()


def final_price(base_price: float, subsidy_percent: float) -> float:
    return round((base_price or 0) * (1 - (subsidy_percent or 0) / 100))


# ---------------------------------------------------------------------------
# قیمت
# ---------------------------------------------------------------------------
def price_at(db: Session, product_id: int, day: date) -> ProductPrice | None:
    return db.query(ProductPrice).filter(ProductPrice.product_id == product_id, ProductPrice.effective_from <= day) \
        .order_by(ProductPrice.effective_from.desc()).first()


def prices_at(db: Session, product_ids: list[int], day: date) -> dict[int, ProductPrice]:
    """قیمت مؤثر چند کالا در یک روز (یک پرس‌وجو)."""
    result: dict[int, ProductPrice] = {}
    rows = db.query(ProductPrice).filter(ProductPrice.product_id.in_(product_ids or [-1]), ProductPrice.effective_from <= day) \
        .order_by(ProductPrice.product_id, ProductPrice.effective_from).all()
    for row in rows:
        result[row.product_id] = row          # آخرین (بزرگ‌ترین تاریخ) جایگزین می‌شود
    return result


def unit_price_for_order(db: Session, product: Product, delivery_day: date) -> float:
    price = price_at(db, product.id, delivery_day)
    return price.final_price if price else (product.price or 0)


def refresh_cached_price(db: Session, product: Product) -> None:
    current = price_at(db, product.id, today_local())
    if current is not None:
        product.price = current.final_price


def refresh_all_cached_prices(db: Session) -> int:
    """هر شب: قیمت‌های آینده‌ای که امروز اعمال می‌شوند در کش products.price قرار گیرند."""
    changed = 0
    products = db.query(Product).all()
    current = prices_at(db, [p.id for p in products], today_local())
    for p in products:
        price = current.get(p.id)
        if price and p.price != price.final_price:
            p.price = price.final_price
            changed += 1
    db.commit()
    return changed


def set_price(db: Session, user: User | None, product: Product, *, effective_from: date, base_price: float,
              subsidy_percent: float = 0, cost_price: float | None = None, note: str | None = None) -> ProductPrice:
    """قیمت از یک روز به بعد (اگر برای همان روز قیمت هست، جایگزین می‌شود)."""
    row = db.query(ProductPrice).filter(ProductPrice.product_id == product.id, ProductPrice.effective_from == effective_from).first()
    if row is None:
        row = ProductPrice(organization_id=product.organization_id, product_id=product.id, effective_from=effective_from)
        db.add(row)
    row.base_price, row.subsidy_percent = base_price, subsidy_percent or 0
    row.final_price = final_price(base_price, subsidy_percent)
    row.cost_price, row.note = cost_price, (note or "").strip() or None
    row.created_by_id = user.id if user else None
    db.flush()
    refresh_cached_price(db, product)
    product.updated_at = datetime.now(timezone.utc)
    return row


def add_price(db: Session, user: User, product_id: int, **data) -> dict:
    _ensure_editor(user)
    product = _product(db, product_id)
    set_price(db, user, product, **data)
    db.commit()
    return detail(db, user, product.id)


def delete_price(db: Session, user: User, price_id: int) -> dict:
    _ensure_editor(user)
    row = db.get(ProductPrice, price_id)
    if row is None:
        raise NotFoundError("قیمت یافت نشد.")
    product = _product(db, row.product_id)
    if len(product.prices) <= 1:
        raise ConflictError("کالا باید دست‌کم یک قیمت داشته باشد.")
    # قیمت آینده آزادانه حذف می‌شود؛ قیمت گذشته/فعلی فقط اگر هیچ سفارشی در دوره اعتبارش ثبت نشده باشد
    later = [p.effective_from for p in product.prices if p.effective_from > row.effective_from]
    if row.effective_from <= today_local() and _used_between(db, product.id, row.effective_from, min(later) if later else None):
        raise ConflictError("این قیمت در سفارش‌های ثبت‌شده استفاده شده است؛ به‌جای حذف، قیمت جدیدی از امروز ثبت کنید.")
    db.delete(row)
    db.flush()
    refresh_cached_price(db, product)
    db.commit()
    return detail(db, user, product.id)


def _used_between(db: Session, product_id: int, start_day: date, end_day: date | None) -> bool:
    start = dispatch_service.local_to_utc(datetime.combine(start_day, datetime.min.time()))
    query = db.query(OrderItem.id).join(Order, OrderItem.order_id == Order.id)         .filter(OrderItem.product_id == product_id, Order.delivery_window_start >= start)
    if end_day is not None:
        query = query.filter(Order.delivery_window_start < dispatch_service.local_to_utc(datetime.combine(end_day, datetime.min.time())))
    return query.first() is not None


# ---------------------------------------------------------------------------
# کالا
# ---------------------------------------------------------------------------
def _product(db: Session, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise NotFoundError("کالا یافت نشد.")
    return product


def detail(db: Session, user: User, product_id: int) -> dict:
    product = _product(db, product_id)
    today = today_local()
    current = price_at(db, product.id, today)
    warehouses = {w.id: w for w in db.query(Warehouse).all()}
    invs = [i for i in product.inventories if _role(user) != "warehouse_manager" or i.warehouse_id == user.warehouse_id]
    parent = db.get(Product, product.parent_id) if product.parent_id else None
    family_root = parent or product
    variants = db.query(Product).filter(Product.parent_id == family_root.id).order_by(Product.id).all()
    names = {u.id: u.full_name or u.username for u in db.query(User).filter(
        User.id.in_({p.created_by_id for p in product.prices if p.created_by_id} or {-1})).all()}
    return {
        **_fields(product),
        "current_price": current.final_price if current else product.price,
        "current_base_price": current.base_price if current else product.price,
        "current_subsidy_percent": current.subsidy_percent if current else 0,
        "prices": [{
            "id": p.id, "effective_from": p.effective_from, "base_price": p.base_price, "subsidy_percent": p.subsidy_percent,
            "final_price": p.final_price, "cost_price": p.cost_price, "note": p.note, "created_by": names.get(p.created_by_id),
            "is_current": current is not None and p.id == current.id, "is_future": p.effective_from > today,
        } for p in sorted(product.prices, key=lambda p: p.effective_from, reverse=True)],
        "parent": {"id": parent.id, "name": parent.name, "sku": parent.sku} if parent else None,
        "variants": [{"id": v.id, "name": v.name, "sku": v.sku, "variant_label": v.variant_label, "origin": v.origin,
                      "origin_country": v.origin_country, "price": v.price,
                      "stock": sum(i.quantity or 0 for i in v.inventories)} for v in variants if v.id != product.id]
                    + ([{"id": family_root.id, "name": family_root.name, "sku": family_root.sku, "variant_label": "کالای اصلی",
                         "origin": family_root.origin, "origin_country": family_root.origin_country, "price": family_root.price,
                         "stock": sum(i.quantity or 0 for i in family_root.inventories)}] if parent else []),
        "stock": [{"warehouse_id": i.warehouse_id, "warehouse_name": warehouses[i.warehouse_id].name if i.warehouse_id in warehouses else "—",
                   "quantity": i.quantity or 0, "reorder_point": i.reorder_point} for i in invs],
    }


def _fields(product: Product) -> dict:
    return {
        "id": product.id, "name": product.name, "sku": product.sku, "weight_kg": product.weight_kg, "price": product.price,
        "category": product.category, "brand": product.brand, "unit": product.unit or "عدد", "barcode": product.barcode,
        "description": product.description, "origin": product.origin or "domestic", "origin_country": product.origin_country,
        "export_eligible": bool(product.export_eligible), "hs_code": product.hs_code, "specs": product.specs or [],
        "parent_id": product.parent_id, "variant_label": product.variant_label, "is_active": product.is_active is not False,
        "created_at": product.created_at, "updated_at": product.updated_at,
    }


def _ensure_unique_sku(db: Session, sku: str, exclude_id: int | None = None) -> None:
    query = db.query(Product).filter(Product.sku == sku)
    if exclude_id:
        query = query.filter(Product.id != exclude_id)
    if query.first():
        raise ConflictError(f"کد کالای «{sku}» تکراری است.")


def _validate_parent(db: Session, product_id: int | None, parent_id: int | None) -> None:
    if parent_id is None:
        return
    parent = db.get(Product, parent_id)
    if parent is None:
        raise NotFoundError("کالای اصلی یافت نشد.")
    if parent.parent_id is not None:
        raise ConflictError("تنوع فقط زیر یک کالای اصلی تعریف می‌شود (تنوعِ تنوع مجاز نیست).")
    if product_id is not None and (parent_id == product_id or db.query(Product).filter(Product.parent_id == product_id).first()):
        raise ConflictError("کالایی که خودش تنوع دارد نمی‌تواند تنوع کالای دیگری باشد.")


def apply_fields(product: Product, data: dict) -> None:
    for key in ("name", "sku", "weight_kg", "category", "brand", "unit", "barcode", "description", "origin", "origin_country",
                "export_eligible", "hs_code", "specs", "parent_id", "variant_label", "is_active"):
        if key in data:
            setattr(product, key, data[key])
    if product.origin == "domestic":
        product.origin_country = None
    product.updated_at = datetime.now(timezone.utc)


def update(db: Session, user: User, product_id: int, data: dict) -> dict:
    _ensure_editor(user)
    product = _product(db, product_id)
    if "sku" in data:
        _ensure_unique_sku(db, data["sku"], product.id)
    if "parent_id" in data:
        _validate_parent(db, product.id, data["parent_id"])
    apply_fields(product, data)
    db.commit()
    return detail(db, user, product.id)


def create_variant(db: Session, user: User, product_id: int, data: dict) -> dict:
    """تنوع جدید: مشخصات کالای اصلی کپی می‌شود؛ کد، عنوان تنوع، مبدأ و قیمت جدید."""
    _ensure_editor(user)
    base = _product(db, product_id)
    root = db.get(Product, base.parent_id) if base.parent_id else base
    _ensure_unique_sku(db, data["sku"])
    variant = Product(organization_id=root.organization_id, name=data.get("name") or root.name, sku=data["sku"],
                      weight_kg=root.weight_kg, price=0)
    apply_fields(variant, {**_fields(root), "name": data.get("name") or root.name, "sku": data["sku"],
                           "parent_id": root.id, "variant_label": data["variant_label"],
                           "origin": data.get("origin") or root.origin, "origin_country": data.get("origin_country"),
                           "specs": data.get("specs") if data.get("specs") is not None else root.specs})
    db.add(variant)
    db.flush()
    set_price(db, user, variant, effective_from=data.get("effective_from") or today_local(), base_price=data["base_price"],
              subsidy_percent=data.get("subsidy_percent") or 0)
    # موجودی صفر در انبارهایی که کالای اصلی دارد (برای نمایش و ثبت ورود کالا)
    for inv in root.inventories:
        if _role(user) == "warehouse_manager" and inv.warehouse_id != user.warehouse_id:
            continue
        db.add(Inventory(organization_id=root.organization_id, product_id=variant.id, warehouse_id=inv.warehouse_id,
                         quantity=0, reorder_point=inv.reorder_point))
    db.commit()
    return detail(db, user, variant.id)


def categories(db: Session) -> list[str]:
    rows = db.query(Product.category).filter(Product.category.isnot(None)).distinct().all()
    return sorted(r[0] for r in rows if r[0])
