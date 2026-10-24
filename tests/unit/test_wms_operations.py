"""
عملیات انبار (WMS فصل ۶ تا ۱۰):
  • محل‌ها: سلسله‌مراتب، نوع، ظرفیت، قاعده اختلاط
  • رسید دریافت: مقادیر مورد انتظار/دریافتی/پذیرفته/مردود، مغایرت، جلوگیری از تکرار
  • بازرسی کیفی: وضعیت مستقل از محل، مجوز نقش، عدم تخصیص کالای غیرتأییدشده
  • جانمایی: پیشنهاد مقصد، اجرا با اسکن، خطاها
  • موجودی چندبعدی، دفتر ریز گردش و کاردکس
"""
from datetime import timedelta

import pytest

from app.models import (
    Partner, RoleEnum, StockBalance, StockMovementLine, User, Vehicle, Warehouse,
)
from app.schemas.operations import (
    InspectionCreate, PutawayExecute, PutawayProblemIn, ReceiptCloseIn, ReceiptCreate, ReceiveIn,
)
from app.schemas.product import LocationMoveCreate, ProductCreate, StatusChangeCreate, StockMovementCreate
from app.services import (
    catalog_service, inventory_service, location_service, order_service, putaway_service, quality_service,
    receiving_service, stock_document_service, stock_ledger, stock_position_service,
)
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.services.putaway_service import ScanMismatchError
from app.services.stock_ledger import LedgerViolationError, StockKey
from tests.factories import order_request


def _user(db, role, name, **kw):
    user = User(username=name, email=f"{name}@t.local", role=role, hashed_password="x", **kw)
    db.add(user)
    db.commit()
    return user


def _loc(db, user, warehouse, code, level="bin", location_type="storage", parent=None, **kw):
    return location_service.create_location(db, user, warehouse.id, {
        "code": code, "level": level, "location_type": location_type, "parent_id": parent["id"] if parent else None,
        "allow_mixed_products": True, "allow_mixed_lots": True, "allow_mixed_owners": True, "is_active": True,
        "is_blocked": False, **kw})


@pytest.fixture()
def site(db_session):
    db = db_session
    main = Warehouse(name="انبار اصلی", location="تهران", province="تهران", city="تهران", code="WH-01")
    transit = Warehouse(name="در راه", location="تهران", province="تهران", city="تهران", code="WH-T", type="transit")
    db.add_all([main, transit])
    db.commit()
    admin = _user(db, RoleEnum.ORG_ADMIN, "admin")
    manager = _user(db, RoleEnum.WAREHOUSE_MANAGER, "mgr", warehouse_id=main.id)
    driver = _user(db, RoleEnum.DRIVER, "drv", city="تهران")
    vehicle = Vehicle(license_plate="W-1", type="van", capacity_kg=5000, status="available", driver_id=driver.id, city="تهران")
    supplier = Partner(code="SUP-001", name="تأمین‌کننده نمونه", is_supplier=True)
    owner = Partner(code="OWN-001", name="مالک امانی", is_owner=True)
    db.add_all([vehicle, supplier, owner])
    db.commit()
    product = inventory_service.create_product(db, admin, ProductCreate(
        name="روغن", sku="OIL-1", barcode="6260000000011", price=100, weight_kg=2, length_cm=10, width_cm=10, height_cm=10,
        units_per_pallet=10, initial_quantity=20, warehouse_id=main.id))
    zone = _loc(db, admin, main, "A", level="zone")
    locs = {
        "rcv": _loc(db, admin, main, "RCV", location_type="receiving"),
        "a1": _loc(db, admin, main, "A-01", parent=zone),
        "a2": _loc(db, admin, main, "A-02", parent=zone),
        "q1": _loc(db, admin, main, "Q-01", location_type="quarantine"),
        "zone": zone,
    }
    return {"db": db, "main": main, "transit": transit, "admin": admin, "manager": manager, "vehicle": vehicle,
            "supplier": supplier, "owner": owner, "product": product, "loc": locs}


def _purchase(s, qty=10, **kw):
    data = ReceiptCreate(receipt_type="purchase", warehouse_id=s["main"].id, partner_id=s["supplier"].id,
                         lines=[{"product_id": s["product"].id, "expected_quantity": qty}], **kw)
    return receiving_service.create_receipt(s["db"], s["admin"], data)


def _receive(s, receipt, qty, user=None, key=None, **line):
    entry = {"line_id": receipt["lines"][0]["id"], "quantity": qty, **line}
    return receiving_service.receive(s["db"], user or s["manager"], receipt["id"], ReceiveIn(lines=[entry]), key)


