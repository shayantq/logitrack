"""
تست‌های مرحله ۲: درخواست عمومی ثبت سازمان، بررسی توسط ادمین پلتفرم،
و پروفایل/لوگوی سازمان.
"""
import base64
from datetime import timedelta

import pytest

from app.core import storage
from app.core.rate_limit import organization_request_limiter
from app.core.security import bcrypt_context, create_access_token
from app.core.tenancy import set_tenant
from app.models import Organization, OrganizationRequest, RoleEnum, User, Warehouse

PASSWORD = "secret123"
# کوچک‌ترین PNG معتبر (۱×۱ پیکسل)
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _auth(user: User) -> dict:
    token = create_access_token(user.username, user.id, timedelta(minutes=5))
    return {"Authorization": f"Bearer {token}"}


def _valid_request(**overrides) -> dict:
    body = {
        "name": "فروشگاه نمونه قزوين",              # «ي» عربی — باید به «ی» فارسی تبدیل شود
        "legal_name": "شرکت بازرگانی نمونه",
        "business_type": "retail",
        "national_id": "۱۰۱۰۱۲۳۴۵۶۷",              # ارقام فارسی — باید لاتین ذخیره شود
        "province": "قزوین",
        "city": "قزوین",
        "address": "قزوین، خیابان پیروزی، پلاک ۱۲",
        "postal_code": "34151-12345",
        "phone": "028-33334444",
        "employee_count": "11-50",
        "monthly_order_volume": "100-1000",
        "warehouse_count": 2,
        "fleet_size": 5,
        "requested_features": ["transport", "warehouse", "stocktaking"],
        "contact_name": "امیرحسین رضایی",
        "contact_mobile": "۰۹۱۲۱۲۳۴۵۶۷",
        "contact_email": "owner@example.com",
        "notes": "می‌خواهیم انبارگردانی ماهانه داشته باشیم.",
    }
    body.update(overrides)
    return body


@pytest.fixture(autouse=True)
def _isolated_storage_and_limits(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "MEDIA_ROOT", tmp_path / "media")
    organization_request_limiter.reset()
    yield
    organization_request_limiter.reset()


@pytest.fixture()
def env(api_env):
    client, TestingSession = api_env
    db = TestingSession()
    password_hash = bcrypt_context.hash(PASSWORD)
    platform_admin = User(username="root", email="root@example.com", role=RoleEnum.PLATFORM_ADMIN, hashed_password=password_hash)
    support = User(username="helpdesk", email="help@example.com", role=RoleEnum.PLATFORM_SUPPORT, hashed_password=password_hash)
    db.add_all([platform_admin, support])
    db.commit()

    org = Organization(name="سازمان موجود", slug="existing", national_id="10109999999")
    db.add(org)
    db.commit()
    set_tenant(db, org.id)
    warehouse = Warehouse(name="انبار", location="تهران")
    db.add(warehouse)
    db.commit()
    org_admin = User(username="existing_admin", email="ea@example.com", role=RoleEnum.ORG_ADMIN, hashed_password=password_hash)
    manager = User(username="existing_mgr", email="em@example.com", role=RoleEnum.WAREHOUSE_MANAGER,
                   hashed_password=password_hash, warehouse_id=warehouse.id)
    db.add_all([org_admin, manager])
    db.commit()
    set_tenant(db, None)
    try:
        yield client, db, platform_admin, support, org, org_admin, manager
    finally:
        db.close()


def _submit(client, **overrides):
    return client.post("/organization-requests", json=_valid_request(**overrides))


# ---------------------------------------------------------------------------
# فرم عمومی
# ---------------------------------------------------------------------------

