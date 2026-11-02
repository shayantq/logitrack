"""
مرحله ۵ راهنمای عملیات (docs/operations-guide.md): لاگ JSON با شناسه‌ها و بدون داده شخصی، متریک داخلی پشت توکن،
برچسب مسیر بدون شناسه واقعی، انتقال شناسه درخواست به Celery و پیکربندی pool.
"""
import json
import logging
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from app.core import observability, request_context
from app.core.security import create_access_token
from app.core.tenancy import set_tenant
from app.database import pool_options
from app.models import Organization, Product, RoleEnum, User, Warehouse
from app.tasks import _copy_request_id, _end_task_context, _format_task_logs, _start_task_context


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.username, user.id, timedelta(minutes=5))}"}


@pytest.fixture()
def env(api_env):
    client, Session = api_env
    db = Session()
    org = Organization(name="آلفا", slug="alpha")
    db.add(org)
    db.commit()
    set_tenant(db, org.id)
    admin = User(username="adm", email="a@x.io", role=RoleEnum.ORG_ADMIN, hashed_password="x")
    db.add(admin)
    db.commit()
    yield SimpleNamespace(client=client, db=db, org=org, admin=admin)
    db.close()


def _format(message="متن", **state):
    token = request_context.current.set(state)
    rid = request_context.request_id.set("req-12345678")
    try:
        record = logging.LogRecord("pasineh", logging.INFO, __file__, 1, message, (), None)
        return json.loads(observability.JsonFormatter().format(record))
    finally:
        request_context.request_id.reset(rid)
        request_context.current.reset(token)


def test_log_line_is_json_with_correlation_ids():
    line = _format(organization_id=7, user_id=3)
    assert line["request_id"] == "req-12345678" and line["organization_id"] == 7 and line["user_id"] == 3
    assert line["level"] == "INFO" and line["message"] == "متن" and line["time"].endswith("+00:00")
    assert "task_id" not in line


def test_exception_is_recorded_in_the_line():
    try:
        raise ValueError("خطای آزمون")
    except ValueError:
        import sys
        record = logging.LogRecord("pasineh", logging.ERROR, __file__, 1, "شکست", (), sys.exc_info())
    assert "خطای آزمون" in json.loads(observability.JsonFormatter().format(record))["exception"]


def test_user_and_organization_reach_the_log_context_from_the_dependency(env, monkeypatch):
    seen = {}
    original = request_context.current.get

    from app.routers import reports
    monkeypatch.setattr(reports.report_quota, "allow", lambda key: seen.update(original() or {}) or True)
    monkeypatch.setattr(reports.generate_report_task, "delay", lambda *a, **k: SimpleNamespace(id="t1"))
    assert env.client.post("/reports/export/inventory/excel", headers=_auth(env.admin)).status_code == 202
    assert seen["organization_id"] == env.org.id and seen["user_id"] == env.admin.id


def test_response_carries_request_id(env):
    res = env.client.get("/health", headers={"X-Request-ID": "trace-abc-123"})
    assert res.headers["x-request-id"] == "trace-abc-123"


# ---------------------------------------------------------------------------
# متریک
# ---------------------------------------------------------------------------
def test_metrics_do_not_exist_without_a_token(env, monkeypatch):
    monkeypatch.delenv("METRICS_TOKEN", raising=False)
    assert env.client.get("/internal/metrics").status_code == 404
    assert env.client.get("/internal/metrics", headers={"Authorization": "Bearer "}).status_code == 404


