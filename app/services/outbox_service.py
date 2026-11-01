"""
صف پایدار پیام‌های بیرونی و ثبت وظایف شکست‌خورده (docs/operations-guide.md، مرحله ۱).

پیامک و ایمیل در همان تراکنش عملیات در outbound_messages ثبت می‌شوند: اگر عملیات rollback شود پیامی نیست و اگر
commit شود حتماً هست، حتی اگر Redis همان لحظه قطع باشد. ناشر هر ۱۵ ثانیه پیام‌های موعدرسیده را با lease برمی‌دارد.

تحویل «دست‌کم یک‌بار» است: اگر worker بعد از قبول سرویس‌دهنده و پیش از ثبت نتیجه بمیرد، ارسال تکرار می‌شود. شناسه
پیام به‌عنوان localid به کاوه‌نگار می‌رود و dedupe_key مانع ثبت دوباره یک رویداد است.

متن حساس (رمز موقت، کد بازیابی) فقط تا پایان ارسال نگه داشته می‌شود، دوباره ارسال نمی‌شود و بعد از پایان کار پاک
می‌شود. گیرنده هم پس از پایان کار نیمه‌پنهان می‌شود. کد این فایل متن پیام را در لاگ نمی‌نویسد.
"""
import logging
import os
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models_productivity import MESSAGE_ACTIVE_STATUSES, OutboundMessage, TaskFailure
from app.services import audit_service
from app.services.exceptions import ConflictError, NotFoundError

logger = logging.getLogger(__name__)

