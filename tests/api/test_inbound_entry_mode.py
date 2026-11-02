"""
روش ورود کالا (WH-IN-12، ت۱۹): اسکن با کد درست یا ورود دستی با کد دلیل. سرور بارکد و کد را می‌سنجد و ادعای بارکدخوان فیزیکی ندارد.
"""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.core.security import create_access_token
from app.core.tenancy import set_tenant
from app.models import AuditLog, Organization, Partner, Product, RoleEnum, StockMovement, User
from app.models_operations import InboundEntry
from tests.factories import default_warehouse


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.username, user.id, timedelta(minutes=5))}"}


@pytest.fixture()
def env(api_env):
    client, Session = api_env
    db = Session()
    org = Organization(name="آلفا", slug="alpha")
    db.add(org)
    db.commit()
    set_tenant(db, org.id)
    warehouse = default_warehouse(db, org.id)
    admin = User(username="adm", email="a@x.io", role=RoleEnum.ORG_ADMIN, hashed_password="x")
    product = Product(name="برنج", sku="RICE-1", barcode="62600001", price=1000, weight_kg=1)
    partner = Partner(code="SUP-1", name="تأمین", is_supplier=True)
    db.add_all([admin, product, partner])
    db.commit()
    res = client.post("/inbound/receipts", headers=_auth(admin), json={
        "receipt_type": "purchase", "warehouse_id": warehouse.id, "partner_id": partner.id, "external_ref": "BL-1",
        "lines": [{"product_id": product.id, "expected_quantity": 20}]})
    assert res.status_code == 201, res.text
    yield SimpleNamespace(client=client, db=db, org=org, warehouse=warehouse, admin=admin, product=product, receipt=res.json())
    db.close()


def _receive(env, **line):
    body = {"lines": [{"line_id": env.receipt["lines"][0]["id"], "quantity": 2, **line}]}
    return env.client.post(f"/inbound/receipts/{env.receipt['id']}/receive", headers=_auth(env.admin), json=body)


def _movement(env, **extra):
    return env.client.post("/inventory/movements", headers=_auth(env.admin), json={
        "product_id": env.product.id, "warehouse_id": env.warehouse.id, "movement_type": "receipt", "quantity": 1, **extra})


def test_receiving_without_a_mode_is_rejected(env):
    assert _receive(env).status_code == 422
    assert env.db.query(StockMovement).filter(StockMovement.movement_type == "receipt").count() == 0


@pytest.mark.parametrize("line", [
    {"entry_mode": "manual"}, {"entry_mode": "manual", "manual_reason": "because"}, {"entry_mode": "manual", "manual_reason": "other"},
    {"entry_mode": "manual", "manual_reason": "other", "manual_note": "  "}, {"entry_mode": "scan"},
    {"entry_mode": "scan", "product_scan": "RICE-1", "manual_reason": "no_barcode"},
])
def test_invalid_entries_are_rejected(env, line):
    assert _receive(env, **line).status_code == 422
    assert env.db.query(InboundEntry).count() == 0


def test_wrong_barcode_is_rejected_and_adds_no_stock(env):
    assert _receive(env, entry_mode="scan", product_scan="WRONG").status_code == 400
    assert env.db.query(StockMovement).filter(StockMovement.movement_type == "receipt").count() == 0


@pytest.mark.parametrize("code", ["62600001", "RICE-1"])
def test_scan_needs_no_reason_and_is_recorded(env, code):
    res = _receive(env, entry_mode="scan", product_scan=code)
    assert res.status_code == 201, res.text
    entry = env.db.query(InboundEntry).one()
    assert (entry.entry_mode, entry.reason_code, entry.scanned_code) == ("scan", None, code)
    assert env.db.query(AuditLog).filter(AuditLog.action == "inbound.manual_entry").count() == 0


@pytest.mark.parametrize("code,note", [("no_barcode", None), ("label_damaged", None), ("scanner_down", None), ("other", "بسته باز بود")])
def test_manual_entry_keeps_reason_user_and_history(env, code, note):
    res = _receive(env, entry_mode="manual", manual_reason=code, manual_note=note)
    assert res.status_code == 201, res.text
    env.db.expire_all()
    entry = env.db.query(InboundEntry).one()
    assert (entry.entry_mode, entry.reason_code, entry.note, entry.created_by_id, entry.quantity) == ("manual", code, note, env.admin.id, 2)
    assert entry.created_at is not None and entry.movement_id is not None and entry.receipt_id == env.receipt["id"]
    assert env.db.query(AuditLog).filter(AuditLog.action == "inbound.manual_entry").count() == 1
    listed = env.client.get(f"/inbound/receipts/{env.receipt['id']}", headers=_auth(env.admin)).json()["entries"][0]
    assert listed["entry_mode"] == "manual" and listed["reason_code"] == code and listed["created_by_name"] == "adm"


def test_direct_stock_receipt_needs_a_reason(env):
    assert _movement(env).status_code == 422
    assert _movement(env, manual_reason="nope").status_code == 422
    assert _movement(env, manual_reason="other").status_code == 422
    res = _movement(env, manual_reason="scanner_down")
    assert res.status_code == 201, res.text
    env.db.expire_all()
    entry = env.db.query(InboundEntry).one()
    assert entry.reason_code == "scanner_down" and entry.receipt_id is None and entry.movement_id == res.json()["id"]


def test_outgoing_movements_do_not_need_an_entry_reason(env):
    assert _movement(env, manual_reason="no_barcode").status_code == 201
    res = env.client.post("/inventory/movements", headers=_auth(env.admin), json={
        "product_id": env.product.id, "warehouse_id": env.warehouse.id, "movement_type": "damage", "quantity": 1, "reason": "شکستگی"})
    assert res.status_code == 201, res.text
    assert env.db.query(InboundEntry).count() == 1
