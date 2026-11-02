"""
worker جدا برای tests/integration/test_export_worker_kill.py. broker فایلی است تا آزمون به Redis نیاز نداشته باشد.
وظیفه همان build_export را اجرا می‌کند، ولی نوشتن فایل نیمه‌کاره می‌ماند تا سقف سخت زمان پردازش را بکشد.
"""
import os
import time

from celery import Celery

from app.core import storage
from app.database import SessionLocal
from app.services import platform_service

QUEUE = os.environ.get("EXPORT_KILL_QUEUE", "")
TRANSPORT = {"data_folder_in": QUEUE, "data_folder_out": QUEUE, "control_folder": QUEUE, "store_processed": False}
app = Celery("export-kill", broker="filesystem://", broker_transport_options=TRANSPORT)
app.conf.update(worker_prefetch_multiplier=1, task_ignore_result=True, worker_hijack_root_logger=False)


def _stuck_save(relative_path: str, data: bytes) -> str:
    path = storage._resolve(relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.with_suffix(path.suffix + ".tmp").write_bytes(data[:16])
    # ضربان: تا پردازش زنده است این فایل به‌روز می‌شود و آزمون از توقفش مرگ پردازش را می‌فهمد
    heartbeat = storage.MEDIA_ROOT / "heartbeat"
    for _ in range(240):
        heartbeat.write_text(str(time.time()))
        time.sleep(0.5)
    return relative_path


@app.task(name="tests.export_kill_slow")
def slow_export(export_id: int):
    storage.save = _stuck_save
    db = SessionLocal()
    try:
        platform_service.build_export(db, export_id)
    finally:
        db.close()
