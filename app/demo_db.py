"""
ساخت و ریست دیتابیس نسخه نمایشی خصوصی (app/core/demo.py).

  قالب (<demo>_template): یک بار با مایگریشن‌ها و seed_showcase.py ساخته می‌شود — دیتای فرضی کامل، حدود ۱۰ دقیقه.
  ریست (هر ۳۰ دقیقه، tasks.reset_demo): همه تاریخ‌های قالب تا «اکنون» جلو می‌روند تا سفارش‌های «امروز» همیشه امروز باشند،
  سپس دیتابیس دمو با CREATE DATABASE ... TEMPLATE در چند ثانیه از روی قالب از نو ساخته می‌شود.

    docker compose exec web python -m app.demo_db build    # ساخت قالب و دیتابیس دمو
    docker compose exec web python -m app.demo_db reset    # ریست دستی
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import Date, DateTime, Index, UniqueConstraint, create_engine, text
from sqlalchemy.engine import make_url

from app.core import demo

ROOT = Path(__file__).resolve().parent.parent
IRAN = timezone(timedelta(hours=3, minutes=30))
PARK_DAYS = 36500   # جابه‌جایی دومرحله‌ای ستون‌های یکتا: اول بیرون از بازه داده، بعد سر جای نهایی


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _local_date(value: datetime):
    return value.replace(tzinfo=timezone.utc).astimezone(IRAN).date()


def _urls() -> tuple[str, str, str, str]:
    url = make_url(demo.database_url())
    name = url.database
    template = f"{name}_template"
    return (url.render_as_string(hide_password=False), url.set(database=template).render_as_string(hide_password=False),
            url.set(database="postgres").render_as_string(hide_password=False), name)


def _admin(sql: str) -> None:
    engine = create_engine(_urls()[2], isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text(sql))
    finally:
        engine.dispose()


def _run(args: list[str], database_url: str) -> None:
    env = {**os.environ, "DATABASE_URL": database_url.replace("postgresql+psycopg://", "postgresql://", 1),
           "SHOWCASE_MEDIA_PREFIX": "demo/"}
    subprocess.run(args, cwd=ROOT, env=env, check=True)


def build() -> None:
    if not demo.enabled():
        sys.exit("DEMO_ACCESS_TOKEN (حداقل ۲۴ نویسه) و DEMO_DATABASE_URL را تنظیم کنید.")
    _, template_url, _, name = _urls()
    template = f"{name}_template"
    _admin(f'DROP DATABASE IF EXISTS "{template}" WITH (FORCE)')
    _admin(f'CREATE DATABASE "{template}"')
    _run([sys.executable, "-m", "alembic", "upgrade", "head"], template_url)
    _run([sys.executable, "seed_showcase.py"], template_url)
    engine = create_engine(template_url)
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE demo_meta (base TIMESTAMP NOT NULL)"))
            conn.execute(text("INSERT INTO demo_meta VALUES (:t)"), {"t": _now()})
    finally:
        engine.dispose()
    reset()
    print("✅ نسخه نمایشی آماده است.")


def _shift_template(template_url: str) -> None:
    """همه تاریخ‌ها به اندازه فاصله ساخت تا اکنون جلو می‌روند (دفتر گردش و گزارش فعالیت در حالت نگه‌داری)."""
    from app.database import Base
    import app.models  # noqa: F401  ثبت همه جدول‌ها در metadata

    engine = create_engine(template_url)
    try:
        with engine.begin() as conn:
            base = conn.execute(text("SELECT base FROM demo_meta")).scalar_one()
            now = _now()
            seconds, days = (now - base).total_seconds(), (_local_date(now) - _local_date(base)).days
            if seconds < 60:
                return
            conn.execute(text("SELECT set_config('pasineh.ledger_maintenance', 'on', true)"))
            for table in Base.metadata.sorted_tables:
                stamps = [c.name for c in table.c if isinstance(c.type, DateTime)]
                dates = [c.name for c in table.c if isinstance(c.type, Date) and not isinstance(c.type, DateTime)] if days else []
                if not stamps and not dates:
                    continue
                unique = [set(c.name for c in u.columns) for u in table.constraints if isinstance(u, UniqueConstraint)]
                unique += [set(c.name for c in i.columns) for i in table.indexes if isinstance(i, Index) and i.unique]
                parked = any(s & set(stamps + dates) for s in unique)

                sets = [f'"{c}" = "{c}" + make_interval(secs => :s)' for c in stamps] + [f'"{c}" = "{c}" + :d' for c in dates]
                update = text(f'UPDATE "{table.name}" SET {", ".join(sets)}')
                steps = [(PARK_DAYS * 86400, PARK_DAYS), (seconds - PARK_DAYS * 86400, days - PARK_DAYS)] if parked else [(seconds, days)]
                for stamp_secs, date_days in steps:
                    conn.execute(update, {"s": stamp_secs, "d": date_days})
            conn.execute(text("UPDATE demo_meta SET base = :t"), {"t": now})
    finally:
        engine.dispose()
    vacuum = create_engine(template_url, isolation_level="AUTOCOMMIT")
    try:
        with vacuum.connect() as conn:
            conn.execute(text("VACUUM"))
    finally:
        vacuum.dispose()


def reset() -> None:
    if not demo.enabled():
        return
    _, template_url, _, name = _urls()
    _shift_template(template_url)
    _admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    _admin(f'CREATE DATABASE "{name}" TEMPLATE "{name}_template"')


if __name__ == "__main__":
    {"build": build, "reset": reset}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: sys.exit("build | reset"))()
