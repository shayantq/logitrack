"""
کنترل و آمادگی راه‌اندازی (WMS فصل ۱۶ تا ۳۵):
  • انبارگردانی در سطح محل با قفل، دوره‌ای ABC، سقف تأیید و تفکیک وظایف
  • ارزش‌گذاری FIFO / میانگین موزون و کالای راکد • شاخص‌های عملکرد
  • مجوزهای ریز نقش‌ها و گزارش فعالیت با دلیل • برچسب و چاپ مجدد، اسکن
  • گردش‌کار اسناد، مسیر مارپیچ و پیشنهاد جانمایی ABC • ورود داده و چک‌لیست راه‌اندازی
"""
import io
from datetime import datetime, timedelta, timezone

import pytest
from openpyxl import Workbook

from app.core import workflows as wf
from app.core.wms import PICK_LIST_STATUSES, PUTAWAY_STATUSES, RECEIPT_STATUSES, TRANSFER_STATUSES
from app.models import ORDER_STATUSES, AuditLog, LabelPrint, Location, Product, StockBalance, StockMovement
from app.schemas.product import LocationMoveCreate
from app.services import (
    analytics_service, audit_service, control_settings, label_service, location_service, migration_io, permission_service,
    readiness_service, scan_service, stock_ledger, stocktake_service, valuation_service,
)
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.services.inventory_service import move_between_locations
from app.tasks import build_report_file
from tests.wms_helpers import build_site, make_location


@pytest.fixture()
def site(db_session):
    return build_site(db_session)


def _to_bin(s, location, quantity):
    move_between_locations(s["db"], s["admin"], LocationMoveCreate(
        product_id=s["product"].id, warehouse_id=s["main"].id, to_location_id=location["id"], quantity=quantity))


def _bin_qty(db, location_id):
    db.flush()
    return sum(b.quantity for b in db.query(StockBalance).filter(StockBalance.location_id == location_id).all())


def _location_count(s, *, user=None, counted=8, lock=True, counter=None):
    db, a1 = s["db"], s["loc"]["a1"]
    st = stocktake_service.create(db, user or s["manager"], warehouse_id=s["main"].id, scope="partial",
                                  product_ids=[s["product"].id], title=None, note=None, by_location=True,
                                  freeze_mode="lock" if lock else "snapshot", location_ids=[a1["id"]])
    [line] = st["lines"]
    stocktake_service.count(db, counter or s["manager"], st["id"], line["id"], counted)
    stocktake_service.submit(db, counter or s["manager"], st["id"])
    return st


# ---------------------------------------------------------------------------
# فصل ۱۶ — انبارگردانی
# ---------------------------------------------------------------------------
def test_location_count_locks_bins_and_adjusts_exact_location(site):
    db, a1, a2 = site["db"], site["loc"]["a1"], site["loc"]["a2"]
    _to_bin(site, a1, 10)
    st = stocktake_service.create(db, site["manager"], warehouse_id=site["main"].id, scope="partial",
                                  product_ids=[site["product"].id], title=None, note=None, by_location=True,
                                  freeze_mode="lock", location_ids=[a1["id"]])
    assert [(l["location_code"], l["system_qty"]) for l in st["lines"]] == [("A-01", None)]     # کور
    assert db.get(Location, a1["id"]).count_lock_id == st["id"]
    with pytest.raises(ConflictError, match="قفل"):
        _to_bin(site, a1, 2)                                   # محل قفل: ورود ممنوع
    _to_bin(site, a2, 3)                                       # محل دیگر آزاد است
    [line] = st["lines"]
    stocktake_service.count(db, site["manager"], st["id"], line["id"], 8)
    stocktake_service.submit(db, site["manager"], st["id"])
    with pytest.raises(ForbiddenError):
        stocktake_service.approve(db, site["manager"], st["id"], {})        # پیش‌فرض: تأیید با ادمین
    done = stocktake_service.approve(db, site["admin"], st["id"], {line["id"]: "loss"}, "شمارش دوم تأیید شد")
    assert done["status"] == "approved" and done["lines"][0]["adjustment"] == -2
    assert _bin_qty(db, a1["id"]) == 8 and _bin_qty(db, a2["id"]) == 3
    assert db.get(Location, a1["id"]).count_lock_id is None
    assert stock_ledger.find_mismatches(db) == []
    entry = db.query(AuditLog).filter(AuditLog.action == "stocktake.approve").one()
    assert entry.reason == "شمارش دوم تأیید شد" and entry.details["adjusted_lines"] == 1


