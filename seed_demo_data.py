"""
اسکریپت آماده‌سازی داده‌های نمونه (نسخه گسترده) برای پسینه
شامل:
  • کارکنان پلتفرم: ادمین پلتفرم و پشتیبان (بدون سازمان)
  • «سازمان پیش‌فرض»: انبارها، ادمین سازمان، مدیران انبار، رانندگان، خودروها،
    حدود ۵۵ کالا با وضعیت‌های موجودی متنوع و حدود ۲۵ سفارش نمونه
  • سازمان دوم «فروشگاه نمونه قزوین» با داده‌های کاملاً جدا — برای دیدن
    جداسازی سازمان‌ها (حتی کدهای کالای یکسان SKU-001 و ...)

این اسکریپت idempotent است — اجرای چندباره‌اش خطا نمی‌دهد و رکورد تکراری نمی‌سازد.

نحوه اجرا (داخل کانتینر داکر):
    docker compose exec web python seed_demo_data.py
"""

from datetime import datetime, timedelta, timezone

from app.database import SessionLocal
from app.core import geo
from app.services import route_service
from app.models import ProductPrice, Stocktake, StocktakeLine, Ticket, TicketMessage, OrderCheckpoint, Customer, DriverInvite, DriverProfile, DriverShift, DriverTimeOff, OrderItem, OrderStatusHistory, Organization, OrganizationRequest, User, RoleEnum, Warehouse, Vehicle, Product, Inventory, Order
from app.core.security import bcrypt_context
from app.core.tenancy import SKIP_TENANT_FILTER, set_tenant
from app.services import allocation_service, order_service, stock_ledger, warehouse_service

db = SessionLocal()


def get_or_create_org(slug, name):
    org = db.query(Organization).filter(Organization.slug == slug).first()
    if org:
        return org
    org = Organization(name=name, slug=slug, is_active=True)
    db.add(org)
    db.commit()
    db.refresh(org)
    print(f"✅ سازمان ساخته شد: {name} ({slug})")
    return org


def get_or_create_warehouse(name, location):
    city = geo.find_city(location)
    wh = db.query(Warehouse).filter(Warehouse.name == name).first()
    if wh:
        if city and not wh.city:          # انبارهای قدیمی: شهر و استان برای نقشه (مرحله ۱۰)
            wh.province, wh.city = city.province, city.name
            db.commit()
        return wh
    wh = Warehouse(name=name, location=location, province=city.province if city else None, city=city.name if city else None,
                   code=warehouse_service.next_code(db))
    db.add(wh)
    db.commit()
    db.refresh(wh)
    print(f"✅ انبار ساخته شد: {name}")
    return wh


