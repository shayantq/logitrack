"""
محل‌های انبار (فصل ۶): سلسله‌مراتب، نوع، ظرفیت و قواعد اختلاط.

- سطح‌ها: منطقه ← راهرو ← قفسه ← طبقه ← خانه. زیرمجموعه همیشه سطح پایین‌تری دارد، پس حلقه ممکن نیست.
- کالا فقط در محل انتهایی (بدون زیرمجموعه)، فعال و غیرمسدود می‌نشیند؛ به محلی که کالا دارد زیرمجموعه اضافه نمی‌شود.
- ظرفیت (وزن، حجم، پالت) و اختلاط (کالا، بچ، مالک) هنگام هر ورود کالا در دفتر گردش بررسی می‌شود
  (ensure_fits، با قفل ردیف محل تا دو ورود هم‌زمان با هم از ظرفیت رد نشوند). همین قواعد در پیشنهاد مقصد جانمایی.
- فقط موجودی تأییدشده‌ی محل نگهداری/برداشت (فعال و غیرمسدود) قابل تخصیص به سفارش است. تغییری در محل که
  موجودی قابل تخصیص را کمتر از رزرو سفارش‌های باز کند رد می‌شود.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.wms import ALLOCATABLE_LOCATION_TYPES, LOCATION_LEVEL_LABELS, LOCATION_LEVELS, LOCATION_TYPES
from app.models import Inventory, Location, Product, StockBalance, StockMovementLine, User, Warehouse
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError

STAFF = ("org_admin", "warehouse_manager")


def _role(user: User) -> str:
    return getattr(user.role, "value", user.role)


def label(location: Location | None) -> str:
    return location.code if location is not None else "بدون محل"


def is_allocatable(location: Location | None) -> bool:
    """موجودی تأییدشده این محل قابل تخصیص به سفارش است؟ (بدون محل = بله، مثل انبار بدون محل‌بندی)"""
    if location is None:
        return True
    return location.location_type in ALLOCATABLE_LOCATION_TYPES and location.is_active is not False and not location.is_blocked


def has_children(db: Session, location_id: int) -> bool:
    return db.query(Location.id).filter(Location.parent_id == location_id).first() is not None


# ---------------------------------------------------------------------------
# محتوا و ظرفیت
# ---------------------------------------------------------------------------
@dataclass
class Content:
    product_id: int
    lot_number: str | None
    owner_id: int | None
    quantity: int


def contents(db: Session, location_ids) -> dict[int, list[Content]]:
    ids = list(set(location_ids))
    result: dict[int, list[Content]] = defaultdict(list)
    if not ids:
        return result
    rows = db.query(StockBalance.location_id, StockBalance.product_id, StockBalance.lot_number, StockBalance.owner_id,
                    func.sum(StockBalance.quantity)).filter(
        StockBalance.location_id.in_(ids), StockBalance.quantity > 0,
    ).group_by(StockBalance.location_id, StockBalance.product_id, StockBalance.lot_number, StockBalance.owner_id).all()
    for location_id, product_id, lot, owner, qty in rows:
        result[location_id].append(Content(product_id, lot, owner, int(qty)))
    return result


def unit_volume_m3(product: Product) -> float:
    if product.length_cm and product.width_cm and product.height_cm:
        return product.length_cm * product.width_cm * product.height_cm / 1_000_000
    return 0.0


def _pallets(quantity: int, product: Product) -> int:
    return math.ceil(quantity / product.units_per_pallet) if product.units_per_pallet else 0


def usage(items: list[Content], products: dict[int, Product]) -> dict:
    per_product: dict[int, int] = defaultdict(int)
    for c in items:
        per_product[c.product_id] += c.quantity
    weight = sum(q * (products[p].weight_kg or 0) for p, q in per_product.items() if p in products)
    volume = sum(q * unit_volume_m3(products[p]) for p, q in per_product.items() if p in products)
    pallets = sum(_pallets(q, products[p]) for p, q in per_product.items() if p in products)
    return {"quantity": sum(per_product.values()), "products": len(per_product), "weight_kg": round(weight, 3),
            "volume_m3": round(volume, 4), "pallets": pallets}


def fit_problems(location: Location, product: Product, quantity: int, *, lot_number: str | None, owner_id: int | None,
                 items: list[Content], products: dict[int, Product], is_leaf: bool) -> list[str]:
    """دلایلی که quantity واحد از product در این محل جا نمی‌شود (خالی = جا می‌شود)."""
    name = location.code
    if location.is_active is False:
        return [f"محل {name} غیرفعال است."]
    if location.is_blocked:
        return [f"محل {name} مسدود است" + (f" ({location.block_reason})." if location.block_reason else ".")]
    if not is_leaf:
        return [f"محل {name} زیرمجموعه دارد؛ کالا فقط در محل انتهایی (مثلاً خانه قفسه) نگهداری می‌شود."]
    problems = []
    others = {c.product_id for c in items if c.product_id != product.id}
    if others and not location.allow_mixed_products:
        other = products.get(next(iter(others)))
        problems.append(f"محل {name} فقط یک نوع کالا می‌پذیرد و الان «{other.name if other else 'کالای دیگر'}» در آن است.")
    if not location.allow_mixed_lots and any(c.product_id == product.id and c.lot_number != lot_number for c in items):
        problems.append(f"محل {name} اختلاط بچ را نمی‌پذیرد و بچ دیگری از همین کالا در آن است.")
    if not location.allow_mixed_owners and any(c.owner_id != owner_id for c in items):
        problems.append(f"محل {name} کالای چند مالک را با هم نمی‌پذیرد.")

    after = items + [Content(product.id, lot_number, owner_id, quantity)]
    catalog = {**products, product.id: product}
    used = usage(after, catalog)
    if location.max_weight_kg is not None and used["weight_kg"] > location.max_weight_kg + 1e-9:
        problems.append(f"ظرفیت وزنی محل {name} {location.max_weight_kg:g} کیلوگرم است؛ با این ورود {used['weight_kg']:g} کیلوگرم می‌شود.")
    if location.max_volume_m3 is not None and used["volume_m3"] > location.max_volume_m3 + 1e-9:
        problems.append(f"ظرفیت حجمی محل {name} {location.max_volume_m3:g} مترمکعب است؛ با این ورود {used['volume_m3']:g} مترمکعب می‌شود.")
    if location.max_pallets is not None and used["pallets"] > location.max_pallets:
        problems.append(f"ظرفیت محل {name} {location.max_pallets} پالت است؛ با این ورود {used['pallets']} پالت می‌شود.")
    return problems


def ensure_fits(db: Session, inventory: Inventory, location_id: int, quantity: int, *, lot_number: str | None,
                owner_id: int | None) -> Location:
    """دفتر گردش کالا پیش از هر ورود به محل صدا می‌زند. ردیف محل قفل می‌شود (ورودهای هم‌زمان پشت سر هم)."""
    location = db.query(Location).filter(Location.id == location_id).with_for_update().first()
    if location is None:
        raise NotFoundError("محل انتخاب‌شده یافت نشد.")
    if location.warehouse_id != inventory.warehouse_id:
        raise ConflictError(f"محل {location.code} متعلق به این انبار نیست.")
    db.flush()
    items = contents(db, [location.id]).get(location.id, [])
    product = inventory.product or db.get(Product, inventory.product_id)
    products = {p.id: p for p in db.query(Product).filter(Product.id.in_({c.product_id for c in items} or {-1})).all()}
    problems = fit_problems(location, product, quantity, lot_number=lot_number, owner_id=owner_id, items=items,
                            products=products, is_leaf=not has_children(db, location.id))
    if problems:
        raise ConflictError(" ".join(problems))
    return location


# ---------------------------------------------------------------------------
# دسترسی
# ---------------------------------------------------------------------------
def ensure_staff(user: User) -> None:
    if _role(user) not in STAFF:
        raise ForbiddenError("این بخش فقط برای ادمین سازمان و مدیر انبار است.")


def scope_warehouse(user: User, warehouse_id: int | None) -> int | None:
    """مدیر انبار همیشه انبار خودش؛ ادمین هر انباری (یا همه با None)."""
    ensure_staff(user)
    if _role(user) == "warehouse_manager":
        if not user.warehouse_id:
            raise ConflictError("حساب کاربری شما به هیچ انباری متصل نشده است.")
        if warehouse_id is not None and warehouse_id != user.warehouse_id:
            raise ForbiddenError("مدیر انبار فقط به انبار خودش دسترسی دارد.")
        return user.warehouse_id
    return warehouse_id


def get(db: Session, user: User, location_id: int) -> Location:
    location = db.get(Location, location_id)
    if location is None:
        raise NotFoundError("محل یافت نشد.")
    scope_warehouse(user, location.warehouse_id)
    return location


def resolve(db: Session, warehouse_id: int, location_id: int | None) -> Location | None:
    """محل انتخاب‌شده در فرم‌ها (بدون قفل) — باید در همان انبار باشد."""
    if location_id is None:
        return None
    location = db.get(Location, location_id)
    if location is None or location.warehouse_id != warehouse_id:
        raise NotFoundError("محل انتخاب‌شده در این انبار یافت نشد.")
    return location


def find_by_scan(db: Session, warehouse_id: int, scanned: str) -> Location | None:
    """بارکد یا کد محل اسکن‌شده (بدون حساسیت به حروف بزرگ و کوچک) در یک انبار."""
    value = (scanned or "").strip().upper()
    if not value:
        return None
    return db.query(Location).filter(
        Location.warehouse_id == warehouse_id,
        (func.upper(Location.barcode) == value) | (func.upper(Location.code) == value),
    ).first()


# ---------------------------------------------------------------------------
# فهرست و جزئیات
# ---------------------------------------------------------------------------
def _ordered(locations: list[Location]) -> list[tuple[Location, int]]:
    children: dict[int | None, list[Location]] = defaultdict(list)
    ids = {loc.id for loc in locations}
    for loc in sorted(locations, key=lambda x: x.code):
        children[loc.parent_id if loc.parent_id in ids else None].append(loc)
    result: list[tuple[Location, int]] = []

    def walk(parent_id, depth):
        for loc in children.get(parent_id, []):
            result.append((loc, depth))
            walk(loc.id, depth + 1)
    walk(None, 0)
    return result


def serialize(location: Location, depth: int, used: dict, leaf: bool) -> dict:
    def pct(value, cap):
        return round(100 * value / cap, 1) if cap else None
    kind = LOCATION_TYPES[location.location_type]
    return {
        "id": location.id, "warehouse_id": location.warehouse_id, "parent_id": location.parent_id, "depth": depth,
        "level": location.level, "level_label": LOCATION_LEVEL_LABELS[location.level], "code": location.code,
        "barcode": location.barcode, "name": location.name, "location_type": location.location_type,
        "location_type_label": kind.label, "allocatable": is_allocatable(location), "is_leaf": leaf,
        "max_weight_kg": location.max_weight_kg, "max_volume_m3": location.max_volume_m3, "max_pallets": location.max_pallets,
        "allow_mixed_products": location.allow_mixed_products, "allow_mixed_lots": location.allow_mixed_lots,
        "allow_mixed_owners": location.allow_mixed_owners, "is_active": location.is_active is not False,
        "is_blocked": bool(location.is_blocked), "block_reason": location.block_reason,
        "quantity": used["quantity"], "products": used["products"], "weight_kg": used["weight_kg"],
        "volume_m3": used["volume_m3"], "pallets": used["pallets"],
        "weight_pct": pct(used["weight_kg"], location.max_weight_kg), "volume_pct": pct(used["volume_m3"], location.max_volume_m3),
        "pallets_pct": pct(used["pallets"], location.max_pallets),
    }


def _products_for(db: Session, groups: dict[int, list[Content]]) -> dict[int, Product]:
    ids = {c.product_id for items in groups.values() for c in items}
    return {p.id: p for p in db.query(Product).filter(Product.id.in_(ids or {-1})).all()}


def list_locations(db: Session, user: User, warehouse_id: int) -> list[dict]:
    warehouse_id = scope_warehouse(user, warehouse_id)
    if db.get(Warehouse, warehouse_id) is None:
        raise NotFoundError("انبار یافت نشد.")
    locations = db.query(Location).filter(Location.warehouse_id == warehouse_id).all()
    groups = contents(db, [loc.id for loc in locations])
    products = _products_for(db, groups)
    parents = {loc.parent_id for loc in locations if loc.parent_id}
    return [serialize(loc, depth, usage(groups.get(loc.id, []), products), loc.id not in parents)
            for loc, depth in _ordered(locations)]


def location_detail(db: Session, user: User, location_id: int) -> dict:
    location = get(db, user, location_id)
    groups = contents(db, [location.id])
    products = _products_for(db, groups)
    data = serialize(location, 0, usage(groups.get(location.id, []), products), not has_children(db, location.id))
    balances = db.query(StockBalance).filter(StockBalance.location_id == location.id, StockBalance.quantity > 0) \
        .order_by(StockBalance.product_id, StockBalance.expiry_date, StockBalance.id).all()
    from app.core.wms import STOCK_STATUS_LABELS
    data["contents"] = [{
        "balance_id": b.id, "product_id": b.product_id, "product_name": b.product.name, "product_sku": b.product.sku,
        "stock_status": b.stock_status, "stock_status_label": STOCK_STATUS_LABELS.get(b.stock_status, b.stock_status),
        "lot_number": b.lot_number, "serial_number": b.serial_number, "expiry_date": b.expiry_date,
        "owner_id": b.owner_id, "owner_name": b.owner.name if b.owner else None, "quantity": b.quantity,
    } for b in balances]
    return data


def lookup(db: Session, user: User, warehouse_id: int, code: str) -> dict:
    warehouse_id = scope_warehouse(user, warehouse_id)
    location = find_by_scan(db, warehouse_id, code)
    if location is None:
        raise NotFoundError(f"محلی با بارکد/کد «{code}» در این انبار نیست.")
    return location_detail(db, user, location.id)


# ---------------------------------------------------------------------------
# ساخت، ویرایش، حذف
# ---------------------------------------------------------------------------
FIELDS = ("level", "code", "barcode", "name", "location_type", "max_weight_kg", "max_volume_m3", "max_pallets",
          "allow_mixed_products", "allow_mixed_lots", "allow_mixed_owners", "is_active", "is_blocked", "block_reason",
          "parent_id")


def _rank(level: str) -> int:
    return LOCATION_LEVELS.index(level)


def _validate(db: Session, warehouse: Warehouse, data: dict, location: Location | None = None) -> dict:
    code = data["code"].strip().upper()
    duplicate = db.query(Location.id).filter(Location.warehouse_id == warehouse.id, func.upper(Location.code) == code)
    if location is not None:
        duplicate = duplicate.filter(Location.id != location.id)
    if duplicate.first():
        raise ConflictError(f"کد محل «{code}» در این انبار تکراری است.")
    data["code"] = code
    barcode = (data.get("barcode") or "").strip().upper() or f"{warehouse.code}-{code}".upper()
    duplicate = db.query(Location.id).filter(func.upper(Location.barcode) == barcode)
    if location is not None:
        duplicate = duplicate.filter(Location.id != location.id)
    if duplicate.first():
        raise ConflictError(f"بارکد محل «{barcode}» تکراری است.")
    data["barcode"] = barcode

    parent_id = data.get("parent_id")
    if parent_id is not None:
        parent = db.get(Location, parent_id)
        if parent is None or parent.warehouse_id != warehouse.id:
            raise NotFoundError("محل مادر در این انبار یافت نشد.")
        if _rank(data["level"]) <= _rank(parent.level):
            raise ConflictError(f"زیرمجموعه «{LOCATION_LEVEL_LABELS[parent.level]}» باید سطح پایین‌تری داشته باشد "
                                f"(مثلاً {LOCATION_LEVEL_LABELS[LOCATION_LEVELS[min(_rank(parent.level) + 1, 4)]]}).")
        if parent.level == LOCATION_LEVELS[-1]:
            raise ConflictError("«خانه» پایین‌ترین سطح است و زیرمجموعه نمی‌گیرد.")
        if db.query(StockBalance.id).filter(StockBalance.location_id == parent.id, StockBalance.quantity > 0).first():
            raise ConflictError(f"محل {parent.code} کالا دارد؛ ابتدا کالاها را جابه‌جا کنید، بعد زیرمجموعه بسازید.")
    if location is not None:
        child_levels = [lvl for (lvl,) in db.query(Location.level).filter(Location.parent_id == location.id).all()]
        if any(_rank(lvl) <= _rank(data["level"]) for lvl in child_levels):
            raise ConflictError("سطح این محل باید بالاتر از سطح زیرمجموعه‌هایش بماند.")
    if not data.get("is_blocked"):
        data["block_reason"] = None
    elif not data.get("block_reason"):
        raise ConflictError("برای مسدود کردن محل، دلیل را بنویسید.")
    return data


def _check_contents_still_fit(db: Session, location: Location) -> None:
    """کاهش ظرفیت یا سخت‌تر کردن قاعده اختلاط نباید موجودی فعلی محل را «غیرمجاز» کند."""
    items = contents(db, [location.id]).get(location.id, [])
    if not items:
        return
    if location.is_active is False:
        raise ConflictError(f"محل {location.code} کالا دارد و غیرفعال نمی‌شود؛ ابتدا کالاها را جابه‌جا کنید (یا محل را مسدود کنید).")
    products = _products_for(db, {location.id: items})
    used = usage(items, products)
    if len({c.product_id for c in items}) > 1 and not location.allow_mixed_products:
        raise ConflictError(f"محل {location.code} الان چند نوع کالا دارد و نمی‌تواند «تک‌کالایی» شود.")
    lots: dict[int, set] = defaultdict(set)
    for c in items:
        lots[c.product_id].add(c.lot_number)
    if any(len(v) > 1 for v in lots.values()) and not location.allow_mixed_lots:
        raise ConflictError(f"محل {location.code} الان چند بچ از یک کالا دارد و نمی‌تواند «تک‌بچی» شود.")
    if len({c.owner_id for c in items}) > 1 and not location.allow_mixed_owners:
        raise ConflictError(f"محل {location.code} الان کالای چند مالک دارد.")
    for key, cap, unit in (("weight_kg", location.max_weight_kg, "کیلوگرم"), ("volume_m3", location.max_volume_m3, "مترمکعب"),
                           ("pallets", location.max_pallets, "پالت")):
        if cap is not None and used[key] > cap + 1e-9:
            raise ConflictError(f"محل {location.code} الان {used[key]:g} {unit} کالا دارد؛ ظرفیت نمی‌تواند کمتر از آن شود.")


def _check_reservations(db: Session, location: Location) -> None:
    """اگر موجودی محل قابل تخصیص نماند، رزرو سفارش‌های باز باید هنوز از جای دیگر پوشش داشته باشد."""
    from app.services import allocation_service
    inventory_ids = {i for (i,) in db.query(StockBalance.inventory_id).filter(
        StockBalance.location_id == location.id, StockBalance.quantity > 0).all()}
    for inventory in db.query(Inventory).filter(Inventory.id.in_(inventory_ids or {-1})).all():
        allocation_service.ensure_covered(db, inventory)


def create_location(db: Session, user: User, warehouse_id: int, data: dict) -> dict:
    warehouse_id = scope_warehouse(user, warehouse_id)
    warehouse = db.get(Warehouse, warehouse_id)
    if warehouse is None:
        raise NotFoundError("انبار یافت نشد.")
    from app.services import warehouse_service
    if not warehouse_service.type_of(warehouse).holds_stock:
        raise ConflictError(f"«{warehouse.name}» کالا نگه نمی‌دارد و محل‌بندی ندارد.")
    try:
        data = _validate(db, warehouse, dict(data))
        location = Location(warehouse_id=warehouse.id, **{k: data.get(k) for k in FIELDS if k in data})
        db.add(location)
        db.flush()
        from app.services import audit_service
        audit_service.log(db, user, "location.create", f"محل {location.code} در انبار «{warehouse.name}» ساخته شد",
                          target_type="location", target_id=location.id, target_label=location.code)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return location_detail(db, user, location.id)


def update_location(db: Session, user: User, location_id: int, data: dict) -> dict:
    location = get(db, user, location_id)
    warehouse = db.get(Warehouse, location.warehouse_id)
    try:
        data = _validate(db, warehouse, dict(data), location)
        for key in FIELDS:
            if key in data:
                setattr(location, key, data[key])
        db.flush()
        _check_contents_still_fit(db, location)
        _check_reservations(db, location)
        from app.services import audit_service
        audit_service.log(db, user, "location.update", f"محل {location.code} ویرایش شد",
                          target_type="location", target_id=location.id, target_label=location.code)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return location_detail(db, user, location.id)


def delete_location(db: Session, user: User, location_id: int) -> None:
    """فقط محل بی‌سابقه (بدون زیرمجموعه و بدون هیچ گردشی) حذف می‌شود؛ بقیه غیرفعال می‌شوند."""
    location = get(db, user, location_id)
    if has_children(db, location.id):
        raise ConflictError("این محل زیرمجموعه دارد؛ ابتدا زیرمجموعه‌ها را حذف کنید.")
    from app.models import InboundReceipt, PutawayTask
    used = any(q.first() is not None for q in (
        db.query(StockMovementLine.id).filter(StockMovementLine.location_id == location.id),
        db.query(StockBalance.id).filter(StockBalance.location_id == location.id),
        db.query(PutawayTask.id).filter((PutawayTask.source_location_id == location.id)
                                        | (PutawayTask.suggested_location_id == location.id)
                                        | (PutawayTask.destination_location_id == location.id)),
        db.query(InboundReceipt.id).filter(InboundReceipt.receiving_location_id == location.id),
    ))
    if used:
        raise ConflictError("این محل سابقه گردش کالا دارد و برای حفظ سوابق حذف نمی‌شود؛ آن را غیرفعال کنید.")
    from app.services import audit_service
    audit_service.log(db, user, "location.delete", f"محل {location.code} حذف شد",
                      target_type="location", target_id=location.id, target_label=location.code)
    db.delete(location)
    db.commit()
