"""
مرحله ۱۵: بخش کاربران — ویرایش، غیرفعال‌سازی، رمز موقت با اجبار تغییر، قفل ورود، حذف فقط بدون سابقه و گزارش فعالیت.
"""

import pytest

from app.core.security import bcrypt_context
from app.core.tenancy import set_tenant
from app.models import AuditLog, Order, Organization, RoleEnum, User, Vehicle, Warehouse
from app.services.driver_service import is_assignable_driver
from tests.factories import order_payload

PASSWORD = "secret123"


def _login(client, username, password=PASSWORD):
    return client.post("/auth/token", data={"username": username, "password": password})


def _h(client, username, password=PASSWORD) -> dict:
    res = _login(client, username, password)
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture()
def env(api_env):
    client, Session = api_env
    db = Session()
    world = {}
    hashed = bcrypt_context.hash(PASSWORD)
    for slug in ("alpha", "beta"):
        org = Organization(name=f"سازمان {slug}", slug=slug)
        db.add(org)
        db.commit()
        set_tenant(db, org.id)
        wh = Warehouse(name="انبار تهران", province="تهران", city="تهران")
        wh2 = Warehouse(name="انبار کرج", province="البرز", city="کرج")
        db.add_all([wh, wh2])
        db.commit()
        admin = User(username=f"{slug}_admin", email=f"{slug}a@x.io", role=RoleEnum.ORG_ADMIN, hashed_password=hashed, full_name=f"ادمین {slug}")
        manager = User(username=f"{slug}_mgr", email=f"{slug}m@x.io", role=RoleEnum.WAREHOUSE_MANAGER, hashed_password=hashed, warehouse_id=wh.id)
        driver = User(username=f"{slug}_d", email=f"{slug}d@x.io", role=RoleEnum.DRIVER, hashed_password=hashed, city="تهران", full_name="راننده آزمون")
        db.add_all([admin, manager, driver])
        db.commit()
        vehicle = Vehicle(license_plate=f"{slug}-1", type="van", capacity_kg=50_000, status="available", driver_id=driver.id, city="تهران")
        db.add(vehicle)
        db.commit()
        world[slug] = dict(org=org, wh=wh, wh2=wh2, admin=admin, manager=manager, driver=driver, vehicle=vehicle)
        set_tenant(db, None)
    try:
        yield client, db, world
    finally:
        db.close()


def test_tour_state_saved_per_user(env):
    """راهنمای تعاملی: وضعیت هر راهنما برای همان کاربر ذخیره می‌شود و فقط بار اول خودکار باز می‌شود."""
    client, db, w = env
    h = _h(client, "alpha_admin")
    assert client.get("/users/me", headers=h).json()["tour_state"] in (None, {})
    assert client.put("/users/me/tours/main", json={"state": "skipped"}, headers=h).json() == {"main": "skipped"}
    assert client.put("/users/me/tours/inventory", json={"state": "done"}, headers=h).json() == {"main": "skipped", "inventory": "done"}
    assert client.get("/users/me", headers=h).json()["tour_state"] == {"main": "skipped", "inventory": "done"}
    # کاربر دیگر جدا
    assert client.get("/users/me", headers=_h(client, "alpha_mgr")).json()["tour_state"] in (None, {})
    assert client.put("/users/me/tours/BAD ID", json={"state": "done"}, headers=h).status_code in (404, 422)
    assert client.put("/users/me/tours/main", json={"state": "maybe"}, headers=h).status_code == 422
    assert client.delete("/users/me/tours", headers=h).json() == {}
    assert client.get("/users/me", headers=h).json()["tour_state"] == {}


