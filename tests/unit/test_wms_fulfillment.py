"""
اجرای سفارش و جابه‌جایی (WMS فصل ۱۱ تا ۱۵):
  • سفارش معوق و تخصیص با اولویت • سفارش انتقال با وضعیت «در راه» و کسری
  • تأمین مجدد محل برداشت و ABC • پیکینگ با اسکن و FEFO، بسته‌بندی، محموله و ظرفیت خودرو
  • مرجوعی با بازرسی و تعیین تکلیف (امحا، تعمیر، برگشت به تأمین‌کننده)
"""
from datetime import timedelta

import pytest

from app.models import Backorder, Order, Product, StockMovement, StockReservation, Warehouse
from app.schemas.fulfillment import (
    DispositionCreate, PackIn, PickIn, PickListCreate, ReplenishmentRuleIn, ShipmentCreate, ShortIn, TransferCloseIn,
    TransferCreate, TransferReceiveIn,
)
from app.schemas.operations import ReceiptCreate, ReceiveIn
from app.schemas.order import OrderStatusRequest
from app.schemas.product import LocationMoveCreate, StatusChangeCreate
from app.services import (
    backorder_service, catalog_service, disposition_service, inventory_service, order_service, picking_service,
    putaway_service, receiving_service, replenishment_rule_service, shipping_service, stock_ledger, stock_position_service,
    transfer_order_service,
)
from app.services.exceptions import ConflictError, ForbiddenError
from app.services.putaway_service import ScanMismatchError
from tests.factories import order_request
from tests.unit.test_wms_operations import _balances
from tests.wms_helpers import build_site, make_location as _loc


@pytest.fixture()
def site(db_session):
    return build_site(db_session)


def _position(s, warehouse=None):
    [row] = stock_position_service.positions(s["db"], s["admin"], product_id=s["product"].id,
                                             warehouse_id=(warehouse or s["main"]).id)
    return row


def _to_bin(s, location, quantity):
    inventory_service.move_between_locations(s["db"], s["admin"], LocationMoveCreate(
        product_id=s["product"].id, warehouse_id=s["main"].id, to_location_id=location["id"], quantity=quantity))


def _order(s, quantity, **kw):
    return order_service.create_order(s["db"], s["admin"], order_request(s["product"].id, s["vehicle"].id, quantity=quantity, **kw))


# ---------------------------------------------------------------------------
# فصل ۱۱ — سفارش معوق و اولویت تخصیص
# ---------------------------------------------------------------------------
def test_backorder_keeps_unfulfilled_quantity(site):
    db = site["db"]
    with pytest.raises(ConflictError):
        _order(site, 25)
    order = _order(site, 25, allow_backorder=True)
    assert [(i.quantity) for i in order.items] == [20]
    [backorder] = backorder_service.list_backorders(db, site["admin"], order_id=order.id)
    assert (backorder["quantity"], backorder["status"]) == (5, "open")
    assert _position(site)["available"] == 0


def test_backorders_are_allocated_by_priority_then_due_date(site):
    db, admin = site["db"], site["admin"]
    urgent = _order(site, 1, priority=True)                                 # سفارش فوری: ۱ عدد رزرو
    late = _order(site, 22, allow_backorder=True)                          # ۱۹ رزرو، ۳ معوق، عادی
    # بخش تأمین‌نشده سفارش فوری (مثلاً افزایش مقدار): ۴ عدد معوق با اولویت
    backorder_service.open_backorder(db, admin, urgent, site["product"], 4, 100)
    db.commit()
    receipt = receiving_service.create_receipt(db, admin, ReceiptCreate(
        receipt_type="purchase", warehouse_id=site["main"].id, partner_id=site["supplier"].id,
        lines=[{"product_id": site["product"].id, "expected_quantity": 5}]))
    receiving_service.receive(db, admin, receipt["id"], ReceiveIn(lines=[{"line_id": receipt["lines"][0]["id"], "quantity": 5}]))
    # کالا در محل تخلیه است و قابل تخصیص نیست؛ بعد از جانمایی به سفارش‌های معوق می‌رسد
    assert backorder_service.allocate(db, admin)["allocated_quantity"] == 0
    [task] = putaway_service.list_tasks(db, admin, status="active")
    putaway_service.execute(db, admin, task["id"], putaway_service_scan(task))
    result = backorder_service.allocate(db, admin)
    assert result == {"allocated_quantity": 5, "split": 1}
    rows = {(b["order_id"], b["status"]): b["quantity"] for b in backorder_service.list_backorders(db, admin, status=None)}
    assert rows == {(urgent.id, "allocated"): 4, (late.id, "allocated"): 1, (late.id, "open"): 2}
    tomorrow = order_service.datetime.now(order_service.timezone.utc) + timedelta(hours=2)
    follow = backorder_service.fulfill(db, admin, urgent.id, tomorrow, tomorrow + timedelta(hours=3))
    assert (follow.parent_order_id, follow.total_quantity) == (urgent.id, 4)
    assert db.query(StockReservation).filter_by(reference_type="order", reference_id=follow.id, status="active").one().quantity == 4
    order_service.update_order_status(db, admin, late.id, OrderStatusRequest(order_status="canceled"))
    assert {b.status for b in db.query(Backorder).filter_by(order_id=late.id)} == {"canceled"}
    assert stock_ledger.find_mismatches(db) == []


