"""
تست‌های یکپارچگی کنترل روی PostgreSQL واقعی:
  • گزارش فعالیت با SQL مستقیم هم ویرایش یا حذف نمی‌شود (فقط خالی شدن انجام‌دهنده هنگام حذف کاربر)
  • حذف سازمان، گزارش فعالیتش را هم پاک می‌کند (آبشاری)
"""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.core.tenancy import set_tenant
from app.models import AuditLog, Organization, RoleEnum, User
from app.services import audit_service
from tests.integration.conftest import TEST_DATABASE_URL

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DATABASE_URL or "postgresql" not in TEST_DATABASE_URL,
                       reason="فقط روی PostgreSQL واقعی (تریگر)."),
]


@pytest.fixture()
def factory():
    engine = create_engine(TEST_DATABASE_URL)
    yield sessionmaker(bind=engine, autoflush=False, autocommit=False)
    engine.dispose()


@pytest.fixture()
def logged(factory):
    db = factory()
    org = Organization(name="سازمان ممیزی", slug="audit-pg-org")
    db.add(org)
    db.commit()
    set_tenant(db, org.id)
    admin = User(username="audit_pg_admin", email="audit_pg@test.local", role=RoleEnum.ORG_ADMIN, hashed_password="x")
    clerk = User(username="audit_pg_clerk", email="audit_pg_c@test.local", role=RoleEnum.WAREHOUSE_MANAGER, hashed_password="x")
    db.add_all([admin, clerk])
    db.commit()
    audit_service.log(db, clerk, "stock.adjust", "اصلاح موجودی", reason="شکستگی")
    db.commit()
    data = {"org_id": org.id, "clerk_id": clerk.id}
    db.close()
    yield data
    db = factory()
    db.execute(text("DELETE FROM organizations WHERE id = :id"), {"id": data["org_id"]})
    db.commit()
    db.close()


@pytest.mark.parametrize("sql", [
    "UPDATE audit_logs SET summary = 'بازنویسی'",
    "UPDATE audit_logs SET reason = NULL",
    "DELETE FROM audit_logs",
])
def test_audit_rows_cannot_be_rewritten(factory, logged, sql):
    db = factory()
    try:
        with pytest.raises(DBAPIError, match="immutable"):
            db.execute(text(sql))
    finally:
        db.rollback()
        db.close()


def test_deleting_user_keeps_log_with_name_and_org_delete_cascades(factory, logged):
    db = factory()
    db.execute(text("DELETE FROM users WHERE id = :id"), {"id": logged["clerk_id"]})
    db.commit()
    row = db.query(AuditLog).filter(AuditLog.organization_id == logged["org_id"]).one()
    assert row.actor_id is None and row.actor_name == "audit_pg_clerk" and row.reason == "شکستگی"
    db.execute(text("DELETE FROM organizations WHERE id = :id"), {"id": logged["org_id"]})
    db.commit()
    assert db.query(AuditLog).filter(AuditLog.organization_id == logged["org_id"]).count() == 0
    db.close()
