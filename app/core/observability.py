"""
لاگ ساخت‌یافته و متریک داخلی (docs/operations-guide.md، مرحله ۵؛ تصمیم ت۹: هیچ داده‌ای به بیرون از سرور نمی‌رود).

هر خط لاگ JSON است و شناسه درخواست، سازمان، کاربر و وظیفه را دارد. نام، موبایل، نشانی و متن پیام در این فیلدها نیست و
کد برنامه هم متن پیام را لاگ نمی‌کند. متریک‌ها در GET /internal/metrics هستند و بدون METRICS_TOKEN این مسیر وجود ندارد.
"""
import json
import logging
import os
import sys
import time
import traceback
from contextvars import ContextVar
from datetime import datetime, timezone

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.core import request_context

REGISTRY = CollectorRegistry()
HTTP_REQUESTS = Counter("pasineh_http_requests_total", "درخواست‌های HTTP", ["method", "route", "status"], registry=REGISTRY)
HTTP_SECONDS = Histogram("pasineh_http_request_seconds", "زمان پاسخ HTTP", ["route"], registry=REGISTRY,
                         buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30))
HTTP_DB_QUERIES = Histogram("pasineh_http_db_queries", "شمار کوئری هر درخواست", ["route"], registry=REGISTRY,
                            buckets=(1, 2, 5, 10, 20, 50, 100, 200, 500))
DB_SECONDS = Histogram("pasineh_db_query_seconds", "زمان هر کوئری", registry=REGISTRY, buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1, 5, 30))
MESSAGES_PENDING = Gauge("pasineh_outbox_pending", "پیام‌های منتظر ارسال", registry=REGISTRY)
MESSAGES_OLDEST = Gauge("pasineh_outbox_oldest_seconds", "سن قدیمی‌ترین پیام منتظر", registry=REGISTRY)
MESSAGES_RETRYING = Gauge("pasineh_outbox_retrying", "پیام‌هایی که دست‌کم یک‌بار شکست خورده‌اند", registry=REGISTRY)
MESSAGES_FAILED = Gauge("pasineh_outbox_failed", "پیام‌های ناموفق", registry=REGISTRY)
TASKS_FAILED = Gauge("pasineh_task_failures", "وظایف ناموفق بررسی‌نشده", registry=REGISTRY)
QUEUE_DEPTH = Gauge("pasineh_celery_queue_depth", "طول صف Celery", registry=REGISTRY)
POOL_IN_USE = Gauge("pasineh_db_pool_in_use", "اتصال‌های در حال استفاده این پردازش", registry=REGISTRY)
EXCEPTIONS_OPEN = Gauge("pasineh_exceptions_open", "استثناهای باز", ["severity"], registry=REGISTRY)

task_id: ContextVar[str | None] = ContextVar("task_id", default=None)
task_organization: ContextVar[int | None] = ContextVar("task_organization", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        state = request_context.current.get() or {}
        data = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_context.request_id.get(),
            "organization_id": state.get("organization_id") or task_organization.get(),
            "user_id": state.get("user_id"),
            "task_id": task_id.get(),
        }
        if record.exc_info:
            data["exception"] = "".join(traceback.format_exception(*record.exc_info))[-4000:]
        return json.dumps({k: v for k, v in data.items() if v is not None}, ensure_ascii=False)


def _json_logs() -> bool:
    return os.getenv("LOG_FORMAT", "json").lower() == "json"


def configure_logging() -> None:
    """برای وب و worker. لاگ‌های uvicorn هم همین قالب را می‌گیرند تا یک نوع خط در فایل باشد."""
    if not _json_logs():
        return
    formatter = JsonFormatter()
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(logging.StreamHandler(sys.stdout))
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)
    for handler in root.handlers:
        handler.setFormatter(formatter)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(name).handlers:
            handler.setFormatter(formatter)


def format_celery_logger(logger: logging.Logger) -> None:
    if _json_logs():
        for handler in logger.handlers:
            handler.setFormatter(JsonFormatter())


# ---------------------------------------------------------------------------
# زمان کوئری
# ---------------------------------------------------------------------------
@event.listens_for(Engine, "before_cursor_execute")
def _before_query(conn, cursor, statement, parameters, context, executemany):
    conn.info["query_started"] = time.perf_counter()


@event.listens_for(Engine, "after_cursor_execute")
def _after_query(conn, cursor, statement, parameters, context, executemany):
    started = conn.info.pop("query_started", None)
    if started is not None:
        DB_SECONDS.observe(time.perf_counter() - started)
    state = request_context.current.get()
    if state is not None:
        state["queries"] = state.get("queries", 0) + 1


# ---------------------------------------------------------------------------
# متریک درخواست
# ---------------------------------------------------------------------------
class MetricsMiddleware:
    """پس از RequestContextMiddleware اجرا می‌شود. برچسب مسیر الگوی مسیر است (نه آدرس واقعی) تا شناسه و کد پیگیری در متریک نیاید."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = time.perf_counter()
        status = {"code": 500}

        async def track(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)
        try:
            await self.app(scope, receive, track)
        finally:
            route = getattr(scope.get("route"), "path", None) or "unmatched"
            HTTP_REQUESTS.labels(scope["method"], route, str(status["code"])).inc()
            HTTP_SECONDS.labels(route).observe(time.perf_counter() - started)
            state = request_context.current.get() or {}
            HTTP_DB_QUERIES.labels(route).observe(state.get("queries", 0))


def render_metrics(db) -> bytes:
    """عددهای وضعیت همان لحظه خوانده می‌شوند تا متریک با دیتابیس اختلاف نداشته باشد."""
    from sqlalchemy import func

    from app.database import engine
    from app.models_productivity import ACTIVE_EXCEPTION_STATUSES, OperationException, OutboundMessage, TaskFailure
    from app.services import outbox_service
    overview = outbox_service.overview(db)
    MESSAGES_PENDING.set(overview["pending"])
    MESSAGES_OLDEST.set(overview["oldest_pending_seconds"])
    MESSAGES_RETRYING.set(db.query(OutboundMessage).filter(OutboundMessage.status == "pending", OutboundMessage.attempts > 0).count())
    MESSAGES_FAILED.set(db.query(OutboundMessage).filter(OutboundMessage.status == "failed").count())
    TASKS_FAILED.set(db.query(TaskFailure).filter(TaskFailure.status == "failed").count())
    if overview["queue_depth"] is not None:
        QUEUE_DEPTH.set(overview["queue_depth"])
    in_use = getattr(engine.pool, "checkedout", None)
    if in_use is not None:
        POOL_IN_USE.set(in_use())
    counts = dict(db.query(OperationException.severity, func.count()).filter(OperationException.status.in_(ACTIVE_EXCEPTION_STATUSES))
                  .execution_options(skip_tenant_filter=True).group_by(OperationException.severity).all())
    for severity in ("low", "medium", "high", "critical"):
        EXCEPTIONS_OPEN.labels(severity).set(counts.get(severity, 0))
    return generate_latest(REGISTRY)
