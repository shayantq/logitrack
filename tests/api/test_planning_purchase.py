"""درخواست خرید (ت۲۲)، مقایسه (ت۲۳)، ظرفیت فقط‌خواندنی (ت۲۴) و محل دریافت برگشت (ت۲۱)."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from app.core.security import create_access_token
from app.core.tenancy import set_tenant
from app.models import Organization, Product, ProductPrice, RoleEnum, User, Vehicle
from app.models_notification import Notification
from app.models_operations import Location
from app.models_productivity import DriverReturn, PurchaseRequestEvent
from app.services import stock_ledger
from tests.factories import default_warehouse


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
    rival = User(username="rival", email="r@x.io", role=RoleEnum.ORG_ADMIN, hashed_password="x")
    db.add(rival)
    db.commit()
    rival_id = rival.id
    set_tenant(db, org.id)
    warehouse = default_warehouse(db, org.id)
    admin = User(username="adm", email="a@x.io", role=RoleEnum.ORG_ADMIN, hashed_password="x", full_name="ادمین")
    admin2 = User(username="adm2", email="a2@x.io", role=RoleEnum.ORG_ADMIN, hashed_password="x")
    manager = User(username="wm", email="m@x.io", role=RoleEnum.WAREHOUSE_MANAGER, hashed_password="x", warehouse_id=warehouse.id, full_name="مدیر")
    driver = User(username="drv", email="d@x.io", role=RoleEnum.DRIVER, hashed_password="x", full_name="علی", driver_code="D1", driver_status="approved", city="تهران")
    product = Product(name="برنج", sku="RICE-1", barcode="62600001", price=1000, weight_kg=500)
    db.add_all([admin, admin2, manager, driver, product])
    db.commit()
    db.add(ProductPrice(product_id=product.id, effective_from=date(2020, 1, 1), base_price=1000, final_price=1000, cost_price=600))
    vehicle = Vehicle(license_plate="11الف111-11", type="van", capacity_kg=600, driver_id=driver.id, status="available", city="تهران")
    db.add(vehicle)
    inventory = stock_ledger.lock_bucket(db, product.id, warehouse.id, "available", organization_id=org.id)
    document = stock_ledger.new_document(db, "receipt", organization_id=org.id, warehouse_id=warehouse.id, note="اولیه")
    stock_ledger.record(db, inventory, 50, "receipt", document=document, reason="اولیه")
    db.commit()
    yield SimpleNamespace(client=client, db=db, org=org, warehouse=warehouse, admin=admin, admin2=admin2, manager=manager, driver=driver, product=product, vehicle=vehicle,
                          rival=db.get(User, rival_id))
    db.close()


def _create(env, user=None) -> dict:
    res = env.client.post("/purchase-requests/", headers=_auth(user or env.manager), json={"warehouse_id": env.warehouse.id, "note": "کمبود", "lines": [{"product_id": env.product.id, "quantity": 4}]})
    assert res.status_code == 201, res.text
    return res.json()


def _decide(env, request_id, user, approve=True, note=None):
    return env.client.post(f"/purchase-requests/{request_id}/decide", headers=_auth(user), json={"approve": approve, "note": note})


def test_request_keeps_requester_lines_and_estimate(env):
    row = _create(env)
    assert row["status"] == "pending" and row["requested_by"] == "مدیر" and row["warehouse_id"] == env.warehouse.id
    assert row["estimated_total"] == 2400 and row["estimate_complete"] is True and row["lines"][0]["product_name"] == "برنج"


def test_admin_is_notified(env):
    _create(env)
    assert env.db.query(Notification).filter(Notification.link == "/app/purchase-requests").count() == 1


def test_only_organization_admin_decides_and_not_their_own(env):
    row = _create(env)
    assert _decide(env, row["id"], env.manager).status_code == 403
    assert _decide(env, row["id"], env.driver).status_code == 403
    own = _create(env, env.admin)
    assert _decide(env, own["id"], env.admin).status_code == 403
    done = _decide(env, row["id"], env.admin)
    assert done.status_code == 200 and done.json()["status"] == "approved"
    assert [e["action"] for e in done.json()["events"]] == ["created", "approved"]


def test_rejection_needs_a_reason(env):
    row = _create(env)
    assert _decide(env, row["id"], env.admin, approve=False).status_code == 400
    assert _decide(env, row["id"], env.admin, approve=False, note="بودجه نیست").json()["status"] == "rejected"


def test_second_or_conflicting_decision_is_rejected(env):
    row = _create(env)
    assert _decide(env, row["id"], env.admin).status_code == 200
    assert _decide(env, row["id"], env.admin2, approve=False, note="نه").status_code == 400
    assert env.client.post(f"/purchase-requests/{row['id']}/cancel", headers=_auth(env.manager), json={}).status_code == 400
    assert env.db.query(PurchaseRequestEvent).count() == 2


def test_cancel_rules(env):
    row = _create(env)
    assert env.client.post(f"/purchase-requests/{row['id']}/cancel", headers=_auth(env.driver), json={}).status_code == 403
    done = env.client.post(f"/purchase-requests/{row['id']}/cancel", headers=_auth(env.manager), json={})
    assert done.status_code == 200 and done.json()["status"] == "canceled"
    second = _create(env)
    assert env.client.post(f"/purchase-requests/{second['id']}/cancel", headers=_auth(env.admin), json={}).json()["status"] == "canceled"


def test_requests_are_isolated_between_organizations(env):
    row = _create(env)
    assert env.client.get("/purchase-requests/", headers=_auth(env.rival)).json() == []
    assert _decide(env, row["id"], env.rival).status_code == 404


def test_comparison_is_admin_only_and_marks_missing_data(env):
    assert env.client.get("/planning/comparison", headers=_auth(env.manager)).status_code == 403
    res = env.client.get("/planning/comparison", headers=_auth(env.admin))
    assert res.status_code == 200, res.text
    data = res.json()
    assert {m["key"] for m in data["metrics"]} >= {"order_fulfillment", "on_time_delivery"} and all(m["definition"] for m in data["metrics"])
    assert data["warehouses"][0]["values"]["order_fulfillment"]["insufficient"] is True
    assert {t["team"] for t in data["teams"]} == {"warehouse", "fleet", "support", "management"}


def _order(env, quantity=2):
    start = _now() - timedelta(hours=1)
    res = env.client.post("/orders/", headers=_auth(env.admin), json={
        "items": [{"product_id": env.product.id, "quantity": quantity}], "customer": {"name": "مریم", "mobile": "09121112233"},
        "destination_province": "تهران", "destination_city": "تهران", "destination_address": "خیابان آزادی پلاک ۱", "size": "m", "auto_assign": False,
        "warehouse_id": env.warehouse.id, "delivery_window_start": start.isoformat() + "Z", "delivery_window_end": (start + timedelta(hours=8)).isoformat() + "Z"})
    assert res.status_code == 201, res.text
    return res.json()


def test_capacity_shows_the_constraint_and_changes_nothing(env):
    order = _order(env)
    day = (_now() + timedelta(hours=3, minutes=30) - timedelta(hours=1)).date().isoformat()
    bind = env.db.get_bind()
    writes = []

    def watch(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) and "audit" not in statement.lower():
            writes.append(statement)
    event.listen(bind, "before_cursor_execute", watch)
    try:
        data = env.client.get(f"/planning/capacity?day={day}", headers=_auth(env.admin)).json()
    finally:
        event.remove(bind, "before_cursor_execute", watch)
    assert writes == []
    assert data["orders"] == 1 and data["unassigned_orders"] == 1
    assert any(w["kind"] == "orders" for w in data["warnings"]) and data["assumptions"]
    env.client.put(f"/orders/{order['id']}/assign", headers=_auth(env.admin), json={"vehicle_id": env.vehicle.id})
    assert env.client.get(f"/planning/capacity?day={day}", headers=_auth(env.manager)).status_code == 200
    assert env.client.get(f"/planning/capacity?day={day}", headers=_auth(env.driver)).status_code == 403


def test_return_records_receiving_location_without_making_stock_available(env):
    location = Location(warehouse_id=env.warehouse.id, code="RET", barcode="RET", level="bin", location_type="receiving")
    env.db.add(location)
    env.db.commit()
    order = _order(env, quantity=1)
    env.client.put(f"/orders/{order['id']}/assign", headers=_auth(env.admin), json={"vehicle_id": env.vehicle.id})
    for status, extra in (("picked_up", {}), ("in_transit", {}), ("failed", {"failure_reason": "recipient_absent"})):
        assert env.client.put(f"/orders/{order['id']}/status", headers=_auth(env.admin), json={"order_status": status, **extra}).status_code == 200
    assert env.client.post(f"/orders/{order['id']}/resolve-failure", headers=_auth(env.admin), json={"resolution": "return_to_warehouse"}).status_code == 200
    env.db.expire_all()
    row = env.db.query(DriverReturn).one()
    body = {"location_id": location.id, "lines": [{"product_id": env.product.id, "received_quantity": 1}]}
    res = env.client.post(f"/orders/{order['id']}/driver-returns/{row.id}/receive", headers=_auth(env.admin), json=body)
    assert res.status_code in (200, 201), res.text
    assert res.json()["received_location_code"] == "RET"
    wrong = env.client.post(f"/orders/{order['id']}/driver-returns/{row.id}/receive", headers=_auth(env.admin), json=body)
    assert wrong.status_code == 400