def test_guided_count_shows_live_system_quantity(site):
    db = site["db"]
    _to_bin(site, site["loc"]["a1"], 6)
    st = stocktake_service.create(db, site["admin"], warehouse_id=site["main"].id, scope="partial", product_ids=[site["product"].id],
                                  title=None, note=None, blind=False, by_location=True)
    codes = {l["location_code"]: l["system_qty"] for l in st["lines"]}
    assert codes == {"A-01": 6, None: 14}


def test_approval_threshold_and_segregation_of_duties(site):
    db, admin, manager = site["db"], site["admin"], site["manager"]
    _to_bin(site, site["loc"]["a1"], 10)
    permission_service.update(db, admin, "warehouse_manager", "stocktake.approve_minor", True, "مدیر انبار مغایرت کوچک را تأیید کند")
    control_settings.update(db, admin, {"count_approval_value": 1000})
    # مغایرت کوچک (۱ × ۱۰۰ ریال) ولی خودش شمرده ← تفکیک وظایف
    st = _location_count(site, counted=9)
    with pytest.raises(ForbiddenError, match="تفکیک وظایف"):
        stocktake_service.approve(db, manager, st["id"], {})
    stocktake_service.cancel(db, admin, st["id"], "شمارش دوباره با نفر دیگر")
    # شمارنده ادمین، تأییدکننده مدیر انبار: زیر سقف مجاز است
    st = _location_count(site, user=admin, counted=9, counter=admin)
    assert stocktake_service.detail(db, manager, st["id"])["can_approve"] is True
    assert stocktake_service.approve(db, manager, st["id"], {})["status"] == "approved"
    # بالای سقف (۲۰ × ۱۰۰ ریال) فقط با مجوز کامل
    st = _location_count(site, user=admin, counted=29, counter=admin)
    detail = stocktake_service.detail(db, manager, st["id"])
    assert detail["needs_full_approval"] is True and detail["can_approve"] is False
    with pytest.raises(ForbiddenError, match="سقف"):
        stocktake_service.approve(db, manager, st["id"], {})
    assert stocktake_service.approve(db, admin, st["id"], {})["lines"][0]["adjustment"] == 20


def test_cycle_count_selects_due_abc_products(site):
    db, product = site["db"], site["product"]
    product.abc_class = "A"
    db.commit()
    [row] = stocktake_service.cycle_candidates(db, site["admin"], site["main"].id)
    assert row["due"] is True and row["interval_days"] == 30
    st = stocktake_service.create(db, site["admin"], warehouse_id=site["main"].id, scope="partial", product_ids=None,
                                  title=None, note=None, count_type="cycle", abc_classes=["A"])
    assert st["count_type"] == "cycle" and [l["product_id"] for l in st["lines"]] == [product.id]
    stocktake_service.count(db, site["admin"], st["id"], st["lines"][0]["id"], 20)
    stocktake_service.submit(db, site["admin"], st["id"])
    stocktake_service.approve(db, site["admin"], st["id"], {})
    [row] = stocktake_service.cycle_candidates(db, site["admin"], site["main"].id)
    assert row["due"] is False and row["last_counted_at"] is not None
    with pytest.raises(ConflictError, match="سررسید"):
        stocktake_service.create(db, site["admin"], warehouse_id=site["main"].id, scope="partial", product_ids=None,
                                 title=None, note=None, count_type="cycle")


def test_lock_requires_location_level_count(site):
    with pytest.raises(ConflictError, match="سطح محل"):
        stocktake_service.create(site["db"], site["admin"], warehouse_id=site["main"].id, scope="full", product_ids=None,
                                 title=None, note=None, freeze_mode="lock")


# ---------------------------------------------------------------------------
# فصل ۱۷ — ارزش‌گذاری و سلامت موجودی
# ---------------------------------------------------------------------------
def test_fifo_and_weighted_average_differ_on_rising_costs():
    t = [datetime(2026, 1, d) for d in (1, 2, 3)]
    events = [(t[0], "receipt", 10), (t[1], "receipt", 10), (t[2], "order_out", -15)]
    result = valuation_service._run(events, lambda at: 100.0 if at == t[0] else 200.0)
    assert result["qty"] == 5 and result["fifo"] == 1000          # ۵ عدد از لایه ۲۰۰ ریالی
    assert result["weighted_average"] == pytest.approx(750)        # میانگین ۱۵۰
    assert result["cogs"] == {"fifo": 2000, "weighted_average": pytest.approx(2250)} and result["issued_qty"] == 15


