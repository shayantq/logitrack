"""
تست‌های مرحله ۶: ثبت‌نام راننده با لینک دعوت، تکمیل پرونده و مدارک، بررسی ادمین،
و دو قانون اصلی:
  - راننده تأییدنشده هیچ سفارشی نمی‌گیرد (نه خودکار، نه دستی)
  - فایل مدارک فقط برای خود راننده و ادمین همان سازمان قابل دریافت است
"""
import base64
from datetime import date, datetime, timedelta, timezone

import pytest

from app.core import storage
from app.core.rate_limit import driver_signup_limiter
from app.core.security import bcrypt_context, create_access_token
from app.core.tenancy import set_tenant
from app.models import DriverInvite, Inventory, Organization, Product, RoleEnum, User, Vehicle, Warehouse
from tests.factories import order_payload

PASSWORD = "secret123"
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
TINY_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 64
IMAGE_DOCS = ("national_card", "selfie", "driving_license", "vehicle_photo", "vehicle_card", "technical_inspection")


def _national_code(prefix: str = "001234567") -> str:
    """کد ملی معتبر با رقم کنترل درست."""
    remainder = sum(int(prefix[i]) * (10 - i) for i in range(9)) % 11
    return prefix + str(remainder if remainder < 2 else 11 - remainder)


def _auth(user_or_token) -> dict:
    token = user_or_token if isinstance(user_or_token, str) else create_access_token(
        user_or_token.username, user_or_token.id, timedelta(minutes=5))
    return {"Authorization": f"Bearer {token}"}


FULL_PROFILE = {
    "first_name": "علی", "last_name": "رضایی", "national_code": _national_code(),
    "birth_date": "1990-05-01", "mobile": "09121112233",
    "province": "قزوین", "city": "قزوین", "address": "قزوین، خیابان پیروزی، پلاک ۱۲",
    "vehicle_type": "pickup", "vehicle_model": "نیسان زامیاد", "license_plate": "۱۲ ب ۳۴۵ ایران ۶۷",
    "max_weight_kg": 1200, "intercity": True,
    "inspection_expiry": (date.today() + timedelta(days=200)).isoformat(),
}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "MEDIA_ROOT", tmp_path / "media")
    driver_signup_limiter.reset()
    yield
    driver_signup_limiter.reset()


@pytest.fixture()
def env(api_env):
    client, TestingSession = api_env
    db = TestingSession()
    password_hash = bcrypt_context.hash(PASSWORD)
    platform_admin = User(username="root", email="root@x.io", role=RoleEnum.PLATFORM_ADMIN, hashed_password=password_hash)
    db.add(platform_admin)
    db.commit()

    orgs = {}
    for slug in ("alpha", "beta"):
        org = Organization(name=f"سازمان {slug}", slug=slug)
        db.add(org)
        db.commit()
        set_tenant(db, org.id)
        warehouse = Warehouse(name="انبار", location="قزوین")
        db.add(warehouse)
        db.commit()
        admin = User(username=f"{slug}_admin", email=f"{slug}a@x.io", role=RoleEnum.ORG_ADMIN, hashed_password=password_hash)
        manager = User(username=f"{slug}_mgr", email=f"{slug}m@x.io", role=RoleEnum.WAREHOUSE_MANAGER,
                       hashed_password=password_hash, warehouse_id=warehouse.id)
        db.add_all([admin, manager])
        db.commit()
        orgs[slug] = {"org": org, "admin": admin, "manager": manager, "warehouse": warehouse}
        set_tenant(db, None)
    try:
        yield client, db, platform_admin, orgs
    finally:
        db.close()


def _invite(client, admin, **body) -> dict:
    res = client.post("/drivers/invites", json=body, headers=_auth(admin))
    assert res.status_code == 201, res.text
    return res.json()


def _signup(client, code, username="new_driver", **overrides) -> str:
    body = {"full_name": "علی رضایی", "mobile": "۰۹۱۲۱۱۱۲۲۳۳", "username": username, "password": PASSWORD}
    body.update(overrides)
    res = client.post(f"/driver-signup/{code}", json=body)
    assert res.status_code == 201, res.text
    return res.json()["access_token"]