def test_edit_rules_and_role_changes(env):
    client, db, w = env
    a = w["alpha"]
    h = _h(client, "alpha_admin")
    # مدیر انبار ← ادمین (انبار پاک می‌شود)، و برگشت فقط با انبار
    res = client.put(f"/users/{a['manager'].id}", json={"role": "org_admin", "full_name": "مینا کاظمی", "mobile": "09121234567"}, headers=h)
    assert res.status_code == 200, res.text
    assert res.json()["role"] == "org_admin" and res.json()["warehouse_id"] is None and res.json()["mobile"] == "09121234567"
    assert client.put(f"/users/{a['manager'].id}", json={"role": "warehouse_manager"}, headers=h).status_code == 400
    back = client.put(f"/users/{a['manager'].id}", json={"role": "warehouse_manager", "warehouse_id": a["wh2"].id}, headers=h)
    assert back.status_code == 200 and back.json()["warehouse_id"] == a["wh2"].id
    # راننده نقش عوض نمی‌کند؛ نقش خود ادمین هم
    assert client.put(f"/users/{a['driver'].id}", json={"role": "warehouse_manager", "warehouse_id": a["wh"].id}, headers=h).status_code == 400
    assert client.put(f"/users/{a['admin'].id}", json={"role": "warehouse_manager", "warehouse_id": a["wh"].id}, headers=h).status_code == 400
    # ایمیل تکراری (حتی از سازمان دیگر)
    assert client.put(f"/users/{a['driver'].id}", json={"email": "betaa@x.io"}, headers=h).status_code == 400
    # جداسازی سازمان‌ها
    assert client.put(f"/users/{w['beta']['driver'].id}", json={"full_name": "x"}, headers=h).status_code == 404
    assert client.put(f"/users/{a['driver'].id}", json={"full_name": "x"}, headers=_h(client, "alpha_mgr")).status_code == 403
    logs = client.get("/users/activity-log", params={"category": "users"}, headers=h).json()
    assert logs["total"] == 2 and "مینا کاظمی" in logs["items"][-1]["summary"]
    assert logs["items"][-1]["details"]["changes"]["role"] == ["مدیر انبار", "ادمین سازمان"]


def test_deactivate_blocks_login_and_kills_sessions(env):
    client, db, w = env
    a = w["alpha"]
    h = _h(client, "alpha_admin")
    mgr_h = _h(client, "alpha_mgr")
    assert client.get("/users/me", headers=mgr_h).status_code == 200
    res = client.post(f"/users/{a['manager'].id}/deactivate", headers=h)
    assert res.status_code == 200 and res.json()["is_active"] is False
    assert client.get("/users/me", headers=mgr_h).status_code == 401
    blocked = _login(client, "alpha_mgr")
    assert blocked.status_code == 403 and "غیرفعال" in blocked.json()["detail"]
    assert client.post(f"/users/{a['admin'].id}/deactivate", headers=h).status_code == 400          # خودش
    assert client.post(f"/users/{a['manager'].id}/activate", headers=h).json()["is_active"] is True
    assert _login(client, "alpha_mgr").status_code == 200

    # راننده با سفارش در جریان غیرفعال نمی‌شود؛ بعد از پایان سفارش می‌شود و دیگر سفارش نمی‌گیرد
    pid = client.post("/inventory/products", json={"name": "برنج", "sku": "R-1", "price": 1000, "weight_kg": 1, "initial_quantity": 10,
                                                   "warehouse_id": a["wh"].id}, headers=h).json()["product"]["id"]
    order = client.post("/orders/", json=order_payload(pid, a["vehicle"].id), headers=h)
    assert order.status_code == 201, order.text
    assert order.json()["status"] == "assigned"
    busy = client.post(f"/users/{a['driver'].id}/deactivate", headers=h)
    assert busy.status_code == 400 and "سفارش در جریان" in busy.json()["detail"]
    set_tenant(db, None)
    db.get(Order, order.json()["id"]).status = "canceled"
    db.commit()
    assert client.post(f"/users/{a['driver'].id}/deactivate", headers=h).status_code == 200
    db.expire_all()
    assert is_assignable_driver(db, a["driver"].id) is False


def test_last_active_admin_is_protected(env):
    client, db, w = env
    a = w["alpha"]
    h = _h(client, "alpha_admin")
    client.put(f"/users/{a['manager'].id}", json={"role": "org_admin"}, headers=h)
    mh = _h(client, "alpha_mgr")
    assert client.post(f"/users/{a['admin'].id}/deactivate", headers=mh).status_code == 200
    # حالا alpha_mgr تنها ادمین فعال است و نمی‌شود نقشش را با کمک دیگری پایین آورد
    assert client.post(f"/users/{a['manager'].id}/deactivate", headers=mh).status_code == 400


