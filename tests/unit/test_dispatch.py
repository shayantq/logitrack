"""
تست‌های مرحله ۷: زمان‌بندی و تخصیص هوشمند.

سناریوی اصلی مرحله: «سفارش ۱۵۰ کیلویی، چهارشنبه ساعت ۱۰ تا ۱۲، مقصد قزوین»
فقط باید رانندگان واجد شرایط را پیشنهاد کند؛ هر راننده دیگر با دلیل مشخص کنار گذاشته شود.
"""
from datetime import date, datetime, time, timedelta

import pytest

from app.models import DriverProfile, DriverShift, DriverTimeOff, Inventory, Order, Product, RoleEnum, User, Vehicle
from app.schemas.order import OrderAssignRequest
from app.services import dispatch_service, order_service
from app.services.dispatch_service import local_to_utc
from app.services.exceptions import ConflictError
from tests.factories import default_warehouse, order_request

WEDNESDAY = 2   # weekday پایتون


def next_weekday(weekday: int) -> date:
    today = date.today()
    return today + timedelta(days=(weekday - today.weekday()) % 7 or 7)


WED = next_weekday(WEDNESDAY)
WIN_START = local_to_utc(datetime.combine(WED, time(10)))      # چهارشنبه ۱۰:۰۰ به وقت ایران
WIN_END = local_to_utc(datetime.combine(WED, time(12)))


class World:
    def __init__(self, db):
        self.db = db
        self.n = 0
        self.admin = self.user("admin", RoleEnum.ORG_ADMIN)

    def user(self, tag, role=RoleEnum.DRIVER, **kw):
        u = User(username=f"u_{tag}", email=f"{tag}@t.io", role=role, hashed_password="x", full_name=tag, **kw)
        self.db.add(u)
        self.db.commit()
        return u

    def driver(self, tag, *, city="قزوین", capacity=1000, vtype="van", vstatus="available", shifts=((WEDNESDAY, 8, 16),),
               intercity=False, max_daily=None, status="approved", province=None):
        d = self.user(tag, city=city, driver_status=status)
        self.db.add(DriverProfile(user_id=d.id, intercity=intercity, max_daily_orders=max_daily, province=province))
        for weekday, start, end in shifts:
            self.db.add(DriverShift(user_id=d.id, weekday=weekday, start_time=time(start), end_time=time(end)))
        v = Vehicle(license_plate=f"P-{tag}", type=vtype, capacity_kg=capacity, status=vstatus, driver_id=d.id, city=city)
        self.db.add(v)
        self.db.commit()
        return v

    def existing_order(self, vehicle, kg, start=WIN_START, end=WIN_END, city="قزوین", status="assigned"):
        self.n += 1
        o = Order(tracking_code=f"LT-EX{self.n:05d}", status=status, size="m", priority=False,
                  delivery_window_start=start, delivery_window_end=end, destination_city=city,
                  total_weight_kg=kg, vehicle_id=vehicle.id)
        self.db.add(o)
        self.db.commit()
        return o


@pytest.fixture()
def world(db_session):
    return World(db_session)


def _suggest(db, weight=150, city="قزوین", province="قزوین", start=WIN_START, end=WIN_END):
    return dispatch_service.suggest(db, weight=weight, window_start=start, window_end=end,
                                    destination_city=city, destination_province=province)


def test_wednesday_10am_150kg_returns_only_eligible_drivers(world):
    db = world.db
    a = world.driver("A_best")                                                     # هم‌شهر، در شیفت، ظرفیت متناسب
    b = world.driver("B_off_shift", shifts=((5, 8, 16),))                          # فقط شنبه کار می‌کند
    c = world.driver("C_small", capacity=100, vtype="motorcycle")                  # ظرفیت کم
    d = world.driver("D_full")                                                      # ۹۰۰ کیلو در همان بازه رزرو
    world.existing_order(d, 900)
    e = world.driver("E_leave")                                                     # مرخصی
    db.add(DriverTimeOff(user_id=e.driver_id, starts_at=local_to_utc(datetime.combine(WED, time(0))),
                         ends_at=local_to_utc(datetime.combine(WED + timedelta(days=1), time(0))), reason="مرخصی"))
    f = world.driver("F_tehran_local", city="تهران")                               # شهر دیگر، بین‌شهری نمی‌برد
    g = world.driver("G_tehran_intercity", city="تهران", intercity=True)           # شهر دیگر ولی بین‌شهری می‌برد
    h = world.driver("H_daily_cap", max_daily=1)                                    # سهمیه روزانه پر
    world.existing_order(h, 10, start=WIN_START + timedelta(hours=5), end=WIN_END + timedelta(hours=5))
    i = world.driver("I_unapproved", status="submitted")                            # احراز هویت نشده
    j = world.driver("J_maintenance", vstatus="maintenance")                        # در تعمیر
    k = world.driver("K_no_schedule", shifts=())                                    # برنامه ثبت نشده ← همیشه در دسترس
    l = world.driver("L_truck", capacity=20000, vtype="truck")                      # کامیون؛ مجاز ولی نامتناسب
    m = world.driver("M_short_overlap", shifts=((WEDNESDAY, 11, 16),))              # یک ساعت از بازه را پوشش می‌دهد ← مجاز
    n = world.driver("N_edge", shifts=((WEDNESDAY, 6, 10),))                        # شیفت دقیقاً ساعت ۱۰ تمام می‌شود
    db.commit()

    result = _suggest(db)
    candidates = [c["vehicle_id"] for c in result["candidates"]]
    excluded = {x["vehicle_id"]: x["reason"] for x in result["excluded"]}

    assert set(candidates) == {a.id, g.id, k.id, l.id, m.id}
    assert candidates[0] == a.id                                  # بهترین گزینه: هم‌شهر و متناسب
    assert candidates.index(l.id) > candidates.index(a.id)        # کامیون برای ۱۵۰ کیلو اولویت پایین‌تر
    assert candidates.index(g.id) > candidates.index(a.id)        # بین‌شهری بعد از هم‌شهری
    assert "خارج از شیفت" in excluded[b.id] and "چهارشنبه" in excluded[b.id]
    assert "ظرفیت خودرو" in excluded[c.id]
    assert "پر است" in excluded[d.id]
    assert "مرخصی" in excluded[e.id]
    assert "بین‌شهری" in excluded[f.id]
    assert "سقف سفارش روزانه" in excluded[h.id]
    assert "احراز هویت" in excluded[i.id]
    assert "تعمیر" in excluded[j.id]
    assert "خارج از شیفت" in excluded[n.id]
    best = result["candidates"][0]
    assert "هم‌شهر با مقصد" in best["reasons"] and best["free_kg"] == 1000