def _complete_application(client, token, profile=None, docs=IMAGE_DOCS):
    res = client.put("/driver-onboarding", json=profile or FULL_PROFILE, headers=_auth(token))
    assert res.status_code == 200, res.text
    for kind in docs:
        res = client.post(f"/driver-onboarding/documents/{kind}", files={"file": ("a.png", TINY_PNG, "image/png")},
                          headers=_auth(token))
        assert res.status_code == 200, res.text
    res = client.post("/driver-onboarding/documents/video", files={"file": ("v.mp4", TINY_MP4, "video/mp4")},
                      headers=_auth(token))
    assert res.status_code == 200, res.text
    return res.json()


def _submitted_driver(client, admin, username="new_driver") -> tuple[str, int]:
    code = _invite(client, admin)["code"]
    token = _signup(client, code, username=username)
    _complete_application(client, token)
    res = client.post("/driver-onboarding/submit", headers=_auth(token))
    assert res.status_code == 200, res.text
    return token, res.json()["user_id"]


# ---------------------------------------------------------------------------
# لینک دعوت و ثبت‌نام
# ---------------------------------------------------------------------------
def test_invite_signup_creates_incomplete_driver_in_inviting_org(env):
    client, db, _, orgs = env
    alpha = orgs["alpha"]
    invite = _invite(client, alpha["admin"], label="رانندگان قزوین", max_uses=2)
    assert invite["is_usable"] and len(invite["code"]) == 8

    info = client.get(f"/driver-signup/{invite['code'].lower()}")
    assert info.status_code == 200 and info.json()["organization_name"] == "سازمان alpha"

    token = _signup(client, invite["code"])
    me = client.get("/users/me", headers=_auth(token)).json()
    assert me["role"] == "driver" and me["driver_status"] == "incomplete"
    assert me["organization"]["slug"] == "alpha"

    app = client.get("/driver-onboarding", headers=_auth(token)).json()
    assert app["mobile"] == "09121112233" and app["first_name"] == "علی" and app["invite_label"] == "رانندگان قزوین"
    assert "video" in app["missing"] and "national_code" in app["missing"]

    invites = client.get("/drivers/invites", headers=_auth(alpha["admin"])).json()
    assert invites[0]["uses"] == 1


def test_invite_limits_and_permissions(env):
    client, db, platform_admin, orgs = env
    alpha = orgs["alpha"]
    assert client.post("/drivers/invites", json={}, headers=_auth(alpha["manager"])).status_code == 403
    assert client.post("/drivers/invites", json={}, headers=_auth(platform_admin)).status_code == 403
    assert client.get("/driver-signup/NOPE1234").status_code == 404

    once = _invite(client, alpha["admin"], max_uses=1)
    _signup(client, once["code"], username="first_one")
    assert client.post(f"/driver-signup/{once['code']}", json={
        "full_name": "دومی رانندگان", "mobile": "09120000001", "username": "second_one", "password": PASSWORD,
    }).status_code == 400

    disabled = _invite(client, alpha["admin"])
    res = client.patch(f"/drivers/invites/{disabled['id']}", json={"is_active": False}, headers=_auth(alpha["admin"]))
    assert res.json()["is_usable"] is False
    assert client.get(f"/driver-signup/{disabled['code']}").status_code == 400

    expired = _invite(client, alpha["admin"], expires_in_days=1)
    row = db.query(DriverInvite).filter(DriverInvite.id == expired["id"]).first()
    row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
    db.commit()
    assert client.get(f"/driver-signup/{expired['code']}").status_code == 400

    # دعوت سازمان دیگر برای ادمین alpha دیده/قابل تغییر نیست
    beta_invite = _invite(client, orgs["beta"]["admin"])
    assert client.patch(f"/drivers/invites/{beta_invite['id']}", json={"is_active": False},
                        headers=_auth(alpha["admin"])).status_code == 404


