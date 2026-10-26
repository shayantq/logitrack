"""
مجوزهای ریز نقش‌ها (فصل ۲۲): پیش‌فرض از app/core/permissions.py + تفاوت‌های هر سازمان در role_permissions.

`ensure(db, user, key)` در سرویس‌ها پیش از عملیات حساس صدا زده می‌شود (بررسی سمت سرور، مستقل از رابط کاربری).
نتیجه در طول یک درخواست در db.info کش می‌شود.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.permissions import LOCKED, PERMISSIONS, ROLE_LABELS, ROLES, catalog, default
from app.models import RolePermission, User
from app.services import audit_service
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError

_CACHE = "permission_overrides"


def _role(user: User) -> str:
    return getattr(user.role, "value", user.role)


def _overrides(db: Session, organization_id: int) -> dict[tuple[str, str], bool]:
    cache = db.info.setdefault(_CACHE, {})
    if organization_id not in cache:
        cache[organization_id] = {(r.role, r.permission): r.allowed for r in db.query(RolePermission).filter(
            RolePermission.organization_id == organization_id).all()}
    return cache[organization_id]


def allowed(db: Session, user: User, key: str) -> bool:
    perm = PERMISSIONS[key]
    role = _role(user)
    if role not in perm.max_roles or user.organization_id is None:
        return False
    if (role, key) in LOCKED:
        return True
    return _overrides(db, user.organization_id).get((role, key), default(role, key))


def ensure(db: Session, user: User, key: str, message: str | None = None) -> None:
    if not allowed(db, user, key):
        raise ForbiddenError(message or f"مجوز «{PERMISSIONS[key].label}» برای نقش شما فعال نیست؛ با ادمین سازمان تماس بگیرید.")


def mine(db: Session, user: User) -> list[str]:
    return [key for key in PERMISSIONS if allowed(db, user, key)]


def matrix(db: Session, user: User) -> dict:
    ensure(db, user, "permissions.manage")
    overrides = _overrides(db, user.organization_id)
    rows = []
    for item in catalog():
        key = item["key"]
        item["roles"] = {role: {
            "allowed": (role, key) in LOCKED or overrides.get((role, key), default(role, key)) if role in item["max_roles"] else False,
            "editable": role in item["max_roles"] and (role, key) not in LOCKED,
            "customized": (role, key) in overrides,
        } for role in ROLES}
        rows.append(item)
    return {"roles": [{"code": r, "label": ROLE_LABELS[r]} for r in ROLES], "permissions": rows}


def update(db: Session, user: User, role: str, key: str, value: bool, reason: str | None) -> dict:
    ensure(db, user, "permissions.manage")
    perm = PERMISSIONS.get(key)
    if perm is None:
        raise NotFoundError("مجوز یافت نشد.")
    if role not in perm.max_roles:
        raise ConflictError(f"«{perm.label}» برای نقش {ROLE_LABELS.get(role, role)} قابل فعال‌سازی نیست.")
    if (role, key) in LOCKED:
        raise ConflictError("مدیریت مجوزها از ادمین سازمان گرفته نمی‌شود.")
    if not (reason or "").strip():
        raise ConflictError("دلیل تغییر مجوز را بنویسید.")
    row = db.query(RolePermission).filter(RolePermission.organization_id == user.organization_id,
                                          RolePermission.role == role, RolePermission.permission == key).first()
    before = row.allowed if row else default(role, key)
    if value == default(role, key):
        if row is not None:
            db.delete(row)
    else:
        if row is None:
            row = RolePermission(organization_id=user.organization_id, role=role, permission=key)
            db.add(row)
        row.allowed, row.updated_by_id = value, user.id
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    audit_service.log(db, user, "permission.update",
                      f"مجوز «{perm.label}» برای {ROLE_LABELS[role]} {'فعال' if value else 'غیرفعال'} شد",
                      target_type="permission", target_label=key, reason=reason.strip(),
                      details={"role": role, "permission": key, "before": before, "after": value})
    db.commit()
    db.info.pop(_CACHE, None)
    return matrix(db, user)


def reset(db: Session, user: User, reason: str | None) -> dict:
    ensure(db, user, "permissions.manage")
    if not (reason or "").strip():
        raise ConflictError("دلیل بازگشت به پیش‌فرض را بنویسید.")
    count = db.query(RolePermission).filter(RolePermission.organization_id == user.organization_id).delete()
    audit_service.log(db, user, "permission.reset", f"همه مجوزها به پیش‌فرض برگشت ({count} تغییر حذف شد)",
                      target_type="permission", reason=reason.strip())
    db.commit()
    db.info.pop(_CACHE, None)
    return matrix(db, user)