def test_temporary_password_forces_change(env):
    client, db, w = env
    a = w["alpha"]
    h = _h(client, "alpha_admin")
    old = _h(client, "alpha_d")
    res = client.post(f"/users/{a['driver'].id}/reset-password", headers=h)
    assert res.status_code == 200
    temp = res.json()["temporary_password"]
    assert len(temp) == 10 and res.json()["user"]["must_change_password"] is True
    assert client.get("/users/me", headers=old).status_code == 401
    assert _login(client, "alpha_d").status_code == 401
    th = _h(client, "alpha_d", temp)
    assert client.get("/users/me", headers=th).json()["must_change_password"] is True
    changed = client.put("/users/me/password", json={"old_password": temp, "new_password": "brandnew99"}, headers=th)
    assert changed.status_code == 200
    nh = {"Authorization": f"Bearer {changed.json()['access_token']}"}
    assert client.get("/users/me", headers=nh).json()["must_change_password"] is False
    assert client.post(f"/users/{a['admin'].id}/reset-password", headers=h).status_code == 400


def test_lockout_after_five_failures_and_unlock(env):
    client, db, w = env
    a = w["alpha"]
    for _ in range(5):
        assert _login(client, "alpha_mgr", "wrong-pass").status_code == 401
    locked = _login(client, "alpha_mgr")                     # حتی با رمز درست
    assert locked.status_code == 429 and "دقیقه" in locked.json()["detail"]
    h = _h(client, "alpha_admin")
    users = {u["username"]: u for u in client.get("/users/", headers=h).json()}
    assert users["alpha_mgr"]["locked_until"] is not None
    detail = client.get(f"/users/{a['manager'].id}", headers=h).json()
    assert detail["stats"]["failed_logins_30d"] == 5
    assert client.post(f"/users/{a['manager'].id}/unlock", headers=h).status_code == 200
    assert _login(client, "alpha_mgr").status_code == 200
    log = client.get("/users/activity-log", params={"category": "auth"}, headers=h).json()
    actions = [i["action"] for i in log["items"]]
    assert actions.count("auth.login_failed") == 5 and "auth.locked" in actions
    # سازمان دیگر چیزی از این‌ها نمی‌بیند
    beta = client.get("/users/activity-log", headers=_h(client, "beta_admin")).json()
    assert all(i["actor_name"] in (None, "ادمین beta") for i in beta["items"])
    assert all("alpha" not in (i["target_label"] or "") for i in beta["items"])


def test_delete_only_without_history_and_user_timeline(env):
    client, db, w = env
    a = w["alpha"]
    h = _h(client, "alpha_admin")
    new = client.post("/auth/", json={"username": "temp_user", "email": "t@x.io", "role": "warehouse_manager", "password": PASSWORD,
                                      "warehouse_id": a["wh"].id, "must_change_password": True}, headers=h)
    assert new.status_code == 201 and new.json()["must_change_password"] is True
    # کاربر بی‌سابقه حذف می‌شود
    assert client.delete(f"/users/{new.json()['id']}", headers=h).status_code == 204
    # مدیر انباری که گردش انبار ثبت کرده حذف نمی‌شود
    mh = _h(client, "alpha_mgr")
    pid = client.post("/inventory/products", json={"name": "چای", "sku": "T-1", "price": 1000, "weight_kg": 1, "initial_quantity": 5,
                                                   "warehouse_id": a["wh"].id}, headers=h).json()["product"]["id"]
    mv = client.post("/inventory/movements", json={"product_id": pid, "warehouse_id": a["wh"].id, "movement_type": "receipt",
                                                    "quantity": 3, "reason": "ورود بار"}, headers=mh)
    assert mv.status_code in (200, 201), mv.text
    res = client.delete(f"/users/{a['manager'].id}", headers=h)
    assert res.status_code == 400 and "غیرفعال" in res.json()["detail"]
    timeline = client.get(f"/users/{a['manager'].id}/activity", headers=h).json()
    kinds = {t["kind"] for t in timeline}
    assert {"audit", "stock"} <= kinds
    assert any("ورود به سامانه" == t["title"] for t in timeline)
    detail = client.get(f"/users/{a['manager'].id}", headers=h).json()
    assert detail["stats"]["stock_movements"] == 1 and detail["stats"]["logins_30d"] == 1 and detail["stats"]["history"] >= 1
    deleted = client.get("/users/activity-log", params={"q": "temp_user"}, headers=h).json()
    assert any(i["action"] == "user.delete" for i in deleted["items"])
    set_tenant(db, a["org"].id)
    assert db.query(AuditLog).filter(AuditLog.action == "auth.login").count() >= 2
    set_tenant(db, None)
