"""
API پایه انبارداری: طرف‌های تجاری، اسناد و سند برگشت، تغییر وضعیت کیفی، رزروها، رویدادها، واژه‌نامه و انواع انبار
— با تأکید بر جداسازی سازمان‌ها و یکتایی درخواست.
"""
from datetime import timedelta

import pytest

from app.core.security import bcrypt_context, create_access_token
from app.core.tenancy import set_tenant
from app.models import Inventory, Organization, Product, RoleEnum, User, Vehicle, Warehouse
from tests.factories import order_payload

HASH = bcrypt_context.hash("secret123")


def _auth(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.username, user.id, timedelta(minutes=5))}"}


def _legal_id(prefix: str = "1032054") -> str:
    """شناسه ملی ۱۱ رقمی معتبر (با رقم کنترل)."""
    body = (prefix + "0" * 10)[:10]
    tens = int(body[9]) + 2
    weights = (29, 27, 23, 19, 17, 29, 27, 23, 19, 17)
    total = sum((int(body[i]) + tens) * weights[i] for i in range(10)) % 11
    return body + str(0 if total == 10 else total)


def _iban(bban: str = "0170000000123456789012") -> str:
    check = 98 - int(bban + "182700") % 97
    return f"IR{check:02d}{bban}"


@pytest.fixture()
def env(api_env):
    client, Session = api_env
    db = Session()
    out = {}
    for slug in ("a", "b"):
        org = Organization(name=f"سازمان {slug}", slug=f"wms-{slug}")
        db.add(org)
        db.commit()
        set_tenant(db, org.id)
        main = Warehouse(name="انبار اصلی", location="تهران", province="تهران", city="تهران", code="WH-01")
        db.add(main)
        db.commit()
        admin = User(username=f"{slug}_admin", email=f"{slug}a@x.io", role=RoleEnum.ORG_ADMIN, hashed_password=HASH)
        manager = User(username=f"{slug}_mgr", email=f"{slug}m@x.io", role=RoleEnum.WAREHOUSE_MANAGER, hashed_password=HASH,
                       warehouse_id=main.id)
        driver = User(username=f"{slug}_drv", email=f"{slug}d@x.io", role=RoleEnum.DRIVER, hashed_password=HASH, city="تهران")
        db.add_all([admin, manager, driver])
        db.commit()
        product = Product(name="برنج", sku="RICE", price=100, weight_kg=1)
        vehicle = Vehicle(license_plate=f"{slug}-1", type="van", capacity_kg=5000, status="available", driver_id=driver.id, city="تهران")
        db.add_all([product, vehicle])
        db.commit()
        db.add(Inventory(product_id=product.id, warehouse_id=main.id, quantity=30))
        db.commit()
        out[slug] = dict(admin=_auth(admin), manager=_auth(manager), driver=_auth(driver), warehouse=main.id,
                         product=product.id, vehicle=vehicle.id)
        set_tenant(db, None)
    db.close()
    return client, out


SUPPLIER = {"name": "پخش البرز", "kind": "legal", "is_supplier": True, "legal_name": "شرکت پخش البرز",
            "mobile": "09121234567", "province": "تهران", "city": "تهران", "postal_code": "1234567890",
            "payment_terms_days": 30, "lead_time_days": 5}


def test_vocabulary_is_shared_terminology(env):
    client, t = env
    data = client.get("/wms/vocabulary", headers=t["a"]["manager"]).json()
    assert [s["code"] for s in data["stock_statuses"]] == ["available", "quarantine", "blocked", "damaged"]
    assert {d["code"] for d in data["document_types"]} >= {"receipt", "transfer", "reversal", "status_change"}
    assert any(g["term"] == "SKU" for g in data["glossary"])


def test_partner_lifecycle_validation_and_masking(env):
    client, t = env
    a = t["a"]
    created = client.post("/partners/", headers=a["admin"], json={**SUPPLIER, "national_id": _legal_id(), "iban": _iban()})
    assert created.status_code == 201, created.text
    partner = created.json()
    assert partner["code"] == "SUP-001" and partner["roles"] == ["supplier"] and not partner["masked"]

    as_manager = client.get(f"/partners/{partner['id']}", headers=a["manager"]).json()
    assert as_manager["masked"] and as_manager["iban"].startswith("•") and as_manager["iban"][-4:] == partner["iban"][-4:]
    assert client.post("/partners/", headers=a["manager"], json=SUPPLIER).status_code == 403
    assert client.get("/partners/", headers=a["driver"]).status_code == 403

    # شناسه تکراری، شبا و شناسه ملی نامعتبر، بدون نقش
    assert client.post("/partners/", headers=a["admin"], json={**SUPPLIER, "national_id": _legal_id()}).status_code == 400
    assert client.post("/partners/", headers=a["admin"], json={**SUPPLIER, "iban": "IR000000000000000000000000"}).status_code == 422
    assert client.post("/partners/", headers=a["admin"], json={**SUPPLIER, "national_id": "12345678901"}).status_code == 422
    assert client.post("/partners/", headers=a["admin"], json={**SUPPLIER, "is_supplier": False}).status_code == 422
    carrier = client.post("/partners/", headers=a["admin"], json={
        "name": "باربری سریع", "is_carrier": True, "carrier_service": "road",
        "tracking_url": "https://track.example.ir/{code}"}).json()
    assert carrier["code"] == "CAR-001"

    # سازمان دیگر نه می‌بیند نه ارجاع می‌دهد
    assert client.get(f"/partners/{partner['id']}", headers=t["b"]["admin"]).status_code == 404
    assert client.get("/partners/", headers=t["b"]["admin"]).json() == []

    archived = client.post(f"/partners/{carrier['id']}/archive", headers=a["admin"]).json()
    assert archived["is_active"] is False
    assert all(p["id"] != carrier["id"] for p in client.get("/partners/", headers=a["admin"]).json())
    assert client.delete(f"/partners/{carrier['id']}", headers=a["admin"]).status_code == 204


