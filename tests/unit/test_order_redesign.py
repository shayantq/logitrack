"""
تست‌های مرحله ۴: سفارش چندقلمی، مشتری و آدرس، کد پیگیری، تخصیص خودرو
پس از ثبت، ماشین وضعیت جدید، تاریخچه وضعیت و انقضای خودکار.
"""
import re
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import sessionmaker

from app import tasks
from app.models import (
    Customer, Inventory, Order, OrderStatusHistory, Product, RoleEnum, StockMovement, User, Vehicle, Warehouse,
)
from app.schemas.order import OrderAssignRequest, OrderStatusRequest
from app.services import inventory_service, order_service, stock_ledger
from app.services.exceptions import ConflictError, ForbiddenError
from tests.factories import order_request


def _user(db, role, tag, warehouse_id=None):
    user = User(username=f"{role.value}_{tag}", email=f"{tag}@test.local", role=role,
                hashed_password="x", warehouse_id=warehouse_id, city="تهران")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _qty(db, product_id, warehouse_id):
    inv = db.query(Inventory).filter(Inventory.product_id == product_id, Inventory.warehouse_id == warehouse_id).one()
    db.refresh(inv)
    return inv.quantity


def _status(db, user, order, new_status, note=None):
    return order_service.update_order_status(db, user, order.id, OrderStatusRequest(order_status=new_status, note=note))


@pytest.fixture()
def world(db_session):
    db = db_session
    wh1, wh2 = Warehouse(name="انبار تهران", location="تهران"), Warehouse(name="انبار کرج", location="کرج")
    db.add_all([wh1, wh2])
    db.commit()
    admin = _user(db, RoleEnum.ORG_ADMIN, "admin")
    manager = _user(db, RoleEnum.WAREHOUSE_MANAGER, "mgr", warehouse_id=wh1.id)
    driver = _user(db, RoleEnum.DRIVER, "drv")
    vehicle = Vehicle(license_plate="V-1", type="van", capacity_kg=1000, status="available", driver_id=driver.id, city="تهران")
    db.add(vehicle)
    rice = Product(name="برنج", sku="RICE", price=100, weight_kg=10)
    oil = Product(name="روغن", sku="OIL", price=50, weight_kg=2)
    db.add_all([rice, oil])
    db.commit()
    db.add_all([
        Inventory(product_id=rice.id, warehouse_id=wh1.id, quantity=20),
        Inventory(product_id=oil.id, warehouse_id=wh1.id, quantity=1),
        Inventory(product_id=rice.id, warehouse_id=wh2.id, quantity=5),
        Inventory(product_id=oil.id, warehouse_id=wh2.id, quantity=30),
    ])
    db.commit()
    return db, wh1, wh2, admin, manager, driver, vehicle, rice, oil


# ---------------------------------------------------------------------------
# سفارش چندقلمی
# ---------------------------------------------------------------------------

def test_multi_item_order_snapshots_prices_and_records_each_item(world):
    db, wh1, wh2, admin, manager, driver, vehicle, rice, oil = world

    order = order_service.create_order(db, admin, order_request(items=[(rice.id, 3), (oil.id, 4)]))

    assert re.fullmatch(r"LT-[A-HJ-NP-Z2-9]{8}", order.tracking_code)
    assert order.warehouse_id == wh2.id  # فقط انبار کرج برای «هر دو» کالا موجودی کافی دارد
    assert (order.total_quantity, order.total_weight_kg, order.total_price) == (7, 38, 500)
    assert [(i.product_name, i.quantity, i.unit_price) for i in order.items] == [("برنج", 3, 100), ("روغن", 4, 50)]
    assert (_qty(db, rice.id, wh2.id), _qty(db, oil.id, wh2.id)) == (2, 26)
    assert _qty(db, rice.id, wh1.id) == 20  # انبار دیگر دست‌نخورده

    moves = db.query(StockMovement).filter(StockMovement.reference_id == order.id, StockMovement.movement_type == "order_out").all()
    assert sorted(m.quantity_change for m in moves) == [-4, -3]

    # تغییر بعدی قیمت کالا، سفارش ثبت‌شده را تغییر نمی‌دهد
    rice.price = 999
    db.commit()
    db.refresh(order)
    assert order.items[0].unit_price == 100 and order.total_price == 500
    assert stock_ledger.find_mismatches(db) == []


