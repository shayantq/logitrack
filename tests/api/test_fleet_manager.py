"""
نقش مدیر ناوگان (ت۲۰): ارسال، خودرو، برنامه راننده، نقشه و استثناهای ناوگان؛ بدون مالی، کمیسیون، مدیریت کاربران و تأیید مدارک.
"""
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core import role_access
from app.core.security import create_access_token
from app.core.tenancy import set_tenant
from app.main import app
from app.models import Organization, Product, RoleEnum, User, Vehicle
from app.models_productivity import OperationException
from app.services import stock_ledger
from tests.factories import default_warehouse

MONEY = ("delivery_fee", "commission_level", "commission_percent", "commission_amount", "driver_earning", "total_price")


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.username, user.id, timedelta(minutes=5))}"}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture()
def env(api_env):
    client, Session = api_env
    db = Session()
    other = Organization(name="دیگر", slug="other-org")
    org = Organization(name="آلفا", slug="alpha")
    db.add_all([org, other])
    db.commit()
    set_tenant(db, other.id)
    outsider = User(username="out_fleet", email="o@x.io", role=RoleEnum.FLEET_MANAGER, hashed_password="x")
    db.add(outsider)
    db.commit()
    outsider_id = outsider.id
    set_tenant(db, org.id)
    warehouse = default_warehouse(db, org.id)
    admin = User(username="adm", email="a@x.io", role=RoleEnum.ORG_ADMIN, hashed_password="x")
    fleet = User(username="fleet", email="f@x.io", role=RoleEnum.FLEET_MANAGER, hashed_password="x", full_name="مدیر ناوگان")
    driver = User(username="drv", email="d@x.io", role=RoleEnum.DRIVER, hashed_password="x", full_name="علی", driver_code="D1", driver_status="approved", city="تهران")
    product = Product(name="برنج", sku="RICE-1", barcode="62600001", price=1000, weight_kg=1)
    db.add_all([admin, fleet, driver, product])
    db.commit()
    vehicle = Vehicle(license_plate="11الف111-11", type="van", capacity_kg=1000, driver_id=driver.id, status="available", city="تهران")
    db.add(vehicle)
    inventory = stock_ledger.lock_bucket(db, product.id, warehouse.id, "available", organization_id=org.id)
    document = stock_ledger.new_document(db, "receipt", organization_id=org.id, warehouse_id=warehouse.id, note="اولیه")
    stock_ledger.record(db, inventory, 50, "receipt", document=document, reason="اولیه")
    db.commit()
    start = _now() - timedelta(hours=1)
    order = client.post("/orders/", headers=_auth(admin), json={
        "items": [{"product_id": product.id, "quantity": 1}], "customer": {"name": "مریم", "mobile": "09121112233"},
        "destination_province": "تهران", "destination_city": "تهران", "destination_address": "خیابان آزادی پلاک ۱", "size": "m", "auto_assign": False,
        "warehouse_id": warehouse.id, "delivery_window_start": start.isoformat() + "Z", "delivery_window_end": (start + timedelta(hours=8)).isoformat() + "Z"}).json()
    yield SimpleNamespace(client=client, db=db, org=org, admin=admin, fleet=fleet, driver=driver, vehicle=vehicle, order=order, outsider=db.get(User, outsider_id), warehouse=warehouse)
    db.close()


def test_every_route_outside_the_allow_list_is_forbidden(env):
    headers = _auth(env.fleet)
    checked = 0
    for template, operations in app.openapi()["paths"].items():
        for method in (m.upper() for m in operations):
            path = re.sub(r"\{[^}]+\}", "1", template)
            if role_access.allows("fleet_manager", method, path) or env.client.request(method, path, json={}).status_code != 401:
                continue
            checked += 1
            assert env.client.request(method, path, headers=headers, json={}).status_code == 403, (method, path)
    assert checked > 200


@pytest.mark.parametrize("method,path", [
    ("GET", "/users/"), ("POST", "/auth/"), ("GET", "/reports/finance"), ("GET", "/inventory/products"), ("GET", "/drivers/applications"),
    ("GET", "/orders/1/timeline"), ("DELETE", "/orders/1"), ("DELETE", "/vehicles/1"), ("POST", "/orders/"), ("GET", "/picking/lists"),
])
def test_forbidden_areas(env, method, path):
    assert env.client.request(method, path, headers=_auth(env.fleet), json={}).status_code in (403, 404)
    assert not role_access.allows("fleet_manager", method, path)