def test_receipt_documents_reversal_and_idempotency(env):
    client, t = env
    a = t["a"]
    supplier = client.post("/partners/", headers=a["admin"], json=SUPPLIER).json()
    body = {"product_id": a["product"], "movement_type": "receipt", "quantity": 10, "partner_id": supplier["id"],
            "external_ref": "INV-1402-77"}
    headers = {**a["manager"], "Idempotency-Key": "rc-test-000001"}
    first = client.post("/inventory/movements", headers=headers, json=body)
    again = client.post("/inventory/movements", headers=headers, json=body)
    assert first.status_code == again.status_code == 201
    assert first.json()["id"] == again.json()["id"] and first.json()["document_code"].startswith("RC-")
    assert client.post("/inventory/movements", headers=headers, json={**body, "quantity": 11}).status_code == 409
    assert client.post("/inventory/movements", headers={**a["manager"], "Idempotency-Key": "bad key"}, json=body).status_code == 422

    docs = client.get("/inventory/documents", headers=a["manager"], params={"doc_type": "receipt"}).json()
    assert len(docs) == 1 and docs[0]["partner_name"] == "پخش البرز" and docs[0]["external_ref"] == "INV-1402-77"
    assert docs[0]["can_reverse"] and docs[0]["total_in"] == 10

    # تأمین‌کننده سازمان دیگر قابل ارجاع نیست
    assert client.post("/inventory/movements", headers=t["b"]["manager"], json={**body, "product_id": t["b"]["product"]}).status_code == 404

    reversal = client.post(f"/inventory/documents/{docs[0]['id']}/reverse", headers=a["manager"], json={"reason": "فاکتور اشتباه"})
    assert reversal.status_code == 201, reversal.text
    assert reversal.json()["reversal_of_code"] == docs[0]["code"]
    detail = client.get(f"/inventory/documents/{docs[0]['id']}", headers=a["manager"]).json()
    assert detail["status"] == "reversed" and detail["reversed_by_code"] == reversal.json()["code"] and not detail["can_reverse"]
    assert client.post(f"/inventory/documents/{docs[0]['id']}/reverse", headers=a["manager"], json={"reason": "دوباره"}).status_code == 400
    assert client.get("/inventory/ledger-check", headers=a["admin"]).json()["ok"] is True
    # سازمان دیگر سند را نمی‌بیند
    assert client.get(f"/inventory/documents/{docs[0]['id']}", headers=t["b"]["admin"]).status_code == 404


def test_status_change_buckets_and_reservations(env):
    client, t = env
    a = t["a"]
    change = client.post("/inventory/status-changes", headers=a["manager"], json={
        "product_id": a["product"], "from_status": "available", "to_status": "blocked", "quantity": 4, "reason": "توقیف برای بررسی"})
    assert change.status_code == 201, change.text
    buckets = {b["stock_status"]: b for b in client.get("/inventory/stock", headers=a["manager"]).json()}
    assert (buckets["available"]["quantity"], buckets["blocked"]["quantity"]) == (26, 4)

    payload = order_payload(a["product"], a["vehicle"], quantity=6)
    order = client.post("/orders/", headers={**a["admin"], "Idempotency-Key": "order-test-001"}, json=payload)
    assert order.status_code == 201, order.text
    # تکرار همان درخواست (مثلاً بعد از قطع شبکه) سفارش دوم نمی‌سازد
    repeat = client.post("/orders/", headers={**a["admin"], "Idempotency-Key": "order-test-001"}, json=payload)
    assert repeat.status_code == 201, repeat.text
    assert repeat.json()["id"] == order.json()["id"]
    [reservation] = client.get("/inventory/reservations", headers=a["manager"]).json()
    assert (reservation["quantity"], reservation["reference_label"]) == (6, order.json()["tracking_code"])
    product = next(p for p in client.get("/inventory/products", headers=a["admin"]).json() if p["id"] == a["product"])
    assert (product["stock"], product["reserved"], product["free_stock"], product["held_stock"]) == (26, 6, 20, {"blocked": 4})
    assert product["stock_by_warehouse"][0]["free"] == 20