BATCH = 10
LEASE = timedelta(minutes=2)
MAX_ATTEMPTS = 5
BASE_DELAY = 30
MAX_DELAY = 1800
KEEP_DONE = timedelta(days=30)
KEEP_FAILURES = timedelta(days=90)
LIST_LIMIT = 100
# وظایف دوره‌ای بدون ورودی که اجرای دوباره‌شان امن است؛ گزارش‌ها را خود کاربر دوباره می‌خواهد
REPLAYABLE_TASKS = {
    "tasks.check_low_stock", "tasks.expire_overdue_orders", "tasks.refresh_current_prices", "tasks.recalculate_reorder_points",
    "tasks.check_replenishment_rules", "tasks.detect_exceptions", "tasks.reconcile_stock", "tasks.classify_abc",
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def enqueue(db: Session, channel: str, recipient: str, body: str, *, subject: str | None = None, organization_id: int | None = None,
            sensitive: bool = False, expires_in: timedelta | None = None, dedupe_key: str | None = None) -> OutboundMessage | None:
    """در تراکنش جاری ثبت می‌کند (بدون commit). رویدادی که قبلاً ثبت شده دوباره ثبت نمی‌شود."""
    now = _now()
    message = OutboundMessage(organization_id=organization_id, channel=channel, recipient=recipient, subject=subject, body=body,
                              sensitive=sensitive, dedupe_key=dedupe_key, status="pending", created_at=now, next_attempt_at=now,
                              expires_at=now + expires_in if expires_in else None)
    if dedupe_key is None:
        db.add(message)
        return message
    try:
        with db.begin_nested():
            db.add(message)
            db.flush()
    except IntegrityError:
        return None
    return message


def _delay(attempts: int) -> timedelta:
    """عقب‌نشینی نمایی با jitter تا تلاش‌های دوباره هم‌زمان نشوند."""
    base = min(BASE_DELAY * 2 ** max(attempts - 1, 0), MAX_DELAY)
    return timedelta(seconds=random.uniform(base / 2, base))


def _clean_error(error: Exception) -> str:
    text = f"{type(error).__name__}: {error}"
    key = os.getenv("SMS_API_KEY", "").strip()
    if key:
        text = text.replace(key, "***")
    return text[:300]


def _finish(message: OutboundMessage, status: str, now: datetime, error: str | None = None) -> None:
    from app.services.messaging import mask
    message.status, message.lease_until, message.last_error = status, None, error
    if status == "sent":
        message.sent_at = now
    # متن و گیرنده کامل فقط برای پیام غیرحساسی می‌ماند که شاید دوباره ارسال شود
    if status != "failed" or message.sensitive:
        message.body = None
        message.recipient = mask(message.recipient)


def _deliver(message: OutboundMessage) -> bool:
    from app.services import messaging
    if message.channel == "sms":
        return messaging.deliver_sms(message.recipient, message.body, local_id=message.id)
    return messaging.deliver_email(message.recipient, message.subject or "", message.body)


def publish_due(db: Session, now: datetime | None = None) -> dict:
    """پیام‌های موعدرسیده را می‌فرستد. پیامی که lease آن گذشته (worker مرده) هم دوباره برداشته می‌شود."""
    now = now or _now()
    due = db.query(OutboundMessage).filter(or_(
        and_(OutboundMessage.status == "pending", OutboundMessage.next_attempt_at <= now),
        and_(OutboundMessage.status == "sending", OutboundMessage.lease_until <= now),
    )).order_by(OutboundMessage.id).limit(BATCH).with_for_update(skip_locked=True).all()
    result = {"sent": 0, "retry": 0, "failed": 0, "expired": 0, "skipped": 0}
    claimed = []
    for message in due:
        if message.expires_at is not None and message.expires_at <= now:
            _finish(message, "expired", now)
            result["expired"] += 1
        elif message.attempts >= MAX_ATTEMPTS:
            _finish(message, "failed", now, message.last_error or "پایان مهلت ارسال")
            result["failed"] += 1
        else:
            message.status, message.lease_until = "sending", now + LEASE
            message.attempts += 1
            claimed.append(message.id)
    db.commit()

    for message_id in claimed:
        message = db.get(OutboundMessage, message_id)
        try:
            delivered = _deliver(message)
        except Exception as error:      # شکست یک پیام نباید بقیه را نگه دارد
            logger.warning("ارسال پیام %s ناموفق بود: %s", message.id, type(error).__name__)
            if message.attempts >= MAX_ATTEMPTS:
                _finish(message, "failed", now, _clean_error(error))
                result["failed"] += 1
            else:
                message.status, message.lease_until, message.last_error = "pending", None, _clean_error(error)
                message.next_attempt_at = _now() + _delay(message.attempts)
                result["retry"] += 1
        else:
            _finish(message, "sent" if delivered else "skipped", _now())
            result["sent" if delivered else "skipped"] += 1
        db.commit()
    return result


def record_failure(db: Session, task_name: str, error: Exception, *, task_id: str | None = None, organization_id: int | None = None) -> None:
    db.add(TaskFailure(task_name=task_name[:80], task_id=task_id, organization_id=organization_id, error=_clean_error(error),
                       created_at=_now(), status="failed"))
    db.commit()


def purge_old(db: Session, now: datetime | None = None) -> dict:
    now = now or _now()
    done = db.query(OutboundMessage).filter(OutboundMessage.status.notin_(MESSAGE_ACTIVE_STATUSES),
                                            OutboundMessage.created_at < now - KEEP_DONE).delete(synchronize_session=False)
    failures = db.query(TaskFailure).filter(TaskFailure.created_at < now - KEEP_FAILURES).delete(synchronize_session=False)
    db.commit()
    return {"messages": done, "failures": failures}


# ---------------------------------------------------------------------------
# دید و اجرای دوباره (کارکنان پلتفرم)
# ---------------------------------------------------------------------------
def _message_out(m: OutboundMessage) -> dict:
    from app.services.messaging import mask
    return {"id": m.id, "channel": m.channel, "recipient": mask(m.recipient), "organization_id": m.organization_id, "status": m.status,
            "attempts": m.attempts, "last_error": m.last_error, "created_at": m.created_at, "replayable": m.body is not None}


def _task_out(t: TaskFailure) -> dict:
    return {"id": t.id, "task_name": t.task_name, "organization_id": t.organization_id, "error": t.error, "created_at": t.created_at,
            "status": t.status, "replayable": t.status == "failed" and t.task_name in REPLAYABLE_TASKS}


def _queue_depth() -> int | None:
    """طول صف پیش‌فرض Celery در Redis؛ None اگر Redis در دسترس نباشد."""
    from app.core.rate_limit import _redis
    client = _redis()
    if client is None:
        return None
    try:
        return int(client.llen("celery"))
    except Exception:
        return None


def overview(db: Session) -> dict:
    """متن پیام هرگز برنمی‌گردد و گیرنده نیمه‌پنهان است."""
    oldest = db.query(func.min(OutboundMessage.created_at)).filter(OutboundMessage.status.in_(MESSAGE_ACTIVE_STATUSES)).scalar()
    return {
        "pending": db.query(OutboundMessage).filter(OutboundMessage.status.in_(MESSAGE_ACTIVE_STATUSES)).count(),
        "oldest_pending_seconds": int((_now() - oldest).total_seconds()) if oldest else 0,
        "queue_depth": _queue_depth(),
        "messages": [_message_out(m) for m in db.query(OutboundMessage).filter(OutboundMessage.status == "failed")
                     .order_by(OutboundMessage.id.desc()).limit(LIST_LIMIT).all()],
        "tasks": [_task_out(t) for t in db.query(TaskFailure).filter(TaskFailure.status == "failed")
                  .order_by(TaskFailure.id.desc()).limit(LIST_LIMIT).all()],
    }


def retry_message(db: Session, user, message_id: int, reason: str) -> dict:
    message = db.query(OutboundMessage).filter(OutboundMessage.id == message_id).with_for_update().first()
    if message is None:
        raise NotFoundError("این پیام یافت نشد.")
    if message.status != "failed" or message.body is None:
        raise ConflictError("فقط پیام ناموفقِ غیرحساس دوباره ارسال می‌شود؛ رمز موقت و کد بازیابی باید دوباره صادر شوند.")
    message.status, message.attempts, message.next_attempt_at, message.last_error = "pending", 0, _now(), None
    audit_service.log(db, user, "platform.message_retry", f"ارسال دوباره پیام شماره {message.id}", target_type="outbound_message",
                      target_id=message.id, organization_id=message.organization_id, reason=reason)
    db.commit()
    return _message_out(message)


def replay_task(db: Session, user, failure_id: int, reason: str, send_task) -> dict:
    failure = db.query(TaskFailure).filter(TaskFailure.id == failure_id).with_for_update().first()
    if failure is None:
        raise NotFoundError("این رکورد یافت نشد.")
    if failure.status != "failed" or failure.task_name not in REPLAYABLE_TASKS:
        raise ConflictError("این وظیفه قابل اجرای دوباره نیست.")
    failure.status, failure.replayed_by_id, failure.replayed_at = "replayed", user.id, _now()
    audit_service.log(db, user, "platform.task_replay", f"اجرای دوباره {failure.task_name}", target_type="task_failure",
                      target_id=failure.id, organization_id=failure.organization_id, reason=reason)
    db.commit()
    send_task(failure.task_name)
    return _task_out(failure)
