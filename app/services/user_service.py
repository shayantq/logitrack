"""
لایه سرویس کاربران (User Service)
منطق تجاری مربوط به کاربران: جلوگیری از نام‌کاربری/ایمیل تکراری، تولید
خودکار کد راننده، و کنترل دسترسی ادمین‌محور برای مدیریت کاربران.

مرحله ۱۵: ویرایش، غیرفعال‌سازی (به‌جای حذف کاربر دارای سابقه)، رمز موقت با اجبار تغییر،
قفل موقت پس از تلاش‌های ناموفق ورود، و ثبت همه این‌ها در گزارش فعالیت (audit_service).
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.core import storage, totp
from app.core.iran import fa_digits, latin_digits
from app.models import AuditLog, DriverDocument, PasswordReset, Order, OrderStatusHistory, StockMovement, User, Vehicle, Warehouse
from app.core.security import SECRET_KEY, bcrypt_context
from app.core.tenancy import SKIP_TENANT_FILTER
from app.schemas.user import CreateUserRequest
from app.services import audit_service, messaging
from app.services.exceptions import ConflictError, DomainError, ForbiddenError, NotFoundError

LOCK_AFTER = 5                      # تلاش ناموفق پشت‌سرهم
LOCK_MINUTES = 15
ACTIVE_DRIVER_STATUSES = ("assigned", "picking_up", "picked_up", "in_transit")
# جدول‌هایی که «پرونده» کاربرند و سابقه کاری حساب نمی‌شوند (با حذف کاربر پاک می‌شوند یا بی‌اهمیت‌اند)
_NOT_HISTORY = {"audit_logs", "driver_documents", "driver_shifts", "driver_time_off", "driver_profiles", "driver_requests",
                "driver_invites", "vehicles", "commission_plans", "organization_requests"}
ROLE_FA = {"org_admin": "ادمین سازمان", "warehouse_manager": "مدیر انبار", "driver": "راننده"}
_TEMP_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
GENERIC_LOGIN_ERROR = 'نام کاربری یا رمز عبور اشتباه است. لطفاً اطلاعات ورود را بررسی و دوباره تلاش کنید.'


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _role(u: User) -> str:
    return getattr(u.role, "value", u.role)


def _label(u: User) -> str:
    return u.full_name or u.username


def _require_admin(user: User) -> None:
    if _role(user) != "org_admin":
        raise ForbiddenError("فقط ادمین سازمان می‌تواند حساب‌ها را مدیریت کند.")


def _target(db: Session, user_id: int) -> User:
    target = db.get(User, user_id)
    if target is None:
        raise NotFoundError("کاربر مورد نظر یافت نشد.")
    return target


def _other_active_admins(db: Session, target: User) -> int:
    return db.query(User).filter(User.role == "org_admin", User.is_active.is_(True), User.id != target.id).count()


def create_user(db: Session, current_user: User, request: CreateUserRequest) -> User:
    if current_user.role != 'org_admin':
        raise ForbiddenError('فقط ادمین می‌تواند کاربر جدید ثبت کند.')

    # نام کاربری و ایمیل در کل پلتفرم یکتا هستند (ورود فقط با نام کاربری است)،
    # پس بررسی باید بین همه سازمان‌ها انجام شود، نه فقط سازمان جاری
    existing = db.query(User).filter(or_(
        User.username == request.username,
        User.email == request.email
    )).execution_options(**SKIP_TENANT_FILTER).first()
    if existing:
        raise ConflictError('کاربری با این نام کاربری یا ایمیل قبلاً ثبت شده است.')

    if request.warehouse_id is not None and db.get(Warehouse, request.warehouse_id) is None:
        raise NotFoundError('انبار انتخاب‌شده یافت نشد.')

    try:
        requested_data = request.model_dump(exclude={'password'})
        new_user = User(
            **requested_data,
            organization_id=current_user.organization_id,
            hashed_password=bcrypt_context.hash(request.password)
        )
        db.add(new_user)
        db.flush()  # گرفتن id برای ساخت کد راننده، در همان تراکنش

        # تولید خودکار کد راننده برای کاربران با نقش راننده
        if new_user.role == 'driver' and not new_user.driver_code:
            new_user.driver_code = f"DRV-{new_user.id:04d}"

        audit_service.log(db, current_user, "user.create",
                          f"کاربر «{_label(new_user)}» با نقش {ROLE_FA.get(_role(new_user), _role(new_user))} ساخته شد", target=new_user)
        db.commit()
        db.refresh(new_user)
        return new_user
    except Exception:
        db.rollback()
        raise


def list_users(db: Session, user: User) -> list[User]:
    if user.role != 'org_admin':
        raise ForbiddenError('شما مجوز مشاهده لیست کاربران را ندارید.')
    return db.query(User).order_by(User.id).all()


# ---------------------------------------------------------------------------
# مدیریت حساب‌ها (مرحله ۱۵)
# ---------------------------------------------------------------------------
def history_count(db: Session, user_id: int) -> int:
    """تعداد سوابق کاری کاربر در همه جدول‌هایی که به او اشاره می‌کنند (برای تصمیم حذف یا غیرفعال‌سازی)."""
    from app.database import Base
    total = 0
    for table in Base.metadata.sorted_tables:
        if table.name in _NOT_HISTORY:
            continue
        for column in table.columns:
            if any(fk.column.table.name == "users" for fk in column.foreign_keys):
                total += db.execute(select(func.count()).select_from(table).where(column == user_id)).scalar() or 0
    return total


def update_user(db: Session, admin: User, user_id: int, data: dict) -> User:
    _require_admin(admin)
    target = _target(db, user_id)
    changes: dict[str, list] = {}
    role = data.get("role")
    if role and role != _role(target):
        if target.id == admin.id:
            raise ConflictError("نقش خودتان را نمی‌توانید تغییر دهید.")
        if "driver" in (role, _role(target)):
            raise ConflictError("حساب راننده پرونده، خودرو و سوابق سفر دارد و به نقش دیگری تبدیل نمی‌شود؛ برای این کار حساب جدید بسازید.")
        if _role(target) == "org_admin" and target.is_active and _other_active_admins(db, target) == 0:
            raise ConflictError("سازمان باید دست‌کم یک ادمین فعال داشته باشد.")
        changes["role"] = [ROLE_FA.get(_role(target)), ROLE_FA.get(role)]
        target.role = role
    if data.get("email") and data["email"] != target.email:
        taken = db.query(User).filter(User.email == data["email"], User.id != target.id).execution_options(**SKIP_TENANT_FILTER).first()
        if taken:
            raise ConflictError("این ایمیل برای کاربر دیگری ثبت شده است.")
    for field in ("full_name", "email", "mobile", "city"):
        if field in data and (data[field] or None) != getattr(target, field):
            if field == "email" and not data[field]:
                continue                                  # ایمیل پاک نمی‌شود
            changes[field] = [getattr(target, field), data[field] or None]
            setattr(target, field, data[field] or None)
    if _role(target) == "warehouse_manager":
        wid = data.get("warehouse_id") or target.warehouse_id
        if not wid:
            raise ConflictError("برای مدیر انبار، انبار تحت مدیریت را انتخاب کنید.")
        if db.get(Warehouse, wid) is None:
            raise NotFoundError("انبار انتخاب‌شده یافت نشد.")
        if wid != target.warehouse_id:
            changes["warehouse_id"] = [target.warehouse_id, wid]
            target.warehouse_id = wid
    elif target.warehouse_id:
        target.warehouse_id = None
    if not changes:
        return target
    fa = {"role": "نقش", "full_name": "نام", "email": "ایمیل", "mobile": "موبایل", "city": "شهر", "warehouse_id": "انبار"}
    audit_service.log(db, admin, "user.update", f"اطلاعات «{_label(target)}» ویرایش شد ({'، '.join(fa[k] for k in changes)})",
                      target=target, details={"changes": changes})
    db.commit()
    db.refresh(target)
    return target


def set_active(db: Session, admin: User, user_id: int, active: bool) -> User:
    _require_admin(admin)
    target = _target(db, user_id)
    if target.is_active == active:
        return target
    if not active:
        if target.id == admin.id:
            raise ConflictError("حساب خودتان را نمی‌توانید غیرفعال کنید.")
        if _role(target) == "org_admin" and _other_active_admins(db, target) == 0:
            raise ConflictError("سازمان باید دست‌کم یک ادمین فعال داشته باشد.")
        if _role(target) == "driver":
            busy = db.query(Order).filter(Order.driver_id == target.id, Order.status.in_(ACTIVE_DRIVER_STATUSES)).count()
            if busy:
                raise ConflictError(f"این راننده {fa_digits(str(busy))} سفارش در جریان دارد؛ "
                                    "اول سفارش‌ها را به راننده دیگری بدهید یا تمام کنید.")
        target.is_active = False
        target.token_version = (target.token_version or 0) + 1      # خروج فوری از همه دستگاه‌ها
        audit_service.log(db, admin, "user.deactivate", f"حساب «{_label(target)}» غیرفعال شد", target=target)
    else:
        target.is_active = True
        target.failed_logins, target.locked_until = 0, None
        audit_service.log(db, admin, "user.activate", f"حساب «{_label(target)}» دوباره فعال شد", target=target)
    db.commit()
    db.refresh(target)
    return target


def reset_password(db: Session, admin: User, user_id: int) -> tuple[User, str]:
    """رمز موقت تصادفی؛ کاربر در اولین ورود باید عوضش کند و همه نشست‌های قبلی‌اش بسته می‌شود."""
    _require_admin(admin)
    target = _target(db, user_id)
    if target.id == admin.id:
        raise ConflictError("رمز خودتان را از «تغییر رمز» عوض کنید.")
    password = "".join(secrets.choice(_TEMP_ALPHABET) for _ in range(10))
    target.hashed_password = bcrypt_context.hash(password)
    target.must_change_password = True
    target.token_version = (target.token_version or 0) + 1
    target.failed_logins, target.locked_until = 0, None
    # گوشی گم‌شده: بازنشانی رمز توسط ادمین، ورود دومرحله‌ای را هم خاموش می‌کند تا کاربر دوباره راه‌اندازی‌اش کند
    mfa_was_on = target.totp_enabled_at is not None
    target.totp_secret, target.totp_enabled_at, target.totp_last_step = None, None, None
    audit_service.log(db, admin, "user.reset_password", f"رمز «{_label(target)}» بازنشانی شد (رمز موقت)"
                      + ("؛ ورود دومرحله‌ای خاموش شد" if mfa_was_on else ""), target=target)
    db.commit()
    db.refresh(target)
    return target, password


def unlock(db: Session, admin: User, user_id: int) -> User:
    _require_admin(admin)
    target = _target(db, user_id)
    target.failed_logins, target.locked_until = 0, None
    audit_service.log(db, admin, "user.unlock", f"قفل ورود «{_label(target)}» برداشته شد", target=target)
    db.commit()
    db.refresh(target)
    return target


def user_detail(db: Session, admin: User, user_id: int) -> dict:
    _require_admin(admin)
    target = _target(db, user_id)
    since = _now() - timedelta(days=30)
    stats = {
        "logins_30d": db.query(AuditLog).filter(AuditLog.actor_id == target.id, AuditLog.action == "auth.login",
                                                AuditLog.created_at >= since).count(),
        "failed_logins_30d": db.query(AuditLog).filter(AuditLog.target_type == "user", AuditLog.target_id == target.id,
                                                       AuditLog.action == "auth.login_failed", AuditLog.created_at >= since).count(),
        "order_actions": db.query(OrderStatusHistory).filter(OrderStatusHistory.changed_by_id == target.id).count(),
        "stock_movements": db.query(StockMovement).filter(StockMovement.created_by_id == target.id).count(),
        "deliveries": db.query(Order).filter(Order.driver_id == target.id, Order.status == "delivered").count()
        if _role(target) == "driver" else 0,
        "history": history_count(db, target.id),
    }
    return {"user": target, "stats": stats}


def delete_user(db: Session, user: User, user_id: int) -> None:
    if user.role != 'org_admin':
        raise ForbiddenError('شما مجوز حذف کاربر را ندارید.')

    if user.id == user_id:
        raise ConflictError('امکان حذف حساب کاربری خودتان وجود ندارد.')

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise NotFoundError('کاربر مورد نظر یافت نشد.')

    if db.query(Vehicle).filter(Vehicle.driver_id == target.id).first():
        raise ConflictError('این راننده هنوز خودروی اختصاص‌یافته دارد؛ ابتدا خودرو را به راننده دیگری منتقل یا حذف کنید.')
    # کاربری که سابقه کاری دارد حذف نمی‌شود تا گزارش‌ها و دفتر گردش ناقص نشوند
    if history_count(db, target.id):
        raise ConflictError('این کاربر سابقه کاری (سفارش، گردش انبار، تیکت و ...) دارد؛ به‌جای حذف، حسابش را غیرفعال کنید.')
    if _role(target) == "org_admin" and _other_active_admins(db, target) == 0:
        raise ConflictError("سازمان باید دست‌کم یک ادمین فعال داشته باشد.")

    audit_service.log(db, user, "user.delete", f"کاربر «{_label(target)}» ({target.username}) حذف شد",
                      target_type="user", target_id=target.id, target_label=_label(target))
    # فایل مدارک احراز هویت روی دیسک هم پاک شود (ردیف‌هایش با cascade دیتابیس حذف می‌شوند)
    files = [d.file_path for d in db.query(DriverDocument).filter(DriverDocument.user_id == target.id).all()]
    db.delete(target)
    db.commit()
    for path in files:
        storage.delete(path)


# ---------------------------------------------------------------------------
# ورود و تغییر رمز
# ---------------------------------------------------------------------------
_timing_hash: str | None = None


def _equalize_timing(password: str) -> None:
    """برای نام کاربری ناموجود هم یک بررسی bcrypt انجام می‌شود تا زمان پاسخ، وجود حساب را لو ندهد."""
    global _timing_hash
    if _timing_hash is None:
        _timing_hash = bcrypt_context.hash(secrets.token_urlsafe(16))
    bcrypt_context.verify(password, _timing_hash)


class MfaRequired(DomainError):
    """رمز درست است ولی کد ورود دومرحله‌ای لازم است (فرم ورود فیلد کد را نشان می‌دهد)."""


MFA_REQUIRED = "کد ورود دومرحله‌ای را از برنامه احراز هویت گوشی‌تان وارد کنید."
MFA_WRONG = "کد ورود دومرحله‌ای درست نیست یا قبلاً استفاده شده؛ کد تازه را وارد کنید."


def _count_failure(db: Session, user: User, now: datetime) -> None:
    # شمارش و قفل با UPDATE شرطی در خود دیتابیس تا تلاش‌های هم‌زمان هیچ‌کدام گم نشوند
    attempts = db.execute(
        update(User).where(User.id == user.id)
        .values(failed_logins=func.coalesce(User.failed_logins, 0) + 1)
        .returning(User.failed_logins).execution_options(**SKIP_TENANT_FILTER)
    ).scalar_one()
    audit_service.log(db, None, "auth.login_failed", f"ورود ناموفق با نام کاربری «{user.username}»", target=user,
                      organization_id=user.organization_id, details={"attempt": attempts})
    locked = attempts >= LOCK_AFTER and db.execute(
        update(User).where(User.id == user.id, User.failed_logins >= LOCK_AFTER)
        .values(failed_logins=0, locked_until=now + timedelta(minutes=LOCK_MINUTES))
        .execution_options(**SKIP_TENANT_FILTER)
    ).rowcount
    if locked:
        audit_service.log(db, None, "auth.locked",
                          f"ورود «{user.username}» پس از {fa_digits(str(LOCK_AFTER))} تلاش ناموفق "
                          f"{fa_digits(str(LOCK_MINUTES))} دقیقه قفل شد", target=user, organization_id=user.organization_id)
    db.commit()


def authenticate(db: Session, username: str, password: str, otp: str | None = None) -> User:
    """
    ورود با قفل موقت: پس از ۵ تلاش ناموفق پشت‌سرهم (رمز یا کد دومرحله‌ای)، ۱۵ دقیقه ورود بسته است (حتی با رمز درست).
    اگر ورود دومرحله‌ای فعال است، بعد از رمز درست کد شش‌رقمی هم لازم است.
    """
    user = db.query(User).filter(User.username == username).execution_options(**SKIP_TENANT_FILTER).first()
    if user is None:
        _equalize_timing(password)
        raise DomainError(GENERIC_LOGIN_ERROR, 401)
    now = _now()
    if user.locked_until and user.locked_until > now:
        minutes = max(1, int((user.locked_until - now).total_seconds() // 60) + 1)
        raise DomainError(f"به دلیل چند تلاش ناموفق، ورود این حساب تا {fa_digits(str(minutes))} دقیقه دیگر بسته است. "
                          "اگر رمز را فراموش کرده‌اید، از ادمین سازمان بخواهید آن را بازنشانی کند.", 429)
    if not bcrypt_context.verify(password, user.hashed_password):
        _count_failure(db, user, now)
        raise DomainError(GENERIC_LOGIN_ERROR, 401)
    if user.is_active is False:
        raise DomainError("حساب کاربری شما غیرفعال شده است؛ با ادمین سازمان تماس بگیرید.", 403)
    if user.organization_id is not None and (user.organization is None or not user.organization.is_active):
        raise DomainError('حساب سازمان شما غیرفعال شده است؛ با پشتیبانی پسینه تماس بگیرید.', 403)
    if user.totp_enabled_at is not None:
        if not (otp or "").strip():
            raise MfaRequired(MFA_REQUIRED, 401)
        step = totp.verify(user.totp_secret, otp, user.totp_last_step)
        if step is None:
            _count_failure(db, user, now)
            raise MfaRequired(MFA_WRONG, 401)
        user.totp_last_step = step
    user.failed_logins, user.locked_until, user.last_login_at = 0, None, now
    audit_service.log(db, user, "auth.login", "ورود به سامانه")
    db.commit()
    return user


PLATFORM_ROLES = ("platform_admin", "platform_support")


def mfa_required(user: User) -> bool:
    """در سرور اصلی ورود دومرحله‌ای برای کارکنان پلتفرم (دسترسی به همه سازمان‌ها) اجباری است."""
    from app.core.security import is_production
    return is_production() and _role(user) in PLATFORM_ROLES


def mfa_setup(db: Session, user: User) -> dict:
    if user.totp_enabled_at is not None:
        raise ConflictError("ورود دومرحله‌ای از قبل فعال است.")
    user.totp_secret = totp.new_secret()
    db.commit()
    uri = totp.provisioning_uri(user.totp_secret, user.username)
    return {"secret": user.totp_secret, "uri": uri, "qr": totp.qr_svg_data_uri(uri)}


def mfa_enable(db: Session, user: User, code: str) -> None:
    if user.totp_enabled_at is not None:
        raise ConflictError("ورود دومرحله‌ای از قبل فعال است.")
    if not user.totp_secret:
        raise ConflictError("اول کد QR را بسازید و در برنامه احراز هویت اسکن کنید.")
    step = totp.verify(user.totp_secret, code, None)
    if step is None:
        raise ConflictError("کد درست نیست؛ ساعت گوشی را بررسی کنید و کد تازه را وارد کنید.")
    user.totp_enabled_at, user.totp_last_step = _now(), step
    audit_service.log(db, user, "auth.mfa_enabled", "ورود دومرحله‌ای فعال شد", target=user)
    db.commit()


def mfa_disable(db: Session, user: User, password: str, code: str) -> None:
    if user.totp_enabled_at is None:
        raise ConflictError("ورود دومرحله‌ای فعال نیست.")
    if mfa_required(user):
        raise ForbiddenError("برای کارکنان پلتفرم ورود دومرحله‌ای اجباری است و خاموش نمی‌شود.")
    if not bcrypt_context.verify(password or "", user.hashed_password):
        raise ConflictError("رمز عبور درست نیست.")
    step = totp.verify(user.totp_secret, code, user.totp_last_step)
    if step is None:
        raise ConflictError(MFA_WRONG)
    user.totp_secret, user.totp_enabled_at, user.totp_last_step = None, None, None
    audit_service.log(db, user, "auth.mfa_disabled", "ورود دومرحله‌ای خاموش شد", target=user)
    db.commit()


MAX_TOURS = 50


def set_tour_state(db: Session, user: User, tour_id: str | None, state: str | None) -> dict[str, str]:
    """راهنمای تعاملی: ثبت «دیده شد/رد شد» یک راهنما؛ tour_id خالی = پاک کردن همه (شروع دوباره)."""
    tours = dict(user.tour_state or {})
    if tour_id is None:
        tours = {}
    else:
        if tour_id not in tours and len(tours) >= MAX_TOURS:
            raise ConflictError("تعداد راهنماها بیش از حد مجاز است.")
        tours[tour_id] = state
    user.tour_state = tours          # انتساب دوباره تا SQLAlchemy تغییر JSON را ببیند
    db.commit()
    return tours


def change_own_password(db: Session, user: User, old_password: str, new_password: str) -> User:
    if not bcrypt_context.verify(old_password, user.hashed_password):
        raise ConflictError("رمز عبور فعلی اشتباه است.")
    if old_password == new_password:
        raise ConflictError("رمز جدید باید با رمز فعلی فرق داشته باشد.")
    user.hashed_password = bcrypt_context.hash(new_password)
    user.must_change_password = False
    user.token_version = (user.token_version or 0) + 1        # نشست‌های دیگر بسته می‌شوند؛ این نشست توکن تازه می‌گیرد
    audit_service.log(db, user, "auth.password_changed", "رمز عبور خود را تغییر داد")
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# بازیابی رمز توسط خود کاربر (کد یک‌بارمصرف با پیامک یا ایمیل)
# ---------------------------------------------------------------------------
RESET_TTL = timedelta(minutes=10)
RESET_MAX_ATTEMPTS = 5
RESET_MAX_PER_HOUR = 3


def reset_channels() -> dict:
    return {"sms": messaging.sms_enabled(), "email": messaging.email_enabled()}


def _normalize_mobile(value: str) -> str | None:
    digits = "".join(ch for ch in value if ch.isdigit())
    if digits.startswith("0098"):
        digits = digits[4:]
    elif digits.startswith("98") and len(digits) == 12:
        digits = digits[2:]
    if len(digits) == 10 and digits.startswith("9"):
        digits = "0" + digits
    return digits if len(digits) == 11 and digits.startswith("09") else None


def _find_reset_user(db: Session, identifier: str) -> User | None:
    ident = latin_digits((identifier or "").strip())
    if not ident:
        return None
    conditions = [User.username == ident, func.lower(User.email) == ident.lower()]
    mobile = _normalize_mobile(ident)
    if mobile:
        conditions.append(User.mobile == mobile)
    users = db.query(User).filter(or_(*conditions)).execution_options(**SKIP_TENANT_FILTER).limit(2).all()
    return users[0] if len(users) == 1 else None      # شناسه مبهم (مثلاً موبایل مشترک) ← هیچ


def _reset_hash(user_id: int, code: str) -> str:
    return hmac.new(SECRET_KEY.encode(), f"{user_id}:{code}".encode(), hashlib.sha256).hexdigest()


def request_password_reset(db: Session, identifier: str) -> None:
    """
    پاسخ همیشه یکسان است (چه حساب باشد چه نباشد) تا وجود حساب‌ها فاش نشود.
    کد به موبایل کاربر (اگر پیامک فعال است) وگرنه به ایمیلش فرستاده می‌شود.
    """
    user = _find_reset_user(db, identifier)
    if user is None or user.is_active is False:
        return
    if user.mobile and messaging.sms_enabled():
        channel = "sms"
    elif user.email and messaging.email_enabled():
        channel = "email"
    else:
        return
    now = _now()
    recent = db.query(PasswordReset).filter(PasswordReset.user_id == user.id,
                                            PasswordReset.created_at > now - timedelta(hours=1)).count()
    if recent >= RESET_MAX_PER_HOUR:
        return
    db.query(PasswordReset).filter(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None)) \
        .update({PasswordReset.used_at: now}, synchronize_session=False)
    code = f"{secrets.randbelow(10 ** 6):06d}"
    db.add(PasswordReset(user_id=user.id, code_hash=_reset_hash(user.id, code), channel=channel,
                         created_at=now, expires_at=now + RESET_TTL))
    audit_service.log(db, None, "auth.reset_requested",
                      f"درخواست کد بازیابی رمز ({'پیامک' if channel == 'sms' else 'ایمیل'})", target=user,
                      organization_id=user.organization_id)
    db.commit()
    messaging.password_reset_code(user, code, channel)


INVALID_RESET = "کد نامعتبر است یا منقضی شده؛ دوباره درخواست کد بدهید."


def confirm_password_reset(db: Session, identifier: str, code: str, new_password: str) -> None:
    user = _find_reset_user(db, identifier)
    now = _now()
    reset = None
    if user is not None:
        reset = db.query(PasswordReset).filter(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None),
                                               PasswordReset.expires_at > now) \
            .order_by(PasswordReset.created_at.desc()).first()
    if reset is None or reset.attempts >= RESET_MAX_ATTEMPTS:
        raise ConflictError(INVALID_RESET)
    if not hmac.compare_digest(reset.code_hash, _reset_hash(user.id, latin_digits((code or "").strip()))):
        # شمارش اتمی تا تلاش‌های هم‌زمان سقف را دور نزنند
        attempts = db.execute(update(PasswordReset).where(PasswordReset.id == reset.id)
                              .values(attempts=PasswordReset.attempts + 1).returning(PasswordReset.attempts)
                              .execution_options(**SKIP_TENANT_FILTER)).scalar_one()
        db.commit()
        left = RESET_MAX_ATTEMPTS - attempts
        raise ConflictError(f"کد واردشده درست نیست. {fa_digits(str(left))} بار دیگر می‌توانید امتحان کنید." if left > 0
                            else INVALID_RESET)
    # مصرف یک‌باره و اتمی: از دو درخواست هم‌زمان با همین کد فقط یکی موفق می‌شود
    consumed = db.execute(update(PasswordReset).where(PasswordReset.id == reset.id, PasswordReset.used_at.is_(None))
                          .values(used_at=now).execution_options(**SKIP_TENANT_FILTER)).rowcount
    if consumed != 1:
        db.rollback()
        raise ConflictError(INVALID_RESET)
    user.hashed_password = bcrypt_context.hash(new_password)
    user.must_change_password = False
    user.token_version = (user.token_version or 0) + 1          # خروج از همه دستگاه‌ها
    user.failed_logins, user.locked_until = 0, None
    audit_service.log(db, user, "auth.password_reset", "رمز عبور را با کد بازیابی تغییر داد")
    db.commit()
