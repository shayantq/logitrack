"""
تنظیمات امنیتی مشترک: کلید امضای JWT، هش رمز عبور و ساخت توکن.

⚠️ کلید JWT دیگر داخل کد نوشته نمی‌شود و فقط از متغیر محیطی SECRET_KEY
خوانده می‌شود. اگر تنظیم نشده باشد، یک کلید تصادفی موقت ساخته می‌شود (با
هشدار در لاگ) — در این حالت با هر ری‌استارت سرور همه کاربران باید دوباره
وارد شوند. در محیط واقعی حتماً SECRET_KEY را در فایل .env تنظیم کنید.
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

SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
if not SECRET_KEY:
    SECRET_KEY = secrets.token_urlsafe(64)
    logger.warning("SECRET_KEY تنظیم نشده است؛ یک کلید تصادفی موقت ساخته شد. توکن‌ها با ری‌استارت سرور باطل می‌شوند.")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", str(60 * 24)))

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
