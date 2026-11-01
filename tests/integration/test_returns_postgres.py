"""
برگشت کالا از راننده روی PostgreSQL واقعی (DL-02).

هر درخواست نشست و اتصال خودش را دارد. یک نشست نگه‌دارنده ردیف سفارش را قفل می‌کند و آزاد نمی‌شود تا pg_stat_activity نشان دهد همه
درخواست‌ها پشت همان قفل منتظرند؛ پس این آزمون‌ها همزمانی واقعی را می‌سنجند و نتیجه‌شان به زمان‌بندی ترد وابسته نیست.
"""
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.tenancy import set_tenant
from app.core.wms import AVAILABLE, PENDING
from app.models import Inventory, Order, Organization, Product, RoleEnum, StockDocument, StockMovement, User, Vehicle
from app.models_productivity import DriverReturn
from app.schemas.field import ReceiveReturnIn
from app.schemas.order import OrderStatusRequest, ResolveFailureRequest
from app.services import field_service, order_service, stock_ledger
from app.services.exceptions import ConflictError, NotFoundError
from tests.factories import default_warehouse, order_request
from tests.integration.conftest import TEST_DATABASE_URL

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DATABASE_URL or "postgresql" not in TEST_DATABASE_URL,
                       reason="فقط روی PostgreSQL واقعی (قفل ردیف)."),
]

QUANTITY = 3
STOCK = 10


@pytest.fixture()
def factory():
    engine = create_engine(TEST_DATABASE_URL, pool_size=10, max_overflow=5)
    yield sessionmaker(bind=engine, autoflush=False, autocommit=False)
    engine.dispose()


@pytest.fixture()
def shop(factory):
    db = factory()
    org = Organization(name="سازمان برگشت", slug="returns-pg-org")
    rival = Organization(name="سازمان رقیب برگشت", slug="returns-pg-rival")
    db.add_all([org, rival])
    db.commit()
    set_tenant(db, rival.id)
    rival_admin = User(username="ret_rival", email="ret_rival@test.local", role=RoleEnum.ORG_ADMIN, hashed_password="x")
    db.add(rival_admin)
    db.commit()
    rival_admin_id = rival_admin.id
    set_tenant(db, org.id)
    admin = User(username="ret_admin", email="ret_admin@test.local", role=RoleEnum.ORG_ADMIN, hashed_password="x")
    driver = User(username="ret_drv", email="ret_drv@test.local", role=RoleEnum.DRIVER, hashed_password="x", city="تهران")
    product = Product(name="کالای برگشتی", sku="RET-1", price=10, weight_kg=1)
    db.add_all([admin, driver, product])
    db.commit()
    warehouse = default_warehouse(db)
    vehicle = Vehicle(license_plate="RET-1", type="truck", capacity_kg=100000, status="available", driver_id=driver.id, city="تهران")
    db.add(vehicle)
    inventory = stock_ledger.lock_bucket(db, product.id, warehouse.id)
    stock_ledger.record(db, inventory, STOCK, "receipt")
    db.commit()
    data = {"org_id": org.id, "rival_org_id": rival.id, "rival_admin_id": rival_admin_id, "admin_id": admin.id, "product_id": product.id,
            "warehouse_id": warehouse.id, "vehicle_id": vehicle.id}
    try:
        yield data
    finally:
        db.rollback()
        set_tenant(db, None)
        db.execute(text("SELECT set_config('pasineh.ledger_maintenance', 'on', true)"))
        db.query(Organization).filter(Organization.id.in_((org.id, rival.id))).delete(synchronize_session=False)
        db.commit()
        db.close()


def _session(factory, shop):
    db = factory()
    admin = db.get(User, shop["admin_id"])
    set_tenant(db, admin.organization_id)
    return db, admin


