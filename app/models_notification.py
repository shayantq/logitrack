"""
مدل اعلان‌ها (Notification)

⚠️ این مدل عمداً در یک فایل جدا نگه داشته شده (نه داخل app/models.py)
تا هیچ ریسکی برای فایل اصلی مدل‌های شما ایجاد نشود. چون از همان Base
مشترک (app.database.Base) استفاده می‌کند، به‌محض import شدن این فایل در
هر جای برنامه (مثلاً app/tasks.py یا روتر notifications)، جدولش هم در
Base.metadata ثبت می‌شود و توسط Alembic قابل مدیریت است.

مخاطب اعلان:
  • staff — ادمین سازمان + مدیر همان انبار (اعلان بدون انبار: همه مدیران انبار)
  • admin — فقط ادمین سازمان
  • user  — فقط کاربر مشخص (user_id)؛ مثلاً راننده‌ای که سفارش به او سپرده شده
خوانده‌شدن و حذف (بستن) برای هر کاربر جداست (NotificationReceipt) — اگر ادمین اعلانی را
ببندد، از فهرست مدیر انبار پاک نمی‌شود.
"""
from datetime import datetime, timezone
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from app.database import Base
from app.core.tenancy import TenantScoped


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Notification(TenantScoped, Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=_now, index=True)
    kind = Column(String(32), nullable=False, default="low_stock", server_default="low_stock")
    severity = Column(String(16), nullable=False, default="warning", server_default="warning")
    title = Column(String(160), nullable=True)
    message = Column(String, nullable=False)
    # مسیر صفحه مقصد در پنل (کلیک روی اعلان ← همان مورد در همان بخش)
    link = Column(String(255), nullable=True)
    # جزئیات کوتاه برای نمایش: [{"label": "موجودی فعلی", "value": "۳ عدد"}, ...]
    details = Column(JSON, nullable=True)
    audience = Column(String(8), nullable=False, default="staff", server_default="staff")
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=True)
    # انبار مربوط به اعلان — مدیر انبار فقط اعلان‌های انبار خودش را می‌بیند
    warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=True)
    # رویداد تکراری (مثلاً پیام تازه در همان تیکت) به‌جای اعلان جدید، همان اعلان را تازه می‌کند
    dedupe_key = Column(String(120), nullable=True, index=True)


class NotificationReceipt(TenantScoped, Base):
    """وضعیت هر اعلان برای هر کاربر: خوانده‌شده / بسته‌شده."""
    __tablename__ = "notification_receipts"
    __table_args__ = (UniqueConstraint("notification_id", "user_id", name="uq_notification_receipt"),)

    id = Column(Integer, primary_key=True)
    notification_id = Column(Integer, ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    read_at = Column(DateTime, nullable=True)
    dismissed_at = Column(DateTime, nullable=True)
