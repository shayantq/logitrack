"""خروجی سازمان روی PostgreSQL واقعی: پایان اجرا و ثبت شکست هم‌زمان فقط یک نتیجه دارند و تلاش دوباره هم‌زمان یک ردیف می‌سازد (CEL-02)."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.tenancy import set_tenant
from app.models import Organization, RoleEnum, User
from app.models_productivity import TenantExport
from app.services import platform_service
from app.services.exceptions import ConflictError
from tests.integration.conftest import TEST_DATABASE_URL
from tests.integration.test_wms_postgres import _run_parallel

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DATABASE_URL or "postgresql" not in TEST_DATABASE_URL, reason="فقط روی PostgreSQL واقعی."),
]
ROUNDS = 12
ADMINS = 6


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture()
def site():
    engine = create_engine(TEST_DATABASE_URL, pool_size=ADMINS + 2)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    org = Organization(name="سازمان خروجی", slug="export-pg-org")
    db.add(org)
    db.commit()
    set_tenant(db, None)
    admins = [User(username=f"ex_root{i}", email=f"ex{i}@test.local", role=RoleEnum.PLATFORM_ADMIN, hashed_password="x") for i in range(ADMINS)]
    db.add_all(admins)
    db.commit()
    yield factory, org.id, [a.id for a in admins]
    db.rollback()
    db.execute(text("SELECT set_config('pasineh.ledger_maintenance', 'on', true)"))
    db.query(Organization).filter(Organization.id == org.id).delete()
    db.query(User).filter(User.id.in_([a.id for a in admins])).delete(synchronize_session=False)
    db.commit()
    db.close()
    engine.dispose()


def _stale_row(factory, org_id) -> int:
    db = factory()
    started = _now() - timedelta(hours=1)
    row = TenantExport(organization_id=org_id, status="pending", created_at=started, run_token="live", started_at=started,
                       lease_until=started + platform_service._export_lease())
    db.add(row)
    db.commit()
    row_id = row.id
    db.close()
    return row_id


def test_finish_and_stale_detection_never_both_win(site):
    factory, org_id, _ = site
    for _ in range(ROUNDS):
        row_id = _stale_row(factory, org_id)

        def race(index):
            db = factory()
            try:
                if index == 0:
                    return platform_service._finish_export(db, row_id, "live", status="done", path="exports/x.zip")
                return platform_service.fail_stale_exports(db, now=_now() + timedelta(days=1), organization_id=org_id)
            finally:
                db.close()

        finished, failed = _run_parallel(2, race)
        db = factory()
        row = db.get(TenantExport, row_id)
        assert (finished, failed) in ((True, 0), (False, 1))
        assert row.status == ("done" if finished else "failed")
        assert (row.path is not None) == finished
        db.close()


def test_concurrent_retries_create_one_row(site):
    factory, org_id, admin_ids = site
    db = factory()
    failed = TenantExport(organization_id=org_id, status="failed", created_at=_now(), error="MemoryError", finished_at=_now())
    db.add(failed)
    db.commit()
    failed_id = failed.id
    db.close()

    def retry(index):
        db = factory()
        try:
            set_tenant(db, None)
            user = db.get(User, admin_ids[index])
            return platform_service.retry_export(db, user, org_id, failed_id, "خرابی worker", lambda *_: None)["id"]
        except ConflictError:
            db.rollback()
            return None
        finally:
            db.close()

    created = [r for r in _run_parallel(ADMINS, retry) if r]
    assert len(created) == 1
    db = factory()
    assert db.query(TenantExport).filter(TenantExport.retry_of_id == failed_id).count() == 1
    db.close()
