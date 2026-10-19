"""
تست‌های دفتر گردش کالا (Stock Ledger)

قانون اصلی که بعد از هر عملیات بررسی می‌شود:
    مانده هر ردیف موجودی == مجموع گردش‌هایش == balance_after آخرین گردش
"""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.models import Inventory, Order, Product, RoleEnum, StockMovement, User, Vehicle, Warehouse
from app.schemas.order import OrderRequest, OrderStatusRequest
from app.schemas.product import ProductCreate, StockMovementCreate, StockTransferCreate, StockUpdate
from app.services import inventory_service, order_service, stock_ledger
from app.services.exceptions import ConflictError, ForbiddenError
from app.services.stock_ledger import LedgerViolationError
from tests.factories import order_request, order_payload


def _user(db, role, tag, warehouse_id=None):
    user = User(username=f"{role.value}_{tag}", email=f"{tag}@test.local", role=role,
                hashed_password="x", warehouse_id=warehouse_id, city="تهران")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _assert_ledger_consistent(db):
    assert stock_ledger.find_mismatches(db) == []
    for inv in db.query(Inventory).all():
        last = db.query(StockMovement).filter(StockMovement.inventory_id == inv.id).order_by(StockMovement.id.desc()).first()
        assert (last.balance_after if last else 0) == inv.quantity


def _movements(db, product_id, warehouse_id=None):
    query = db.query(StockMovement).filter(StockMovement.product_id == product_id)
    if warehouse_id is not None:
        query = query.filter(StockMovement.warehouse_id == warehouse_id)
    return query.order_by(StockMovement.id).all()


def _qty(db, product_id, warehouse_id):
    inv = db.query(Inventory).filter(Inventory.product_id == product_id, Inventory.warehouse_id == warehouse_id).one()
    db.refresh(inv)
    return inv.quantity


@pytest.fixture()
def world(db_session):
    db = db_session
    wh1, wh2 = Warehouse(name="انبار ۱", location="تهران"), Warehouse(name="انبار ۲", location="کرج")
    db.add_all([wh1, wh2])
    db.commit()
    admin = _user(db, RoleEnum.ORG_ADMIN, "admin")
    manager = _user(db, RoleEnum.WAREHOUSE_MANAGER, "mgr", warehouse_id=wh1.id)
    driver = _user(db, RoleEnum.DRIVER, "drv")
    vehicle = Vehicle(license_plate="LEDGER-1", type="van", capacity_kg=5000, status="available", driver_id=driver.id, city="تهران")
    db.add(vehicle)
    db.commit()
    product = inventory_service.create_product(
        db, admin, ProductCreate(name="کالای دفتر", sku="LEDGER-SKU", price=10, initial_quantity=20, warehouse_id=wh1.id)
    )
    return db, wh1, wh2, admin, manager, driver, vehicle, product


def _order(product_id, vehicle_id, quantity):
    return order_request(product_id, vehicle_id, quantity=quantity)


# ---------------------------------------------------------------------------
# هر عملیات یک گردش با نوع، مقدار، مانده، کاربر و مرجع درست ثبت می‌کند
# ---------------------------------------------------------------------------

def test_create_product_records_initial_movement(world):
    db, wh1, wh2, admin, *_, product = world
    [movement] = _movements(db, product.id)
    assert (movement.movement_type, movement.quantity_change, movement.balance_after) == ("initial", 20, 20)
    assert movement.created_by_id == admin.id
    _assert_ledger_consistent(db)


def test_full_order_lifecycle_is_recorded(world):
    db, wh1, wh2, admin, manager, driver, vehicle, product = world

    order = order_service.create_order(db, admin, _order(product.id, vehicle.id, 5))
    order_service.update_order_status(db, driver, order.id, OrderStatusRequest(order_status="failed"))

    out, back = _movements(db, product.id)[1:]
    assert (out.movement_type, out.quantity_change, out.balance_after) == ("order_out", -5, 15)
    assert (out.reference_type, out.reference_id) == ("order", order.id)
    assert (back.movement_type, back.quantity_change, back.balance_after) == ("order_return", 5, 20)
    assert back.created_by_id == driver.id
    _assert_ledger_consistent(db)


def test_deleting_active_order_records_return(world):
    db, wh1, wh2, admin, manager, driver, vehicle, product = world
    order = order_service.create_order(db, admin, _order(product.id, vehicle.id, 3))
    order_service.delete_order(db, admin, order.id)

    last = _movements(db, product.id)[-1]
    assert (last.movement_type, last.quantity_change, last.reference_id) == ("order_return", 3, order.id)
    assert _qty(db, product.id, wh1.id) == 20
    _assert_ledger_consistent(db)


def test_update_stock_records_difference_as_adjustment(world):
    db, wh1, wh2, admin, manager, *_, product = world
    inventory_service.update_stock(db, manager, product.id, StockUpdate(quantity=17, reason="شمارش پایان روز"))
    last = _movements(db, product.id)[-1]
    assert (last.movement_type, last.quantity_change, last.balance_after, last.reason) == ("adjustment", -3, 17, "شمارش پایان روز")

    # اگر عدد تغییری نکند، گردش بی‌معنی ثبت نمی‌شود
    inventory_service.update_stock(db, manager, product.id, StockUpdate(quantity=17))
    assert len(_movements(db, product.id)) == 2
    _assert_ledger_consistent(db)