def _balances(db, **filters):
    db.expire_all()
    return {(b.location_id, b.stock_status, b.lot_number): b.quantity
            for b in db.query(StockBalance).filter_by(**filters).all() if b.quantity}


def _position(s):
    [row] = stock_position_service.positions(s["db"], s["admin"], product_id=s["product"].id, warehouse_id=s["main"].id)
    return row


# ---------------------------------------------------------------------------
# فصل ۶ — محل‌ها
# ---------------------------------------------------------------------------
def test_location_hierarchy_requires_lower_levels_and_unique_codes(site):
    db, admin, main, zone = site["db"], site["admin"], site["main"], site["loc"]["zone"]
    assert site["loc"]["a1"]["barcode"] == "WH-01-A-01"
    with pytest.raises(ConflictError):
        _loc(db, admin, main, "A-SUB", level="zone", parent=zone)          # هم‌سطح مادر
    with pytest.raises(ConflictError):
        _loc(db, admin, main, "a-01")                                       # کد تکراری (بدون حساسیت به حروف)
    rack = _loc(db, admin, main, "A-R1", level="rack", parent=zone)
    shelf = _loc(db, admin, main, "A-R1-S1", level="shelf", parent=rack)
    assert [x["depth"] for x in location_service.list_locations(db, admin, main.id) if x["code"].startswith("A-R1")] == [1, 2]
    assert shelf["is_leaf"] and not location_service.location_detail(db, admin, rack["id"])["is_leaf"]


def test_stock_only_sits_in_leaf_active_unblocked_locations(site):
    db, admin, main, product, loc = site["db"], site["admin"], site["main"], site["product"], site["loc"]
    with pytest.raises(ConflictError, match="زیرمجموعه"):
        inventory_service.record_movement(db, admin, StockMovementCreate(
            product_id=product.id, warehouse_id=main.id, movement_type="receipt", quantity=1, location_id=loc["zone"]["id"]))
    location_service.update_location(db, admin, loc["a2"]["id"], {**loc["a2"], "is_blocked": True, "block_reason": "قفسه شکسته"})
    with pytest.raises(ConflictError, match="مسدود"):
        inventory_service.record_movement(db, admin, StockMovementCreate(
            product_id=product.id, warehouse_id=main.id, movement_type="receipt", quantity=1, location_id=loc["a2"]["id"]))
    shelf = _loc(db, admin, main, "S-1", level="shelf")                    # طبقه بدون زیرمجموعه = محل انتهایی
    inventory_service.record_movement(db, admin, StockMovementCreate(
        product_id=product.id, warehouse_id=main.id, movement_type="receipt", quantity=1, location_id=shelf["id"]))
    with pytest.raises(ConflictError, match="کالا دارد"):
        _loc(db, admin, main, "S-1-B1", parent=shelf)                       # زیرمجموعه برای محلِ پر


def test_capacity_weight_volume_and_pallets_are_enforced(site):
    db, admin, main, product, loc = site["db"], site["admin"], site["main"], site["product"], site["loc"]
    a1 = location_service.update_location(db, admin, loc["a1"]["id"], {**loc["a1"], "max_weight_kg": 30, "max_pallets": 1})

    def receive(qty):
        return inventory_service.record_movement(db, admin, StockMovementCreate(
            product_id=product.id, warehouse_id=main.id, movement_type="receipt", quantity=qty, location_id=a1["id"]))
    receive(10)                                                            # ۲۰ کیلو، ۱ پالت
    with pytest.raises(ConflictError, match="پالت"):
        receive(1)                                                         # ۱۱ عدد = ۲ پالت
    location_service.update_location(db, admin, a1["id"], {**a1, "max_pallets": None})
    with pytest.raises(ConflictError, match="وزنی"):
        receive(6)                                                         # ۳۲ کیلو
    with pytest.raises(ConflictError, match="کمتر"):
        location_service.update_location(db, admin, a1["id"], {**a1, "max_pallets": None, "max_weight_kg": 10})
    detail = location_service.location_detail(db, admin, a1["id"])
    assert (detail["quantity"], detail["weight_kg"], detail["volume_m3"], detail["weight_pct"]) == (10, 20, 0.01, 66.7)


