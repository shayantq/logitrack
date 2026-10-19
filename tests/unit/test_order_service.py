"""
تست‌های واحد سرویس سفارشات (Order Service).
تست همزمانی واقعی (race condition) اینجا نیست — چون SQLite از قفل ردیف
واقعی پشتیبانی نمی‌کند. آن تست در tests/integration/test_concurrent_orders.py
با PostgreSQL واقعی انجام می‌شود. اینجا فقط درستیِ منطق تجاری را می‌سنجیم.
"""
import pytest
from datetime import datetime, timedelta, timezone

from app.models import DriverProfile, User, RoleEnum, Vehicle, Product, Inventory
from app.schemas.order import OrderRequest, OrderStatusRequest
from app.services import order_service
from app.services.exceptions import ConflictError, ForbiddenError
from tests.factories import order_request, order_payload


def _make_user(db, role, city=None, tag=""):
    user = User(username=f"u_{role.value}_{tag}", email=f"{role.value}{tag}@test.local",
                role=role, hashed_password="x", city=city)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_vehicle(db, driver, city, capacity=1000, vstatus="available", tag=""):
    vehicle = Vehicle(license_plate=f"PLT-{driver.id}-{tag}", type="van", capacity_kg=capacity,
                       status=vstatus, driver_id=driver.id, city=city)
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)
    return vehicle


def _make_product_with_stock(db, quantity, weight_kg=1.0, tag=""):
    product = Product(name="کالای تستی", sku=f"SKU-{quantity}-{weight_kg}-{tag}", price=100, weight_kg=weight_kg)
    db.add(product)
    db.commit()
    db.refresh(product)
    db.add(Inventory(product_id=product.id, quantity=quantity, reorder_point=10))
    db.commit()
    return product


def _order_request(product_id, vehicle_id=None, destination="تهران", quantity=1):
    return order_request(product_id, vehicle_id, city=destination, quantity=quantity)


def test_create_order_decrements_stock(db_session):
    admin = _make_user(db_session, RoleEnum.ORG_ADMIN)
    driver = _make_user(db_session, RoleEnum.DRIVER, city="تهران", tag="a")
    vehicle = _make_vehicle(db_session, driver, city="تهران")
    product = _make_product_with_stock(db_session, quantity=10)

    order = order_service.create_order(db_session, admin, _order_request(product.id, vehicle.id, quantity=3))

    inv = db_session.query(Inventory).filter(Inventory.product_id == product.id).first()
    assert inv.quantity == 7
    assert order.total_quantity == 3


def test_create_order_insufficient_stock_raises_and_does_not_touch_stock(db_session):
    admin = _make_user(db_session, RoleEnum.ORG_ADMIN)
    driver = _make_user(db_session, RoleEnum.DRIVER, city="تهران", tag="b")
    vehicle = _make_vehicle(db_session, driver, city="تهران")
    product = _make_product_with_stock(db_session, quantity=2)

    with pytest.raises(ConflictError):
        order_service.create_order(db_session, admin, _order_request(product.id, vehicle.id, quantity=5))

    inv = db_session.query(Inventory).filter(Inventory.product_id == product.id).first()
    assert inv.quantity == 2  # چون سفارش رد شده، موجودی نباید دست‌نخورده باقی نمانده باشد


def test_driver_cannot_create_order(db_session):
    driver = _make_user(db_session, RoleEnum.DRIVER, city="تهران", tag="c")
    product = _make_product_with_stock(db_session, quantity=10)
    with pytest.raises(ForbiddenError):
        order_service.create_order(db_session, driver, _order_request(product.id, quantity=1))


def test_auto_assign_prefers_same_city_vehicle(db_session):
    admin = _make_user(db_session, RoleEnum.ORG_ADMIN)
    driver_far = _make_user(db_session, RoleEnum.DRIVER, city="تهران", tag="far")
    driver_near = _make_user(db_session, RoleEnum.DRIVER, city="تبریز", tag="near")
    _make_vehicle(db_session, driver_far, city="تهران", tag="far")
    vehicle_near = _make_vehicle(db_session, driver_near, city="تبریز", tag="near")
    product = _make_product_with_stock(db_session, quantity=10, tag="city")

    order = order_service.create_order(db_session, admin, _order_request(product.id, vehicle_id=None, destination="تبریز", quantity=1))

    assert order.vehicle_id == vehicle_near.id