def test_duplicate_username_rejected(env):
    client, db, _, orgs = env
    code = _invite(client, orgs["alpha"]["admin"])["code"]
    res = client.post(f"/driver-signup/{code}", json={
        "full_name": "تکراری", "mobile": "09120000001", "username": "alpha_admin", "password": PASSWORD})
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# پرونده و مدارک
# ---------------------------------------------------------------------------
def test_profile_validation_and_normalization(env):
    client, db, _, orgs = env
    token = _signup(client, _invite(client, orgs["alpha"]["admin"])["code"])

    assert client.put("/driver-onboarding", json={"national_code": "0012345678"}, headers=_auth(token)).status_code == 422
    assert client.put("/driver-onboarding", json={"national_code": "1111111111"}, headers=_auth(token)).status_code == 422
    assert client.put("/driver-onboarding", json={"license_plate": "ABC"}, headers=_auth(token)).status_code == 422

    res = client.put("/driver-onboarding", json={"license_plate": "۱۲ ب ۳۴۵ ایران ۶۷", "vehicle_type": "pickup"},
                     headers=_auth(token))
    assert res.status_code == 200 and res.json()["license_plate"] == "12ب345-67"
    moto = client.put("/driver-onboarding", json={"license_plate": "۱۲۳-۴۵۶۷۸", "vehicle_type": "motorcycle"},
                      headers=_auth(token)).json()
    assert moto["license_plate"] == "123-45678"
    assert "technical_inspection" not in moto["required_documents"]   # معاینه فنی فقط برای خودرو


def test_documents_are_type_checked(env):
    client, db, _, orgs = env
    token = _signup(client, _invite(client, orgs["alpha"]["admin"])["code"])
    up = lambda kind, data: client.post(f"/driver-onboarding/documents/{kind}",
                                        files={"file": ("f", data, "application/octet-stream")}, headers=_auth(token))
    assert up("selfie", b"<svg onload=alert(1)>").status_code == 400
    assert up("selfie", TINY_MP4).status_code == 400          # ویدیو به‌جای عکس
    assert up("video", TINY_PNG).status_code == 400           # عکس به‌جای ویدیو
    assert up("video", TINY_MP4).status_code == 200
    assert up("selfie", TINY_PNG + b"\0" * (5 * 1024 * 1024)).status_code == 400
    assert up("passport", TINY_PNG).status_code == 422

    # جایگزینی: فایل قبلی از دیسک پاک می‌شود
    up("selfie", TINY_PNG)
    first = list((storage.MEDIA_ROOT / "drivers").rglob("selfie-*"))
    up("selfie", TINY_PNG)
    second = list((storage.MEDIA_ROOT / "drivers").rglob("selfie-*"))
    assert len(first) == len(second) == 1 and first != second
    assert client.get("/driver-onboarding/documents/selfie", headers=_auth(token)).content == TINY_PNG


def test_submit_requires_complete_and_consistent_application(env):
    client, db, _, orgs = env
    token = _signup(client, _invite(client, orgs["alpha"]["admin"])["code"])
    assert client.post("/driver-onboarding/submit", headers=_auth(token)).status_code == 400

    _complete_application(client, token, {**FULL_PROFILE, "max_weight_kg": 9000})
    res = client.post("/driver-onboarding/submit", headers=_auth(token))
    assert res.status_code == 400 and "سقف بار" in res.json()["detail"]

    client.put("/driver-onboarding", json={"max_weight_kg": 1200, "license_plate": "123-45678"}, headers=_auth(token))
    res = client.post("/driver-onboarding/submit", headers=_auth(token))
    assert res.status_code == 400 and "پلاک" in res.json()["detail"]

    client.put("/driver-onboarding", json={"license_plate": "12ب345-67", "birth_date": "2015-01-01"}, headers=_auth(token))
    assert "سن" in client.post("/driver-onboarding/submit", headers=_auth(token)).json()["detail"]

    client.put("/driver-onboarding", json={"birth_date": "1990-01-01"}, headers=_auth(token))
    res = client.post("/driver-onboarding/submit", headers=_auth(token))
    assert res.status_code == 200 and res.json()["driver_status"] == "submitted" and res.json()["missing"] == []

    # پس از ارسال، ویرایش و آپلود قفل است
    assert client.put("/driver-onboarding", json={"city": "تهران"}, headers=_auth(token)).status_code == 400
    assert client.post("/driver-onboarding/documents/selfie", files={"file": ("a.png", TINY_PNG, "image/png")},
                       headers=_auth(token)).status_code == 400


