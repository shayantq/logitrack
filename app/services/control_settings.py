"""
تنظیمات کنترل موجودی سازمان (فصل‌های ۱۶ و ۱۷) — کنار سیاست نقطه سفارش در organizations.inventory_policy:
  • valuation_method — روش ارزش‌گذاری مالی (fifo | weighted_average | standard)، مستقل از قاعده برداشت فیزیکی FEFO
  • count_approval_value — سقف ارزش مغایرت (ریال) که زیر آن تأیید انبارگردانی با مجوز «زیر سقف» کافی است
  • slow_days / dead_days — بی‌گردشی برای «کم‌گردش» و «راکد»
  • expiry_warning_days — هشدار نزدیک به انقضا
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Organization, User
from app.services import audit_service, permission_service
from app.services.exceptions import ConflictError

VALUATION_METHODS = {"fifo": "اولین صادره از اولین وارده (FIFO)", "weighted_average": "میانگین موزون متحرک",
                     "standard": "بهای استاندارد (آخرین بهای تمام‌شده)"}
DEFAULTS = {"valuation_method": "weighted_average", "count_approval_value": 5_000_000, "slow_days": 60, "dead_days": 180,
            "expiry_warning_days": 30}
LIMITS = {"count_approval_value": (0, 100_000_000_000), "slow_days": (7, 720), "dead_days": (14, 1460),
          "expiry_warning_days": (1, 365)}
LABELS = {"valuation_method": "روش ارزش‌گذاری", "count_approval_value": "سقف تأیید انبارگردانی",
          "slow_days": "کم‌گردش پس از (روز)", "dead_days": "راکد پس از (روز)", "expiry_warning_days": "هشدار انقضا (روز)"}


def of(db: Session, organization_id: int) -> dict:
    org = db.get(Organization, organization_id)
    stored = (org.inventory_policy if org else None) or {}
    return {key: stored.get(key, default) for key, default in DEFAULTS.items()}


def get(db: Session, user: User) -> dict:
    permission_service.ensure(db, user, "analytics.view")
    data = of(db, user.organization_id)
    data["valuation_methods"] = [{"code": k, "label": v} for k, v in VALUATION_METHODS.items()]
    return data


def update(db: Session, user: User, data: dict, reason: str | None = None) -> dict:
    permission_service.ensure(db, user, "valuation.manage")
    org = db.get(Organization, user.organization_id)
    current = of(db, user.organization_id)
    changed = {}
    for key, value in data.items():
        if key not in DEFAULTS or value is None:
            continue
        if key == "valuation_method":
            if value not in VALUATION_METHODS:
                raise ConflictError("روش ارزش‌گذاری معتبر نیست.")
        else:
            low, high = LIMITS[key]
            if not low <= value <= high:
                raise ConflictError(f"مقدار «{LABELS[key]}» خارج از محدوده مجاز است.")
            value = int(value)
        if current[key] != value:
            changed[key] = {"before": current[key], "after": value}
            current[key] = value
    if current["slow_days"] >= current["dead_days"]:
        raise ConflictError("مدت «راکد» باید بیشتر از «کم‌گردش» باشد.")
    if changed:
        if "valuation_method" in changed and not (reason or "").strip():
            raise ConflictError("تغییر روش ارزش‌گذاری اثر مالی دارد؛ دلیل آن را بنویسید.")
        org.inventory_policy = {**(org.inventory_policy or {}), **current}
        audit_service.log(db, user, "valuation.method", "تنظیمات کنترل و ارزش‌گذاری موجودی تغییر کرد",
                          target_type="organization", target_id=org.id, reason=(reason or "").strip() or None, details=changed)
        db.commit()
    return get(db, user)