def test_same_province_counts_as_local_for_kyc_drivers(world):
    db = world.db
    v = world.driver("abyek", city="آبیک", province="قزوین")
    assert [c["vehicle_id"] for c in _suggest(db, city="قزوین", province="قزوین")["candidates"]] == [v.id]
    assert _suggest(db, city="تبریز", province="آذربایجان شرقی")["candidates"] == []


def test_capacity_is_per_time_window_not_per_day(world):
    """۹۰۰ کیلو صبح، بار عصر را مسدود نمی‌کند؛ ولی بار هم‌پوشان را چرا."""
    db = world.db
    v = world.driver("cap", shifts=((WEDNESDAY, 8, 20),))
    world.existing_order(v, 900)
    assert _suggest(db, weight=150)["candidates"] == []
    later = _suggest(db, weight=150, start=WIN_START + timedelta(hours=4), end=WIN_END + timedelta(hours=4))
    assert [c["vehicle_id"] for c in later["candidates"]] == [v.id]
    assert _suggest(db, weight=100)["candidates"][0]["free_kg"] == 100         # ۱۰۰ کیلوی باقی‌مانده هنوز جا دارد


def test_finished_orders_free_capacity_but_count_toward_daily_cap(world):
    db = world.db
    v = world.driver("fin", max_daily=2)
    world.existing_order(v, 900, status="canceled")
    world.existing_order(v, 900, status="delivered", start=WIN_START - timedelta(hours=2), end=WIN_START - timedelta(hours=1))
    only = _suggest(db)["candidates"]
    assert [c["vehicle_id"] for c in only] == [v.id] and only[0]["day_orders"] == 1
    world.existing_order(v, 5, status="delivered", start=WIN_END + timedelta(hours=1), end=WIN_END + timedelta(hours=2))
    assert _suggest(db)["candidates"] == []


def test_consolidation_prefers_driver_already_going_to_same_city(world):
    db = world.db
    a = world.driver("a1")
    b = world.driver("b1")
    world.existing_order(b, 100, city="قزوین")
    result = _suggest(db, weight=100)
    assert result["candidates"][0]["vehicle_id"] == b.id
    assert any("تجمیع" in r for r in result["candidates"][0]["reasons"])
    assert a.id in [c["vehicle_id"] for c in result["candidates"]]


# ---------------------------------------------------------------------------
# اتصال به ثبت/تخصیص سفارش
# ---------------------------------------------------------------------------
def _stock(db, weight=150, qty=50):
    p = Product(name="بار ۱۵۰ کیلویی", sku=f"SKU-{weight}", price=1, weight_kg=weight)
    db.add(p)
    db.commit()
    db.add(Inventory(product_id=p.id, warehouse_id=default_warehouse(db).id, quantity=qty))
    db.commit()
    return p


def _wed_request(product_id, vehicle_id=None, **kw):
    return order_request(product_id, vehicle_id, city="قزوین", destination_province="قزوین",
                         delivery_window_start=WIN_START.isoformat() + "Z", delivery_window_end=WIN_END.isoformat() + "Z", **kw)


def test_auto_assign_uses_best_candidate_and_respects_capacity(world):
    db = world.db
    a = world.driver("auto_a", capacity=400)
    b = world.driver("auto_b", capacity=1000)
    product = _stock(db)
    first = order_service.create_order(db, world.admin, _wed_request(product.id, quantity=2))   # ۳۰۰ کیلو
    assert first.vehicle_id == a.id                                    # متناسب‌ترین خودرو
    second = order_service.create_order(db, world.admin, _wed_request(product.id, quantity=2))
    assert second.vehicle_id == b.id                                   # a فقط ۱۰۰ کیلو جا دارد
    db.refresh(a)
    assert a.status == "available"                                     # تخصیص دیگر خودرو را «مشغول» نمی‌کند


def test_manual_assignment_rejects_ineligible_vehicle_with_reason(world):
    db = world.db
    off = world.driver("manual_off", shifts=((5, 8, 16),))
    product = _stock(db)
    with pytest.raises(ConflictError, match="خارج از شیفت"):
        order_service.create_order(db, world.admin, _wed_request(product.id, off.id))

    pending = order_service.create_order(db, world.admin, _wed_request(product.id, auto_assign=False))
    with pytest.raises(ConflictError, match="هیچ راننده‌ای"):
        order_service.assign_vehicle(db, world.admin, pending.id, OrderAssignRequest())
    ok = world.driver("manual_ok")
    assigned = order_service.assign_vehicle(db, world.admin, pending.id, OrderAssignRequest(vehicle_id=ok.id))
    assert (assigned.status, assigned.vehicle_id) == ("assigned", ok.id)
