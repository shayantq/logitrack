"""
مرحله ۶ راهنمای عملیات (docs/operations-guide.md): خانه مدیرعامل با ریزش و برچسب برآورد، کار امروز انبار، و فهرست شروع سازمان تازه.
"""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core.security import create_access_token
from app.core.tenancy import set_tenant
from app.models import Order, Organization, Product, ProductPrice, RoleEnum, User, Vehicle, Warehouse
from app.models_operations import PutawayTask
from app.models_productivity import OperationException
from app.services import stock_ledger
from tests.factories import default_warehouse


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.username, user.id, timedelta(minutes=5))}"}


@pytest.fixture()
def env(api_env):
    client, Session = api_env
    db = Session()
    org = Organization(name="آلفا", slug="alpha")
    db.add(org)
    db.commit()
    set_tenant(db, org.id)
    warehouse = default_warehouse(db, org.id)
    admin = User(username="adm", email="a@x.io", role=RoleEnum.ORG_ADMIN, hashed_password="x", full_name="ادمین")
    manager = User(username="wm", email="m@x.io", role=RoleEnum.WAREHOUSE_MANAGER, hashed_password="x", warehouse_id=warehouse.id)
    driver = User(username="drv", email="d@x.io", role=RoleEnum.DRIVER, hashed_password="x", full_name="علی", driver_code="D1", driver_status="approved")
    db.add_all([admin, manager, driver])
    db.commit()
    yield SimpleNamespace(client=client, db=db, org=org, warehouse=warehouse, admin=admin, manager=manager, driver=driver)
    db.close()


def _stock(env, quantity=100, reorder_point=None) -> Product:
    product = Product(name="برنج", sku="RICE-1", barcode="62600001", price=1000, weight_kg=1)
    env.db.add(product)
    env.db.commit()
    inventory = stock_ledger.lock_bucket(env.db, product.id, env.warehouse.id, "available", organization_id=env.org.id)
    document = stock_ledger.new_document(env.db, "receipt", organization_id=env.org.id, warehouse_id=env.warehouse.id, note="اولیه")
    stock_ledger.record(env.db, inventory, quantity, "receipt", document=document, reason="اولیه")
    if reorder_point is not None:
        inventory.reorder_point = reorder_point
    env.db.commit()
    return product


def _order(env, product, *, start=None, vehicle=None) -> dict:
    start = start or _now() - timedelta(hours=1)
    res = env.client.post("/orders/", headers=_auth(env.admin), json={
        "items": [{"product_id": product.id, "quantity": 2}], "customer": {"name": "مریم", "mobile": "09121112233"},
        "destination_province": "تهران", "destination_city": "تهران", "destination_address": "خیابان آزادی پلاک ۱", "size": "m",
        "vehicle_id": vehicle.id if vehicle else None, "warehouse_id": env.warehouse.id, "auto_assign": False,
        "delivery_window_start": start.isoformat() + "Z", "delivery_window_end": (start + timedelta(hours=8)).isoformat() + "Z"})
    assert res.status_code == 201, res.text
    return res.json()


def _business(env) -> dict:
    res = env.client.get("/home/business", headers=_auth(env.admin))
    assert res.status_code == 200, res.text
    return res.json()


# ---------------------------------------------------------------------------
# دسترسی
# ---------------------------------------------------------------------------
def test_business_view_is_only_for_the_organization_admin(env):
    assert env.client.get("/home/business", headers=_auth(env.manager)).status_code == 403
    assert env.client.get("/home/business", headers=_auth(env.driver)).status_code == 403
    assert env.client.get("/home/business").status_code == 401


def test_driver_has_no_warehouse_home(env):
    assert env.client.get("/home/warehouse", headers=_auth(env.driver)).status_code == 403


# ---------------------------------------------------------------------------
# سلامت کسب‌وکار
# ---------------------------------------------------------------------------
def test_empty_organization_gets_a_setup_checklist(api_env):
    client, Session = api_env
    db = Session()
    org = Organization(name="تازه", slug="fresh")
    db.add(org)
    db.commit()
    set_tenant(db, org.id)
    admin = User(username="new_adm", email="n@x.io", role=RoleEnum.ORG_ADMIN, hashed_password="x")
    db.add(admin)
    db.commit()
    data = client.get("/home/business", headers=_auth(admin)).json()
    assert [s["key"] for s in data["setup"]] == ["warehouse", "product", "vehicle", "driver", "order"]
    assert not any(s["done"] for s in data["setup"][1:])
    db.close()