def test_valuation_report_and_method_change_needs_reason(site):
    db, admin = site["db"], site["admin"]
    data = valuation_service.valuation(db, admin)
    [row] = data["items"]
    assert row["quantity"] == 20 and row["value"]["weighted_average"] == 2000 and row["estimated"] is True
    assert data["method"] == "weighted_average"
    with pytest.raises(ForbiddenError):
        valuation_service.valuation(db, site["manager"])          # پیش‌فرض: فقط ادمین
    with pytest.raises(ConflictError, match="دلیل"):
        control_settings.update(db, admin, {"valuation_method": "fifo"})
    assert control_settings.update(db, admin, {"valuation_method": "fifo"}, "هماهنگی با حسابداری")["valuation_method"] == "fifo"
    assert db.query(AuditLog).filter(AuditLog.action == "valuation.method").one().reason == "هماهنگی با حسابداری"


def test_dead_stock_detection(site):
    db = site["db"]
    old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=400)
    with stock_ledger.maintenance(db):
        db.query(StockMovement).update({StockMovement.created_at: old}, synchronize_session=False)
        db.commit()
    data = valuation_service.health(db, site["admin"])
    [item] = data["items"]
    assert item["status"] == "no_sales" and item["idle_days"] >= 399
    buckets = {b["status"]: b["count"] for b in data["buckets"]}
    assert buckets["no_sales"] == 1 and buckets["active"] == 0


# ---------------------------------------------------------------------------
# فصل ۲۲ و ۲۶ — مجوزها و گزارش فعالیت
# ---------------------------------------------------------------------------
def test_permission_overrides_are_enforced_server_side(site):
    db, admin, manager = site["db"], site["admin"], site["manager"]
    assert not permission_service.allowed(db, manager, "audit.view")
    with pytest.raises(ForbiddenError):
        audit_service.list_logs(db, manager)
    with pytest.raises(ConflictError, match="دلیل"):
        permission_service.update(db, admin, "warehouse_manager", "audit.view", True, " ")
    permission_service.update(db, admin, "warehouse_manager", "audit.view", True, "سرپرست شیفت گزارش ببیند")
    assert audit_service.list_logs(db, manager, action="permission.update")["total"] == 1
    # گرفتن مجوز محل‌ها از مدیر انبار
    permission_service.update(db, admin, "warehouse_manager", "masterdata.locations", False, "فقط ادمین محل تعریف کند")
    with pytest.raises(ForbiddenError):
        make_location(db, manager, site["main"], "X-1")
    with pytest.raises(ConflictError):
        permission_service.update(db, admin, "org_admin", "permissions.manage", False, "تست قفل")
    with pytest.raises(ConflictError):
        permission_service.update(db, admin, "warehouse_manager", "valuation.manage", True, "خارج از حداکثر نقش")
    matrix = permission_service.matrix(db, admin)
    row = next(p for p in matrix["permissions"] if p["key"] == "masterdata.locations")
    assert row["roles"]["warehouse_manager"] == {"allowed": False, "editable": True, "customized": True}
    permission_service.reset(db, admin, "بازگشت به پیش‌فرض")
    assert permission_service.allowed(db, manager, "masterdata.locations")


def test_audit_search_by_reason_and_target(site):
    db, admin = site["db"], site["admin"]
    audit_service.log(db, admin, "stock.adjust", "اصلاح موجودی روغن", target_type="movement", target_id=7, reason="شکستگی هنگام تخلیه")
    db.commit()
    assert audit_service.list_logs(db, admin, q="شکستگی")["total"] == 1
    assert audit_service.list_logs(db, admin, target_type="movement", target_id=7)["items"][0]["reason"] == "شکستگی هنگام تخلیه"


