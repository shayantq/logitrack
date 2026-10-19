"""
تست‌های سطح API (با TestClient) برای مسیرهایی که قبلاً خطای ۵۰۰ می‌دادند
یا دسترسی نادرست داشتند. دیتابیس: SQLite درون‌حافظه‌ای با StaticPool تا
ترد TestClient و ترد تست یک اتصال مشترک ببینند.
"""
from datetime import timedelta

import pytest
from app.core.security import create_access_token
from app.core.tenancy import set_tenant
from app.models import User, RoleEnum, Vehicle, Product, Inventory, Organization
from tests.factories import order_request, order_payload


@pytest.fixture()
def api(api_env):
    client, TestingSession = api_env
    db = TestingSession()
    org = Organization(name="سازمان API", slug="api-org")
    db.add(org)
    db.commit()
    set_tenant(db, org.id)
    try:
        yield client, db
    finally:
        db.close()


def _user(db, role, tag, email=True):
    user = User(username=f"{role.value}_{tag}", email=f"{tag}@test.local" if email else None,
                role=role, hashed_password="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth(user):
    token = create_access_token(user.username, user.id, timedelta(minutes=5))
    return {"Authorization": f"Bearer {token}"}


def _order_payload(product_id, vehicle_id, **overrides):
    return order_payload(product_id, vehicle_id, delivery_window_start="2026-10-10T10:00:00Z",
                         delivery_window_end="2026-10-11T10:00:00Z", **overrides)


@pytest.fixture()
def world(api):
    client, db = api
    admin = _user(db, RoleEnum.ORG_ADMIN, "admin")
    driver = _user(db, RoleEnum.DRIVER, "driver")
    vehicle = Vehicle(license_plate="API-1", type="van", capacity_kg=1000, status="available", driver_id=driver.id)
    product = Product(name="کالا", sku="API-SKU", price=10, weight_kg=1)
    db.add_all([vehicle, product])
    db.commit()
    db.add(Inventory(product_id=product.id, quantity=10))
    db.commit()
    return client, db, admin, driver, vehicle, product


def test_stats_summary_no_longer_500(world):
    client, db, admin, driver, vehicle, product = world
    client.post("/orders/", json=_order_payload(product.id, vehicle.id), headers=_auth(admin))

    res = client.get("/orders/stats/summary", headers=_auth(admin))
    assert res.status_code == 200, res.text
    assert res.json()["metrics"]["active_orders"] == 1
    assert len(res.json()["recent_orders"]) == 1

    assert client.get("/orders/stats/summary", headers=_auth(driver)).status_code == 403


def test_users_list_with_user_without_email(world):
    client, db, admin, *_ = world
    _user(db, RoleEnum.DRIVER, "noemail", email=False)
    res = client.get("/users/", headers=_auth(admin))
    assert res.status_code == 200, res.text


def test_invalid_enum_values_return_422_not_500(world):
    client, db, admin, driver, vehicle, product = world
    assert client.post("/orders/", json=_order_payload(product.id, vehicle.id, size="huge"), headers=_auth(admin)).status_code == 422
    assert client.get("/orders/?order_status=bogus", headers=_auth(admin)).status_code == 422
    bad_user = {"username": "xx_bad", "email": "bad@example.com", "role": "superuser", "password": "secret123"}
    assert client.post("/auth/", json=bad_user, headers=_auth(admin)).status_code == 422


def test_driver_cannot_read_foreign_order(world):
    client, db, admin, driver, vehicle, product = world
    order_id = client.post("/orders/", json=_order_payload(product.id, vehicle.id), headers=_auth(admin)).json()["id"]
    stranger = _user(db, RoleEnum.DRIVER, "stranger")

    assert client.get(f"/orders/{order_id}", headers=_auth(stranger)).status_code == 404
    assert client.get(f"/vehicles/{vehicle.id}", headers=_auth(stranger)).status_code == 404
    assert client.get(f"/orders/{order_id}", headers=_auth(driver)).status_code == 200


def test_order_dates_are_iso_formatted(world):
    client, db, admin, driver, vehicle, product = world
    body = client.post("/orders/", json=_order_payload(product.id, vehicle.id), headers=_auth(admin)).json()
    assert body["delivery_window_start"].startswith("2026-10-10T10:00:00")


def test_create_product_endpoint_returns_json(world):
    client, db, admin, *_ = world
    res = client.post("/inventory/products", json={"name": "میز", "sku": "DESK-1", "price": 5, "weight_kg": 12.5},
                      headers=_auth(admin))
    assert res.status_code == 201, res.text
    assert res.json()["product"]["weight_kg"] == 12.5


def test_health_endpoint(api):
    client, _ = api
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_cors_disabled_by_default(world):
    client, *_ = world
    res = client.get("/users/me", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in res.headers


def test_order_api_returns_items_customer_and_history(world):
    client, db, admin, driver, vehicle, product = world
    res = client.post("/orders/", json=_order_payload(product.id, None, auto_assign=False), headers=_auth(admin))
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "pending" and body["tracking_code"].startswith("LT-")
    assert body["items"][0]["product_name"] == product.name
    assert body["customer"]["mobile"] == "09120000000"
    assert [h["to_status"] for h in body["history"]] == ["pending"]

    assigned = client.put(f"/orders/{body['id']}/assign", json={"vehicle_id": vehicle.id}, headers=_auth(admin))
    assert assigned.status_code == 200 and assigned.json()["status"] == "assigned"

    moved = client.put(f"/orders/{body['id']}/status", json={"order_status": "picking_up", "note": "حرکت"}, headers=_auth(driver))
    assert moved.status_code == 200
    history = client.get(f"/orders/{body['id']}", headers=_auth(admin)).json()["history"]
    assert [h["to_status"] for h in history] == ["pending", "assigned", "picking_up"]
    assert history[-1]["note"] == "حرکت" and history[-1]["changed_by_name"]


def test_order_api_validates_address_and_contact(world):
    client, db, admin, driver, vehicle, product = world
    bad_province = _order_payload(product.id, vehicle.id, destination_province="کالیفرنیا")
    bad_mobile = _order_payload(product.id, vehicle.id, customer={"name": "x y", "mobile": "12345"})
    no_items = {**_order_payload(product.id, vehicle.id), "items": []}
    for payload in (bad_province, bad_mobile, no_items):
        assert client.post("/orders/", json=payload, headers=_auth(admin)).status_code == 422