def test_mixing_rules_for_products_lots_and_owners(site):
    db, admin, main, product, loc = site["db"], site["admin"], site["main"], site["product"], site["loc"]
    other = inventory_service.create_product(db, admin, ProductCreate(name="کره", sku="BUT-1", price=5, warehouse_id=main.id))
    catalog_service.update(db, admin, product.id, {"lot_tracked": True})
    a1 = location_service.update_location(db, admin, loc["a1"]["id"], {**loc["a1"], "allow_mixed_products": False,
                                                                        "allow_mixed_lots": False})

    def receive(prod, **kw):
        return inventory_service.record_movement(db, admin, StockMovementCreate(
            product_id=prod.id, warehouse_id=main.id, movement_type="receipt", quantity=1, location_id=a1["id"], **kw))
    receive(product, lot_number="L1")
    receive(product, lot_number="l1")                                      # همان بچ (حروف بزرگ می‌شود)
    with pytest.raises(ConflictError, match="بچ"):
        receive(product, lot_number="L2")
    with pytest.raises(ConflictError, match="یک نوع کالا"):
        receive(other)
    # محلی که الان چند کالا دارد نمی‌تواند «تک‌کالایی» شود
    for prod, lot in ((other, None), (product, "L9")):
        inventory_service.record_movement(db, admin, StockMovementCreate(
            product_id=prod.id, warehouse_id=main.id, movement_type="receipt", quantity=1, location_id=loc["a2"]["id"],
            lot_number=lot))
    with pytest.raises(ConflictError, match="تک‌کالایی"):
        location_service.update_location(db, admin, loc["a2"]["id"], {**loc["a2"], "allow_mixed_products": False})


def test_owner_mixing_and_consigned_stock_is_not_allocatable(site):
    db, admin, main, product, loc = site["db"], site["admin"], site["main"], site["product"], site["loc"]
    location_service.update_location(db, admin, loc["a1"]["id"], {**loc["a1"], "allow_mixed_owners": False})
    inv = stock_ledger.lock_bucket(db, product.id, main.id)
    stock_ledger.record(db, inv, 5, "receipt", lines=[(StockKey(location_id=loc["a1"]["id"], owner_id=site["owner"].id), 5)])
    db.commit()
    with pytest.raises(ConflictError, match="مالک"):
        stock_ledger.record(db, inv, 1, "receipt", match={"location_id": loc["a1"]["id"]})
    db.rollback()
    row = _position(site)
    assert (row["on_hand"], row["consigned"], row["allocatable"], row["available"]) == (25, 5, 20, 20)


def test_delete_location_only_without_history(site):
    db, admin, main, product, loc = site["db"], site["admin"], site["main"], site["product"], site["loc"]
    spare = _loc(db, admin, main, "SPARE")
    location_service.delete_location(db, admin, spare["id"])
    inventory_service.record_movement(db, admin, StockMovementCreate(
        product_id=product.id, warehouse_id=main.id, movement_type="receipt", quantity=1, location_id=loc["a1"]["id"]))
    with pytest.raises(ConflictError, match="سابقه"):
        location_service.delete_location(db, admin, loc["a1"]["id"])
    with pytest.raises(ConflictError, match="غیرفعال"):
        location_service.update_location(db, admin, loc["a1"]["id"], {**loc["a1"], "is_active": False})


def test_manager_only_sees_own_warehouse_locations(site):
    db, manager, transit = site["db"], site["manager"], site["transit"]
    assert len(location_service.list_locations(db, manager, site["main"].id)) == 5
    with pytest.raises(ForbiddenError):
        location_service.list_locations(db, manager, transit.id)


# ---------------------------------------------------------------------------
# فصل ۱۰ — دفتر ریز گردش و موجودی چندبعدی
# ---------------------------------------------------------------------------
def test_detail_balances_always_sum_to_bucket_and_lines_are_immutable(site):
    db, admin, main, product = site["db"], site["admin"], site["main"], site["product"]
    inventory_service.record_movement(db, admin, StockMovementCreate(
        product_id=product.id, warehouse_id=main.id, movement_type="receipt", quantity=4, location_id=site["loc"]["a1"]["id"]))
    inventory_service.record_movement(db, admin, StockMovementCreate(
        product_id=product.id, warehouse_id=main.id, movement_type="damage", quantity=3, reason="شکستگی"))
    assert stock_ledger.find_mismatches(db) == []
    line = db.query(StockMovementLine).first()
    line.quantity_change = 99
    with pytest.raises(LedgerViolationError):
        db.flush()
    db.rollback()
    balance = db.query(StockBalance).first()
    balance.quantity += 1
    with pytest.raises(LedgerViolationError):
        db.flush()
    db.rollback()
    balance = db.query(StockBalance).first()
    balance.location_id = site["loc"]["a2"]["id"]
    with pytest.raises(LedgerViolationError):
        db.flush()
    db.rollback()


