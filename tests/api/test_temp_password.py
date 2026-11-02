"""
رمز موقت (P0): ادمین سازمان تازه باید در اولین ورود رمز را عوض کند، رمز موقت پس از TEMP_PASSWORD_TTL پذیرفته نمی‌شود
و تا عوض نشده سرور (نه فقط فرانت) جز پروفایل خود، تغییر رمز و خروج چیزی را باز نمی‌کند.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core.tenancy import set_tenant
from app.models import AuditLog, Organization, OrganizationRequest, RoleEnum, User
from app.services import messaging, organization_request_service, user_service

PASSWORD = "Temp-Pass-2026"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _login(client, username, password=PASSWORD):
    return client.post("/auth/token", data={"username": username, "password": password})


@pytest.fixture()
def env(api_env):
    client, Session = api_env
    db = Session()
    org = Organization(name="آلفا", slug="alpha")
    db.add(org)
    db.commit()
    set_tenant(db, org.id)
    admin = User(username="adm", email="a@x.io", role=RoleEnum.ORG_ADMIN, hashed_password="x")
    target = User(username="drv", email="d@x.io", role=RoleEnum.DRIVER, hashed_password="x", driver_code="D1", driver_status="approved")
    user_service.set_temporary_password(target, PASSWORD)
    db.add_all([admin, target])
    db.commit()
    yield SimpleNamespace(client=client, db=db, org=org, admin=admin, target=target)
    db.close()


def _token(env, password=PASSWORD) -> dict:
    res = _login(env.client, "drv", password)
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_temporary_password_gets_the_existing_ttl(env):
    expires = env.target.temp_password_expires_at
    assert env.target.must_change_password and abs((expires - _now()) - messaging.TEMP_PASSWORD_TTL) < timedelta(minutes=1)


def test_server_allows_only_profile_password_change_and_logout(env):
    headers = _token(env)
    assert env.client.get("/users/me", headers=headers).status_code == 200
    for method, path in (("GET", "/orders/"), ("GET", "/vehicles/"), ("GET", "/notifications/"), ("PUT", "/users/me/tours/x")):
        res = env.client.request(method, path, headers=headers, json={})
        assert res.status_code == 403 and "رمز موقت" in res.json()["detail"], (method, path, res.text)
    changed = env.client.put("/users/me/password", headers=headers, json={"old_password": PASSWORD, "new_password": "New-Pass-2026x"})
    assert changed.status_code == 200, changed.text
    fresh = {"Authorization": f"Bearer {changed.json()['access_token']}"}
    assert env.client.get("/notifications/", headers=fresh).status_code == 200
    env.db.expire_all()
    assert env.db.get(User, env.target.id).temp_password_expires_at is None


def test_expired_temporary_password_cannot_log_in(env):
    env.target.temp_password_expires_at = _now() - timedelta(minutes=1)
    env.db.commit()
    res = _login(env.client, "drv")
    assert res.status_code == 403 and "منقضی" in res.json()["detail"]
    assert env.db.query(AuditLog).filter(AuditLog.action == "auth.temp_password_expired").count() == 1
    assert _login(env.client, "drv", "wrong-password").status_code == 401        # رمز غلط همان پاسخ عمومی را می‌گیرد


def test_admin_reset_and_admin_created_users_get_the_same_rule(env):
    env.target.must_change_password, env.target.temp_password_expires_at = False, None
    env.db.commit()
    user, password = user_service.reset_password(env.db, env.admin, env.target.id)
    assert user.must_change_password and user.temp_password_expires_at is not None and password
    created = user_service.create_user(env.db, env.admin, user_service.CreateUserRequest(
        username="newop", email="n@x.io", role="driver", password="Start-Pass-2026", must_change_password=True))
    assert created.temp_password_expires_at is not None
    plain = user_service.create_user(env.db, env.admin, user_service.CreateUserRequest(
        username="plain", email="p@x.io", role="driver", password="Start-Pass-2026"))
    assert plain.must_change_password is False and plain.temp_password_expires_at is None


def test_new_organization_admin_must_change_the_temporary_password(env, monkeypatch):
    set_tenant(env.db, None)
    reviewer = User(username="root", email="r@x.io", role=RoleEnum.PLATFORM_ADMIN, hashed_password="x")
    request = OrganizationRequest(name="فروشگاه بتا", contact_name="مریم", contact_mobile="09121112233", contact_email="m@x.io",
                                  province="تهران", city="تهران", address="خیابان آزادی", status="pending", tracking_code="REQ-TEMP1")
    env.db.add_all([reviewer, request])
    env.db.commit()
    data = organization_request_service.OrganizationRequestApprove(slug="beta-shop")
    result = organization_request_service.approve_request(env.db, reviewer, request.id, data)
    admin = env.db.query(User).filter(User.username == result["admin_username"]).execution_options(skip_tenant_filter=True).one()
    assert admin.must_change_password and admin.temp_password_expires_at is not None and result["temporary_password"]
