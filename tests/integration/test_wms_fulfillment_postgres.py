"""
تست‌های یکپارچگی اجرای سفارش روی PostgreSQL واقعی:
  • چند تخصیص هم‌زمان سفارش‌های معوق هرگز بیش از موجودی قابل وعده رزرو نمی‌کند
  • ثبت هم‌زمان سفارش‌های «با پذیرش معوق»: مجموع رزروها = موجودی، بقیه معوق (هیچ مقداری گم نمی‌شود)
"""
import pytest
from sqlalchemy import create_engine, func, text
from sqlalchemy.orm import sessionmaker

from app.core.tenancy import set_tenant
from app.models import Backorder, Inventory, Organization, Product, RoleEnum, StockReservation, User, Vehicle
from app.services import backorder_service, order_service, stock_ledger
from app.services.exceptions import ConflictError
from tests.factories import default_warehouse, order_request
from tests.integration.conftest import TEST_DATABASE_URL
from tests.integration.test_wms_postgres import _run_parallel

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DATABASE_URL or "postgresql" not in TEST_DATABASE_URL,
                       reason="فقط روی PostgreSQL واقعی (قفل ردیف)."),
]


@pytest.fixture()
def factory():
    engine = create_engine(TEST_DATABASE_URL, pool_size=10, max_overflow=5)
    yield sessionmaker(bind=engine, autoflush=False, autocommit=False)
    engine.dispose()


@pytest.fixture()
def shop(factory):
    db = factory()
    org = Organization(name="سازمان آزمون ارسال", slug="wms-ful-pg-org")
    db.add(org)
    db.commit()
    set_tenant(db, org.id)
    admin = User(username="wms_ful_admin", email="wms_ful@test.local", role=RoleEnum.ORG_ADMIN, hashed_password="x")
    driver = User(username="wms_ful_drv", email="wms_ful_drv@test.local", role=RoleEnum.DRIVER, hashed_password="x", city="تهران")
    product = Product(name="کالای پرتقاضا", sku="FUL-HOT", price=10, weight_kg=1)
    db.add_all([admin, driver, product])
    db.commit()
    warehouse = default_warehouse(db)
    vehicle = Vehicle(license_plate="FUL-1", type="truck", capacity_kg=100000, status="available", driver_id=driver.id, city="تهران")
    db.add(vehicle)
    inventory = stock_ledger.lock_bucket(db, product.id, warehouse.id)
    stock_ledger.record(db, inventory, 6, "receipt")
    db.commit()
    data = {"org_id": org.id, "admin_id": admin.id, "product_id": product.id, "warehouse_id": warehouse.id,
            "vehicle_id": vehicle.id}
    try:
        yield data
    finally:
        db.rollback()
        set_tenant(db, None)
        db.execute(text("SELECT set_config('pasineh.ledger_maintenance', 'on', true)"))
        db.query(Organization).filter(Organization.id == org.id).delete()
        db.commit()
        db.close()


def _session(factory, shop):
    db = factory()
    admin = db.get(User, shop["admin_id"])
    set_tenant(db, admin.organization_id)
    return db, admin


def test_concurrent_backorder_orders_never_overbook(factory, shop):
    def place(i):
        db, admin = _session(factory, shop)
        try:
            order = order_service.create_order(db, admin, order_request(shop["product_id"], shop["vehicle_id"], quantity=2,
                                                                        allow_backorder=True, mobile=f"0912000000{i}"))
            return sum(item.quantity for item in order.items)
        except ConflictError:
            return 0
        finally:
            db.close()

    reserved = _run_parallel(5, place)
    db, _ = _session(factory, shop)
    assert sum(reserved) == 6
    inventory = db.query(Inventory).filter(Inventory.product_id == shop["product_id"]).one()
    assert inventory.reserved_quantity == 6
    backordered = db.query(func.coalesce(func.sum(Backorder.quantity), 0)).scalar()
    # هر سفارشی که ثبت شد، باقی‌مانده‌اش معوق ثبت شده است (چیزی دور ریخته نشد)
    placed = sum(1 for r in reserved if r)
    assert backordered == placed * 2 - 6
    db.close()


def test_concurrent_backorder_allocation_respects_stock(factory, shop):
    db, admin = _session(factory, shop)
    order = order_service.create_order(db, admin, order_request(shop["product_id"], shop["vehicle_id"], quantity=6))
    product = db.get(Product, shop["product_id"])
    for _ in range(4):
        backorder_service.open_backorder(db, admin, order, product, 3, 10)
    db.commit()
    # موجودی تازه: ۷ عدد
    inventory = stock_ledger.lock_bucket(db, shop["product_id"], shop["warehouse_id"])
    stock_ledger.record(db, inventory, 7, "receipt")
    db.commit()
    db.close()

    def allocate(i):
        db, admin = _session(factory, shop)
        try:
            return backorder_service.allocate(db, admin)["allocated_quantity"]
        finally:
            db.close()

    results = _run_parallel(3, allocate)
    db, _ = _session(factory, shop)
    assert sum(results) == 7
    active = db.query(func.sum(StockReservation.quantity)).filter(StockReservation.reference_type == "backorder",
                                                                  StockReservation.status == "active").scalar()
    assert active == 7
    assert stock_ledger.find_mismatches(db) == []
    db.close()