def test_fefo_pick_and_lot_has_one_expiry(site):
    db, admin, main, product = site["db"], site["admin"], site["main"], site["product"]
    catalog_service.update(db, admin, product.id, {"lot_tracked": True, "expiry_tracked": True})
    today = catalog_service.today_local()
    for lot, days in (("LATE", 300), ("SOON", 30)):
        inventory_service.record_movement(db, admin, StockMovementCreate(
            product_id=product.id, warehouse_id=main.id, movement_type="receipt", quantity=5, lot_number=lot,
            expiry_date=today + timedelta(days=days)))
    with pytest.raises(ConflictError, match="یک تاریخ انقضا"):
        inventory_service.record_movement(db, admin, StockMovementCreate(
            product_id=product.id, warehouse_id=main.id, movement_type="receipt", quantity=1, lot_number="SOON",
            expiry_date=today + timedelta(days=31)))
    with pytest.raises(ConflictError, match="بچ"):
        inventory_service.record_movement(db, admin, StockMovementCreate(
            product_id=product.id, warehouse_id=main.id, movement_type="receipt", quantity=1))
    movement = inventory_service.record_movement(db, admin, StockMovementCreate(
        product_id=product.id, warehouse_id=main.id, movement_type="damage", quantity=27, reason="نمونه"))
    # ابتدا موجودی اولیه بدون بچ؟ نه — بچ زودتر منقضی و بعد بقیه (موجودی بدون انقضا آخر)
    assert [(ln.lot_number, ln.quantity_change) for ln in movement.lines] == [("SOON", -5), ("LATE", -5), (None, -17)]


def test_serial_numbers_are_unique_in_stock(site):
    db, admin, main, product = site["db"], site["admin"], site["main"], site["product"]
    catalog_service.update(db, admin, product.id, {"serial_tracked": True})
    with pytest.raises(ConflictError, match="سریال"):
        inventory_service.record_movement(db, admin, StockMovementCreate(
            product_id=product.id, warehouse_id=main.id, movement_type="receipt", quantity=2, serial_numbers=["S1"]))
    inventory_service.record_movement(db, admin, StockMovementCreate(
        product_id=product.id, warehouse_id=main.id, movement_type="receipt", quantity=2, serial_numbers=["s1", "s2"]))
    with pytest.raises(ConflictError, match="S1"):
        inventory_service.record_movement(db, admin, StockMovementCreate(
            product_id=product.id, warehouse_id=main.id, movement_type="receipt", quantity=1, serial_numbers=["S1"]))


def test_status_change_keeps_location_and_lot(site):
    db, admin, main, product, a1 = site["db"], site["admin"], site["main"], site["product"], site["loc"]["a1"]
    inventory_service.record_movement(db, admin, StockMovementCreate(
        product_id=product.id, warehouse_id=main.id, movement_type="receipt", quantity=6, location_id=a1["id"]))
    inventory_service.change_status(db, admin, StatusChangeCreate(
        product_id=product.id, warehouse_id=main.id, from_status="available", to_status="blocked", quantity=4,
        reason="دستور مدیریت", location_id=a1["id"]))
    assert _balances(db, product_id=product.id)[(a1["id"], "blocked", None)] == 4
    with pytest.raises(ForbiddenError):
        inventory_service.change_status(db, site["manager"], StatusChangeCreate(
            product_id=product.id, warehouse_id=main.id, from_status="blocked", to_status="available", quantity=1,
            reason="آزادسازی"))
    with pytest.raises(ConflictError, match="مجاز نیست"):
        inventory_service.change_status(db, admin, StatusChangeCreate(
            product_id=product.id, warehouse_id=main.id, from_status="available", to_status="pending", quantity=1,
            reason="برگشت به بازرسی"))


def test_location_move_and_exact_reversal(site):
    db, admin, main, product, loc = site["db"], site["admin"], site["main"], site["product"], site["loc"]
    doc = inventory_service.move_between_locations(db, admin, LocationMoveCreate(
        product_id=product.id, warehouse_id=main.id, from_location_id=None, to_location_id=loc["a1"]["id"], quantity=8))
    assert doc["code"].startswith("MV-")
    inventory_service.move_between_locations(db, admin, LocationMoveCreate(
        product_id=product.id, warehouse_id=main.id, from_location_id=loc["a1"]["id"], to_location_id=loc["a2"]["id"],
        quantity=5))
    # کالا بعداً از A-01 رفته است؛ برگشت سند اول باید رد شود (برگشت دقیقاً از همان محل)
    with pytest.raises(ConflictError, match="جابه‌جا"):
        stock_document_service.reverse_document(db, admin, doc["id"], "اشتباه")
    second = stock_document_service.list_documents(db, admin, doc_type="location_move")[0]
    stock_document_service.reverse_document(db, admin, second["id"], "اشتباه")
    stock_document_service.reverse_document(db, admin, doc["id"], "اشتباه")
    assert _balances(db, product_id=product.id) == {(None, "available", None): 20}
    assert stock_ledger.find_mismatches(db) == []