def test_submit_request_normalizes_and_returns_tracking_code(env):
    client, db, *_ = env
    res = _submit(client)
    assert res.status_code == 201, res.text
    code = res.json()["tracking_code"]
    assert code.startswith("REQ-")

    stored = db.query(OrganizationRequest).one()
    assert stored.national_id == "10101234567"
    assert stored.contact_mobile == "09121234567"
    assert stored.postal_code == "3415112345"
    assert stored.name == "فروشگاه نمونه قزوین"
    assert stored.requested_features == ["transport", "warehouse", "stocktaking"]
    assert stored.status == "pending"

    status = client.get(f"/organization-requests/status/{code.lower()}").json()
    assert status["status"] == "pending"
    assert "national_id" not in status  # اطلاعات داخلی به بیرون نمی‌رود


@pytest.mark.parametrize("override", [
    {"national_id": "12345"},
    {"contact_mobile": "02112345678"},
    {"province": "کالیفرنیا"},
    {"requested_features": []},
    {"business_type": "casino"},
    {"postal_code": "123"},
    {"city": "سسس"},                       # شهر خارج از فهرست
    {"province": "تهران", "city": "قزوین"},   # شهر استان دیگر
])
def test_invalid_request_fields_rejected(env, override):
    client, *_ = env
    assert _submit(client, **override).status_code == 422


def test_duplicate_pending_request_and_existing_org_rejected(env):
    client, *_ = env
    assert _submit(client).status_code == 201
    assert _submit(client).status_code == 400
    # شناسه ملی سازمانی که از قبل ثبت شده
    assert _submit(client, national_id="10109999999").status_code == 400


def test_honeypot_submission_is_silently_dropped(env):
    client, db, *_ = env
    res = _submit(client, company_fax="bot was here")
    assert res.status_code == 201
    assert db.query(OrganizationRequest).count() == 0


def test_public_form_is_rate_limited(env):
    client, *_ = env
    codes = [_submit(client, national_id=f"1010000000{i}").status_code for i in range(6)]
    assert codes[:5] == [201] * 5
    assert codes[5] == 429


def test_referral_source_is_optional(env):
    client, db, *_ = env
    assert _submit(client).status_code == 201
    stored = db.query(OrganizationRequest).one()
    assert stored.referral_source is None and stored.referral_detail is None


def test_referral_other_requires_detail_and_is_shown_to_platform(env):
    client, db, platform_admin, *_ = env
    # «سایر» بدون توضیح پذیرفته نمی‌شود
    assert _submit(client, referral_source="other").status_code == 422
    assert _submit(client, referral_source="other", referral_detail="  ").status_code == 422
    assert _submit(client, referral_source="tiktok").status_code == 422

    assert _submit(client, referral_source="other", referral_detail="پادكست لجستیک").status_code == 201
    listed = client.get("/platform/organization-requests", headers=_auth(platform_admin)).json()
    assert listed[0]["referral_source"] == "other"
    assert listed[0]["referral_detail"] == "پادکست لجستیک"   # «ك» عربی یکسان‌سازی شد


def test_referral_detail_dropped_without_source_and_kept_for_referral(env):
    client, db, *_ = env
    assert _submit(client, referral_detail="بی‌معنی").status_code == 201
    assert db.query(OrganizationRequest).one().referral_detail is None

    assert _submit(client, national_id="10100000001", referral_source="referral", referral_detail="شرکت معرف").status_code == 201
    assert _submit(client, national_id="10100000002", referral_source="instagram").status_code == 201
    rows = {r.national_id: r for r in db.query(OrganizationRequest).all()}
    assert (rows["10100000001"].referral_source, rows["10100000001"].referral_detail) == ("referral", "شرکت معرف")
    assert (rows["10100000002"].referral_source, rows["10100000002"].referral_detail) == ("instagram", None)


def test_unknown_tracking_code(env):
    client, *_ = env
    assert client.get("/organization-requests/status/REQ-NOPE0000").status_code == 404


# ---------------------------------------------------------------------------
# بررسی درخواست توسط ادمین پلتفرم
# ---------------------------------------------------------------------------

