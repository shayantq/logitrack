"""
worker واقعی prefork که سقف سخت زمان پردازش خروجی را وسط نوشتن فایل می‌کشد (CEL-02، یافته ۱).
ردیف تا پایان lease در pending می‌ماند، بعد ناموفق ثبت می‌شود و فایل نیمه‌کاره پاک می‌شود.
"""
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from celery import Celery
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import storage
from app.models import Organization
from app.models_productivity import TenantExport
from app.services import platform_service
from tests.integration.conftest import TEST_DATABASE_URL

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DATABASE_URL or "postgresql" not in TEST_DATABASE_URL, reason="فقط روی PostgreSQL واقعی."),
    pytest.mark.skipif(sys.platform == "win32", reason="pool از نوع prefork روی ویندوز نیست."),
]
ROOT = Path(__file__).resolve().parents[2]
HARD_LIMIT = 3


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _wait(check, seconds: float):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.5)
    return None


def test_killed_worker_leaves_a_run_that_fails_only_after_its_lease(tmp_path, monkeypatch):
    queue, media = tmp_path / "queue", tmp_path / "media"
    queue.mkdir()
    media.mkdir()
    engine = create_engine(TEST_DATABASE_URL)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    org = Organization(name="سازمان کشته‌شدن worker", slug="export-kill-org")
    db.add(org)
    db.commit()
    row = TenantExport(organization_id=org.id, status="pending", created_at=_now())
    db.add(row)
    db.commit()
    row_id = row.id
    env = {**os.environ, "DATABASE_URL": TEST_DATABASE_URL, "EXPORT_KILL_QUEUE": str(queue), "MEDIA_ROOT": str(media)}
    worker = subprocess.Popen(
        [sys.executable, "-m", "celery", "-A", "tests.integration.export_kill_helper:app", "worker", "--pool=prefork", "--concurrency=1",
         "--loglevel=WARNING", "--without-heartbeat", "--without-gossip", "--without-mingle"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        transport = {"data_folder_in": str(queue), "data_folder_out": str(queue), "control_folder": str(queue)}
        probe = Celery("probe", broker="filesystem://", broker_transport_options=transport)
        probe.send_task("tests.export_kill_slow", args=[row_id], time_limit=HARD_LIMIT)

        def started():
            db.expire_all()
            current = db.get(TenantExport, row_id)
            return current if current.run_token else None
        current = _wait(started, 60)
        assert current is not None, "worker وظیفه را شروع نکرد"
        partial = _wait(lambda: next(media.rglob("*.tmp"), None), 20)
        assert partial is not None
        time.sleep(HARD_LIMIT + 3)                     # پردازش با SIGTERM و سپس SIGKILL کشته شده است
        heartbeat = media / "heartbeat"
        beat = heartbeat.read_text()
        time.sleep(2)
        assert heartbeat.read_text() == beat, "پردازش پس از سقف سخت زمان هنوز زنده است"
        db.expire_all()
        current = db.get(TenantExport, row_id)
        assert current.status == "pending" and current.path is None and partial.exists()

        lease = platform_service._export_lease()
        assert platform_service.fail_stale_exports(db, now=current.started_at + lease - timedelta(seconds=1)) == 0
        assert platform_service.fail_stale_exports(db, now=current.started_at + lease + timedelta(seconds=1)) == 1
        db.expire_all()
        assert db.get(TenantExport, row_id).status == "failed" and db.get(TenantExport, row_id).error == "LeaseExpired"
        monkeypatch.setattr(storage, "MEDIA_ROOT", media)
        assert platform_service.clean_export_files(db, now=_now() + lease + timedelta(minutes=1)) == 1
        assert not partial.exists()
    finally:
        worker.terminate()
        try:
            worker.wait(timeout=15)
        except subprocess.TimeoutExpired:
            worker.kill()
        db.rollback()
        db.query(Organization).filter(Organization.id == org.id).delete()
        db.commit()
        db.close()
        engine.dispose()
