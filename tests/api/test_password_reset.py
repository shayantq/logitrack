"""
بازیابی رمز توسط خود کاربر و پیام‌های خودکار:
  - بدون پیامک/ایمیل تنظیم‌شده هیچ‌چیز ارسال نمی‌شود و هیچ عملیاتی خطا نمی‌دهد
  - پاسخ درخواست کد برای حساب موجود و ناموجود یکسان است (وجود حساب فاش نمی‌شود)
  - کد با موبایل، ایمیل یا نام کاربری؛ کد اشتباه، سقف تلاش، انقضا، یک‌بارمصرف بودن و باطل شدن نشست‌های قبلی
  - پیام به متقاضی سازمان هنگام ثبت، تأیید (همراه رمز موقت) و رد
"""
import re
from datetime import timedelta

import pytest

from app.core.rate_limit import password_reset_confirm_limiter, password_reset_request_limiter
from app.core.security import bcrypt_context
from app.core.tenancy import set_tenant
from app.models import Organization, PasswordReset, RoleEnum, User
from app.services import messaging, user_service


@pytest.fixture()
def env(api_env, monkeypatch):
    client, Session = api_env
    password_reset_request_limiter.reset()
    password_reset_confirm_limiter.reset()
    sent = []
    monkeypatch.setattr(messaging, "queue_sms", lambda mobile, text: bool(mobile) and not sent.append(("sms", mobile, text)))
    monkeypatch.setattr(messaging, "queue_email", lambda to, subject, text: bool(to) and not sent.append(("email", to, text)))
    db = Session()
    org = Organization(name="فروشگاه آزمون", slug="test")
    db.add(org)
    db.commit()
    set_tenant(db, org.id)
    user = User(username="ali_admin", email="ali@example.com", mobile="09121234567", role=RoleEnum.ORG_ADMIN,
                hashed_password=bcrypt_context.hash("old-secret"), full_name="علی", token_version=3,
                failed_logins=4)
    db.add(user)
    db.commit()
    set_tenant(db, None)
    try:
        yield client, db, user, sent, monkeypatch
    finally:
        db.close()


def _enable(monkeypatch, sms=True, email=True):
    monkeypatch.setattr(messaging, "sms_enabled", lambda: sms)
    monkeypatch.setattr(messaging, "email_enabled", lambda: email)


def _code(sent) -> str:
    return re.search(r"[0-9]{6}", next(t for _, _, t in reversed(sent) if "کد بازیابی" in t)).group()


def test_nothing_is_sent_without_configured_channels(env):
    client, db, user, sent, _ = env
    assert client.get("/auth/password-reset").json() == {"sms": False, "email": False}
    res = client.post("/auth/password-reset/request", json={"identifier": "ali_admin"})
    assert res.status_code == 200 and sent == [] and db.query(PasswordReset).count() == 0


def test_reset_by_mobile_sms_and_sessions_are_revoked(env):
    client, db, user, sent, monkeypatch = env
    _enable(monkeypatch)
    unknown = client.post("/auth/password-reset/request", json={"identifier": "nobody"}).json()
    known = client.post("/auth/password-reset/request", json={"identifier": "۰۹۱۲ ۱۲۳ ۴۵۶۷"}).json()
    assert unknown == known                                   # همان پاسخ برای حساب ناموجود
    assert [s[:2] for s in sent] == [("sms", "09121234567")]
    code = _code(sent)
    assert db.query(PasswordReset).one().code_hash != code    # خود کد ذخیره نمی‌شود

    bad = client.post("/auth/password-reset/confirm", json={"identifier": "ali_admin", "code": "000000" if code != "000000" else "111111",
                                                           "new_password": "new-secret-1"})
    assert bad.status_code == 400 and "۴ بار" in bad.json()["detail"]
    ok = client.post("/auth/password-reset/confirm", json={"identifier": "ali_admin", "code": code, "new_password": "new-secret-1"})
    assert ok.status_code == 200, ok.text
    db.expire_all()
    u = db.get(User, user.id)
    assert bcrypt_context.verify("new-secret-1", u.hashed_password)
    assert (u.token_version, u.failed_logins, u.must_change_password) == (4, 0, False)
    assert client.post("/auth/token", data={"username": "ali_admin", "password": "new-secret-1"}).status_code == 200
    # کد یک‌بارمصرف است
    again = client.post("/auth/password-reset/confirm", json={"identifier": "ali_admin", "code": code, "new_password": "other-pass"})
    assert again.status_code == 400


