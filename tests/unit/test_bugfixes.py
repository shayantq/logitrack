"""
تست‌های رگرسیون برای باگ‌های رفع‌شده: حذف امن، ماشین وضعیت سفارش،
محدوده انبار، IDOR، اعتبارسنجی ورودی‌ها و اعلان موجودی تمام‌شده.
"""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import sessionmaker

from app import tasks
from app.models import User, RoleEnum, Vehicle, Product, Inventory, Order, Warehouse
from app.models_notification import Notification
from app.schemas.order import OrderStatusRequest
from app.schemas.product import ProductCreate, StockUpdate
from app.schemas.user import CreateUserRequest
from app.schemas.vehicle import VehicleStatusRequest
from app.services import order_service, inventory_service, user_service, vehicle_service
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError
from tests.factories import order_request


# ---------------------------------------------------------------------------
# ابزارهای ساخت داده
# ---------------------------------------------------------------------------

def _user(db, role, tag, warehouse_id=None, city=None):
    user = User(username=f"{role.value}_{tag}", email=f"{role.value}_{tag}@test.local",
                role=role, hashed_password="x", warehouse_id=warehouse_id, city=city)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _vehicle(db, driver, tag, city="تهران", capacity=1000):
    vehicle = Vehicle(license_plate=f"P-{tag}", type="van", capacity_kg=capacity,
                      status="available", driver_id=driver.id, city=city)
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)
    return vehicle


def _warehouse(db, name):
    wh = Warehouse(name=name, location=name)
    db.add(wh)
    db.commit()
    db.refresh(wh)
    return wh


def _product(db, tag, stocks):
    """stocks: لیست (warehouse_id, quantity)"""
    product = Product(name=f"کالا {tag}", sku=f"SKU-{tag}", price=100, weight_kg=1.0)
    db.add(product)
    db.commit()
    db.refresh(product)
    for warehouse_id, quantity in stocks:
        db.add(Inventory(product_id=product.id, warehouse_id=warehouse_id, quantity=quantity,
                         reorder_point=10, ever_exceeded_reorder=quantity > 10))
    db.commit()
    return product


def _request(product_id, vehicle_id=None, quantity=1, warehouse_id=None):
    return order_request(product_id, vehicle_id, quantity=quantity, warehouse_id=warehouse_id)


def _stock(db, product_id, warehouse_id=None):
    query = db.query(Inventory).filter(Inventory.product_id == product_id)
    if warehouse_id is not None:
        query = query.filter(Inventory.warehouse_id == warehouse_id)
    inv = query.first()
    db.refresh(inv)
    return inv.quantity


@pytest.fixture()
def setup(db_session):
    db = db_session
    admin = _user(db, RoleEnum.ORG_ADMIN, "a")
    driver = _user(db, RoleEnum.DRIVER, "d", city="تهران")
    vehicle = _vehicle(db, driver, "v")
    product = _product(db, "p", [(None, 20)])
    return db, admin, driver, vehicle, product


# ---------------------------------------------------------------------------
# حذف امن (قبلاً حذف راننده، خودرو و همه سفارش‌هایش را پاک می‌کرد)
# ---------------------------------------------------------------------------

def test_cannot_delete_driver_with_vehicle_and_orders_survive(setup):
    db, admin, driver, vehicle, product = setup
    order_service.create_order(db, admin, _request(product.id, vehicle.id))

    with pytest.raises(ConflictError):
        user_service.delete_user(db, admin, driver.id)

    assert db.query(Order).count() == 1
    assert db.query(Vehicle).count() == 1


def test_admin_cannot_delete_self(setup):
    db, admin, *_ = setup
    with pytest.raises(ConflictError):
        user_service.delete_user(db, admin, admin.id)


def test_cannot_delete_vehicle_with_active_order(setup):
    db, admin, driver, vehicle, product = setup
    order_service.create_order(db, admin, _request(product.id, vehicle.id))
    with pytest.raises(ConflictError):
        vehicle_service.delete_vehicle(db, admin, vehicle.id)


def test_deleting_vehicle_keeps_order_history(setup):
    db, admin, driver, vehicle, product = setup
    order = order_service.create_order(db, admin, _request(product.id, vehicle.id))
    order_service.update_order_status(db, admin, order.id, OrderStatusRequest(order_status="picked_up"))
    order_service.update_order_status(db, admin, order.id, OrderStatusRequest(order_status="in_transit"))
    order_service.update_order_status(db, admin, order.id, OrderStatusRequest(order_status="delivered"))

    vehicle_service.delete_vehicle(db, admin, vehicle.id)

    kept = db.get(Order, order.id)
    assert kept is not None
    assert kept.vehicle_id is None


# ---------------------------------------------------------------------------
# ماشین وضعیت سفارش و برگشت موجودی
# ---------------------------------------------------------------------------

def test_failed_order_restores_stock_and_frees_vehicle(setup):
    db, admin, driver, vehicle, product = setup
    order = order_service.create_order(db, admin, _request(product.id, vehicle.id, quantity=5))
    assert _stock(db, product.id) == 15

    order_service.update_order_status(db, driver, order.id, OrderStatusRequest(order_status="failed"))

    assert _stock(db, product.id) == 20
    db.refresh(vehicle)
    assert vehicle.status == "available"