def test_other_city_needs_intercity_driver(db_session):
    """از مرحله ۷: سفارش شهر دیگر فقط به راننده‌ای که بار بین‌شهری می‌برد پیشنهاد/تخصیص داده می‌شود."""
    admin = _make_user(db_session, RoleEnum.ORG_ADMIN)
    driver = _make_user(db_session, RoleEnum.DRIVER, city="تهران", tag="fallback")
    vehicle = _make_vehicle(db_session, driver, city="تهران", tag="fallback")
    product = _make_product_with_stock(db_session, quantity=10, tag="fallback")

    with pytest.raises(ConflictError, match="بین‌شهری"):
        order_service.create_order(db_session, admin, _order_request(product.id, vehicle_id=None, destination="اصفهان", quantity=1))

    db_session.add(DriverProfile(user_id=driver.id, intercity=True))
    db_session.commit()
    order = order_service.create_order(db_session, admin, _order_request(product.id, vehicle_id=None, destination="اصفهان", quantity=1))
    assert order.vehicle_id == vehicle.id


def test_auto_assign_no_vehicle_with_enough_capacity(db_session):
    admin = _make_user(db_session, RoleEnum.ORG_ADMIN)
    driver = _make_user(db_session, RoleEnum.DRIVER, city="تهران", tag="cap")
    _make_vehicle(db_session, driver, city="تهران", capacity=5, tag="cap")
    product = _make_product_with_stock(db_session, quantity=100, weight_kg=10.0, tag="cap")

    with pytest.raises(ConflictError):
        order_service.create_order(db_session, admin, _order_request(product.id, vehicle_id=None, quantity=5))


def test_manual_vehicle_capacity_check(db_session):
    admin = _make_user(db_session, RoleEnum.ORG_ADMIN)
    driver = _make_user(db_session, RoleEnum.DRIVER, city="تهران", tag="manualcap")
    vehicle = _make_vehicle(db_session, driver, city="تهران", capacity=5, tag="manualcap")
    product = _make_product_with_stock(db_session, quantity=100, weight_kg=10.0, tag="manualcap")

    with pytest.raises(ConflictError):
        order_service.create_order(db_session, admin, _order_request(product.id, vehicle_id=vehicle.id, quantity=5))


def test_driver_can_mark_own_order_completed_and_frees_vehicle(db_session):
    admin = _make_user(db_session, RoleEnum.ORG_ADMIN)
    driver = _make_user(db_session, RoleEnum.DRIVER, city="تهران", tag="complete")
    vehicle = _make_vehicle(db_session, driver, city="تهران", tag="complete")
    product = _make_product_with_stock(db_session, quantity=10, tag="complete")
    order = order_service.create_order(db_session, admin, _order_request(product.id, vehicle.id, quantity=1))

    order_service.update_order_status(db_session, driver, order.id, OrderStatusRequest(order_status="picked_up"))
    order_service.update_order_status(db_session, driver, order.id, OrderStatusRequest(order_status="in_transit"))
    updated = order_service.update_order_status(db_session, driver, order.id, OrderStatusRequest(order_status="delivered"))
    assert updated.status == "delivered"

    db_session.refresh(vehicle)
    assert vehicle.status == "available"


def test_driver_cannot_update_others_order(db_session):
    admin = _make_user(db_session, RoleEnum.ORG_ADMIN)
    driver1 = _make_user(db_session, RoleEnum.DRIVER, city="تهران", tag="owner")
    driver2 = _make_user(db_session, RoleEnum.DRIVER, city="تبریز", tag="stranger")
    vehicle1 = _make_vehicle(db_session, driver1, city="تهران", tag="owner")
    product = _make_product_with_stock(db_session, quantity=10, tag="others")
    order = order_service.create_order(db_session, admin, _order_request(product.id, vehicle1.id, quantity=1))

    with pytest.raises(ForbiddenError):
        order_service.update_order_status(db_session, driver2, order.id, OrderStatusRequest(order_status="picked_up"))
        order_service.update_order_status(db_session, driver2, order.id, OrderStatusRequest(order_status="delivered"))


def test_delete_order_restores_stock_and_frees_vehicle(db_session):
    admin = _make_user(db_session, RoleEnum.ORG_ADMIN)
    driver = _make_user(db_session, RoleEnum.DRIVER, city="تهران", tag="delete")
    vehicle = _make_vehicle(db_session, driver, city="تهران", tag="delete")
    product = _make_product_with_stock(db_session, quantity=10, tag="delete")
    order = order_service.create_order(db_session, admin, _order_request(product.id, vehicle.id, quantity=4))

    inv_before = db_session.query(Inventory).filter(Inventory.product_id == product.id).first()
    assert inv_before.quantity == 6

    order_service.delete_order(db_session, admin, order.id)

    inv_after = db_session.query(Inventory).filter(Inventory.product_id == product.id).first()
    assert inv_after.quantity == 10

    db_session.refresh(vehicle)
    assert vehicle.status == "available"
