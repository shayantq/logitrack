"""
سابقه فروش نمونه برای «نقطه سفارش هوشمند» و «برآورد سرمایه خرید».

برای سازمان‌های نمونه (سازمان پیش‌فرض و فروشگاه نمونه قزوین)، ۸ ماه فروش روزانه (با روند، الگوی هفتگی و نوسان)
و خریدهای دوره‌ای در دفتر گردش ثبت می‌کند، بهای خرید کالاها را کامل می‌کند (چند کالا عمداً بدون بها می‌مانند تا
هشدار «بهای خرید ثبت نشده» دیده شود) و زمان تأمین متنوع می‌گذارد. همه گردش‌ها با stock_ledger ثبت می‌شوند؛ مانده بعد
از گردش‌ها به ترتیب تاریخ دوباره حساب می‌شود تا دفتر گردش خوانا بماند.

idempotent است: اگر سابقه نمونه یک سازمان قبلاً ثبت شده باشد، کاری نمی‌کند.
    docker compose exec web python seed_sales_history.py
"""
from __future__ import annotations

import math
import random
from datetime import datetime, time, timedelta

from sqlalchemy.orm import joinedload

from app.core.tenancy import set_tenant
from app.core.wms import AVAILABLE
from app.models import Inventory, Organization, ProductPrice, StockMovement
from app.models_notification import Notification
from app.services import dispatch_service, notification_service, replenishment_service, stock_ledger

DEMO_SLUGS = ("default", "qazvin-shop")
MARKER = "فروش نمونه (سابقه)"
DAYS = 240


def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 30:                                    # تقریب نرمال برای میانگین‌های بزرگ
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _at(day, hour: int, minute: int) -> datetime:
    return dispatch_service.local_to_utc(datetime.combine(day, time(hour, minute)))


def seed(db) -> None:
    today = replenishment_service.today_local()
    for slug in DEMO_SLUGS:
        org = db.query(Organization).filter(Organization.slug == slug).first()
        if org is None:
            continue
        set_tenant(db, org.id)
        if db.query(StockMovement.id).filter(StockMovement.reason == MARKER).first():
            print(f"↩️  سابقه فروش نمونه «{org.name}» قبلاً ثبت شده است.")
            set_tenant(db, None)
            continue
        # ساخت سابقه گذشته (تاریخ و مانده گردش‌ها بعد از ثبت تنظیم می‌شود) فقط در حالت نگهداری دفتر مجاز است
        with stock_ledger.maintenance(db):
            invs = db.query(Inventory).options(joinedload(Inventory.product)) \
                .filter(Inventory.stock_status == AVAILABLE).order_by(Inventory.id).all()
            rows, seeded = 0, []
            for index, inv in enumerate(invs):
                p = inv.product
                if p is None or p.is_active is False:
                    continue
                rng = random.Random(inv.id * 7919)
                if rng.random() < 0.15:                 # چند کالا بی‌فروش
                    continue
                base = rng.choice([0.6, 1.2, 2.5, 4, 6, 9, 14]) * rng.uniform(0.8, 1.25)
                growth = rng.uniform(-0.0012, 0.0035)     # روند روزانه
                imported = p.origin == "imported"
                lead = rng.choice([25, 30, 40]) if imported else rng.choice([3, 5, 7, 7, 10, 14])
                # سیاست ساده خرید در گذشته (فقط برای ساختن سابقه)
                reorder_at = base * (lead + 6)
                batch = max(5, round(base * rng.choice([20, 30, 45])))
                stock, pending = 0, []                    # [(روز رسیدن، مقدار)]
                start = today - timedelta(days=DAYS)
                # موجودی آغاز دوره
                first = max(5, round(base * (lead + 25)))
                stock_ledger.record(db, inv, first, "receipt", reason=f"{MARKER} — موجودی آغاز دوره")
                db.flush()
                last = db.query(StockMovement).filter(StockMovement.inventory_id == inv.id).order_by(StockMovement.id.desc()).first()
                last.created_at = _at(start, 8, 0)
                stock = first
                for d in range(DAYS):
                    day = start + timedelta(days=d)
                    for arrival in [x for x in pending if x[0] == d]:
                        m = stock_ledger.record(db, inv, arrival[1], "receipt", reason=f"{MARKER} — رسید خرید")
                        db.flush()
                        m.created_at = _at(day, 9, rng.randint(0, 50))
                        stock += arrival[1]
                        pending.remove(arrival)
                        rows += 1
                    weekday = day.weekday()                # جمعه = ۴
                    factor = 0.35 if weekday == 4 else 0.8 if weekday == 3 else 1.0
                    qty = min(stock, _poisson(rng, base * (1 + growth * d) * factor))
                    if qty > 0:
                        m = stock_ledger.record(db, inv, -qty, "order_out", reason=MARKER)
                        db.flush()
                        m.created_at = _at(day, rng.randint(10, 19), rng.randint(0, 59))
                        stock -= qty
                        rows += 1
                    # خرید جدید وقتی موجودی + در راه به حد برسد (۲۰٪ از کالاها در ماه آخر خرید نمی‌کنند ← کمبود نمونه)
                    on_order = sum(x[1] for x in pending)
                    skip_late = index % 5 == 0 and d > DAYS - 40
                    if stock + on_order <= reorder_at and not skip_late:
                        pending.append((d + lead + rng.randint(-1, 2), batch))
                seeded.append(inv)
                # زمان تأمین کالا برای فرمول (بخشی پیش‌فرض سازمان می‌مانند)
                if rng.random() < 0.6:
                    inv.lead_time_days = float(lead)
                    inv.lead_time_std_days = round(lead * 0.25, 1)
                db.flush()
                # مانده بعد از هر گردش به ترتیب تاریخ
                balance = 0
                for m in db.query(StockMovement).filter(StockMovement.inventory_id == inv.id).order_by(StockMovement.created_at, StockMovement.id).all():
                    balance += m.quantity_change
                    m.balance_after = balance
            db.flush()
        # بهای خرید (≈ ۷۸٪ قیمت فروش)؛ هر هفتمین کالا بدون بها
        priced = 0
        for row in db.query(ProductPrice).filter(ProductPrice.cost_price.is_(None)).order_by(ProductPrice.product_id).all():
            if row.product_id % 7 == 0:
                continue
            row.cost_price = round((row.final_price or 0) * 0.78, -3)
            priced += 1
        db.commit()
        # نقطه سفارش بیشتر کالاهای دارای سابقه خودکار (بقیه دستی، برای مقایسه)
        for inv in seeded:
            if inv.id % 4 != 0:
                inv.rop_mode = "auto"
        replenishment_service.recalculate(db, org.id)
        db.commit()
        # هشدارهای کمبودِ هر دور ۸ ماه سابقه ساختگی پاک می‌شوند؛ فقط کالاهایی که الان زیر نقطه سفارش‌اند یک هشدار می‌گیرند
        db.query(Notification).filter(Notification.kind.in_(("low_stock", "out_of_stock"))).delete(synchronize_session=False)
        for inv in seeded:
            inv.low_alerted = False
            notification_service.low_stock(db, inv)
        db.commit()
        set_tenant(db, None)
        print(f"✅ سابقه فروش ۸ ماهه «{org.name}»: {rows:,} گردش، بهای خرید {priced} ردیف قیمت.")


if __name__ == "__main__":
    from app.database import SessionLocal
    session = SessionLocal()
    try:
        seed(session)
        mismatches = stock_ledger.find_mismatches(session)
        print("✅ دفتر گردش سالم است." if not mismatches else f"⚠️ مغایرت دفتر گردش: {mismatches[:3]}")
    finally:
        session.close()