# ---------------------------------------------------------------------------
# فصل ۲۷ — برچسب، چاپ مجدد و اسکن
# ---------------------------------------------------------------------------
def test_labels_print_once_then_reprint_needs_reason_and_permission(site):
    db, a1 = site["db"], site["loc"]["a1"]
    pdf, name = label_service.print_labels(db, site["manager"], label_type="location", ids=[a1["id"]], copies=2)
    assert pdf.startswith(b"%PDF") and name.endswith(".pdf")
    with pytest.raises(ForbiddenError):
        label_service.print_labels(db, site["manager"], label_type="location", ids=[a1["id"]], reason="پاره شد")
    with pytest.raises(ConflictError, match="دلیل"):
        label_service.print_labels(db, site["admin"], label_type="location", ids=[a1["id"]])
    label_service.print_labels(db, site["admin"], label_type="location", ids=[a1["id"]], reason="برچسب قبلی پاره شد")
    rows = db.query(LabelPrint).order_by(LabelPrint.id).all()
    assert [(r.is_reprint, r.reason, r.copies) for r in rows] == [(False, None, 2), (True, "برچسب قبلی پاره شد", 1)]
    pdf, _ = label_service.print_labels(db, site["admin"], label_type="product", ids=[site["product"].id])
    assert pdf.startswith(b"%PDF")
    assert [h["is_reprint"] for h in label_service.history(db, site["admin"])] == [False, True, False]


def test_scan_resolves_products_locations_and_tracking_links(site):
    db = site["db"]
    assert scan_service.resolve(db, site["admin"], "6260000000011")["kind"] == "product"
    assert scan_service.resolve(db, site["admin"], "oil-1")["id"] == site["product"].id
    loc = scan_service.resolve(db, site["admin"], site["loc"]["a1"]["barcode"])
    assert loc["kind"] == "location" and loc["code"] == "A-01"
    with pytest.raises(NotFoundError):
        scan_service.resolve(db, site["admin"], "https://passineh.ir/track/LT-NOPE0000")


# ---------------------------------------------------------------------------
# فصل ۲۰ و ۳۰ — گردش‌کار، مسیر برداشت و پیشنهاد جانمایی
# ---------------------------------------------------------------------------
def test_workflow_states_match_the_real_vocabulary():
    states = {w["code"]: [s["code"] for s in w["states"]] for w in wf.workflows()}
    assert states["order"] == list(ORDER_STATUSES)
    assert states["receipt"] == list(RECEIPT_STATUSES)
    assert states["putaway"] == list(PUTAWAY_STATUSES)
    assert states["pick_list"] == list(PICK_LIST_STATUSES)
    assert states["transfer"] == list(TRANSFER_STATUSES)
    for w in wf.workflows():
        codes = {s["code"] for s in w["states"]}
        assert all(t["from"] in codes and t["to"] in codes for t in w["transitions"]), w["code"]


def test_serpentine_route_and_manual_sequence():
    codes = ["A-02-01", "A-01-02", "A-02-02", "A-01-01", "B-01-01"]
    ordered = sorted((Location(code=c) for c in codes), key=location_service.route_key)
    assert [loc.code for loc in ordered] == ["A-01-01", "A-01-02", "A-02-02", "A-02-01", "B-01-01"]
    assert location_service.route_key(Location(code="Z-9", route_sequence=1)) < location_service.route_key(Location(code="A-01-01"))


def test_putaway_ranking_keeps_near_bins_for_a_class(site):
    from app.services import putaway_service
    db, product = site["db"], site["product"]
    product.abc_class = "A"
    db.commit()
    near = putaway_service.ranked_options(db, warehouse_id=site["main"].id, product=product, quantity=1,
                                          stock_status="available", lot_number=None, owner_id=None)
    assert [loc.code for _, loc, _ in near][:2] == ["A-01", "A-02"] and "پرگردش" in near[0][2]
    product.abc_class = "C"
    db.commit()
    far = putaway_service.ranked_options(db, warehouse_id=site["main"].id, product=product, quantity=1,
                                         stock_status="available", lot_number=None, owner_id=None)
    assert [loc.code for _, loc, _ in far][:2] == ["A-02", "A-01"]
    _to_bin(site, site["loc"]["a2"], 1)
    product.abc_class = None
    db.commit()
    first = putaway_service.ranked_options(db, warehouse_id=site["main"].id, product=product, quantity=1,
                                           stock_status="available", lot_number=None, owner_id=None)[0]
    assert first[1].code == "A-02" and "تجمیع" in first[2]


