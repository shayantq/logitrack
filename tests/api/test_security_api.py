"""سخت‌سازی HTTP و ورود: هدرهای امنیتی، no-store، پاسخ یکسان برای نام کاربری ناموجود، شمارش اتمی و سقف IP، و ۴۰۳ نقش‌های کم‌دسترسی."""
from datetime import timedelta

import pytest

from app.core.rate_limit import login_failure_limiter
from app.core.security import bcrypt_context, create_access_token
from app.core.tenancy import set_tenant
from app.models import Organization, RoleEnum, User

PASSWORD = "secret123"


@pytest.fixture()
def env(api_env):
    client, Session = api_env
    db = Session()
    org = Organization(name="سازمان امنیت", slug="sec")
    db.add(org)
    db.commit()
    set_tenant(db, org.id)
    users = {role: User(username=f"sec_{role.value}", email=f"{role.value}@example.com", role=role,
                        hashed_password=bcrypt_context.hash(PASSWORD))
             for role in (RoleEnum.ORG_ADMIN, RoleEnum.WAREHOUSE_MANAGER, RoleEnum.DRIVER)}
    db.add_all(users.values())
    db.commit()
    set_tenant(db, None)
    login_failure_limiter.reset()
    try:
        yield client, db, users
    finally:
        login_failure_limiter.reset()
        db.close()


def _auth(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.username, user.id, timedelta(minutes=5))}"}


def test_security_headers_on_every_response(env):
    client, *_ = env
    res = client.get("/health")
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"
    assert res.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "camera=(self)" in res.headers["permissions-policy"]
    csp = res.headers["content-security-policy-report-only"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp and "unsafe-eval" not in csp


def test_auth_responses_are_never_cached(env):
    client, _, users = env
    res = client.post("/auth/token", data={"username": users[RoleEnum.ORG_ADMIN].username, "password": PASSWORD})
    assert res.status_code == 200 and res.headers["cache-control"] == "no-store"
    assert client.post("/auth/token", data={"username": "x", "password": "y"}).headers["cache-control"] == "no-store"


def test_unknown_user_and_wrong_password_look_identical(env):
    client, _, users = env
    unknown = client.post("/auth/token", data={"username": "nobody_here", "password": "wrong-pass"})
    wrong = client.post("/auth/token", data={"username": users[RoleEnum.ORG_ADMIN].username, "password": "wrong-pass"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


def test_failed_logins_are_counted_in_the_database(env):
    client, db, users = env
    manager = users[RoleEnum.WAREHOUSE_MANAGER]
    for _ in range(3):
        client.post("/auth/token", data={"username": manager.username, "password": "wrong-pass"})
    db.expire_all()
    assert db.get(User, manager.id).failed_logins == 3


def test_many_failures_from_one_ip_are_blocked_across_usernames(env):
    client, _, users = env
    for i in range(login_failure_limiter.max_requests):
        assert client.post("/auth/token", data={"username": f"guess_{i}", "password": "x"}).status_code == 401
    blocked = client.post("/auth/token", data={"username": users[RoleEnum.ORG_ADMIN].username, "password": PASSWORD})
    assert blocked.status_code == 429 and "تلاش ناموفق" in blocked.json()["detail"]


def test_low_privilege_roles_get_403_on_admin_endpoints(env):
    client, _, users = env
    manager, driver = users[RoleEnum.WAREHOUSE_MANAGER], users[RoleEnum.DRIVER]
    new_user = {"username": "sneaky", "email": "sneaky@example.com", "role": "org_admin", "password": PASSWORD}
    assert client.post("/auth/", json=new_user, headers=_auth(manager)).status_code == 403
    assert client.post("/auth/", json=new_user, headers=_auth(driver)).status_code == 403
    assert client.get("/users/activity-log", headers=_auth(driver)).status_code == 403
    assert client.get("/platform/organizations", headers=_auth(manager)).status_code == 403
    assert client.get("/platform/organizations", headers=_auth(users[RoleEnum.ORG_ADMIN])).status_code == 403