def get_or_create_user(username, email, password, role, full_name=None, city=None, warehouse_id=None):
    # نام کاربری در کل پلتفرم یکتاست — جستجو بین همه سازمان‌ها
    user = db.query(User).filter(User.username == username).execution_options(**SKIP_TENANT_FILTER).first()
    if user:
        return user
    user = User(
        username=username, email=email,
        hashed_password=bcrypt_context.hash(password),
        role=role, full_name=full_name, city=city, warehouse_id=warehouse_id
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    if role == RoleEnum.DRIVER:
        user.driver_code = f"DRV-{user.id:04d}"
        db.commit()
    print(f"✅ کاربر ساخته شد: {username} / رمز: {password} ({role.value})")
    return user


def get_or_create_vehicle(license_plate, name, vtype, capacity, vstatus, driver_id, city):
    v = db.query(Vehicle).filter(Vehicle.license_plate == license_plate).first()
    if v:
        return v
    v = Vehicle(
        license_plate=license_plate, model=name, type=vtype, capacity_kg=capacity,
        status=vstatus, driver_id=driver_id, city=city
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    print(f"✅ خودرو ساخته شد: {name} ({license_plate})")
    return v


def get_or_create_product(name, sku, price, weight_kg=1.0):
    p = db.query(Product).filter(Product.sku == sku).first()
    if p:
        return p
    p = Product(name=name, sku=sku, price=price, weight_kg=weight_kg)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def get_or_create_inventory(product_id, warehouse_id, quantity, ever_high_override=None, reorder_point=10):
    inv = db.query(Inventory).filter(
        Inventory.product_id == product_id,
        Inventory.warehouse_id == warehouse_id
    ).first()
    if inv:
        return inv
    ever_high = quantity > reorder_point if ever_high_override is None else ever_high_override
    inv = Inventory(
        product_id=product_id, warehouse_id=warehouse_id, quantity=quantity,
        reorder_point=reorder_point, ever_exceeded_reorder=ever_high
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv


CITY_PROVINCE = {
    "تهران": "تهران", "تبریز": "آذربایجان شرقی", "مشهد": "خراسان رضوی", "اصفهان": "اصفهان", "شیراز": "فارس",
    "کرج": "البرز", "اهواز": "خوزستان", "قم": "قم", "رشت": "گیلان", "قزوین": "قزوین", "تاکستان": "قزوین", "آبیک": "قزوین",
}
DEMO_CUSTOMERS = [
    ("امیرحسین رضایی", "09121110001"), ("نگار احمدی", "09121110002"), ("بهرام صادقی", "09121110003"),
    ("سحر موسوی", "09121110004"), ("کاوه اکبری", "09121110005"), ("مینا کریمی", "09121110006"),
]


def create_demo_order(org_id, items, status, city, vehicle, warehouse_id, days_ago, customer, priority=False, size="m"):
    """
    یک سفارش نمونه کامل (اقلام، مشتری، آدرس، تاریخچه، گردش کالا) — همان ساختاری که
    order_service می‌سازد. items = [(product, inventory, quantity), ...]
    """
    name, mobile = customer
    cust = db.query(Customer).filter(Customer.mobile == mobile).first()
    if cust is None:
        cust = Customer(organization_id=org_id, name=name, mobile=mobile)
        db.add(cust)
        db.flush()
    start = datetime.now(timezone.utc) - timedelta(days=days_ago)
    order = Order(
        organization_id=org_id, tracking_code=order_service._new_tracking_code(db), status=status, size=size,
        priority=priority, delivery_window_start=start, delivery_window_end=start + timedelta(hours=6),
        customer_id=cust.id, recipient_name=cust.name, recipient_mobile=cust.mobile,
        destination_province=CITY_PROVINCE.get(city), destination_city=city,
        destination_address=f"{city}، خیابان نمونه، پلاک {days_ago + 1}",
        warehouse_id=warehouse_id, vehicle_id=vehicle.id if vehicle and status != "pending" else None,
        driver_id=vehicle.driver_id if vehicle and status != "pending" else None,
        total_quantity=sum(q for _, _, q in items),
        total_weight_kg=sum((p.weight_kg or 0) * q for p, _, q in items),
        total_price=sum((p.price or 0) * q for p, _, q in items),
    )
    db.add(order)
    for product, _, qty in items:
        order.items.append(OrderItem(organization_id=org_id, product_id=product.id, product_name=product.name,
                                     product_sku=product.sku, quantity=qty, unit_price=product.price or 0,
                                     unit_weight_kg=product.weight_kg or 0))
    db.flush()
    # همان چرخه order_service: ثبت = رزرو، بارگیری = حواله خروج، لغو/انقضا قبل از بارگیری = آزادسازی،
    # عدم تحویل بعد از بارگیری = سند برگشت
    reservations = [allocation_service.reserve(db, inv, qty, reference_type="order", reference_id=order.id)
                    for _, inv, qty in items]
    order.stock_state = "reserved"
    if status in ("canceled", "expired"):
        for r in reservations:
            allocation_service.release(db, r, reason=f"سفارش نمونه {order.tracking_code}")
        order.stock_state = "released"
    elif status not in ("pending", "assigned"):
        issue = stock_ledger.new_document(db, "order_issue", organization_id=org_id, warehouse_id=warehouse_id,
                                          reference_type="order", reference_id=order.id)
        for r in reservations:
            allocation_service.consume(db, r, issue, reason=f"خروج بابت سفارش نمونه {order.tracking_code}")
        order.stock_state = "issued"
    db.add(OrderStatusHistory(organization_id=org_id, order=order, from_status=None,
                              to_status="pending" if status == "pending" else "assigned", note="ثبت سفارش نمونه",
                              changed_at=start - timedelta(hours=2)))
    if status not in ("pending", "assigned"):
        db.add(OrderStatusHistory(organization_id=org_id, order=order, from_status="assigned", to_status=status,
                                  note="وضعیت نمونه", changed_at=start))
    if status == "failed":
        back = stock_ledger.new_document(db, "order_return", organization_id=org_id, warehouse_id=warehouse_id,
                                         reference_type="order", reference_id=order.id)
        for _, inv, qty in items:
            stock_ledger.record(db, inv, qty, "order_return", document=back, reason=f"برگشت سفارش نمونه {order.tracking_code}",
                                reference_type="order", reference_id=order.id)
        order.stock_state = "returned"
    return order


print("===== ۰. کارکنان پلتفرم پسینه (بدون سازمان) =====")
set_tenant(db, None)
get_or_create_user("superadmin", "superadmin@pasineh.local", "superadmin123", RoleEnum.PLATFORM_ADMIN, full_name="ادمین پلتفرم")
get_or_create_user("support", "support@pasineh.local", "support123", RoleEnum.PLATFORM_SUPPORT, full_name="پشتیبان پلتفرم")

print("===== سازمان اول: سازمان پیش‌فرض =====")
default_org = get_or_create_org("default", "سازمان پیش‌فرض")
# از اینجا به بعد هر رکوردی ساخته شود خودکار به این سازمان تعلق می‌گیرد
set_tenant(db, default_org.id)

print("===== ۱. انبارها =====")
wh_tehran = get_or_create_warehouse("انبار مرکزی تهران", "تهران")
wh_tabriz = get_or_create_warehouse("انبار تبریز", "تبریز")
wh_mashhad = get_or_create_warehouse("انبار مشهد", "مشهد")
warehouses = [wh_tehran, wh_tabriz, wh_mashhad]

print("===== ۲. ادمین =====")
admin = get_or_create_user("admin", "admin@pasineh.local", "admin123", RoleEnum.ORG_ADMIN, full_name="مدیر ارشد سیستم")

print("===== ۳. مدیران انبار (۳ نفر) =====")
mgr_tehran = get_or_create_user("manager_tehran", "manager.tehran@pasineh.local", "manager123", RoleEnum.WAREHOUSE_MANAGER, full_name="کیانوش رادفر", warehouse_id=wh_tehran.id)
mgr_tabriz = get_or_create_user("manager_tabriz", "manager.tabriz@pasineh.local", "manager123", RoleEnum.WAREHOUSE_MANAGER, full_name="پریسا امینی", warehouse_id=wh_tabriz.id)
mgr_mashhad = get_or_create_user("manager_mashhad", "manager.mashhad@pasineh.local", "manager123", RoleEnum.WAREHOUSE_MANAGER, full_name="سعید طاهری", warehouse_id=wh_mashhad.id)

print("===== ۴. رانندگان (۱۲ نفر، با نام کامل و شهر) =====")
drivers_data = [
    ("driver_ali", "علی رضایی", "تهران"),
    ("driver_reza", "رضا احمدی", "تبریز"),
    ("driver_sara", "سارا محمدی", "مشهد"),
    ("driver_hossein", "حسین کریمی", "تهران"),
    ("driver_maryam", "مریم حسینی", "اصفهان"),
    ("driver_amir", "امیر نوروزی", "شیراز"),
    ("driver_zahra", "زهرا صادقی", "تبریز"),
    ("driver_mohammad", "محمد قاسمی", "کرج"),
    ("driver_fateme", "فاطمه رحیمی", "مشهد"),
    ("driver_hamed", "حامد یوسفی", "اهواز"),
    ("driver_narges", "نرگس جعفری", "قم"),
    ("driver_babak", "بابک شریفی", "رشت"),
]
drivers = []
for username, full_name, city in drivers_data:
    d = get_or_create_user(username, f"{username}@pasineh.local", "driver123", RoleEnum.DRIVER, full_name=full_name, city=city)
    drivers.append(d)

print("===== ۵. خودروها (یکی برای هر راننده، با نام واقعی خودرو) =====")
vehicles_data = [
    ("۱۲ایران۳۴۵ب۶۷", "پژو ۴۰۵", "sedan", 400, "available"),
    ("۲۲ایران۹۸۷ج۱۲", "کامیون بنز اکتروس", "truck", 12000, "available"),
    ("۳۳ایران۵۵۵د۹۹", "وانت نیسان زامیاد", "pickup", 1500, "available"),
    ("۴۴ایران۱۱۱الف۲۲", "ون هیوندای اچ۱", "van", 1200, "on_route"),
    ("۵۵ایران۷۷۷ب۸۸", "پراید صندوق‌دار", "sedan", 300, "available"),
    ("۶۶ایران۲۲۲ج۳۳", "کامیونت خاور ۹۱۱", "truck", 6000, "maintenance"),
    ("۷۷ایران۹۹۹د۴۴", "وانت مزدا تیتان", "pickup", 2000, "available"),
    ("۸۸ایران۳۳۳الف۵۵", "ون تویوتا هایس", "van", 1300, "available"),
    ("۹۹ایران۶۶۶ب۷۷", "کامیون ولوو FH", "truck", 15000, "available"),
    ("۱۰ایران۴۴۴ج۸۸", "موتورسیکلت هوندا ۱۲۵", "motorcycle", 50, "available"),
    ("۱۱ایران۸۸۸د۹۹", "سمند سورن", "sedan", 350, "inactive"),
    ("۱۳ایران۲۲۲الف۱۱", "وانت فوتون", "pickup", 1800, "available"),
]
vehicles = []
for (plate, name, vtype, capacity, vstatus), driver in zip(vehicles_data, drivers, strict=False):
    v = get_or_create_vehicle(plate, name, vtype, capacity, vstatus, driver.id, driver.city)
    vehicles.append(v)

print("===== ۶. کالاها (~۵۵ قلم) با موجودی متنوع در انبارهای مختلف =====")
product_names = [
    "کارتن بسته‌بندی لوازم خانگی", "کیسه سیمان ۵۰ کیلویی", "جعبه میوه پلاستیکی",
    "پالت چوبی استاندارد", "نایلون حبابدار بسته‌بندی", "چسب پهن صنعتی",
    "کارتن مقوایی سایز بزرگ", "کارتن مقوایی سایز کوچک", "طناب بسته‌بندی",
    "جعبه فلزی ابزار", "بشکه پلاستیکی ۲۰۰ لیتری", "گونی برنج ۱۰ کیلویی",
    "کیسه نایلون صنعتی", "قفل و زنجیر بسته‌بندی", "برچسب بارکد کالا",
    "جعبه چوبی نوشیدنی", "سبد پلاستیکی حمل بار", "کارتن لوازم الکترونیکی",
    "پک ایمنی جاده‌ای", "چادر برزنتی کامیون", "تسمه بسته‌بندی فلزی",
    "کیسه کود شیمیایی ۲۵ کیلویی", "جعبه دارویی سرد", "بطری آب معدنی ۱۹ لیتری",
    "کارتن لوازم آرایشی", "کیسه برنج ۵ کیلویی", "جعبه چای خشک",
    "گونی گندم ۵۰ کیلویی", "کارتن قطعات خودرو", "پالت پلاستیکی سبک",
    "کیسه شکر ۵۰ کیلویی", "کارتن پوشاک زمستانی", "کارتن پوشاک تابستانی",
    "جعبه اسباب‌بازی", "کارتن کتاب و نشریات", "بسته نایلون کشاورزی",
    "کیسه کود آلی", "جعبه سرامیک و ظروف", "کارتن مواد غذایی خشک",
    "بشکه روغن موتور", "گالن ۲۰ لیتری روغن", "کارتن لوازم بهداشتی",
    "جعبه یخچالی گوشت منجمد", "کارتن نوشابه", "پک بطری آب معدنی کوچک",
    "کیسه آرد ۲۵ کیلویی", "جعبه تخم‌مرغ", "کارتن میوه خشک",
    "گونی حبوبات", "کارتن ادویه‌جات", "جعبه چوبی انگور",
    "پالت فلزی سنگین", "کارتن لوازم التحریر", "جعبه کفش",
    "کارتن کیف و ساک", "بسته نایلون گلخانه‌ای", "جعبه گل و گیاه",
]

products = []
for i, name in enumerate(product_names):
    sku = f"SKU-{i + 1:03d}"
    price = 20000 + (i * 3750) % 500000
    weight = round(0.5 + (i % 12) * 3.7, 1)
    product = get_or_create_product(name, sku, price, weight)
    products.append(product)

    warehouse = warehouses[i % 3]
    bucket = i % 10
    if bucket == 0:
        qty, ever_high = 0, False          # ناموجود، از اول هم کم بوده
    elif bucket == 1:
        qty, ever_high = 0, True           # ناموجود، ولی قبلاً موجودی بالا داشته
    elif bucket in (2, 3):
        qty, ever_high = 3 + (i % 8), True  # رو به اتمام، قبلاً بیشتر از ۱۰ بوده
    elif bucket == 4:
        qty, ever_high = 5, False          # رو به اتمام، ولی از اول هم بیشتر از ۱۰ نشده
    else:
        qty, ever_high = 20 + (i * 7) % 300, True  # موجودی عادی

    get_or_create_inventory(product.id, warehouse.id, qty, ever_high_override=ever_high)

print("===== ۷. سفارش‌های نمونه (~۲۵ سفارش با وضعیت‌های مختلف) =====")
destinations = ["تهران", "تبریز", "مشهد", "اصفهان", "شیراز", "کرج", "اهواز", "قم", "رشت"]
sizes = ["xs", "s", "m", "l", "xl"]
statuses = ["pending", "in_transit", "delivered", "failed", "assigned", "picked_up", "canceled"]

if db.query(Order).count() == 0:
    # کالاهایی که موجودی کافی برای سفارش نمونه دارند (برای جلوگیری از منفی شدن موجودی)
    healthy_products = [p for p in products if db.query(Inventory).filter(Inventory.product_id == p.id, Inventory.quantity > 20).first()]

    order_count = 0
    for i in range(25):
        product = healthy_products[i % len(healthy_products)]
        vehicle = vehicles[i % len(vehicles)]
        inv = db.query(Inventory).filter(Inventory.product_id == product.id).first()
        qty = min(3 + (i % 5), max(inv.free_quantity - 5, 1))
        # سفارش‌های فعال جدیدتر، سفارش‌های تمام‌شده قدیمی‌تر
        status = statuses[i % len(statuses)]
        create_demo_order(default_org.id, [(product, inv, qty)], status, destinations[i % len(destinations)],
                          vehicle, inv.warehouse_id, days_ago=(0 if status in ("pending", "assigned", "in_transit", "picked_up") else 25 - i),
                          customer=DEMO_CUSTOMERS[i % len(DEMO_CUSTOMERS)], priority=(i % 4 == 0), size=sizes[i % len(sizes)])
        order_count += 1

    db.commit()
    print(f"✅ {order_count} سفارش نمونه ساخته شد.")
else:
    print("📦 سفارش از قبل در دیتابیس وجود دارد — از ساخت سفارش نمونه صرف‌نظر شد.")

print("===== سازمان دوم: فروشگاه نمونه قزوین (داده‌های کاملاً جدا) =====")
qazvin = get_or_create_org("qazvin-shop", "فروشگاه نمونه قزوین")
set_tenant(db, qazvin.id)

wh_qazvin = get_or_create_warehouse("انبار مرکزی قزوین", "قزوین")
get_or_create_user("qazvin_admin", "qazvin.admin@pasineh.local", "admin123", RoleEnum.ORG_ADMIN, full_name="مدیر فروشگاه قزوین")
get_or_create_user("qazvin_manager", "qazvin.manager@pasineh.local", "manager123", RoleEnum.WAREHOUSE_MANAGER,
                   full_name="نیما کاظمی", warehouse_id=wh_qazvin.id)
q_driver1 = get_or_create_user("qazvin_driver1", "qazvin.driver1@pasineh.local", "driver123", RoleEnum.DRIVER, full_name="مهدی صالحی", city="قزوین")
q_driver2 = get_or_create_user("qazvin_driver2", "qazvin.driver2@pasineh.local", "driver123", RoleEnum.DRIVER, full_name="لیلا مرادی", city="تهران")
q_vehicles = [
    get_or_create_vehicle("۲۹ایران۴۵۱ق۷۱", "وانت پیکان", "pickup", 1200, "available", q_driver1.id, "قزوین"),
    get_or_create_vehicle("۲۹ایران۸۸۲ق۷۱", "موتورسیکلت باکسر", "motorcycle", 40, "available", q_driver2.id, "تهران"),
]

q_products = []
for i, (name, price, weight, qty) in enumerate([
    ("برنج ایرانی ۱۰ کیلویی", 1850000, 10.0, 80), ("روغن مایع ۴ لیتری", 620000, 4.0, 45),
    ("چای سیاه ۵۰۰ گرمی", 390000, 0.5, 120), ("شکر ۵ کیلویی", 410000, 5.0, 8),
    ("ماکارونی ۷۰۰ گرمی", 95000, 0.7, 200), ("رب گوجه ۸۰۰ گرمی", 135000, 0.8, 0),
    ("حبوبات مخلوط ۱ کیلویی", 260000, 1.0, 60), ("پنیر ۴۰۰ گرمی", 175000, 0.4, 35),
], start=1):
    # کدهای کالا عمداً همان SKU-001 تا SKU-008 سازمان اول است — یکتایی SKU فقط داخل هر سازمان است
    product = get_or_create_product(name, f"SKU-{i:03d}", price, weight)
    get_or_create_inventory(product.id, wh_qazvin.id, qty, ever_high_override=qty > 10 or name.startswith("شکر"))
    q_products.append(product)

if db.query(Order).count() == 0:
    q_customers = [("رضا قزوینی", "09191110001"), ("الهام تاکستانی", "09191110002"), ("مجید آبیکی", "09191110003")]
    for i, (destination, status) in enumerate([
        ("قزوین", "pending"), ("تاکستان", "in_transit"), ("تهران", "delivered"),
        ("قزوین", "assigned"), ("آبیک", "delivered"),
    ]):
        # سفارش اول دوقلمی است (برنج + روغن)
        picks = [q_products[i], q_products[(i + 1) % len(q_products)]] if i == 0 else [q_products[i]]
        items = [(p, db.query(Inventory).filter(Inventory.product_id == p.id).first(), 2) for p in picks]
        create_demo_order(qazvin.id, items, status, destination, q_vehicles[i % 2], wh_qazvin.id,
                          days_ago=0 if status in ("pending", "assigned", "in_transit") else 5 - i,
                          customer=q_customers[i % len(q_customers)], priority=(i == 0))
    db.commit()
    print("✅ ۵ سفارش نمونه برای فروشگاه قزوین ساخته شد.")

print("===== پروفایل سازمان‌ها و درخواست‌های نمونه (مرحله ثبت سازمان) =====")
set_tenant(db, None)


def fill_profile_if_empty(org, **profile):
    if org.national_id:
        return
    for field, value in profile.items():
        setattr(org, field, value)
    db.commit()
    print(f"✅ پروفایل سازمان تکمیل شد: {org.name}")


fill_profile_if_empty(
    db.get(Organization, default_org.id),
    legal_name="شرکت لجستیک نمونه (سهامی خاص)", business_type="wholesale", national_id="10100000001",
    economic_code="10100000001", province="تهران", city="تهران", address="تهران، خیابان ولیعصر، پلاک ۱۰۰",
    postal_code="1415600000", phone="02188990011", employee_count="51-200", monthly_order_volume="1000-10000",
    warehouse_count=3, fleet_size=12, contact_name="مدیر ارشد سیستم", contact_mobile="09120000001",
    contact_email="admin@pasineh.local",
)
fill_profile_if_empty(
    db.get(Organization, qazvin.id),
    legal_name="فروشگاه زنجیره‌ای نمونه قزوین", business_type="retail", national_id="10100000002",
    province="قزوین", city="قزوین", address="قزوین، خیابان پیروزی، پلاک ۱۲", postal_code="3415100000",
    phone="02833334444", employee_count="11-50", monthly_order_volume="100-1000",
    warehouse_count=1, fleet_size=2, contact_name="مدیر فروشگاه قزوین", contact_mobile="09120000002",
    contact_email="qazvin.admin@pasineh.local",
)

if db.query(OrganizationRequest).count() == 0:
    db.add_all([
        OrganizationRequest(
            tracking_code="REQ-DEMO0001", status="pending", name="داروخانه‌های زنجیره‌ای سلامت",
            legal_name="شرکت توزیع دارویی سلامت پارس", business_type="healthcare", national_id="10100000003",
            province="اصفهان", city="اصفهان", address="اصفهان، خیابان چهارباغ، ساختمان سلامت",
            employee_count="201-1000", monthly_order_volume="10000+", warehouse_count=4, fleet_size=30,
            requested_features=["transport", "warehouse", "stocktaking", "reports"],
            contact_name="دکتر سمیرا نادری", contact_mobile="09130000003", contact_email="naderi@example.com",
            notes="به انبارگردانی ماهانه و زنجیره سرد برای داروها نیاز داریم.",
            referral_source="referral", referral_detail="شرکت پخش البرز",
        ),
        OrganizationRequest(
            tracking_code="REQ-DEMO0002", status="pending", name="فروشگاه اینترنتی کالا‌کده",
            legal_name="شرکت تجارت الکترونیک کالاکده", business_type="ecommerce", national_id="10100000004",
            province="فارس", city="شیراز", address="شیراز، بلوار چمران، پلاک ۴۵",
            employee_count="11-50", monthly_order_volume="1000-10000", warehouse_count=1, fleet_size=0,
            requested_features=["transport", "api"],
            contact_name="رضا کاظمی", contact_mobile="09170000004", contact_email="kazemi@example.com",
            referral_source="instagram",
        ),
    ])
    db.commit()
    print("✅ دو درخواست نمونه در انتظار بررسی ساخته شد (REQ-DEMO0001، REQ-DEMO0002).")
# درخواست‌های نمونه قدیمی‌تر: منبع آشنایی برای نمایش خلاصه «از کجا آشنا شدند» در پنل پلتفرم
for _code, _src, _detail in (("REQ-DEMO0001", "referral", "شرکت پخش البرز"), ("REQ-DEMO0002", "instagram", None)):
    _req = db.query(OrganizationRequest).filter(OrganizationRequest.tracking_code == _code).first()
    if _req is not None and _req.referral_source is None:
        _req.referral_source, _req.referral_detail = _src, _detail
db.commit()

print("===== برنامه کاری رانندگان (مرحله زمان‌بندی) =====")
from datetime import time as _time  # noqa: E402

# weekday پایتون: شنبه=۵، یکشنبه=۶، دوشنبه=۰، سه‌شنبه=۱، چهارشنبه=۲، پنجشنبه=۳
FULL_TIME = [(d, 8, 17) for d in (5, 6, 0, 1, 2)] + [(3, 8, 13)]
PART_TIME = [(d, 14, 20) for d in (5, 0, 2)]


def seed_schedule(org_id, driver, shifts, employment="full_time", intercity=False, max_daily=None):
    set_tenant(db, org_id)
    if db.query(DriverShift).filter(DriverShift.user_id == driver.id).first():
        return
    profile = db.query(DriverProfile).filter(DriverProfile.user_id == driver.id).first()
    if profile is None:
        profile = DriverProfile(user_id=driver.id)
        db.add(profile)
    profile.employment_type, profile.intercity, profile.max_daily_orders = employment, intercity, max_daily
    for weekday, start, end in shifts:
        db.add(DriverShift(user_id=driver.id, weekday=weekday, start_time=_time(start), end_time=_time(end)))
    db.commit()


default_org = db.query(Organization).filter(Organization.slug != "qazvin-shop").order_by(Organization.id).first()
for i, (driver, vehicle) in enumerate(zip(drivers, vehicles, strict=False)):
    part_time = i % 4 == 3
    seed_schedule(default_org.id, driver, PART_TIME if part_time else FULL_TIME, "part_time" if part_time else "full_time",
                  intercity=vehicle.type in ("truck", "van"), max_daily=4 if part_time else 8)
set_tenant(db, default_org.id)
if not db.query(DriverTimeOff).first():
    start = datetime.now(timezone.utc).replace(tzinfo=None, hour=20, minute=30, second=0, microsecond=0) + timedelta(days=2)
    db.add(DriverTimeOff(user_id=drivers[3].id, starts_at=start, ends_at=start + timedelta(days=2), reason="مرخصی استحقاقی"))
    db.commit()
seed_schedule(qazvin.id, q_driver1, FULL_TIME, intercity=True, max_daily=8)
seed_schedule(qazvin.id, q_driver2, PART_TIME, "part_time", max_daily=4)
print("✅ شیفت‌های هفتگی، نوع همکاری، سقف روزانه و یک مرخصی نمونه ثبت شد.")
set_tenant(db, None)

print("===== عملکرد رانندگان: تسویه پورسانت و امتیازهای نمونه (مرحله ۸) =====")
# سفارش‌های نمونه قدیمی که راننده‌شان ثبت نشده بود ← راننده خودرو
for _o in db.query(Order).filter(Order.driver_id.is_(None), Order.vehicle_id.isnot(None)).execution_options(**SKIP_TENANT_FILTER).all():
    _v = db.get(Vehicle, _o.vehicle_id)
    _o.driver_id = _v.driver_id if _v else None
db.commit()
import random as _random  # noqa: E402
from app.models import DriverRating  # noqa: E402
from app.services import commission_service  # noqa: E402

_rng = _random.Random(8)
for _org in db.query(Organization).order_by(Organization.id).all():
    set_tenant(db, _org.id)
    pending = db.query(Order).filter(Order.status == "delivered", Order.commission_amount.is_(None)) \
        .order_by(Order.delivered_at, Order.id).all()
    for _order in pending:   # سفارش‌های نمونه قدیمی: تسویه با قانون پیش‌فرض و زمان تحویل خودشان
        commission_service.settle_delivery(db, _order, now=_order.delivered_at or _order.updated_at)
        db.flush()
    if pending and not db.query(DriverRating).first():
        for _order in pending:
            if _order.driver_id and _rng.random() < 0.8:
                db.add(DriverRating(order_id=_order.id, driver_id=_order.driver_id, source="organization",
                                    score=_rng.choice([3, 4, 4, 5, 5, 5])))
            if _order.driver_id and _rng.random() < 0.5:
                db.add(DriverRating(order_id=_order.id, driver_id=_order.driver_id, source="customer",
                                    score=_rng.choice([2, 4, 5, 5, 5]), comment=_rng.choice([None, "خیلی مؤدب بود", "به‌موقع رسید", "کمی دیر رسید"])))
    db.commit()
    if pending:
        print(f"✅ {_org.name}: {len(pending)} سفارش تحویل‌شده تسویه شد و امتیاز نمونه ثبت شد.")
set_tenant(db, None)

print("===== مسیر سفارش‌های در راه روی نقشه (مرحله ۱۰) =====")
# سفارش‌های «در مسیر» نمونه: چند ساعت پیش حرکت کرده‌اند و راننده رسیدن به چند شهر را گزارش داده است
_moving = db.query(Order).filter(Order.status == "in_transit").execution_options(**SKIP_TENANT_FILTER).order_by(Order.id).all()
_routed = 0
for _i, _order in enumerate(_moving):
    set_tenant(db, _order.organization_id)
    if _order.route is not None or db.query(OrderCheckpoint).filter(OrderCheckpoint.order_id == _order.id).first():
        continue
    _hours = 2 + (_i % 4) * 1.5
    _departed = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=_hours)
    _history = db.query(OrderStatusHistory).filter(OrderStatusHistory.order_id == _order.id,
                                                   OrderStatusHistory.to_status == "in_transit").first()
    if _history:
        _history.changed_at = _departed
    route_service.freeze_route(db, _order)
    if _order.route:
        _reachable = geo.AVERAGE_SPEED_KMH * (_hours - 0.4)
        for _p in _order.route["points"][1:-1]:
            if _p["km"] > _reachable:
                break
            db.add(OrderCheckpoint(organization_id=_order.organization_id, order_id=_order.id, seq=_p["seq"],
                                   city=_p["label"], province=_p["province"], reported_by_id=_order.driver_id,
                                   reached_at=_departed + timedelta(hours=_p["km"] / geo.AVERAGE_SPEED_KMH)))
        _routed += 1
    db.commit()
set_tenant(db, None)
print(f"✅ مسیر {_routed} سفارش در راه ثبت شد.")

print("===== تیکت‌های پشتیبانی نمونه (مرحله ۱۱) =====")
if not db.query(Ticket).execution_options(**SKIP_TENANT_FILTER).first():
    import secrets as _secrets
    _now = datetime.now(timezone.utc).replace(tzinfo=None)

    def _ticket(org_id, code, subject, category, source, handler, waiting, messages, order=None, requester=None,
                customer=None, priority="normal", escalated=None, hours_ago=3):
        t = Ticket(organization_id=org_id, code=code, subject=subject, category=category, source=source, handler=handler,
                   status="open", waiting_on=waiting, priority=priority, order_id=order.id if order else None,
                   requester_user_id=requester.id if requester else None,
                   requester_name=(customer or (requester.full_name if requester else None)),
                   requester_mobile=order.recipient_mobile if (customer and order) else None,
                   access_token=_secrets.token_urlsafe(24) if customer else None,
                   escalated_at=_now - timedelta(hours=1) if escalated else None, escalation_reason=escalated,
                   created_at=_now - timedelta(hours=hours_ago), last_activity_at=_now - timedelta(minutes=20))
        db.add(t)
        db.flush()
        for i, (side, name, body, visibility) in enumerate(messages):
            db.add(TicketMessage(organization_id=org_id, ticket_id=t.id, author_side=side, author_name=name, body=body,
                                 visibility=visibility, created_at=_now - timedelta(hours=hours_ago) + timedelta(minutes=15 * i)))
        return t

    for _org in (default_org, qazvin):
        set_tenant(db, _org.id)
        _orders = db.query(Order).filter(Order.status.in_(("in_transit", "delivered"))).order_by(Order.id).limit(2).all()
        _driver = db.query(User).filter(User.role == RoleEnum.DRIVER).order_by(User.id).first()
        _admin = db.query(User).filter(User.role == RoleEnum.ORG_ADMIN).order_by(User.id).first()
        _prefix = "TK-DEMO" + ("1" if _org.id == default_org.id else "2")
        if _orders:
            o = _orders[0]
            _ticket(_org.id, f"{_prefix}01", f"تأخیر در ارسال — سفارش {o.tracking_code}", "delay", "customer", "org", "org",
                    [("requester", o.recipient_name, "سلام، قرار بود سفارش امروز برسد ولی هنوز خبری نیست.", "all")],
                    order=o, customer=o.recipient_name or "مشتری")
        if len(_orders) > 1:
            o = _orders[1]
            _ticket(_org.id, f"{_prefix}02", f"آسیب‌دیدگی کالا — سفارش {o.tracking_code}", "damaged", "customer", "platform", "platform",
                    [("requester", o.recipient_name, "یکی از کارتن‌ها پاره و کالا آسیب دیده است.", "all"),
                     ("org", _admin.full_name if _admin else "ادمین", "عذرخواهی می‌کنیم؛ در حال بررسی با راننده هستیم.", "all"),
                     ("org", _admin.full_name if _admin else "ادمین", "راننده می‌گوید کالا سالم تحویل شده؛ عکس تحویل نداریم.", "side")],
                    order=o, customer=o.recipient_name or "مشتری", priority="high",
                    escalated="ثبت عکس هنگام تحویل در سامانه ممکن است؟ برای این اختلاف کمک لازم داریم.")
        if _driver:
            _ticket(_org.id, f"{_prefix}03", "پورسانت و تسویه", "payment", "driver", "org", "org",
                    [("requester", _driver.full_name, "پورسانت سفرهای دیروز در پروفایلم ثبت نشده است.", "all")], requester=_driver, hours_ago=5)
        if _admin:
            _ticket(_org.id, f"{_prefix}04", "درخواست خروجی ماهانه پورسانت رانندگان", "feature", "org", "platform", "platform",
                    [("org", _admin.full_name, "آیا امکان گرفتن خروجی اکسل پورسانت ماهانه رانندگان وجود دارد؟", "all")], requester=_admin,
                    hours_ago=30)
    db.commit()
    set_tenant(db, None)
    print("✅ تیکت‌های نمونه پشتیبانی ساخته شد.")

print("===== انبارگردانی نمونه (مرحله ۱۲) =====")
if not db.query(Stocktake).execution_options(**SKIP_TENANT_FILTER).first():
    set_tenant(db, default_org.id)
    _whs = db.query(Warehouse).order_by(Warehouse.id).all()
    for _w, _days in zip(_whs, (30, 90, 180), strict=False):
        _w.stocktake_interval_days = _days
    if _whs:
        _wh = _whs[0]
        _invs = db.query(Inventory).filter(Inventory.warehouse_id == _wh.id, Inventory.quantity > 5).order_by(Inventory.id).limit(6).all()
        _mgr = db.query(User).filter(User.role == RoleEnum.WAREHOUSE_MANAGER, User.warehouse_id == _wh.id).first()
        _now = datetime.now(timezone.utc).replace(tzinfo=None)
        _st = Stocktake(organization_id=default_org.id, code="ST-DEMO01", warehouse_id=_wh.id, title="انبارگردانی نمونه مهر",
                        scope="partial", status="review", created_by_id=_mgr.id if _mgr else None, created_at=_now - timedelta(hours=5),
                        submitted_at=_now - timedelta(hours=1), submitted_by_id=_mgr.id if _mgr else None)
        db.add(_st)
        db.flush()
        for _i, _inv in enumerate(_invs):
            _diff = (0, -2, 0, 3, -1, 0)[_i % 6]           # چند مغایرت نمونه: کسری و اضافی
            db.add(StocktakeLine(organization_id=default_org.id, stocktake_id=_st.id, product_id=_inv.product_id, inventory_id=_inv.id,
                                 product_name=_inv.product.name, product_sku=_inv.product.sku, unit_price=_inv.product.price or 0,
                                 counted_qty=max(0, _inv.quantity + _diff), expected_qty=_inv.quantity,
                                 counted_at=_now - timedelta(hours=2), counted_by_id=_mgr.id if _mgr else None))
    db.commit()
    set_tenant(db, None)
    print("✅ دوره انبارگردانی انبارها و یک انبارگردانی نمونه «منتظر بررسی» ساخته شد.")

print("===== کاتالوگ: قیمت تاریخ‌دار، مشخصات و تنوع نمونه (مرحله ۱۳) =====")
from datetime import date as _date  # noqa: E402
from app.services import catalog_service as _catalog  # noqa: E402
_today = _catalog.today_local()
_all_products = db.query(Product).execution_options(**SKIP_TENANT_FILTER).all()
_with_price = {pid for (pid,) in db.query(ProductPrice.product_id).execution_options(**SKIP_TENANT_FILTER).distinct().all()}
_added = 0
for _p in _all_products:
    if _p.id in _with_price:
        continue
    db.add(ProductPrice(organization_id=_p.organization_id, product_id=_p.id, effective_from=_date(2001, 3, 21),
                        base_price=_p.price or 0, subsidy_percent=0, final_price=_p.price or 0, note="قیمت اولیه کالا"))
    _added += 1
db.commit()
if _added:
    print(f"✅ قیمت اولیه {_added} کالا ثبت شد.")

if not db.query(ProductPrice).filter(ProductPrice.note == "نمونه کاتالوگ").execution_options(**SKIP_TENANT_FILTER).first():
    _CATS = (("برنج", "مواد غذایی"), ("روغن", "مواد غذایی"), ("چای", "مواد غذایی"), ("شکر", "مواد غذایی"), ("ماکارونی", "مواد غذایی"),
             ("رب", "مواد غذایی"), ("حبوبات", "مواد غذایی"), ("پنیر", "لبنیات"), ("کارتن", "بسته‌بندی"), ("نایلون", "بسته‌بندی"),
             ("چسب", "بسته‌بندی"), ("پالت", "تجهیزات انبار"), ("جعبه", "بسته‌بندی"), ("کیسه", "بسته‌بندی"))
    for _org in (default_org, qazvin):
        set_tenant(db, _org.id)
        _products = db.query(Product).order_by(Product.id).all()
        for _i, _p in enumerate(_products):
            _p.category = next((c for k, c in _CATS if k in _p.name), _p.category or "کالای عمومی")
            if _i % 4 == 1:
                _p.origin, _p.origin_country = "imported", ("امارات", "ترکیه", "چین", "هند")[_i % 4]
            if _i % 5 == 0:
                _p.specs = [["کیفیت", "درجه یک"], ["ماندگاری", "۱۲ ماه"]]
            # تاریخچه: قیمت سه ماه پیش ۱۵٪ ارزان‌تر بود؛ قیمت فعلی از ۱۰ روز پیش
            _base = _p.price or 0
            _catalog.set_price(db, None, _p, effective_from=_today - timedelta(days=95), base_price=round(_base * 0.85), note="نمونه کاتالوگ")
            _catalog.set_price(db, None, _p, effective_from=_today - timedelta(days=10), base_price=_base,
                               subsidy_percent=20 if "روغن" in _p.name else 0, note="نمونه کاتالوگ")
            if _i == 2:   # افزایش قیمت برنامه‌ریزی‌شده از ماه بعد
                _catalog.set_price(db, None, _p, effective_from=_today + timedelta(days=20), base_price=round(_base * 1.12), note="افزایش نرخ ارز")
        # یک خانواده تنوع: کالای اول با سری وارداتی دیگر
        _root = _products[0] if _products else None
        if _root is not None and not db.query(Product).filter(Product.parent_id == _root.id).first():
            _var = Product(organization_id=_org.id, name=_root.name, sku=f"{_root.sku}-TR", price=0, weight_kg=_root.weight_kg,
                           category=_root.category, unit=_root.unit or "عدد", origin="imported", origin_country="ترکیه",
                           parent_id=_root.id, variant_label="سری واردات ترکیه", specs=_root.specs)
            db.add(_var)
            db.flush()
            _catalog.set_price(db, None, _var, effective_from=_today - timedelta(days=10), base_price=round((_root.price or 0) * 1.08), note="نمونه کاتالوگ")
            for _inv in _root.inventories:
                db.add(Inventory(organization_id=_org.id, product_id=_var.id, warehouse_id=_inv.warehouse_id, quantity=0, reorder_point=5))
        db.commit()
    set_tenant(db, None)
    print("✅ قیمت تاریخ‌دار، گروه، مبدأ و یک خانواده تنوع نمونه ثبت شد.")

print("===== سابقه فروش نمونه (نقطه سفارش هوشمند و برآورد سرمایه خرید) =====")
import seed_sales_history  # noqa: E402
seed_sales_history.seed(db)

print("===== لینک دعوت نمونه برای ثبت‌نام راننده (مرحله احراز هویت) =====")
if not db.query(DriverInvite).filter(DriverInvite.code == "QAZVIN26").execution_options(**SKIP_TENANT_FILTER).first():
    db.add(DriverInvite(organization_id=qazvin.id, code="QAZVIN26", label="رانندگان جدید قزوین (نمونه)"))
    db.commit()
    print("✅ لینک دعوت ساخته شد: /join/QAZVIN26 (فروشگاه نمونه قزوین)")

db.close()

print("\n🎉 داده‌های نمونه با موفقیت آماده شدند. اطلاعات ورود:")
print("   🛰️ ادمین پلتفرم:       superadmin / superadmin123   (پنل /platform)")
print("   🛟 پشتیبان پلتفرم:     support / support123")
print("   ── سازمان پیش‌فرض ──")
print("   👑 ادمین سازمان:       admin / admin123")
print("   🏬 مدیر انبار تهران:    manager_tehran / manager123")
print("   🏬 مدیر انبار تبریز:    manager_tabriz / manager123")
print("   🏬 مدیر انبار مشهد:     manager_mashhad / manager123")
print("   🚚 رانندگان:            driver_ali, driver_reza, driver_sara, driver_hossein,")
print("                          driver_maryam, driver_amir, driver_zahra, driver_mohammad,")
print("                          driver_fateme, driver_hamed, driver_narges, driver_babak")
print("                          (رمز همه: driver123)")
print("   ── فروشگاه نمونه قزوین ──")
print("   👑 ادمین سازمان:       qazvin_admin / admin123")
print("   🏬 مدیر انبار:          qazvin_manager / manager123")
print("   🚚 رانندگان:            qazvin_driver1, qazvin_driver2 (رمز: driver123)")
print("   🔗 ثبت‌نام راننده جدید:  /join/QAZVIN26")
