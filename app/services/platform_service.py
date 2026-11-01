"""
عملیات پلتفرم (docs/operations-guide.md، مرحله ۴): تعلیق مرحله‌ای، پلن و سقف‌ها، دسترسی موقت پشتیبانی، پرچم قابلیت،
خروجی داده سازمان و چرخه خروج سازمان.

اصل‌ها:
  • تعلیق کار تازه را می‌بندد ولی کار در جریان (سفرها و برگشت‌ها) تا آخر می‌رود.
  • سقف پلن فقط جلوی کار تازه را می‌گیرد و هیچ عملیات بازی را نمی‌شکند؛ کاهش پلن مهلت دارد.
  • عملیات حساس شناسه سازمان را به‌صورت تایپی می‌خواهد و با دلیل در گزارش فعالیت می‌ماند.
  • خروج سازمان حذف فیزیکی نیست: اسناد انبار و گزارش فعالیت عمداً غیرقابل‌حذف‌اند، پس داده شخصی و فایل‌ها پاک می‌شوند
    و سوابق انبار می‌ماند.
"""
import csv
import io
import re
import shutil
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core import storage
from app.database import Base
from app.models import AuthSession, Customer, Order, Organization, Ticket, TicketMessage, User, Warehouse
from app.models_productivity import FeatureFlag, OutboundMessage, PlanChange, SupportAccessGrant, TenantExport
from app.services import audit_service
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError

# همان سقف‌های frontend/src/pages/public/content/pricing.ts
PLANS = {
    "trial": {"label": "آزمایشی", "warehouses": 1, "drivers": 3, "orders": 100, "users": 2, "modules": ["reorder", "stocktake", "branding", "phone"]},
    "basic": {"label": "پایه", "warehouses": 1, "drivers": 5, "orders": 500, "users": 3, "modules": []},
    "pro": {"label": "حرفه‌ای", "warehouses": 3, "drivers": 25, "orders": 3000, "users": 10, "modules": ["reorder", "stocktake", "branding", "phone"]},
    "enterprise": {"label": "سازمانی", "warehouses": 10, "drivers": 100, "orders": 20000, "users": 50, "modules": ["reorder", "stocktake", "branding", "phone"]},
}
RESOURCE_LABELS = {"warehouses": "انبار", "drivers": "راننده", "orders": "سفارش این ماه", "users": "کاربر پنل"}
DOWNGRADE_GRACE = timedelta(days=14)
NEAR_LIMIT = 0.8
SUPPORT_MAX_MINUTES = 240
DEPROVISION_GRACE = timedelta(days=30)
EXPORT_VALID = timedelta(days=30)
# ستون‌هایی که هرگز از سازمان خارج نمی‌شوند
EXPORT_SECRET_COLUMNS = {"hashed_password", "totp_secret", "totp_last_step", "token_version", "access_token", "rating_token", "request_hash", "idempotency_key"}
# جدول‌های سند و گزارش فعالیت با trigger غیرقابل‌تغییرند و در پاک‌سازی دست نمی‌خورند
IMMUTABLE_TABLES = {"stock_movements", "stock_movement_lines", "domain_events", "stock_documents", "audit_logs"}
PII_COLUMNS = {
    "recipient_name", "recipient_mobile", "requester_name", "requester_mobile", "destination_address", "destination_postal_code", "first_name", "last_name",
    "national_code", "birth_date", "mobile", "address", "postal_code", "note", "exception_note", "body", "photo_path", "attachment_path", "decision_note", "response_note",
    "resolution", "email",
}
FEATURES = {"customer_requests": "درخواست مشتری از صفحه رهگیری"}
# کار در جریان که در تعلیق هم باید تمام شود (سفرها، برگشت و تعیین تکلیف)
SUSPENDED_ALLOWED = re.compile(
    r"^/(auth/.+|handovers/\d+/respond|notifications(/.*)?|orders/\d+/(status|contacts|mission|resolve-failure|handovers|attempts/\d+/photo|driver-returns/\d+/receive|checkpoints(/.*)?)|exceptions/report|users/me(/.*)?)$")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _org(db: Session, organization_id: int) -> Organization:
    org = db.get(Organization, organization_id)
    if org is None:
        raise NotFoundError("سازمان مورد نظر یافت نشد.")
    return org


def _confirm(org: Organization, confirm_slug: str | None) -> None:
    if (confirm_slug or "").strip() != org.slug:
        raise ConflictError(f"برای تأیید، شناسه سازمان ({org.slug}) را دقیق بنویسید.")


