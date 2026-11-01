"""
شناسه درخواست و خط پایان وظیفه روی worker واقعی Celery با broker حافظه‌ای (CI سرویس Redis ندارد).
آزمون با Redis و worker جدا در docs/operations-guide.md ثبت شده است.
"""
import json
import logging

import pytest
from celery.contrib.testing.worker import start_worker

from app.celery_app import celery_app
from app.core import observability, request_context

pytestmark = pytest.mark.integration


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.formatter = observability.JsonFormatter()
        self.lines = []

    def emit(self, record):
        self.lines.append(json.loads(self.format(record)))


@celery_app.task(name="tests.echo_request_id")
def _echo_request_id(secret):
    logging.getLogger("app.tasks").info("داخل وظیفه آزمون")
    return request_context.request_id.get()


@pytest.fixture()
def worker():
    conf = celery_app.conf
    saved = conf.broker_url, conf.result_backend
    conf.broker_url, conf.result_backend = "memory://", "cache+memory://"
    celery_app.backend  # noqa: B018  مقدار تازه خوانده شود
    with start_worker(celery_app, pool="solo", perform_ping_check=False, loglevel="INFO"):
        yield
    conf.broker_url, conf.result_backend = saved


def test_request_id_reaches_the_worker_and_inputs_stay_out_of_logs(worker):
    capture = _Capture()
    app_logger = logging.getLogger("app.tasks")
    app_logger.addHandler(capture)
    app_logger.setLevel(logging.INFO)
    secret = "09121234567"
    token = request_context.request_id.set("req-worker-1234")
    try:
        result = _echo_request_id.delay(secret).get(timeout=20)
    finally:
        request_context.request_id.reset(token)
        app_logger.removeHandler(capture)
    assert result == "req-worker-1234"
    inside = next(line for line in capture.lines if line["message"] == "داخل وظیفه آزمون")
    assert inside["request_id"] == "req-worker-1234" and inside["task_id"]
    end = next(line for line in capture.lines if line.get("task_name") == "tests.echo_request_id")
    assert end["outcome"] == "SUCCESS" and end["duration_ms"] >= 0 and end["request_id"] == "req-worker-1234"
    assert secret not in json.dumps(capture.lines)
