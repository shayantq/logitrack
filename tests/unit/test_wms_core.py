"""
اصول پایه انبارداری (WMS فصل ۱ تا ۵):
  • تغییر موجودی فقط با سند؛ سند و گردش تغییرناپذیر؛ اصلاح با سند برگشت
  • جدایی وضعیت کیفی، تخصیص (رزرو) و وضعیت سند
  • یکتایی درخواست (Idempotency) و رویدادهای دامنه در همان تراکنش
  • انواع و سلسله‌مراتب انبار، داده پایه کالا، جداسازی ارجاع بین سازمان‌ها
"""
from datetime import timedelta

import pytest

from app.core.tenancy import TenantIsolationError, set_tenant
from app.models import (
    DomainEvent, Inventory, Order, Organization, Product, RoleEnum, StockDocument, StockMovement, StockReservation, User,
    Vehicle, Warehouse,
)
from app.schemas.order import OrderStatusRequest
from app.schemas.product import ProductCreate, StatusChangeCreate, StockMovementCreate, StockTransferCreate
from app.services import (
    allocation_service, catalog_service, inventory_service, order_service, stock_document_service, stock_ledger,
    stocktake_service, warehouse_service,
)
from app.services.exceptions import ConflictError, ForbiddenError
from app.services.stock_document_service import IdempotencyConflictError
from app.services.stock_ledger import LedgerViolationError
from tests.factories import order_request


def _user(db, role, name, **kw):
    user = User(username=name, email=f"{name}@t.local", role=role, hashed_password="x", **kw)
    db.add(user)
    db.commit()
    return user


@pytest.fixture()
def world(db_session):
    db = db_session
    main = Warehouse(name="انبار اصلی", location="تهران", province="تهران", city="تهران", code="WH-01")
    quarantine = Warehouse(name="قرنطینه", location="تهران", province="تهران", city="تهران", code="WH-Q", type="quarantine")
    db.add_all([main, quarantine])
    db.commit()
    admin = _user(db, RoleEnum.ORG_ADMIN, "admin")
    manager = _user(db, RoleEnum.WAREHOUSE_MANAGER, "mgr", warehouse_id=main.id)
    driver = _user(db, RoleEnum.DRIVER, "drv", city="تهران")
    vehicle = Vehicle(license_plate="W-1", type="van", capacity_kg=5000, status="available", driver_id=driver.id, city="تهران")
    db.add(vehicle)
    db.commit()
    product = inventory_service.create_product(db, admin, ProductCreate(
        name="روغن", sku="OIL-1", price=100, initial_quantity=20, warehouse_id=main.id))
    return db, main, quarantine, admin, manager, driver, vehicle, product


def _bucket(db, product_id, warehouse_id, status="available"):
    inv = db.query(Inventory).filter_by(product_id=product_id, warehouse_id=warehouse_id, stock_status=status).first()
    if inv is not None:
        db.refresh(inv)
    return inv


def _receipt(db, user, product, warehouse, qty, **kw):
    return inventory_service.record_movement(db, user, StockMovementCreate(
        product_id=product.id, warehouse_id=warehouse.id, movement_type="receipt", quantity=qty, **kw))


# ---------------------------------------------------------------------------
# ۱. قاعده‌های غیرقابل‌مذاکره
# ---------------------------------------------------------------------------
def test_every_movement_belongs_to_a_posted_document(world):
    db, main, *_ , product = world
    [movement] = db.query(StockMovement).all()
    assert movement.document.doc_type == "opening" and movement.document.status == "posted"
    assert movement.document.code.startswith("OB-")


def test_direct_quantity_edit_is_rejected(world):
    db, main, *_, product = world
    inv = _bucket(db, product.id, main.id)
    inv.quantity = 999
    with pytest.raises(LedgerViolationError):
        db.flush()
    db.rollback()


def test_direct_reservation_edit_is_rejected(world):
    db, main, *_, product = world
    inv = _bucket(db, product.id, main.id)
    inv.reserved_quantity = 5
    with pytest.raises(LedgerViolationError):
        db.flush()
    db.rollback()


