"""خروجی سازمان پس از خرابی worker (CEL-02، یافته ۱): fencing اجرا، ثبت شکست پس از lease، تلاش دوباره دستی و پاک‌سازی فایل."""
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core import storage
from app.core.security import create_access_token
from app.core.tenancy import set_tenant
from app.models import AuditLog, Organization, RoleEnum, User
from app.models_productivity import TenantExport
from app.services import platform_service


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.username, user.id, timedelta(minutes=5))}"}


@pytest.fixture()
def env(api_env, tmp_path, monkeypatch):
    from app import tasks
    monkeypatch.setattr(storage, "MEDIA_ROOT", tmp_path)
    monkeypatch.setattr(tasks.export_tenant_task, "delay", lambda *a: None)
    client, Session = api_env
    db = Session()
    org = Organization(name="سازمان آلفا", slug="alpha")
    other = Organization(name="سازمان بتا", slug="beta")
    db.add_all([org, other])
    db.commit()
    set_tenant(db, None)
    root = User(username="root", email="r@x.io", role=RoleEnum.PLATFORM_ADMIN, hashed_password="x")
    support = User(username="sup", email="s@x.io", role=RoleEnum.PLATFORM_SUPPORT, hashed_password="x")
    db.add_all([root, support])
    db.commit()
    yield SimpleNamespace(client=client, db=db, Session=Session, org=org, other=other, root=root, support=support, media=tmp_path)
    db.close()


def _url(env, suffix="", org=None):
    return f"/platform/organizations/{(org or env.org).id}/exports{suffix}"


def _create(env) -> int:
    res = env.client.post(_url(env), headers=_auth(env.root), json={"reason": "درخواست مشتری"})
    assert res.status_code == 200, res.text
    return res.json()["id"]


def _row(env, export_id) -> TenantExport:
    env.db.expire_all()
    return env.db.get(TenantExport, export_id)


def _started(env, export_id, at=None):
    """اجرایی که شروع شده و worker آن وسط کار مرده است."""
    at = at or _now()
    row = _row(env, export_id)
    row.run_token, row.started_at, row.lease_until = "dead-worker", at, at + platform_service._export_lease()
    env.db.commit()


def _listed(env, user, export_id) -> dict:
    res = env.client.get(_url(env), headers=_auth(user))
    assert res.status_code == 200, res.text
    return next(x for x in res.json() if x["id"] == export_id)


def test_lease_comes_from_the_task_hard_limit():
    from app.tasks import export_tenant_task
    assert platform_service._export_lease() == timedelta(seconds=export_tenant_task.time_limit) + platform_service.EXPORT_LEASE_MARGIN
    assert platform_service._export_lease() == timedelta(seconds=1320)


def test_build_finishes_once_and_a_second_run_is_skipped(env):
    export_id = _create(env)
    assert platform_service.build_export(env.db, export_id)["status"] == "done"
    path = _row(env, export_id).path
    assert platform_service.build_export(env.db, export_id) == {"id": export_id, "skipped": True}
    assert _row(env, export_id).status == "done" and _row(env, export_id).path == path


def test_stale_worker_cannot_finish_and_its_file_is_removed(env, monkeypatch):
    export_id = _create(env)
    save = storage.save

    def save_then_lose_the_lease(relative, data):
        result = save(relative, data)
        other = env.Session()
        set_tenant(other, None)
        platform_service.fail_stale_exports(other, now=_now() + timedelta(days=1))
        other.close()
        return result
    monkeypatch.setattr(storage, "save", save_then_lose_the_lease)
    assert platform_service.build_export(env.db, export_id) == {"id": export_id, "skipped": True}
    row = _row(env, export_id)
    assert row.status == "failed" and row.error == "LeaseExpired" and row.path is None
    assert not list((env.media / "exports").rglob("*.zip"))


def test_failure_inside_the_run_is_recorded_by_the_same_run(env, monkeypatch):
    export_id = _create(env)
    monkeypatch.setattr(storage, "save", lambda *a: (_ for _ in ()).throw(MemoryError()))
    with pytest.raises(MemoryError):
        platform_service.build_export(env.db, export_id)
    row = _row(env, export_id)
    assert row.status == "failed" and row.error == "MemoryError"


def test_started_run_fails_only_after_its_lease(env):
    export_id = _create(env)
    _started(env, export_id)
    lease = platform_service._export_lease()
    assert platform_service.fail_stale_exports(env.db, now=_now() + lease - timedelta(seconds=5)) == 0
    assert _row(env, export_id).status == "pending"
    assert platform_service.fail_stale_exports(env.db, now=_now() + lease + timedelta(seconds=5)) == 1
    row = _row(env, export_id)
    assert row.status == "failed" and row.error == "LeaseExpired" and row.finished_at


def test_unstarted_export_is_never_failed_automatically_and_only_warns(env):
    export_id = _create(env)
    row = _row(env, export_id)
    row.created_at = _now() - platform_service._queue_warning_after() - timedelta(minutes=1)
    env.db.commit()
    assert platform_service.fail_stale_exports(env.db, now=_now() + timedelta(days=30)) == 0
    shown = _listed(env, env.root, export_id)
    assert shown["status"] == "pending" and shown["waiting_too_long"] is True and shown["message"] == platform_service.EXPORT_WAITING_MESSAGE
    assert shown["can_retry"] is False


