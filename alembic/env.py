import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# اجازه بده ماژول app از ریشه پروژه import بشه (چه از داخل کانتینر چه لوکال)
sys.path.append(os.getcwd())

from app.database import Base  # noqa: E402
from app import models  # noqa: E402,F401  -- import لازم است تا همه مدل‌ها روی Base.metadata ثبت بشن
from app import models_notification  # noqa: E402,F401

config = context.config

# آدرس دیتابیس را از همان متغیر محیطی پروژه (DATABASE_URL) می‌خوانیم،
# دقیقا همان چیزی که app/database.py استفاده می‌کند — یک منبع حقیقت واحد.
# اگر برنامه با نقش محدود اجرا می‌شود (app/db_roles.py)، مایگریشن با کاربر مدیر (MIGRATION_DATABASE_URL) اجرا می‌شود
db_url = os.getenv("MIGRATION_DATABASE_URL") or os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:123456@localhost:5432/logitrack")
if db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)
config.set_main_option("sqlalchemy.url", db_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
