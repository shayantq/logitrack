"""
طرف‌های تجاری (تأمین‌کننده، مشتری حقوقی/عمده، شرکت حمل).

- فقط ادمین سازمان می‌سازد و ویرایش می‌کند؛ مدیر انبار فهرست را (برای رسید کالا) می‌بیند ولی شناسه ملی و
  شماره شبا برایش پوشانده است. راننده دسترسی ندارد.
- کد طرف در سازمان یکتاست (خالی = SUP-001 / CUS-001 / CAR-001)؛ شناسه ملی هم تکراری ثبت نمی‌شود.
- طرفی که در سند انبار یا تأمین کالا استفاده شده حذف نمی‌شود، غیرفعال (بایگانی) می‌شود.
- هر تغییر در گزارش فعالیت و رویدادها ثبت می‌شود.
"""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.wms import PARTNER_ROLES
from app.models import Partner, ProductSupplier, StockDocument, User
from app.services import audit_service
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError

PREFIX = {"supplier": "SUP", "customer": "CUS", "carrier": "CAR", "owner": "OWN"}
SENSITIVE = ("national_id", "iban")


def _role(user: User) -> str:
    return getattr(user.role, "value", user.role)


def _ensure_reader(user: User) -> None:
    if _role(user) not in ("org_admin", "warehouse_manager"):
        raise ForbiddenError("طرف‌های تجاری فقط برای ادمین سازمان و مدیر انبار است.")


def _ensure_admin(user: User) -> None:
    if _role(user) != "org_admin":
        raise ForbiddenError("تعریف و ویرایش طرف‌های تجاری با ادمین سازمان است.")


def _mask(value: str | None) -> str | None:
    return None if not value else "•" * max(0, len(value) - 4) + value[-4:]


def roles(p: Partner) -> list[str]:
    return [r for r in PARTNER_ROLES if getattr(p, f"is_{r}")]


def serialize(db: Session, user: User, p: Partner, counts: tuple[int, int] | None = None) -> dict:
    masked = _role(user) != "org_admin"
    products, documents = counts if counts is not None else (
        db.query(func.count(ProductSupplier.id)).filter(ProductSupplier.partner_id == p.id).scalar() or 0,
        db.query(func.count(StockDocument.id)).filter(StockDocument.partner_id == p.id).scalar() or 0,
    )
    data = {c.key: getattr(p, c.key) for c in Partner.__table__.columns if c.key not in ("organization_id", "created_by_id")}
    if masked:
        data.update({k: _mask(data[k]) for k in SENSITIVE})
    return {**data, "roles": roles(p), "masked": masked, "products_count": products, "documents_count": documents}


def list_partners(db: Session, user: User, *, role: str | None = None, q: str | None = None,
                  include_inactive: bool = False) -> list[dict]:
    _ensure_reader(user)
    query = db.query(Partner)
    if role in PARTNER_ROLES:
        query = query.filter(getattr(Partner, f"is_{role}").is_(True))
    if not include_inactive:
        query = query.filter(Partner.is_active.is_(True))
    if q:
        term = f"%{q.strip()}%"
        query = query.filter(Partner.name.ilike(term) | Partner.code.ilike(term) | Partner.legal_name.ilike(term)
                             | Partner.national_id.like(term) | Partner.mobile.like(term))
    partners = query.order_by(Partner.is_active.desc(), Partner.name).all()
    ids = [p.id for p in partners] or [-1]
    products = dict(db.query(ProductSupplier.partner_id, func.count(ProductSupplier.id))
                    .filter(ProductSupplier.partner_id.in_(ids)).group_by(ProductSupplier.partner_id).all())
    documents = dict(db.query(StockDocument.partner_id, func.count(StockDocument.id))
                     .filter(StockDocument.partner_id.in_(ids)).group_by(StockDocument.partner_id).all())
    return [serialize(db, user, p, (products.get(p.id, 0), documents.get(p.id, 0))) for p in partners]


def _get(db: Session, partner_id: int) -> Partner:
    partner = db.get(Partner, partner_id)
    if partner is None:
        raise NotFoundError("طرف تجاری یافت نشد.")
    return partner


