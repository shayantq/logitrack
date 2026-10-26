"""
API اجرای سفارش (فصل ۱۱ تا ۱۵): سفارش معوق، پیکینگ ← بسته‌بندی ← محموله ← تحویل به راننده، سفارش انتقال،
تأمین مجدد و ABC، تعیین تکلیف — با نقش‌ها و جداسازی سازمان‌ها.
"""
from datetime import datetime, timedelta, timezone

from tests.api.test_wms_api import env  # noqa: F401 -- fixture مشترک دو سازمان
from tests.factories import order_payload


def _bin(client, a, code, kind="storage"):
    r = client.post(f"/warehouses/{a['warehouse']}/locations", headers=a["manager"],
                    json={"code": code, "level": "bin", "location_type": kind})
    assert r.status_code == 201, r.text
    return r.json()


def test_order_to_driver_flow_over_http(env):  # noqa: F811
    client, t = env
    a = t["a"]
    shelf, staging = _bin(client, a, "A-01"), _bin(client, a, "STG", "staging")
    move = client.post("/inventory/location-moves", headers=a["manager"],
                       json={"product_id": a["product"], "to_location_id": shelf["id"], "quantity": 30})
    assert move.status_code == 201, move.text
    order = client.post("/orders/", headers=a["admin"], json=order_payload(a["product"], a["vehicle"], quantity=34,
                                                                         allow_backorder=True))
    assert order.status_code == 201, order.text
    order = order.json()
    assert (order["items"][0]["quantity"], order["fulfillment_state"]) == (30, "open")
    [backorder] = client.get("/backorders/", headers=a["manager"], params={"order_id": order["id"]}).json()
    assert (backorder["quantity"], backorder["status"]) == (4, "open")

    assert [c["id"] for c in client.get("/picking/candidates", headers=a["manager"]).json()] == [order["id"]]
    pick = client.post("/picking/lists", headers=a["manager"], json={
        "strategy": "single", "order_ids": [order["id"]], "staging_location_id": staging["id"]})
    assert pick.status_code == 201, pick.text
    [line] = pick.json()["lines"]
    bad = client.post(f"/picking/lines/{line['id']}/pick", headers=a["manager"],
                      json={"source_scan": "STG", "product_scan": "RICE", "quantity": 30})
    assert bad.status_code == 422
    done = client.post(f"/picking/lines/{line['id']}/pick", headers={**a["manager"], "Idempotency-Key": "pick-line-0001"},
                       json={"source_scan": shelf["barcode"], "product_scan": "rice", "quantity": 30})
    assert done.status_code == 200 and done.json()["status"] == "picked", done.text

    pack = client.post(f"/shipping/orders/{order['id']}/pack", headers=a["manager"], json={"packages": [
        {"length_cm": 60, "width_cm": 40, "height_cm": 40, "items": [{"product_id": a["product"], "quantity": 30}]}]})
    assert pack.status_code == 200, pack.text
    assert pack.json()["total_weight_kg"] == 30
    slip = client.get(f"/shipping/orders/{order['id']}/packing-slip", headers=a["manager"]).json()
    assert slip["packages"][0]["items"][0]["quantity"] == 30
    shipment = client.post("/shipping/shipments", headers=a["manager"], json={"vehicle_id": a["vehicle"], "order_ids": [order["id"]]})
    assert shipment.status_code == 201, shipment.text
    dispatched = client.post(f"/shipping/shipments/{shipment.json()['id']}/dispatch", headers=a["manager"], json={})
    assert dispatched.status_code == 200 and dispatched.json()["status"] == "dispatched", dispatched.text
    shipped = client.get(f"/orders/{order['id']}", headers=a["admin"]).json()
    assert (shipped["status"], shipped["fulfillment_state"]) == ("picked_up", "shipped")
    assert client.get("/inventory/ledger-check", headers=a["admin"]).json()["ok"] is True

    # موجودی تازه ← تخصیص به معوق ← سفارش تکمیلی
    client.post("/inventory/movements", headers=a["manager"],
                json={"product_id": a["product"], "movement_type": "receipt", "quantity": 4})
    assert client.post("/backorders/allocate", headers=a["manager"], json={}).json()["allocated_quantity"] == 4
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    follow = client.post(f"/backorders/orders/{order['id']}/fulfill", headers=a["admin"], json={
        "delivery_window_start": start.isoformat(), "delivery_window_end": (start + timedelta(hours=4)).isoformat()})
    assert follow.status_code == 201, follow.text
    assert (follow.json()["parent_order_id"], follow.json()["total_quantity"]) == (order["id"], 4)


def test_transfer_replenishment_abc_and_dispositions_over_http(env):  # noqa: F811
    client, t = env
    a = t["a"]
    pick_face, shelf = _bin(client, a, "P-01", "picking"), _bin(client, a, "A-02")
    client.post("/inventory/location-moves", headers=a["manager"],
                json={"product_id": a["product"], "to_location_id": shelf["id"], "quantity": 20})
    rule = client.post("/replenishment-rules/", headers=a["manager"], json={
        "location_id": pick_face["id"], "product_id": a["product"], "min_quantity": 1, "max_quantity": 6})
    assert rule.status_code == 201 and rule.json()["needs_replenishment"], rule.text
    assert client.post("/replenishment-rules/generate", headers=a["manager"]).json()["quantity"] == 6
    tasks = client.get("/putaway/tasks", headers=a["manager"], params={"task_type": "replenishment"}).json()
    assert tasks[0]["task_type"] == "replenishment" and tasks[0]["suggested_location_code"] == "P-01"
    assert client.post("/replenishment-rules/abc", headers=a["manager"], json={}).status_code == 403
    assert client.post("/replenishment-rules/abc", headers=a["admin"], json={"days": 90}).status_code == 200
    assert client.get("/replenishment-rules/abc", headers=a["manager"]).json()[0]["count_every_days"] in (30, 90, 180)

    transfer = client.post("/transfer-orders/", headers=a["manager"], json={
        "from_warehouse_id": a["warehouse"], "to_warehouse_id": a["warehouse"], "from_location_id": shelf["id"],
        "to_location_id": pick_face["id"], "lines": [{"product_id": a["product"], "quantity": 2}]})
    assert transfer.status_code == 201, transfer.text
    tid = transfer.json()["id"]
    assert client.post(f"/transfer-orders/{tid}/ship", headers=a["manager"]).json()["status"] == "in_transit"
    line = client.get(f"/transfer-orders/{tid}", headers=a["manager"]).json()["lines"][0]
    received = client.post(f"/transfer-orders/{tid}/receive", headers=a["manager"], json={
        "lines": [{"line_id": line["id"], "received_quantity": 1, "damaged_quantity": 1, "reason": "شکست"}]})
    assert received.json()["status"] == "received", received.text
    assert client.get(f"/transfer-orders/{tid}", headers=t["b"]["admin"]).status_code == 404

    disposed = client.post("/dispositions/", headers=a["manager"], json={
        "product_id": a["product"], "from_status": "damaged", "action": "scrap", "quantity": 1, "reason": "قابل استفاده نیست"})
    assert disposed.status_code == 201 and disposed.json()["document_code"].startswith("SC-"), disposed.text
    assert len(client.get("/dispositions/", headers=a["manager"]).json()) == 1
    assert client.get("/dispositions/", headers=t["b"]["admin"]).json() == []
    assert client.get("/picking/lists", headers=a["driver"]).status_code == 403