def _audit(db: Session, user: User, action: str, summary: str, org: Organization, reason: str | None = None) -> None:
    audit_service.log(db, user, action, summary[:500], target_type="organization", target_id=org.id, target_label=org.name, organization_id=org.id, reason=reason)


# ---------------------------------------------------------------------------
# تعلیق
# ---------------------------------------------------------------------------
def blocked_by_suspension(org: Organization | None, method: str, path: str) -> bool:
    if org is None or org.suspended_at is None or method in ("GET", "HEAD", "OPTIONS"):
        return False
    return not SUSPENDED_ALLOWED.match(path.rstrip("/"))


def suspend(db: Session, user: User, organization_id: int, reason: str, confirm_slug: str) -> Organization:
    org = _org(db, organization_id)
    _confirm(org, confirm_slug)
    if org.suspended_at is not None:
        raise ConflictError("این سازمان از قبل تعلیق است.")
    org.suspended_at, org.suspension_reason = _now(), reason
    _audit(db, user, "platform.org_suspend", f"سازمان «{org.name}» تعلیق شد", org, reason)
    db.commit()
    return org


def resume(db: Session, user: User, organization_id: int, reason: str) -> Organization:
    org = _org(db, organization_id)
    if org.suspended_at is None:
        raise ConflictError("این سازمان تعلیق نیست.")
    org.suspended_at, org.suspension_reason = None, None
    _audit(db, user, "platform.org_resume", f"تعلیق سازمان «{org.name}» برداشته شد", org, reason)
    db.commit()
    return org


# ---------------------------------------------------------------------------
# پلن و سقف
# ---------------------------------------------------------------------------
def plan_of(org: Organization | None) -> dict:
    return PLANS.get(org.plan_id if org else "enterprise", PLANS["enterprise"])


def modules_of(org: Organization | None) -> list[str]:
    return plan_of(org)["modules"]


def _month_start() -> datetime:
    today = date.today()
    return datetime(today.year, today.month, 1)


def _usage(db: Session, organization_id: int) -> dict[str, int]:
    users = db.query(User.role).filter(User.organization_id == organization_id, User.is_active.is_not(False)).execution_options(skip_tenant_filter=True).all()
    return {
        "warehouses": db.query(Warehouse).filter(Warehouse.organization_id == organization_id, Warehouse.is_active.is_not(False)).execution_options(skip_tenant_filter=True).count(),
        "drivers": sum(1 for (role,) in users if getattr(role, "value", role) == "driver"),
        "users": sum(1 for (role,) in users if getattr(role, "value", role) != "driver"),
        "orders": db.query(Order).filter(Order.organization_id == organization_id, Order.created_at >= _month_start()).execution_options(skip_tenant_filter=True).count(),
    }


def ensure_capacity(db: Session, organization_id: int | None, resource: str) -> None:
    """فقط کار تازه را می‌بندد. در مهلت پس از کاهش پلن چیزی بسته نمی‌شود."""
    if organization_id is None:
        return
    org = db.get(Organization, organization_id)
    if org is None or (org.plan_grace_until is not None and org.plan_grace_until > _now()):
        return
    plan = plan_of(org)
    used = _usage(db, organization_id)[resource]
    if used >= plan[resource]:
        raise ConflictError(f"سقف {RESOURCE_LABELS[resource]} پلن «{plan['label']}» ({plan[resource]}) پر شده است؛ برای ادامه پلن را ارتقا دهید. کارهای در جریان ادامه دارند.")


def plan_summary(db: Session, organization_id: int) -> dict:
    org = _org(db, organization_id)
    plan = plan_of(org)
    used = _usage(db, organization_id)
    return {
        "plan_id": org.plan_id, "label": plan["label"], "version": org.plan_version, "grace_until": org.plan_grace_until, "modules": plan["modules"],
        "resources": [{"key": key, "label": label, "used": used[key], "limit": plan[key], "near_limit": used[key] >= plan[key] * NEAR_LIMIT}
                      for key, label in RESOURCE_LABELS.items()],
    }


def change_plan(db: Session, user: User, organization_id: int, plan_id: str, reason: str) -> dict:
    org = _org(db, organization_id)
    if plan_id not in PLANS:
        raise ConflictError("این پلن معتبر نیست.")
    if plan_id == org.plan_id:
        raise ConflictError("سازمان همین الان روی این پلن است.")
    previous = plan_of(org)
    target = PLANS[plan_id]
    downgrade = any(target[key] < previous[key] for key in RESOURCE_LABELS)
    org.plan_grace_until = _now() + DOWNGRADE_GRACE if downgrade else None
    org.plan_version = (org.plan_version or 1) + 1
    db.add(PlanChange(organization_id=org.id, from_plan=org.plan_id, to_plan=plan_id, version=org.plan_version, limits={k: target[k] for k in RESOURCE_LABELS},
                      modules=target["modules"], reason=reason, changed_by_id=user.id, created_at=_now()))
    org.plan_id = plan_id
    _audit(db, user, "platform.plan_change", f"پلن سازمان «{org.name}» به «{target['label']}» تغییر کرد", org, reason)
    db.commit()
    return plan_summary(db, org.id)


