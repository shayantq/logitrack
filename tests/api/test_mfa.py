"""ورود دومرحله‌ای (TOTP): راه‌اندازی، ورود با کد، رد کد تکراری، خاموش‌کردن، بازنشانی ادمین و اجبار برای کارکنان پلتفرم."""
import time
from datetime import timedelta

import pytest

from app.core import totp
from app.core.rate_limit import login_failure_limiter
from app.core.security import bcrypt_context, create_access_token
from app.core.tenancy import set_tenant
from app.models import Organization, RoleEnum, User

PASSWORD = "secret123"


@pytest.fixture()
def env(api_env):
    client, Session = api_env
    db = Session()
    org = Organization(name="سازمان دومرحله‌ای", slug="mfa")
    db.add(org)
    db.commit()
    set_tenant(db, org.id)
    admin = User(username="mfa_admin", email="a@example.com", role=RoleEnum.ORG_ADMIN, hashed_password=bcrypt_context.hash(PASSWORD))
    staff = User(username="mfa_staff", email="s@example.com", role=RoleEnum.WAREHOUSE_MANAGER, hashed_password=bcrypt_context.hash(PASSWORD))
    db.add_all([admin, staff])
    db.commit()
    set_tenant(db, None)
    root = User(username="mfa_root", email="r@example.com", role=RoleEnum.PLATFORM_ADMIN, hashed_password=bcrypt_context.hash(PASSWORD))
    db.add(root)
    db.commit()
    login_failure_limiter.reset()
    try:
        yield client, db, admin, staff, root
    finally:
        db.close()


def _auth(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.username, user.id, timedelta(minutes=5), user.token_version or 0)}"}


def _enable(client, user) -> str:
    setup = client.post("/auth/mfa/setup", headers=_auth(user))
    assert setup.status_code == 200 and setup.json()["qr"].startswith("data:image/svg+xml;base64,")
    secret = setup.json()["secret"]
    assert client.post("/auth/mfa/enable", json={"code": "000000"}, headers=_auth(user)).status_code == 400
    assert client.post("/auth/mfa/enable", json={"code": totp.code_at(secret)}, headers=_auth(user)).status_code == 204
    return secret


def _login(client, username, otp=None):
    data = {"username": username, "password": PASSWORD}
    if otp is not None:
        data["otp"] = otp
    return client.post("/auth/token", data=data)


def test_rfc6238_reference_codes():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"          # "12345678901234567890"
    assert totp.code_at(secret, 59) == "287082" and totp.code_at(secret, 1111111109) == "081804"


def test_login_requires_a_fresh_code_once_enabled(env):
    client, db, admin, *_ = env
    secret = _enable(client, admin)
    missing = _login(client, admin.username)
    assert missing.status_code == 401 and missing.headers["x-mfa-required"] == "1"
    wrong = _login(client, admin.username, "123456" if totp.code_at(secret) != "123456" else "654321")
    assert wrong.status_code == 401 and wrong.headers["x-mfa-required"] == "1"
    db.expire_all()
    assert db.get(User, admin.id).failed_logins == 1                   # کد اشتباه هم تلاش ناموفق است

    next_code = totp.code_at(secret, time.time() + totp.STEP)            # کد گام بعد (گام فعلی هنگام فعال‌سازی مصرف شد)
    assert _login(client, admin.username, next_code).status_code == 200
    assert _login(client, admin.username, next_code).status_code == 401  # همان کد دوباره پذیرفته نمی‌شود


def test_disable_needs_password_and_code(env):
    client, _, admin, *_ = env
    secret = _enable(client, admin)
    code = totp.code_at(secret, time.time() + totp.STEP)
    assert client.post("/auth/mfa/disable", json={"password": "wrong", "code": code}, headers=_auth(admin)).status_code == 400
    assert client.post("/auth/mfa/disable", json={"password": PASSWORD, "code": code}, headers=_auth(admin)).status_code == 204
    assert _login(client, admin.username).status_code == 200


def test_admin_password_reset_turns_mfa_off_for_lost_phones(env):
    client, db, admin, staff, _ = env
    _enable(client, staff)
    res = client.post(f"/users/{staff.id}/reset-password", headers=_auth(admin))
    assert res.status_code == 200, res.text
    db.expire_all()
    assert db.get(User, staff.id).totp_enabled_at is None


def test_platform_staff_must_set_up_mfa_in_production(env, monkeypatch):
    client, db, _, _, root = env
    monkeypatch.setenv("APP_ENV", "production")
    me = client.get("/users/me", headers=_auth(root)).json()
    assert me["mfa_setup_required"] is True and me["mfa_enabled"] is False
    assert client.get("/platform/organizations", headers=_auth(root)).status_code == 403
    secret = _enable(client, root)
    db.expire_all()
    assert client.get("/platform/organizations", headers=_auth(db.get(User, root.id))).status_code == 200
    code = totp.code_at(secret, time.time() + totp.STEP)
    assert client.post("/auth/mfa/disable", json={"password": PASSWORD, "code": code}, headers=_auth(root)).status_code == 403


def test_org_users_are_not_forced(env, monkeypatch):
    client, _, admin, *_ = env
    monkeypatch.setenv("APP_ENV", "production")
    me = client.get("/users/me", headers=_auth(admin)).json()
    assert me["mfa_setup_required"] is False
