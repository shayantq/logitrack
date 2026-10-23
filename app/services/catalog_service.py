"""
کاتالوگ کالا (مرحله ۱۳): مشخصات تکمیلی، تنوع‌ها و قیمت تاریخ‌دار با یارانه.

- قیمت هر کالا تاریخچه دارد؛ «قیمت در روز X» = آخرین قیمتی که effective_from آن ≤ X است.
- سفارش جدید قیمت روز تحویلش را می‌گیرد و روی اقلام سفارش ثبت می‌شود؛ پس تغییر قیمت (حتی برای گذشته)
  سفارش‌ها و صورت‌حساب‌های قبلی را تغییر نمی‌دهد.
- products.price کش «قیمت امروز» است و با هر تغییر قیمت و هر شب (Celery) به‌روز می‌شود.

داده پایه کالا (WMS فصل ۵):
- SKU یکتا (بدون حساسیت به حروف بزرگ و کوچک) و پس از ثبت تغییرناپذیر است.
- بارکد در کل سازمان یکتاست — چه بارکد خود کالا و چه بارکد واحدهای فرعی (کارتن، بسته).
- واحد پایه کوچک‌ترین واحد شمارش است؛ هر واحد فرعی عدد صحیحی از آن است، پس تبدیل همیشه دقیق است
  و موجودی همیشه عدد صحیحِ واحد پایه می‌ماند (to_base).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.wms import AVAILABLE
from app.models import Inventory, Order, OrderItem, Partner, Product, ProductPrice, ProductSupplier, ProductUom, User, Warehouse
from app.services import dispatch_service
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError

# مشخصات پایه‌ای که با فرم «مشخصات کالا» ویرایش می‌شوند (SKU عمداً نیست)
MASTER_FIELDS = ("name", "short_name", "weight_kg", "net_weight_kg", "length_cm", "width_cm", "height_cm",
                 "lot_tracked", "serial_tracked", "expiry_tracked", "shelf_life_days", "min_stock", "max_stock",
                 "reorder_point", "category", "brand", "unit", "barcode", "description", "origin", "origin_country",
                 "export_eligible", "hs_code", "specs", "parent_id", "variant_label", "is_active")

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
    invs = [i for i in product.stock_rows if _role(user) != "warehouse_manager" or i.warehouse_id == user.warehouse_id]
    invs = [i for i in invs if i.stock_status == AVAILABLE or i.quantity]
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
                   "quantity": i.quantity or 0, "reorder_point": i.reorder_point if i.stock_status == AVAILABLE else None,
                   "stock_status": i.stock_status, "reserved": i.reserved_quantity or 0, "free": i.free_quantity}
                  for i in sorted(invs, key=lambda i: (i.warehouse_id, i.stock_status != AVAILABLE, i.stock_status))],
        "uoms": [{"id": u.id, "name": u.name, "factor": u.factor, "barcode": u.barcode,
                  "is_purchase_default": u.is_purchase_default, "is_sales_default": u.is_sales_default} for u in product.uoms],
        "suppliers": [{"id": s.id, "partner_id": s.partner_id, "partner_code": s.partner.code if s.partner else "",
                       "partner_name": s.partner.name if s.partner else "", "supplier_sku": s.supplier_sku,
                       "lead_time_days": s.lead_time_days, "min_order_qty": s.min_order_qty, "last_price": s.last_price,
                       "is_preferred": s.is_preferred} for s in product.suppliers],
    }


def _fields(product: Product) -> dict:
    dims = (product.length_cm, product.width_cm, product.height_cm)
    return {
        "id": product.id, "name": product.name, "sku": product.sku, "weight_kg": product.weight_kg, "price": product.price,
        "short_name": product.short_name, "net_weight_kg": product.net_weight_kg, "length_cm": product.length_cm,
        "width_cm": product.width_cm, "height_cm": product.height_cm,
        "volume_m3": round(dims[0] * dims[1] * dims[2] / 1_000_000, 6) if all(dims) else None,
        "lot_tracked": bool(product.lot_tracked), "serial_tracked": bool(product.serial_tracked),
        "expiry_tracked": bool(product.expiry_tracked), "shelf_life_days": product.shelf_life_days,
        "min_stock": product.min_stock, "max_stock": product.max_stock, "reorder_point": product.reorder_point,
        "category": product.category, "brand": product.brand, "unit": product.unit or "عدد", "barcode": product.barcode,
        "description": product.description, "origin": product.origin or "domestic", "origin_country": product.origin_country,
        "export_eligible": bool(product.export_eligible), "hs_code": product.hs_code, "specs": product.specs or [],
        "parent_id": product.parent_id, "variant_label": product.variant_label, "is_active": product.is_active is not False,
        "created_at": product.created_at, "updated_at": product.updated_at,
    }


def ensure_unique_sku(db: Session, sku: str, exclude_id: int | None = None) -> None:
    """SKU یکتا در سازمان، بدون حساسیت به حروف بزرگ/کوچک (SKU-1 و sku-1 یک کد حساب می‌شوند)."""
    query = db.query(Product).filter(func.lower(Product.sku) == sku.lower())
    if exclude_id:
        query = query.filter(Product.id != exclude_id)
    if query.first():
        raise ConflictError(f"کد کالای «{sku}» تکراری است.")


_ensure_unique_sku = ensure_unique_sku


def ensure_unique_barcode(db: Session, barcode: str | None, *, product_id: int | None = None, uom_id: int | None = None) -> None:
    """بارکد در کل سازمان یکتاست: نه کالای دیگری، نه واحد فرعی دیگری (حتی از همین کالا) همان بارکد را ندارد."""
    if not barcode:
        return
    other = db.query(Product).filter(Product.barcode == barcode)
    if product_id is not None and uom_id is None:
        other = other.filter(Product.id != product_id)
    hit = other.first()
    if hit is not None:
        raise ConflictError(f"بارکد «{barcode}» قبلاً برای کالای «{hit.name}» ({hit.sku}) ثبت شده است.")
    uoms = db.query(ProductUom).filter(ProductUom.barcode == barcode)
    if uom_id is not None:
        uoms = uoms.filter(ProductUom.id != uom_id)
    hit_uom = uoms.first()
    if hit_uom is not None:
        owner = db.get(Product, hit_uom.product_id)
        raise ConflictError(f"بارکد «{barcode}» قبلاً برای واحد «{hit_uom.name}» کالای «{owner.name if owner else ''}» ثبت شده است.")


def validate_master(product: Product) -> None:
    """قواعد بین فیلدهای داده پایه (همان قیدهای CHECK دیتابیس، با پیام فارسی)."""
    if product.net_weight_kg and product.weight_kg and product.net_weight_kg > product.weight_kg:
        raise ConflictError("وزن خالص نمی‌تواند از وزن ناخالص بیشتر باشد.")
    if product.expiry_tracked and not product.lot_tracked:
        raise ConflictError("ردیابی تاریخ انقضا بدون ردیابی بچ (سری ساخت) ممکن نیست؛ «ردیابی بچ» را هم فعال کنید.")
    if product.shelf_life_days and not product.expiry_tracked:
        product.shelf_life_days = None
    lo, hi, rop = product.min_stock, product.max_stock, product.reorder_point
    if lo is not None and hi is not None and hi < lo:
        raise ConflictError("حداکثر موجودی نمی‌تواند کمتر از حداقل موجودی باشد.")
    if rop is not None and hi is not None and rop > hi:
        raise ConflictError("نقطه سفارش نمی‌تواند از حداکثر موجودی بیشتر باشد.")


def to_base(product: Product, quantity: int, uom: str | None) -> int:
    """مقدار به واحد uom ← واحد پایه (عدد صحیح). uom خالی یا همان واحد پایه یعنی بدون تبدیل."""
    if not uom or uom == (product.unit or "عدد"):
        return quantity
    match = next((u for u in product.uoms if u.name == uom), None)
    if match is None:
        raise ConflictError(f"واحد «{uom}» برای کالای «{product.name}» تعریف نشده است.")
    return quantity * match.factor


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
    for key in MASTER_FIELDS:
        if key in data:
            setattr(product, key, data[key])
    if product.origin == "domestic":
        product.origin_country = None
    if product.barcode is not None:
        product.barcode = product.barcode.strip() or None
    product.updated_at = datetime.now(timezone.utc)


def update(db: Session, user: User, product_id: int, data: dict) -> dict:
    _ensure_editor(user)
    product = _product(db, product_id)
    if "sku" in data and data["sku"] != product.sku:
        raise ConflictError("کد کالا (SKU) پس از ثبت تغییرناپذیر است؛ برای کد جدید، کالای تازه تعریف و این کالا را بایگانی کنید.")
    if "parent_id" in data:
        _validate_parent(db, product.id, data["parent_id"])
    if data.get("barcode"):
        ensure_unique_barcode(db, data["barcode"], product_id=product.id)
    try:
        apply_fields(product, data)
        validate_master(product)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return detail(db, user, product.id)


def set_uoms(db: Session, user: User, product_id: int, uoms: list[dict]) -> dict:
    """جایگزینی کامل فهرست واحدهای فرعی کالا (مقادیر اسناد قبلی به واحد پایه ثبت شده‌اند و عوض نمی‌شوند)."""
    _ensure_editor(user)
    product = _product(db, product_id)
    names = [u["name"] for u in uoms]
    if len(set(names)) != len(names):
        raise ConflictError("نام واحدهای فرعی تکراری است.")
    if (product.unit or "عدد") in names:
        raise ConflictError(f"«{product.unit}» واحد پایه همین کالاست؛ واحد فرعی باید نام دیگری داشته باشد.")
    barcodes = [u["barcode"] for u in uoms if u.get("barcode")]
    if len(set(barcodes)) != len(barcodes) or (product.barcode and product.barcode in barcodes):
        raise ConflictError("بارکد واحدها باید با هم و با بارکد خود کالا فرق داشته باشد.")
    for key in ("is_purchase_default", "is_sales_default"):
        if sum(1 for u in uoms if u.get(key)) > 1:
            raise ConflictError("فقط یک واحد می‌تواند پیش‌فرض خرید (یا فروش) باشد.")
    existing = {u.name: u for u in product.uoms}
    # اول همه بررسی‌ها، بعد تغییر (تا خطا نیمه‌کاره چیزی را عوض نکند)
    for data in uoms:
        row = existing.get(data["name"])
        ensure_unique_barcode(db, data.get("barcode"), uom_id=row.id if row else -1)
    keep = set()
    for data in uoms:
        row = existing.get(data["name"])
        if row is None:
            row = ProductUom(organization_id=product.organization_id, name=data["name"])
            product.uoms.append(row)
        row.factor, row.barcode = data["factor"], data.get("barcode")
        row.is_purchase_default, row.is_sales_default = bool(data.get("is_purchase_default")), bool(data.get("is_sales_default"))
        keep.add(data["name"])
    for name, row in existing.items():
        if name not in keep:
            product.uoms.remove(row)
    product.updated_at = datetime.now(timezone.utc)
    db.commit()
    return detail(db, user, product.id)


def set_suppliers(db: Session, user: User, product_id: int, links: list[dict]) -> dict:
    """جایگزینی کامل تأمین‌کننده‌های کالا؛ فقط طرف‌های فعال با نقش «تأمین‌کننده»، حداکثر یک تأمین‌کننده اصلی."""
    _ensure_editor(user)
    product = _product(db, product_id)
    ids = [link["partner_id"] for link in links]
    if len(set(ids)) != len(ids):
        raise ConflictError("یک تأمین‌کننده دو بار انتخاب شده است.")
    if sum(1 for link in links if link.get("is_preferred")) > 1:
        raise ConflictError("فقط یک تأمین‌کننده می‌تواند «اصلی» باشد.")
    partners = {p.id: p for p in db.query(Partner).filter(Partner.id.in_(ids or [-1])).all()}
    existing = {s.partner_id: s for s in product.suppliers}
    for link in links:
        partner = partners.get(link["partner_id"])
        if partner is None:
            raise NotFoundError("تأمین‌کننده یافت نشد.")
        if not partner.is_supplier:
            raise ConflictError(f"«{partner.name}» نقش تأمین‌کننده ندارد.")
        if partner.id not in existing and partner.is_active is False:
            raise ConflictError(f"«{partner.name}» غیرفعال است.")
    for link in links:
        partner = partners[link["partner_id"]]
        row = existing.get(partner.id)
        if row is None:
            row = ProductSupplier(organization_id=product.organization_id, partner_id=partner.id)
            product.suppliers.append(row)
        for key in ("supplier_sku", "lead_time_days", "min_order_qty", "last_price"):
            setattr(row, key, link.get(key))
        row.is_preferred = bool(link.get("is_preferred"))
    for partner_id, row in existing.items():
        if partner_id not in set(ids):
            product.suppliers.remove(row)
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
    # بارکد مال همان کالاست و به تنوع کپی نمی‌شود
    apply_fields(variant, {**_fields(root), "name": data.get("name") or root.name, "barcode": None,
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
