"""تست‌های واحد سرویس انبار (Inventory Service)."""
import pytest

from app.models import User, RoleEnum, Warehouse, Inventory
from app.schemas.product import ProductCreate, StockUpdate
from app.services import inventory_service
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError


def _make_user(db, role, warehouse_id=None, tag=""):
    user = User(username=f"user_{role.value}_{tag}", email=f"{role.value}{tag}@test.local",
                role=role, hashed_password="x", warehouse_id=warehouse_id)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_create_product_sets_initial_stock(db_session):
    admin = _make_user(db_session, RoleEnum.ORG_ADMIN, tag="1")
    product = inventory_service.create_product(
        db_session, admin, ProductCreate(name="کالای تستی", sku="T-001", price=1000, initial_quantity=25)
    )
    inv = db_session.query(Inventory).filter(Inventory.product_id == product.id).first()
    assert inv.quantity == 25
    assert inv.ever_exceeded_reorder is True  # چون ۲۵ > ۱۰ (reorder_point پیش‌فرض)


def test_create_product_low_initial_stock_never_marked_high(db_session):
    admin = _make_user(db_session, RoleEnum.ORG_ADMIN, tag="2")
    product = inventory_service.create_product(
        db_session, admin, ProductCreate(name="کالای کم‌موجودی", sku="T-002", price=500, initial_quantity=3)
    )
    inv = db_session.query(Inventory).filter(Inventory.product_id == product.id).first()
    assert inv.ever_exceeded_reorder is False  # چون از اول هم کمتر از حد آستانه بوده -> نباید اعلان بگیره


def test_create_product_duplicate_sku_rejected(db_session):
    admin = _make_user(db_session, RoleEnum.ORG_ADMIN, tag="3")
    inventory_service.create_product(db_session, admin, ProductCreate(name="کالا۱", sku="DUP-1", price=100, initial_quantity=5))
    with pytest.raises(ConflictError):
        inventory_service.create_product(db_session, admin, ProductCreate(name="کالا۲", sku="DUP-1", price=200, initial_quantity=5))


def test_driver_cannot_create_product(db_session):
    driver = _make_user(db_session, RoleEnum.DRIVER, tag="4")
    with pytest.raises(ForbiddenError):
        inventory_service.create_product(db_session, driver, ProductCreate(name="کالا", sku="T-003", price=100, initial_quantity=1))


def test_warehouse_manager_without_warehouse_cannot_create_product(db_session):
    manager = _make_user(db_session, RoleEnum.WAREHOUSE_MANAGER, warehouse_id=None, tag="5")
    with pytest.raises(ConflictError):
        inventory_service.create_product(db_session, manager, ProductCreate(name="کالا", sku="T-004", price=100, initial_quantity=1))


def test_warehouse_manager_only_sees_own_warehouse_stock(db_session):
    wh1 = Warehouse(name="انبار ۱", location="تهران")
    wh2 = Warehouse(name="انبار ۲", location="تبریز")
    db_session.add_all([wh1, wh2])
    db_session.commit()
    db_session.refresh(wh1)
    db_session.refresh(wh2)

    admin = _make_user(db_session, RoleEnum.ORG_ADMIN, tag="6")
    product = inventory_service.create_product(
        db_session, admin, ProductCreate(name="کالای مشترک", sku="SHARED-1", price=100, initial_quantity=0, warehouse_id=wh1.id)
    )
    db_session.add(Inventory(product_id=product.id, warehouse_id=wh2.id, quantity=50, reorder_point=10))
    db_session.commit()

    manager1 = _make_user(db_session, RoleEnum.WAREHOUSE_MANAGER, warehouse_id=wh1.id, tag="m1")
    manager2 = _make_user(db_session, RoleEnum.WAREHOUSE_MANAGER, warehouse_id=wh2.id, tag="m2")

    stock_for_manager1 = next(p["stock"] for p in inventory_service.list_products(db_session, manager1) if p["id"] == product.id)
    stock_for_manager2 = next(p["stock"] for p in inventory_service.list_products(db_session, manager2) if p["id"] == product.id)

    assert stock_for_manager1 == 0    # موجودی انبار خودش
    assert stock_for_manager2 == 50   # موجودی انبار خودش


def test_delete_product_not_found(db_session):
    admin = _make_user(db_session, RoleEnum.ORG_ADMIN, tag="7")
    with pytest.raises(NotFoundError):
        inventory_service.delete_product(db_session, admin, 9999)


def test_update_stock_reports_low_stock_status(db_session):
    admin = _make_user(db_session, RoleEnum.ORG_ADMIN, tag="8")
    product = inventory_service.create_product(db_session, admin, ProductCreate(name="کالا", sku="T-005", price=100, initial_quantity=50))
    result = inventory_service.update_stock(db_session, admin, product.id, StockUpdate(quantity=5, reorder_point=10))
    assert "بحرانی" in result["status"]
    assert result["current_stock"] == 5