def test_order_data_has_no_money(env):
    order = env.db.get_bind() and env.order
    for res in (env.client.get(f"/orders/{order['id']}", headers=_auth(env.fleet)), env.client.get("/orders/", headers=_auth(env.fleet))):
        assert res.status_code == 200, res.text
        row = res.json() if isinstance(res.json(), dict) else res.json()[0]
        assert all(row.get(key) is None for key in MONEY), {k: row.get(k) for k in MONEY}
        assert all(item["unit_price"] is None for item in row["items"])
        assert row["destination_address"] and row["items"][0]["product_name"] == "برنج"
    admin_view = env.client.get(f"/orders/{order['id']}", headers=_auth(env.admin)).json()
    assert admin_view["total_price"] and admin_view["items"][0]["unit_price"]


def test_fleet_assigns_within_capacity_rules(env):
    url = f"/orders/{env.order['id']}/assign"
    overloaded = Vehicle(license_plate="22ب222-22", type="van", capacity_kg=0, driver_id=env.driver.id, status="inactive", city="تهران")
    env.db.add(overloaded)
    env.db.commit()
    assert env.client.put(url, headers=_auth(env.fleet), json={"vehicle_id": overloaded.id}).status_code == 400
    assert env.client.put(url, headers=_auth(env.fleet), json={"vehicle_id": env.vehicle.id}).status_code == 200


def test_fleet_cannot_mark_delivered_or_decide_a_return(env):
    env.client.put(f"/orders/{env.order['id']}/assign", headers=_auth(env.fleet), json={"vehicle_id": env.vehicle.id})
    status = f"/orders/{env.order['id']}/status"
    assert env.client.put(status, headers=_auth(env.fleet), json={"order_status": "canceled"}).status_code == 400
    assert env.client.put(status, headers=_auth(env.fleet), json={"order_status": "picked_up"}).status_code == 200
    assert env.client.put(status, headers=_auth(env.fleet), json={"order_status": "in_transit"}).status_code == 200
    assert env.client.put(status, headers=_auth(env.fleet), json={"order_status": "delivered"}).status_code == 400
    assert env.client.put(status, headers=_auth(env.fleet), json={"order_status": "failed", "failure_reason": "recipient_absent"}).status_code == 200
    resolve = f"/orders/{env.order['id']}/resolve-failure"
    assert env.client.post(resolve, headers=_auth(env.fleet), json={"resolution": "return_to_warehouse"}).status_code == 403


def test_fleet_sees_only_fleet_exceptions(env):
    for index, team in enumerate(("fleet", "warehouse"), start=1):
        env.db.add(OperationException(organization_id=env.org.id, kind="driver_incident" if team == "fleet" else "pick_short", entity_type="order", entity_id=index, severity="high",
                                      team=team, status="open", opened_at=_now(), trigger_reason="دلیل", suggested_action="اقدام"))
    env.db.commit()
    rows = env.client.get("/exceptions/", headers=_auth(env.fleet)).json()
    assert [r["team"] for r in rows] == ["fleet"]
    hidden = env.db.query(OperationException).filter(OperationException.team == "warehouse").one()
    assert env.client.get(f"/exceptions/{hidden.id}", headers=_auth(env.fleet)).status_code == 404


def test_fleet_manages_vehicles_and_schedules(env):
    assert env.client.get("/vehicles/", headers=_auth(env.fleet)).status_code == 200
    assert env.client.get("/dispatch/schedules", headers=_auth(env.fleet)).status_code == 200
    assert env.client.get("/map/orders", headers=_auth(env.fleet)).status_code == 200
    assert env.client.delete(f"/vehicles/{env.vehicle.id}", headers=_auth(env.fleet)).status_code == 403


def test_other_organization_is_isolated(env):
    assert env.client.get(f"/orders/{env.order['id']}", headers=_auth(env.outsider)).status_code == 404
    assert env.client.get(f"/vehicles/{env.vehicle.id}", headers=_auth(env.outsider)).status_code == 404


def test_orders_sort_is_validated(env):
    assert env.client.get("/orders/?sort=delivery_window_start&direction=asc", headers=_auth(env.admin)).status_code == 200
    assert env.client.get("/orders/?sort=driver_earning", headers=_auth(env.admin)).status_code == 422
    assert env.client.get("/exceptions/?sort=due_at", headers=_auth(env.admin)).status_code == 200
    assert env.client.get("/exceptions/?sort=nope", headers=_auth(env.admin)).status_code == 422