def putaway_service_scan(task):
    from app.schemas.operations import PutawayExecute
    return PutawayExecute(product_scan="OIL-1", source_scan=task["source_location_code"] or "WH-01",
                          destination_scan=task["suggested_location_code"], quantity=task["remaining"])


# ---------------------------------------------------------------------------
# فصل ۱۲ — سفارش انتقال
# ---------------------------------------------------------------------------
def test_transfer_order_tracks_in_transit_and_discrepancies(site):
    db, admin, main = site["db"], site["admin"], site["main"]
    second = Warehouse(name="شعبه", code="WH-02", city="تهران", province="تهران")
    db.add(second)
    db.commit()
    dock = _loc(db, admin, second, "D-RCV", location_type="receiving")
    transfer = transfer_order_service.create(db, admin, TransferCreate(
        from_warehouse_id=main.id, to_warehouse_id=second.id, to_location_id=dock["id"],
        lines=[{"product_id": site["product"].id, "quantity": 6}]))
    assert transfer["code"].startswith("TO-") and transfer["status"] == "open"
    transfer = transfer_order_service.ship(db, admin, transfer["id"])
    assert transfer["status"] == "in_transit"
    assert (_position(site)["on_hand"], _position(site, second)["in_transit"]) == (14, 6)
    assert _position(site, second)["allocatable"] == 0
    line = transfer["lines"][0]
    transfer = transfer_order_service.receive(db, admin, transfer["id"], TransferReceiveIn(
        lines=[{"line_id": line["id"], "received_quantity": 4, "damaged_quantity": 1, "reason": "کارتن له شده"}]))
    assert (transfer["lines"][0]["in_transit"], transfer["status"]) == (1, "in_transit")
    with pytest.raises(ConflictError, match="دلیل"):
        transfer_order_service.close(db, admin, transfer["id"], TransferCloseIn())
    transfer = transfer_order_service.close(db, admin, transfer["id"], TransferCloseIn(resolution="write_off", reason="گم شد در حمل"))
    assert (transfer["status"], transfer["lines"][0]["resolved_quantity"]) == ("closed", 1)
    row = _position(site, second)
    assert (row["on_hand"], row["in_transit"], row["quarantine"]) == (5, 0, 1)
    assert _balances(db, warehouse_id=second.id) == {(dock["id"], "available", None): 4, (dock["id"], "damaged", None): 1}
    assert stock_ledger.find_mismatches(db) == []


def test_internal_two_step_transfer_and_manager_scope(site):
    db, manager = site["db"], site["manager"]
    _to_bin(site, site["loc"]["a1"], 8)
    transfer = transfer_order_service.create(db, manager, TransferCreate(
        from_warehouse_id=site["main"].id, to_warehouse_id=site["main"].id, from_location_id=site["loc"]["a1"]["id"],
        to_location_id=site["loc"]["a2"]["id"], lines=[{"product_id": site["product"].id, "quantity": 3}]))
    assert transfer["internal"]
    transfer_order_service.ship(db, manager, transfer["id"])
    assert _position(site)["in_transit"] == 3
    line = transfer_order_service.get(db, manager, transfer["id"])["lines"][0]
    transfer_order_service.receive(db, manager, transfer["id"], TransferReceiveIn(lines=[{"line_id": line["id"], "received_quantity": 3}]))
    a1, a2 = site["loc"]["a1"]["id"], site["loc"]["a2"]["id"]
    assert {k: v for k, v in _balances(db, product_id=site["product"].id).items() if k[0] in (a1, a2)} == {
        (a1, "available", None): 5, (a2, "available", None): 3}
    with pytest.raises(ForbiddenError):
        transfer_order_service.create(db, manager, TransferCreate(
            from_warehouse_id=site["transit"].id, to_warehouse_id=site["main"].id,
            lines=[{"product_id": site["product"].id, "quantity": 1}]))