# ---------------------------------------------------------------------------
# فصل ۷ — رسید دریافت
# ---------------------------------------------------------------------------
def test_purchase_receipt_partial_receive_shortage_and_close(site):
    db = site["db"]
    receipt = _purchase(site, qty=10, external_ref="BL-100", reference_number="PO-7")
    assert receipt["code"].startswith("IR-") and receipt["status"] == "open"
    receipt = _receive(site, receipt, 6)
    line = receipt["lines"][0]
    assert (receipt["status"], line["received_quantity"], line["accepted_quantity"], line["outstanding"]) == ("receiving", 6, 6, 4)
    assert receipt["documents"][0]["code"].startswith("GR-")
    with pytest.raises(ConflictError, match="دلیل"):
        receiving_service.close(db, site["admin"], receipt["id"], ReceiptCloseIn())
    closed = receiving_service.close(db, site["admin"], receipt["id"], ReceiptCloseIn(reasons={line["id"]: "تأمین‌کننده کم فرستاد"}))
    line = closed["lines"][0]
    assert (closed["status"], line["discrepancy_type"], line["discrepancy_quantity"]) == ("closed", "shortage", 4)
    with pytest.raises(ConflictError, match="بسته"):
        _receive(site, closed, 1)
    # کالا در محل تخلیه است: هنوز قابل تخصیص نیست، وظیفه جانمایی دارد
    row = _position(site)
    assert (row["approved"], row["not_put_away"], row["allocatable"]) == (26, 6, 20)
    assert closed["putaway_tasks"][0]["quantity"] == 6


def test_duplicate_receipts_are_blocked(site):
    db = site["db"]
    _purchase(site, external_ref="BL-1")
    with pytest.raises(ConflictError, match="BL-1"):
        _purchase(site, external_ref="bl-1")
    data = ReceiptCreate(receipt_type="purchase", warehouse_id=site["main"].id, partner_id=site["supplier"].id,
                         lines=[{"product_id": site["product"].id, "expected_quantity": 3}])
    first = receiving_service.create_receipt(db, site["admin"], data, "receipt-key-0001")
    again = receiving_service.create_receipt(db, site["admin"], data, "receipt-key-0001")
    assert first["id"] == again["id"]
    receipt = _receive(site, first, 2, key="receive-key-0001")
    receipt = _receive(site, receipt, 2, key="receive-key-0001")              # تکرار درخواست: دریافت دوم ثبت نمی‌شود
    assert receipt["lines"][0]["received_quantity"] == 2 and len(receipt["documents"]) == 1
    with pytest.raises(ConflictError):
        receiving_service.create_receipt(db, site["admin"], ReceiptCreate(
            receipt_type="purchase", warehouse_id=site["main"].id, lines=[{"product_id": site["product"].id, "expected_quantity": 1}]))


def test_over_delivery_and_unexpected_items_need_a_reason(site):
    db = site["db"]
    receipt = _purchase(site, qty=10, over_tolerance_pct=10)
    receipt = _receive(site, receipt, 11)                                     # در حد تلورانس
    with pytest.raises(ConflictError, match="اضافه تحویل"):
        _receive(site, receipt, 1)
    receipt = _receive(site, receipt, 1, over_reason="تحویل اضافه با تأیید خرید")
    other = inventory_service.create_product(db, site["admin"], ProductCreate(name="کره", sku="BUT-1", price=5))
    with pytest.raises(ConflictError, match="خارج از برنامه"):
        receiving_service.receive(db, site["manager"], receipt["id"], ReceiveIn(lines=[{"product_id": other.id, "quantity": 2}]))
    receipt = receiving_service.receive(db, site["manager"], receipt["id"], ReceiveIn(
        lines=[{"product_id": other.id, "quantity": 2, "over_reason": "اشتباه در ارسال"}]))
    closed = receiving_service.close(db, site["admin"], receipt["id"], ReceiptCloseIn())
    assert [(ln["discrepancy_type"], ln["discrepancy_quantity"]) for ln in closed["lines"]] == [("over", 2), ("unexpected_item", 2)]