def test_movements_and_posted_documents_are_immutable(world):
    db, *_ = world
    movement = db.query(StockMovement).first()
    movement.quantity_change = 1
    with pytest.raises(LedgerViolationError):
        db.flush()
    db.rollback()
    with pytest.raises(LedgerViolationError):
        db.delete(db.query(StockMovement).first())
        db.flush()
    db.rollback()
    document = db.query(StockDocument).first()
    document.note = "بازنویسی"
    with pytest.raises(LedgerViolationError):
        db.flush()
    db.rollback()
    with pytest.raises(LedgerViolationError):
        db.delete(db.query(StockDocument).first())
        db.flush()
    db.rollback()


def test_bucket_identity_cannot_change(world):
    db, main, quarantine, *_, product = world
    inv = _bucket(db, product.id, main.id)
    inv.stock_status = "quarantine"
    with pytest.raises(LedgerViolationError):
        db.flush()
    db.rollback()


def test_sku_is_immutable(world):
    db, main, quarantine, admin, *_, product = world
    with pytest.raises(ConflictError):
        catalog_service.update(db, admin, product.id, {"sku": "OIL-2"})
    product.sku = "OIL-2"
    with pytest.raises(LedgerViolationError):
        db.flush()
    db.rollback()


def test_reversal_neutralises_document_without_deleting_it(world):
    db, main, quarantine, admin, manager, *_, product = world
    movement = _receipt(db, manager, product, main, 5, reason="فاکتور ۱۲")
    assert _bucket(db, product.id, main.id).quantity == 25

    result = stock_document_service.reverse_document(db, manager, movement.document_id, "ثبت اشتباه")
    assert result["doc_type"] == "reversal" and result["reversal_of_id"] == movement.document_id
    [back] = result["movements"]
    assert (back.quantity_change, back.reversal_of_id, back.movement_type) == (-5, movement.id, "receipt")
    assert _bucket(db, product.id, main.id).quantity == 20
    original = db.get(StockDocument, movement.document_id)
    assert original.status == "reversed" and len(original.movements) == 1
    assert stock_ledger.find_mismatches(db) == []

    with pytest.raises(ConflictError):              # هر سند فقط یک‌بار برگشت می‌خورد
        stock_document_service.reverse_document(db, admin, movement.document_id, "دوباره")


def test_order_documents_are_not_user_reversible(world):
    db, main, quarantine, admin, manager, driver, vehicle, product = world
    order = order_service.create_order(db, admin, order_request(product.id, vehicle.id, quantity=2))
    order_service.update_order_status(db, admin, order.id, OrderStatusRequest(order_status="picked_up"))
    issue = db.query(StockDocument).filter_by(doc_type="order_issue").one()
    with pytest.raises(ConflictError, match="مسیر خودش"):
        stock_document_service.reverse_document(db, admin, issue.id, "آزمون برگشت")


def test_reversal_cannot_consume_reserved_stock(world):
    db, main, quarantine, admin, manager, driver, vehicle, product = world
    movement = _receipt(db, admin, product, main, 5)
    order_service.create_order(db, admin, order_request(product.id, vehicle.id, quantity=22))
    with pytest.raises(ConflictError, match="آزاد"):
        stock_document_service.reverse_document(db, admin, movement.document_id, "ثبت اشتباه")
    assert db.get(StockDocument, movement.document_id).status == "posted"


def test_manager_cannot_reverse_cross_warehouse_transfer(world):
    db, main, quarantine, admin, manager, *_, product = world
    other = Warehouse(name="انبار دوم", location="کرج", code="WH-02")
    db.add(other)
    db.commit()
    moves = inventory_service.transfer_stock(db, manager, StockTransferCreate(
        product_id=product.id, from_warehouse_id=main.id, to_warehouse_id=other.id, quantity=3))
    assert moves[0].document_id == moves[1].document_id
    with pytest.raises(ForbiddenError):
        stock_document_service.reverse_document(db, manager, moves[0].document_id, "انتقال اشتباه")
    stock_document_service.reverse_document(db, admin, moves[0].document_id, "انتقال اشتباه")
    assert (_bucket(db, product.id, main.id).quantity, _bucket(db, product.id, other.id).quantity) == (20, 0)


