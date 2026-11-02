"""
نقش اپراتور انبار (ت۱۸): رد پیش‌فرض همه مسیرها جز فهرست مجاز، محدود به انبار خودش، و برداشتن کار از صف.
"""
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core import role_access
from app.core.security import create_access_token
from app.core.tenancy import set_tenant
from app.main import app
from app.models import Organization, Product, RoleEnum, User, Warehouse
from app.models_operations import Location, PutawayTask
from app.services import stock_ledger, work_claim_service
from tests.factories import default_warehouse


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.username, user.id, timedelta(minutes=5))}"}


@pytest.fixture()
def env(api_env):
    client, Session = api_env
    db = Session()
    other_org = Organization(name="دیگر", slug="other-org")
    org = Organization(name="آلفا", slug="alpha")
    db.add_all([org, other_org])
    db.commit()
    set_tenant(db, other_org.id)
    outsider = User(username="out_op", email="out@x.io", role=RoleEnum.WAREHOUSE_OPERATOR, hashed_password="x", warehouse_id=default_warehouse(db, other_org.id).id)
    db.add(outsider)
    db.commit()
    outsider_id = outsider.id
    set_tenant(db, org.id)
    warehouse = default_warehouse(db, org.id)
    second = Warehouse(code="W2", name="دوم")
    db.add(second)
    db.commit()
    admin = User(username="adm", email="a@x.io", role=RoleEnum.ORG_ADMIN, hashed_password="x")
    manager = User(username="wm", email="m@x.io", role=RoleEnum.WAREHOUSE_MANAGER, hashed_password="x", warehouse_id=warehouse.id)
    op1 = User(username="op1", email="o1@x.io", role=RoleEnum.WAREHOUSE_OPERATOR, hashed_password="x", warehouse_id=warehouse.id, full_name="اپراتور یک")
    op2 = User(username="op2", email="o2@x.io", role=RoleEnum.WAREHOUSE_OPERATOR, hashed_password="x", warehouse_id=warehouse.id)
    far = User(username="op3", email="o3@x.io", role=RoleEnum.WAREHOUSE_OPERATOR, hashed_password="x", warehouse_id=second.id)
    product = Product(name="برنج", sku="RICE-1", barcode="62600001", price=1000, weight_kg=1)
    source = Location(warehouse_id=warehouse.id, code="SRC", barcode="SRC", level="bin", location_type="receiving")
    target = Location(warehouse_id=warehouse.id, code="DST", barcode="DST", level="bin", location_type="storage")
    db.add_all([admin, manager, op1, op2, far, product, source, target])
    db.commit()
    inventory = stock_ledger.lock_bucket(db, product.id, warehouse.id, "available", organization_id=org.id)
    document = stock_ledger.new_document(db, "receipt", organization_id=org.id, warehouse_id=warehouse.id, note="اولیه")
    stock_ledger.record(db, inventory, 5, "receipt", document=document, reason="اولیه", lines=[(stock_ledger.StockKey(location_id=source.id), 5)])
    task = PutawayTask(code="PT-1", warehouse_id=warehouse.id, product_id=product.id, stock_status="available", quantity=5, status="open", source_location_id=source.id)
    db.add(task)
    db.commit()
    yield SimpleNamespace(client=client, db=db, org=org, warehouse=warehouse, second=second, admin=admin, manager=manager, op1=op1, op2=op2, far=far,
                          outsider=db.get(User, outsider_id), product=product, task=task, source=source, target=target)
    db.close()


ALLOWED = re.compile(r"^/(users/me|auth/|notifications|organization/(profile|logo)|picking/l|putaway/tasks|inbound/receipts)")


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


def test_every_route_outside_the_allow_list_is_forbidden(env):
    """اگر مسیر تازه‌ای اضافه شود، این آزمون بدون تغییر فهرست هم آن را می‌سنجد."""
    headers = _auth(env.op1)
    checked = 0
    for template, operations in app.openapi()["paths"].items():
        for method in (m.upper() for m in operations):
            path = _concrete(template)
            if role_access.allows("warehouse_operator", method, path):
                assert ALLOWED.match(path), f"{method} {path} نباید مجاز باشد"
                continue
            # مسیر عمومی بدون ورود هم پاسخ می‌دهد؛ فقط مسیرهایی که ورود می‌خواهند باید برای این نقش بسته باشند
            if env.client.request(method, path, json={}).status_code != 401:
                continue
            checked += 1
            assert env.client.request(method, path, headers=headers, json={}).status_code == 403, (method, path)
    assert checked > 200