def test_inspection_required_receipt_and_damaged_on_arrival(site):
    db, admin, product = site["db"], site["admin"], site["product"]
    catalog_service.update(db, admin, product.id, {"inspection_required": True})
    receipt = _purchase(site, qty=10)
    receipt = receiving_service.receive(db, site["manager"], receipt["id"], ReceiveIn(lines=[
        {"line_id": receipt["lines"][0]["id"], "quantity": 8},
        {"line_id": receipt["lines"][0]["id"], "quantity": 2, "condition": "damaged"},
    ]))
    line = receipt["lines"][0]
    assert (line["received_quantity"], line["accepted_quantity"], line["rejected_quantity"], line["pending_inspection"]) == (10, 0, 2, 8)
    row = _position(site)
    assert (row["pending_inspection"], row["quarantine"], row["allocatable"]) == (8, 2, 20)
    # کالای در انتظار بازرسی به سفارش نمی‌رسد
    with pytest.raises(ConflictError):
        order_service.create_order(db, admin, order_request(product.id, site["vehicle"].id, quantity=21))


def test_cancel_only_before_receiving(site):
    db = site["db"]
    receipt = _purchase(site)
    canceled = receiving_service.cancel(db, site["admin"], receipt["id"], "سفارش خرید لغو شد")
    assert canceled["status"] == "canceled"
    receipt = _receive(site, _purchase(site), 1)
    with pytest.raises(ConflictError):
        receiving_service.cancel(db, site["admin"], receipt["id"], "دیر شد")


def test_transfer_receipt_pulls_from_transit_warehouse(site):
    db, admin, main, transit, product = site["db"], site["admin"], site["main"], site["transit"], site["product"]
    from app.schemas.product import StockTransferCreate
    inventory_service.transfer_stock(db, admin, StockTransferCreate(
        product_id=product.id, from_warehouse_id=main.id, to_warehouse_id=transit.id, quantity=7))
    receipt = receiving_service.create_receipt(db, admin, ReceiptCreate(
        receipt_type="transfer", warehouse_id=main.id, source_warehouse_id=transit.id,
        lines=[{"product_id": product.id, "expected_quantity": 7}]))
    assert _position(site)["in_transit"] == 7
    receipt = _receive(site, receipt, 5, user=admin)
    assert receipt["lines"][0]["accepted_quantity"] == 5
    [transit_row] = stock_position_service.positions(db, admin, product_id=product.id, warehouse_id=transit.id)
    assert (transit_row["on_hand"], transit_row["in_transit"]) == (2, 2)
    assert _position(site)["in_transit"] == 2
    assert stock_ledger.find_mismatches(db) == []


def test_return_receipt_is_always_pending_inspection(site):
    db, admin = site["db"], site["admin"]
    receipt = receiving_service.create_receipt(db, admin, ReceiptCreate(
        receipt_type="return", warehouse_id=site["main"].id, lines=[{"product_id": site["product"].id, "expected_quantity": 2}]))
    _receive(site, receipt, 2, user=admin)
    assert _position(site)["pending_inspection"] == 2


# ---------------------------------------------------------------------------
# فصل ۸ — بازرسی کیفی
# ---------------------------------------------------------------------------
def test_inspection_results_update_receipt_and_create_putaway_tasks(site):
    db, admin, manager, product, loc = site["db"], site["admin"], site["manager"], site["product"], site["loc"]
    catalog_service.update(db, admin, product.id, {"inspection_required": True})
    receipt = _receive(site, _purchase(site, qty=10), 10)
    assert receipt["putaway_tasks"] == []                                     # در انتظار بازرسی جانمایی نمی‌شود
    inspection = quality_service.inspect(db, manager, InspectionCreate(
        product_id=product.id, receipt_id=receipt["id"], results=[
            {"status": "available", "quantity": 7}, {"status": "rejected", "quantity": 3, "reason": "پلمب باز"}]))
    assert inspection["code"].startswith("QC-") and inspection["document_code"].startswith("QI-")
    # وضعیت عوض شد، محل نه
    assert _balances(db, product_id=product.id) == {
        (None, "available", None): 20, (loc["rcv"]["id"], "available", None): 7, (loc["rcv"]["id"], "rejected", None): 3}
    receipt = receiving_service.get_receipt(db, admin, receipt["id"])
    line = receipt["lines"][0]
    assert (line["accepted_quantity"], line["rejected_quantity"], line["pending_inspection"]) == (7, 3, 0)
    tasks = {(t["stock_status"], t["quantity"], t["suggested_location_code"])
             for t in putaway_service.list_tasks(db, admin, receipt_id=receipt["id"])}
    assert tasks == {("available", 7, "A-01"), ("rejected", 3, "Q-01")}
    # رد شده‌ها را فقط ادمین آزاد می‌کند
    with pytest.raises(ForbiddenError):
        quality_service.inspect(db, manager, InspectionCreate(product_id=product.id, from_status="rejected",
                                                              results=[{"status": "available", "quantity": 1}]))
    with pytest.raises(ConflictError, match="کافی نیست"):
        quality_service.inspect(db, manager, InspectionCreate(product_id=product.id, results=[{"status": "available", "quantity": 1}]))