# ---------------------------------------------------------------------------
# ۲. وضعیت کیفی و تخصیص
# ---------------------------------------------------------------------------
def test_receipt_into_quarantine_warehouse_is_held_until_released(world):
    db, main, quarantine, admin, manager, driver, vehicle, product = world
    _receipt(db, admin, product, quarantine, 8)
    held = _bucket(db, product.id, quarantine.id, "quarantine")
    assert held.quantity == 8 and _bucket(db, product.id, quarantine.id) is None

    listed = next(p for p in inventory_service.list_products(db, admin) if p["id"] == product.id)
    assert listed["stock"] == 20 and listed["held_stock"] == {"quarantine": 8}

    doc = inventory_service.change_status(db, admin, StatusChangeCreate(
        product_id=product.id, warehouse_id=quarantine.id, from_status="quarantine", to_status="available",
        quantity=6, reason="بازرسی کیفی تأیید شد"))
    assert doc["doc_type"] == "status_change" and [m.movement_type for m in doc["movements"]] == ["status_out", "status_in"]
    assert (_bucket(db, product.id, quarantine.id, "quarantine").quantity, _bucket(db, product.id, quarantine.id).quantity) == (2, 6)


def test_quarantine_stock_cannot_be_sold(world):
    db, main, quarantine, admin, manager, driver, vehicle, product = world
    _receipt(db, admin, product, main, 10, stock_status="quarantine")
    with pytest.raises(ConflictError):
        order_service.create_order(db, admin, order_request(product.id, vehicle.id, quantity=25))


def test_orders_ship_only_from_shipping_warehouses(world):
    db, main, quarantine, admin, manager, driver, vehicle, product = world
    with pytest.raises(ConflictError, match="ارسال نمی‌شود"):
        order_service.create_order(db, admin, order_request(product.id, vehicle.id, quantity=1, warehouse_id=quarantine.id))


def test_reservation_protects_stock_from_other_exits(world):
    db, main, quarantine, admin, manager, driver, vehicle, product = world
    order_service.create_order(db, admin, order_request(product.id, vehicle.id, quantity=15))
    inv = _bucket(db, product.id, main.id)
    assert (inv.quantity, inv.reserved_quantity, inv.free_quantity) == (20, 15, 5)
    with pytest.raises(ConflictError, match="رزرو"):
        inventory_service.record_movement(db, admin, StockMovementCreate(
            product_id=product.id, warehouse_id=main.id, movement_type="damage", quantity=6, reason="شکستگی"))
    with pytest.raises(ConflictError):
        order_service.create_order(db, admin, order_request(product.id, vehicle.id, quantity=6))
    with pytest.raises(ConflictError):
        allocation_service.reserve(db, inv, 6, reference_type="order", reference_id=999)


def test_stocktake_never_adjusts_below_open_reservations(world):
    db, main, quarantine, admin, manager, driver, vehicle, product = world
    order_service.create_order(db, admin, order_request(product.id, vehicle.id, quantity=12))
    st = stocktake_service.create(db, manager, warehouse_id=main.id, scope="full", product_ids=None, title=None, note=None)
    line = st["lines"][0]
    stocktake_service.count(db, manager, st["id"], line["id"], 4)
    stocktake_service.submit(db, manager, st["id"])
    result = stocktake_service.approve(db, admin, st["id"], {})
    inv = _bucket(db, product.id, main.id)
    assert (inv.quantity, inv.reserved_quantity) == (12, 12)
    assert result["lines"][0]["adjustment"] == -8
    assert db.query(StockDocument).filter_by(doc_type="stocktake").count() == 1


# ---------------------------------------------------------------------------
# ۳. یکتایی درخواست و رویدادها
# ---------------------------------------------------------------------------
def test_idempotency_key_prevents_duplicate_documents(world):
    db, main, quarantine, admin, manager, *_, product = world
    first = inventory_service.record_movement(
        db, admin, StockMovementCreate(product_id=product.id, warehouse_id=main.id, movement_type="receipt", quantity=4),
        idempotency_key="receipt-0001")
    again = inventory_service.record_movement(
        db, admin, StockMovementCreate(product_id=product.id, warehouse_id=main.id, movement_type="receipt", quantity=4),
        idempotency_key="receipt-0001")
    assert first.id == again.id
    assert _bucket(db, product.id, main.id).quantity == 24
    with pytest.raises(IdempotencyConflictError):
        inventory_service.record_movement(
            db, admin, StockMovementCreate(product_id=product.id, warehouse_id=main.id, movement_type="receipt", quantity=9),
            idempotency_key="receipt-0001")


