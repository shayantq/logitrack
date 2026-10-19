"""
جداسازی داده‌های سازمان‌ها (Multi-tenancy)

هر مدلی که از TenantScoped ارث ببرد، ستون organization_id دارد و:

۱. خواندن: وقتی برای یک Session «سازمان جاری» تنظیم شده باشد
   (set_tenant)، به همه‌ی SELECT/UPDATE/DELETEهای ORM به‌طور خودکار شرط
   organization_id = سازمان جاری اضافه می‌شود — حتی اگر در سرویس فراموش
   شود. یعنی کاربر سازمان A هرگز رکورد سازمان B را نمی‌بیند (نه در لیست، نه
   با id، نه از طریق relationship).

۲. نوشتن: رکورد جدیدی که organization_id ندارد، قبل از flush سازمان جاری
   را می‌گیرد. اگر سازمان جاری هم نباشد خطا داده می‌شود (به‌جز کاربرانی که
   عمداً بدون سازمان‌اند، یعنی کارکنان پلتفرم).

Session بدون سازمان جاری (کارکنان پلتفرم، تسک‌های سیستمی Celery،
اسکریپت‌ها) فیلتری ندارد و همه سازمان‌ها را می‌بیند.

برای کوئری‌هایی که عمداً باید بین همه سازمان‌ها باشند (مثل بررسی یکتا
بودن نام کاربری) از execution option `SKIP_TENANT_FILTER` استفاده کنید.
"""
from sqlalchemy import Column, ForeignKey, Integer, event
from sqlalchemy.orm import Session, declared_attr, with_loader_criteria

TENANT_KEY = "organization_id"
SKIP_TENANT_FILTER = {"skip_tenant_filter": True}


class TenantScoped:
    """Mixin برای مدل‌هایی که به یک سازمان تعلق دارند."""

    # اجازه NULL فقط برای مدل‌هایی که عمداً رکورد بدون سازمان دارند (User برای کارکنان پلتفرم)
    __tenant_nullable__ = False

    @declared_attr
    def organization_id(cls):
        return Column(
            Integer,
            ForeignKey("organizations.id", ondelete="CASCADE"),
            index=True,
            nullable=cls.__tenant_nullable__,
        )


class TenantMissingError(RuntimeError):
    pass


def set_tenant(db: Session, organization_id: int | None) -> None:
    """سازمان جاری این Session را تنظیم می‌کند (None یعنی بدون فیلتر)."""
    if organization_id is None:
        db.info.pop(TENANT_KEY, None)
    else:
        db.info[TENANT_KEY] = organization_id


def current_tenant(db: Session) -> int | None:
    return db.info.get(TENANT_KEY)


@event.listens_for(Session, "do_orm_execute")
def _apply_tenant_filter(execute_state):
    if not (execute_state.is_select or execute_state.is_update or execute_state.is_delete):
        return
    if execute_state.is_column_load or execute_state.execution_options.get("skip_tenant_filter"):
        return
    organization_id = execute_state.session.info.get(TENANT_KEY)
    if organization_id is None:
        return
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            TenantScoped,
            lambda cls: cls.organization_id == organization_id,
            include_aliases=True,
        )
    )


@event.listens_for(Session, "before_flush")
def _assign_tenant_on_insert(session, flush_context, instances):
    organization_id = session.info.get(TENANT_KEY)
    for obj in session.new:
        if not isinstance(obj, TenantScoped) or obj.organization_id is not None:
            continue
        if organization_id is not None:
            obj.organization_id = organization_id
        elif not type(obj).__tenant_nullable__:
            raise TenantMissingError(
                f"{type(obj).__name__} بدون سازمان قابل ثبت نیست (organization_id یا سازمان جاری Session تنظیم نشده است)."
            )
