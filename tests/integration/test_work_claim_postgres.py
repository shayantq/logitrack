"""برداشتن کار روی PostgreSQL واقعی: از چند اپراتور همزمان فقط یکی کار را می‌گیرد (ت۱۸)."""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.tenancy import set_tenant
from app.models import Organization, Product, RoleEnum, User
from app.models_operations import PutawayTask
from app.services import work_claim_service
from app.services.exceptions import ConflictError
from tests.factories import default_warehouse
from tests.integration.conftest import TEST_DATABASE_URL
from tests.integration.test_wms_postgres import _run_parallel

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DATABASE_URL or "postgresql" not in TEST_DATABASE_URL, reason="فقط روی PostgreSQL واقعی."),
]
OPERATORS = 6


@pytest.fixture()
def site():
    engine = create_engine(TEST_DATABASE_URL, pool_size=OPERATORS + 2)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    org = Organization(name="سازمان برداشتن", slug="claim-pg-org")
    db.add(org)
    db.commit()
    set_tenant(db, org.id)
    warehouse = default_warehouse(db)
    users = [User(username=f"cl_op{i}", email=f"cl{i}@test.local", role=RoleEnum.WAREHOUSE_OPERATOR, hashed_password="x", warehouse_id=warehouse.id) for i in range(OPERATORS)]
    product = Product(name="کالا", sku="CL-1", price=1, weight_kg=1)
    db.add_all([*users, product])
    db.commit()
    task = PutawayTask(code="CL-TASK", warehouse_id=warehouse.id, product_id=product.id, stock_status="available", quantity=1, status="open")
    db.add(task)
    db.commit()
    data = (factory, org.id, [u.id for u in users], task.id)
    yield data
    db.rollback()
    set_tenant(db, None)
    db.execute(text("SELECT set_config('pasineh.ledger_maintenance', 'on', true)"))
    db.query(Organization).filter(Organization.id == org.id).delete()
    db.commit()
    db.close()
    engine.dispose()


def test_only_one_operator_gets_the_task(site):
    factory, org_id, user_ids, task_id = site

    def claim(index):
        db = factory()
        try:
            set_tenant(db, org_id)
            user = db.get(User, user_ids[index])
            work_claim_service.claim(db, user, PutawayTask, task_id, ("open", "partial"))
            return user.id
        except ConflictError:
            db.rollback()
            return None
        finally:
            db.close()

    winners = [w for w in _run_parallel(OPERATORS, claim) if w]
    assert len(winners) == 1
    db = factory()
    set_tenant(db, org_id)
    assert db.get(PutawayTask, task_id).claimed_by_id == winners[0]
    db.close()
