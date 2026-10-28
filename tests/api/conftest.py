"""
Fixture مشترک تست‌های سطح API: اپ واقعی FastAPI روی SQLite درون‌حافظه‌ای
با StaticPool (تا ترد TestClient و ترد تست یک اتصال مشترک ببینند).
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Query
from sqlalchemy.pool import StaticPool

from app.core.rate_limit import login_failure_limiter
from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def api_env(monkeypatch):
    """(TestClient, SessionFactory) — دیتابیس خالی، بدون هیچ سازمانی."""
    monkeypatch.setattr(Query, "with_for_update", lambda self, *a, **kw: self)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    login_failure_limiter.reset()
    try:
        yield TestClient(app), TestingSession
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
