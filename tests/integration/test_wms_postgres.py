"""
تست‌های یکپارچگی پایه انبارداری روی PostgreSQL واقعی:
  • چند رزرو هم‌زمان برای آخرین واحدها: هیچ‌وقت بیش از موجودی رزرو نمی‌شود
  • دو درخواست هم‌زمان با یک کلید یکتایی: فقط یک سند
  • تریگرهای دیتابیس جلوی ویرایش/حذف مستقیم دفتر گردش، سند قطعی و رویداد را می‌گیرند (حتی با SQL خام)
"""
import threading

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.core.tenancy import set_tenant
from app.models import Inventory, Organization, Product, RoleEnum, StockDocument, StockReservation, User
from app.schemas.product import StockMovementCreate
from app.services import allocation_service, inventory_service
from app.services.exceptions import ConflictError
from tests.factories import default_warehouse
from tests.integration.conftest import TEST_DATABASE_URL

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DATABASE_URL or "postgresql" not in TEST_DATABASE_URL,
                       reason="فقط روی PostgreSQL واقعی (قفل ردیف و تریگرها)."),
]


@pytest.fixture()
def factory():
    engine = create_engine(TEST_DATABASE_URL, pool_size=10, max_overflow=5)
    yield sessionmaker(bind=engine, autoflush=False, autocommit=False)
    engine.dispose()


@pytest.fixture()
def stock(factory):
    db = factory()
    org = Organization(name="سازمان آزمون WMS", slug="wms-pg-org")
    db.add(org)
    db.commit()
    set_tenant(db, org.id)
    admin = User(username="wms_pg_admin", email="wms_pg@test.local", role=RoleEnum.ORG_ADMIN, hashed_password="x")
    product = Product(name="کالای رقابتی", sku="WMS-RACE", price=1, weight_kg=1)
    db.add_all([admin, product])
    db.commit()
    warehouse = default_warehouse(db)
    db.add(Inventory(product_id=product.id, warehouse_id=warehouse.id, quantity=3))
    db.commit()
    data = {"org_id": org.id, "admin_id": admin.id, "product_id": product.id, "warehouse_id": warehouse.id}
    try:
        yield data
    finally:
        db.rollback()
        set_tenant(db, None)
        db.execute(text("SELECT set_config('pasineh.ledger_maintenance', 'on', true)"))
        db.query(Organization).filter(Organization.id == org.id).delete()
        db.commit()
        db.close()


def _run_parallel(n, target):
    barrier = threading.Barrier(n)
    results = [None] * n

    def run(i):
        barrier.wait()
        results[i] = target(i)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    return results


def test_concurrent_reservations_never_exceed_stock(factory, stock):
    def reserve(i):
        db = factory()
        try:
            set_tenant(db, stock["org_id"])
            [inv] = allocation_service.lock_inventories(db, [
                db.query(Inventory.id).filter(Inventory.product_id == stock["product_id"]).scalar()]).values()
            allocation_service.reserve(db, inv, 1, reference_type="test", reference_id=i)
            db.commit()
            return "ok"
        except ConflictError:
            db.rollback()
            return "short"
        finally:
            db.close()

    results = _run_parallel(6, reserve)
    assert results.count("ok") == 3 and results.count("short") == 3, results
    db = factory()
    inv = db.query(Inventory).filter(Inventory.product_id == stock["product_id"]).one()
    assert (inv.quantity, inv.reserved_quantity) == (3, 3)
    assert db.query(StockReservation).filter(StockReservation.product_id == stock["product_id"]).count() == 3
    db.close()


def test_concurrent_requests_with_same_idempotency_key_post_once(factory, stock):
    def receive(i):
        db = factory()
        try:
            admin = db.get(User, stock["admin_id"])
            set_tenant(db, admin.organization_id)
            movement = inventory_service.record_movement(db, admin, StockMovementCreate(
                product_id=stock["product_id"], warehouse_id=stock["warehouse_id"], movement_type="receipt", quantity=5),
                idempotency_key="pg-receipt-key-1")
            return movement.document_id
        finally:
            db.close()

    document_ids = _run_parallel(4, receive)
    assert len(set(document_ids)) == 1, document_ids
    db = factory()
    assert db.query(StockDocument).filter(StockDocument.idempotency_key == "pg-receipt-key-1").count() == 1
    assert db.query(Inventory).filter(Inventory.product_id == stock["product_id"]).one().quantity == 8
    db.close()


@pytest.mark.parametrize("sql", [
    "UPDATE stock_movements SET quantity_change = 99",
    "DELETE FROM stock_movements",
    "UPDATE stock_documents SET note = 'بازنویسی'",
    "DELETE FROM stock_documents",
    "UPDATE domain_events SET event_type = 'x'",
    "DELETE FROM domain_events",
])
def test_database_triggers_block_raw_sql_rewrites(factory, stock, sql):
    db = factory()
    try:
        with pytest.raises(DBAPIError, match="immutable|cannot be deleted"):
            db.execute(text(sql))
    finally:
        db.rollback()
        db.close()