def test_setup_steps_finish_as_the_organization_fills_in(env):
    product = _stock(env)
    env.db.add(Vehicle(license_plate="11الف111-11", type="van", capacity_kg=1000, driver_id=env.driver.id, status="available"))
    env.db.commit()
    assert {s["key"]: s["done"] for s in _business(env)["setup"]}["order"] is False
    _order(env, product)
    assert all(s["done"] for s in _business(env)["setup"])


def test_every_number_links_to_its_list(env):
    data = _business(env)
    assert data["generated_at"]
    assert data["stock"]["link"] == "/app/reorder" and data["exceptions"]["link"].startswith("/app/exceptions")
    assert {k["key"] for k in data["kpis"]} == {"on_time_delivery", "order_fulfillment", "fill_rate", "failed_attempt_rate", "inventory_accuracy"}
    assert all(k["link"].startswith("/app/") for k in data["kpis"])


def test_late_order_is_counted_with_one_cause(env):
    product = _stock(env)
    _order(env, product, start=_now() - timedelta(hours=12))
    delays = _business(env)["delays"]
    assert delays["late"] == 1 and sum(c["count"] for c in delays["causes"]) == 1
    assert delays["causes"][0]["key"] == "vehicle" and delays["causes"][0]["link"] == "/app/orders?order_status=pending"


def test_low_and_out_of_stock_match_reorder_points(env):
    _stock(env, quantity=3, reorder_point=10)
    assert _business(env)["stock"] == {"out": 0, "low": 1, "link": "/app/reorder"}


def test_urgent_exceptions_are_counted_by_severity(env):
    for index, (severity, status) in enumerate((("critical", "open"), ("high", "acknowledged"), ("low", "open"), ("critical", "resolved")), start=1):
        env.db.add(OperationException(organization_id=env.org.id, kind="backorder_open", entity_type="backorder", entity_id=index, severity=severity, team="warehouse",
                                      status=status, opened_at=_now(), trigger_reason="دلیل", suggested_action="اقدام"))
    env.db.commit()
    summary = _business(env)["exceptions"]
    assert summary["critical"] == 1 and summary["high"] == 1


def test_money_is_labeled_an_estimate_and_uses_recorded_values(env):
    product = _stock(env)
    env.db.add(ProductPrice(product_id=product.id, effective_from=date(2020, 1, 1), base_price=1000, final_price=1000, cost_price=600))
    env.db.commit()
    order = env.db.get(Order, _order(env, product)["id"])
    order.status, order.delivered_at, order.delivery_fee, order.commission_amount, order.driver_earning = "delivered", _now(), 5000, 1000, 4000
    for item in order.items:
        item.unit_price = 1000
    env.db.commit()
    money = _business(env)["money"]
    assert money["estimated"] is True
    assert (money["trips"], money["fare"], money["company_share"], money["driver_share"]) == (1, 5000, 1000, 4000)
    assert (money["goods_sales"], money["goods_margin"]) == (2000, 800)
    assert (money["cost_coverage_lines"], money["total_lines"]) == (1, 1)
    assert money["top_products"] == [{"product_id": product.id, "name": "برنج", "margin": 800}]


def test_missing_cost_is_reported_not_assumed_zero(env):
    product = _stock(env)
    order = env.db.get(Order, _order(env, product)["id"])
    order.status, order.delivered_at = "delivered", _now()
    env.db.commit()
    money = _business(env)["money"]
    assert money["goods_margin"] == 0 and (money["cost_coverage_lines"], money["total_lines"]) == (0, 1)


# ---------------------------------------------------------------------------
# کار امروز انبار
# ---------------------------------------------------------------------------
def test_warehouse_today_is_scoped_to_the_manager_warehouse(env):
    product = _stock(env)
    other = Warehouse(code="OTHER", name="دیگر")
    env.db.add(other)
    env.db.commit()
    for warehouse in (env.warehouse, other):
        env.db.add(PutawayTask(code=f"PA-{warehouse.code}", warehouse_id=warehouse.id, product_id=product.id, stock_status="available", quantity=5, status="open"))
    env.db.commit()
    data = env.client.get("/home/warehouse", headers=_auth(env.manager)).json()
    counts = {i["key"]: i["count"] for i in data["items"]}
    assert data["warehouse_id"] == env.warehouse.id and counts["putaway"] == 1
    assert {i["key"] for i in data["items"]} == {"receipts", "putaway", "picks", "shipments", "shortages", "counts", "exceptions"}
    admin = {i["key"]: i["count"] for i in env.client.get("/home/warehouse", headers=_auth(env.admin)).json()["items"]}
    assert admin["putaway"] == 2


def test_manager_without_a_warehouse_gets_a_clear_error(env):
    env.manager.warehouse_id = None
    env.db.commit()
    assert env.client.get("/home/warehouse", headers=_auth(env.manager)).status_code == 400
