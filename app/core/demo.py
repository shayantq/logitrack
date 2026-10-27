"""
نسخه نمایشی خصوصی: یک دیتابیس جدا (DEMO_DATABASE_URL) با یک سازمان فرضی که فقط با لینک مخفی باز می‌شود.

  • لینک: /app/d/<DEMO_ACCESS_TOKEN> — بدون ورود، مستقیم داشبورد ادمین سازمان فرضی. تا توکن تنظیم نشود، دمو وجود ندارد.
  • هر درخواستی که توکن ورودش ادعای demo دارد به دیتابیس دمو می‌رود؛ دیتابیس اصلی هرگز دیده نمی‌شود.
  • محدودیت‌ها سمت سرور: فقط چرخه‌های اصلی قابل ثبت‌اند؛ خروجی، دانلود، تنظیمات و مدیریت کاربران بسته است.
  • هر ۳۰ دقیقه دیتابیس از روی قالب از نو ساخته می‌شود (app/demo_db.py).
"""
from __future__ import annotations

import hmac
import os
import re
from functools import lru_cache

from fastapi import HTTPException, Request
from jose import JWTError, jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.security import ALGORITHM, SECRET_KEY

DEMO_USERNAME = "arya_admin"
RESET_MINUTES = 30
SESSION_HOURS = 6
RESTRICTED = "این بخش در نسخه نمایشی غیرفعال است."

# نوشتن‌های مجاز: چرخه اصلی سفارش، انبار، رانندگان و پشتیبانی
_ALLOWED_WRITES = [re.compile(p) for p in (
    r"POST /orders/?", r"PUT /orders/\d+/(status|assign)", r"POST /orders/\d+/checkpoints", r"POST /dispatch/suggest",
    r"POST /backorders/allocate",
    r"POST /inbound/receipts/\d+/(receive|close)", r"POST /quality/inspections",
    r"POST /putaway/tasks/\d+/(execute|suggest)",
    r"POST /picking/lists", r"POST /picking/lines/\d+/(pick|short)",
    r"POST /shipping/orders/\d+/pack", r"POST /shipping/shipments(/\d+/dispatch)?",
    r"POST /stocktakes/?", r"POST /stocktakes/\d+/(submit|approve|recount|lines)", r"PUT /stocktakes/\d+/lines/\d+",
    r"POST /drivers/applications/\d+/(approve|reject)", r"POST /driver-requests/\d+/(approve|reject)",
    r"POST /tickets/?", r"PATCH /tickets/\d+", r"POST /tickets/\d+/(messages|resolve|close|escalate)",
    r"PUT /notifications/(\d+/read|read-all)", r"DELETE /notifications(/\d+)?",
    r"PUT /users/me/tours/[a-z0-9_-]+", r"DELETE /users/me/tours",
)]
# خواندن‌های بسته: خروجی و دانلود، مالی و ارزش، تنظیمات، کاربران، دفتر و اسناد کامل
_BLOCKED_READS = re.compile(
    r"^/(reports/(?!stats$)|catalog/(export|template)|labels/|readiness|permissions|workflows|valuation"
    r"|users/(activity-log|\d+)|replenishment/(capital-plan|policy)|inventory/(ledger-check|movements|documents|stock-card|reservations)"
    r"|wms/|shipping/orders/\d+/packing-slip|platform)"
)


def enabled() -> bool:
    return len(access_token()) >= 24 and bool(database_url())


def access_token() -> str:
    return os.getenv("DEMO_ACCESS_TOKEN", "").strip()


def database_url() -> str:
    url = os.getenv("DEMO_DATABASE_URL", "").strip()
    return url.replace("postgresql://", "postgresql+psycopg://", 1) if url.startswith("postgresql://") else url


def token_matches(candidate: str) -> bool:
    return enabled() and hmac.compare_digest(candidate.encode(), access_token().encode())


@lru_cache(maxsize=1)
def session_factory():
    # pool_pre_ping: هر ۳۰ دقیقه دیتابیس دمو از نو ساخته می‌شود و اتصال‌های قبلی قطع می‌شوند
    return sessionmaker(autocommit=False, autoflush=False, bind=create_engine(database_url(), pool_pre_ping=True, pool_size=3))


def is_demo_request(request: Request | None) -> bool:
    if request is None or not enabled():
        return False
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return False
    try:
        return jwt.decode(auth[7:], SECRET_KEY, algorithms=[ALGORITHM]).get("demo") is True
    except JWTError:
        return False


def guard(method: str, path: str) -> None:
    """فقط کارهای مجاز نسخه نمایشی؛ بقیه با پیام روشن رد می‌شوند."""
    path = path.rstrip("/") or "/"
    if method in ("GET", "HEAD", "OPTIONS"):
        if _BLOCKED_READS.match(path):
            raise HTTPException(status_code=403, detail=RESTRICTED)
        return
    if not any(p.fullmatch(f"{method} {path}") for p in _ALLOWED_WRITES):
        raise HTTPException(status_code=403, detail=RESTRICTED)


def is_demo_session(db) -> bool:
    return bool(db is not None and db.info.get("demo"))
