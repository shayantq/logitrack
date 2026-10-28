"""
نشست ماندگار ورود — توکن دسترسی کوتاه (پیش‌فرض ۳۰ دقیقه) + توکن تمدید در کوکی HttpOnly.

- توکن تمدید تصادفی است و فقط هش SHA-256 آن ذخیره می‌شود؛ جاوااسکریپت صفحه هرگز آن را نمی‌بیند (XSS).
- هر تمدید توکن را عوض می‌کند (چرخش). اگر توکن جایگزین‌شده دوباره بیاید، یعنی دزدیده شده است و کل
  خانواده نشست باطل می‌شود؛ مگر در چند ثانیه اول (دو زبانه هم‌زمان تمدید کرده‌اند) که فقط توکن دسترسی تازه می‌گیرد.
- «مرا به خاطر بسپار»: کوکی ماندگار ۳۰ روزه (با سقف بیکاری ۷ روز)؛ بدون آن، کوکی با بستن مرورگر پاک می‌شود
  و نشست حداکثر ۱۲ ساعت (و ۲ ساعت بیکاری) اعتبار دارد. کارکنان پلتفرم هیچ‌وقت ماندگار نمی‌شوند.
- تغییر رمز، بازنشانی، غیرفعال‌سازی (token_version) و غیرفعال شدن سازمان همه نشست‌ها را بی‌اثر می‌کند.
"""
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Request, Response
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core import request_context
from app.core.tenancy import SKIP_TENANT_FILTER
from app.models import AuthSession, User

COOKIE_NAME = "pasineh_refresh"
COOKIE_PATH = "/auth"
REMEMBER_DAYS = 30
REMEMBER_IDLE = timedelta(days=7)
SESSION_HOURS = 12
SESSION_IDLE = timedelta(hours=2)
REUSE_GRACE = timedelta(seconds=30)
PLATFORM_ROLES = {"platform_admin", "platform_support"}


class SessionInvalid(Exception):
    pass


@dataclass
class Issued:
    user: User
    token: str | None          # None یعنی کوکی فعلی مرورگر معتبر است و عوض نمی‌شود
    remember: bool
    expires_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _role(user: User) -> str:
    return getattr(user.role, "value", user.role)


def _new_row(db: Session, user: User, family: str, remember: bool, expires_at: datetime) -> tuple[AuthSession, str]:
    token = secrets.token_urlsafe(32)
    now = _now()
    row = AuthSession(user_id=user.id, family=family, token_hash=_hash(token), remember=remember,
                      token_version=user.token_version or 0, created_at=now, last_used_at=now, expires_at=expires_at,
                      ip=request_context.client_ip.get(), user_agent=request_context.user_agent.get())
    db.add(row)
    return row, token


def start(db: Session, user: User, remember: bool) -> Issued:
    remember = remember and _role(user) not in PLATFORM_ROLES
    expires = _now() + (timedelta(days=REMEMBER_DAYS) if remember else timedelta(hours=SESSION_HOURS))
    _, token = _new_row(db, user, secrets.token_hex(16), remember, expires)
    db.commit()
    return Issued(user, token, remember, expires)


def _revoke_family(db: Session, family: str) -> None:
    db.execute(update(AuthSession).where(AuthSession.family == family, AuthSession.revoked_at.is_(None))
               .values(revoked_at=_now()))
    db.commit()


def refresh(db: Session, token: str | None) -> Issued:
    if not token:
        raise SessionInvalid()
    row = db.query(AuthSession).filter(AuthSession.token_hash == _hash(token)).first()
    now = _now()
    if row is None or row.revoked_at is not None:
        raise SessionInvalid()
    user = db.query(User).filter(User.id == row.user_id).execution_options(**SKIP_TENANT_FILTER).first()
    idle = REMEMBER_IDLE if row.remember else SESSION_IDLE
    if (user is None or user.is_active is False or (user.token_version or 0) != row.token_version
            or (user.organization_id is not None and (user.organization is None or not user.organization.is_active))
            or row.expires_at <= now or row.last_used_at + idle <= now):
        _revoke_family(db, row.family)
        raise SessionInvalid()
    if row.replaced_at is not None:
        if now - row.replaced_at <= REUSE_GRACE:
            return Issued(user, None, row.remember, row.expires_at)     # زبانه دیگر همین الان تمدید کرده است
        _revoke_family(db, row.family)                                    # توکن قدیمی دوباره آمده ← سرقت
        raise SessionInvalid()
    # چرخش اتمی: از دو درخواست هم‌زمان با یک توکن فقط یکی جانشین می‌سازد
    claimed = db.execute(update(AuthSession).where(AuthSession.id == row.id, AuthSession.replaced_at.is_(None))
                         .values(replaced_at=now, last_used_at=now)).rowcount
    if claimed != 1:
        db.rollback()
        return Issued(user, None, row.remember, row.expires_at)
    _, new_token = _new_row(db, user, row.family, row.remember, row.expires_at)
    db.commit()
    return Issued(user, new_token, row.remember, row.expires_at)


def end(db: Session, token: str | None) -> None:
    if not token:
        return
    row = db.query(AuthSession).filter(AuthSession.token_hash == _hash(token)).first()
    if row is not None:
        _revoke_family(db, row.family)


def active_for(db: Session, user: User) -> list[AuthSession]:
    now = _now()
    return (db.query(AuthSession)
            .filter(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None), AuthSession.replaced_at.is_(None),
                    AuthSession.expires_at > now, AuthSession.token_version == (user.token_version or 0))
            .order_by(AuthSession.last_used_at.desc()).all())


def revoke_for(db: Session, user: User, session_id: int) -> bool:
    row = db.query(AuthSession).filter(AuthSession.id == session_id, AuthSession.user_id == user.id).first()
    if row is None:
        return False
    _revoke_family(db, row.family)
    return True


def remembered(db: Session, token: str | None) -> bool:
    if not token:
        return False
    row = db.query(AuthSession).filter(AuthSession.token_hash == _hash(token)).first()
    return bool(row and row.remember)


def set_cookie(request: Request, response: Response, issued: Issued) -> None:
    if issued.token is None:
        return
    max_age = int((issued.expires_at - _now()).total_seconds()) if issued.remember else None
    response.set_cookie(COOKIE_NAME, issued.token, max_age=max_age, path=COOKIE_PATH, httponly=True,
                        secure=request.url.scheme == "https", samesite="strict")


def clear_cookie(request: Request, response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH, httponly=True, secure=request.url.scheme == "https", samesite="strict")


def current_family(db: Session, token: str | None) -> str | None:
    if not token:
        return None
    row = db.query(AuthSession).filter(AuthSession.token_hash == _hash(token)).first()
    return row.family if row else None
