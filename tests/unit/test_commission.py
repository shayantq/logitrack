"""
تست اصلی مرحله ۸: «با داده نمونه، لول و پورسانت دقیقاً طبق قانون تعریف‌شده محاسبه شود.»

قانون پیش‌فرض:
  سطح D: بدون شرط ← ۱۵٪ | سطح C: ۵۰ تحویل + ۳۰ روز + امتیاز ≥ ۴٫۰ ← ۱۲٪ | B: ۲۰۰/۹۰/۴٫۴ ← ۱۰٪ | A: ۵۰۰/۱۸۰/۴٫۷ ← ۸٪
  پله روزانه: سفر ۱ تا ۵ ← ۱۰۰٪ درصد سطح | ۶ تا ۱۰ ← ۵۰٪ | از ۱۱ ← ۰
  پورسانت = کرایه × درصد سطح × ضریب پله ؛ سطح بر اساس تحویل‌های «قبل از» همین سفارش
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import CommissionPlan, DriverProfile, DriverRating, Inventory, Order, Product, RoleEnum, User, Vehicle
from app.schemas.order import OrderStatusRequest
from app.services import commission_service, order_service
from app.services.commission_service import DEFAULT_LEVELS, DEFAULT_TIERS, compute, level_for, tier_multiplier
from tests.factories import order_request

PLAN = {"base_fare": 500_000, "fare_per_kg": 5_000, "levels": DEFAULT_LEVELS, "tiers": DEFAULT_TIERS}
NOW = datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# قانون، بدون دیتابیس
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("deliveries,days,rating,expected", [
    (0, 0, None, "D"),
    (49, 40, 4.2, "D"),        # یک تحویل کم
    (50, 40, 4.2, "C"),
    (50, 29, 4.2, "D"),        # سابقه کم
    (50, 40, 3.9, "D"),        # امتیاز کم
    (50, 40, None, "D"),       # بدون امتیاز، شرط امتیاز برقرار نیست
    (250, 100, 4.5, "B"),
    (600, 200, 4.6, "B"),      # برای A امتیاز ۴٫۷ لازم است
    (600, 200, 4.8, "A"),
])
def test_level_rule(deliveries, days, rating, expected):
    assert DEFAULT_LEVELS[level_for(DEFAULT_LEVELS, deliveries, days, rating)]["code"] == expected


@pytest.mark.parametrize("trip,multiplier", [(1, 100), (5, 100), (6, 50), (10, 50), (11, 0), (40, 0)])
def test_daily_tiers(trip, multiplier):
    assert tier_multiplier(DEFAULT_TIERS, trip) == multiplier


def test_commission_formula():
    assert compute(PLAN, 1_000_000, 49, 40, 4.2, 1)["commission"] == 150_000          # D ۱۵٪
    assert compute(PLAN, 1_000_000, 50, 40, 4.2, 1)["commission"] == 120_000          # C ۱۲٪
    half = compute(PLAN, 1_000_000, 50, 40, 4.2, 6)
    assert (half["percent"], half["commission"], half["earning"]) == (6.0, 60_000, 940_000)
    assert compute(PLAN, 1_000_000, 50, 40, 4.2, 11)["commission"] == 0               # از سفر ۱۱ رایگان
    assert compute(PLAN, 777_777, 0, 0, None, 1)["commission"] == 116_667             # گرد به ریال
    assert commission_service.default_fee(PLAN, 42.3) == 712_000                        # ۵۰۰٬۰۰۰ + ۵٬۰۰۰×۴۲٫۳ ← گرد به هزار


# ---------------------------------------------------------------------------
# روز کاری واقعی راننده روی دیتابیس
# ---------------------------------------------------------------------------
@pytest.fixture()
def world(db_session):
    db = db_session
    admin = User(username="adm", email="a@t.io", role=RoleEnum.ORG_ADMIN, hashed_password="x")
    driver = User(username="drv", email="d@t.io", role=RoleEnum.DRIVER, hashed_password="x", city="تهران",
                  created_at=NOW - timedelta(days=40))
    db.add_all([admin, driver])
    db.commit()
    db.add(DriverProfile(user_id=driver.id))
    vehicle = Vehicle(license_plate="V-1", type="van", capacity_kg=100_000, status="available", driver_id=driver.id, city="تهران")
    product = Product(name="بار", sku="SKU-C", price=1, weight_kg=1)
    db.add_all([vehicle, product])
    db.commit()
    db.add(Inventory(product_id=product.id, quantity=1000))
    # ۴۸ تحویل موفق در روزهای قبل (برای «سابقه»)
    for i in range(48):
        db.add(Order(tracking_code=f"LT-OLD{i:05d}", status="delivered", size="m", priority=False,
                     delivery_window_start=NOW - timedelta(days=3), delivery_window_end=NOW - timedelta(days=3),
                     destination_city="تهران", total_weight_kg=1, vehicle_id=vehicle.id, driver_id=driver.id,
                     delivered_at=NOW - timedelta(days=3)))
    # امتیاز وزنی: (۴×۰٫۵ + ۵×۰٫۳۵) / ۰٫۸۵ = ۴٫۴۱
    db.add_all([DriverRating(driver_id=driver.id, source="organization", score=4),
                DriverRating(driver_id=driver.id, source="customer", score=5)])
    db.commit()
    return db, admin, driver, vehicle, product


def _deliver_new_order(db, admin, driver, vehicle, product, fee=1_000_000):
    order = order_service.create_order(db, admin, order_request(product.id, vehicle.id, delivery_fee=fee))
    order_service.update_order_status(db, driver, order.id, OrderStatusRequest(order_status="picked_up"))
    order_service.update_order_status(db, driver, order.id, OrderStatusRequest(order_status="in_transit"))
    return order_service.update_order_status(db, driver, order.id, OrderStatusRequest(order_status="delivered"))


def test_driver_day_levels_up_mid_day_and_passes_daily_tiers(world):
    db, admin, driver, vehicle, product = world
    assert commission_service.weighted_rating(db, driver.id)[0] == 4.41

    results = [_deliver_new_order(db, admin, driver, vehicle, product) for _ in range(7)]
    got = [(o.day_trip_number, o.commission_level, o.commission_percent, o.commission_amount, o.driver_earning) for o in results]
    assert got == [
        (1, "D", 15.0, 150_000, 850_000),     # ۴۸ تحویل قبلی ← D
        (2, "D", 15.0, 150_000, 850_000),     # ۴۹ ← هنوز D
        (3, "C", 12.0, 120_000, 880_000),     # ۵۰ تحویل + ۴۰ روز + امتیاز ۴٫۴۱ ← C
        (4, "C", 12.0, 120_000, 880_000),
        (5, "C", 12.0, 120_000, 880_000),
        (6, "C", 6.0, 60_000, 940_000),       # از سفر ششم روز ← نصف
        (7, "C", 6.0, 60_000, 940_000),
    ]
    assert sum(o.commission_amount for o in results) == 780_000
    assert all(o.delivered_at and o.rating_token and o.driver_id == driver.id for o in results)


def test_rules_change_affects_only_future_orders(world):
    db, admin, driver, vehicle, product = world
    first = _deliver_new_order(db, admin, driver, vehicle, product)
    assert first.commission_amount == 150_000
    db.add(CommissionPlan(base_fare=0, fare_per_kg=0, levels=[{**DEFAULT_LEVELS[0], "commission_percent": 20}], tiers=DEFAULT_TIERS))
    db.commit()
    second = _deliver_new_order(db, admin, driver, vehicle, product)
    db.refresh(first)
    assert (first.commission_amount, second.commission_amount) == (150_000, 200_000)


def test_default_fee_failed_orders_and_trip_counting(world):
    db, admin, driver, vehicle, product = world
    auto_fee = order_service.create_order(db, admin, order_request(product.id, vehicle.id, quantity=3))
    assert auto_fee.delivery_fee == 515_000                                          # ۵۰۰٬۰۰۰ + ۳ کیلو × ۵٬۰۰۰

    failed = order_service.create_order(db, admin, order_request(product.id, vehicle.id, delivery_fee=1_000_000))
    failed = order_service.update_order_status(db, driver, failed.id, OrderStatusRequest(order_status="failed"))
    assert failed.commission_amount is None and failed.delivered_at is None         # ناموفق ← بدون پورسانت

    order_service.update_order_status(db, driver, auto_fee.id, OrderStatusRequest(order_status="picked_up"))
    order_service.update_order_status(db, driver, auto_fee.id, OrderStatusRequest(order_status="in_transit"))
    done = order_service.update_order_status(db, driver, auto_fee.id, OrderStatusRequest(order_status="delivered"))
    assert (done.day_trip_number, done.commission_amount) == (1, round(515_000 * 0.15))   # ناموفق سفر حساب نمی‌شود
