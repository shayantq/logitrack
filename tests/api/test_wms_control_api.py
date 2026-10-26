"""
API کنترل و آمادگی راه‌اندازی (فصل ۱۶ تا ۳۵): انبارگردانی در سطح محل با قفل، مجوزها، شاخص‌ها، ارزش‌گذاری،
برچسب و اسکن، گردش‌کار، چک‌لیست راه‌اندازی، قالب یکسان خطا — با نقش‌ها و جداسازی سازمان‌ها.
"""
from tests.api.test_wms_api import env  # noqa: F401 -- fixture مشترک دو سازمان


def _bin(client, a, code):
    r = client.post(f"/warehouses/{a['warehouse']}/locations", headers=a["manager"],
                    json={"code": code, "level": "bin", "location_type": "storage"})
    assert r.status_code == 201, r.text
    return r.json()


def test_location_count_with_lock_over_http(env):  # noqa: F811
    client, t = env
    a = t["a"]
    shelf = _bin(client, a, "A-01")
    assert client.post("/inventory/location-moves", headers=a["manager"],
                       json={"product_id": a["product"], "to_location_id": shelf["id"], "quantity": 10}).status_code == 201
    st = client.post("/stocktakes/", headers=a["manager"], json={
        "warehouse_id": a["warehouse"], "scope": "partial", "product_ids": [a["product"]], "by_location": True,
        "freeze_mode": "lock", "location_ids": [shelf["id"]]})
    assert st.status_code == 201, st.text
    st = st.json()
    assert st["freeze_mode"] == "lock" and st["locked_locations"] == 1
    blocked = client.post("/inventory/location-moves", headers=a["manager"],
                          json={"product_id": a["product"], "to_location_id": shelf["id"], "quantity": 1})
    assert blocked.status_code == 400 and "قفل" in blocked.json()["detail"]
    body = blocked.json()
    assert body["code"] == "business_rule" and body["request_id"] == blocked.headers["x-request-id"]
    line = st["lines"][0]
    client.put(f"/stocktakes/{st['id']}/lines/{line['id']}", headers=a["manager"], json={"counted_qty": 9})
    client.post(f"/stocktakes/{st['id']}/submit", headers=a["manager"])
    assert client.post(f"/stocktakes/{st['id']}/approve", headers=a["manager"], json={}).status_code == 403
    done = client.post(f"/stocktakes/{st['id']}/approve", headers=a["admin"], json={"reasons": {str(line["id"]): "loss"},
                                                                                   "note": "تأیید پس از شمارش دوم"})
    assert done.status_code == 200 and done.json()["lines"][0]["adjustment"] == -1, done.text
    assert client.get("/inventory/ledger-check", headers=a["admin"]).json()["ok"] is True
    cycle = client.get(f"/stocktakes/warehouses/{a['warehouse']}/cycle", headers=a["manager"])
    assert cycle.status_code == 200 and cycle.json()[0]["due"] is False


def test_permissions_matrix_and_me(env):  # noqa: F811
    client, t = env
    a = t["a"]
    me = client.get("/users/me", headers=a["manager"]).json()
    assert "stock.adjust" in me["permissions"] and "audit.view" not in me["permissions"]
    assert client.get("/permissions/", headers=a["manager"]).status_code == 403
    assert client.get("/users/activity-log", headers=a["manager"]).status_code == 403
    r = client.put("/permissions/warehouse_manager/audit.view", headers=a["admin"], json={"allowed": True, "reason": "سرپرست شیفت"})
    assert r.status_code == 200, r.text
    assert client.get("/users/activity-log", headers=a["manager"], params={"category": "security"}).json()["total"] == 1
    # سازمان دیگر تغییر نکرده است
    assert "audit.view" not in client.get("/users/me", headers=t["b"]["manager"]).json()["permissions"]
    r = client.put("/permissions/warehouse_manager/stock.adjust", headers=a["admin"], json={"allowed": False, "reason": "فقط ادمین"})
    assert r.status_code == 200
    adjust = client.post("/inventory/movements", headers=a["manager"],
                         json={"product_id": a["product"], "movement_type": "adjustment", "quantity": -1, "reason": "شکستگی"})
    assert adjust.status_code == 403, adjust.text
    ok = client.post("/inventory/movements", headers=a["admin"],
                     json={"product_id": a["product"], "warehouse_id": a["warehouse"], "movement_type": "adjustment",
                           "quantity": -1, "reason": "شکستگی هنگام تخلیه"})
    assert ok.status_code == 201, ok.text
    log = client.get("/users/activity-log", headers=a["admin"], params={"action": "stock.adjust"}).json()["items"][0]
    assert log["reason"] == "شکستگی هنگام تخلیه"


def test_analytics_valuation_labels_scan_and_readiness(env):  # noqa: F811
    client, t = env
    a = t["a"]
    shelf = _bin(client, a, "A-01")
    kpis = client.get("/analytics/kpis", headers=a["manager"])
    assert kpis.status_code == 200 and len(kpis.json()["kpis"]) == 9
    assert client.get("/valuation/", headers=a["manager"]).status_code == 403
    val = client.get("/valuation/", headers=a["admin"]).json()
    assert val["totals"]["weighted_average"] == 3000 and val["items"][0]["quantity"] == 30
    assert client.get("/valuation/health", headers=a["admin"]).status_code == 200
    settings = client.put("/valuation/settings", headers=a["admin"], json={"slow_days": 30, "dead_days": 90})
    assert settings.status_code == 200 and settings.json()["dead_days"] == 90

    pdf = client.post("/labels/print", headers=a["manager"], json={"label_type": "location", "ids": [shelf["id"]]})
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content[:4] == b"%PDF"
    again = client.post("/labels/print", headers=a["manager"], json={"label_type": "location", "ids": [shelf["id"]], "reason": "پاره"})
    assert again.status_code == 403
    assert client.get("/labels/history", headers=a["manager"]).json()[0]["target_code"] == shelf["barcode"]
    scanned = client.get("/scan/resolve", headers=a["manager"], params={"code": "rice"}).json()
    assert scanned["kind"] == "product" and scanned["path"].startswith("/app/stock-card")
    assert client.get("/scan/resolve", headers=t["b"]["manager"], params={"code": shelf["barcode"]}).status_code == 404

    flows = client.get("/workflows/", headers=a["manager"]).json()
    assert {f["code"] for f in flows} >= {"order", "stocktake", "transfer"} and "from" in flows[0]["transitions"][0]

    ready = client.get("/readiness/", headers=a["admin"])
    assert ready.status_code == 200 and ready.json()["total"] > 10
    assert client.get("/readiness/", headers=a["manager"]).status_code == 403
    tpl = client.get("/readiness/import/locations/template", headers=a["admin"])
    assert tpl.status_code == 200 and tpl.content[:2] == b"PK"
    preview = client.post("/readiness/import/locations", headers=a["admin"], data={"dry_run": "true"},
                          files={"file": ("loc.xlsx", tpl.content, "application/octet-stream")})
    assert preview.status_code == 200 and preview.json()["applied"] is False, preview.text


def test_validation_errors_use_the_same_envelope(env):  # noqa: F811
    client, t = env
    r = client.post("/stocktakes/", headers=t["a"]["manager"], json={"warehouse_id": 0})
    assert r.status_code == 422 and r.json()["code"] == "validation" and isinstance(r.json()["detail"], list)
    r = client.get("/stocktakes/999999", headers=t["a"]["manager"])
    assert r.status_code == 404 and r.json()["code"] == "not_found"