def test_only_platform_staff_see_requests_and_only_admin_reviews(env):
    client, db, platform_admin, support, org, org_admin, manager = env
    _submit(client)
    request_id = db.query(OrganizationRequest).one().id

    assert client.get("/platform/organization-requests", headers=_auth(org_admin)).status_code == 403
    listed = client.get("/platform/organization-requests?status=pending", headers=_auth(support))
    assert listed.status_code == 200 and len(listed.json()) == 1
    assert client.get("/platform/organization-requests?status=approved", headers=_auth(support)).json() == []

    assert client.post(f"/platform/organization-requests/{request_id}/approve", json={"slug": "qazvin"},
                       headers=_auth(support)).status_code == 403
    assert client.post(f"/platform/organization-requests/{request_id}/reject", json={"reason": "تست"},
                       headers=_auth(support)).status_code == 403


def test_approve_creates_organization_with_profile_and_admin(env):
    client, db, platform_admin, *_ = env
    code = _submit(client).json()["tracking_code"]
    request_id = db.query(OrganizationRequest).one().id

    res = client.post(f"/platform/organization-requests/{request_id}/approve", json={"slug": "Qazvin-Shop"},
                      headers=_auth(platform_admin))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["organization"]["slug"] == "qazvin-shop"
    assert body["admin_username"] == "qazvin_shop_admin"
    temp_password = body["temporary_password"]
    assert temp_password

    db.expire_all()
    org = db.query(Organization).filter(Organization.slug == "qazvin-shop").one()
    assert org.national_id == "10101234567"
    assert org.province == "قزوین"
    assert org.fleet_size == 5
    assert org.contact_email == "owner@example.com"
    # انبار پیش‌فرض در شهر سازمان (مبدأ مسیرها روی نقشه)
    set_tenant(db, org.id)
    warehouse = db.query(Warehouse).one()
    assert (warehouse.province, warehouse.city, warehouse.name) == ("قزوین", "قزوین", "انبار مرکزی قزوین")
    set_tenant(db, None)

    # ادمین سازمان جدید با رمز موقت وارد می‌شود و پروفایل منتقل‌شده را می‌بیند
    token = client.post("/auth/token", data={"username": "qazvin_shop_admin", "password": temp_password}).json()["access_token"]
    profile = client.get("/organization/profile", headers={"Authorization": f"Bearer {token}"}).json()
    assert profile["legal_name"] == "شرکت بازرگانی نمونه"
    assert profile["monthly_order_volume"] == "100-1000"

    status = client.get(f"/organization-requests/status/{code}").json()
    assert status["status"] == "approved"

    # یک درخواست دوبار بررسی نمی‌شود
    again = client.post(f"/platform/organization-requests/{request_id}/approve", json={"slug": "other"},
                        headers=_auth(platform_admin))
    assert again.status_code == 400


def test_approve_with_explicit_credentials_and_conflicts(env):
    client, db, platform_admin, support, org, org_admin, manager = env
    _submit(client)
    request_id = db.query(OrganizationRequest).one().id
    h = _auth(platform_admin)

    assert client.post(f"/platform/organization-requests/{request_id}/approve", json={"slug": "existing"}, headers=h).status_code == 400
    assert client.post(f"/platform/organization-requests/{request_id}/approve",
                       json={"slug": "new-one", "admin_username": "existing_admin"}, headers=h).status_code == 400

    res = client.post(f"/platform/organization-requests/{request_id}/approve",
                      json={"slug": "new-one", "admin_username": "boss", "admin_password": "mypassword1",
                            "admin_email": "boss@example.com"}, headers=h)
    assert res.status_code == 200, res.text
    assert res.json()["temporary_password"] is None
    assert client.post("/auth/token", data={"username": "boss", "password": "mypassword1"}).status_code == 200


