"""
دیتای ساختگی بار آزمایشی (ت۱۷): ردیف‌های seed_demo_data را با کلیدهای تازه تکثیر می‌کند.
فقط با LOAD_TEST=1 و غیر production اجرا می‌شود. داخل کانتینر web استک جدا:
    docker compose -p pasineh_load exec -T web python scripts/load/seed_synthetic.py
"""
import os
import sys

from sqlalchemy import create_engine, text

ORDERS = 20_000
MOVEMENTS = 200_000
AUDIT = 100_000


def _columns(conn, table: str, skip: set[str]) -> list[str]:
    rows = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :t ORDER BY ordinal_position"), {"t": table})
    return [r[0] for r in rows if r[0] not in skip]


def main() -> None:
    if os.getenv("LOAD_TEST") != "1" or os.getenv("APP_ENV", "development") == "production":
        sys.exit("فقط روی استک بار آزمایشی (LOAD_TEST=1) اجرا می‌شود.")
    engine = create_engine(os.environ["MIGRATION_DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://", 1))
    with engine.begin() as conn:
        org = conn.execute(text("SELECT organization_id FROM users WHERE username = 'qazvin_admin'")).scalar()
        columns = _columns(conn, "orders", {"id", "tracking_code", "rating_token"})
        cols = ", ".join(columns)
        special = {"status": "'delivered'", "shipment_id": "NULL", "created_at": "now() - (g % 365 + 40) * interval '1 day'"}
        picks = ", ".join(special.get(c, c) for c in columns)
        conn.execute(text(f"""
            WITH src AS (SELECT * FROM orders WHERE organization_id = :org ORDER BY id LIMIT 1)
            INSERT INTO orders ({cols}, tracking_code) SELECT {picks}, 'LD' || lpad(g::text, 8, '0') FROM src, generate_series(1, :n) g
        """), {"n": ORDERS, "org": org})
        columns = _columns(conn, "stock_movements", {"id", "idempotency_key", "request_hash", "reversal_of_id"})
        cols = ", ".join(columns)
        conn.execute(text(f"""
            WITH src AS (SELECT * FROM stock_movements WHERE organization_id = :org ORDER BY id LIMIT 1000)
            INSERT INTO stock_movements ({cols}) SELECT {cols} FROM src, generate_series(1, :n)
        """), {"n": MOVEMENTS // 1000, "org": org})
        columns = _columns(conn, "audit_logs", {"id"})
        cols = ", ".join(columns)
        rows = conn.execute(text("SELECT count(*) FROM audit_logs WHERE organization_id = :org"), {"org": org}).scalar()
        if rows:
            conn.execute(text(f"""
                WITH src AS (SELECT * FROM audit_logs WHERE organization_id = :org ORDER BY id LIMIT 100)
                INSERT INTO audit_logs ({cols}) SELECT {cols} FROM src, generate_series(1, :n)
            """), {"n": AUDIT // min(rows, 100), "org": org})
        # سقف روزانه راننده در این استک برداشته می‌شود تا بار روی سرویس‌ها بیفتد، نه روی قاعده کسب‌وکار
        conn.execute(text("UPDATE driver_profiles SET max_daily_orders = 100000"))
        conn.execute(text("ANALYZE"))
        for table in ("orders", "stock_movements", "audit_logs"):
            print(table, conn.execute(text(f"SELECT count(*) FROM {table}")).scalar())
        print("organization", org)
    engine.dispose()


if __name__ == "__main__":
    main()
