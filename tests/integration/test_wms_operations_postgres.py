"""
تست‌های یکپارچگی عملیات انبار روی PostgreSQL واقعی:
  • دو جانمایی هم‌زمان در محلی با ظرفیت یک پالت: فقط یکی جا می‌شود (قفل ردیف محل)
  • چند دریافت هم‌زمان یک رسید: اضافه تحویل از حد مجاز رد نمی‌شود (قفل ردیف رسید)
  • یک شماره سریال هم‌زمان در دو انبار: فقط یک‌بار در موجودی می‌نشیند (ایندکس یکتای جزئی)
  • تریگر دیتابیس جلوی ویرایش/حذف مستقیم ردیف‌های ریز گردش را می‌گیرد
"""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.tenancy import set_tenant
from app.models import Location, Organization, Product, RoleEnum, StockBalance, User, Warehouse
from app.schemas.operations import ReceiptCreate, ReceiveIn
from app.schemas.product import LocationMoveCreate, StockMovementCreate
from app.services import inventory_service, receiving_service, stock_ledger
from app.services.exceptions import ConflictError
from tests.integration.conftest import TEST_DATABASE_URL
from tests.integration.test_wms_postgres import _run_parallel

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DATABASE_URL or "postgresql" not in TEST_DATABASE_URL,
                       reason="فقط روی PostgreSQL واقعی (قفل ردیف، ایندکس جزئی و تریگرها)."),
]


@pytest.fixture()
def factory():
    engine = create_engine(TEST_DATABASE_URL, pool_size=10, max_overflow=5)
    yield sessionmaker(bind=engine, autoflush=False, autocommit=False)
    engine.dispose()


@pytest.fixture()
def site(factory):
    db = factory()
    org = Organization(name="سازمان آزمون عملیات", slug="wms-ops-pg-org")
    db.add(org)
    db.commit()
    set_tenant(db, org.id)
    admin = User(username="wms_ops_admin", email="wms_ops@test.local", role=RoleEnum.ORG_ADMIN, hashed_password="x")
    main = Warehouse(name="اصلی", code="OPS-1", city="تهران", province="تهران")
    second = Warehouse(name="دوم", code="OPS-2", city="تهران", province="تهران")
    product = Product(name="پالت‌دار", sku="OPS-PLT", price=1, weight_kg=1, units_per_pallet=5)
    serial = Product(name="سریال‌دار", sku="OPS-SER", price=1, weight_kg=1, serial_tracked=True)
    from app.models import Partner
    supplier = Partner(code="SUP-OPS", name="تأمین‌کننده", is_supplier=True)
    db.add_all([admin, main, second, product, serial, supplier])
    db.commit()
    bin_ = Location(warehouse_id=main.id, level="bin", code="B-1", barcode="OPS-1-B-1", location_type="storage", max_pallets=1)
    db.add(bin_)
    db.commit()
    inv = stock_ledger.lock_bucket(db, product.id, main.id)
    stock_ledger.record(db, inv, 10, "receipt")
    db.commit()
    data = {"org_id": org.id, "admin_id": admin.id, "main": main.id, "second": second.id, "product": product.id,
            "serial": serial.id, "bin": bin_.id, "supplier": supplier.id}
    try:
        yield data
    finally:
        db.rollback()
        set_tenant(db, None)
        db.execute(text("SELECT set_config('pasineh.ledger_maintenance', 'on', true)"))
        db.query(Organization).filter(Organization.id == org.id).delete()
        db.commit()
        db.close()


def _session(factory, site):
    db = factory()
    admin = db.get(User, site["admin_id"])
    set_tenant(db, admin.organization_id)
    return db, admin


def test_concurrent_putaway_respects_location_capacity(factory, site):
    def move(i):
        db, admin = _session(factory, site)
        try:
            inventory_service.move_between_locations(db, admin, LocationMoveCreate(
                product_id=site["product"], warehouse_id=site["main"], to_location_id=site["bin"], quantity=5))
            return "ok"
        except ConflictError:
            return "full"
        finally:
            db.close()

    results = _run_parallel(2, move)
    assert sorted(results) == ["full", "ok"], results
    db, _ = _session(factory, site)
    assert db.query(StockBalance).filter(StockBalance.location_id == site["bin"]).one().quantity == 5
    assert stock_ledger.find_mismatches(db) == []
    db.close()


def test_concurrent_receives_cannot_overshoot_expected_quantity(factory, site):
    db, admin = _session(factory, site)
    receipt = receiving_service.create_receipt(db, admin, ReceiptCreate(
        receipt_type="purchase", warehouse_id=site["main"], partner_id=site["supplier"],
        lines=[{"product_id": site["product"], "expected_quantity": 5}]))
    db.close()

    def receive(i):
        db, admin = _session(factory, site)
        try:
            receiving_service.receive(db, admin, receipt["id"], ReceiveIn(
                lines=[{"line_id": receipt["lines"][0]["id"], "quantity": 3}]))
            return "ok"
        except ConflictError:
            return "over"
        finally:
            db.close()

    results = _run_parallel(3, receive)
    assert results.count("ok") == 1, results
    db, admin = _session(factory, site)
    assert receiving_service.get_receipt(db, admin, receipt["id"])["lines"][0]["received_quantity"] == 3
    db.close()


def test_same_serial_cannot_enter_stock_twice_concurrently(factory, site):
    def receive(i):
        db, admin = _session(factory, site)
        try:
            inventory_service.record_movement(db, admin, StockMovementCreate(
                product_id=site["serial"], warehouse_id=site["main"] if i == 0 else site["second"],
                movement_type="receipt", quantity=1, serial_numbers=["SN-RACE-1"]))
            return "ok"
        except (ConflictError, IntegrityError):
            return "duplicate"
        finally:
            db.close()

    results = _run_parallel(2, receive)
    assert sorted(results) == ["duplicate", "ok"], results
    db, _ = _session(factory, site)
    assert db.query(StockBalance).filter(StockBalance.serial_number == "SN-RACE-1", StockBalance.quantity > 0).count() == 1
    db.close()


@pytest.mark.parametrize("sql", [
    "UPDATE stock_movement_lines SET quantity_change = 99",
    "DELETE FROM stock_movement_lines",
])
def test_trigger_blocks_raw_rewrites_of_movement_lines(factory, site, sql):
    db = factory()
    try:
        with pytest.raises(DBAPIError, match="immutable"):
            db.execute(text(sql))
    finally:
        db.rollback()
        db.close()