def test_quarantined_stock_is_never_allocated(site):
    db, admin, product, main = site["db"], site["admin"], site["product"], site["main"]
    inventory_service.change_status(db, admin, StatusChangeCreate(
        product_id=product.id, warehouse_id=main.id, from_status="available", to_status="quarantine", quantity=15,
        reason="شک به آلودگی"))
    with pytest.raises(ConflictError):
        order_service.create_order(db, admin, order_request(product.id, site["vehicle"].id, quantity=6))
    order_service.create_order(db, admin, order_request(product.id, site["vehicle"].id, quantity=5))
    # رزرو بی‌پوشش نمی‌ماند: کالای رزروشده را نمی‌توان قرنطینه کرد
    with pytest.raises(ConflictError):
        inventory_service.change_status(db, admin, StatusChangeCreate(
            product_id=product.id, warehouse_id=main.id, from_status="available", to_status="quarantine", quantity=1,
            reason="شک به آلودگی"))


# ---------------------------------------------------------------------------
# فصل ۹ — جانمایی
# ---------------------------------------------------------------------------
def _task(s):
    receipt = _receive(s, _purchase(s, qty=6), 6)
    return receipt, putaway_service.get_task(s["db"], s["admin"], receipt["putaway_tasks"][0]["id"])


def _scan(task, **kw):
    return PutawayExecute(**{"product_scan": "6260000000011", "source_scan": "RCV",
                             "destination_scan": task["suggested_location_code"], "quantity": task["remaining"], **kw})


def test_putaway_requires_correct_scans_and_logs_failures(site):
    db, manager = site["db"], site["manager"]
    _, task = _task(site)
    assert (task["source_location_code"], task["suggested_location_code"]) == ("RCV", "A-01")
    with pytest.raises(ScanMismatchError, match="کالای اسکن‌شده"):
        putaway_service.execute(db, manager, task["id"], _scan(task, product_scan="WRONG"))
    with pytest.raises(ScanMismatchError, match="مبدأ"):
        putaway_service.execute(db, manager, task["id"], _scan(task, source_scan="A-02"))
    with pytest.raises(ScanMismatchError, match="قرنطینه|نگهداری"):
        putaway_service.execute(db, manager, task["id"], _scan(task, destination_scan="Q-01"))
    task = putaway_service.get_task(db, manager, task["id"])
    assert (task["failure_count"], task["last_problem"]) == (3, "scan_mismatch")

    task = putaway_service.execute(db, manager, task["id"], _scan(task, product_scan="oil-1", quantity=4))
    assert (task["status"], task["remaining"]) == ("partial", 2)
    task = putaway_service.execute(db, manager, task["id"], _scan(task, destination_scan="WH-01-A-02"))   # مقصد غیر از پیشنهاد
    assert (task["status"], task["destination_location_code"]) == ("done", "A-02")
    a1, a2 = site["loc"]["a1"]["id"], site["loc"]["a2"]["id"]
    assert _balances(db, product_id=site["product"].id) == {(None, "available", None): 20, (a1, "available", None): 4,
                                                             (a2, "available", None): 2}
    assert _position(site)["allocatable"] == 26
    assert stock_ledger.find_mismatches(db) == []


def test_putaway_rule_violation_and_problem_reports(site):
    db, admin, manager, loc = site["db"], site["admin"], site["manager"], site["loc"]
    _, task = _task(site)
    location_service.update_location(db, admin, loc["a1"]["id"], {**loc["a1"], "max_pallets": 1})
    location_service.update_location(db, admin, loc["a2"]["id"], {**loc["a2"], "max_weight_kg": 4})
    with pytest.raises(ConflictError, match="وزنی"):
        putaway_service.execute(db, manager, task["id"], _scan(task, destination_scan="A-02"))
    assert putaway_service.get_task(db, manager, task["id"])["last_problem"] == "rule_violation"
    task = putaway_service.report_problem(db, manager, task["id"], PutawayProblemIn(problem="destination_full"))
    assert task["suggested_location_code"] is None                           # A-01 کنار رفت، A-02 جا ندارد
    location_service.update_location(db, admin, loc["a2"]["id"], {**loc["a2"], "max_weight_kg": None})
    task = putaway_service.refresh_suggestion(db, manager, task["id"])
    assert task["suggested_location_code"] == "A-02"
    task = putaway_service.report_problem(db, manager, task["id"], PutawayProblemIn(problem="item_damaged", note="خیس شده"))
    assert task["status"] == "canceled"
    assert _balances(db, product_id=site["product"].id)[(loc["rcv"]["id"], "damaged", None)] == 6


