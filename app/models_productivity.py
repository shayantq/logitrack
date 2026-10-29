"""
بهره‌وری عملیات (docs/productivity.md):
  • SavedView — نمای ذخیره‌شده یک فهرست (فیلترهای همان آدرس صفحه)؛ برای خود کاربر یا مشترک با یک نقش
"""
from datetime import datetime, timezone

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.tenancy import TenantScoped
from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


SAVED_VIEW_PAGES = ("orders", "receipts", "inventory", "transfers", "tickets")


class SavedView(TenantScoped, Base):
    __tablename__ = "saved_views"
    __table_args__ = (
        UniqueConstraint("owner_id", "page_key", "name", name="uq_saved_views_owner_page_name"),
        CheckConstraint("page_key IN ('orders', 'receipts', 'inventory', 'transfers', 'tickets')", name="ck_saved_views_page"),
        CheckConstraint("shared_role IS NULL OR shared_role IN ('org_admin', 'warehouse_manager')", name="ck_saved_views_role"),
    )

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    page_key = Column(String(16), nullable=False)
    name = Column(String(60), nullable=False)
    filters = Column(JSON, nullable=False, default=dict)
    shared_role = Column(String(32), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now)

    owner = relationship("User")