def test_reject_request_with_reason(env):
    client, db, platform_admin, *_ = env
    code = _submit(client).json()["tracking_code"]
    request_id = db.query(OrganizationRequest).one().id

    res = client.post(f"/platform/organization-requests/{request_id}/reject",
                      json={"reason": "مدارک ناقص است"}, headers=_auth(platform_admin))
    assert res.status_code == 200 and res.json()["status"] == "rejected"

    status = client.get(f"/organization-requests/status/{code}").json()
    assert status["status"] == "rejected"
    assert status["rejection_reason"] == "مدارک ناقص است"

    # پس از رد، کسب‌وکار می‌تواند دوباره درخواست بدهد
    assert _submit(client).status_code == 201


# ---------------------------------------------------------------------------
# پروفایل سازمان
# ---------------------------------------------------------------------------

def test_profile_read_by_members_and_edited_only_by_org_admin(env):
    client, db, platform_admin, support, org, org_admin, manager = env

    assert client.get("/organization/profile", headers=_auth(manager)).status_code == 200
    assert client.put("/organization/profile", json={"city": "کرج"}, headers=_auth(manager)).status_code == 403

    res = client.put("/organization/profile", json={"city": "كرج", "postal_code": "۳۱۹۹۹۸۸۸۷۷", "fleet_size": 12},
                     headers=_auth(org_admin))
    assert res.status_code == 200, res.text
    assert res.json()["city"] == "کرج"
    assert res.json()["postal_code"] == "3199988877"
    assert res.json()["slug"] == "existing"  # slug از این مسیر قابل تغییر نیست

    assert client.put("/organization/profile", json={"postal_code": "12"}, headers=_auth(org_admin)).status_code == 422
    assert client.put("/organization/profile", json={"province": "نامعتبر"}, headers=_auth(org_admin)).status_code == 422

    # پلتفرم پروفایل کامل را می‌بیند
    platform_view = client.get(f"/platform/organizations/{org.id}/profile", headers=_auth(support)).json()
    assert platform_view["fleet_size"] == 12


def test_profile_national_id_must_be_unique(env):
    client, db, platform_admin, support, org, org_admin, manager = env
    other = Organization(name="دیگری", slug="other", national_id="10108888888")
    db.add(other)
    db.commit()
    res = client.put("/organization/profile", json={"national_id": "10108888888"}, headers=_auth(org_admin))
    assert res.status_code == 400


def test_platform_staff_cannot_use_tenant_profile(env):
    client, db, platform_admin, *_ = env
    assert client.get("/organization/profile", headers=_auth(platform_admin)).status_code == 403


# ---------------------------------------------------------------------------
# لوگو
# ---------------------------------------------------------------------------

def test_logo_upload_download_and_delete(env):
    client, db, platform_admin, support, org, org_admin, manager = env

    assert client.get("/organization/logo", headers=_auth(org_admin)).status_code == 404

    res = client.post("/organization/logo", files={"file": ("logo.png", TINY_PNG, "image/png")}, headers=_auth(org_admin))
    assert res.status_code == 200, res.text
    assert res.json()["has_logo"] is True

    got = client.get("/organization/logo", headers=_auth(manager))
    assert got.status_code == 200
    assert got.content == TINY_PNG
    assert got.headers["content-type"] == "image/png"

    assert client.get(f"/platform/organizations/{org.id}/logo", headers=_auth(support)).content == TINY_PNG

    assert client.delete("/organization/logo", headers=_auth(org_admin)).status_code == 204
    assert client.get("/organization/logo", headers=_auth(org_admin)).status_code == 404


def test_logo_rejects_non_images_oversize_and_non_admins(env):
    client, db, platform_admin, support, org, org_admin, manager = env

    fake = client.post("/organization/logo", files={"file": ("logo.png", b"<svg onload=alert(1)>", "image/png")},
                       headers=_auth(org_admin))
    assert fake.status_code == 400

    huge = TINY_PNG + b"\0" * (2 * 1024 * 1024)
    assert client.post("/organization/logo", files={"file": ("big.png", huge, "image/png")},
                       headers=_auth(org_admin)).status_code == 400

    assert client.post("/organization/logo", files={"file": ("logo.png", TINY_PNG, "image/png")},
                       headers=_auth(manager)).status_code == 403