def test_metrics_need_the_exact_token(env, monkeypatch):
    monkeypatch.setenv("METRICS_TOKEN", "metrics-secret")
    assert env.client.get("/internal/metrics").status_code == 404
    assert env.client.get("/internal/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 404
    assert env.client.get("/internal/metrics", headers=_auth(env.admin)).status_code == 404
    assert env.client.get("/internal/metrics", headers={"Authorization": "Bearer metrics-secret"}).status_code == 200


def test_metrics_use_route_templates_not_real_identifiers(env, monkeypatch):
    monkeypatch.setenv("METRICS_TOKEN", "metrics-secret")
    env.client.get("/public/track/LT-SECRETCODE")
    env.client.get("/orders/987654", headers=_auth(env.admin))
    body = env.client.get("/internal/metrics", headers={"Authorization": "Bearer metrics-secret"}).text
    assert 'route="/public/track/{code}"' in body and 'route="/orders/{order_id}"' in body
    assert "LT-SECRETCODE" not in body and "987654" not in body and "adm" not in body.replace("pasineh", "")
    for name in ("pasineh_http_request_seconds_bucket", "pasineh_http_db_queries_bucket", "pasineh_db_query_seconds_bucket", "pasineh_outbox_pending",
                 "pasineh_outbox_oldest_seconds", "pasineh_outbox_retrying", "pasineh_task_failures", "pasineh_exceptions_open"):
        assert name in body


def test_query_count_is_measured_per_request():
    token = request_context.current.set({})
    try:
        observability._after_query(SimpleNamespace(info={}), None, "", None, None, False)
        observability._after_query(SimpleNamespace(info={}), None, "", None, None, False)
        assert request_context.current.get()["queries"] == 2
    finally:
        request_context.current.reset(token)


def test_movement_history_query_count_does_not_grow_with_rows(env):
    """شاهد pg_stat_statements: این فهرست برای هر ردیف یک کوئری جدا می‌زد (۵۰۱ کوئری برای یک درخواست)."""
    warehouse = Warehouse(code="W1", name="مرکزی")
    product = Product(name="برنج", sku="RICE-1", barcode="62600001", price=1000, weight_kg=1)
    env.db.add_all([warehouse, product])
    env.db.commit()
    headers = _auth(env.admin)

    def add(count):
        for _ in range(count):
            res = env.client.post("/inventory/movements", headers=headers, json={
                "product_id": product.id, "warehouse_id": warehouse.id, "movement_type": "receipt", "manual_reason": "no_barcode", "quantity": 1, "reason": "ورود"})
            assert res.status_code == 201, res.text

    def queries():
        seen = []
        bind = env.db.get_bind()

        def count(conn, cursor, statement, parameters, context, executemany):
            seen.append(statement)
        event.listen(bind, "before_cursor_execute", count)
        try:
            rows = env.client.get("/inventory/movements", headers=headers).json()
        finally:
            event.remove(bind, "before_cursor_execute", count)
        assert all(r["lines"] for r in rows)
        return len(rows), len(seen)

    add(2)
    few_rows, few = queries()
    add(8)
    many_rows, many = queries()
    assert (few_rows, many_rows) == (2, 10) and many == few


# ---------------------------------------------------------------------------
# Celery و pool
# ---------------------------------------------------------------------------
def test_request_id_travels_to_the_task():
    rid = request_context.request_id.set("req-abcdefgh")
    headers = {}
    try:
        _copy_request_id(headers=headers)
    finally:
        request_context.request_id.reset(rid)
    assert headers["pasineh_request_id"] == "req-abcdefgh"

    task = SimpleNamespace(request=SimpleNamespace(get=lambda key, default=None: headers.get(key, default)))
    _start_task_context(task_id="task-1", task=task)
    try:
        assert request_context.request_id.get() == "req-abcdefgh"
        assert _format()["task_id"] == "task-1"
    finally:
        observability.task_id.set(None)
        request_context.request_id.set(None)


def test_task_end_logs_name_duration_and_outcome_without_inputs(caplog):
    secret = "09121234567"
    task = SimpleNamespace(name="tasks.send_sms", request=SimpleNamespace(get=lambda key, default=None: {"args": [secret]}.get(key, default)))
    _start_task_context(task_id="task-2", task=task, args=[secret], kwargs={"text": secret})
    with caplog.at_level(logging.INFO, logger="app.tasks"):
        _end_task_context(task_id="task-2", task=task, state="FAILURE", args=[secret], kwargs={"text": secret}, retval=secret)
    record = next(r for r in caplog.records if r.name == "app.tasks")
    line = json.loads(observability.JsonFormatter().format(record))
    assert line["task_name"] == "tasks.send_sms" and line["outcome"] == "FAILURE" and line["duration_ms"] >= 0
    assert secret not in json.dumps(line)
    assert observability.task_started.get() is None and observability.task_id.get() is None


def test_celery_success_line_with_task_output_is_silenced():
    _format_task_logs(logger=logging.getLogger("tests.unused"))
    assert logging.getLogger("celery.app.trace").getEffectiveLevel() == logging.WARNING


def test_task_end_without_a_start_writes_nothing(caplog):
    with caplog.at_level(logging.INFO, logger="app.tasks"):
        _end_task_context(task=SimpleNamespace(name="x"), state="SUCCESS")
    assert not [r for r in caplog.records if r.name == "app.tasks"]


def test_pool_settings_only_apply_to_postgres(monkeypatch):
    assert pool_options("sqlite://") == {}
    options = pool_options("postgresql+psycopg://x")
    assert options["pool_pre_ping"] is True and options["pool_size"] == 10 and options["max_overflow"] == 10 and options["pool_timeout"] == 15
    monkeypatch.setenv("DB_POOL_SIZE", "4")
    assert pool_options("postgresql+psycopg://x")["pool_size"] == 4


def test_deadlock_is_a_retryable_busy_answer_not_a_server_error():
    import asyncio

    from sqlalchemy.exc import OperationalError

    from app.main import database_busy_handler

    class DeadlockDetected(Exception):
        pass
    response = asyncio.run(database_busy_handler(None, OperationalError("x", {}, DeadlockDetected())))
    assert response.status_code == 503


@pytest.mark.parametrize("path,expected", [
    ("/app/d/SECRET-DEMO-TOKEN", "/app/d/***"),
    ("/app/d/SECRET-DEMO-TOKEN/orders?x=1", "/app/d/***/orders"),
    ("/public/ratings/abc123", "/public/ratings/***"),
    ("/rate/abc123", "/rate/***"),
    ("/public/track/LT-12345", "/public/track/***"),
    ("/track/LT-12345", "/track/***"),
    ("/organization-requests/status/REQ-1", "/organization-requests/status/***"),
    ("/orders/?search=09121112233", "/orders/"),
    ("/health", "/health"),
])
def test_access_log_hides_secret_paths_and_queries(path, expected):
    assert observability.redact_path(path) == expected


def test_access_log_filter_rewrites_the_uvicorn_record():
    import logging
    observability.configure_logging()
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                               ("1.2.3.4", "GET", "/app/d/SECRET-DEMO-TOKEN?a=1", "1.1", 200), None)
    for f in logging.getLogger("uvicorn.access").filters:
        f.filter(record)
    assert "SECRET-DEMO-TOKEN" not in record.getMessage() and "/app/d/***" in record.getMessage()