# ---------------------------------------------------------------------------
# فصل ۱۴ — پیکینگ، بسته‌بندی، ارسال
# ---------------------------------------------------------------------------
def _pick_all(s, pick_list, **override):
    for line in pick_list["lines"]:
        if line["status"] != "open":
            continue
        pick_list = picking_service.pick(s["db"], s["manager"], line["id"], PickIn(**{
            "source_scan": line["location_code"] or "WH-01", "product_scan": "OIL-1",
            "quantity": line["quantity"] - line["picked_quantity"], **override}))
    return pick_list


def test_single_order_pick_pack_ship_with_scans_and_capacity(site):
    db, admin, manager = site["db"], site["admin"], site["manager"]
    _to_bin(site, site["loc"]["a2"], 12)
    _to_bin(site, site["loc"]["a1"], 8)
    staging = _loc(db, admin, site["main"], "STG", location_type="staging")
    order = _order(site, 10)
    pick_list = picking_service.create_pick_list(db, manager, PickListCreate(
        strategy="single", order_ids=[order.id], staging_location_id=staging["id"]))
    assert pick_list["code"].startswith("PL-")
    assert [(ln["location_code"], ln["quantity"]) for ln in pick_list["lines"]] == [("A-01", 8), ("A-02", 2)]
    with pytest.raises(ScanMismatchError):
        picking_service.pick(db, manager, pick_list["lines"][0]["id"], PickIn(source_scan="A-02", product_scan="OIL-1", quantity=8))
    pick_list = _pick_all(site, pick_list)
    assert pick_list["status"] == "picked"
    db.expire_all()
    assert db.get(Order, order.id).fulfillment_state == "picked"
    # کالای منتقل‌شده به آماده‌سازی هنوز پوشش رزرو همین سفارش است: قابل وعده تغییر نمی‌کند
    row = _position(site)
    assert (row["picked"], row["reserved"], row["available"]) == (10, 10, 10)
    with pytest.raises(ConflictError, match="برابر نیست"):
        shipping_service.pack(db, manager, order.id, PackIn(packages=[{"length_cm": 40, "width_cm": 30, "height_cm": 20,
                                                                       "items": [{"product_id": site["product"].id, "quantity": 9}]}]))
    slip = shipping_service.pack(db, manager, order.id, PackIn(packages=[
        {"length_cm": 40, "width_cm": 30, "height_cm": 20, "items": [{"product_id": site["product"].id, "quantity": 6}]},
        {"length_cm": 30, "width_cm": 30, "height_cm": 20, "weight_kg": 9, "items": [{"product_id": site["product"].id, "quantity": 4}]},
    ]))
    assert (slip["packages"][0]["code"], slip["total_weight_kg"]) == (f"{order.tracking_code}-1", 21)
    site["vehicle"].max_weight_kg = 15
    db.commit()
    with pytest.raises(ConflictError, match="ظرفیت وزنی"):
        shipping_service.create_shipment(db, manager, ShipmentCreate(vehicle_id=site["vehicle"].id, order_ids=[order.id]))
    site["vehicle"].max_weight_kg, site["vehicle"].max_volume_m3 = 100, 0.03
    db.commit()
    with pytest.raises(ConflictError, match="ظرفیت حجمی"):
        shipping_service.create_shipment(db, manager, ShipmentCreate(vehicle_id=site["vehicle"].id, order_ids=[order.id]))
    site["vehicle"].max_volume_m3 = 1
    db.commit()
    shipment = shipping_service.create_shipment(db, manager, ShipmentCreate(vehicle_id=site["vehicle"].id, order_ids=[order.id]))
    shipment = shipping_service.dispatch(db, manager, shipment["id"])
    assert shipment["status"] == "dispatched"
    db.expire_all()
    order = db.get(Order, order.id)
    assert (order.status, order.stock_state, order.fulfillment_state) == ("picked_up", "issued", "shipped")
    issue = db.query(StockMovement).filter_by(movement_type="order_out", reference_id=order.id).one()
    assert [(ln.location_id, ln.quantity_change) for ln in issue.lines] == [(staging["id"], -10)]
    assert _position(site)["picked"] == 0
    assert stock_ledger.find_mismatches(db) == []


