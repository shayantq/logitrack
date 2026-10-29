"""نقش محدود برنامه (app/db_roles.py) روی PostgreSQL واقعی: خواندن/نوشتن ردیف بله؛ تغییر ساختار، ساخت نقش و خاموش‌کردن trigger نه."""
import secrets

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from app import db_roles
from tests.integration.conftest import TEST_DATABASE_URL

ROLE = "pasineh_test_app"


def _psycopg(url: str) -> str:
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.fixture()
def runtime_engine():
    password = secrets.token_urlsafe(24)
    db_roles.ensure_role(TEST_DATABASE_URL, ROLE, password)
    db_roles.ensure_role(TEST_DATABASE_URL, ROLE, password)            # اجرای دوباره بی‌خطر است
    db_roles.grant(TEST_DATABASE_URL, ROLE)
    url = make_url(TEST_DATABASE_URL).set(username=ROLE, password=password).render_as_string(hide_password=False)
    engine = create_engine(_psycopg(url))
    try:
        yield engine
    finally:
        engine.dispose()
        admin = create_engine(_psycopg(TEST_DATABASE_URL), isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f'DROP OWNED BY "{ROLE}"'))
            conn.execute(text(f'DROP ROLE "{ROLE}"'))
        admin.dispose()


def test_runtime_role_has_row_access_only(runtime_engine):
    with runtime_engine.connect() as conn:
        superuser, bypass, createdb, createrole = conn.execute(text(
            "SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = current_user")).one()
        assert not (superuser or bypass or createdb or createrole)
        for table in ("organizations", "orders", "stock_movements", "audit_logs"):
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                assert conn.execute(text("SELECT has_table_privilege(current_user, :t, :p)"),
                                    {"t": table, "p": privilege}).scalar(), (table, privilege)
        conn.execute(text("SELECT count(*) FROM organizations")).scalar()


@pytest.mark.parametrize("statement", [
    "DROP TABLE organizations",
    "ALTER TABLE orders ADD COLUMN hacked integer",
    "CREATE TABLE intruder (id integer)",
    "ALTER TABLE stock_movements DISABLE TRIGGER ALL",
    "CREATE ROLE intruder",
    "CREATE DATABASE intruder",
])
def test_runtime_role_cannot_change_structure_or_roles(runtime_engine, statement):
    with runtime_engine.connect() as conn:
        with pytest.raises(DBAPIError):
            conn.execute(text(statement))
        conn.rollback()