# ---------------------------------------------------------------------------
# دسترسی موقت پشتیبانی
# ---------------------------------------------------------------------------
def _grant_out(db: Session, row: SupportAccessGrant) -> dict:
    user = db.get(User, row.user_id)
    return {"id": row.id, "organization_id": row.organization_id, "user_id": row.user_id, "user_name": (user.full_name or user.username) if user else None, "reason": row.reason,
            "expires_at": row.expires_at, "revoked_at": row.revoked_at, "created_at": row.created_at, "active": row.revoked_at is None and row.expires_at > _now()}


def grant_access(db: Session, user: User, organization_id: int, target_user_id: int, reason: str, minutes: int) -> dict:
    org = _org(db, organization_id)
    target = db.get(User, target_user_id)
    if target is None or target.organization_id is not None:
        raise ConflictError("دسترسی فقط به کارکنان پلتفرم داده می‌شود.")
    if not 1 <= minutes <= SUPPORT_MAX_MINUTES:
        raise ConflictError(f"مدت دسترسی باید بین ۱ تا {SUPPORT_MAX_MINUTES} دقیقه باشد.")
    row = SupportAccessGrant(organization_id=org.id, user_id=target.id, reason=reason, granted_by_id=user.id, created_at=_now(), expires_at=_now() + timedelta(minutes=minutes))
    db.add(row)
    _audit(db, user, "platform.support_grant", f"دسترسی موقت پشتیبانی به سازمان «{org.name}» برای {minutes} دقیقه", org, reason)
    db.commit()
    return _grant_out(db, row)


def revoke_access(db: Session, user: User, grant_id: int) -> dict:
    row = db.get(SupportAccessGrant, grant_id)
    if row is None:
        raise NotFoundError("این دسترسی یافت نشد.")
    if row.revoked_at is not None:
        raise ConflictError("این دسترسی قبلاً لغو شده است.")
    row.revoked_at, row.revoked_by_id = _now(), user.id
    _audit(db, user, "platform.support_revoke", "دسترسی موقت پشتیبانی لغو شد", _org(db, row.organization_id))
    db.commit()
    return _grant_out(db, row)


def list_grants(db: Session, organization_id: int) -> list[dict]:
    rows = db.query(SupportAccessGrant).filter(SupportAccessGrant.organization_id == organization_id).order_by(SupportAccessGrant.id.desc()).limit(50).all()
    return [_grant_out(db, r) for r in rows]


def support_view(db: Session, user: User, organization_id: int) -> dict:
    """نمای فقط‌خواندنی با دسترسی معتبر. هر مشاهده در گزارش فعالیت همان سازمان می‌ماند و داده تماس مشتری برنمی‌گردد."""
    org = _org(db, organization_id)
    grant = db.query(SupportAccessGrant).filter(SupportAccessGrant.organization_id == org.id, SupportAccessGrant.user_id == user.id,
                                                SupportAccessGrant.revoked_at.is_(None), SupportAccessGrant.expires_at > _now()).first()
    if grant is None:
        raise ForbiddenError("دسترسی موقت معتبری برای این سازمان ندارید.")
    rows = db.query(Order).filter(Order.organization_id == org.id).execution_options(skip_tenant_filter=True).order_by(Order.id.desc()).limit(100).all()
    _audit(db, user, "platform.support_view", f"مشاهده نمای پشتیبانی سازمان «{org.name}»", org, grant.reason)
    db.commit()
    return {"organization_id": org.id, "expires_at": grant.expires_at, "orders": [
        {"id": o.id, "tracking_code": o.tracking_code, "status": o.status, "stock_state": o.stock_state, "destination_city": o.destination_city, "created_at": o.created_at} for o in rows]}


# ---------------------------------------------------------------------------
# پرچم قابلیت
# ---------------------------------------------------------------------------
def feature_enabled(db: Session, key: str, organization_id: int | None) -> bool:
    """بدون ردیف = روشن. kill همیشه خاموش می‌کند؛ allowlist خالی یعنی برای همه."""
    row = db.query(FeatureFlag).filter(FeatureFlag.key == key).first()
    if row is None:
        return True
    if row.kill_switch or not row.enabled:
        return False
    return not row.allowlist or organization_id in row.allowlist