def test_order_idempotency(world):
    db, main, quarantine, admin, manager, driver, vehicle, product = world
    request = order_request(product.id, vehicle.id, quantity=2)
    a = order_service.create_order(db, admin, request, "order-key-0001")
    b = order_service.create_order(db, admin, request, "order-key-0001")
    assert a.id == b.id and db.query(Order).count() == 1
    assert _bucket(db, product.id, main.id).reserved_quantity == 2


def test_events_are_written_in_the_same_transaction(world):
    db, main, quarantine, admin, manager, driver, vehicle, product = world
    order = order_service.create_order(db, admin, order_request(product.id, vehicle.id, quantity=2))
    order_service.update_order_status(db, admin, order.id, OrderStatusRequest(order_status="canceled"))
    types = [e.event_type for e in db.query(DomainEvent).order_by(DomainEvent.id).all()]
    assert types[:4] == ["warehouse.created", "warehouse.created", "product.created", "stock.document.posted"]
    assert "stock.reserved" in types and "stock.reservation.released" in types
    event = db.query(DomainEvent).filter_by(event_type="stock.document.posted").first()
    assert event.payload["lines"][0]["quantity_change"] == 20 and event.payload["doc_type"] == "opening"

    with pytest.raises(LedgerViolationError):
        event.payload = {}
        db.flush()
    db.rollback()


def test_failed_operation_leaves_no_event(world):
    db, main, quarantine, admin, *_, product = world
    before = db.query(DomainEvent).count()
    with pytest.raises(ConflictError):
        inventory_service.record_movement(db, admin, StockMovementCreate(
            product_id=product.id, warehouse_id=main.id, movement_type="damage", quantity=500, reason="آزمون"))
    assert db.query(DomainEvent).count() == before


# ---------------------------------------------------------------------------
# ۴. انواع و سلسله‌مراتب انبار
# ---------------------------------------------------------------------------
def test_warehouse_type_rules(world):
    db, main, quarantine, admin, manager, *_, product = world
    site = Warehouse(name="مجتمع شمال", code="SITE-N", type="site")
    transit = Warehouse(name="در راه", code="WH-T", type="transit")
    db.add_all([site, transit])
    db.commit()
    with pytest.raises(ConflictError, match="کالا نگه نمی‌دارد"):
        _receipt(db, admin, product, site, 1)
    with pytest.raises(ConflictError, match="فقط با سند انتقال"):
        _receipt(db, admin, product, transit, 1)
    inventory_service.transfer_stock(db, admin, StockTransferCreate(
        product_id=product.id, from_warehouse_id=main.id, to_warehouse_id=transit.id, quantity=2))
    assert _bucket(db, product.id, transit.id).quantity == 2


def test_warehouse_hierarchy_rejects_cycles_and_deactivation_with_stock(world):
    db, main, quarantine, *_ = world
    site = Warehouse(name="مجتمع", code="SITE-1", type="site")
    db.add(site)
    db.commit()
    main.parent_id = site.id
    db.commit()
    with pytest.raises(ConflictError, match="زیرمجموعه خودش"):
        warehouse_service.validate(db, {"code": "SITE-1", "type": "site", "parent_id": main.id}, site)
    with pytest.raises(ConflictError, match="موجودی"):
        warehouse_service.validate(db, {"code": "WH-01", "type": "general", "parent_id": site.id, "is_active": False}, main)
    with pytest.raises(ConflictError, match="تکراری"):
        warehouse_service.validate(db, {"code": "wh-q", "type": "general"})
    tree = [w.code for w in warehouse_service.ordered_tree(db.query(Warehouse).all())]
    assert tree.index("SITE-1") + 1 == tree.index("WH-01")      # زیرمجموعه بلافاصله بعد از مادرش
    assert warehouse_service.depth_map(db.query(Warehouse).all())[main.id] == 1


