"""
مرحله ۴ راهنمای عملیات (docs/operations-guide.md): تعلیق مرحله‌ای، پلن و سقف، سهمیه خروجی، دسترسی موقت پشتیبانی،
پرچم قابلیت، خروجی داده و چرخه خروج سازمان.
"""
import csv
import io
import zipfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core import storage
from app.core.security import create_access_token
from app.core.tenancy import set_tenant
from app.models import AuditLog, Customer, Order, Organization, Product, RoleEnum, StockMovement, User, Vehicle
from app.models_productivity import TenantExport
from app.services import platform_service, stock_ledger
from tests.factories import default_warehouse


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.username, user.id, timedelta(minutes=5))}"}


def _world(db, slug):
    org = Organization(name=f"سازمان {slug}", slug=slug)
    db.add(org)
    db.commit()
    set_tenant(db, org.id)
    warehouse = default_warehouse(db, org.id)
    admin = User(username=f"{slug}_adm", email=f"{slug}@x.io", role=RoleEnum.ORG_ADMIN, hashed_password="hash-secret", full_name="ادمین")
    driver = User(username=f"{slug}_drv", email=f"{slug}d@x.io", role=RoleEnum.DRIVER, hashed_password="x", full_name="علی", driver_code=f"D{slug}", driver_status="approved")
    db.add_all([admin, driver])
    db.commit()
    vehicle = Vehicle(license_plate=f"11{slug[:1]}111-11", type="van", capacity_kg=1000, driver_id=driver.id, status="available")
    product = Product(name="برنج", sku=f"RICE-{slug}", barcode=f"6260{slug}", price=1000, weight_kg=1)
    db.add_all([vehicle, product])
    db.commit()
    inventory = stock_ledger.lock_bucket(db, product.id, warehouse.id, "available", organization_id=org.id)
    document = stock_ledger.new_document(db, "receipt", organization_id=org.id, warehouse_id=warehouse.id, note="اولیه")
    stock_ledger.record(db, inventory, 100, "receipt", document=document, reason="اولیه")
    db.commit()
    return SimpleNamespace(org=org, warehouse=warehouse, admin=admin, driver=driver, vehicle=vehicle, product=product)


@pytest.fixture()
def env(api_env, tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "MEDIA_ROOT", tmp_path)
    client, Session = api_env
    db = Session()
    a = _world(db, "alpha")
    b = _world(db, "beta")
    set_tenant(db, None)
    root = User(username="root", email="r@x.io", role=RoleEnum.PLATFORM_ADMIN, hashed_password="x")
    support = User(username="sup", email="s@x.io", role=RoleEnum.PLATFORM_SUPPORT, hashed_password="x")
    db.add_all([root, support])
    db.commit()
    set_tenant(db, a.org.id)
    yield SimpleNamespace(client=client, db=db, Session=Session, a=a, b=b, root=root, support=support, media=tmp_path)
    db.close()


def _order(env, w=None, **extra):
    w = w or env.a
    start = _now() - timedelta(hours=1)
    return env.client.post("/orders/", headers=_auth(w.admin), json={
        "items": [{"product_id": w.product.id, "quantity": 1}], "customer": {"name": "مریم احمدی", "mobile": "09121112233"},
        "destination_province": "تهران", "destination_city": "تهران", "destination_address": "خیابان آزادی پلاک ۱", "size": "m",
        "vehicle_id": w.vehicle.id, "warehouse_id": w.warehouse.id, "delivery_window_start": start.isoformat() + "Z",
        "delivery_window_end": (start + timedelta(hours=8)).isoformat() + "Z", **extra})


def _suspend(env, org=None, slug=None, user=None):
    org = org or env.a.org
    return env.client.post(f"/platform/organizations/{org.id}/suspend", headers=_auth(user or env.root), json={"reason": "بدهی معوق", "confirm_slug": slug or org.slug})