def _flag_out(key: str, row: FeatureFlag | None) -> dict:
    return {"key": key, "label": FEATURES[key], "enabled": row.enabled if row else True, "kill_switch": row.kill_switch if row else False, "allowlist": (row.allowlist or []) if row else []}


def list_flags(db: Session) -> list[dict]:
    rows = {r.key: r for r in db.query(FeatureFlag).all()}
    return [_flag_out(key, rows.get(key)) for key in FEATURES]


def set_flag(db: Session, user: User, key: str, data) -> dict:
    if key not in FEATURES:
        raise NotFoundError("این قابلیت شناخته نشد.")
    row = db.query(FeatureFlag).filter(FeatureFlag.key == key).first()
    if row is None:
        row = FeatureFlag(key=key)
        db.add(row)
    row.enabled, row.kill_switch, row.allowlist, row.updated_at, row.updated_by_id = data.enabled, data.kill_switch, data.allowlist, _now(), user.id
    audit_service.log(db, user, "platform.feature_flag", f"پرچم {key}: روشن={data.enabled}، توقف اضطراری={data.kill_switch}", target_type="feature_flag", target_label=key, reason=data.reason)
    db.commit()
    return _flag_out(key, row)


# ---------------------------------------------------------------------------
# خروجی داده سازمان
# ---------------------------------------------------------------------------
def _export_out(row: TenantExport) -> dict:
    return {"id": row.id, "organization_id": row.organization_id, "status": row.status, "created_at": row.created_at, "finished_at": row.finished_at, "error": row.error}


def request_export(db: Session, user: User, organization_id: int, reason: str, enqueue) -> dict:
    org = _org(db, organization_id)
    row = TenantExport(organization_id=org.id, status="pending", requested_by_id=user.id, reason=reason, created_at=_now())
    db.add(row)
    _audit(db, user, "platform.org_export", f"خروجی داده سازمان «{org.name}»", org, reason)
    db.commit()
    enqueue(row.id)
    return _export_out(row)


def list_exports(db: Session, organization_id: int) -> list[dict]:
    rows = db.query(TenantExport).filter(TenantExport.organization_id == organization_id).order_by(TenantExport.id.desc()).limit(20).all()
    return [_export_out(r) for r in rows]


def build_export(db: Session, export_id: int) -> dict:
    """هر جدول سازمانی یک CSV. ستون‌های رمز و توکن هرگز نمی‌آیند. فیلتر سازمان صریح است چون کار با Core انجام می‌شود."""
    row = db.get(TenantExport, export_id)
    if row is None:
        raise NotFoundError("این خروجی یافت نشد.")
    org_id = row.organization_id
    buffer = io.BytesIO()
    try:
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for table in Base.metadata.sorted_tables:
                if "organization_id" not in table.c:
                    continue
                columns = [c for c in table.c if c.name not in EXPORT_SECRET_COLUMNS]
                rows = db.execute(select(*columns).where(table.c.organization_id == org_id)).all()
                if not rows:
                    continue
                out = io.StringIO()
                writer = csv.writer(out)
                writer.writerow([c.name for c in columns])
                writer.writerows(rows)
                archive.writestr(f"{table.name}.csv", "﻿" + out.getvalue())
        row.path = storage.save(f"exports/{org_id}/{uuid.uuid4().hex}.zip", buffer.getvalue())
        row.status, row.finished_at = "done", _now()
    except Exception as error:
        db.rollback()
        row = db.get(TenantExport, export_id)
        row.status, row.error, row.finished_at = "failed", f"{type(error).__name__}"[:200], _now()
        db.commit()
        raise
    db.commit()
    return _export_out(row)


def export_file(db: Session, user: User, organization_id: int, export_id: int):
    row = db.query(TenantExport).filter(TenantExport.id == export_id, TenantExport.organization_id == organization_id).first()
    if row is None or row.status != "done" or not row.path:
        raise NotFoundError("این خروجی آماده نیست.")
    path = storage.path_of(row.path)
    if path is None:
        raise NotFoundError("فایل این خروجی دیگر موجود نیست.")
    _audit(db, user, "platform.org_export_download", "دریافت فایل خروجی سازمان", _org(db, organization_id))
    db.commit()
    return path