def test_short_pick_replans_and_incomplete_pick_blocks_issue(site):
    db, manager = site["db"], site["manager"]
    _to_bin(site, site["loc"]["a1"], 3)
    _to_bin(site, site["loc"]["a2"], 10)
    order = _order(site, 5)
    pick_list = picking_service.create_pick_list(db, manager, PickListCreate(strategy="single", order_ids=[order.id]))
    first = pick_list["lines"][0]
    assert (first["location_code"], first["quantity"]) == ("A-01", 3)
    pick_list = picking_service.short(db, manager, first["id"], ShortIn(reason="قفسه خالی بود"))
    assert pick_list["replanned"] == 3
    with pytest.raises(ConflictError, match="کامل نشده"):
        order_service.update_order_status(db, site["admin"], order.id, OrderStatusRequest(order_status="picked_up"))
    pick_list = _pick_all(site, pick_list)
    assert pick_list["status"] == "picked"
    order_service.update_order_status(db, site["admin"], order.id, OrderStatusRequest(order_status="picked_up"))
    assert _balances(db, product_id=site["product"].id)[(site["loc"]["a2"]["id"], "available", None)] == 5


def test_batch_wave_and_zone_strategies(site):
    db, manager = site["db"], site["manager"]
    _to_bin(site, site["loc"]["a1"], 10)
    first, second = _order(site, 2), _order(site, 3)
    with pytest.raises(ConflictError, match="دقیقاً یک"):
        picking_service.create_pick_list(db, manager, PickListCreate(strategy="single", order_ids=[first.id, second.id]))
    batch = picking_service.create_pick_list(db, manager, PickListCreate(strategy="zone", zone_location_id=site["loc"]["zone"]["id"]))
    assert set(batch["orders"]) == {first.tracking_code, second.tracking_code}
    assert all(ln["location_code"] == "A-01" for ln in batch["lines"])
    picking_service.cancel_list(db, manager, batch["id"], "آزمون لغو")
    today = catalog_service.today_local()
    wave = picking_service.create_pick_list(db, manager, PickListCreate(strategy="wave", wave_date=today))
    assert len(wave["orders"]) == 2 and wave["total_quantity"] == 5
    assert picking_service.candidates(db, manager, None) == []


# ---------------------------------------------------------------------------
# فصل ۱۳ — تأمین مجدد و ABC
# ---------------------------------------------------------------------------
def test_picking_location_min_max_replenishment(site):
    db, admin, manager = site["db"], site["admin"], site["manager"]
    pick_face = _loc(db, admin, site["main"], "P-01", location_type="picking")
    _to_bin(site, site["loc"]["a1"], 20)
    with pytest.raises(ConflictError, match="برداشت"):
        replenishment_rule_service.save_rule(db, manager, ReplenishmentRuleIn(
            location_id=site["loc"]["a1"]["id"], product_id=site["product"].id, min_quantity=1, max_quantity=5))
    rule = replenishment_rule_service.save_rule(db, manager, ReplenishmentRuleIn(
        location_id=pick_face["id"], product_id=site["product"].id, min_quantity=2, max_quantity=8))
    assert rule["needs_replenishment"]
    assert replenishment_rule_service.generate(db, manager, None)["quantity"] == 8
    assert replenishment_rule_service.generate(db, manager, None)["quantity"] == 0       # وظیفه باز کافی است
    [task] = putaway_service.list_tasks(db, manager, status="active", task_type="replenishment")
    assert (task["source_location_code"], task["suggested_location_code"], task["quantity"]) == ("A-01", "P-01", 8)
    putaway_service.execute(db, manager, task["id"], putaway_service_scan(task))
    rule = replenishment_rule_service.list_rules(db, manager, None)[0]
    assert (rule["current_quantity"], rule["needs_replenishment"]) == (8, False)
    doc = db.query(StockMovement).filter_by(movement_type="move_in").order_by(StockMovement.id.desc()).first().document
    assert doc.doc_type == "replenishment" and doc.code.startswith("RP-")


