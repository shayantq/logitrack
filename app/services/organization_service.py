"""
لایه سرویس سازمان‌ها (فقط برای کارکنان پلتفرم پسینه)
ساخت سازمان جدید همراه با اولین ادمینش، فعال/غیرفعال کردن، و آمار هر
سازمان. این توابع روی Session بدون «سازمان جاری» اجرا می‌شوند و همه
سازمان‌ها را می‌بینند.
"""
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.security import bcrypt_context
from app.core.tenancy import SKIP_TENANT_FILTER
from app.models import (
    Organization, User, RoleEnum, Warehouse, Product, Vehicle, Order, ACTIVE_ORDER_STATUSES,
)
from app.core import storage
from app.schemas.organization import OrganizationCreate, OrganizationUpdate, OrganizationProfileUpdate
from app.services.exceptions import NotFoundError, ConflictError


def _count_by_org(db: Session, column, *criteria) -> dict[int, int]:
    query = db.query(column, func.count()).execution_options(**SKIP_TENANT_FILTER)
    if criteria:
        query = query.filter(*criteria)
    return dict(query.group_by(column).all())


def _with_stats(db: Session, organizations: list[Organization]) -> list[dict]:
    users = _count_by_org(db, User.organization_id)
    drivers = _count_by_org(db, User.organization_id, User.role == RoleEnum.DRIVER)
    warehouses = _count_by_org(db, Warehouse.organization_id)
    products = _count_by_org(db, Product.organization_id)
    vehicles = _count_by_org(db, Vehicle.organization_id)
    orders = _count_by_org(db, Order.organization_id)
    active_orders = _count_by_org(db, Order.organization_id, Order.status.in_(ACTIVE_ORDER_STATUSES))

    return [
        {
            "id": org.id, "name": org.name, "slug": org.slug, "is_active": org.is_active,
            "created_at": org.created_at,
            "users_count": users.get(org.id, 0), "drivers_count": drivers.get(org.id, 0),
            "warehouses_count": warehouses.get(org.id, 0), "products_count": products.get(org.id, 0),
            "vehicles_count": vehicles.get(org.id, 0), "orders_count": orders.get(org.id, 0),
            "active_orders_count": active_orders.get(org.id, 0),
        }
        for org in organizations
    ]


def list_organizations(db: Session) -> list[dict]:
    return _with_stats(db, db.query(Organization).order_by(Organization.id).all())


def get_organization(db: Session, organization_id: int) -> dict:
    org = db.get(Organization, organization_id)
    if org is None:
        raise NotFoundError("سازمان مورد نظر یافت نشد.")
    return _with_stats(db, [org])[0]


def create_organization(db: Session, data: OrganizationCreate) -> dict:
    if db.query(Organization).filter(Organization.slug == data.slug).first():
        raise ConflictError("سازمانی با این شناسه (slug) قبلاً ثبت شده است.")

    existing_user = db.query(User).filter(or_(
        User.username == data.admin.username,
        User.email == data.admin.email,
    )).execution_options(**SKIP_TENANT_FILTER).first()
    if existing_user:
        raise ConflictError("کاربری با این نام کاربری یا ایمیل قبلاً ثبت شده است.")

    try:
        org = Organization(name=data.name, slug=data.slug, is_active=True)
        db.add(org)
        db.flush()

        db.add(User(
            organization_id=org.id,
            username=data.admin.username,
            email=data.admin.email,
            full_name=data.admin.full_name,
            role=RoleEnum.ORG_ADMIN,
            hashed_password=bcrypt_context.hash(data.admin.password),
        ))
        db.commit()
        db.refresh(org)
        return _with_stats(db, [org])[0]
    except Exception:
        db.rollback()
        raise


def update_organization(db: Session, organization_id: int, data: OrganizationUpdate) -> dict:
    org = db.get(Organization, organization_id)
    if org is None:
        raise NotFoundError("سازمان مورد نظر یافت نشد.")
    if data.name is not None:
        org.name = data.name
    if data.is_active is not None:
        org.is_active = data.is_active
    db.commit()
    db.refresh(org)
    return _with_stats(db, [org])[0]


def list_organization_users(db: Session, organization_id: int) -> list[User]:
    if db.get(Organization, organization_id) is None:
        raise NotFoundError("سازمان مورد نظر یافت نشد.")
    return db.query(User).filter(User.organization_id == organization_id).order_by(User.id).all()


# ---------------------------------------------------------------------------
# پروفایل و لوگو سازمان
# ---------------------------------------------------------------------------
MAX_LOGO_BYTES = 2 * 1024 * 1024


def _get_org(db: Session, organization_id: int) -> Organization:
    org = db.get(Organization, organization_id)
    if org is None:
        raise NotFoundError("سازمان مورد نظر یافت نشد.")
    return org


def get_profile(db: Session, organization_id: int) -> dict:
    org = _get_org(db, organization_id)
    data = {column.name: getattr(org, column.name) for column in Organization.__table__.columns}
    data["has_logo"] = bool(org.logo_path and storage.path_of(org.logo_path))
    return data


def update_profile(db: Session, organization_id: int, data: OrganizationProfileUpdate) -> dict:
    org = _get_org(db, organization_id)
    changes = data.model_dump(exclude_unset=True)
    if "national_id" in changes and changes["national_id"]:
        taken = db.query(Organization).filter(
            Organization.national_id == changes["national_id"], Organization.id != org.id
        ).first()
        if taken:
            raise ConflictError("سازمان دیگری با این شناسه ملی ثبت شده است.")
    for field, value in changes.items():
        if field == "name" and not value:
            continue  # نام سازمان خالی نمی‌شود
        setattr(org, field, str(value) if field == "contact_email" and value is not None else value)
    db.commit()
    return get_profile(db, organization_id)


def set_logo(db: Session, organization_id: int, data: bytes) -> dict:
    org = _get_org(db, organization_id)
    if not data:
        raise ConflictError("فایل لوگو خالی است.")
    if len(data) > MAX_LOGO_BYTES:
        raise ConflictError("حجم لوگو نباید بیشتر از ۲ مگابایت باشد.")
    try:
        ext = storage.detect_image(data)
    except storage.InvalidFileError as e:
        raise ConflictError(str(e))

    new_path = f"organizations/{org.id}/logo.{ext}"
    storage.save(new_path, data)
    if org.logo_path and org.logo_path != new_path:
        storage.delete(org.logo_path)
    org.logo_path = new_path
    db.commit()
    return get_profile(db, organization_id)


def delete_logo(db: Session, organization_id: int) -> None:
    org = _get_org(db, organization_id)
    storage.delete(org.logo_path)
    org.logo_path = None
    db.commit()


def logo_file(db: Session, organization_id: int):
    """(مسیر فایل، media type) لوگو یا NotFoundError."""
    org = _get_org(db, organization_id)
    path = storage.path_of(org.logo_path) if org.logo_path else None
    if path is None:
        raise NotFoundError("این سازمان لوگو ندارد.")
    ext = path.suffix.lstrip(".")
    return path, storage.MEDIA_TYPES.get(ext, "application/octet-stream")