# ---------------------------------------------------------------------------
# ۵. داده پایه کالا
# ---------------------------------------------------------------------------
def test_sku_and_barcode_uniqueness(world):
    db, main, quarantine, admin, *_, product = world
    with pytest.raises(ConflictError):
        inventory_service.create_product(db, admin, ProductCreate(name="دیگر", sku="oil-1", price=1, warehouse_id=main.id))
    inventory_service.create_product(db, admin, ProductCreate(name="الف", sku="A-1", price=1, barcode="6260000000017"))
    with pytest.raises(ConflictError, match="بارکد"):
        inventory_service.create_product(db, admin, ProductCreate(name="ب", sku="B-1", price=1, barcode="6260000000017"))
    with pytest.raises(ConflictError, match="بارکد"):
        catalog_service.set_uoms(db, admin, product.id, [{"name": "کارتن", "factor": 12, "barcode": "6260000000017"}])


def test_master_data_rules_and_uom_conversion(world):
    db, main, quarantine, admin, manager, *_, product = world
    with pytest.raises(ConflictError, match="بچ"):
        catalog_service.update(db, admin, product.id, {"expiry_tracked": True})
    with pytest.raises(ConflictError, match="وزن خالص"):
        catalog_service.update(db, admin, product.id, {"net_weight_kg": 5, "weight_kg": 1})
    with pytest.raises(ConflictError, match="حداکثر"):
        catalog_service.update(db, admin, product.id, {"min_stock": 10, "max_stock": 5})
    detail = catalog_service.update(db, admin, product.id, {"lot_tracked": True, "expiry_tracked": True, "shelf_life_days": 180,
                                                            "length_cm": 20, "width_cm": 10, "height_cm": 30})
    assert detail["volume_m3"] == 0.006 and detail["shelf_life_days"] == 180

    catalog_service.set_uoms(db, admin, product.id, [{"name": "کارتن", "factor": 12, "barcode": "6260000000999"}])
    # کالای بچ‌دار و تاریخ‌دار: رسید بدون بچ/انقضا پذیرفته نمی‌شود
    expiry = catalog_service.today_local() + timedelta(days=180)
    with pytest.raises(ConflictError, match="بچ"):
        inventory_service.record_movement(db, manager, StockMovementCreate(
            product_id=product.id, movement_type="receipt", quantity=3, uom="کارتن"))
    movement = inventory_service.record_movement(db, manager, StockMovementCreate(
        product_id=product.id, movement_type="receipt", quantity=3, uom="کارتن", lot_number="b-1", expiry_date=expiry))
    assert movement.quantity_change == 36 and movement.lines[0].lot_number == "B-1"
    with pytest.raises(ConflictError, match="تعریف نشده"):
        inventory_service.record_movement(db, manager, StockMovementCreate(
            product_id=product.id, movement_type="receipt", quantity=1, uom="پالت", lot_number="B-1", expiry_date=expiry))


def test_product_with_history_is_archived_not_deleted(world):
    db, main, quarantine, admin, *_, product = world
    with pytest.raises(ConflictError, match="بایگانی"):
        inventory_service.delete_product(db, admin, product.id)
    fresh = inventory_service.create_product(db, admin, ProductCreate(name="بی‌سابقه", sku="NEW-1", price=1, warehouse_id=main.id))
    inventory_service.delete_product(db, admin, fresh.id)
    assert db.get(Product, fresh.id) is None


# ---------------------------------------------------------------------------
# جداسازی ارجاع بین سازمان‌ها
# ---------------------------------------------------------------------------
def test_cross_tenant_reference_is_rejected_at_flush(world):
    db, main, quarantine, admin, *_, product = world
    other = Organization(name="دیگری", slug="other-org")
    db.add(other)
    db.commit()
    set_tenant(db, other.id)
    foreign_wh = Warehouse(name="انبار دیگری", code="WH-01")
    db.add(foreign_wh)
    db.commit()
    foreign_id = foreign_wh.id
    set_tenant(db, admin.organization_id)

    db.add(Inventory(product_id=product.id, warehouse_id=foreign_id, quantity=0))
    with pytest.raises(TenantIsolationError):
        db.flush()
    db.rollback()

    reservation_inv = _bucket(db, product.id, main.id)
    db.add(StockReservation(inventory_id=reservation_inv.id, product_id=product.id, warehouse_id=foreign_id, quantity=1,
                            reference_type="order", reference_id=1))
    with pytest.raises(TenantIsolationError):
        db.flush()
    db.rollback()