def test_listing_shows_a_stale_run_without_changing_it(env):
    export_id = _create(env)
    _started(env, export_id, at=_now() - timedelta(hours=1))
    for user, can_retry in ((env.root, True), (env.support, False)):
        shown = _listed(env, user, export_id)
        assert shown["status"] == "pending" and shown["stale"] is True and shown["message"] == platform_service.EXPORT_STALE_MESSAGE
        assert shown["can_retry"] is can_retry
    assert _row(env, export_id).status == "pending"


def test_technical_detail_is_for_platform_admin_only(env):
    export_id = _create(env)
    row = _row(env, export_id)
    row.status, row.error, row.finished_at = "failed", "MemoryError", _now()
    env.db.commit()
    admin_view, support_view = _listed(env, env.root, export_id), _listed(env, env.support, export_id)
    assert admin_view["error"] == "MemoryError" and support_view["error"] is None
    assert admin_view["message"] == support_view["message"] == platform_service.EXPORT_FAILED_MESSAGE


def test_retry_is_manual_admin_only_and_once_per_failed_row(env):
    export_id = _create(env)
    row = _row(env, export_id)
    row.status, row.error, row.finished_at = "failed", "MemoryError", _now()
    env.db.commit()
    retry_url = _url(env, f"/{export_id}/retry")
    assert env.client.post(retry_url, headers=_auth(env.support), json={"reason": "دوباره"}).status_code == 403
    assert env.client.post(retry_url, headers=_auth(env.root), json={}).status_code == 422
    res = env.client.post(retry_url, headers=_auth(env.root), json={"reason": "خرابی worker"})
    assert res.status_code == 200, res.text
    assert res.json()["retry_of_id"] == export_id and res.json()["status"] == "pending" and res.json()["id"] != export_id
    assert env.client.post(retry_url, headers=_auth(env.root), json={"reason": "باز هم"}).status_code == 400
    assert env.db.query(AuditLog).filter(AuditLog.action == "platform.org_export_retry").count() == 1
    original = _listed(env, env.root, export_id)
    assert original["status"] == "failed" and original["retried"] is True and original["can_retry"] is False
    assert env.client.post(_url(env, f"/{export_id}/retry", env.other), headers=_auth(env.root), json={"reason": "سازمان دیگر"}).status_code == 404


def test_only_failed_or_stale_rows_can_be_retried(env):
    done = _create(env)
    platform_service.build_export(env.db, done)
    assert env.client.post(_url(env, f"/{done}/retry"), headers=_auth(env.root), json={"reason": "دوباره"}).status_code == 400
    waiting = _create(env)
    assert env.client.post(_url(env, f"/{waiting}/retry"), headers=_auth(env.root), json={"reason": "دوباره"}).status_code == 400
    assert _row(env, waiting).status == "pending"


def test_retrying_a_stale_run_records_its_failure_first(env):
    export_id = _create(env)
    _started(env, export_id, at=_now() - timedelta(hours=1))
    res = env.client.post(_url(env, f"/{export_id}/retry"), headers=_auth(env.root), json={"reason": "اجرا متوقف شد"})
    assert res.status_code == 200, res.text
    assert _row(env, export_id).status == "failed" and _row(env, export_id).error == "LeaseExpired"


def test_export_that_never_reached_the_queue_is_failed_at_once(env, monkeypatch):
    from app import tasks

    def broken(*_):
        raise ConnectionError("redis down")
    monkeypatch.setattr(tasks.export_tenant_task, "delay", broken)
    res = env.client.post(_url(env), headers=_auth(env.root), json={"reason": "درخواست مشتری"})
    assert res.status_code == 400 and "صف کار" in res.json()["detail"]
    row = env.db.query(TenantExport).one()
    assert row.status == "failed" and row.error == "EnqueueFailed: ConnectionError"


def test_deprovision_records_stale_runs(env):
    done = _create(env)
    platform_service.build_export(env.db, done)
    stale = _create(env)
    _started(env, stale, at=_now() - timedelta(hours=1))
    res = env.client.post(f"/platform/organizations/{env.org.id}/deprovision", headers=_auth(env.root), json={"reason": "پایان قرارداد", "confirm_slug": "alpha"})
    assert res.status_code == 200, res.text
    assert _row(env, stale).status == "failed"


def test_cleanup_removes_partial_and_orphan_files_only(env):
    done = _create(env)
    platform_service.build_export(env.db, done)
    kept = env.media / _row(env, done).path
    folder = kept.parent
    partial, orphan, fresh = folder / "a.zip.tmp", folder / "orphan.zip", folder / "fresh.zip.tmp"
    for path in (partial, orphan, fresh):
        path.write_bytes(b"x")
    old = (_now() - platform_service._export_lease() - timedelta(minutes=5)).replace(tzinfo=timezone.utc).timestamp()
    for path in (partial, orphan, kept):
        os.utime(path, (old, old))
    assert platform_service.clean_export_files(env.db) == 2
    assert kept.exists() and fresh.exists() and not partial.exists() and not orphan.exists()