# ---------------------------------------------------------------------------
# تعلیق
# ---------------------------------------------------------------------------
def test_suspension_needs_typed_slug_and_blocks_only_new_work(env):
    assert _suspend(env, slug="beta").status_code == 400
    assert _suspend(env, user=env.support).status_code == 403
    active = _order(env).json()
    assert _suspend(env).status_code == 200
    assert _order(env).status_code == 403
    staff = env.client.post("/auth/", headers=_auth(env.a.admin), json={"username": "during_stop", "email": "ds@x.io", "role": "driver", "password": "Secret-pass-123"})
    assert staff.status_code == 403                                                                  # مسیر auth هم کار تازه را نمی‌گذراند
    assert env.client.get("/orders/", headers=_auth(env.a.admin)).status_code == 200                 # خواندن آزاد است
    url = f"/orders/{active['id']}/status"
    assert env.client.put(url, headers=_auth(env.a.driver), json={"order_status": "picked_up"}).status_code == 200   # سفر تمام می‌شود
    assert env.client.put(url, headers=_auth(env.a.driver), json={"order_status": "in_transit"}).status_code == 200
    assert env.client.put(url, headers=_auth(env.a.driver), json={"order_status": "delivered"}).status_code == 200
    assert _order(env, env.b).status_code == 201                                                     # سازمان دیگر اثر نمی‌گیرد
    me = env.client.get("/users/me", headers=_auth(env.a.admin)).json()
    assert me["organization"]["suspended"] is True
    assert env.client.post(f"/platform/organizations/{env.a.org.id}/resume", headers=_auth(env.root), json={"reason": "پرداخت شد"}).status_code == 200
    assert _order(env).status_code == 201
    env.db.expire_all()
    assert env.db.query(AuditLog).filter(AuditLog.action == "platform.org_suspend").execution_options(skip_tenant_filter=True).one().reason == "بدهی معوق"


def test_deactivation_also_needs_typed_slug(env):
    url = f"/platform/organizations/{env.b.org.id}"
    assert env.client.patch(url, headers=_auth(env.root), json={"is_active": False}).status_code == 400
    assert env.client.patch(url, headers=_auth(env.root), json={"is_active": False, "confirm_slug": "beta"}).status_code == 200
    assert env.client.patch(url, headers=_auth(env.root), json={"is_active": True}).status_code == 200


# ---------------------------------------------------------------------------
# پلن
# ---------------------------------------------------------------------------
def _plan(env, plan, org=None):
    org = org or env.a.org
    return env.client.put(f"/platform/organizations/{org.id}/plan", headers=_auth(env.root), json={"plan_id": plan, "reason": "درخواست مشتری"})


def test_existing_organizations_keep_everything_on_enterprise(env):
    res = env.client.get(f"/platform/organizations/{env.a.org.id}/plan", headers=_auth(env.support))
    assert res.json()["plan_id"] == "enterprise" and {r["key"] for r in res.json()["resources"]} == {"warehouses", "drivers", "orders", "users"}
    assert set(env.client.get("/users/me", headers=_auth(env.a.admin)).json()["plan_modules"]) >= {"reorder", "stocktake"}


def test_downgrade_has_grace_and_never_breaks_open_work(env):
    open_order = _order(env).json()
    res = _plan(env, "basic")
    assert res.status_code == 200 and res.json()["grace_until"] and res.json()["version"] == 2
    assert _order(env).status_code == 201                                                            # در مهلت
    assert env.client.get("/users/me", headers=_auth(env.a.admin)).json()["plan_modules"] == []
    org = env.db.get(Organization, env.a.org.id)
    org.plan_grace_until = _now() - timedelta(minutes=1)
    env.db.query(Organization).filter(Organization.id == org.id).update({"plan_grace_until": org.plan_grace_until})
    env.db.commit()
    assert env.client.put(f"/orders/{open_order['id']}/status", headers=_auth(env.a.driver), json={"order_status": "picked_up"}).status_code == 200
    # سقف پایه ۵۰۰ سفارش است؛ با سقف کوچک‌تر تست می‌کنیم
    original = platform_service.PLANS["basic"]["orders"]
    platform_service.PLANS["basic"]["orders"] = 2
    try:
        blocked = _order(env)
        assert blocked.status_code == 400 and "سقف" in blocked.json()["detail"]
    finally:
        platform_service.PLANS["basic"]["orders"] = original


def test_user_limit_blocks_only_new_staff(env):
    original = platform_service.PLANS["enterprise"]["users"]
    platform_service.PLANS["enterprise"]["users"] = 1
    try:
        res = env.client.post("/auth/", headers=_auth(env.a.admin), json={"username": "new_staff", "email": "n@x.io", "full_name": "کارمند تازه", "role": "warehouse_manager", "password": "Secret-pass-123", "warehouse_id": env.a.warehouse.id})
        assert res.status_code == 400 and "سقف" in res.json()["detail"]
    finally:
        platform_service.PLANS["enterprise"]["users"] = original


# ---------------------------------------------------------------------------
# سهمیه خروجی
# ---------------------------------------------------------------------------
def test_report_quota_is_per_organization(env, monkeypatch):
    from app.routers import reports
    reports.report_quota.reset()
    calls = []
    monkeypatch.setattr(reports.generate_report_task, "delay", lambda *a, **k: calls.append(a) or SimpleNamespace(id="t1"))
    url = "/reports/export/inventory/excel"
    for _ in range(reports.report_quota.max_requests):
        assert env.client.post(url, headers=_auth(env.a.admin)).status_code == 202
    assert env.client.post(url, headers=_auth(env.a.admin)).status_code == 429
    assert env.client.post(url, headers=_auth(env.b.admin)).status_code == 202
    reports.report_quota.reset()


