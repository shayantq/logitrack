"""
یافته‌های بار آزمایشی (ت۱۷) روی PostgreSQL واقعی:
  • برداشت همزمان یک کالا به محل آماده‌سازی نباید بن‌بست بدهد.
  • جمع‌زدن تقاضا در دیتابیس باید همان نتیجه محاسبه در پایتون را بدهد، حتی نزدیک نیمه‌شب ایران.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.tenancy import set_tenant
from app.models import Organization, Product, RoleEnum, User
from app.models_operations import Location
from app.schemas.fulfillment import PickIn, PickListCreate
from app.services import order_service, picking_service, replenishment_service, stock_ledger
from tests.factories import default_warehouse, order_request
from tests.integration.conftest import TEST_DATABASE_URL
from tests.integration.test_wms_postgres import _run_parallel

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DATABASE_URL or "postgresql" not in TEST_DATABASE_URL,
                       reason="فقط روی PostgreSQL واقعی (قفل ردیف)."),
]
PARALLEL = 8


@pytest.fixture()
def shop():
    engine = create_engine(TEST_DATABASE_URL, pool_size=12, max_overflow=4)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    org = Organization(name="سازمان برداشت", slug="pick-load-org")
    db.add(org)
    db.commit()
    set_tenant(db, org.id)
    admin = User(username="pl_admin", email="pl_admin@test.local", role=RoleEnum.ORG_ADMIN, hashed_password="x")
    product = Product(name="کالای برداشت", sku="PL-1", price=10, weight_kg=1)
    db.add_all([admin, product])
    db.commit()
    warehouse = default_warehouse(db)
    staging = Location(warehouse_id=warehouse.id, code="PL-STG", barcode="PL-STG", level="bin", location_type="staging")
    db.add(staging)
    inventory = stock_ledger.lock_bucket(db, product.id, warehouse.id)
    stock_ledger.record(db, inventory, 200, "receipt")
    db.commit()
    data = dict(admin_id=admin.id, product_id=product.id, warehouse_id=warehouse.id, warehouse_code=warehouse.code, staging_id=staging.id, org_id=org.id, inventory_id=inventory.id)
    yield factory, data
    db.rollback()
    set_tenant(db, None)
    db.execute(text("SELECT set_config('pasineh.ledger_maintenance', 'on', true)"))
    db.query(Organization).filter(Organization.id == org.id).delete()
    db.commit()
    db.close()
    engine.dispose()


def _session(factory, data):
    db = factory()
    admin = db.get(User, data["admin_id"])
    set_tenant(db, data["org_id"])
    return db, admin


def test_simultaneous_picks_to_staging_do_not_deadlock(shop):
    factory, data = shop
    db, admin = _session(factory, data)
    lines = []
    for index in range(PARALLEL):
        order = order_service.create_order(db, admin, order_request(data["product_id"], None, mobile=f"0912000000{index}", auto_assign=False))
        pick_list = picking_service.create_pick_list(db, admin, PickListCreate(warehouse_id=data["warehouse_id"], strategy="single",
                                                                               order_ids=[order.id], staging_location_id=data["staging_id"]))
        lines.extend(line["id"] for line in pick_list["lines"])
    db.close()

    def pick(index):
        session, user = _session(factory, data)
        try:
            picking_service.pick(session, user, lines[index], PickIn(source_scan=data["warehouse_code"], product_scan="PL-1", quantity=1))
            return "ok"
        except Exception as error:
            session.rollback()
            return type(getattr(error, "orig", error)).__name__
        finally:
            session.close()

    results = _run_parallel(len(lines), pick)
    assert results == ["ok"] * len(lines), results


def test_database_daily_demand_matches_the_python_calculation(shop):
    factory, data = shop
    db, _ = _session(factory, data)
    inventory_id = data["inventory_id"]
    moves = [(datetime(2026, 3, 1, 20, 0), -2), (datetime(2026, 3, 1, 20, 29), -1), (datetime(2026, 3, 1, 20, 31), -4),
             (datetime(2026, 3, 2, 8, 0), -5), (datetime(2026, 3, 2, 9, 0), 1)]
    document = stock_ledger.new_document(db, "adjustment", organization_id=data["org_id"], warehouse_id=data["warehouse_id"], note="آزمون تقاضا")
    db.flush()
    for at, change in moves:
        db.execute(text("""
            INSERT INTO stock_movements (organization_id, document_id, inventory_id, product_id, warehouse_id, stock_status, movement_type, quantity_change, balance_after, created_at)
            VALUES (:o, :d, :i, :p, :w, 'available', :t, :c, 0, :at)
        """), dict(o=data["org_id"], d=document.id, i=inventory_id, p=data["product_id"], w=data["warehouse_id"], t="order_out" if change < 0 else "order_return", c=change, at=at))
    db.commit()
    expected: dict = defaultdict(float)
    for at, change in moves:
        expected[(at + timedelta(hours=3, minutes=30)).date()] -= change
    result = replenishment_service.daily_demand(db, [inventory_id], date(2026, 3, 1), date(2026, 3, 3))
    assert dict(result[inventory_id]) == dict(expected)
    db.close()
