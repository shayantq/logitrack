"""
Fixture های مخصوص تست‌های یکپارچگی (tests/integration).

این تست‌ها به یک دیتابیس PostgreSQL کاملاً جدا (logitrack_test) وصل
می‌شوند — نه به دیتابیس اصلی/دمو (logitrack) — تا هرگز داده‌های واقعی را
دست‌کاری نکنند. جدول‌ها فقط یک‌بار در ابتدای کل session تست ساخته می‌شوند.
"""
import os
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from app.database import Base
from app import models  # noqa: F401 -- برای ثبت شدن همه مدل‌ها روی Base.metadata
from app import models_notification  # noqa: F401


def resolve_test_database_url() -> str:
    url = os.getenv("TEST_DATABASE_URL", "")
    if url:
        return url.replace("postgresql://", "postgresql+psycopg://", 1)

    # fallback: اگر TEST_DATABASE_URL تنظیم نشده بود، از DATABASE_URL می‌سازیمش
    # (فقط برای راحتی — تنظیم صریح TEST_DATABASE_URL همیشه ترجیح داده می‌شود)
    main_url = os.getenv("DATABASE_URL", "")
    if main_url and "/logitrack" in main_url:
        return main_url.replace("/logitrack", "/logitrack_test", 1).replace("postgresql://", "postgresql+psycopg://", 1)
    return ""


TEST_DATABASE_URL = resolve_test_database_url()


@pytest.fixture(scope="session", autouse=True)
def _prepare_test_database():
    """
    یک‌بار در ابتدای کل session، دیتابیس تستِ جدا را کاملاً از نو با ساختار
    فعلی مدل‌ها می‌سازد — create_all جدول‌های قدیمی را به‌روز نمی‌کند، پس بعد
    از هر تغییر مدل، ساختار کهنه باعث خطا می‌شد.
    """
    if not TEST_DATABASE_URL or "postgresql" not in TEST_DATABASE_URL:
        yield  # اگر Postgres در دسترس نیست، تست‌ها خودشان skip می‌شوند (مارکر integration)
        return
    # محافظ: فقط دیتابیسی که نامش به _test ختم می‌شود پاک می‌شود، هرگز دیتابیس اصلی
    database_name = make_url(TEST_DATABASE_URL).database or ""
    if not database_name.endswith("_test"):
        raise RuntimeError(f"TEST_DATABASE_URL باید به دیتابیسی با پسوند _test اشاره کند (فعلی: {database_name!r}).")
    engine = create_engine(TEST_DATABASE_URL)
    try:
        engine.connect().close()
    except OperationalError as e:
        # مثلاً اجرای pytest روی ویندوز بیرون از داکر: به‌جای خطای قرمز، تست با دلیل روشن skip می‌شود
        engine.dispose()
        pytest.skip(f"دیتابیس تست در دسترس نیست (داخل داکر اجرا کنید): {e.__class__.__name__}")
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    Base.metadata.create_all(bind=engine)
    yield
    engine.dispose()