# ---------------------------------------------------------------------------
# بررسی ادمین
# ---------------------------------------------------------------------------
def test_reject_then_fix_and_approve_creates_vehicle(env):
    client, db, _, orgs = env
    admin = orgs["alpha"]["admin"]
    token, driver_id = _submitted_driver(client, admin)

    pending = client.get("/drivers/applications?status=submitted", headers=_auth(admin)).json()
    assert [a["user_id"] for a in pending] == [driver_id]
    assert client.get("/drivers/applications/pending-count", headers=_auth(admin)).json()["count"] == 1
    assert client.get("/drivers/applications", headers=_auth(orgs["alpha"]["manager"])).status_code == 403

    res = client.post(f"/drivers/applications/{driver_id}/reject", json={"reason": "تصویر کارت ملی خوانا نیست."},
                      headers=_auth(admin))
    assert res.json()["driver_status"] == "rejected"
    mine = client.get("/driver-onboarding", headers=_auth(token)).json()
    assert mine["rejection_reason"] == "تصویر کارت ملی خوانا نیست."

    client.post("/driver-onboarding/documents/national_card", files={"file": ("a.png", TINY_PNG, "image/png")},
                headers=_auth(token))
    assert client.post("/driver-onboarding/submit", headers=_auth(token)).json()["rejection_reason"] is None

    res = client.post(f"/drivers/applications/{driver_id}/approve", headers=_auth(admin))
    assert res.status_code == 200, res.text
    approved = res.json()
    assert approved["driver_status"] == "approved" and approved["vehicle_id"]
    vehicle = client.get("/vehicles/", headers=_auth(token)).json()[0]
    assert vehicle["license_plate"] == "12ب345-67" and vehicle["capacity_kg"] == 1200
    assert vehicle["type"] == "pickup" and vehicle["city"] == "قزوین" and vehicle["status"] == "available"
    assert client.post(f"/drivers/applications/{driver_id}/approve", headers=_auth(admin)).status_code == 400


def test_other_org_cannot_see_or_review_application(env):
    client, db, _, orgs = env
    _, driver_id = _submitted_driver(client, orgs["alpha"]["admin"])
    beta_admin = orgs["beta"]["admin"]
    assert client.get("/drivers/applications", headers=_auth(beta_admin)).json() == []
    assert client.get(f"/drivers/applications/{driver_id}", headers=_auth(beta_admin)).status_code == 404
    assert client.post(f"/drivers/applications/{driver_id}/approve", headers=_auth(beta_admin)).status_code == 404


# ---------------------------------------------------------------------------
# ✅ تست مرحله: مدارک فقط برای ادمین همان سازمان
# ---------------------------------------------------------------------------
def test_documents_visible_only_to_driver_and_own_org_admin(env):
    client, db, platform_admin, orgs = env
    token, driver_id = _submitted_driver(client, orgs["alpha"]["admin"])
    other_token, _ = _submitted_driver(client, orgs["alpha"]["admin"], username="other_driver")
    url = f"/drivers/{driver_id}/documents/national_card"

    own_admin = client.get(url, headers=_auth(orgs["alpha"]["admin"]))
    assert own_admin.status_code == 200 and own_admin.content == TINY_PNG
    assert own_admin.headers["cache-control"].startswith("private")
    assert client.get(f"/drivers/{driver_id}/documents/video", headers=_auth(orgs["alpha"]["admin"])).content == TINY_MP4

    assert client.get(url, headers=_auth(orgs["beta"]["admin"])).status_code == 404      # سازمان دیگر
    assert client.get(url, headers=_auth(orgs["alpha"]["manager"])).status_code == 403   # مدیر انبار
    assert client.get(url, headers=_auth(platform_admin)).status_code == 403             # کارکنان پلتفرم
    assert client.get(url, headers=_auth(other_token)).status_code == 403                # راننده دیگر
    assert client.get(url).status_code == 401                                            # بدون لاگین
    # فایل‌ها هیچ مسیر عمومی ندارند
    assert client.get("/media/drivers").status_code == 404


