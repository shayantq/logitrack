"""
سازمان نمایشی «پخش سراسری آریا» با چند هزار رکورد در همه بخش‌ها و حالت‌ها — برای دمو و ویدیوی معرفی.

کاملاً جدا از سازمان‌های دیگر (چندسازمانی)؛ همه گردش‌های انبار از دفتر گردش و سرویس‌های واقعی ثبت می‌شوند و
سپس تاریخشان به گذشته برده می‌شود (۱۲۰ روز سابقه)، پس دفتر گردش، کاردکس و شاخص‌ها سازگار و خوانا هستند.

    docker compose exec web python seed_showcase.py            # ساخت (اگر هست، کاری نمی‌کند)
    docker compose exec web python seed_showcase.py --reset    # حذف کامل و ساخت دوباره
    docker compose exec web python seed_showcase.py --delete   # فقط حذف کامل سازمان نمایشی

پیامک و ایمیل در طول ساخت خاموش است. ورود: arya_admin / Arya@1405 (همه کاربران همین رمز).
"""
from __future__ import annotations

import io
import os
import random
import secrets
import sys
from datetime import date, datetime, time, timedelta, timezone

from PIL import Image, ImageDraw
from sqlalchemy import DateTime, func, select, text

from app.core import geo, storage
from app.core.iran import fa_digits
from app.core.security import bcrypt_context
from app.core.tenancy import SKIP_TENANT_FILTER, set_tenant
from app.core.wms import AVAILABLE, PENDING
from app.database import Base, SessionLocal
from app.models import (
    Customer, CutoverCheck, DriverDocument, DriverInvite, DriverProfile, DriverRating, DriverRequest, DriverShift,
    DriverTimeOff, Location, Order, OrderCheckpoint, OrderItem, OrderStatusHistory, Organization, Package, PackageItem,
    Partner, PickLine, PickList, Product, PutawayTask, RoleEnum, Shipment, StockMovement, StockMovementLine, Ticket, TicketMessage,
    User, Vehicle, Warehouse,
)
from app.schemas.fulfillment import (
    DispositionCreate, PackIn, PickIn, PickListCreate, ReplenishmentRuleIn, ShipmentCreate, TransferCreate, TransferReceiveIn,
)
from app.schemas.operations import InspectionCreate, ReceiptCloseIn, ReceiptCreate, ReceiveIn
from app.schemas.order import OrderRequest
from app.schemas.product import StatusChangeCreate
from app.services import (
    allocation_service, catalog_service, commission_service, disposition_service, dispatch_service, inventory_service,
    label_service, messaging, permission_service, picking_service, putaway_service, quality_service, receiving_service,
    replenishment_rule_service, replenishment_service, route_service, shipping_service, stock_ledger, stocktake_service,
    transfer_order_service, order_service,
)
from app.services.stock_ledger import StockKey

SLUG, NAME, PASSWORD = "arya-demo", "پخش سراسری آریا", "Arya@1405"
DAYS = int(os.getenv("SHOWCASE_DAYS", "120"))
SCALE = float(os.getenv("SHOWCASE_SCALE", "1"))
rng = random.Random(1405)

# پیامک/ایمیل به شماره‌های ساختگی فرستاده نشود
for _name in ("queue_sms", "queue_email", "deliver_sms", "deliver_email"):
    setattr(messaging, _name, lambda *a, **k: False)

FIRST = ["علی", "رضا", "محمد", "حسین", "مهدی", "سارا", "مریم", "زهرا", "فاطمه", "نرگس", "امیر", "حامد", "بابک", "نیلوفر", "پویا",
         "کیان", "الهام", "شیما", "آرش", "سینا", "یاسمن", "پرستو", "مجید", "وحید", "لیلا"]
LAST = ["احمدی", "رضایی", "محمدی", "حسینی", "کریمی", "موسوی", "جعفری", "صادقی", "رحیمی", "نوری", "کاظمی", "قاسمی", "مرادی",
        "یزدانی", "شریفی", "عباسی", "نادری", "سلطانی", "فراهانی", "توکلی"]
CATALOG = [  # (گروه، نمونه‌ها، وزن، قیمت پایه، بچ/انقضا، بازرسی)
    ("مواد غذایی", ["برنج هاشمی ۱۰ کیلویی", "روغن مایع ۱.۵ لیتری", "چای سیاه ۵۰۰ گرمی", "شکر ۱ کیلویی", "ماکارونی ۷۰۰ گرمی",
                    "رب گوجه ۸۰۰ گرمی", "عدس ۹۰۰ گرمی", "لوبیا چیتی", "زعفران ۴.۶ گرمی", "خرمای مضافتی"], 2.0, 1_800_000, True, False),
    ("لبنیات", ["شیر کم‌چرب ۱ لیتری", "ماست ۹۰۰ گرمی", "پنیر سفید ۴۰۰ گرمی", "کره ۱۰۰ گرمی", "دوغ ۱.۵ لیتری"], 1.2, 650_000, True, True),
    ("بهداشتی", ["شامپو ۴۰۰ میلی", "خمیردندان", "مایع ظرفشویی ۴ لیتری", "پودر لباسشویی ۵ کیلویی", "دستمال کاغذی ۶ قلو"], 1.5, 900_000, False, False),
    ("دارویی", ["قرص ویتامین D", "شربت سرفه", "ماسک سه‌لایه ۵۰ عددی", "ژل ضدعفونی", "باند استریل"], 0.3, 1_200_000, True, True),
    ("لوازم خانگی", ["اتو بخار", "چای‌ساز", "جاروبرقی", "مخلوط‌کن", "سرخ‌کن بدون روغن"], 5.0, 45_000_000, False, False),
    ("الکترونیک", ["هدفون بی‌سیم", "پاوربانک ۲۰۰۰۰", "شارژر سریع", "اسپیکر بلوتوثی", "ساعت هوشمند"], 0.4, 18_000_000, False, False),
    ("نوشت‌افزار", ["دفتر ۱۰۰ برگ", "خودکار آبی ۱۲ عددی", "کاغذ A4 بسته ۵۰۰", "ماژیک وایت‌برد"], 1.0, 350_000, False, False),
    ("بسته‌بندی", ["کارتن سه‌لایه متوسط", "نوار چسب پهن", "نایلون حباب‌دار", "پالت چوبی"], 3.0, 280_000, False, False),
]
CITIES = {"تهران": ["تهران", "کرج", "قم", "قزوین", "رشت", "ساری", "اراک", "سمنان"], "اصفهان": ["اصفهان", "کاشان", "یزد", "شهرکرد", "شیراز"],
          "مشهد": ["مشهد", "نیشابور", "سبزوار", "بجنورد", "گرگان"]}


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_dt(day: date, hour: float) -> datetime:
    return dispatch_service.local_to_utc(datetime.combine(day, time(0, 0)) + timedelta(hours=hour))


def mobile(i: int) -> str:
    return f"0912{7_000_000 + i:07d}"[:11]


def person(i: int) -> str:
    return f"{FIRST[i % len(FIRST)]} {LAST[(i * 7) % len(LAST)]}"


# ---------------------------------------------------------------------------
# حذف و ابزار جابه‌جایی زمان
# ---------------------------------------------------------------------------
def delete_org(db) -> None:
    org = db.query(Organization).filter(Organization.slug == SLUG).first()
    if org is None:
        print("سازمان نمایشی وجود ندارد.")
        return
    name, org_id = org.name, org.id
    with stock_ledger.maintenance(db):
        db.execute(text("UPDATE users SET vehicle_id = NULL WHERE organization_id = :o"), {"o": org.id})
        db.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org.id})
    db.commit()
    storage_root = storage.MEDIA_ROOT / "drivers" / str(org_id)
    if storage_root.exists():
        import shutil
        shutil.rmtree(storage_root, ignore_errors=True)
    print(f"🗑️ سازمان نمایشی «{name}» و همه داده‌هایش حذف شد.")