def test_email_fallback_attempt_limit_and_expiry(env):
    client, db, user, sent, monkeypatch = env
    _enable(monkeypatch, sms=False, email=True)
    client.post("/auth/password-reset/request", json={"identifier": "ALI@example.com"})
    assert sent[-1][:2] == ("email", "ali@example.com")
    code = _code(sent)
    wrong = "999999" if code != "999999" else "888888"
    for _ in range(user_service.RESET_MAX_ATTEMPTS):
        client.post("/auth/password-reset/confirm", json={"identifier": "ali_admin", "code": wrong, "new_password": "new-secret-1"})
    blocked = client.post("/auth/password-reset/confirm", json={"identifier": "ali_admin", "code": code, "new_password": "new-secret-1"})
    assert blocked.status_code == 400                         # بعد از ۵ تلاش اشتباه، کد درست هم پذیرفته نمی‌شود

    client.post("/auth/password-reset/request", json={"identifier": "ali_admin"})
    fresh = _code(sent)
    row = db.query(PasswordReset).filter(PasswordReset.used_at.is_(None)).one()
    row.expires_at = row.created_at - timedelta(seconds=1)
    db.commit()
    expired = client.post("/auth/password-reset/confirm", json={"identifier": "ali_admin", "code": fresh, "new_password": "new-secret-1"})
    assert expired.status_code == 400


def test_hourly_cap_and_inactive_users(env):
    client, db, user, sent, monkeypatch = env
    _enable(monkeypatch)
    for _ in range(5):
        client.post("/auth/password-reset/request", json={"identifier": "ali_admin"})
    assert len(sent) == user_service.RESET_MAX_PER_HOUR
    u = db.get(User, user.id)
    u.is_active = False
    db.commit()
    sent.clear()
    db.query(PasswordReset).delete()
    db.commit()
    client.post("/auth/password-reset/request", json={"identifier": "ali_admin"})
    assert sent == []


def test_organization_request_messages(env):
    client, db, user, sent, monkeypatch = env
    from app.models import OrganizationRequest
    from app.schemas.organization import OrganizationRequestApprove, OrganizationRequestReject
    from app.services import organization_request_service as ors
    req = OrganizationRequest(tracking_code="REQ-TEST01", status="pending", name="پخش آزمون", contact_name="سارا",
                              contact_mobile="09351112233", contact_email="sara@example.com", national_id="10101234567",
                              province="قزوین", city="قزوین", requested_features=[])
    db.add(req)
    db.commit()
    platform = User(username="root", email="root@x.io", role=RoleEnum.PLATFORM_ADMIN, hashed_password="x")
    db.add(platform)
    db.commit()
    result = ors.approve_request(db, platform, req.id, OrganizationRequestApprove(slug="pakhsh-test"))
    texts = [t for _, _, t in sent]
    assert any(result["temporary_password"] in t and result["admin_username"] in t for t in texts)
    assert {kind for kind, _, _ in sent} == {"sms", "email"}
    admin = db.query(User).filter(User.username == result["admin_username"]).one()
    assert admin.mobile == "09351112233"                       # بازیابی رمز با موبایل متقاضی ممکن است

    sent.clear()
    req2 = OrganizationRequest(tracking_code="REQ-TEST02", status="pending", name="پخش دوم", contact_mobile="09351112244",
                               national_id="10101234568", requested_features=[])
    db.add(req2)
    db.commit()
    ors.reject_request(db, platform, req2.id, OrganizationRequestReject(reason="اطلاعات ناقص است"))
    assert sent and "اطلاعات ناقص است" in sent[0][2]


def test_delivery_uses_provider_settings(monkeypatch):
    """ارسال واقعی: درخواست کاوه‌نگار و پیام SMTP با تنظیمات .env (بدون تماس با اینترنت)."""
    import io
    import json as _json
    calls = {}

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        calls["url"], calls["data"] = req.full_url, req.data.decode()
        return _Resp(_json.dumps({"return": {"status": 200}}).encode())

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls["smtp"] = (host, port)

        def starttls(self, context):
            calls["tls"] = True

        def login(self, user, password):
            calls["login"] = user

        def send_message(self, msg):
            calls["to"], calls["subject"] = msg["To"], msg["Subject"]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    for k, v in {"SMS_PROVIDER": "kavenegar", "SMS_API_KEY": "KEY123", "SMS_SENDER": "10004346",
                 "SMTP_HOST": "mail.example.ir", "SMTP_USER": "no-reply@passineh.ir", "SMTP_PASSWORD": "x"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(messaging.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(messaging.smtplib, "SMTP", FakeSMTP)

    assert messaging.deliver_sms("09121234567", "سلام") is True
    assert "/KEY123/sms/send.json" in calls["url"] and "receptor=09121234567" in calls["data"] and "sender=10004346" in calls["data"]
    assert messaging.deliver_email("a@b.ir", "موضوع", "متن") is True
    assert calls["smtp"] == ("mail.example.ir", 587) and calls["tls"] and calls["login"] == "no-reply@passineh.ir"
    assert calls["to"] == "a@b.ir"