def get_partner(db: Session, user: User, partner_id: int) -> dict:
    _ensure_reader(user)
    return serialize(db, user, _get(db, partner_id))


def _next_code(db: Session, data: dict) -> str:
    prefix = next(PREFIX[r] for r in PARTNER_ROLES if data.get(f"is_{r}"))
    codes = {c for (c,) in db.query(Partner.code).filter(Partner.code.like(f"{prefix}-%")).all()}
    n = len(codes) + 1
    while f"{prefix}-{n:03d}" in codes:
        n += 1
    return f"{prefix}-{n:03d}"


def _check_unique(db: Session, data: dict, exclude_id: int | None) -> None:
    def taken(column, value):
        query = db.query(Partner.id).filter(column == value)
        if exclude_id:
            query = query.filter(Partner.id != exclude_id)
        return query.first() is not None

    if taken(func.upper(Partner.code), data["code"].upper()):
        raise ConflictError(f"کد طرف تجاری «{data['code']}» تکراری است.")
    if data.get("national_id") and taken(Partner.national_id, data["national_id"]):
        raise ConflictError("طرف تجاری دیگری با همین شناسه/کد ملی ثبت شده است.")


def create_partner(db: Session, user: User, data: dict) -> dict:
    _ensure_admin(user)
    data["code"] = data.get("code") or _next_code(db, data)
    _check_unique(db, data, None)
    partner = Partner(**{**data, "email": str(data["email"]) if data.get("email") else None}, created_by_id=user.id)
    db.add(partner)
    db.flush()
    audit_service.log(db, user, "partner.create", f"طرف تجاری «{partner.name}» ({partner.code}) تعریف شد",
                      target_type="partner", target_id=partner.id, target_label=partner.code)
    db.commit()
    return serialize(db, user, partner)


def update_partner(db: Session, user: User, partner_id: int, data: dict) -> dict:
    _ensure_admin(user)
    partner = _get(db, partner_id)
    data["code"] = data.get("code") or partner.code
    _check_unique(db, data, partner.id)
    if not data.get("is_supplier") and partner.is_supplier and \
            db.query(ProductSupplier.id).filter(ProductSupplier.partner_id == partner.id).first():
        raise ConflictError("این طرف تأمین‌کننده کالاهایی است؛ ابتدا از فهرست تأمین‌کنندگان آن کالاها حذفش کنید.")
    changed = []
    for key, value in data.items():
        value = str(value) if key == "email" and value else value
        if getattr(partner, key) != value:
            changed.append(key)
            setattr(partner, key, value)
    if changed:
        # مقدار فیلدهای حساس در گزارش فعالیت ثبت نمی‌شود، فقط نامشان
        audit_service.log(db, user, "partner.update", f"طرف تجاری «{partner.name}» ویرایش شد", target_type="partner",
                          target_id=partner.id, target_label=partner.code, details={"fields": changed})
    db.commit()
    return serialize(db, user, partner)


def set_active(db: Session, user: User, partner_id: int, active: bool) -> dict:
    _ensure_admin(user)
    partner = _get(db, partner_id)
    if partner.is_active != active:
        partner.is_active = active
        audit_service.log(db, user, "partner.activate" if active else "partner.archive",
                          f"طرف تجاری «{partner.name}» {'فعال' if active else 'بایگانی'} شد", target_type="partner",
                          target_id=partner.id, target_label=partner.code)
        db.commit()
    return serialize(db, user, partner)


def delete_partner(db: Session, user: User, partner_id: int) -> None:
    _ensure_admin(user)
    partner = _get(db, partner_id)
    if db.query(StockDocument.id).filter(StockDocument.partner_id == partner.id).first() or \
            db.query(ProductSupplier.id).filter(ProductSupplier.partner_id == partner.id).first():
        raise ConflictError("این طرف تجاری در اسناد انبار یا تأمین کالاها استفاده شده و برای حفظ سوابق حذف نمی‌شود؛ بایگانی کنید.")
    audit_service.log(db, user, "partner.delete", f"طرف تجاری «{partner.name}» ({partner.code}) حذف شد",
                      target_type="partner", target_id=partner.id, target_label=partner.code)
    db.delete(partner)
    db.commit()