# ---------------------------------------------------------------------------
# دسترسی موقت پشتیبانی
# ---------------------------------------------------------------------------
def test_support_access_is_temporary_reason_bound_and_audited(env):
    _order(env)
    url = f"/platform/organizations/{env.a.org.id}/support-access"
    view = f"/platform/organizations/{env.a.org.id}/support-view"
    assert env.client.get(view, headers=_auth(env.support)).status_code == 403
    assert env.client.post(url, headers=_auth(env.support), json={"user_id": env.support.id, "reason": "بررسی تیکت", "minutes": 30}).status_code == 403
    assert env.client.post(url, headers=_auth(env.root), json={"user_id": env.a.admin.id, "reason": "بررسی تیکت", "minutes": 30}).status_code == 400
    grant = env.client.post(url, headers=_auth(env.root), json={"user_id": env.support.id, "reason": "بررسی تیکت", "minutes": 30}).json()
    res = env.client.get(view, headers=_auth(env.support))
    assert res.status_code == 200 and len(res.json()["orders"]) == 1
    assert "09121112233" not in res.text and "مریم" not in res.text
    assert env.client.get(f"/platform/organizations/{env.b.org.id}/support-view", headers=_auth(env.support)).status_code == 403
    env.db.expire_all()
    assert env.db.query(AuditLog).filter(AuditLog.action == "platform.support_view", AuditLog.organization_id == env.a.org.id).execution_options(skip_tenant_filter=True).count() == 1
    assert env.client.post(f"/platform/support-access/{grant['id']}/revoke", headers=_auth(env.root)).status_code == 200
    assert env.client.get(view, headers=_auth(env.support)).status_code == 403


def test_expired_support_access_stops_working(env):
    url = f"/platform/organizations/{env.a.org.id}/support-access"
    assert env.client.post(url, headers=_auth(env.root), json={"user_id": env.support.id, "reason": "بررسی تیکت", "minutes": 241}).status_code == 422
    assert env.client.post(url, headers=_auth(env.root), json={"user_id": env.support.id, "reason": "بررسی تیکت", "minutes": 1}).status_code == 200
    env.db.execute(__import__("sqlalchemy").text("UPDATE support_access_grants SET expires_at = :t"), {"t": _now() - timedelta(minutes=1)})
    env.db.commit()
    assert env.client.get(f"/platform/organizations/{env.a.org.id}/support-view", headers=_auth(env.support)).status_code == 403


# ---------------------------------------------------------------------------
# پرچم قابلیت
# ---------------------------------------------------------------------------
def _flag(env, **body):
    return env.client.put("/platform/feature-flags/customer_requests", headers=_auth(env.root), json={"reason": "راه‌اندازی تدریجی", **body})


def test_flag_allowlist_and_kill_switch_control_customer_requests(env):
    order = _order(env).json()
    ask = lambda: env.client.post(f"/public/track/{order['tracking_code']}/requests", json={"phone": "2233", "kind": "cancel"})  # noqa: E731
    assert env.client.get("/platform/feature-flags", headers=_auth(env.support)).json()[0]["enabled"] is True
    assert env.client.put("/platform/feature-flags/customer_requests", headers=_auth(env.support), json={"reason": "تغییر پرچم"}).status_code == 403
    assert env.client.put("/platform/feature-flags/unknown", headers=_auth(env.root), json={"reason": "تغییر پرچم"}).status_code == 404
    assert _flag(env, allowlist=[env.b.org.id]).status_code == 200
    assert ask().status_code == 400
    assert _flag(env, allowlist=[env.a.org.id]).status_code == 200
    assert ask().status_code == 200
    assert _flag(env, kill_switch=True).status_code == 200
    second = env.client.post(f"/public/track/{order['tracking_code']}/requests", json={"phone": "2233", "kind": "address_change"})
    assert second.status_code == 400


# ---------------------------------------------------------------------------
# خروجی و خروج سازمان
# ---------------------------------------------------------------------------
def _export(env, org=None):
    org = org or env.a.org
    res = env.client.post(f"/platform/organizations/{org.id}/exports", headers=_auth(env.root), json={"reason": "درخواست مشتری"})
    assert res.status_code == 200, res.text
    db = env.Session()
    set_tenant(db, None)
    platform_service.build_export(db, res.json()["id"])
    db.close()
    return res.json()["id"]


