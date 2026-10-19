"""
Fixture مشترک برای تست‌های واحد (Unit Tests).

از یک دیتابیس SQLite کاملاً درون‌حافظه‌ای استفاده می‌شود — سریع، بدون نیاز
به PostgreSQL، مناسب برای تست درستیِ منطق تجاری.

⚠️ نکته مهم: SQLite از SELECT ... FOR UPDATE پشتیبانی نمی‌کند (که در
app/services/order_service.py و inventory_service.py برای جلوگیری از
race condition استفاده شده). چون در تست‌های واحد فقط "درستی منطق" را
می‌سنجیم، نه "رفتار واقعی قفل هم‌زمانی دیتابیس"، این متد را در سطح
دیتابیس تست بی‌اثر (no-op) می‌کنیم. تست واقعیِ قفل هم‌زمانی (که باید حتماً
روی PostgreSQL واقعی انجام شود) در tests/integration قرار دارد.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Query

from app.core.tenancy import set_tenant
from app.database import Base
from app import models  # noqa: F401 -- برای ثبت شدن همه مدل‌ها روی Base.metadata
from app.models import Organization
from app import models_notification  # noqa: F401


@pytest.fixture()
def db_session(monkeypatch):
    # SQLite از FOR UPDATE پشتیبانی نمی‌کند؛ برای تست‌های واحد بی‌اثرش می‌کنیم
    monkeypatch.setattr(Query, "with_for_update", lambda self, *a, **kw: self)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSessionLocal()
    # همه تست‌های واحد داخل یک سازمان آزمایشی اجرا می‌شوند (مثل یک درخواست واقعی کاربر سازمانی)
    org = Organization(name="سازمان تست", slug="test-org")
    session.add(org)
    session.commit()
    set_tenant(session, org.id)
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