# ---------------------------------------------------------------------------
# چرخه خروج سازمان
# ---------------------------------------------------------------------------
def request_deprovision(db: Session, user: User, organization_id: int, reason: str, confirm_slug: str) -> dict:
    """سازمان همان لحظه بسته می‌شود و پس از مهلت داده شخصی پاک می‌شود. بدون خروجی تازه شروع نمی‌شود."""
    org = _org(db, organization_id)
    _confirm(org, confirm_slug)
    if org.deprovisioned_at is not None or org.deprovision_requested_at is not None:
        raise ConflictError("خروج این سازمان از قبل ثبت شده است.")
    recent = db.query(TenantExport.id).filter(TenantExport.organization_id == org.id, TenantExport.status == "done", TenantExport.finished_at >= _now() - EXPORT_VALID).first()
    if recent is None:
        raise ConflictError("پیش از خروج، یک خروجی کامل تازه از داده سازمان بگیرید.")
    org.deprovision_requested_at, org.is_active = _now(), False
    _audit(db, user, "platform.org_deprovision", f"خروج سازمان «{org.name}» ثبت شد", org, reason)
    db.commit()
    return deprovision_status(org)


def cancel_deprovision(db: Session, user: User, organization_id: int, reason: str) -> dict:
    org = _org(db, organization_id)
    if org.deprovision_requested_at is None or org.deprovisioned_at is not None:
        raise ConflictError("خروج فعالی برای این سازمان نیست یا پاک‌سازی انجام شده است.")
    org.deprovision_requested_at, org.is_active = None, True
    _audit(db, user, "platform.org_deprovision_cancel", f"خروج سازمان «{org.name}» لغو شد", org, reason)
    db.commit()
    return deprovision_status(org)


def deprovision_status(org: Organization) -> dict:
    requested = org.deprovision_requested_at
    return {"requested_at": requested, "erase_after": requested + DEPROVISION_GRACE if requested else None, "erased_at": org.deprovisioned_at}


def erase_due(db: Session, now: datetime | None = None) -> int:
    now = now or _now()
    due = db.query(Organization).filter(Organization.deprovision_requested_at.is_not(None), Organization.deprovision_requested_at <= now - DEPROVISION_GRACE,
                                        Organization.deprovisioned_at.is_(None)).all()
    for org in due:
        erase_organization(db, org.id)
    return len(due)


def erase_organization(db: Session, organization_id: int) -> None:
    """داده شخصی و فایل‌ها پاک می‌شود؛ اسناد انبار و گزارش فعالیت که عمداً غیرقابل‌تغییرند می‌مانند. اجرای دوباره بی‌اثر است."""
    org = _org(db, organization_id)
    db.query(OutboundMessage).filter(OutboundMessage.organization_id == organization_id).delete(synchronize_session=False)
    users = db.query(User).filter(User.organization_id == organization_id).execution_options(skip_tenant_filter=True).all()
    user_ids = [u.id for u in users]
    if user_ids:
        db.query(AuthSession).filter(AuthSession.user_id.in_(user_ids)).delete(synchronize_session=False)
    for user in users:
        user.username, user.email, user.full_name, user.is_active = f"deleted-{user.id}", None, None, False
        user.hashed_password, user.totp_secret, user.totp_enabled_at = "!", None, None
        user.token_version = (user.token_version or 0) + 1
    db.flush()
    for table in Base.metadata.sorted_tables:
        if "organization_id" not in table.c or table.name in IMMUTABLE_TABLES or table.name == "users":
            continue
        values = {}
        for column in table.c:
            if column.name in PII_COLUMNS:
                if column.nullable:
                    values[column.name] = None
                elif column.type.python_type is str:
                    values[column.name] = "حذف‌شده"
        if values:
            db.execute(table.update().where(table.c.organization_id == organization_id).values(**values))
    for customer in db.query(Customer).filter(Customer.organization_id == organization_id).execution_options(skip_tenant_filter=True).all():
        customer.name, customer.mobile, customer.email = "حذف‌شده", f"{customer.id:011d}"[-11:], None
    db.query(Ticket).filter(Ticket.organization_id == organization_id).execution_options(skip_tenant_filter=True).update({Ticket.access_token: None}, synchronize_session=False)
    db.query(TicketMessage).filter(TicketMessage.organization_id == organization_id).execution_options(skip_tenant_filter=True).update({TicketMessage.author_name: None}, synchronize_session=False)
    db.execute(text("UPDATE customer_requests SET payload = '{}' WHERE organization_id = :org"), {"org": organization_id})
    org.logo_path, org.deprovisioned_at, org.is_active = None, _now(), False
    db.commit()
    root = storage.MEDIA_ROOT.resolve()
    for folder in ("deliveries", "tickets", "drivers", "organizations"):
        target = (root / folder / str(organization_id)).resolve()
        if root in target.parents and target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
