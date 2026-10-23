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

۳. ارجاع: رکوردی که به رکورد سازمان دیگری اشاره کند (مثلاً سفارش سازمان A با
   انبار سازمان B) ذخیره نمی‌شود — حتی اگر سرویس شناسه را بدون بررسی از کاربر
   گرفته باشد (TenantIsolationError). پنهان کردن در رابط کاربری امنیت نیست؛
   جداسازی در لایه داده تضمین می‌شود.
"""
from collections import defaultdict

from sqlalchemy import Column, ForeignKey, Integer, event, inspect as sa_inspect, select
from sqlalchemy.orm import Session, declared_attr, with_loader_criteria
from sqlalchemy.orm.util import identity_key

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


class TenantIsolationError(RuntimeError):
    """ارجاع یک رکورد به رکوردی از سازمان دیگر."""


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


# ---------------------------------------------------------------------------
# محافظ ارجاع بین سازمان‌ها
# ---------------------------------------------------------------------------
_REFERENCES: dict[type, tuple[list, list]] = {}


def _tenant_references(cls) -> tuple[list[tuple[str, type]], list[tuple[str, type]]]:
    """(ستون‌های کلید خارجی، رابطه‌های many-to-one) این مدل که به مدل سازمانی دیگری اشاره می‌کنند."""
    refs = _REFERENCES.get(cls)
    if refs is None:
        mapper = sa_inspect(cls)
        by_table = {m.local_table: m.class_ for m in mapper.registry.mappers}
        columns = []
        for prop in mapper.column_attrs:
            for column in prop.columns:
                for fk in column.foreign_keys:
                    target = by_table.get(fk.column.table)
                    if target is not None and issubclass(target, TenantScoped):
                        columns.append((prop.key, target))
        relations = [(r.key, r.mapper.class_) for r in mapper.relationships
                     if r.direction.name == "MANYTOONE" and issubclass(r.mapper.class_, TenantScoped) and not r.viewonly]
        refs = _REFERENCES[cls] = (columns, relations)
    return refs


def _isolation_error(obj, key: str) -> TenantIsolationError:
    return TenantIsolationError(f"{type(obj).__name__}.{key} به رکوردی از سازمان دیگر اشاره می‌کند؛ ذخیره نشد.")


@event.listens_for(Session, "before_flush")
def _guard_cross_tenant_references(session, flush_context, instances):
    expected: dict[type, dict[int, list]] = defaultdict(lambda: defaultdict(list))
    for obj in list(session.new) + list(session.dirty):
        if not isinstance(obj, TenantScoped) or obj.organization_id is None:
            continue
        state = sa_inspect(obj)
        is_new = state.key is None
        columns, relations = _tenant_references(type(obj))
        for key, target in columns:
            value = state.dict.get(key)
            if value is not None and (is_new or state.attrs[key].history.has_changes()):
                expected[target][value].append((obj, key))
        for key, _target in relations:
            related = state.dict.get(key)
            if related is None or not (is_new or state.attrs[key].history.has_changes()):
                continue
            if related.organization_id is not None and related.organization_id != obj.organization_id:
                raise _isolation_error(obj, key)

    for target, refs in expected.items():
        unresolved = {}
        for target_id, owners in refs.items():
            loaded = session.identity_map.get(identity_key(target, target_id))
            if loaded is not None:
                organizations = {loaded.organization_id}
            else:
                unresolved[target_id] = owners
                continue
            for obj, key in owners:
                if None not in organizations and obj.organization_id not in organizations:
                    raise _isolation_error(obj, key)
        if unresolved:
            table = target.__table__
            rows = session.execute(
                select(table.c.id, table.c.organization_id).where(table.c.id.in_(list(unresolved))),
                execution_options={"skip_tenant_filter": True},
            ).all()
            for target_id, organization_id in rows:
                for obj, key in unresolved[target_id]:
                    if organization_id is not None and organization_id != obj.organization_id:
                        raise _isolation_error(obj, key)
