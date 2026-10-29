"""
نماهای ذخیره‌شده فهرست‌ها: همان فیلترهای آدرس صفحه با یک نام.

هر کاربر نماهای خودش را می‌بیند و حذف می‌کند، به‌علاوه نماهایی که همکارانش با نقش او به اشتراک گذاشته‌اند.
فیلترها فقط کلید/مقدار ساده‌اند (رشته، عدد، بولی) تا مستقیم به آدرس صفحه برگردند.
"""
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.models import User
from app.models_productivity import SavedView
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError

MAX_PER_PAGE = 30
STAFF = ("org_admin", "warehouse_manager")


def _role(user: User) -> str:
    return getattr(user.role, "value", user.role)


def _ensure_staff(user: User) -> None:
    if _role(user) not in STAFF:
        raise ForbiddenError("نماهای ذخیره‌شده فقط برای ادمین سازمان و مدیر انبار است.")


def _clean(filters: dict) -> dict:
    out = {}
    for key, value in (filters or {}).items():
        if not isinstance(key, str) or len(key) > 32 or not key.replace("_", "").isalnum():
            raise ConflictError("نام فیلتر نامعتبر است.")
        if value is None or value == "":
            continue
        if not isinstance(value, (str, int, float, bool)) or (isinstance(value, str) and len(value) > 120):
            raise ConflictError("مقدار فیلتر نامعتبر است.")
        out[key] = value
    if len(out) > 20:
        raise ConflictError("تعداد فیلترها زیاد است.")
    return out


def serialize(view: SavedView, user: User) -> dict:
    owner = view.owner
    return {
        "id": view.id, "page_key": view.page_key, "name": view.name, "filters": view.filters or {},
        "shared_role": view.shared_role, "owner_id": view.owner_id,
        "owner_name": (owner.full_name or owner.username) if owner else None,
        "mine": view.owner_id == user.id, "created_at": view.created_at,
    }


def list_views(db: Session, user: User, page: str | None = None) -> list[dict]:
    _ensure_staff(user)
    query = db.query(SavedView).options(joinedload(SavedView.owner)).filter(
        or_(SavedView.owner_id == user.id, SavedView.shared_role == _role(user)))
    if page:
        query = query.filter(SavedView.page_key == page)
    views = query.order_by(SavedView.name, SavedView.id).all()
    return [serialize(v, user) for v in views]


def create_view(db: Session, user: User, data) -> dict:
    _ensure_staff(user)
    if db.query(SavedView).filter(SavedView.owner_id == user.id, SavedView.page_key == data.page_key).count() >= MAX_PER_PAGE:
        raise ConflictError(f"برای هر صفحه حداکثر {MAX_PER_PAGE} نما می‌توانید ذخیره کنید.")
    if db.query(SavedView).filter(SavedView.owner_id == user.id, SavedView.page_key == data.page_key,
                                  SavedView.name == data.name).first():
        raise ConflictError("نمایی با همین نام در این صفحه دارید.")
    view = SavedView(organization_id=user.organization_id, owner_id=user.id, page_key=data.page_key, name=data.name,
                     filters=_clean(data.filters), shared_role=data.shared_role)
    db.add(view)
    db.commit()
    db.refresh(view)
    return serialize(view, user)


def delete_view(db: Session, user: User, view_id: int) -> None:
    _ensure_staff(user)
    view = db.get(SavedView, view_id)
    if view is None:
        raise NotFoundError("نما یافت نشد.")
    if view.owner_id != user.id:
        raise ForbiddenError("فقط سازنده نما می‌تواند آن را حذف کند.")
    db.delete(view)
    db.commit()
