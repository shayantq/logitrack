"""
تنظیمات امنیتی مشترک: کلید امضای JWT، هش رمز عبور و ساخت توکن.

⚠️ کلید JWT دیگر داخل کد نوشته نمی‌شود و فقط از متغیر محیطی SECRET_KEY
خوانده می‌شود. اگر تنظیم نشده باشد، یک کلید تصادفی موقت ساخته می‌شود (با
هشدار در لاگ) — در این حالت با هر ری‌استارت سرور همه کاربران باید دوباره
وارد شوند. در محیط واقعی حتماً SECRET_KEY را در فایل .env تنظیم کنید؛ با APP_ENV=production برنامه
بدون کلید امن (یا با رمز نمونه دیتابیس) اصلاً بالا نمی‌آید.
"""
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from jose import jwt
from passlib.context import CryptContext

load_dotenv()

logger = logging.getLogger(__name__)

# مقدارهای نمونه .env.example و موارد رایج که نباید در سرور اصلی پذیرفته شوند
PLACEHOLDER_SECRETS = {"change-me-to-a-long-random-string", "change-me", "changeme", "secret", "your_secure_password",
                       "ci-only-secret-key", "ci-db-password"}
MIN_SECRET_LENGTH = 32


def is_production() -> bool:
    """APP_ENV=production فقط روی سرور اصلی؛ توسعه، تست و CI همان رفتار قبلی را دارند."""
    return os.getenv("APP_ENV", "").strip().lower() == "production"


def _db_password(url: str) -> str:
    from sqlalchemy.engine import make_url
    try:
        return make_url(url).password or ""
    except Exception:
        return ""


def insecure_settings() -> list[tuple[str, bool]]:
    """
    بررسی‌های پیش از اجرا در سرور اصلی: (نام بررسی، قبول شد؟). هیچ مقداری برگردانده یا چاپ نمی‌شود.
    """
    key = os.getenv("SECRET_KEY", "").strip()
    checks = [
        ("SECRET_KEY تنظیم شده", bool(key)),
        (f"SECRET_KEY حداقل {MIN_SECRET_LENGTH} نویسه", len(key) >= MIN_SECRET_LENGTH),
        ("SECRET_KEY مقدار نمونه نیست", key.lower() not in PLACEHOLDER_SECRETS and not key.lower().startswith("change-me")),
    ]
    for name in ("DATABASE_URL", "DEMO_DATABASE_URL"):
        url = os.getenv(name, "").strip()
        if url:
            password = _db_password(url)
            checks.append((f"رمز دیتابیس در {name} نمونه یا خالی نیست", bool(password) and password.lower() not in PLACEHOLDER_SECRETS))
    return checks


def enforce_production_settings() -> None:
    """هنگام بالا آمدن وب صدا زده می‌شود: سرور اصلی با کلید یا رمز ناامن اصلاً بالا نمی‌آید (مقدارها در پیام نمی‌آیند)."""
    if not is_production():
        return
    failed = [name for name, ok in insecure_settings() if not ok]
    if failed:
        raise RuntimeError("تنظیمات امنیتی سرور اصلی ناقص است: " + "، ".join(failed)
                           + " — مقدارها را در .env اصلاح کنید و «python -m app.security_preflight» را اجرا کنید.")


SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
if not SECRET_KEY:
    SECRET_KEY = secrets.token_urlsafe(64)
    logger.warning("SECRET_KEY تنظیم نشده است؛ یک کلید تصادفی موقت ساخته شد. توکن‌ها با ری‌استارت سرور باطل می‌شوند.")

ALGORITHM = "HS256"
# توکن دسترسی کوتاه است؛ ماندگاری ورود با کوکی HttpOnly تمدید است (app/services/session_service.py)
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

bcrypt_context = CryptContext(schemes=['bcrypt'], deprecated='auto')


def create_access_token(username: str, user_id: int, expiry_time: timedelta, token_version: int = 0) -> str:
    """tv = نسخه توکن کاربر؛ با بازنشانی رمز یا غیرفعال‌سازی زیاد می‌شود و توکن‌های قدیمی باطل می‌شوند."""
    expires = datetime.now(timezone.utc) + expiry_time
    encode = {
        'sub': username,
        'id': user_id,
        'exp': expires,
        'tv': token_version,
    }
    return jwt.encode(encode, SECRET_KEY, algorithm=ALGORITHM)