def test_deleting_failed_order_does_not_restore_stock_twice(setup):
    db, admin, driver, vehicle, product = setup
    order = order_service.create_order(db, admin, _request(product.id, vehicle.id, quantity=5))
    order_service.update_order_status(db, admin, order.id, OrderStatusRequest(order_status="failed"))

    order_service.delete_order(db, admin, order.id)
    assert _stock(db, product.id) == 20


def test_deleting_completed_order_does_not_restore_stock(setup):
    db, admin, driver, vehicle, product = setup
    order = order_service.create_order(db, admin, _request(product.id, vehicle.id, quantity=5))
    order_service.update_order_status(db, admin, order.id, OrderStatusRequest(order_status="picked_up"))
    order_service.update_order_status(db, admin, order.id, OrderStatusRequest(order_status="in_transit"))
    order_service.update_order_status(db, admin, order.id, OrderStatusRequest(order_status="delivered"))

    order_service.delete_order(db, admin, order.id)
    assert _stock(db, product.id) == 15


def test_final_order_status_cannot_be_reopened(setup):
    db, admin, driver, vehicle, product = setup
    order = order_service.create_order(db, admin, _request(product.id, vehicle.id))
    order_service.update_order_status(db, admin, order.id, OrderStatusRequest(order_status="picked_up"))
    order_service.update_order_status(db, admin, order.id, OrderStatusRequest(order_status="in_transit"))
    order_service.update_order_status(db, admin, order.id, OrderStatusRequest(order_status="delivered"))

    with pytest.raises(ConflictError):
        order_service.update_order_status(db, admin, order.id, OrderStatusRequest(order_status="pending"))


def test_completing_order_keeps_vehicle_in_maintenance(setup):
    db, admin, driver, vehicle, product = setup
    order = order_service.create_order(db, admin, _request(product.id, vehicle.id))
    vehicle.status = "maintenance"
    db.commit()

    order_service.update_order_status(db, driver, order.id, OrderStatusRequest(order_status="picked_up"))
    order_service.update_order_status(db, driver, order.id, OrderStatusRequest(order_status="in_transit"))
    order_service.update_order_status(db, driver, order.id, OrderStatusRequest(order_status="delivered"))
    db.refresh(vehicle)
    assert vehicle.status == "maintenance"


def test_marking_vehicle_available_does_not_allow_overbooking(setup):
    """
    از مرحله ۷ راننده می‌تواند با سفارش فعال «در دسترس» بزند؛ دیگر وضعیت خودرو جلوی
    تخصیص دوباره را نمی‌گیرد، بلکه ظرفیت هم‌پوشان در همان بازه زمانی.
    """
    db, admin, driver, vehicle, product = setup
    order_service.create_order(db, admin, _request(product.id, vehicle.id))
    vehicle_service.update_vehicle_status(db, driver, vehicle.id, VehicleStatusRequest(vehicle_status="on_route"))
    vehicle_service.update_vehicle_status(db, driver, vehicle.id, VehicleStatusRequest(vehicle_status="available"))

    vehicle.capacity_kg = 1   # بار سفارش اول کل ظرفیت همین بازه را پر کرده است
    db.commit()
    with pytest.raises(ConflictError, match="ظرفیت"):
        order_service.create_order(db, admin, _request(product.id, vehicle.id))


# ---------------------------------------------------------------------------
# دسترسی راننده به سفارش/خودروی دیگران (IDOR)
# ---------------------------------------------------------------------------

def test_driver_cannot_read_other_drivers_order_or_vehicle(setup):
    db, admin, driver, vehicle, product = setup
    order = order_service.create_order(db, admin, _request(product.id, vehicle.id))
    stranger = _user(db, RoleEnum.DRIVER, "stranger")

    with pytest.raises(NotFoundError):
        order_service.get_order(db, stranger, order.id)
    with pytest.raises(NotFoundError):
        vehicle_service.get_vehicle(db, stranger, vehicle.id)

    assert order_service.get_order(db, driver, order.id).id == order.id
    assert vehicle_service.get_vehicle(db, driver, vehicle.id).id == vehicle.id


# ---------------------------------------------------------------------------
# محدوده انبار
# ---------------------------------------------------------------------------

@pytest.fixture()
def two_warehouses(db_session):
    db = db_session
    wh1, wh2 = _warehouse(db, "تهران"), _warehouse(db, "تبریز")
    admin = _user(db, RoleEnum.ORG_ADMIN, "wa")
    manager1 = _user(db, RoleEnum.WAREHOUSE_MANAGER, "m1", warehouse_id=wh1.id)
    manager2 = _user(db, RoleEnum.WAREHOUSE_MANAGER, "m2", warehouse_id=wh2.id)
    driver = _user(db, RoleEnum.DRIVER, "wd", city="تهران")
    vehicle = _vehicle(db, driver, "wv")
    product = _product(db, "shared", [(wh1.id, 2), (wh2.id, 50)])
    return db, wh1, wh2, admin, manager1, manager2, vehicle, product