def test_shortage_message_names_the_missing_product(world):
    db, wh1, wh2, admin, manager, driver, vehicle, rice, oil = world
    with pytest.raises(ConflictError, match="روغن"):
        order_service.create_order(db, admin, order_request(items=[(rice.id, 1), (oil.id, 40)]))
    # برنج ۱۰ از تهران و روغن ۱۰ از کرج: هیچ انباری به‌تنهایی هر دو را ندارد
    with pytest.raises(ConflictError, match="تفکیک"):
        order_service.create_order(db, admin, order_request(items=[(rice.id, 10), (oil.id, 10)]))
    assert _qty(db, rice.id, wh1.id) == 20


def test_duplicate_items_rejected():
    with pytest.raises(ValidationError):
        order_request(items=[(1, 1), (1, 2)])


def test_customer_is_matched_by_mobile_and_recipient_defaults(world):
    db, wh1, wh2, admin, manager, driver, vehicle, rice, oil = world
    first = order_service.create_order(db, admin, order_request(rice.id, auto_assign=False, mobile="۰۹۱۲۱۱۱۲۲۳۳"))
    second = order_service.create_order(db, admin, order_request(rice.id, auto_assign=False, mobile="09121112233",
                                                                 recipient_name="همکار مشتری", recipient_mobile="09350000000"))
    assert first.customer_id == second.customer_id
    assert db.query(Customer).count() == 1
    assert (first.recipient_name, first.recipient_mobile) == ("مشتری تست", "09121112233")
    assert (second.recipient_name, second.recipient_mobile) == ("همکار مشتری", "09350000000")


# ---------------------------------------------------------------------------
# تخصیص خودرو
# ---------------------------------------------------------------------------

def test_order_without_vehicle_then_assigned(world):
    db, wh1, wh2, admin, manager, driver, vehicle, rice, oil = world

    order = order_service.create_order(db, admin, order_request(rice.id, quantity=2, auto_assign=False))
    assert (order.status, order.vehicle_id) == ("pending", None)
    db.refresh(vehicle)
    assert vehicle.status == "available"

    order = order_service.assign_vehicle(db, manager, order.id, OrderAssignRequest())  # خودکار
    assert (order.status, order.vehicle_id) == ("assigned", vehicle.id)
    db.refresh(vehicle)
    assert vehicle.status == "available"   # از مرحله ۷ ظرفیت از روی بازه زمانی سفارش‌ها کنترل می‌شود
    assert [(h.from_status, h.to_status) for h in order.history] == [(None, "pending"), ("pending", "assigned")]

    with pytest.raises(ConflictError):
        order_service.assign_vehicle(db, admin, order.id, OrderAssignRequest(vehicle_id=vehicle.id))


def test_auto_assigned_order_starts_as_assigned(world):
    db, wh1, wh2, admin, manager, driver, vehicle, rice, oil = world
    order = order_service.create_order(db, admin, order_request(rice.id))
    assert (order.status, order.vehicle_id) == ("assigned", vehicle.id)
    assert order.history[0].note.startswith("ثبت سفارش و تخصیص خودرو")


# ---------------------------------------------------------------------------
# ماشین وضعیت و تاریخچه
# ---------------------------------------------------------------------------

def test_full_delivery_flow_with_history(world):
    db, wh1, wh2, admin, manager, driver, vehicle, rice, oil = world
    order = order_service.create_order(db, admin, order_request(rice.id, quantity=2))

    _status(db, driver, order, "picking_up")
    _status(db, manager, order, "picked_up", note="تحویل به راننده در سکوی ۲")
    _status(db, driver, order, "in_transit")
    order = _status(db, driver, order, "delivered", note="تحویل به خود مشتری")

    assert [h.to_status for h in order.history] == ["assigned", "picking_up", "picked_up", "in_transit", "delivered"]
    assert order.history[2].changed_by_id == manager.id and order.history[2].note == "تحویل به راننده در سکوی ۲"
    db.refresh(vehicle)
    assert vehicle.status == "available"
    assert _qty(db, rice.id, wh1.id) == 18  # تحویل‌شده: موجودی برنمی‌گردد

    with pytest.raises(ConflictError):  # وضعیت نهایی
        _status(db, admin, order, "canceled")


