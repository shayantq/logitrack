"""
جستجوی سراسری (Ctrl+K): سفارش، کالا، محموله، انتقال، تیکت، راننده و خودرو در یک ورودی.

ورودی یکسان‌سازی می‌شود (ی/ک عربی، ارقام فارسی و عربی). از هر گروه حداکثر ۵ نتیجه برمی‌گردد و همه
کوئری‌ها زیر فیلتر خودکار سازمان‌اند؛ مدیر انبار محموله و انتقال را فقط برای انبار خودش می‌بیند.
اگر ورودی دقیقاً یک شناسه باشد (کد رهگیری، کد تیکت/محموله/انتقال، بارکد یا SKU، پلاک) همان یک
نتیجه در exact برمی‌گردد تا رابط کاربری مستقیم به رکورد برود.
راننده جستجوی سراسری ندارد (فهرست سفارش‌هایش کوچک و جداست)؛ کارکنان پلتفرم فقط تیکت و سازمان.
"""
from urllib.parse import quote

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.iran import latin_digits, normalize_digits, normalize_persian_text
from app.models import PLATFORM_ROLES, Organization, Product, User, Vehicle
from app.models_fulfillment import Shipment, TransferOrder
from app.services import order_service, ticket_service
from app.services.exceptions import ForbiddenError

LIMIT = 5


def _role(user: User) -> str:
    return getattr(user.role, "value", user.role)


def _hit(id_: int, label: str, sub: str, link: str) -> dict:
    return {"id": id_, "label": label, "sub": sub or "", "link": link}


def _orders(db: Session, user: User, term: str, code: str) -> tuple[list[dict], list[dict]]:
    rows = order_service.list_orders(db, user, q=term, limit=LIMIT) if len(term) >= 2 else []
    hits = [_hit(o.id, o.tracking_code, f"{o.recipient_name or ''} · {o.destination_city}", f"/app/orders?order={o.id}")
            for o in rows]
    return hits, [h for h in hits if h["label"].upper() == code]


def _products(db: Session, term: str, code: str) -> tuple[list[dict], list[dict]]:
    like = f"%{term}%"
    rows = db.query(Product).filter(or_(Product.name.ilike(like), Product.sku.ilike(f"%{code}%"),
                                        Product.barcode.ilike(f"%{code}%"))).order_by(Product.name).limit(LIMIT).all()
    hits = [_hit(p.id, p.name, p.sku, f"/app/stock-card?product={p.id}") for p in rows]
    exact = [h for p, h in zip(rows, hits, strict=False) if code in ((p.sku or "").upper(), (p.barcode or "").upper())]
    return hits, exact


def _shipments(db: Session, user: User, code: str) -> tuple[list[dict], list[dict]]:
    query = db.query(Shipment).filter(Shipment.code.ilike(f"%{code}%"))
    if _role(user) == "warehouse_manager":
        query = query.filter(Shipment.warehouse_id == user.warehouse_id)
    rows = query.order_by(Shipment.id.desc()).limit(LIMIT).all()
    hits = [_hit(s.id, s.code, "محموله", "/app/shipping") for s in rows]
    return hits, [h for h in hits if h["label"].upper() == code]


def _transfers(db: Session, user: User, code: str) -> tuple[list[dict], list[dict]]:
    query = db.query(TransferOrder).filter(TransferOrder.code.ilike(f"%{code}%"))
    if _role(user) == "warehouse_manager":
        query = query.filter(or_(TransferOrder.from_warehouse_id == user.warehouse_id,
                                 TransferOrder.to_warehouse_id == user.warehouse_id))
    rows = query.order_by(TransferOrder.id.desc()).limit(LIMIT).all()
    hits = [_hit(t.id, t.code, "سفارش انتقال", f"/app/transfers?transfer={t.id}") for t in rows]
    return hits, [h for h in hits if h["label"].upper() == code]


def _tickets(db: Session, user: User, term: str, code: str, base: str) -> tuple[list[dict], list[dict]]:
    rows = ticket_service.list_tickets(db, user, q=term)[:LIMIT] if len(term) >= 2 else []
    hits = [_hit(t["id"], t["subject"], t["code"], f"{base}/{t['id']}") for t in rows]
    return hits, [h for h in hits if h["sub"].upper() == code]


def _drivers(db: Session, term: str) -> list[dict]:
    like = f"%{term}%"
    digits = normalize_digits(term)
    conditions = [User.full_name.ilike(like), User.username.ilike(like), User.driver_code.ilike(f"%{digits}%")]
    if digits.isdigit() and len(digits) >= 4:
        conditions.append(User.mobile.like(f"%{digits}%"))
    rows = db.query(User).filter(User.role == "driver", or_(*conditions)).order_by(User.full_name).limit(LIMIT).all()
    return [_hit(u.id, u.full_name or u.username, u.driver_code or "", f"/app/drivers/{u.id}") for u in rows]


def _vehicles(db: Session, term: str) -> tuple[list[dict], list[dict]]:
    key = order_service._plate_key(term)
    if len(key) < 2:
        return [], []
    rows = [v for v in db.query(Vehicle).order_by(Vehicle.id).all() if key in order_service._plate_key(v.license_plate)][:LIMIT]
    hits = [_hit(v.id, v.license_plate or "", v.model or "", f"/app/orders?plate={quote(v.license_plate or '')}") for v in rows]
    exact = [h for v, h in zip(rows, hits, strict=False) if order_service._plate_key(v.license_plate) == key]
    return hits, exact


def _organizations(db: Session, term: str) -> list[dict]:
    like = f"%{term}%"
    rows = db.query(Organization).filter(or_(Organization.name.ilike(like), Organization.slug.ilike(like))) \
        .order_by(Organization.name).limit(LIMIT).all()
    return [_hit(o.id, o.name, o.slug, "/app/platform") for o in rows]


def search(db: Session, user: User, q: str) -> dict:
    term = normalize_persian_text(q.strip())
    code = latin_digits(term).upper()
    role = _role(user)
    groups: list[dict] = []
    exact: list[dict] = []

    def add(type_: str, title: str, result):
        hits, matched = result if isinstance(result, tuple) else (result, [])
        if hits:
            groups.append({"type": type_, "title": title, "hits": hits})
        exact.extend(matched)

    if role in [getattr(r, "value", r) for r in PLATFORM_ROLES]:
        add("ticket", "تیکت‌ها", _tickets(db, user, term, code, "/app/platform/tickets"))
        add("organization", "سازمان‌ها", _organizations(db, term))
    elif role in ("org_admin", "warehouse_manager"):
        add("order", "سفارش‌ها", _orders(db, user, term, code))
        add("product", "کالاها", _products(db, term, code))
        add("shipment", "محموله‌ها", _shipments(db, user, code))
        add("transfer", "انتقال‌ها", _transfers(db, user, code))
        add("ticket", "تیکت‌ها", _tickets(db, user, term, code, "/app/tickets"))
        add("driver", "رانندگان", _drivers(db, term))
        add("vehicle", "خودروها", _vehicles(db, term))
    else:
        raise ForbiddenError("جستجوی سراسری برای این نقش فعال نیست.")
    return {"query": term, "exact": exact[0] if len(exact) == 1 else None, "groups": groups}
