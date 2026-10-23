"""
تست یکپارچگی حیاتی: سناریوی «کاهش هم‌زمان موجودی یک کالا»
(دقیقاً همان سناریویی که در مستندات پروژه به‌عنوان معیار پذیرش خواسته شده بود.)

⚠️ این تست از یک دیتابیس PostgreSQL کاملاً جدا (logitrack_test) استفاده
می‌کند — نه دیتابیس اصلی/دمو — و اگر آن دیتابیس در دسترس نباشد، به‌طور
خودکار skip می‌شود؛ چون SELECT ... FOR UPDATE (راه‌حل ما برای جلوگیری از
overselling) یک قابلیت قفل سطح ردیف واقعی در PostgreSQL است و SQLite
رفتار مشابهی ندارد.

اجرا (داخل کانتینر داکر):
    docker compose exec web pytest tests/integration -v -m integration
"""
import threading

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.tenancy import set_tenant
from app.models import User, RoleEnum, Vehicle, Product, Inventory, Organization
from app.services import order_service
from app.services.exceptions import ConflictError
from tests.factories import default_warehouse, order_request
from tests.integration.conftest import TEST_DATABASE_URL

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL or "postgresql" not in TEST_DATABASE_URL,
        reason="این تست فقط روی PostgreSQL واقعی معنا دارد (برای تست واقعی SELECT ... FOR UPDATE)."
    ),
]


@pytest.fixture()
def pg_session_factory():
    engine = create_engine(TEST_DATABASE_URL, pool_size=5, max_overflow=5)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    yield SessionLocal
    engine.dispose()


@pytest.fixture()
def race_condition_setup(pg_session_factory):
    """یک کالا با موجودی دقیقاً ۱ عدد + یک خودروی آزاد + یک ادمین آماده می‌کند، و در پایان تمیز می‌کند."""
    db = pg_session_factory()

    org = Organization(name="سازمان تست رقابت", slug="race-test-org")
    db.add(org)
    db.commit()
    set_tenant(db, org.id)

    driver = User(username="race_test_driver", email="race_driver@test.local", role=RoleEnum.DRIVER, hashed_password="x")
    admin = User(username="race_test_admin", email="race_admin@test.local", role=RoleEnum.ORG_ADMIN, hashed_password="x")
    db.add_all([driver, admin])
    db.commit()
    db.refresh(driver)
    db.refresh(admin)

    vehicle = Vehicle(license_plate="RACE-TEST-PLATE", type="van", capacity_kg=5000,
                       status="available", driver_id=driver.id, city="تهران")
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)

    product = Product(name="کالای تست رقابت هم‌زمان", sku="RACE-TEST-SKU", price=1000, weight_kg=1.0)
    db.add(product)
    db.commit()
    db.refresh(product)

    db.add(Inventory(product_id=product.id, warehouse_id=default_warehouse(db).id, quantity=1, reorder_point=10))  # ⚠️ فقط ۱ عدد موجودی!
    db.commit()

    try:
        yield {"product_id": product.id, "vehicle_id": vehicle.id, "admin_id": admin.id}
    finally:
        # پاکسازی کامل: حذف سازمان همه داده‌هایش را هم (با ON DELETE CASCADE) پاک می‌کند؛
        # دفتر گردش کالا تغییرناپذیر است، پس فقط در حالت نگهداری دفتر
        db.rollback()
        set_tenant(db, None)
        db.execute(text("SELECT set_config('pasineh.ledger_maintenance', 'on', true)"))
        db.query(Organization).filter(Organization.id == org.id).delete()
        db.commit()
        db.close()


def test_two_simultaneous_orders_for_last_unit_only_one_succeeds(pg_session_factory, race_condition_setup):
    """
    سناریوی حیاتی: موجودی فقط ۱ عدد است. دو درخواست سفارش برای همین کالا
    دقیقاً هم‌زمان (با threading واقعی، هرکدام با اتصال جدای خودشان به
    دیتابیس) ارسال می‌شوند.

    نتیجه‌ی مورد انتظار: دقیقاً یکی موفق می‌شود، دیگری با خطای «موجودی
    کافی نیست» رد می‌شود — نه اینکه هر دو موفق شوند و موجودی منفی شود
    (که دقیقاً همان باگ اصلی «فروش بیش از موجودی» بود که این پروژه با آن
    شروع شد).
    """
    product_id = race_condition_setup["product_id"]
    vehicle_id = race_condition_setup["vehicle_id"]
    admin_id = race_condition_setup["admin_id"]

    results = {}
    start_barrier = threading.Barrier(2)  # هر دو ترد دقیقاً همزمان شروع کنند

    def place_order(thread_name):
        db = pg_session_factory()
        try:
            local_admin = db.get(User, admin_id)
            set_tenant(db, local_admin.organization_id)
            request = order_request(product_id, vehicle_id, city="تهران", quantity=1)
            start_barrier.wait()  # اطمینان از هم‌زمانی واقعی دو ترد
            order_service.create_order(db, local_admin, request)
            results[thread_name] = "success"
        except ConflictError:
            results[thread_name] = "insufficient_stock"
        except Exception as e:  # noqa: BLE001 -- می‌خواهیم هر خطای غیرمنتظره را هم در نتیجه ببینیم
            results[thread_name] = f"unexpected_error: {e!r}"
        finally:
            db.close()

    thread_a = threading.Thread(target=place_order, args=("thread_a",))
    thread_b = threading.Thread(target=place_order, args=("thread_b",))
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=15)
    thread_b.join(timeout=15)

    outcomes = list(results.values())
    assert outcomes.count("success") == 1, f"دقیقاً باید یک سفارش موفق شود. نتیجه واقعی: {results}"
    assert outcomes.count("insufficient_stock") == 1, f"دقیقاً باید یک سفارش رد شود. نتیجه واقعی: {results}"

    verify_db = pg_session_factory()
    try:
        inv = verify_db.query(Inventory).filter(Inventory.product_id == product_id).first()
        # سفارش فقط رزرو می‌کند: تنها واحد موجود دقیقاً یک‌بار رزرو شده و موجودی آزاد صفر است
        assert (inv.quantity, inv.reserved_quantity) == (1, 1), \
            f"رزرو باید دقیقاً ۱ باشد، ولی {inv.reserved_quantity} است — یعنی رزرو دوباره (overselling) رخ داده!"
    finally:
        verify_db.close()