def test_export_contains_only_this_organization_and_no_secrets(env, monkeypatch):
    from app import tasks
    monkeypatch.setattr(tasks.export_tenant_task, "delay", lambda *a: None)
    _order(env)
    _order(env, env.b)
    export_id = _export(env)
    url = f"/platform/organizations/{env.a.org.id}/exports/{export_id}/download"
    assert env.client.get(url, headers=_auth(env.support)).status_code == 403
    res = env.client.get(url, headers=_auth(env.root))
    assert res.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(res.content))
    assert {"orders.csv", "users.csv", "customers.csv"} <= set(archive.namelist())
    rows = list(csv.DictReader(io.StringIO(archive.read("users.csv").decode("utf-8-sig"))))
    assert {r["username"] for r in rows} == {"alpha_adm", "alpha_drv"} and "hashed_password" not in rows[0]
    assert "hash-secret" not in b"".join(archive.read(n) for n in archive.namelist()).decode("utf-8", "ignore")
    assert all(r["organization_id"] == str(env.a.org.id) for r in csv.DictReader(io.StringIO(archive.read("orders.csv").decode("utf-8-sig"))))
    assert env.client.get(f"/platform/organizations/{env.b.org.id}/exports/{export_id}/download", headers=_auth(env.root)).status_code == 404


def _deprovision(env, slug="alpha"):
    return env.client.post(f"/platform/organizations/{env.a.org.id}/deprovision", headers=_auth(env.root), json={"reason": "پایان قرارداد", "confirm_slug": slug})


def test_deprovision_needs_recent_export_and_typed_slug_and_can_be_canceled(env, monkeypatch):
    from app import tasks
    monkeypatch.setattr(tasks.export_tenant_task, "delay", lambda *a: None)
    assert _deprovision(env).status_code == 400
    _export(env)
    assert _deprovision(env, "beta").status_code == 400
    res = _deprovision(env)
    assert res.status_code == 200 and res.json()["erase_after"]
    assert env.client.get("/orders/", headers=_auth(env.a.admin)).status_code == 403
    db = env.Session()
    set_tenant(db, None)
    assert platform_service.erase_due(db) == 0                                   # مهلت هنوز نگذشته
    db.close()
    assert env.client.post(f"/platform/organizations/{env.a.org.id}/deprovision/cancel", headers=_auth(env.root), json={"reason": "مشتری برگشت"}).status_code == 200
    assert env.client.get("/orders/", headers=_auth(env.a.admin)).status_code == 200


def test_erase_removes_personal_data_and_files_but_keeps_ledger_and_other_tenants(env, monkeypatch):
    from app import tasks
    monkeypatch.setattr(tasks.export_tenant_task, "delay", lambda *a: None)
    mine = _order(env).json()
    theirs = _order(env, env.b).json()
    storage.save(f"deliveries/{env.a.org.id}/{mine['id']}/1.png", b"x")
    storage.save(f"deliveries/{env.b.org.id}/{theirs['id']}/1.png", b"y")
    _export(env)
    assert _deprovision(env).status_code == 200
    db = env.Session()
    set_tenant(db, None)
    movements_before = db.query(StockMovement).execution_options(skip_tenant_filter=True).count()
    assert platform_service.erase_due(db, _now() + timedelta(days=31)) == 1
    assert platform_service.erase_due(db, _now() + timedelta(days=31)) == 0      # دوباره اجرا نمی‌شود
    db.expire_all()
    order = db.query(Order).filter(Order.id == mine["id"]).execution_options(skip_tenant_filter=True).one()
    assert order.recipient_name is None and order.recipient_mobile is None and order.destination_address is None
    assert order.tracking_code == mine["tracking_code"]
    customer = db.query(Customer).filter(Customer.organization_id == env.a.org.id).execution_options(skip_tenant_filter=True).one()
    assert customer.name == "حذف‌شده" and "0912" not in customer.mobile
    admin = db.query(User).filter(User.id == env.a.admin.id).execution_options(skip_tenant_filter=True).one()
    assert admin.username.startswith("deleted-") and admin.email is None and admin.hashed_password == "!" and admin.is_active is False
    assert db.query(StockMovement).execution_options(skip_tenant_filter=True).count() == movements_before
    other = db.query(Order).filter(Order.id == theirs["id"]).execution_options(skip_tenant_filter=True).one()
    assert other.recipient_name == "مریم احمدی"
    assert not (env.media / "deliveries" / str(env.a.org.id)).exists() and (env.media / "deliveries" / str(env.b.org.id)).exists()
    assert db.query(TenantExport).filter(TenantExport.organization_id == env.a.org.id).count() == 1
    db.close()
    assert env.client.get("/orders/", headers=_auth(env.b.admin)).status_code == 200


def test_platform_health_reports_queue_state(env):
    body = env.client.get("/platform/operations", headers=_auth(env.support)).json()
    assert {"pending", "oldest_pending_seconds", "queue_depth", "messages", "tasks"} <= set(body)
    assert env.client.post(f"/platform/organizations/{env.a.org.id}/suspend", headers=_auth(env.a.admin), json={"reason": "تلاش", "confirm_slug": "alpha"}).status_code == 403