TABLES = [t for t in Base.metadata.sorted_tables if "organization_id" in t.c and "id" in t.c]


def marks(db, org_id: int) -> dict:
    db.flush()
    return {t.name: db.execute(select(func.max(t.c.id)).where(t.c.organization_id == org_id)).scalar() or 0 for t in TABLES}


def shift(db, org_id: int, since: dict, target: datetime) -> None:
    """همه ردیف‌های تازه (بعد از since) را با حفظ فاصله نسبی‌شان به زمان target می‌برد."""
    delta = now() - target
    db.flush()
    with stock_ledger.maintenance(db):
        for t in TABLES:
            cols = [c for c in t.c if isinstance(c.type, DateTime)]
            if cols:
                db.execute(t.update().where(t.c.organization_id == org_id, t.c.id > since[t.name])
                           .values({c.name: c - delta for c in cols}))
    db.commit()


def jpeg(label: str, color: str) -> bytes:
    img = Image.new("RGB", (480, 300), color)
    draw = ImageDraw.Draw(img)
    draw.rectangle((20, 20, 460, 280), outline="white", width=4)
    draw.text((40, 130), f"SAMPLE  {label}", fill="white")
    out = io.BytesIO()
    img.save(out, "JPEG", quality=70)
    return out.getvalue()


