"""
تست‌های جداسازی سازمان‌ها (Multi-tenancy)

دو سازمان A و B با داده کامل (ادمین، مدیر انبار، راننده، انبار، کالا،
خودرو، سفارش، اعلان) ساخته می‌شوند. کاربران A نباید هیچ داده‌ای از B را
ببینند، تغییر دهند یا به آن ارجاع دهند — نه در لیست‌ها، نه با id مستقیم.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from app.core.security import bcrypt_context, create_access_token
from app.core.tenancy import TenantMissingError, set_tenant
from app.models import (
    Organization, User, RoleEnum, Warehouse, Product, Inventory, Vehicle, Order, OrderItem,
)
from app.models_notification import Notification
from tests.factories import order_request, order_payload

PASSWORD = "secret123"
PASSWORD_HASH = bcrypt_context.hash(PASSWORD)


@dataclass
class Tenant:
    org_id: int
    admin: User
    manager: User
    driver: User
    warehouse_id: int
    product_id: int
    vehicle_id: int
    order_id: int
    notification_id: int


def _auth(user: User) -> dict:
    token = create_access_token(user.username, user.id, timedelta(minutes=5))
    return {"Authorization": f"Bearer {token}"}


def _make_tenant(db, slug: str) -> Tenant:
    org = Organization(name=f"سازمان {slug}", slug=slug)
    db.add(org)
    db.commit()
    set_tenant(db, org.id)

    warehouse = Warehouse(name=f"انبار {slug}", location="تهران")
    db.add(warehouse)
    db.commit()

    admin = User(username=f"{slug}_admin", email=f"{slug}_admin@example.com", role=RoleEnum.ORG_ADMIN, hashed_password=PASSWORD_HASH)
    manager = User(username=f"{slug}_mgr", email=f"{slug}_mgr@example.com", role=RoleEnum.WAREHOUSE_MANAGER,
                   hashed_password=PASSWORD_HASH, warehouse_id=warehouse.id)
    driver = User(username=f"{slug}_drv", email=f"{slug}_drv@example.com", role=RoleEnum.DRIVER,
                  hashed_password=PASSWORD_HASH, city="تهران")
    db.add_all([admin, manager, driver])
    db.commit()

    product = Product(name=f"کالا {slug}", sku="SAME-SKU", price=100, weight_kg=1)
    vehicle = Vehicle(license_plate="PLATE-1", type="van", capacity_kg=1000, status="available", driver_id=driver.id, city="تهران")
    db.add_all([product, vehicle])
    db.commit()
    db.add(Inventory(product_id=product.id, warehouse_id=warehouse.id, quantity=50, reorder_point=10))
    order = Order(tracking_code=f"LT-{slug.upper().replace('-', '')[:8]}", destination_city="تهران",
                  destination_province="تهران", size="m", priority=False, status="assigned",
                  vehicle_id=vehicle.id, warehouse_id=warehouse.id, total_quantity=1,
                  delivery_window_start=datetime.now(timezone.utc), delivery_window_end=datetime.now(timezone.utc) + timedelta(days=1))
    order.items.append(OrderItem(product_id=product.id, product_name=product.name, product_sku=product.sku, quantity=1))
    db.add(order)
    db.commit()
    notification = Notification(product_id=product.id, warehouse_id=warehouse.id, message="کمبود موجودی")
    db.add(notification)
    db.commit()

    tenant = Tenant(org.id, admin, manager, driver, warehouse.id, product.id, vehicle.id, order.id, notification.id)
    set_tenant(db, None)
    return tenant


@pytest.fixture()
def tenants(api_env):
    client, TestingSession = api_env
    db = TestingSession()
    a = _make_tenant(db, "org-a")
    b = _make_tenant(db, "org-b")
    platform_admin = User(username="platform_root", email="root@example.com", role=RoleEnum.PLATFORM_ADMIN, hashed_password=PASSWORD_HASH)
    support = User(username="platform_help", email="help@example.com", role=RoleEnum.PLATFORM_SUPPORT, hashed_password=PASSWORD_HASH)
    db.add_all([platform_admin, support])
    db.commit()
    try:
        yield client, db, a, b, platform_admin, support
    finally:
        db.close()


def _ids(response) -> set[int]:
    assert response.status_code == 200, response.text
    return {item["id"] for item in response.json()}


# ---------------------------------------------------------------------------
# لیست‌ها فقط داده‌های سازمان خود کاربر را برمی‌گردانند
# ---------------------------------------------------------------------------

def test_lists_only_show_own_organization(tenants):
    client, db, a, b, *_ = tenants
    h = _auth(a.admin)

    assert _ids(client.get("/orders/", headers=h)) == {a.order_id}
    assert _ids(client.get("/vehicles/", headers=h)) == {a.vehicle_id}
    assert _ids(client.get("/inventory/products", headers=h)) == {a.product_id}
    assert _ids(client.get("/warehouses/", headers=h)) == {a.warehouse_id}
    assert _ids(client.get("/notifications/unread", headers=h)) == {a.notification_id}
    assert _ids(client.get("/users/", headers=h)) == {a.admin.id, a.manager.id, a.driver.id}


def test_stats_only_count_own_organization(tenants):
    client, db, a, b, *_ = tenants
    h = _auth(a.admin)

    stats = client.get("/reports/stats", headers=h).json()
    assert stats["total_orders"] == 1
    assert stats["total_products"] == 1
    assert stats["total_vehicles"] == 1

    summary = client.get("/orders/stats/summary", headers=h).json()
    assert summary["metrics"]["total_orders"] == 1
    assert [o["id"] for o in summary["recent_orders"]] == [a.order_id]


# ---------------------------------------------------------------------------
# دسترسی مستقیم با id به داده سازمان دیگر → ۴۰۴ (وجودش هم فاش نمی‌شود)
# ---------------------------------------------------------------------------

def test_cannot_read_or_modify_other_organization_by_id(tenants):
    client, db, a, b, *_ = tenants
    h = _auth(a.admin)

    assert client.get(f"/orders/{b.order_id}", headers=h).status_code == 404
    assert client.get(f"/vehicles/{b.vehicle_id}", headers=h).status_code == 404
    assert client.put(f"/orders/{b.order_id}/status", json={"order_status": "failed"}, headers=h).status_code == 404
    assert client.put(f"/vehicles/{b.vehicle_id}/status", json={"vehicle_status": "maintenance"}, headers=h).status_code == 404
    assert client.put(f"/vehicles/{b.vehicle_id}/driver", json={"driver_id": a.driver.id}, headers=h).status_code == 404
    assert client.put(f"/inventory/stock/{b.product_id}", json={"quantity": 0}, headers=h).status_code == 404
    assert client.put(f"/notifications/{b.notification_id}/read", headers=h).status_code == 404
    assert client.delete(f"/orders/{b.order_id}", headers=h).status_code == 404
    assert client.delete(f"/vehicles/{b.vehicle_id}", headers=h).status_code == 404
    assert client.delete(f"/inventory/products/{b.product_id}", headers=h).status_code == 404
    assert client.delete(f"/users/{b.driver.id}", headers=h).status_code == 404

    # داده‌های B دست‌نخورده باقی مانده‌اند
    set_tenant(db, None)
    db.expire_all()
    assert db.get(Order, b.order_id).status == "assigned"
    assert db.get(Vehicle, b.vehicle_id).status == "available"
    assert db.get(Product, b.product_id) is not None
    assert db.get(User, b.driver.id) is not None


def test_cannot_reference_other_organization_records(tenants):
    client, db, a, b, *_ = tenants
    h = _auth(a.admin)
    assert client.post("/orders/", json=order_payload(b.product_id), headers=h).status_code == 404
    assert client.post("/orders/", json=order_payload(a.product_id, b.vehicle_id), headers=h).status_code == 404
    assert client.post("/inventory/products", json={"name": "x", "sku": "X-1", "price": 1, "warehouse_id": b.warehouse_id},
                       headers=h).status_code == 404
    assert client.post("/auth/", json={"username": "new_mgr", "email": "new_mgr@example.com", "role": "warehouse_manager",
                                       "password": PASSWORD, "warehouse_id": b.warehouse_id}, headers=h).status_code == 404
    assert client.post("/vehicles/", json={"license_plate": "NEW-1", "vehicle_type": "van", "capacity_kg": 100,
                                           "driver_id": b.driver.id}, headers=h).status_code == 404


def test_manager_and_driver_are_isolated_too(tenants):
    client, db, a, b, *_ = tenants
    assert _ids(client.get("/inventory/products", headers=_auth(a.manager))) == {a.product_id}
    assert _ids(client.get("/orders/", headers=_auth(a.driver))) == {a.order_id}
    assert client.get(f"/orders/{b.order_id}", headers=_auth(a.driver)).status_code == 404


# ---------------------------------------------------------------------------
# رکوردهای جدید خودکار به سازمان سازنده تعلق می‌گیرند؛ یکتایی‌ها در محدوده سازمان
# ---------------------------------------------------------------------------

def test_new_records_belong_to_creator_organization(tenants):
    client, db, a, b, *_ = tenants
    h = _auth(a.admin)

    res = client.post("/inventory/products", json={"name": "کالای جدید", "sku": "NEW-SKU", "price": 1, "warehouse_id": a.warehouse_id},
                      headers=h)
    assert res.status_code == 201, res.text
    res = client.post("/auth/", json={"username": "a_new_driver", "email": "a_new_driver@example.com", "role": "driver",
                                      "password": PASSWORD}, headers=h)
    assert res.status_code == 201, res.text

    set_tenant(db, None)
    assert db.query(Product).filter(Product.sku == "NEW-SKU").one().organization_id == a.org_id
    assert db.query(User).filter(User.username == "a_new_driver").one().organization_id == a.org_id


def test_sku_unique_per_organization_but_username_global(tenants):
    client, db, a, b, *_ = tenants

    # هر دو سازمان از قبل SKU «SAME-SKU» دارند؛ تکرارش داخل یک سازمان مجاز نیست
    dup = client.post("/inventory/products", json={"name": "y", "sku": "SAME-SKU", "price": 1}, headers=_auth(a.admin))
    assert dup.status_code == 400

    # نام کاربری در کل پلتفرم یکتاست — باید ۴۰۰ بدهد، نه خطای ۵۰۰ دیتابیس
    res = client.post("/auth/", json={"username": b.driver.username, "email": "other@example.com", "role": "driver",
                                      "password": PASSWORD}, headers=_auth(a.admin))
    assert res.status_code == 400, res.text


def test_org_admin_cannot_create_platform_staff(tenants):
    client, db, a, *_ = tenants
    res = client.post("/auth/", json={"username": "sneaky", "email": "sneaky@example.com", "role": "platform_admin",
                                      "password": PASSWORD}, headers=_auth(a.admin))
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# گزارش‌های پس‌زمینه
# ---------------------------------------------------------------------------

class _FakeResult:
    def __init__(self, payload):
        self.state = "SUCCESS"
        self.result = payload


def test_report_result_of_other_organization_is_hidden(tenants, monkeypatch):
    client, db, a, b, *_ = tenants
    from app.routers import reports
    payload = {"organization_id": b.org_id, "filename": "x.xlsx", "content_type": "text/plain", "content_b64": "eA=="}
    monkeypatch.setattr(reports, "AsyncResult", lambda task_id, app=None: _FakeResult(payload))

    assert client.get("/reports/task-result/some-task", headers=_auth(a.admin)).status_code == 404
    assert client.get("/reports/task-status/some-task", headers=_auth(a.admin)).status_code == 404
    assert client.get("/reports/task-result/some-task", headers=_auth(b.admin)).status_code == 200


# ---------------------------------------------------------------------------
# پنل پلتفرم
# ---------------------------------------------------------------------------

def test_platform_and_tenant_areas_are_separated(tenants):
    client, db, a, b, platform_admin, support = tenants

    assert client.get("/platform/organizations", headers=_auth(a.admin)).status_code == 403
    assert client.get("/orders/", headers=_auth(platform_admin)).status_code == 403
    assert client.get("/inventory/products", headers=_auth(support)).status_code == 403


def test_platform_lists_organizations_with_stats(tenants):
    client, db, a, b, platform_admin, support = tenants
    res = client.get("/platform/organizations", headers=_auth(support))
    assert res.status_code == 200
    by_id = {o["id"]: o for o in res.json()}
    assert by_id[a.org_id]["orders_count"] == 1
    assert by_id[a.org_id]["users_count"] == 3
    assert by_id[a.org_id]["drivers_count"] == 1

    users = client.get(f"/platform/organizations/{b.org_id}/users", headers=_auth(support)).json()
    assert {u["id"] for u in users} == {b.admin.id, b.manager.id, b.driver.id}


def test_platform_admin_creates_organization_and_its_admin_can_log_in(tenants):
    client, db, a, b, platform_admin, support = tenants
    body = {"name": "فروشگاه قزوین", "slug": "Qazvin-Shop",
            "admin": {"username": "qazvin_admin", "email": "qazvin@example.com", "password": PASSWORD, "full_name": "مدیر قزوین"}}

    assert client.post("/platform/organizations", json=body, headers=_auth(support)).status_code == 403

    res = client.post("/platform/organizations", json=body, headers=_auth(platform_admin))
    assert res.status_code == 201, res.text
    assert res.json()["slug"] == "qazvin-shop"
    assert client.post("/platform/organizations", json=body, headers=_auth(platform_admin)).status_code == 400

    token = client.post("/auth/token", data={"username": "qazvin_admin", "password": PASSWORD}).json()["access_token"]
    me = client.get("/users/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["role"] == "org_admin"
    assert me["organization"]["name"] == "فروشگاه قزوین"
    # سازمان تازه خالی است
    assert client.get("/orders/", headers={"Authorization": f"Bearer {token}"}).json() == []


def test_deactivated_organization_is_locked_out(tenants):
    client, db, a, b, platform_admin, support = tenants

    res = client.patch(f"/platform/organizations/{b.org_id}", json={"is_active": False}, headers=_auth(platform_admin))
    assert res.status_code == 200 and res.json()["is_active"] is False

    assert client.get("/orders/", headers=_auth(b.admin)).status_code == 403
    assert client.post("/auth/token", data={"username": b.admin.username, "password": PASSWORD}).status_code == 403
    # سازمان‌های دیگر تأثیری نمی‌گیرند
    assert client.get("/orders/", headers=_auth(a.admin)).status_code == 200

    client.patch(f"/platform/organizations/{b.org_id}", json={"is_active": True}, headers=_auth(platform_admin))
    assert client.get("/orders/", headers=_auth(b.admin)).status_code == 200


# ---------------------------------------------------------------------------
# محافظ لایه داده: ثبت رکورد بدون سازمان ممکن نیست
# ---------------------------------------------------------------------------

def test_insert_without_organization_is_rejected(api_env):
    _, TestingSession = api_env
    db = TestingSession()
    try:
        db.add(Product(name="بی‌سازمان", sku="ORPHAN", price=1))
        with pytest.raises(TenantMissingError):
            db.commit()
    finally:
        db.rollback()
        db.close()


def test_stock_movements_are_isolated(tenants):
    client, db, a, b, *_ = tenants
    h = _auth(a.admin)

    movements = client.get("/inventory/movements", headers=h).json()
    assert movements and {m["product_id"] for m in movements} == {a.product_id}

    # ثبت گردش یا انتقال روی کالا/انبار سازمان دیگر ممکن نیست
    assert client.post("/inventory/movements", json={"product_id": b.product_id, "movement_type": "receipt", "quantity": 5},
                       headers=h).status_code == 404
    assert client.post("/inventory/transfers", json={"product_id": a.product_id, "from_warehouse_id": a.warehouse_id,
                                                     "to_warehouse_id": b.warehouse_id, "quantity": 1},
                       headers=h).status_code == 404
    assert client.get("/inventory/ledger-check", headers=h).json() == {"ok": True, "mismatches": []}
