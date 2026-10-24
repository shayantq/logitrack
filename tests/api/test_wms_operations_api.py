"""
API عملیات انبار (فصل ۶ تا ۱۰): محل‌ها، رسید دریافت، بازرسی، جانمایی با اسکن، موجودی چندبعدی و کاردکس
— از ورود کالا تا قفسه، با تأکید بر نقش‌ها، جداسازی سازمان‌ها و یکتایی درخواست.
"""
from tests.api.test_wms_api import env  # noqa: F401 -- fixture مشترک دو سازمان


def _locations(client, t):
    a = t["a"]
    created = {}
    for code, kind in (("RCV", "receiving"), ("A-01", "storage"), ("Q-01", "quarantine")):
        r = client.post(f"/warehouses/{a['warehouse']}/locations", headers=a["manager"],
                        json={"code": code, "level": "bin", "location_type": kind})
        assert r.status_code == 201, r.text
        created[code] = r.json()
    return created


def _supplier(client, t):
    r = client.post("/partners/", headers=t["a"]["admin"], json={"name": "تأمین برنج", "is_supplier": True})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_inbound_to_shelf_flow_over_http(env):  # noqa: F811
    client, t = env
    a = t["a"]
    locs = _locations(client, t)
    assert locs["A-01"]["barcode"] == "WH-01-A-01" and locs["A-01"]["allocatable"]
    supplier = _supplier(client, t)
    body = {"receipt_type": "purchase", "warehouse_id": a["warehouse"], "partner_id": supplier, "external_ref": "BL-9",
            "lines": [{"product_id": a["product"], "expected_quantity": 12}]}
    receipt = client.post("/inbound/receipts", headers={**a["admin"], "Idempotency-Key": "ir-api-0001"}, json=body)
    assert receipt.status_code == 201, receipt.text
    again = client.post("/inbound/receipts", headers={**a["admin"], "Idempotency-Key": "ir-api-0001"}, json=body)
    assert again.json()["id"] == receipt.json()["id"]
    duplicate = client.post("/inbound/receipts", headers=a["admin"], json=body)
    assert duplicate.status_code == 400 and "BL-9" in duplicate.json()["detail"]

    rid, line = receipt.json()["id"], receipt.json()["lines"][0]["id"]
    received = client.post(f"/inbound/receipts/{rid}/receive", headers=a["manager"],
                           json={"lines": [{"line_id": line, "quantity": 10}]})
    assert received.status_code == 201, received.text
    data = received.json()
    assert (data["status"], data["total_received"], data["total_outstanding"]) == ("receiving", 10, 2)

    [task] = client.get("/putaway/tasks", headers=a["manager"], params={"status": "active"}).json()
    assert (task["source_location_code"], task["suggested_location_code"], task["remaining"]) == ("RCV", "A-01", 10)
    wrong = client.post(f"/putaway/tasks/{task['id']}/execute", headers=a["manager"], json={
        "product_scan": "RICE", "source_scan": "RCV", "destination_scan": "Q-01", "quantity": 10})
    assert wrong.status_code == 422
    done = client.post(f"/putaway/tasks/{task['id']}/execute", headers=a["manager"], json={
        "product_scan": "rice", "source_scan": "WH-01-RCV", "destination_scan": "A-01", "quantity": 10})
    assert done.status_code == 200, done.text
    assert (done.json()["status"], done.json()["failure_count"]) == ("done", 1)

    closed = client.post(f"/inbound/receipts/{rid}/close", headers=a["admin"], json={"note": "کسری بارنامه"})
    assert closed.json()["lines"][0]["discrepancy_type"] == "shortage"

    [position] = client.get("/inventory/positions", headers=a["manager"], params={"product_id": a["product"]}).json()
    assert (position["on_hand"], position["allocatable"], position["not_put_away"]) == (40, 40, 0)
    location = client.get(f"/warehouses/{a['warehouse']}/locations/lookup", headers=a["manager"],
                          params={"code": "wh-01-a-01"}).json()
    assert location["contents"][0]["quantity"] == 10
    card = client.get("/inventory/stock-card", headers=a["manager"], params={"product_id": a["product"]}).json()
    assert [(r["doc_type"], r["balance"]) for r in card["rows"]] == [("opening", 30), ("inbound_receipt", 40)]
    balances = client.get("/inventory/balances", headers=a["manager"], params={"location_id": locs["A-01"]["id"]}).json()
    assert balances[0]["quantity"] == 10 and balances[0]["allocatable"]
    assert client.get("/inventory/ledger-check", headers=a["admin"]).json()["ok"] is True


def test_quality_inspection_permissions_over_http(env):  # noqa: F811
    client, t = env
    a = t["a"]
    _locations(client, t)
    product = client.put(f"/catalog/products/{a['product']}", headers=a["admin"], json={"inspection_required": True})
    assert product.status_code == 200, product.text
    receipt = client.post("/inbound/receipts", headers=a["admin"], json={
        "receipt_type": "purchase", "warehouse_id": a["warehouse"], "partner_id": _supplier(client, t),
        "lines": [{"product_id": a["product"], "expected_quantity": 5}]}).json()
    client.post(f"/inbound/receipts/{receipt['id']}/receive", headers=a["manager"],
                json={"lines": [{"line_id": receipt["lines"][0]["id"], "quantity": 5}]})
    missing_reason = client.post("/quality/inspections", headers=a["manager"], json={
        "product_id": a["product"], "results": [{"status": "rejected", "quantity": 1}]})
    assert missing_reason.status_code == 422
    inspected = client.post("/quality/inspections", headers=a["manager"], json={
        "product_id": a["product"], "receipt_id": receipt["id"],
        "results": [{"status": "available", "quantity": 4}, {"status": "blocked", "quantity": 1, "reason": "نیاز به نظر ادمین"}]})
    assert inspected.status_code == 201, inspected.text
    release = {"product_id": a["product"], "from_status": "blocked", "results": [{"status": "available", "quantity": 1}]}
    assert client.post("/quality/inspections", headers=a["manager"], json=release).status_code == 403
    assert client.post("/quality/inspections", headers=a["admin"], json=release).status_code == 201
    transitions = client.get("/quality/transitions", headers=a["manager"]).json()
    assert {"from": "blocked", "to": "available", "allowed": False} in transitions
    assert len(client.get("/quality/inspections", headers=a["manager"]).json()) == 2


def test_operations_are_tenant_and_warehouse_scoped(env):  # noqa: F811
    client, t = env
    a, b = t["a"], t["b"]
    locs = _locations(client, t)
    assert client.get(f"/locations/{locs['A-01']['id']}", headers=b["admin"]).status_code == 404
    assert client.get(f"/warehouses/{a['warehouse']}/locations", headers=b["manager"]).status_code == 403
    assert client.get("/putaway/tasks", headers=a["driver"]).status_code == 403
    receipt = client.post("/inbound/receipts", headers=a["admin"], json={
        "receipt_type": "unexpected", "warehouse_id": a["warehouse"]}).json()
    assert client.get(f"/inbound/receipts/{receipt['id']}", headers=b["admin"]).status_code == 404
    got = client.post(f"/inbound/receipts/{receipt['id']}/receive", headers=a["manager"], json={
        "lines": [{"product_id": a["product"], "quantity": 2}]})
    assert got.status_code == 201 and got.json()["lines"][0]["expected_quantity"] == 0
    move = client.post("/inventory/location-moves", headers=a["manager"], json={
        "product_id": a["product"], "to_location_id": locs["A-01"]["id"], "quantity": 5})
    assert move.status_code == 201 and move.json()["code"].startswith("MV-")
