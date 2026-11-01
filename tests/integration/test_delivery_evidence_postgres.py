"""تغییرناپذیری مدرک تحویل روی PostgreSQL واقعی: تریگر UPDATE و DELETE را رد می‌کند و کلید RESTRICT جلوی حذف والد را می‌گیرد."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.core.tenancy import set_tenant
from app.models import Order, Organization, Product, RoleEnum, User, Vehicle
from app.models_productivity import DeliveryAttempt, DeliveryEvidence, DeliveryEvidenceEvent
from app.services import order_service, stock_ledger
from tests.factories import default_warehouse, order_request
from tests.integration.conftest import TEST_DATABASE_URL

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DATABASE_URL or "postgresql" not in TEST_DATABASE_URL,
                       reason="فقط روی PostgreSQL واقعی (تریگر و کلید خارجی)."),
]


@pytest.fixture()
def record():
    engine = create_engine(TEST_DATABASE_URL)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    org = Organization(name="سازمان مدرک", slug="evidence-pg-org")
    db.add(org)
    db.commit()
    set_tenant(db, org.id)
    admin = User(username="ev_admin", email="ev_admin@test.local", role=RoleEnum.ORG_ADMIN, hashed_password="x")
    driver = User(username="ev_drv", email="ev_drv@test.local", role=RoleEnum.DRIVER, hashed_password="x", city="تهران")
    product = Product(name="کالای مدرک", sku="EV-1", price=10, weight_kg=1)
    db.add_all([admin, driver, product])
    db.commit()
    warehouse = default_warehouse(db)
    vehicle = Vehicle(license_plate="EV-1", type="truck", capacity_kg=100000, status="available", driver_id=driver.id, city="تهران")
    db.add(vehicle)
    stock_ledger.record(db, stock_ledger.lock_bucket(db, product.id, warehouse.id), 5, "receipt")
    db.commit()
    order = order_service.create_order(db, admin, order_request(product.id, vehicle.id))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    attempt = DeliveryAttempt(order_id=order.id, attempt_no=1, outcome="delivered", at=now)
    db.add(attempt)
    db.commit()
    row = DeliveryEvidence(attempt_id=attempt.id, storage_key="deliveries/test/a.png", photo_type="delivery", delivery_method="left_at_door",
                           media_type="image/png", size_bytes=1, sha256="0" * 64, uploaded_by_id=admin.id, uploaded_at=now)
    db.add(row)
    db.commit()
    event = DeliveryEvidenceEvent(evidence_id=row.id, event_type="file_deleted", reason="آزمون", at=now)
    db.add(event)
    db.commit()
    data = dict(row_id=row.id, event_id=event.id, order_id=order.id, attempt_id=attempt.id, admin_id=admin.id)
    yield factory, org.id, data
    db.rollback()
    set_tenant(db, None)
    db.execute(text("SELECT set_config('pasineh.ledger_maintenance', 'on', true)"))
    db.execute(text("DELETE FROM delivery_evidence_events WHERE organization_id = :o"), {"o": org.id})
    db.execute(text("DELETE FROM delivery_evidence WHERE organization_id = :o"), {"o": org.id})
    db.query(Organization).filter(Organization.id == org.id).delete()
    db.commit()
    db.close()
    engine.dispose()


@pytest.mark.parametrize("statement", [
    "UPDATE delivery_evidence SET sha256 = 'x' WHERE id = :row_id",
    "UPDATE delivery_evidence SET delivery_method = 'other' WHERE id = :row_id",
    "DELETE FROM delivery_evidence WHERE id = :row_id",
    "UPDATE delivery_evidence_events SET reason = 'x' WHERE id = :event_id",
    "DELETE FROM delivery_evidence_events WHERE id = :event_id",
])
def test_evidence_rows_reject_changes(record, statement):
    factory, _, data = record
    db = factory()
    with pytest.raises(DBAPIError, match="immutable"):
        db.execute(text(statement), data)
    db.rollback()
    db.close()


def test_parent_attempt_cannot_be_deleted(record):
    factory, org_id, data = record
    db = factory()
    set_tenant(db, org_id)
    with pytest.raises(DBAPIError):
        db.execute(text("DELETE FROM delivery_attempts WHERE id = :attempt_id"), data)
    db.rollback()
    with pytest.raises(DBAPIError):
        db.execute(text("DELETE FROM orders WHERE id = :order_id"), data)
    db.rollback()
    assert db.get(Order, data["order_id"]) is not None
    db.close()


def test_uploader_cannot_be_deleted_at_database_level(record):
    factory, _, data = record
    db = factory()
    with pytest.raises(DBAPIError):
        db.execute(text("DELETE FROM users WHERE id = :admin_id"), data)
    db.rollback()
    db.close()
