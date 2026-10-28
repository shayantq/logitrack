"""نشست ماندگار ورود: کوکی HttpOnly، «مرا به خاطر بسپار»، چرخش و تشخیص استفاده دوباره، خروج، تغییر رمز و فهرست نشست‌ها."""
from datetime import timedelta

import pytest

from app.core.rate_limit import login_failure_limiter
from app.core.security import ACCESS_TOKEN_EXPIRE_MINUTES, bcrypt_context
from app.core.tenancy import set_tenant
from app.models import Organization, RoleEnum, User
from app.services import session_service

PASSWORD = "secret123"
SAME_SITE = {"X-Requested-With": "pasineh"}
COOKIE = session_service.COOKIE_NAME


@pytest.fixture()
def env(api_env):
    client, Session = api_env
    db = Session()
    org = Organization(name="سازمان نشست", slug="sess")
    db.add(org)
    db.commit()
    set_tenant(db, org.id)
    admin = User(username="sess_admin", email="sess@example.com", role=RoleEnum.ORG_ADMIN, hashed_password=bcrypt_context.hash(PASSWORD))
    db.add(admin)
    db.commit()
    set_tenant(db, None)
    platform = User(username="sess_root", email="root@example.com", role=RoleEnum.PLATFORM_ADMIN, hashed_password=bcrypt_context.hash(PASSWORD))
    db.add(platform)
    db.commit()
    login_failure_limiter.reset()
    try:
        yield client, db, admin, platform
    finally:
        db.close()


def _login(client, username, remember=False):
    client.cookies.clear()
    res = client.post("/auth/token", data={"username": username, "password": PASSWORD, "remember": str(remember).lower()})
    assert res.status_code == 200, res.text
    return res


def _use(client, token):
    client.cookies.clear()
    client.cookies.set(COOKIE, token)


def test_login_sets_httponly_strict_cookie_and_short_access_token(env):
    client, _, admin, _ = env
    res = _login(client, admin.username)
    cookie = res.headers["set-cookie"]
    assert f"{COOKIE}=" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/auth" in cookie
    assert "Max-Age" not in cookie                       # بدون «مرا به خاطر بسپار»: با بستن مرورگر پاک می‌شود
    assert res.json()["expires_in"] == ACCESS_TOKEN_EXPIRE_MINUTES * 60
    remembered = _login(client, admin.username, remember=True).headers["set-cookie"]
    assert "Max-Age=" in remembered


def test_platform_staff_are_never_remembered(env):
    client, _, _, platform = env
    assert "Max-Age" not in _login(client, platform.username, remember=True).headers["set-cookie"]


def test_refresh_rotates_and_requires_same_site_header(env):
    client, _, admin, _ = env
    _login(client, admin.username)
    first = client.cookies.get(COOKIE)
    assert client.post("/auth/refresh").status_code == 403                 # بدون هدر سایت خودمان
    res = client.post("/auth/refresh", headers=SAME_SITE)
    assert res.status_code == 200 and res.json()["access_token"]
    second = client.cookies.get(COOKIE)
    assert second and second != first
    assert client.get("/users/me", headers={"Authorization": f"Bearer {res.json()['access_token']}"}).status_code == 200


def test_reuse_of_rotated_token_revokes_the_whole_family(env, monkeypatch):
    client, _, admin, _ = env
    _login(client, admin.username)
    old = client.cookies.get(COOKIE)
    assert client.post("/auth/refresh", headers=SAME_SITE).status_code == 200
    new = client.cookies.get(COOKIE)

    _use(client, old)                                    # زبانه دیگر در همان چند ثانیه: فقط توکن دسترسی، بدون باطل‌شدن
    assert client.post("/auth/refresh", headers=SAME_SITE).status_code == 200

    monkeypatch.setattr(session_service, "REUSE_GRACE", timedelta(0))
    _use(client, old)                                    # همان توکن قدیمی بعد از مهلت ← سرقت
    assert client.post("/auth/refresh", headers=SAME_SITE).status_code == 401
    _use(client, new)                                    # نشست اصلی هم دیگر معتبر نیست
    assert client.post("/auth/refresh", headers=SAME_SITE).status_code == 401


def test_logout_revokes_the_session(env):
    client, _, admin, _ = env
    _login(client, admin.username)
    token = client.cookies.get(COOKIE)
    assert client.post("/auth/logout", headers=SAME_SITE).status_code == 204
    _use(client, token)
    assert client.post("/auth/refresh", headers=SAME_SITE).status_code == 401


def test_password_change_ends_other_sessions_but_keeps_this_one(env):
    client, _, admin, _ = env
    _login(client, admin.username)
    other_device = client.cookies.get(COOKIE)
    access = _login(client, admin.username).json()["access_token"]
    res = client.put("/users/me/password", json={"old_password": PASSWORD, "new_password": "brand-new-pass-1"},
                     headers={"Authorization": f"Bearer {access}"})
    assert res.status_code == 200, res.text
    this_device = client.cookies.get(COOKIE)
    assert client.post("/auth/refresh", headers=SAME_SITE).status_code == 200
    _use(client, other_device)
    assert client.post("/auth/refresh", headers=SAME_SITE).status_code == 401
    assert this_device != other_device


def test_deactivated_user_cannot_refresh(env):
    client, db, admin, _ = env
    _login(client, admin.username)
    db.get(User, admin.id).is_active = False
    db.commit()
    assert client.post("/auth/refresh", headers=SAME_SITE).status_code == 401


def test_list_and_revoke_my_sessions(env):
    client, _, admin, _ = env
    _login(client, admin.username)
    first = client.cookies.get(COOKIE)
    access = _login(client, admin.username, remember=True).json()["access_token"]
    auth = {"Authorization": f"Bearer {access}"}
    sessions = client.get("/auth/sessions", headers=auth).json()
    assert len(sessions) == 2 and sum(s["current"] for s in sessions) == 1
    other = next(s for s in sessions if not s["current"])
    assert client.delete(f"/auth/sessions/{other['id']}", headers=auth).status_code == 204
    _use(client, first)
    assert client.post("/auth/refresh", headers=SAME_SITE).status_code == 401