def test_events_feed_is_admin_only_and_tenant_scoped(env):
    client, t = env
    client.post("/inventory/movements", headers=t["a"]["manager"],
                json={"product_id": t["a"]["product"], "movement_type": "receipt", "quantity": 2})
    events = client.get("/wms/events", headers=t["a"]["admin"]).json()
    assert any(e["event_type"] == "stock.document.posted" for e in events)
    assert client.get("/wms/events", headers=t["a"]["manager"]).status_code == 403
    last = events[-1]["id"]
    assert client.get("/wms/events", headers=t["a"]["admin"], params={"after_id": last}).json() == []
    b_events = client.get("/wms/events", headers=t["b"]["admin"]).json()
    assert all(e["payload"].get("doc_type") != "receipt" for e in b_events)


def test_warehouse_types_codes_and_hierarchy(env):
    client, t = env
    a = t["a"]
    base = {"province": "تهران", "city": "تهران"}
    site = client.post("/warehouses/", headers=a["admin"], json={**base, "name": "مجتمع غرب", "type": "site", "code": "site-w"})
    assert site.status_code == 201, site.text
    assert site.json()["code"] == "SITE-W"
    child = client.post("/warehouses/", headers=a["admin"], json={**base, "name": "قرنطینه غرب", "type": "quarantine",
                                                                  "parent_id": site.json()["id"]}).json()
    assert child["code"] == "WH-03" and child["parent_name"] == "مجتمع غرب" and child["ships_orders"] is False
    listed = client.get("/warehouses/", headers=a["manager"]).json()
    order = [w["name"] for w in listed]
    assert order.index("قرنطینه غرب") == order.index("مجتمع غرب") + 1
    assert next(w for w in listed if w["id"] == child["id"])["depth"] == 1
    assert client.post("/warehouses/", headers=a["admin"], json={**base, "name": "تکراری", "code": "WH-01"}).status_code == 400
    # انبار مادر از سازمان دیگر = یافت نشد
    assert client.post("/warehouses/", headers=t["b"]["admin"], json={**base, "name": "انبار بیگانه", "parent_id": site.json()["id"]}).status_code == 404
    # رسید مستقیم در سایت ممکن نیست
    receipt = client.post("/inventory/movements", headers=a["admin"], json={
        "product_id": a["product"], "warehouse_id": site.json()["id"], "movement_type": "receipt", "quantity": 1})
    assert receipt.status_code == 400
    # رسید در قرنطینه به‌طور پیش‌فرض با وضعیت قرنطینه
    held = client.post("/inventory/movements", headers=a["admin"], json={
        "product_id": a["product"], "warehouse_id": child["id"], "movement_type": "receipt", "quantity": 3}).json()
    assert held["stock_status"] == "quarantine"


def test_product_master_data_api(env):
    client, t = env
    a = t["a"]
    pid = a["product"]
    updated = client.put(f"/catalog/products/{pid}", headers=a["admin"], json={
        "short_name": "برنج", "net_weight_kg": 0.95, "length_cm": 30, "width_cm": 20, "height_cm": 8, "barcode": "6261234567890",
        "lot_tracked": True, "expiry_tracked": True, "shelf_life_days": 365, "min_stock": 5, "max_stock": 200, "reorder_point": 20})
    assert updated.status_code == 200, updated.text
    assert updated.json()["volume_m3"] == 0.0048
    assert client.put(f"/catalog/products/{pid}", headers=a["admin"], json={"sku": "RICE-2"}).status_code == 400
    uoms = client.put(f"/catalog/products/{pid}/uoms", headers=a["admin"], json=[{"name": "کیسه", "factor": 10}])
    assert uoms.json()["uoms"][0]["factor"] == 10
    assert client.put(f"/catalog/products/{pid}/uoms", headers=a["admin"], json=[{"name": "کیسه", "factor": 1}]).status_code == 422
    supplier = client.post("/partners/", headers=a["admin"], json=SUPPLIER).json()
    linked = client.put(f"/catalog/products/{pid}/suppliers", headers=a["admin"], json=[
        {"partner_id": supplier["id"], "supplier_sku": "ALB-77", "lead_time_days": 4, "is_preferred": True}]).json()
    assert linked["suppliers"][0]["partner_code"] == "SUP-001"
    # بارکد یکسان در سازمان دیگر مجاز است
    other = client.put(f"/catalog/products/{t['b']['product']}", headers=t["b"]["admin"], json={"barcode": "6261234567890"})
    assert other.status_code == 200