# ---------------------------------------------------------------------------
# فصل ۲۸ — شاخص‌ها و گزارش‌های ناهمگام
# ---------------------------------------------------------------------------
def test_kpi_dashboard_and_new_reports(site):
    db, admin = site["db"], site["admin"]
    _to_bin(site, site["loc"]["a1"], 5)
    _location_count(site, user=admin, counted=5, counter=admin, lock=False)
    st = stocktake_service.list_stocktakes(db, admin)[0]
    stocktake_service.approve(db, admin, st["id"], {})
    data = analytics_service.kpis(db, admin)
    by_key = {k["key"]: k for k in data["kpis"]}
    assert len(data["kpis"]) == 9
    assert by_key["inventory_accuracy"]["value"] == 100.0 and by_key["inventory_accuracy"]["status"] == "good"
    assert by_key["capacity_utilization"]["value"] == 50.0                 # ۱ از ۲ خانه نگهداری
    assert len(data["trend"]) == 30 and data["snapshot"]["on_hand_units"] == 20
    for report in ("kpi", "valuation", "health", "audit"):
        for fmt in ("excel", "csv", "pdf"):
            result = build_report_file(db, admin.organization_id, admin, report, fmt, {})
            assert result["filename"].endswith({"excel": ".xlsx", "csv": ".csv", "pdf": ".pdf"}[fmt])


# ---------------------------------------------------------------------------
# فصل ۳۲ تا ۳۵ — ورود داده و چک‌لیست راه‌اندازی
# ---------------------------------------------------------------------------
def _xlsx(kind, rows):
    wb = Workbook()
    ws = wb.active
    ws.append([title for _, title, *_ in migration_io.COLUMNS[kind]])
    for row in rows:
        ws.append(row)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def test_location_and_opening_balance_import(site):
    db, admin = site["db"], site["admin"]
    locations = _xlsx("locations", [["انبار اصلی", "B", "منطقه", None, "نگهداری"],
                                    ["انبار اصلی", "B-01", "خانه / جایگاه", "B", "برداشت", None, 500, None, None, 3]])
    preview = migration_io.import_locations(db, admin, locations, dry_run=True)
    assert preview["create"] == 2 and preview["error_count"] == 0 and not preview["applied"]
    assert migration_io.import_locations(db, admin, locations, dry_run=False)["applied"] is True
    b01 = db.query(Location).filter(Location.code == "B-01").one()
    assert b01.location_type == "picking" and b01.route_sequence == 3 and b01.parent_id is not None

    bad = migration_io.import_opening(db, admin, _xlsx("opening", [["انبار اصلی", "NOPE", 5]]), dry_run=True)
    assert bad["error_count"] == 1 and "کاتالوگ" in bad["errors"][0]["message"]
    opening = _xlsx("opening", [["انبار اصلی", "OIL-1", 7, "B-01"]])
    report = migration_io.import_opening(db, admin, opening, dry_run=False)
    assert report["applied"] and report["units"] == 7 and report["document_code"].startswith("OB-")
    assert _bin_qty(db, b01.id) == 7 and stock_ledger.find_mismatches(db) == []
    with pytest.raises(ConflictError, match="قبلاً"):
        migration_io.import_opening(db, admin, opening, dry_run=False)
    with pytest.raises(ForbiddenError):
        migration_io.import_opening(db, site["manager"], opening, dry_run=True)   # پیش‌فرض: فقط ادمین
    assert migration_io.template(db, admin, "opening")[:2] == b"PK"


def test_readiness_checklist_and_go_live_signoff(site):
    db, admin = site["db"], site["admin"]
    data = readiness_service.overview(db, admin)
    keys = {c["key"]: c["status"] for c in data["checks"]}
    assert keys["ledger"] == "pass" and keys["opening"] == "pass" and keys["warehouses"] == "warn"
    assert 0 < data["score"] < 100 and data["ready"] is False
    with pytest.raises(ConflictError, match="پیش از امضای شروع"):
        readiness_service.set_manual(db, admin, "go_live_signoff", True, None)
    for key, *_ in readiness_service.MANUAL_ITEMS[:-1]:
        readiness_service.set_manual(db, admin, key, True, "انجام شد")
    done = readiness_service.set_manual(db, admin, "go_live_signoff", True, "شروع رسمی از شنبه")
    assert all(m["done"] for m in done["manual"])
    assert db.query(AuditLog).filter(AuditLog.action == "cutover.check").count() == len(readiness_service.MANUAL_ITEMS)
    with pytest.raises(ForbiddenError):
        readiness_service.overview(db, site["manager"])
    assert db.query(Product).count() == 1