@pytest.mark.parametrize("method,path", [
    ("GET", "/users/"), ("GET", "/orders/"), ("GET", "/reports/stats"), ("GET", "/inventory/products"), ("GET", "/warehouses/"),
    ("POST", "/picking/lists"), ("POST", "/picking/lists/1/cancel"), ("POST", "/putaway/tasks"), ("POST", "/putaway/tasks/1/cancel"),
    ("POST", "/inbound/receipts"), ("POST", "/inbound/receipts/1/close"), ("POST", "/inbound/receipts/1/cancel"), ("GET", "/activity"),
])
def test_sensitive_paths_are_rejected_by_the_backend(env, method, path):
    assert env.client.request(method, path, headers=_auth(env.op1), json={}).status_code in (403, 404)
    assert not role_access.allows("warehouse_operator", method, path)


def test_operator_only_sees_their_own_warehouse(env):
    res = env.client.get("/putaway/tasks?status=active", headers=_auth(env.op1))
    assert res.status_code == 200 and [t["code"] for t in res.json()] == ["PT-1"]
    assert env.client.get("/putaway/tasks?status=active", headers=_auth(env.far)).json() == []
    assert env.client.get(f"/putaway/tasks?warehouse_id={env.second.id}", headers=_auth(env.op1)).status_code == 403
    assert env.client.get(f"/putaway/tasks/{env.task.id}", headers=_auth(env.far)).status_code == 403
    assert env.client.post(f"/putaway/tasks/{env.task.id}/claim", headers=_auth(env.far)).status_code == 403


def test_other_organization_gets_nothing(env):
    env.client.get("/users/me", headers=_auth(env.outsider))
    assert env.client.get(f"/putaway/tasks/{env.task.id}", headers=_auth(env.outsider)).status_code == 404
    assert env.client.post(f"/putaway/tasks/{env.task.id}/claim", headers=_auth(env.outsider)).status_code == 404


def _execute(env, user, quantity=5):
    return env.client.post(f"/putaway/tasks/{env.task.id}/execute", headers=_auth(user), json={
        "product_scan": "RICE-1", "source_scan": "SRC", "destination_scan": "DST", "quantity": quantity})


def test_operator_must_claim_before_working(env):
    assert _execute(env, env.op1).status_code == 400
    assert env.client.post(f"/putaway/tasks/{env.task.id}/claim", headers=_auth(env.op1)).status_code == 200
    res = _execute(env, env.op1)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "done" and res.json()["claimed_by_id"] is None


def test_second_operator_cannot_claim_or_execute_a_held_task(env):
    url = f"/putaway/tasks/{env.task.id}"
    assert env.client.post(f"{url}/claim", headers=_auth(env.op1)).status_code == 200
    assert env.client.post(f"{url}/claim", headers=_auth(env.op2)).status_code == 400
    assert _execute(env, env.op2).status_code == 400
    assert env.client.post(f"{url}/release", headers=_auth(env.op2)).status_code == 403
    assert env.client.post(f"{url}/release", headers=_auth(env.op1)).status_code == 200
    assert env.client.post(f"{url}/claim", headers=_auth(env.op2)).status_code == 200


def test_expired_claim_returns_to_the_queue(env):
    url = f"/putaway/tasks/{env.task.id}"
    env.client.post(f"{url}/claim", headers=_auth(env.op1))
    env.db.expire_all()
    task = env.db.get(PutawayTask, env.task.id)
    task.claimed_until = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    env.db.commit()
    assert _execute(env, env.op1).status_code == 400
    assert env.client.post(f"{url}/claim", headers=_auth(env.op2)).status_code == 200


def test_manager_keeps_oversight_without_claiming(env):
    env.client.post(f"/putaway/tasks/{env.task.id}/claim", headers=_auth(env.op1))
    listed = env.client.get("/putaway/tasks?status=active", headers=_auth(env.manager)).json()[0]
    assert listed["claimed_by_name"] == "اپراتور یک"
    assert env.client.post(f"/putaway/tasks/{env.task.id}/release", headers=_auth(env.manager)).status_code == 200
    assert _execute(env, env.manager).status_code == 200


def test_operator_needs_a_warehouse_at_creation(env):
    body = {"username": "new_op", "email": "n@x.io", "role": "warehouse_operator", "password": "Password-123", "full_name": "تازه"}
    assert env.client.post("/auth/", headers=_auth(env.admin), json=body).status_code == 400
    res = env.client.post("/auth/", headers=_auth(env.admin), json={**body, "warehouse_id": env.warehouse.id})
    assert res.status_code == 201, res.text


def test_claim_duration_is_short(env):
    assert work_claim_service.CLAIM_DURATION <= timedelta(minutes=30)