def _failed_order(factory, shop) -> int:
    """سفارش بیرون‌رفته از انبار و ناموفق؛ هنوز تصمیمی برایش گرفته نشده است."""
    db, admin = _session(factory, shop)
    start = datetime.now(timezone.utc) - timedelta(hours=1)
    order = order_service.create_order(db, admin, order_request(shop["product_id"], shop["vehicle_id"], quantity=QUANTITY,
                                                                delivery_window_start=start, delivery_window_end=start + timedelta(hours=8)))
    order_id = order.id
    for status in ("picked_up", "in_transit"):
        order_service.update_order_status(db, admin, order_id, OrderStatusRequest(order_status=status))
    order_service.update_order_status(db, admin, order_id, OrderStatusRequest(order_status="failed", failure_reason="recipient_absent"))
    db.close()
    return order_id


def _open_return(factory, shop) -> tuple[int, int]:
    order_id = _failed_order(factory, shop)
    db, admin = _session(factory, shop)
    order_service.resolve_failure(db, admin, order_id, ResolveFailureRequest(resolution="return_to_warehouse"))
    return_id = db.query(DriverReturn.id).filter(DriverReturn.order_id == order_id).scalar()
    db.close()
    return order_id, return_id


def _count_in(shop, quantity=QUANTITY) -> ReceiveReturnIn:
    return ReceiveReturnIn(lines=[{"product_id": shop["product_id"], "received_quantity": quantity}])