# ---------------------------------------------------------------------------
# ساخت
# ---------------------------------------------------------------------------
def build(db) -> None:
    if db.query(Organization).filter(Organization.slug == SLUG).first():
        print("↩️ سازمان نمایشی از قبل هست (برای ساخت دوباره: --reset).")
        return
    t0 = now()
    today = catalog_service.today_local()
    org = Organization(name=NAME, slug=SLUG, is_active=True, legal_name="شرکت پخش سراسری آریا (سهامی خاص)",
                       business_type="wholesale", national_id="10320000001", economic_code="41150000001",
                       province="تهران", city="تهران", address="تهران، بزرگراه فتح، شهرک صنعتی آریا، پلاک ۱۴", postal_code="1399000000",
                       phone="02166000000", employee_count="201-1000", monthly_order_volume="1000-10000", warehouse_count=4,
                       fleet_size=15, contact_name="مهندس آرش کیانی", contact_mobile="09120001405", contact_email="info@arya-demo.ir",
                       brand_color="#2563EB")
    db.add(org)
    db.commit()
    O = org.id
    set_tenant(db, O)
    setup = marks(db, O)
    hashed = bcrypt_context.hash(PASSWORD)

    def user(username, role, full_name, **kw):
        u = User(username=username, email=f"{username}@arya-demo.ir", role=role, hashed_password=hashed, full_name=full_name,
                 mobile=kw.pop("mobile", None) or mobile(rng.randint(1, 999_999)), **kw)
        db.add(u)
        db.flush()
        return u

    admin = user("arya_admin", RoleEnum.ORG_ADMIN, "آرش کیانی (مدیرعامل)")
    whs = {}
    for code, name, city, wtype in (("ARY-THR", "مرکز توزیع تهران", "تهران", "distribution"), ("ARY-ISF", "انبار اصفهان", "اصفهان", "general"),
                                    ("ARY-MSH", "انبار مشهد", "مشهد", "general"), ("ARY-TRN", "انبار در راه", "تهران", "transit")):
        c = geo.find_city(city)
        w = Warehouse(code=code, name=name, location=f"{city}، منطقه صنعتی", city=city, province=c.province if c else city,
                      type=wtype, stocktake_interval_days=90 if wtype != "transit" else None)
        db.add(w)
        db.flush()
        if wtype != "transit":
            whs[city] = w
    hubs = ["تهران", "اصفهان", "مشهد"]
    managers = {city: user(f"arya_{key}", RoleEnum.WAREHOUSE_MANAGER, f"{person(i)} (مدیر انبار {city})", warehouse_id=whs[city].id)
                for i, (city, key) in enumerate((("تهران", "tehran"), ("اصفهان", "isfahan"), ("مشهد", "mashhad")))}

    # ---- محل‌ها: تخلیه، قرنطینه، آماده‌سازی، بارگیری و منطقه‌های برداشت/نگهداری ----
    def loc(w, code, level, ltype, parent=None, **kw):
        row = Location(warehouse_id=w.id, parent_id=parent.id if parent else None, level=level, code=code, barcode=f"{w.code}-{code}",
                       location_type=ltype, **kw)
        db.add(row)
        db.flush()
        return row
    bins, special = {c: [] for c in hubs}, {}
    for city, (zones, aisles, per) in {"تهران": ("ABC", 5, 8), "اصفهان": ("AB", 4, 6), "مشهد": ("AB", 3, 6)}.items():
        w = whs[city]
        special[city] = {"rcv": loc(w, "RCV-01", "bin", "receiving"), "qc": loc(w, "QC-01", "bin", "quarantine"),
                         "stg": loc(w, "STG-01", "bin", "staging"), "shp": loc(w, "SHP-01", "bin", "shipping")}
        loc(w, "RCV-02", "bin", "receiving")
        seq = 0
        for z in zones:
            zone = loc(w, z, "zone", "picking" if z == "A" else "storage")
            for a in range(1, aisles + 1):
                aisle = loc(w, f"{z}-{a:02d}", "aisle", "picking" if z == "A" else "storage", zone)
                for b in range(1, per + 1):
                    seq += 1
                    bins[city].append(loc(w, f"{z}-{a:02d}-{b:02d}", "bin", "picking" if z == "A" else "storage", aisle,
                                          max_weight_kg=25000, max_volume_m3=80, route_sequence=seq))
    db.commit()

    # ---- کاتالوگ: کالا، قیمت تاریخ‌دار با بهای تمام‌شده ----
    products = []
    n = 0
    for category, names, weight, price, lot, inspect in CATALOG:
        for base in names:
            for variant in ("", " — بسته عمده") if category not in ("الکترونیک", "لوازم خانگی") else ("", " — مدل پرو"):
                n += 1
                p = Product(name=base + variant, sku=f"AR-{n:04d}", barcode=f"626{n:010d}", category=category,
                            brand=rng.choice(["آریا", "مهرام", "گلستان", "پاکشوما", "سانا", "بهروز", "ایران‌کالا"]),
                            unit="عدد", weight_kg=round(weight * (3 if variant.endswith("عمده") else 1), 2),
                            length_cm=30, width_cm=20, height_cm=15 if weight < 3 else 40, price=0,
                            lot_tracked=lot, expiry_tracked=lot, shelf_life_days=180 if lot else None,
                            inspection_required=inspect and n % 3 == 0, units_per_pallet=60,
                            origin="imported" if category in ("الکترونیک", "لوازم خانگی") and n % 2 else "domestic",
                            min_stock=10, max_stock=400, reorder_point=40)
                db.add(p)
                db.flush()
                base_price = round(price * rng.uniform(0.6, 1.6) * (2.6 if variant.endswith("عمده") else 1), -3)
                for days_ago, factor in ((DAYS + 10, 0.86), (70, 0.94), (20, 1.0)):
                    catalog_service.set_price(db, None, p, effective_from=today - timedelta(days=days_ago),
                                              base_price=round(base_price * factor, -3), cost_price=None if n % 9 == 0 else round(base_price * factor * 0.76, -3),
                                              subsidy_percent=15 if category == "مواد غذایی" and n % 4 == 0 else 0, note="قیمت نمونه")
                p.popularity = rng.choice([0.2, 0.5, 1, 1, 2, 3, 5, 8])
                products.append(p)
    db.commit()
    dead = products[-8:]                      # چند کالای بی‌فروش برای گزارش «راکد»

    # ---- طرف‌های تجاری و مشتریان ----
    suppliers = []
    for i, name in enumerate(["صنایع غذایی گلستان", "پخش البرز", "توزیع مهرام", "بازرگانی سانا", "دارو پخش", "صنایع پاکشوما",
                              "الکترو آریا", "کاغذسازی کاوه", "بسته‌بندی ایرانیان", "لبنیات پاک"]):
        s = Partner(code=f"SUP-{i + 1:03d}", name=name, is_supplier=True, legal_name=f"شرکت {name}", province="تهران", city="تهران",
                    mobile=mobile(500 + i), payment_terms_days=rng.choice([15, 30, 45]), lead_time_days=rng.choice([3, 5, 7, 14]))
        db.add(s)
        suppliers.append(s)
    for i, name in enumerate(["فروشگاه‌های رفاه", "هایپر استار", "زنجیره افق کوروش", "شهروند", "سوپرمارکت ستاره"]):
        db.add(Partner(code=f"CUS-{i + 1:03d}", name=name, is_customer=True, province="تهران", city="تهران", mobile=mobile(600 + i)))
    for i, name in enumerate(["باربری سپهر", "تیپاکس", "پست پیشتاز"]):
        db.add(Partner(code=f"CAR-{i + 1:03d}", name=name, is_carrier=True, carrier_service=("road", "courier", "post")[i]))
    db.add(Partner(code="OWN-001", name="کالای امانی شرکت نیک‌تجارت", is_owner=True))
    customers = []
    for i in range(int(320 * SCALE)):
        c = Customer(organization_id=O, name=person(i + 3), mobile=mobile(1000 + i))
        db.add(c)
        customers.append(c)
    db.commit()

    # ---- رانندگان، خودروها، شیفت، دعوت و احراز هویت ----
    plans = [("van", "ون", 1500), ("truck", "کامیونت", 5000), ("pickup", "وانت", 1200), ("motorcycle", "موتور", 60), ("sedan", "سواری", 300)]
    fleet = {c: [] for c in hubs}
    letters = "بجدسصطقلمنوهی"
    invite = DriverInvite(organization_id=O, code="ARYA1405", label="جذب رانندگان آریا", created_by_id=admin.id)
    db.add(invite)
    for i in range(15):
        city = hubs[i % 3]
        vtype, vname, cap = plans[i % len(plans)]
        d = user(f"arya_driver{i + 1:02d}", RoleEnum.DRIVER, person(i + 40), city=city, driver_code=f"ARD-{i + 1:03d}")
        plate = fa_digits(f"{10 + i}ایران{300 + i}{letters[i % len(letters)]}{20 + i}")
        v = Vehicle(license_plate=plate, model=f"{vname} {i + 1}", type=vtype, capacity_kg=cap, max_weight_kg=cap,
                    max_volume_m3=max(1.0, cap / 400), status="available", driver_id=d.id, city=city)
        db.add(v)
        db.flush()
        d.vehicle_id = v.id
        db.add(DriverProfile(user_id=d.id, first_name=d.full_name.split()[0], last_name=d.full_name.split()[-1], national_code=f"00{12345670 + i}",
                             birth_date=date(1985 + i % 15, 1 + i % 12, 1 + i % 27), mobile=d.mobile, province=whs[city].province, city=city,
                             vehicle_type=vtype, vehicle_model=vname, license_plate=plate, max_weight_kg=cap, intercity=vtype in ("van", "truck"),
                             employment_type="part_time" if i % 5 == 4 else "full_time", max_daily_orders=None, vehicle_id=v.id,
                             submitted_at=now(), reviewed_at=now(), reviewed_by_id=admin.id))
        for wd in ((5, 6, 0, 1, 2) if i % 5 != 4 else (5, 0, 2)):
            db.add(DriverShift(user_id=d.id, weekday=wd, start_time=time(7 if i % 5 != 4 else 14), end_time=time(19 if i % 5 != 4 else 21)))
        fleet[city].append(v)
    # متقاضیان احراز هویت: دو منتظر بررسی، یک ردشده با دلیل، یک ناقص
    for j, (status, reason) in enumerate((("submitted", None), ("submitted", None),
                                          ("rejected", "تصویر کارت خودرو ناخوانا است و تاریخ معاینه فنی گذشته؛ لطفاً مدارک را دوباره بارگذاری کنید."),
                                          ("incomplete", None))):
        d = user(f"arya_applicant{j + 1}", RoleEnum.DRIVER, person(j + 70), city="تهران", driver_status=status)
        db.add(DriverProfile(user_id=d.id, invite_id=invite.id, first_name=d.full_name.split()[0], last_name=d.full_name.split()[-1],
                             national_code=f"00{22345670 + j}", mobile=d.mobile, province="تهران", city="تهران", vehicle_type="van",
                             vehicle_model="ون فوتون", license_plate=fa_digits(f"{40 + j}ایران{510 + j}ل{11 + j}"), max_weight_kg=1500,
                             submitted_at=now() - timedelta(hours=5 + j) if status != "incomplete" else None,
                             reviewed_at=now() - timedelta(hours=2) if status == "rejected" else None,
                             reviewed_by_id=admin.id if status == "rejected" else None, rejection_reason=reason))
        if status != "incomplete":
            for kind, color in (("national_card", "#1e3a8a"), ("selfie", "#0f766e"), ("driving_license", "#7c2d12"),
                                ("vehicle_photo", "#334155"), ("vehicle_card", "#6d28d9"), ("technical_inspection", "#9a3412")):
                data = jpeg(kind, color)
                path = storage.save(f"drivers/{O}/{d.id}/{kind}.jpg", data)
                db.add(DriverDocument(user_id=d.id, kind=kind, file_path=path, content_type="image/jpeg", size_bytes=len(data)))
        invite.uses += 1
    db.commit()
    drivers = [v.driver_id for c in hubs for v in fleet[c]]

    # ---- موجودی اول دوره در محل‌ها (بچ و انقضا برای غذایی/دارویی) ----
    opening = {}
    for city in hubs:
        w = whs[city]
        doc = stock_ledger.new_document(db, "opening", organization_id=O, user=admin, warehouse_id=w.id, note="موجودی اول دوره (راه‌اندازی)")
        for k, p in enumerate(products):
            if city != "تهران" and k % 5 == 0:
                continue
            qty = int(max(20, p.popularity * 45 * (1 if city == "تهران" else 0.5)) * SCALE)
            inv = stock_ledger.lock_bucket(db, p.id, w.id, organization_id=O, reorder_point=40)
            location = bins[city][k % len(bins[city])]
            if p.lot_tracked:
                half = qty // 2
                for part, (lot, exp) in ((half, (f"L{hubs.index(city)}{k:03d}A", today + timedelta(days=(-5, 12, 25, 90, 150)[k % 5]))),
                                         (qty - half, (f"L{hubs.index(city)}{k:03d}B", today + timedelta(days=(60, 120, 200)[k % 3])))):
                    stock_ledger.record(db, inv, part, "initial", document=doc, user=admin, reason="موجودی اول دوره",
                                        lines=[(StockKey(location_id=location.id, lot_number=lot, expiry_date=exp), part)])
            else:
                stock_ledger.record(db, inv, qty, "initial", document=doc, user=admin, reason="موجودی اول دوره",
                                    lines=[(StockKey(location_id=location.id), qty)])
            opening[(city, p.id)] = location
        db.commit()
    shift(db, O, setup, local_dt(today - timedelta(days=DAYS + 1), 8))
    print(f"✅ پایه: {len(products)} کالا، {sum(len(b) for b in bins.values())} خانه، ۱۵ راننده ({(now() - t0).seconds} ثانیه)")

    # ---- سابقه روزانه ----
    counts = {"orders": 0, "receipts": 0, "picks": 0, "transfers": 0, "stocktakes": 0, "dispositions": 0}
    weights = [p.popularity for p in products if p not in dead]
    pool = [p for p in products if p not in dead]
    plan = commission_service.get_plan(db)

    def stock_of(city, p):
        inv = stock_ledger.lock_bucket(db, p.id, whs[city].id, create=False)
        return inv, (allocation_service.available_to_promise(db, inv) if inv else 0)

    def make_order(city, day, status, hour, vehicle=None, now_based=False):
        w = whs[city]
        items = []
        for p in rng.choices(pool, weights=weights, k=rng.choice([1, 1, 2, 2, 3, 4])):
            if any(p.id == x[0].id for x in items):
                continue
            inv, free = stock_of(city, p)
            q = min(free, rng.choice([1, 1, 2, 3, 5, 10]))
            if inv and q > 0:
                items.append((p, inv, q))
        if not items:
            return None
        cust = rng.choice(customers)
        dest = rng.choice(CITIES[city]) if rng.random() < 0.35 else city
        c = geo.find_city(dest)
        base = now() if now_based else now()
        start = base + timedelta(hours=hour)
        vehicle = vehicle or (rng.choice(fleet[city]) if status != "pending" else None)
        o = Order(organization_id=O, tracking_code=order_service.new_tracking_code(db), status=status, size=rng.choice("smml"),
                  priority=rng.random() < 0.12, delivery_window_start=start, delivery_window_end=start + timedelta(hours=rng.choice([3, 4, 6])),
                  customer_id=cust.id, recipient_name=cust.name, recipient_mobile=cust.mobile,
                  destination_province=c.province if c else w.province, destination_city=dest,
                  destination_address=f"{dest}، خیابان {rng.choice(['آزادی', 'انقلاب', 'امام', 'ولیعصر', 'شریعتی'])}، پلاک {rng.randint(1, 300)}",
                  warehouse_id=w.id, vehicle_id=vehicle.id if vehicle else None, driver_id=vehicle.driver_id if vehicle else None,
                  total_quantity=sum(q for *_, q in items), total_weight_kg=sum((p.weight_kg or 0) * q for p, _, q in items),
                  total_price=sum((p.price or 0) * q for p, _, q in items), stock_state="reserved", created_at=start - timedelta(hours=rng.uniform(4, 30)),
                  delivery_fee=commission_service.default_fee(plan, sum((p.weight_kg or 0) * q for p, _, q in items)))
        db.add(o)
        for p, _, q in items:
            o.items.append(OrderItem(organization_id=O, product_id=p.id, product_name=p.name, product_sku=p.sku, quantity=q,
                                     unit_price=p.price or 0, unit_weight_kg=p.weight_kg or 0))
        db.flush()
        res = [allocation_service.reserve(db, inv, q, reference_type="order", reference_id=o.id, user=admin) for _, inv, q in items]
        hist = [(None, "assigned" if vehicle else "pending", o.created_at)]
        if status in ("canceled", "expired"):
            for r in res:
                allocation_service.release(db, r, reason=f"سفارش {o.tracking_code} {status}")
            o.stock_state, o.fulfillment_state = "released", "open"
            hist.append((hist[-1][1], status, start + timedelta(hours=-2 if status == "canceled" else 7)))
        elif status in ("picked_up", "in_transit", "delivered", "failed"):
            issue = stock_ledger.new_document(db, "order_issue", organization_id=O, warehouse_id=w.id, reference_type="order", reference_id=o.id)
            moves = [allocation_service.consume(db, r, issue, reason=f"خروج سفارش {o.tracking_code}") for r in res]
            o.stock_state, o.fulfillment_state = "issued", "shipped"
            hist += [("assigned", "picking_up", start - timedelta(minutes=50)), ("picking_up", "picked_up", start - timedelta(minutes=20))]
            if status != "picked_up":
                hist.append(("picked_up", "in_transit", start))
            o._moves = moves
            if status == "delivered":
                done = start + timedelta(hours=rng.uniform(0.5, 3.5) if rng.random() < 0.9 else rng.uniform(4, 8))
                hist.append(("in_transit", "delivered", done))
                o.status = "delivered"
                commission_service.settle_delivery(db, o, now=done)
            elif status == "failed":
                hist.append(("in_transit", "failed", start + timedelta(hours=2)))
                back = stock_ledger.new_document(db, "order_return", organization_id=O, warehouse_id=w.id, reference_type="order", reference_id=o.id)
                for p, _, q in items:
                    pend = stock_ledger.lock_bucket(db, p.id, w.id, AVAILABLE, organization_id=O)
                    stock_ledger.record(db, pend, q, "order_return", document=back, reason=f"برگشت سفارش {o.tracking_code}",
                                        reference_type="order", reference_id=o.id, match={"location_id": special[city]["rcv"].id})
                o.stock_state = "returned"
        for frm, to, at in hist:
            db.add(OrderStatusHistory(organization_id=O, order=o, from_status=frm, to_status=to, changed_at=at,
                                      changed_by_id=(vehicle.driver_id if vehicle and to in ("picking_up", "in_transit", "delivered", "failed") else admin.id)))
        counts["orders"] += 1
        return o

    def history_pick(city, orders, day_hour):
        """برداشت‌های گذشته (فهرست موجی، سطرها از همان محل‌های حواله، ۲٪ کسری)، بسته‌ها و محموله‌ها."""
        pl = PickList(organization_id=O, code=stock_ledger.new_code(db, PickList, "PL"), strategy=rng.choice(["batch", "wave", "zone"]),
                      status="picked", warehouse_id=whs[city].id, staging_location_id=special[city]["stg"].id, created_by_id=managers[city].id,
                      started_at=now() + timedelta(hours=day_hour - 3), completed_at=now() + timedelta(hours=day_hour - 1.5))
        db.add(pl)
        db.flush()
        seq = 0
        by_vehicle = {}
        for o in orders:
            for m in getattr(o, "_moves", []):
                for ln in m.lines:
                    seq += 1
                    qty = -ln.quantity_change
                    short = rng.random() < 0.02
                    db.add(PickLine(organization_id=O, pick_list_id=pl.id, order_id=o.id, product_id=m.product_id, warehouse_id=whs[city].id,
                                    location_id=ln.location_id, lot_number=ln.lot_number, expiry_date=ln.expiry_date, quantity=qty,
                                    picked_quantity=qty - 1 if short and qty > 1 else qty, status="short" if short and qty > 1 else "picked",
                                    short_reason="کسری در قفسه" if short and qty > 1 else None, sequence=seq, issued=True,
                                    picked_at=pl.started_at + timedelta(minutes=seq), picked_by_id=managers[city].id))
            pkg = Package(organization_id=O, code=f"{o.tracking_code}-1", order_id=o.id, sequence=1, length_cm=40, width_cm=30,
                          height_cm=rng.choice([20, 30, 40]), weight_kg=max(o.total_weight_kg, 0.5), packed_by_id=managers[city].id)
            db.add(pkg)
            db.flush()
            for it in o.items:
                db.add(PackageItem(organization_id=O, package_id=pkg.id, product_id=it.product_id, quantity=it.quantity))
            by_vehicle.setdefault(o.vehicle_id, []).append(o)
        for vehicle_id, group in by_vehicle.items():
            veh = db.get(Vehicle, vehicle_id)
            sh = Shipment(organization_id=O, code=stock_ledger.new_code(db, Shipment, "SH"), status="dispatched", warehouse_id=whs[city].id,
                          vehicle_id=vehicle_id, driver_id=veh.driver_id if veh else None, created_by_id=managers[city].id,
                          dispatched_at=now() + timedelta(hours=day_hour - 1), dispatched_by_id=managers[city].id)
            db.add(sh)
            db.flush()
            for o in group:
                o.shipment_id = sh.id
        counts["picks"] += 1

    def receipt(city, day):
        w = whs[city]
        need = []
        for p in pool:
            inv, free = stock_of(city, p)
            if inv and free < 60 and len(need) < 14:
                need.append((p, int(max(120, p.popularity * 70) * SCALE)))
        if not need:
            return
        m0 = marks(db, O)
        r = receiving_service.create_receipt(db, admin, ReceiptCreate(
            receipt_type="purchase", warehouse_id=w.id, partner_id=rng.choice(suppliers).id, reference_number=f"PO-{rng.randint(10000, 99999)}",
            external_ref=f"BL-{rng.randint(100000, 999999)}", expected_date=day, receiving_location_id=special[city]["rcv"].id,
            lines=[{"product_id": p.id, "expected_quantity": q} for p, q in need]))
        lines = []
        for ln, (p, q) in zip(r["lines"], need, strict=True):
            got = q if rng.random() > 0.08 else q - rng.randint(1, 5)
            entry = {"line_id": ln["id"], "quantity": max(1, got)}
            if p.lot_tracked:
                entry.update(lot_number=f"R{day:%m%d}{p.id}", expiry_date=max(day + timedelta(days=rng.choice([45, 90, 180])),
                                                                         today + timedelta(days=rng.choice([20, 60, 150]))))
            lines.append(entry)
        receiving_service.receive(db, managers[city], r["id"], ReceiveIn(lines=lines, location_id=special[city]["rcv"].id))
        receiving_service.close(db, managers[city], r["id"], ReceiptCloseIn(reasons={l["id"]: "کسری تحویل تأمین‌کننده" for l in r["lines"]}))
        shift(db, O, m0, local_dt(day, 8.5))
        m1 = marks(db, O)
        inspect_receipt(city, r["id"], lines, need)
        for task in putaway_service.list_tasks(db, managers[city], status="active", receipt_id=r["id"]):
            if task["stock_status"] != AVAILABLE or not task["suggested_location_code"]:
                continue
            putaway_service.execute(db, managers[city], task["id"], putaway_service_scan(task))
        stored_at = local_dt(day, 8.5 + rng.uniform(2, 20))
        # وظیفه جانمایی هنگام دریافت ساخته شده (پیش از m1)؛ زمان پایانش هم به همان روز برود
        db.query(PutawayTask).filter(PutawayTask.receipt_id == r["id"], PutawayTask.status == "done").update(
            {PutawayTask.completed_at: stored_at}, synchronize_session=False)
        shift(db, O, m1, stored_at)
        counts["receipts"] += 1

    def inspect_receipt(city, receipt_id, lines, need, reject=True):
        """بازرسی کیفی کالای رسیده: بیشتر سالم و قابل تخصیص، گاهی چند واحد مردود یا معیوب."""
        for entry, (p, _) in zip(lines, need, strict=True):
            qty = entry["quantity"]
            held = stock_ledger.lock_bucket(db, p.id, whs[city].id, PENDING, create=False)
            if held is None or held.free_quantity < qty:
                continue                     # این کالا مستقیم «قابل فروش» دریافت شده است
            bad =rng.randint(1, 3) if reject and qty > 10 and rng.random() < 0.1 else 0
            results = [{"status": AVAILABLE, "quantity": qty - bad}]
            if bad:
                results.append({"status": rng.choice(["rejected", "defective", "damaged"]), "quantity": bad,
                                "reason": rng.choice(["بسته‌بندی پاره", "تاریخ تولید نامعتبر", "آسیب در حمل"])})
            quality_service.inspect(db, managers[city], InspectionCreate(
                product_id=p.id, warehouse_id=whs[city].id, from_status=PENDING, location_id=special[city]["rcv"].id,
                lot_number=entry.get("lot_number"), receipt_id=receipt_id, results=results))

    from app.schemas.operations import PutawayExecute

    def putaway_service_scan(task):
        return PutawayExecute(product_scan=task["product_sku"], source_scan=task["source_location_code"] or whs_code(task),
                              destination_scan=task["suggested_location_code"], lot_scan=task.get("lot_number"), quantity=task["remaining"])

    def whs_code(task):
        return db.get(Warehouse, task["warehouse_id"]).code

    for d in range(DAYS, 0, -1):
        day = today - timedelta(days=d)
        for city in hubs:
            if (d + hubs.index(city)) % 4 == 0:
                receipt(city, day)
        m = marks(db, O)
        for city, mean in (("تهران", 14), ("اصفهان", 7), ("مشهد", 5)):
            weekend = day.weekday() == 4
            done = []
            for _ in range(max(0, int(rng.gauss(mean * SCALE * (0.4 if weekend else 1), 2)))):
                roll = rng.random()
                status = "delivered" if roll < 0.84 else "failed" if roll < 0.88 else "canceled" if roll < 0.95 else "expired"
                o = make_order(city, day, status, rng.uniform(9, 17))
                if o is not None and status in ("delivered", "failed"):
                    done.append(o)
            if done:
                history_pick(city, done, 9)
            if rng.random() < 0.35:
                for o in done[:3]:
                    if o.status == "delivered" and o.driver_id:
                        db.add(DriverRating(order_id=o.id, driver_id=o.driver_id, source="customer", score=rng.choice([3, 4, 5, 5, 5, 2]),
                                            tags=rng.choice([["polite"], ["on_time"], ["late"], None]), comment=rng.choice([None, "عالی بود", "کمی دیر رسید"])))
                        db.add(DriverRating(order_id=o.id, driver_id=o.driver_id, source="organization", score=rng.choice([4, 5, 5]), created_by_id=admin.id))
        db.commit()
        shift(db, O, m, local_dt(day, 0))
        # انتقال بین انبارها، تعیین تکلیف معیوب، انبارگردانی دوره‌ای
        if d % 15 == 7:
            m = marks(db, O)
            lines = [{"product_id": p.id, "quantity": 5} for p in rng.sample(pool[:40], 3) if stock_of("تهران", p)[1] > 20]
            if lines:
                t = transfer_order_service.create(db, admin, TransferCreate(from_warehouse_id=whs["تهران"].id, to_warehouse_id=whs["اصفهان"].id,
                                                                            lines=lines, note="تأمین انبار اصفهان"))
                transfer_order_service.ship(db, admin, t["id"])
                t = transfer_order_service.get(db, admin, t["id"])
                transfer_order_service.receive(db, admin, t["id"], TransferReceiveIn(location_id=special["اصفهان"]["rcv"].id, lines=[
                    {"line_id": ln["id"], "received_quantity": ln["quantity"]} for ln in t["lines"]]))
                counts["transfers"] += 1
            shift(db, O, m, local_dt(day, 11))
        if d % 12 == 3:
            m = marks(db, O)
            for p in rng.sample(pool[:60], 2):
                loc_ = opening.get(("تهران", p.id))
                inv, free = stock_of("تهران", p)
                if not loc_ or free < 10:
                    continue
                try:
                    inventory_service.change_status(db, managers["تهران"], StatusChangeCreate(
                        product_id=p.id, warehouse_id=whs["تهران"].id, from_status="available", to_status="damaged", quantity=2,
                        reason="آسیب هنگام جابه‌جایی با لیفتراک", location_id=loc_.id))
                    disposition_service.dispose(db, managers["تهران"], DispositionCreate(
                        product_id=p.id, warehouse_id=whs["تهران"].id, from_status="damaged", action=rng.choice(["scrap", "repair"]),
                        quantity=2, location_id=loc_.id, reason="کارتن له شده و کالا قابل فروش نیست"))
                    counts["dispositions"] += 1
                except Exception as e:  # noqa: BLE001 — موجودی آن محل ممکن است جابه‌جا شده باشد
                    db.rollback()
                    print("  (تعیین تکلیف رد شد:", str(e)[:80], ")")
            shift(db, O, m, local_dt(day, 15))
        if d in (DAYS - 20, 60, 25):
            m = marks(db, O)
            st = stocktake_service.create(db, managers["تهران"], warehouse_id=whs["تهران"].id, scope="partial", product_ids=[p.id for p in pool[:25]],
                                          title=None, note="شمارش دوره‌ای کلاس A", count_type="partial", by_location=True)
            obj = db.get(__import__("app.models", fromlist=["Stocktake"]).Stocktake, st["id"])
            for ln in obj.lines:
                exp = stocktake_service._expected(db, obj, ln)
                stocktake_service.count(db, managers["تهران"], st["id"], ln.id, max(0, exp + (rng.choice([-2, -1, 1]) if rng.random() < 0.12 else 0)))
            stocktake_service.submit(db, managers["تهران"], st["id"])
            stocktake_service.approve(db, admin, st["id"], {}, "تأیید پس از بازبینی مغایرت‌ها")
            counts["stocktakes"] += 1
            shift(db, O, m, local_dt(day, 18))
        if d % 10 == 0:
            print(f"  … {d} روز مانده — {counts['orders']} سفارش ({(now() - t0).seconds} ثانیه)")

    # ---- امروز: سفارش‌های باز، راننده‌ها، نقشه، پیکینگ، بسته‌بندی، معوق، رسید و … ----
    today_orders = []
    for city in hubs:
        for status, k in (("pending", 4), ("assigned", 6), ("picking_up", 2), ("picked_up", 2), ("in_transit", 4)):
            for _ in range(k):
                o = make_order(city, today, status, rng.uniform(1, 6), now_based=True)
                if o:
                    o.created_at = now() - timedelta(hours=rng.uniform(1, 8))
                    o.fulfillment_state = "shipped" if status in ("picked_up", "in_transit") else "open"
                    today_orders.append(o)
        for _ in range(3):           # فردا (قفل برای راننده تا روز تحویل)
            make_order(city, today, "assigned", 26 + rng.uniform(0, 6), now_based=True)
    db.commit()
    for o in [o for o in today_orders if o.status == "in_transit"]:
        hours = rng.uniform(1.5, 5)
        departed = now() - timedelta(hours=hours)
        o.delivery_window_start = departed
        for h in o.history:
            if h.to_status == "in_transit":
                h.changed_at = departed
        route_service.freeze_route(db, o)
        if o.route:
            reach = geo.AVERAGE_SPEED_KMH * (hours - 0.3)
            for pt in o.route["points"][1:-1]:
                if pt["km"] > reach:
                    break
                db.add(OrderCheckpoint(organization_id=O, order_id=o.id, seq=pt["seq"], city=pt["label"], province=pt["province"],
                                       reported_by_id=o.driver_id, reached_at=departed + timedelta(hours=pt["km"] / geo.AVERAGE_SPEED_KMH)))
    db.commit()
    tehran = whs["تهران"]
    mgr = managers["تهران"]
    assigned = [o for o in today_orders if o.status == "assigned" and o.warehouse_id == tehran.id]
    try:
        if len(assigned) >= 5:
            done = picking_service.create_pick_list(db, mgr, PickListCreate(strategy="batch", order_ids=[assigned[0].id, assigned[1].id],
                                                                            staging_location_id=special["تهران"]["stg"].id))
            for ln in done["lines"]:
                picking_service.pick(db, mgr, ln["id"], PickIn(source_scan=ln["location_code"] or tehran.code, product_scan=ln["product_sku"],
                                                               lot_scan=ln.get("lot_number"), quantity=ln["quantity"]))
            for o in assigned[:2]:
                shipping_service.pack(db, mgr, o.id, PackIn(packages=[{"length_cm": 50, "width_cm": 40, "height_cm": 30, "items": [
                    {"product_id": it.product_id, "quantity": it.quantity} for it in o.items]}]))
            shipping_service.create_shipment(db, mgr, ShipmentCreate(vehicle_id=assigned[0].vehicle_id, order_ids=[assigned[0].id]))
            wave = picking_service.create_pick_list(db, mgr, PickListCreate(strategy="batch", order_ids=[o.id for o in assigned[2:5]],
                                                                            staging_location_id=special["تهران"]["stg"].id))
            first = wave["lines"][0]
            picking_service.pick(db, mgr, first["id"], PickIn(source_scan=first["location_code"] or tehran.code, product_scan=first["product_sku"],
                                                              lot_scan=first.get("lot_number"), quantity=first["quantity"]))
    except Exception as e:  # noqa: BLE001
        db.rollback()
        print("  (پیکینگ امروز:", str(e)[:120], ")")
    # سفارش با معوق (موجودی کم) از مسیر واقعی سرویس
    low = sorted(pool, key=lambda p: stock_of("تهران", p)[1])[:3]
    for p in low:
        free = stock_of("تهران", p)[1]
        try:
            order_service.create_order(db, admin, OrderRequest(**{
                "items": [{"product_id": p.id, "quantity": free + rng.randint(5, 20)}], "customer": {"name": person(5), "mobile": mobile(77)},
                "destination_province": "تهران", "destination_city": "تهران", "destination_address": "تهران، خیابان پیروزی، پلاک ۸",
                "size": "m", "priority": True, "delivery_window_start": (now() + timedelta(hours=3)).isoformat(),
                "delivery_window_end": (now() + timedelta(hours=8)).isoformat(), "allow_backorder": True, "auto_assign": False}))
        except Exception as e:  # noqa: BLE001
            db.rollback()
            print("  (معوق:", str(e)[:100], ")")
    # رسید باز، رسید در انتظار بازرسی، وظیفه جانمایی باز، انتقال در راه
    insp = [p for p in pool if p.inspection_required][:2]
    receiving_service.create_receipt(db, admin, ReceiptCreate(receipt_type="purchase", warehouse_id=tehran.id, partner_id=suppliers[0].id,
                                                                  reference_number="PO-OPEN-1", expected_date=today + timedelta(days=1),
                                                                  lines=[{"product_id": p.id, "expected_quantity": 80} for p in pool[5:9]]))
    if insp:
        r2 = receiving_service.create_receipt(db, admin, ReceiptCreate(receipt_type="purchase", warehouse_id=tehran.id, partner_id=suppliers[4].id,
                                                                       reference_number="PO-QC-1", lines=[{"product_id": p.id, "expected_quantity": 40} for p in insp]))
        receiving_service.receive(db, mgr, r2["id"], ReceiveIn(location_id=special["تهران"]["rcv"].id, lines=[
            {"line_id": ln["id"], "quantity": 40, "lot_number": f"QC{ln['product_id']}", "expiry_date": today + timedelta(days=120)}
            if db.get(Product, ln["product_id"]).lot_tracked else {"line_id": ln["id"], "quantity": 40} for ln in r2["lines"]]))
    r3 = receiving_service.create_receipt(db, admin, ReceiptCreate(receipt_type="purchase", warehouse_id=tehran.id, partner_id=suppliers[2].id,
                                                                   reference_number="PO-PUT-1", lines=[{"product_id": p.id, "expected_quantity": 30} for p in pool[20:23]]))
    receiving_service.receive(db, mgr, r3["id"], ReceiveIn(location_id=special["تهران"]["rcv"].id, lines=[
        ({"line_id": ln["id"], "quantity": 30, "lot_number": f"PT{ln['product_id']}", "expiry_date": today + timedelta(days=200)}
         if db.get(Product, ln["product_id"]).lot_tracked else {"line_id": ln["id"], "quantity": 30}) for ln in r3["lines"]]))
    inspect_receipt("تهران", r3["id"], [{"quantity": 30, "lot_number": f"PT{p.id}" if p.lot_tracked else None} for p in pool[20:23]],
                    [(p, 30) for p in pool[20:23]], reject=False)
    lines = [{"product_id": p.id, "quantity": 4} for p in pool[30:33] if stock_of("تهران", p)[1] > 10]
    if lines:
        t = transfer_order_service.create(db, admin, TransferCreate(from_warehouse_id=tehran.id, to_warehouse_id=whs["مشهد"].id, lines=lines,
                                                                    note="ارسال به مشهد"))
        transfer_order_service.ship(db, admin, t["id"])
    # کالای قرنطینه/آسیب‌دیده منتظر تعیین تکلیف
    for p in pool[40:43]:
        lc = opening.get(("تهران", p.id))
        if lc and stock_of("تهران", p)[1] > 6:
            try:
                inventory_service.change_status(db, mgr, StatusChangeCreate(product_id=p.id, warehouse_id=tehran.id, from_status="available",
                                                                            to_status=rng.choice(["damaged", "quarantine", "defective"]), quantity=3,
                                                                            reason="مشکوک به آسیب در بازرسی دوره‌ای", location_id=lc.id))
            except Exception:  # noqa: BLE001
                db.rollback()
    # قانون تأمین مجدد محل‌های برداشت
    for k, b in enumerate(bins["تهران"][:10]):
        p = next((x for x in pool if opening.get(("تهران", x.id)) and opening[("تهران", x.id)].id == b.id), None)
        if p:
            replenishment_rule_service.save_rule(db, mgr, ReplenishmentRuleIn(location_id=b.id, product_id=p.id, min_quantity=40 + k * 5, max_quantity=200))
    try:
        replenishment_rule_service.generate(db, mgr, None)
    except Exception:  # noqa: BLE001
        db.rollback()
    # انبارگردانی فعال: مشهد قفل و نیمه‌شمرده، اصفهان منتظر بررسی
    st = stocktake_service.create(db, managers["مشهد"], warehouse_id=whs["مشهد"].id, scope="partial", product_ids=[p.id for p in pool[:12]],
                                  title=None, note="شمارش دوره‌ای با قفل محل‌ها", by_location=True, freeze_mode="lock",
                                  location_ids=[b.id for b in bins["مشهد"][:12]])
    from app.models import Stocktake
    obj = db.get(Stocktake, st["id"])
    for ln in obj.lines[: len(obj.lines) // 2]:
        stocktake_service.count(db, managers["مشهد"], st["id"], ln.id, stocktake_service._expected(db, obj, ln))
    st = stocktake_service.create(db, managers["اصفهان"], warehouse_id=whs["اصفهان"].id, scope="partial", product_ids=[p.id for p in pool[10:20]],
                                  title=None, note=None, by_location=True)
    obj = db.get(Stocktake, st["id"])
    for ln in obj.lines:
        stocktake_service.count(db, managers["اصفهان"], st["id"], ln.id, max(0, stocktake_service._expected(db, obj, ln) + rng.choice([0, 0, -3, 2])))
    if obj.lines:
        stocktake_service.submit(db, managers["اصفهان"], st["id"])

    # ---- رانندگان: مرخصی، تغییر خودرو؛ تیکت‌ها و پیام‌ها ----
    for i, (kind, status, leave, cat, days_ahead, reason) in enumerate((
            ("leave", "pending", "urgent", "sickness", 0.5, "تب و سرماخوردگی شدید؛ گواهی پزشک دارم."),
            ("leave", "pending", "normal", "family", 3, "مراسم عروسی خواهرم در شهرستان."),
            ("leave", "approved", "normal", "personal", 5, "کار اداری و تمدید گواهینامه."),
            ("leave", "rejected", "normal", "personal", 1, "سفر شخصی."),
            ("vehicle_change", "pending", None, None, 0, "خودروی جدید با ظرفیت بیشتر خریده‌ام."))):
        d = db.get(User, drivers[i])
        start = now() + timedelta(days=days_ahead)
        rq = DriverRequest(user_id=d.id, kind=kind, status=status, submitted_at=now() - timedelta(hours=6 + i), leave_type=leave, category=cat,
                           starts_at=start if kind == "leave" else None, ends_at=start + timedelta(days=1 if i else 0.5) if kind == "leave" else None,
                           reason=reason, reviewed_at=now() - timedelta(hours=1) if status in ("approved", "rejected") else None,
                           reviewed_by_id=admin.id if status in ("approved", "rejected") else None,
                           review_note="در این روزها سفارش زیاد داریم؛ لطفاً هفته بعد درخواست دهید." if status == "rejected" else None,
                           vehicle_data={"type": "truck", "model": "ایسوزو ۶ تن", "license_plate": fa_digits("۷۲ایران۶۱۲ع۴۴"), "max_weight_kg": 6000}
                           if kind == "vehicle_change" else None)
        if status == "approved":
            off = DriverTimeOff(user_id=d.id, starts_at=rq.starts_at, ends_at=rq.ends_at, reason=reason, created_by_id=admin.id)
            db.add(off)
            db.flush()
            rq.time_off_id = off.id
        db.add(rq)
    delivered = db.query(Order).filter(Order.status == "delivered").order_by(Order.id.desc()).limit(10).all()
    moving = [o for o in today_orders if o.status == "in_transit"]

    def ticket(code, subject, category, source, handler, waiting, msgs, order=None, requester=None, status="open", priority="normal",
               escalated=None, hours=3):
        t = Ticket(organization_id=O, code=code, subject=subject, category=category, source=source, handler=handler, status=status,
                   waiting_on=waiting, priority=priority, order_id=order.id if order else None, requester_user_id=requester.id if requester else None,
                   requester_name=(order.recipient_name if source == "customer" and order else requester.full_name if requester else None),
                   requester_mobile=order.recipient_mobile if source == "customer" and order else None,
                   access_token=secrets.token_urlsafe(24) if source == "customer" else None,
                   escalated_at=now() - timedelta(hours=1) if escalated else None, escalation_reason=escalated,
                   resolved_at=now() - timedelta(minutes=30) if status in ("resolved", "closed") else None,
                   created_at=now() - timedelta(hours=hours), last_activity_at=now() - timedelta(minutes=10))
        db.add(t)
        db.flush()
        for k, (side, name, body, vis) in enumerate(msgs):
            db.add(TicketMessage(organization_id=O, ticket_id=t.id, author_side=side, author_name=name, body=body, visibility=vis,
                                 created_at=t.created_at + timedelta(minutes=12 * (k + 1))))
    drv = db.get(User, drivers[1])
    if moving:
        ticket("TK-ARY0001", f"تأخیر در ارسال — {moving[0].tracking_code}", "delay", "customer", "org", "org",
               [("requester", moving[0].recipient_name, "سلام، سفارشم کی می‌رسد؟", "all")], order=moving[0])
    if delivered:
        ticket("TK-ARY0002", f"کالای اشتباه — {delivered[0].tracking_code}", "wrong_item", "customer", "org", "requester",
               [("requester", delivered[0].recipient_name, "به‌جای روغن ۱.۵ لیتری، ۴ لیتری آمده.", "all"),
                ("org", admin.full_name, "عذرخواهی می‌کنیم؛ فردا تعویض می‌شود. لطفاً کالا را نگه دارید.", "all")], order=delivered[0], hours=20)
        ticket("TK-ARY0003", f"آسیب‌دیدگی کالا — {delivered[1].tracking_code}", "damaged", "customer", "platform", "platform",
               [("requester", delivered[1].recipient_name, "کارتن پاره بود و دو قلم آسیب دیده.", "all"),
                ("org", admin.full_name, "راننده می‌گوید سالم تحویل داده؛ عکس تحویل نداریم.", "side")], order=delivered[1], priority="high",
               escalated="برای اختلاف تحویل، ثبت عکس هنگام تحویل لازم است؛ راهنمایی کنید.", hours=28)
        ticket("TK-ARY0004", f"تغییر نشانی — {delivered[2].tracking_code}", "address", "customer", "org", "none",
               [("requester", delivered[2].recipient_name, "لطفاً به محل کارم تحویل دهید.", "all"),
                ("org", admin.full_name, "انجام شد ✓", "all")], order=delivered[2], status="resolved", hours=50)
    ticket("TK-ARY0005", "پورسانت سفرهای دیروز", "payment", "driver", "org", "org",
           [("requester", drv.full_name, "پورسانت سه سفر دیروز در کارنامه‌ام نیامده.", "all")], requester=drv, hours=6)
    ticket("TK-ARY0006", "باتری خودرو", "vehicle", "driver", "org", "requester",
           [("requester", db.get(User, drivers[2]).full_name, "باتری خودرو ضعیف است؛ امروز دیرتر می‌رسم.", "all"),
            ("org", mgr.full_name, "اشکال ندارد؛ سفارش‌های بعدازظهر به همکارتان داده شد.", "all")], requester=db.get(User, drivers[2]), hours=4)
    ticket("TK-ARY0007", "خروجی ماهانه پورسانت رانندگان", "feature", "org", "platform", "platform",
           [("org", admin.full_name, "امکان خروجی اکسل پورسانت ماهانه رانندگان را دارید؟", "all")], requester=admin, hours=30)
    ticket("TK-ARY0008", "دسترسی مدیر انبار اصفهان", "account", "org", "platform", "none",
           [("org", admin.full_name, "مدیر انبار اصفهان گزارش فعالیت را نمی‌بیند.", "all"),
            ("platform", "پشتیبانی پسینه", "از صفحه «مجوزهای نقش‌ها» مجوز «مشاهده گزارش فعالیت» را بدهید.", "all")],
           requester=admin, status="closed", hours=72)
    db.commit()

    # ---- کنترل: ABC، نقطه سفارش، برچسب، مجوز سفارشی، چک‌لیست ----
    replenishment_rule_service.classify(db, admin)
    for inv in db.query(__import__("app.models", fromlist=["Inventory"]).Inventory).filter_by(stock_status=AVAILABLE).all():
        if inv.id % 3:
            inv.rop_mode = "auto"
    db.commit()
    replenishment_service.recalculate(db, O)
    db.commit()
    leaf_ids = [b.id for b in bins["تهران"]][: int(len(bins["تهران"]) * 0.85)]
    label_service.print_labels(db, admin, label_type="location", ids=leaf_ids)
    label_service.print_labels(db, admin, label_type="product", ids=[p.id for p in pool[:30]])
    permission_service.update(db, admin, "warehouse_manager", "audit.view", True, "سرپرستان انبار گزارش فعالیت انبار خودشان را ببینند")
    permission_service.update(db, admin, "warehouse_manager", "stocktake.approve_minor", True, "تأیید مغایرت‌های کوچک توسط مدیر انبار")
    for key in ("permissions_reviewed", "training_done", "labels_applied", "opening_signed"):
        db.add(CutoverCheck(organization_id=O, item_key=key, done=True, note="انجام شد", updated_by_id=admin.id))
    db.commit()

    # ---- پایان: مانده بعد از هر گردش به ترتیب زمان، پاک‌سازی اعلان‌های قدیمی ----
    with stock_ledger.maintenance(db):
        db.execute(text("""UPDATE stock_movements m SET balance_after = s.b FROM (SELECT id, SUM(quantity_change) OVER
            (PARTITION BY inventory_id ORDER BY created_at, id) b FROM stock_movements WHERE organization_id = :o) s WHERE m.id = s.id"""), {"o": O})
        db.execute(text("""UPDATE stock_movement_lines m SET balance_after = s.b FROM (SELECT l.id, SUM(l.quantity_change) OVER
            (PARTITION BY l.balance_id ORDER BY mv.created_at, l.id) b FROM stock_movement_lines l JOIN stock_movements mv ON mv.id = l.movement_id
            WHERE l.organization_id = :o) s WHERE m.id = s.id"""), {"o": O})
        db.execute(text("DELETE FROM notifications WHERE organization_id = :o AND created_at < :t"), {"o": O, "t": now() - timedelta(days=5)})
    db.commit()
    bad = stock_ledger.find_mismatches(db)
    totals = {name: db.query(model).count() for name, model in (("سفارش", Order), ("گردش کالا", StockMovement), ("ردیف ریز گردش", StockMovementLine),
                                                                ("سطر برداشت", PickLine), ("محموله", Shipment), ("مشتری", Customer))}
    set_tenant(db, None)
    print(f"✅ ساخته شد در {(now() - t0).seconds} ثانیه: " + "، ".join(f"{v:,} {k}" for k, v in totals.items()))
    print(f"   رسید {counts['receipts']}، انتقال {counts['transfers']}، انبارگردانی {counts['stocktakes']}، تعیین تکلیف {counts['dispositions']}")
    print("✅ دفتر گردش سالم است." if not bad else f"⚠️ ناسازگاری دفتر گردش: {bad[:3]}")
    print(f"🔑 ورود: arya_admin، arya_tehran، arya_isfahan، arya_mashhad، arya_driver01..15، arya_applicant1..4 — رمز همه: {PASSWORD}")
    print("🔗 دعوت راننده: /join/ARYA1405")


if __name__ == "__main__":
    session = SessionLocal()
    try:
        session.execute(text("SELECT 1"))
        set_tenant(session, None)
        if "--delete" in sys.argv or "--reset" in sys.argv:
            delete_org(session)
        if "--delete" not in sys.argv:
            build(session)
    finally:
        session.close()
    _ = SKIP_TENANT_FILTER, PENDING
