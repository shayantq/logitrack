"""
رفتارهایی که فقط روی PostgreSQL واقعی معنا دارند: برداشت هم‌زمان پیام (SKIP LOCKED) و سقف زمان کوئری و قفل.
"""
import threading
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.database import connect_args
from app.models_productivity import OutboundMessage
from app.services import messaging, outbox_service
from tests.integration.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.integration


@pytest.fixture()
def factory():
    if not TEST_DATABASE_URL or "postgresql" not in TEST_DATABASE_URL:
        pytest.skip("دیتابیس PostgreSQL آزمون تنظیم نشده است")
    engine = create_engine(TEST_DATABASE_URL)
    make = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = make()
    db.query(OutboundMessage).delete()
    db.commit()
    db.close()
    yield make
    db = make()
    db.query(OutboundMessage).delete()
    db.commit()
    db.close()
    engine.dispose()


def test_two_publishers_never_send_the_same_message(factory, monkeypatch):
    db = factory()
    now = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    db.add_all([OutboundMessage(channel="sms", recipient=f"0912000000{i}", body="متن", status="pending", created_at=now, next_attempt_at=now)
                for i in range(outbox_service.BATCH)])
    db.commit()
    db.close()
    sent, lock = [], threading.Lock()

    def deliver(mobile, text, local_id=None):
        with lock:
            sent.append(local_id)
        return True
    monkeypatch.setattr(messaging, "deliver_sms", deliver)

    def run():
        session = factory()
        try:
            outbox_service.publish_due(session)
        finally:
            session.close()
    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    while True:                       # پیامی که هیچ‌کدام برنداشته‌اند (رد شده با SKIP LOCKED) در دور بعد فرستاده می‌شود
        session = factory()
        result = outbox_service.publish_due(session)
        session.close()
        if not result["sent"]:
            break
    assert len(sent) == outbox_service.BATCH and len(set(sent)) == outbox_service.BATCH


def test_rollback_also_removes_a_message_with_dedupe_key(factory):
    db = factory()
    assert outbox_service.enqueue(db, "sms", "09121112233", "متن", dedupe_key="pg:rollback") is not None
    db.rollback()
    assert db.query(OutboundMessage).filter(OutboundMessage.dedupe_key == "pg:rollback").count() == 0
    # تکرار همان رویداد تراکنش را خراب نمی‌کند و پیام دوم نمی‌سازد
    assert outbox_service.enqueue(db, "sms", "09121112233", "الف", dedupe_key="pg:twice") is not None
    db.commit()
    assert outbox_service.enqueue(db, "sms", "09121112233", "ب", dedupe_key="pg:twice") is None
    db.commit()
    assert db.query(OutboundMessage).filter(OutboundMessage.dedupe_key == "pg:twice").count() == 1
    db.close()


def test_timeouts_are_applied_to_app_connections(monkeypatch):
    if not TEST_DATABASE_URL or "postgresql" not in TEST_DATABASE_URL:
        pytest.skip("دیتابیس PostgreSQL آزمون تنظیم نشده است")
    monkeypatch.setenv("DB_STATEMENT_TIMEOUT_MS", "200")
    engine = create_engine(TEST_DATABASE_URL, connect_args=connect_args(TEST_DATABASE_URL))
    with engine.connect() as conn:
        assert conn.execute(text("SHOW statement_timeout")).scalar() == "200ms"
        assert conn.execute(text("SHOW lock_timeout")).scalar() == "10s"
        with pytest.raises(OperationalError) as caught:
            conn.execute(text("SELECT pg_sleep(1)"))
        assert type(caught.value.orig).__name__ == "QueryCanceled"
    engine.dispose()


def test_erasing_an_organization_respects_ledger_triggers(factory, monkeypatch, tmp_path):
    """روی PostgreSQL واقعی trigger سند انبار فعال است؛ پاک‌سازی نباید به آن جدول‌ها دست بزند و باید خطا ندهد."""
    from app.core import storage
    from app.core.tenancy import set_tenant
    from app.models import Customer, Organization, StockDocument
    from app.services import platform_service, stock_ledger
    from app.models import Product
    from tests.factories import default_warehouse

    monkeypatch.setattr(storage, "MEDIA_ROOT", tmp_path)
    db = factory()
    org = Organization(name="سازمان پاک‌سازی", slug=f"erase-{datetime.now(timezone.utc).timestamp():.0f}")
    db.add(org)
    db.commit()
    set_tenant(db, org.id)
    warehouse = default_warehouse(db, org.id)
    product = Product(organization_id=org.id, name="برنج", sku=f"ERASE-{org.id}", barcode=f"E{org.id}", price=1, weight_kg=1)
    db.add(product)
    db.commit()
    inventory = stock_ledger.lock_bucket(db, product.id, warehouse.id, "available", organization_id=org.id)
    document = stock_ledger.new_document(db, "receipt", organization_id=org.id, warehouse_id=warehouse.id, note="اولیه")
    stock_ledger.record(db, inventory, 5, "receipt", document=document, reason="اولیه")
    db.add(Customer(organization_id=org.id, name="مریم", mobile="09121112233"))
    db.commit()
    before = db.query(StockDocument).filter(StockDocument.organization_id == org.id).count()
    platform_service.erase_organization(db, org.id)
    db.expire_all()
    assert db.query(StockDocument).filter(StockDocument.organization_id == org.id).count() == before
    customer = db.query(Customer).filter(Customer.organization_id == org.id).one()
    assert customer.name == "حذف‌شده" and "0912" not in customer.mobile
    db.close()
