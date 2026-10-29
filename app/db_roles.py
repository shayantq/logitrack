"""
نقش محدود دیتابیس برای اجرای برنامه (اصل حداقل دسترسی).

برنامه و Celery با نقش APP_DB_USER (پیش‌فرض pasineh_app) وصل می‌شوند که فقط خواندن/نوشتن ردیف‌ها را دارد:
نه ساخت/حذف/تغییر جدول، نه ساخت نقش یا دیتابیس، نه دور زدن RLS، نه غیرفعال‌کردن triggerهای دفتر گردش.
مایگریشن‌ها و بازسازی نسخه نمایشی با MIGRATION_DATABASE_URL (کاربر مدیر) اجرا می‌شوند.

    docker compose exec -T -e APP_DB_PASSWORD web python -m app.db_roles

فقط وضعیت هر گام چاپ می‌شود؛ رمز هرگز. اجرای دوباره بی‌خطر است (رمز و دسترسی‌ها به‌روز می‌شوند).
"""
import os
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

DEFAULT_ROLE = "pasineh_app"
DML = "SELECT, INSERT, UPDATE, DELETE"


def _engine(url: str):
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return create_engine(url, isolation_level="AUTOCOMMIT")


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def ensure_role(admin_url: str, role: str, password: str) -> None:
    """نقش بدون هیچ امتیاز مدیریتی؛ رمز با literal امن psycopg ست می‌شود (در هیچ لاگی نمی‌آید)."""
    from psycopg import sql
    engine = _engine(admin_url)
    try:
        with engine.connect() as conn:
            exists = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).first()
            raw = conn.connection.dbapi_connection
            with raw.cursor() as cur:
                verb = "ALTER" if exists else "CREATE"
                cur.execute(sql.SQL(verb + " ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                                    " PASSWORD {}").format(sql.Identifier(role), sql.Literal(password)))
    finally:
        engine.dispose()


def grant(admin_url: str, role: str) -> None:
    """دسترسی ردیفی روی همه جدول‌ها و sequenceهای فعلی و آینده (جدول‌هایی که مایگریشن‌های بعدی می‌سازند)."""
    url = make_url(admin_url)
    owner = url.username or "postgres"
    r, o = _quote_ident(role), _quote_ident(owner)
    engine = _engine(admin_url)
    try:
        with engine.connect() as conn:
            conn.execute(text(f"GRANT CONNECT ON DATABASE {_quote_ident(url.database)} TO {r}"))
            conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {r}"))
            conn.execute(text(f"REVOKE CREATE ON SCHEMA public FROM {r}"))
            conn.execute(text(f"GRANT {DML} ON ALL TABLES IN SCHEMA public TO {r}"))
            conn.execute(text(f"GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {r}"))
            conn.execute(text(f"ALTER DEFAULT PRIVILEGES FOR ROLE {o} IN SCHEMA public GRANT {DML} ON TABLES TO {r}"))
            conn.execute(text(f"ALTER DEFAULT PRIVILEGES FOR ROLE {o} IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {r}"))
    finally:
        engine.dispose()


def database_exists(admin_url: str, name: str) -> bool:
    engine = _engine(make_url(admin_url).set(database="postgres").render_as_string(hide_password=False))
    try:
        with engine.connect() as conn:
            return conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}).first() is not None
    finally:
        engine.dispose()


def runtime_role() -> str | None:
    """نقشی که برنامه با آن وصل است (از DATABASE_URL)، اگر با کاربر مدیر (MIGRATION_DATABASE_URL) فرق دارد."""
    app_url, admin_url = os.getenv("DATABASE_URL", "").strip(), os.getenv("MIGRATION_DATABASE_URL", "").strip()
    if not app_url or not admin_url:
        return None
    role = make_url(app_url).username
    return role if role and role != make_url(admin_url).username else None


def main() -> int:
    admin_url = os.getenv("MIGRATION_DATABASE_URL", "").strip()
    role = os.getenv("APP_DB_USER", "").strip() or DEFAULT_ROLE
    password = os.getenv("APP_DB_PASSWORD", "")
    if not admin_url:
        print("FAIL  MIGRATION_DATABASE_URL تنظیم نشده است.")
        return 1
    if len(password) < 16:
        print("FAIL  APP_DB_PASSWORD باید دست‌کم ۱۶ نویسه باشد.")
        return 1
    ensure_role(admin_url, role, password)
    print(f"PASS  نقش {role} بدون امتیاز مدیریتی ساخته/به‌روز شد")
    base = make_url(admin_url)
    targets = [base.database]
    demo = os.getenv("DEMO_DATABASE_URL", "").strip()
    if demo:
        demo_name = make_url(demo).database
        targets += [f"{demo_name}_template", demo_name]
    for name in targets:
        if name and database_exists(admin_url, name):
            grant(base.set(database=name).render_as_string(hide_password=False), role)
            print(f"PASS  دسترسی ردیفی روی {name}")
    print(f"بعدی: در .env  APP_DB_USER={role}  و  APP_DB_PASSWORD=...  سپس  docker compose up -d")
    return 0


if __name__ == "__main__":
    sys.exit(main())