# ---------------------------------------------------------------------------
# ✅ تست مرحله: راننده تأییدنشده هیچ سفارشی نمی‌گیرد
# ---------------------------------------------------------------------------
def test_unapproved_driver_gets_no_orders(env):
    client, db, _, orgs = env
    alpha = orgs["alpha"]
    admin = alpha["admin"]
    token, driver_id = _submitted_driver(client, admin)

    # ادمین نمی‌تواند خودرو را دستی به راننده تأییدنشده بدهد
    res = client.post("/vehicles/", json={"license_plate": "99ق999-11", "vehicle_type": "van", "capacity_kg": 1000,
                                          "driver_id": driver_id}, headers=_auth(admin))
    assert res.status_code == 400 and "احراز هویت" in res.json()["detail"]

    # حتی اگر خودرویی (مثلاً از قبل) به او وصل باشد، تخصیص خودکار و دستی ردش می‌کنند
    set_tenant(db, alpha["org"].id)
    vehicle = Vehicle(license_plate="11ب111-11", type="van", capacity_kg=1000, status="available",
                      driver_id=driver_id, city="تهران")
    product = Product(name="کالا", sku="SKU-1", price=10, weight_kg=1)
    db.add_all([vehicle, product])
    db.commit()
    db.add(Inventory(product_id=product.id, warehouse_id=alpha["warehouse"].id, quantity=50))
    db.commit()
    vehicle_id, product_id = vehicle.id, product.id
    set_tenant(db, None)

    auto = client.post("/orders/", json=order_payload(product_id), headers=_auth(admin))
    assert auto.status_code == 400, auto.text            # هیچ خودروی واجد شرایطی نیست
    manual = client.post("/orders/", json=order_payload(product_id, vehicle_id), headers=_auth(admin))
    assert manual.status_code == 400 and "احراز هویت" in manual.json()["detail"]
    assert client.get("/orders/", headers=_auth(token)).json() == []

    # پس از تأیید، همان راننده سفارش می‌گیرد
    client.post(f"/drivers/applications/{driver_id}/approve", headers=_auth(admin))
    res = client.post("/orders/", json=order_payload(product_id, vehicle_id), headers=_auth(admin))
    assert res.status_code == 201, res.text
    assert len(client.get("/orders/", headers=_auth(token)).json()) == 1


def test_existing_and_admin_created_drivers_stay_approved(env):
    client, db, _, orgs = env
    res = client.post("/auth/", json={"username": "direct_drv", "email": "d@x.io", "role": "driver", "password": PASSWORD},
                      headers=_auth(orgs["alpha"]["admin"]))
    assert res.status_code == 201 and res.json()["driver_status"] == "approved"


def _mp4(seconds: int, timescale: int = 1000) -> bytes:
    """MP4 حداقلی با جعبه mvhd (نسخه ۰) برای تست تشخیص مدت."""
    mvhd_body = bytes(4) + bytes(8) + timescale.to_bytes(4, "big") + (seconds * timescale).to_bytes(4, "big") + bytes(80)
    mvhd = (8 + len(mvhd_body)).to_bytes(4, "big") + b"mvhd" + mvhd_body
    moov = (8 + len(mvhd)).to_bytes(4, "big") + b"moov" + mvhd
    ftyp = (16).to_bytes(4, "big") + b"ftypisom" + bytes(4)
    mdat = (8 + 32).to_bytes(4, "big") + b"mdat" + bytes(32)
    return ftyp + mdat + moov   # moov در انتهای فایل، مثل ضبط اغلب گوشی‌ها


def test_video_duration_and_size_limits(env):
    client, db, _, orgs = env
    token = _signup(client, _invite(client, orgs["alpha"]["admin"])["code"])
    up = lambda data: client.post("/driver-onboarding/documents/video", files={"file": ("v.mp4", data, "video/mp4")},
                                  headers=_auth(token))
    assert storage.video_duration(_mp4(9), "mp4") == 9
    assert up(_mp4(9)).status_code == 200
    long = up(_mp4(95))
    assert long.status_code == 400 and "ثانیه" in long.json()["detail"]
    huge = up(_mp4(5) + b"\0" * (30 * 1024 * 1024))
    assert huge.status_code == 400 and "مگابایت" in huge.json()["detail"]