def test_manager_order_deducts_only_from_own_warehouse(two_warehouses):
    db, wh1, wh2, admin, manager1, manager2, vehicle, product = two_warehouses

    with pytest.raises(ConflictError):  # انبار ۱ فقط ۲ عدد دارد
        order_service.create_order(db, manager1, _request(product.id, vehicle.id, quantity=5))

    order = order_service.create_order(db, manager2, _request(product.id, vehicle.id, quantity=5))
    assert order.warehouse_id == wh2.id
    assert _stock(db, product.id, wh1.id) == 2
    assert _stock(db, product.id, wh2.id) == 45


def test_admin_order_picks_warehouse_with_enough_stock_and_restores_to_it(two_warehouses):
    db, wh1, wh2, admin, manager1, manager2, vehicle, product = two_warehouses

    order = order_service.create_order(db, admin, _request(product.id, vehicle.id, quantity=5))
    assert order.warehouse_id == wh2.id

    order_service.delete_order(db, admin, order.id)
    assert _stock(db, product.id, wh1.id) == 2
    assert _stock(db, product.id, wh2.id) == 50


def test_manager_update_stock_only_touches_own_warehouse(two_warehouses):
    db, wh1, wh2, admin, manager1, manager2, vehicle, product = two_warehouses

    inventory_service.update_stock(db, manager1, product.id, StockUpdate(quantity=30, reorder_point=5))
    assert _stock(db, product.id, wh1.id) == 30
    assert _stock(db, product.id, wh2.id) == 50


def test_admin_update_stock_requires_warehouse_when_ambiguous(two_warehouses):
    db, wh1, wh2, admin, manager1, manager2, vehicle, product = two_warehouses

    with pytest.raises(ConflictError):
        inventory_service.update_stock(db, admin, product.id, StockUpdate(quantity=30))

    inventory_service.update_stock(db, admin, product.id, StockUpdate(quantity=30, warehouse_id=wh2.id))
    assert _stock(db, product.id, wh2.id) == 30


def test_manager_cannot_delete_product_stocked_in_other_warehouse(two_warehouses):
    db, wh1, wh2, admin, manager1, manager2, vehicle, product = two_warehouses
    with pytest.raises(ForbiddenError):
        inventory_service.delete_product(db, manager1, product.id)


def test_manager_lists_only_own_warehouse_products(two_warehouses):
    db, wh1, wh2, admin, manager1, manager2, vehicle, product = two_warehouses
    _product(db, "only-wh2", [(wh2.id, 7)])

    names_for_manager1 = {p["name"] for p in inventory_service.list_products(db, manager1)}
    assert names_for_manager1 == {"کالا shared"}


def test_product_weight_is_saved(db_session):
    admin = _user(db_session, RoleEnum.ORG_ADMIN, "w")
    product = inventory_service.create_product(
        db_session, admin, ProductCreate(name="یخچال", sku="FRIDGE", price=1, weight_kg=80, initial_quantity=1)
    )
    assert product.weight_kg == 80


# ---------------------------------------------------------------------------
# اعتبارسنجی ورودی‌ها (قبلاً مقادیر نامعتبر تا دیتابیس می‌رسید و خطای ۵۰۰ می‌داد)
# ---------------------------------------------------------------------------

def test_invalid_role_rejected():
    with pytest.raises(ValidationError):
        CreateUserRequest(username="baduser", email="b@example.com", role="superuser", password="secret123")


def test_password_whitespace_is_preserved():
    req = CreateUserRequest(username="okay", email="o@example.com", role="driver", password=" secret 123 ")
    assert req.password == " secret 123 "


def test_invalid_order_size_and_window_rejected():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        order_request(1, size="huge")
    with pytest.raises(ValidationError):
        order_request(1, delivery_window_start=now.isoformat(), delivery_window_end=(now - timedelta(days=1)).isoformat())


def test_two_letter_city_destination_allowed():
    assert order_request(1, city="قم").destination_city == "قم"


# ---------------------------------------------------------------------------
# اعلان دوره‌ای موجودی (قبلاً کالای کاملاً تمام‌شده اعلان نمی‌گرفت)
# ---------------------------------------------------------------------------

def test_low_stock_task_alerts_for_out_of_stock_per_warehouse(db_session, monkeypatch):
    db = db_session
    wh1, wh2 = _warehouse(db, "انبار الف"), _warehouse(db, "انبار ب")
    product = _product(db, "alert", [(wh1.id, 0), (wh2.id, 50)])
    db.query(Inventory).filter(Inventory.warehouse_id == wh1.id).update({"ever_exceeded_reorder": True})
    db.commit()

    monkeypatch.setattr(tasks, "SessionLocal", sessionmaker(bind=db.get_bind()))
    result = tasks.check_low_stock_task()

    assert result["notifications_created"] == 1
    notification = db.query(Notification).one()
    assert notification.product_id == product.id
    assert notification.warehouse_id == wh1.id
    assert "تمام شده" in notification.message

    # اجرای دوباره نباید اعلان تکراری بسازد
    assert tasks.check_low_stock_task()["notifications_created"] == 0