def test_cancel_restocks_every_item(world):
    db, wh1, wh2, admin, manager, driver, vehicle, rice, oil = world
    order = order_service.create_order(db, admin, order_request(items=[(rice.id, 2), (oil.id, 5)], warehouse_id=wh2.id))
    _status(db, admin, order, "canceled", note="انصراف مشتری")
    assert (_qty(db, rice.id, wh2.id), _qty(db, oil.id, wh2.id)) == (5, 30)
    db.refresh(vehicle)
    assert vehicle.status == "available"
    assert stock_ledger.find_mismatches(db) == []


def test_role_rules_for_status_changes(world):
    db, wh1, wh2, admin, manager, driver, vehicle, rice, oil = world
    order = order_service.create_order(db, admin, order_request(rice.id))

    with pytest.raises(ConflictError):      # راننده نمی‌تواند لغو کند
        _status(db, driver, order, "canceled")
    with pytest.raises(ConflictError):      # مدیر انبار نمی‌تواند تحویل‌شده بزند
        _status(db, manager, order, "delivered")
    with pytest.raises(ConflictError):      # پرش غیرمجاز: assigned ← pending
        _status(db, admin, order, "pending")

    other_order = order_service.create_order(db, admin, order_request(oil.id, warehouse_id=wh2.id, auto_assign=False))
    with pytest.raises(ForbiddenError):     # سفارش انبار کرج، مدیر انبار تهران
        _status(db, manager, other_order, "canceled")


def test_expire_overdue_orders(world, monkeypatch):
    db, wh1, wh2, admin, manager, driver, vehicle, rice, oil = world
    past = datetime.now(timezone.utc) - timedelta(days=3)
    overdue = order_service.create_order(db, admin, order_request(
        rice.id, quantity=4, delivery_window_start=past.isoformat(), delivery_window_end=(past + timedelta(hours=4)).isoformat()))
    fresh = order_service.create_order(db, admin, order_request(oil.id, auto_assign=False, warehouse_id=wh2.id))

    monkeypatch.setattr(tasks, "SessionLocal", sessionmaker(bind=db.get_bind()))
    assert tasks.expire_overdue_orders_task() == {"expired_orders": 1}

    db.expire_all()
    assert db.get(Order, overdue.id).status == "expired"
    assert db.get(Order, fresh.id).status == "pending"
    assert _qty(db, rice.id, wh1.id) == 20
    assert db.get(Vehicle, vehicle.id).status == "available"
    last = db.query(OrderStatusHistory).filter(OrderStatusHistory.order_id == overdue.id).order_by(OrderStatusHistory.id.desc()).first()
    assert (last.to_status, last.changed_by_id) == ("expired", None)
    assert tasks.expire_overdue_orders_task() == {"expired_orders": 0}


# ---------------------------------------------------------------------------
# جستجو و حذف کالا
# ---------------------------------------------------------------------------

def test_list_filters_and_search(world):
    db, wh1, wh2, admin, manager, driver, vehicle, rice, oil = world
    a = order_service.create_order(db, admin, order_request(rice.id, auto_assign=False, mobile="09121234567", city="قم"))
    b = order_service.create_order(db, admin, order_request(oil.id, auto_assign=False, warehouse_id=wh2.id, mobile="09359876543"))

    ids = lambda **kw: [o.id for o in order_service.list_orders(db, admin, **kw)]  # noqa: E731
    assert ids(q=a.tracking_code.lower()) == [a.id]
    assert ids(q="0935987") == [b.id]
    assert ids(province="قم") == [a.id]
    assert set(ids(order_status="pending")) == {a.id, b.id}


def test_product_with_active_order_item_cannot_be_deleted(world):
    db, wh1, wh2, admin, manager, driver, vehicle, rice, oil = world
    order_service.create_order(db, admin, order_request(items=[(rice.id, 1), (oil.id, 1)], warehouse_id=wh2.id, auto_assign=False))
    with pytest.raises(ConflictError):
        inventory_service.delete_product(db, admin, oil.id)