def _contend(factory, shop, order_id, calls) -> list:
    """همه درخواست‌ها پشت قفل ردیف سفارش جمع می‌شوند و بعد با هم آزاد می‌شوند."""
    holder, _ = _session(factory, shop)
    holder.query(Order).filter(Order.id == order_id).with_for_update().first()
    results: list = [None] * len(calls)

    def run(index, call):
        db, admin = _session(factory, shop)
        try:
            results[index] = ("ok", call(db, admin))
        except ConflictError as e:
            db.rollback()
            results[index] = ("conflict", str(e))
        except Exception as e:  # خطای پیش‌بینی‌نشده باید آزمون را رد کند
            db.rollback()
            results[index] = ("error", repr(e))
        finally:
            db.close()

    threads = [threading.Thread(target=run, args=(i, call)) for i, call in enumerate(calls)]
    for thread in threads:
        thread.start()
    watcher = factory()
    deadline = time.monotonic() + 15
    waiting = 0
    while time.monotonic() < deadline:
        waiting = watcher.execute(text(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock'")).scalar()
        watcher.rollback()
        if waiting >= len(calls):
            break
        time.sleep(0.02)
    watcher.close()
    assert waiting >= len(calls), f"درخواست‌ها پشت قفل جمع نشدند: {waiting}"
    holder.rollback()
    holder.close()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads)
    return results


def _stock(factory, shop, status) -> int:
    db, _ = _session(factory, shop)
    row = db.query(Inventory).filter(Inventory.product_id == shop["product_id"], Inventory.warehouse_id == shop["warehouse_id"],
                                     Inventory.stock_status == status).first()
    value = row.quantity if row else 0
    db.close()
    return value


def _return_movements(factory, shop, order_id) -> list:
    db, _ = _session(factory, shop)
    rows = db.query(StockMovement.quantity_change).filter(StockMovement.movement_type == "order_return", StockMovement.reference_type == "order",
                                                          StockMovement.reference_id == order_id).all()
    db.close()
    return [quantity for (quantity,) in rows]


def test_failed_delivery_and_return_decision_add_no_stock(factory, shop):
    issued = STOCK - QUANTITY
    order_id = _failed_order(factory, shop)
    assert _stock(factory, shop, AVAILABLE) == issued and _return_movements(factory, shop, order_id) == []
    db, _ = _session(factory, shop)
    assert db.query(DriverReturn).filter(DriverReturn.order_id == order_id).count() == 0
    db.close()

    db, admin = _session(factory, shop)
    order_service.resolve_failure(db, admin, order_id, ResolveFailureRequest(resolution="return_to_warehouse"))
    db.close()
    assert _stock(factory, shop, AVAILABLE) == issued and _stock(factory, shop, PENDING) == 0
    assert _return_movements(factory, shop, order_id) == []


def test_simultaneous_counts_restock_exactly_once(factory, shop):
    order_id, return_id = _open_return(factory, shop)
    available = _stock(factory, shop, AVAILABLE)

    def count(db, admin):
        return field_service.receive_return(db, admin, order_id, return_id, _count_in(shop))["status"]

    results = _contend(factory, shop, order_id, [count, count, count])
    assert sorted(kind for kind, _ in results) == ["conflict", "conflict", "ok"], results
    assert _return_movements(factory, shop, order_id) == [QUANTITY]
    assert _stock(factory, shop, PENDING) == QUANTITY
    assert _stock(factory, shop, AVAILABLE) == available, "کالای برگشتی پیش از بازرسی موجود آزاد نمی‌شود"
    db, _ = _session(factory, shop)
    assert db.query(StockDocument).filter(StockDocument.doc_type == "order_return", StockDocument.reference_id == order_id).count() == 1
    assert db.query(Order).filter(Order.id == order_id).one().stock_state == "returned"
    db.close()


def test_conflicting_counts_keep_only_the_winner(factory, shop):
    order_id, return_id = _open_return(factory, shop)

    def full(db, admin):
        return field_service.receive_return(db, admin, order_id, return_id, _count_in(shop))["status"]

    def short(db, admin):
        data = ReceiveReturnIn(lines=[{"product_id": shop["product_id"], "received_quantity": 1, "shortage_reason": "کسری آزمون"}])
        return field_service.receive_return(db, admin, order_id, return_id, data)["status"]

    results = _contend(factory, shop, order_id, [full, short])
    assert sorted(kind for kind, _ in results) == ["conflict", "ok"], results
    movements = _return_movements(factory, shop, order_id)
    assert len(movements) == 1 and _stock(factory, shop, PENDING) == movements[0]


def test_repeat_after_success_creates_no_second_movement(factory, shop):
    order_id, return_id = _open_return(factory, shop)
    db, admin = _session(factory, shop)
    field_service.receive_return(db, admin, order_id, return_id, _count_in(shop))
    with pytest.raises(ConflictError):
        field_service.receive_return(db, admin, order_id, return_id, _count_in(shop))
    db.rollback()
    db.close()
    assert _return_movements(factory, shop, order_id) == [QUANTITY]
    assert _stock(factory, shop, PENDING) == QUANTITY


def test_simultaneous_return_decisions_open_one_return(factory, shop):
    order_id = _failed_order(factory, shop)

    def decide(db, admin):
        return order_service.resolve_failure(db, admin, order_id, ResolveFailureRequest(resolution="return_to_warehouse")).id

    results = _contend(factory, shop, order_id, [decide, decide])
    assert sorted(kind for kind, _ in results) == ["conflict", "ok"], results
    db, _ = _session(factory, shop)
    assert db.query(DriverReturn).filter(DriverReturn.order_id == order_id).count() == 1
    db.close()
    assert _return_movements(factory, shop, order_id) == []


def test_other_organization_cannot_see_or_count_the_return(factory, shop):
    order_id, return_id = _open_return(factory, shop)
    db = factory()
    rival = db.get(User, shop["rival_admin_id"])
    set_tenant(db, rival.organization_id)
    with pytest.raises(NotFoundError):
        field_service.receive_return(db, rival, order_id, return_id, _count_in(shop))
    with pytest.raises(NotFoundError):
        order_service.resolve_failure(db, rival, order_id, ResolveFailureRequest(resolution="return_to_warehouse"))
    db.rollback()
    db.close()
    assert _return_movements(factory, shop, order_id) == []
    db, _ = _session(factory, shop)
    assert db.query(DriverReturn).filter(DriverReturn.id == return_id).one().status == "open"
    db.close()