def test_putaway_tasks_cannot_overbook_stock(site):
    db, manager, product, loc = site["db"], site["manager"], site["product"], site["loc"]
    from app.schemas.operations import PutawayTaskCreate
    _task(site)                                                               # ۶ عدد در RCV، همه وظیفه دارند
    with pytest.raises(ConflictError, match="وظیفه جانمایی"):
        putaway_service.create_task(db, manager, PutawayTaskCreate(product_id=product.id, quantity=1,
                                                                   source_location_id=loc["rcv"]["id"]))
    task = putaway_service.create_task(db, manager, PutawayTaskCreate(product_id=product.id, quantity=5))  # بدون محل
    assert (task["source_location_code"], task["suggested_location_code"]) == (None, "A-01")
    with pytest.raises(ScanMismatchError, match="کد انبار"):
        putaway_service.execute(db, manager, task["id"], _scan(task, source_scan="RCV"))
    task = putaway_service.execute(db, manager, task["id"], _scan(task, source_scan="wh-01"))
    assert task["status"] == "done"


def test_receiving_location_stock_is_not_allocated_until_putaway(site):
    db, admin, product, vehicle = site["db"], site["admin"], site["product"], site["vehicle"]
    inventory_service.change_status(db, admin, StatusChangeCreate(
        product_id=product.id, warehouse_id=site["main"].id, from_status="available", to_status="quarantine",
        quantity=20, reason="بازرسی دوره‌ای"))
    _, task = _task(site)
    with pytest.raises(ConflictError):
        order_service.create_order(db, admin, order_request(product.id, vehicle.id, quantity=1))
    putaway_service.execute(db, site["manager"], task["id"], _scan(task))
    order = order_service.create_order(db, admin, order_request(product.id, vehicle.id, quantity=6))
    # حواله خروج از همان محل نگهداری برداشت می‌شود
    from app.schemas.order import OrderStatusRequest
    order_service.update_order_status(db, admin, order.id, OrderStatusRequest(order_status="picked_up"))
    assert _balances(db, product_id=product.id, stock_status="available") == {}
    assert stock_ledger.find_mismatches(db) == []


# ---------------------------------------------------------------------------
# فصل ۱۰ — کاردکس
# ---------------------------------------------------------------------------
def test_stock_card_running_balance_and_internal_moves(site):
    db, admin, manager, product, main = site["db"], site["admin"], site["manager"], site["product"], site["main"]
    _, task = _task(site)
    putaway_service.execute(db, manager, task["id"], _scan(task))
    inventory_service.record_movement(db, admin, StockMovementCreate(
        product_id=product.id, warehouse_id=main.id, movement_type="damage", quantity=3, reason="شکستگی"))
    card = stock_position_service.stock_card(db, admin, product_id=product.id, warehouse_id=main.id)
    assert [(r["doc_type"], r["quantity_in"], r["quantity_out"], r["balance"]) for r in card["rows"]] == [
        ("opening", 20, 0, 20), ("inbound_receipt", 6, 0, 26), ("write_off", 0, 3, 23)]
    assert (card["opening_balance"], card["closing_balance"]) == (0, 23)
    a1 = site["loc"]["a1"]["id"]
    card = stock_position_service.stock_card(db, manager, product_id=product.id, location_id=a1)
    assert [(r["doc_type"], r["quantity_in"], r["balance"]) for r in card["rows"]] == [("putaway", 6, 6)]
    full = stock_position_service.stock_card(db, admin, product_id=product.id, include_internal=True)
    assert [r["doc_type"] for r in full["rows"]] == ["opening", "inbound_receipt", "putaway", "write_off"]
    tomorrow = catalog_service.today_local() + timedelta(days=1)
    later = stock_position_service.stock_card(db, admin, product_id=product.id, date_from=tomorrow)
    assert (later["opening_balance"], later["rows"]) == (23, [])
    with pytest.raises(NotFoundError):
        stock_position_service.stock_card(db, admin, product_id=999)
