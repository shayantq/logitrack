"""داده آزمون مشترک عملیات انبار: یک انبار با محل تخلیه، دو خانه نگهداری در یک منطقه، محل قرنطینه، انبار در راه،
تأمین‌کننده، مالک امانی، خودرو و کالای ۲۰ عددی «بدون محل»."""
from app.models import Partner, RoleEnum, User, Vehicle, Warehouse
from app.schemas.product import ProductCreate
from app.services import inventory_service, location_service


def make_user(db, role, name, **kw):
    user = User(username=name, email=f"{name}@t.local", role=role, hashed_password="x", **kw)
    db.add(user)
    db.commit()
    return user


def make_location(db, user, warehouse, code, level="bin", location_type="storage", parent=None, **kw):
    return location_service.create_location(db, user, warehouse.id, {
        "code": code, "level": level, "location_type": location_type, "parent_id": parent["id"] if parent else None,
        "allow_mixed_products": True, "allow_mixed_lots": True, "allow_mixed_owners": True, "is_active": True,
        "is_blocked": False, **kw})


def build_site(db):
    main = Warehouse(name="انبار اصلی", location="تهران", province="تهران", city="تهران", code="WH-01")
    transit = Warehouse(name="در راه", location="تهران", province="تهران", city="تهران", code="WH-T", type="transit")
    db.add_all([main, transit])
    db.commit()
    admin = make_user(db, RoleEnum.ORG_ADMIN, "admin")
    manager = make_user(db, RoleEnum.WAREHOUSE_MANAGER, "mgr", warehouse_id=main.id)
    driver = make_user(db, RoleEnum.DRIVER, "drv", city="تهران")
    vehicle = Vehicle(license_plate="W-1", type="van", capacity_kg=5000, status="available", driver_id=driver.id, city="تهران")
    supplier = Partner(code="SUP-001", name="تأمین‌کننده نمونه", is_supplier=True)
    owner = Partner(code="OWN-001", name="مالک امانی", is_owner=True)
    db.add_all([vehicle, supplier, owner])
    db.commit()
    product = inventory_service.create_product(db, admin, ProductCreate(
        name="روغن", sku="OIL-1", barcode="6260000000011", price=100, weight_kg=2, length_cm=10, width_cm=10, height_cm=10,
        units_per_pallet=10, initial_quantity=20, warehouse_id=main.id))
    zone = make_location(db, admin, main, "A", level="zone")
    locs = {
        "rcv": make_location(db, admin, main, "RCV", location_type="receiving"),
        "a1": make_location(db, admin, main, "A-01", parent=zone),
        "a2": make_location(db, admin, main, "A-02", parent=zone),
        "q1": make_location(db, admin, main, "Q-01", location_type="quarantine"),
        "zone": zone,
    }
    return {"db": db, "main": main, "transit": transit, "admin": admin, "manager": manager, "vehicle": vehicle,
            "supplier": supplier, "owner": owner, "product": product, "loc": locs}
