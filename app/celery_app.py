"""
راه‌اندازی Celery برای پردازش ناهمگام (Asynchronous) کارهای سنگین —
مثل تولید گزارش‌های اکسل/PDF بزرگ، و بررسی دوره‌ای موجودی رو‌به‌اتمام —
بدون بلاک کردن ترد اصلی برنامه FastAPI.

این ماژول توسط سه فرآیند جدا استفاده می‌شود:
  ۱. کانتینر web (FastAPI): فقط task را در صف قرار می‌دهد (delay/apply_async)
  ۲. کانتینر celery_worker: واقعاً task را اجرا می‌کند (در app/tasks.py)
  ۳. کانتینر celery_beat: طبق زمان‌بندی، تسک‌های دوره‌ای را به صف اضافه می‌کند
"""
import os
from celery import Celery
from celery.schedules import crontab

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "pasineh",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Tehran",
    enable_utc=True,
    result_expires=3600,  # نتیجه هر گزارش فقط ۱ ساعت در Redis نگه داشته می‌شود
)

# زمان‌بندی تسک‌های دوره‌ای (Celery Beat)
celery_app.conf.beat_schedule = {
    "check-low-stock-hourly": {
        "task": "tasks.check_low_stock",
        "schedule": crontab(minute=0),  # هر ساعت، راس ساعت
    },
    "expire-overdue-orders-hourly": {
        "task": "tasks.expire_overdue_orders",
        "schedule": crontab(minute=5),  # هر ساعت، دقیقه ۵
    },
    "refresh-current-prices-nightly": {
        "task": "tasks.refresh_current_prices",
        "schedule": crontab(hour=20, minute=31),  # ۰۰:۰۱ به وقت ایران (UTC+03:30)
    },
    "recalculate-reorder-points-nightly": {
        "task": "tasks.recalculate_reorder_points",
        "schedule": crontab(hour=20, minute=45),  # ۰۰:۱۵ به وقت ایران — بعد از تکمیل تقاضای روز قبل
    },
    "check-replenishment-rules-hourly": {
        "task": "tasks.check_replenishment_rules",
        "schedule": crontab(minute=20),
    },
    "classify-abc-weekly": {
        "task": "tasks.classify_abc",
        "schedule": crontab(hour=21, minute=0, day_of_week=5),  # بامداد شنبه به وقت ایران
    },
    "reset-demo-half-hourly": {
        "task": "tasks.reset_demo",
        "schedule": crontab(minute="0,30"),  # نسخه نمایشی خصوصی به حالت اولیه
    },
}

# اطمینان از این‌که Celery ماژول تسک‌ها را پیدا می‌کند
celery_app.autodiscover_tasks(["app"])