def test_receipt_damage_and_adjustment(world):
    db, wh1, wh2, admin, manager, *_, product = world
    inventory_service.record_movement(db, manager, StockMovementCreate(product_id=product.id, movement_type="receipt", quantity=30))
    inventory_service.record_movement(db, manager, StockMovementCreate(product_id=product.id, movement_type="damage", quantity=4, reason="شکستگی"))
    inventory_service.record_movement(db, manager, StockMovementCreate(product_id=product.id, movement_type="adjustment", quantity=-1, reason="اشتباه ثبت"))

    changes = [(m.movement_type, m.quantity_change, m.balance_after) for m in _movements(db, product.id)]
    assert changes == [("initial", 20, 20), ("receipt", 30, 50), ("damage", -4, 46), ("adjustment", -1, 45)]
    _assert_ledger_consistent(db)


def test_stock_can_never_go_negative(world):
    db, wh1, wh2, admin, manager, *_, product = world
    with pytest.raises(ConflictError):
        inventory_service.record_movement(db, manager, StockMovementCreate(product_id=product.id, movement_type="damage", quantity=21, reason="تست"))
    assert _qty(db, product.id, wh1.id) == 20
    assert len(_movements(db, product.id)) == 1
    _assert_ledger_consistent(db)


def test_transfer_between_warehouses(world):
    db, wh1, wh2, admin, manager, *_, product = world
    out_move, in_move = inventory_service.transfer_stock(
        db, manager, StockTransferCreate(product_id=product.id, from_warehouse_id=wh1.id, to_warehouse_id=wh2.id, quantity=8)
    )
    assert _qty(db, product.id, wh1.id) == 12
    assert _qty(db, product.id, wh2.id) == 8   # ردیف مقصد خودکار ساخته شد
    assert (out_move.movement_type, out_move.quantity_change) == ("transfer_out", -8)
    assert (in_move.movement_type, in_move.quantity_change) == ("transfer_in", 8)
    assert out_move.reference_id == in_move.reference_id == out_move.id
    _assert_ledger_consistent(db)


def test_transfer_rules(world):
    db, wh1, wh2, admin, manager, *_, product = world
    with pytest.raises(ConflictError):  # بیشتر از موجودی مبدأ
        inventory_service.transfer_stock(db, admin, StockTransferCreate(product_id=product.id, from_warehouse_id=wh1.id, to_warehouse_id=wh2.id, quantity=99))
    with pytest.raises(ForbiddenError):  # مدیر انبار ۱ نمی‌تواند از انبار ۲ منتقل کند
        inventory_service.transfer_stock(db, manager, StockTransferCreate(product_id=product.id, from_warehouse_id=wh2.id, to_warehouse_id=wh1.id, quantity=1))
    with pytest.raises(ValidationError):
        StockTransferCreate(product_id=product.id, from_warehouse_id=wh1.id, to_warehouse_id=wh1.id, quantity=1)
    _assert_ledger_consistent(db)


def test_movement_input_validation():
    with pytest.raises(ValidationError):
        StockMovementCreate(product_id=1, movement_type="damage", quantity=2)            # بدون دلیل
    with pytest.raises(ValidationError):
        StockMovementCreate(product_id=1, movement_type="receipt", quantity=-5)          # ورود منفی
    with pytest.raises(ValidationError):
        StockMovementCreate(product_id=1, movement_type="adjustment", quantity=0, reason="صفر")
    with pytest.raises(ValidationError):
        StockMovementCreate(product_id=1, movement_type="order_out", quantity=1)         # فقط توسط سیستم


# ---------------------------------------------------------------------------
# محافظ لایه داده
# ---------------------------------------------------------------------------

def test_direct_quantity_change_is_blocked(world):
    db, wh1, *_ , product = world
    inv = db.query(Inventory).filter(Inventory.product_id == product.id).one()
    inv.quantity = 999
    with pytest.raises(LedgerViolationError):
        db.commit()
    db.rollback()
    assert _qty(db, product.id, wh1.id) == 20


def test_inventory_created_directly_gets_opening_movement(world):
    db, wh1, wh2, *_ = world
    product = Product(name="مستقیم", sku="DIRECT", price=1)
    db.add(product)
    db.commit()
    db.add(Inventory(product_id=product.id, warehouse_id=wh2.id, quantity=7))
    db.commit()

    [movement] = _movements(db, product.id)
    assert (movement.movement_type, movement.quantity_change, movement.balance_after) == ("initial", 7, 7)
    _assert_ledger_consistent(db)


def test_listing_is_scoped_for_manager(world):
    db, wh1, wh2, admin, manager, *_, product = world
    inventory_service.transfer_stock(db, admin, StockTransferCreate(product_id=product.id, from_warehouse_id=wh1.id, to_warehouse_id=wh2.id, quantity=2))

    manager_view = inventory_service.list_movements(db, manager)
    assert {m.warehouse_id for m in manager_view} == {wh1.id}
    admin_view = inventory_service.list_movements(db, admin, warehouse_id=wh2.id)
    assert [m.movement_type for m in admin_view] == ["transfer_in"]
    assert [m.movement_type for m in inventory_service.list_movements(db, admin, movement_type="initial")] == ["initial"]

    with pytest.raises(ForbiddenError):
        inventory_service.ledger_check(db, manager)
    assert inventory_service.ledger_check(db, admin) == {"ok": True, "mismatches": []}