def test_abc_classification_and_count_due(site):
    db, admin, main = site["db"], site["admin"], site["main"]
    other = inventory_service.create_product(db, admin, __import__("app.schemas.product", fromlist=["ProductCreate"]).ProductCreate(
        name="کره", sku="BUT-1", price=1, initial_quantity=50, warehouse_id=main.id))
    order = order_service.create_order(db, admin, order_request(items=[(site["product"].id, 10), (other.id, 2)], vehicle_id=site["vehicle"].id))
    order_service.update_order_status(db, admin, order.id, OrderStatusRequest(order_status="picked_up"))
    result = replenishment_rule_service.classify(db, admin)
    assert (result["A"], result["C"]) == (1, 1)
    report = {r["product_sku"]: r for r in replenishment_rule_service.abc_report(db, admin)}
    assert (report["OIL-1"]["abc_class"], report["OIL-1"]["count_every_days"], report["OIL-1"]["count_due"]) == ("A", 30, True)
    assert report["BUT-1"]["abc_class"] in ("B", "C")
    assert db.get(Product, site["product"].id).abc_value == 1000


# ---------------------------------------------------------------------------
# فصل ۱۵ — مرجوعی و تعیین تکلیف
# ---------------------------------------------------------------------------
def test_failed_delivery_returns_for_inspection(site):
    db, admin = site["db"], site["admin"]
    order = _order(site, 4)
    order_service.update_order_status(db, admin, order.id, OrderStatusRequest(order_status="picked_up"))
    order_service.update_order_status(db, admin, order.id, OrderStatusRequest(order_status="failed"))
    row = _position(site)
    assert (row["pending_inspection"], row["allocatable"]) == (4, 16)


def test_dispositions_scrap_repair_reinspect_and_supplier_return(site):
    db, admin, manager, product = site["db"], site["admin"], site["manager"], site["product"]
    receipt = receiving_service.create_receipt(db, admin, ReceiptCreate(
        receipt_type="purchase", warehouse_id=site["main"].id, partner_id=site["supplier"].id,
        lines=[{"product_id": product.id, "expected_quantity": 6}]))
    receiving_service.receive(db, admin, receipt["id"], ReceiveIn(
        lines=[{"line_id": receipt["lines"][0]["id"], "quantity": 6, "condition": "damaged"}]))
    common = {"product_id": product.id, "warehouse_id": site["main"].id, "reason": "تصمیم کمیته کیفیت"}
    scrap = disposition_service.dispose(db, manager, DispositionCreate(from_status="damaged", action="scrap", quantity=1, **common))
    assert scrap["code"].startswith("DS-") and scrap["document_code"].startswith("SC-")
    with pytest.raises(ConflictError, match="تأمین‌کننده"):
        disposition_service.dispose(db, manager, DispositionCreate(from_status="damaged", action="return_to_supplier", quantity=1, **common))
    with pytest.raises(ConflictError, match="قابل برگشت"):
        disposition_service.dispose(db, manager, DispositionCreate(
            from_status="damaged", action="return_to_supplier", quantity=7, partner_id=site["supplier"].id,
            receipt_id=receipt["id"], **common))
    back = disposition_service.dispose(db, manager, DispositionCreate(
        from_status="damaged", action="return_to_supplier", quantity=2, partner_id=site["supplier"].id,
        receipt_id=receipt["id"], **common))
    assert (back["document_code"][:3], back["partner_name"]) == ("SR-", site["supplier"].name)
    disposition_service.dispose(db, manager, DispositionCreate(from_status="damaged", action="repair", quantity=3, **common))
    disposition_service.dispose(db, manager, DispositionCreate(from_status="repair", action="reinspect", quantity=3, **common))
    with pytest.raises(ConflictError, match="نگه‌داشته"):
        disposition_service.dispose(db, manager, DispositionCreate(from_status="pending", action="scrap", quantity=1, **common))
    row = _position(site)
    assert (row["on_hand"], row["pending_inspection"], row["by_status"].get("repair")) == (23, 3, None)
    assert len(disposition_service.list_dispositions(db, manager)) == 4
    assert stock_ledger.find_mismatches(db) == []


def test_dispositions_follow_quality_transitions(site):
    db, admin = site["db"], site["admin"]
    inventory_service.change_status(db, admin, StatusChangeCreate(
        product_id=site["product"].id, warehouse_id=site["main"].id, from_status="available", to_status="defective",
        quantity=2, reason="نقص فنی"))
    # معیوب مستقیم بازرسی دوباره نمی‌شود: اول تعمیر، بعد از «در تعمیر» به «در انتظار بازرسی»
    with pytest.raises(ConflictError, match="مجاز نیست"):
        disposition_service.dispose(db, site["manager"], DispositionCreate(
            product_id=site["product"].id, from_status="defective", action="reinspect", quantity=1, reason="تعمیر شد"))
