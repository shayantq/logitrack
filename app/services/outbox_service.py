"""
صف پایدار پیام‌های بیرونی و ثبت وظایف شکست‌خورده (docs/operations-guide.md، مرحله ۱).

پیامک و ایمیل در همان تراکنش عملیات در outbound_messages ثبت می‌شوند: اگر عملیات rollback شود پیامی نیست و اگر
commit شود حتماً هست، حتی اگر Redis همان لحظه قطع باشد. ناشر هر ۱۵ ثانیه پیام‌های موعدرسیده را با lease برمی‌دارد.

تحویل «دست‌کم یک‌بار» است و «دقیقاً یک‌بار» تضمین نمی‌شود. provider_ref به‌عنوان localid به کاوه‌نگار می‌رود؛ طبق
مستندات، localid تکراری دوباره فرستاده نمی‌شود. dedupe_key مانع ثبت دوباره یک رویداد است.

ارسالی که نتیجه‌اش مبهم ماند (worker وسط ارسال مرد، یا پاسخ نیامد) پیش از تکرار با localid پرسیده می‌شود. اگر پاسخ روشن
نباشد پیام «نامعلوم» (unconfirmed) می‌شود: خودکار تکرار نمی‌شود و ناموفق هم حساب نمی‌شود تا ادمین پلتفرم آن را حل کند.

متن حساس (رمز موقت، کد بازیابی) فقط تا پایان ارسال نگه داشته می‌شود، دوباره ارسال نمی‌شود و بعد از پایان کار یا نامعلوم
شدن پاک می‌شود. گیرنده هم پس از پایان کار نیمه‌پنهان می‌شود. کد این فایل متن پیام را در لاگ نمی‌نویسد.
"""
import hashlib
import logging
import os
import random
import re
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models_productivity import MESSAGE_ACTIVE_STATUSES, MESSAGE_UNCONFIRMED, OutboundMessage, TaskFailure
from app.services import audit_service
from app.services.exceptions import ConflictError, NotFoundError

logger = logging.getLogger(__name__)

BATCH = 10
LEASE_MARGIN = timedelta(seconds=60)
MAX_ATTEMPTS = 5
REF_BITS = 53                    # در Long کاوه‌نگار و عدد صحیح امن جاوااسکریپت جا می‌شود
REF_RETRIES = 3
AMBIGUOUS = "ambiguous"
MANUAL_RESEND = "manual_resend"
CONFLICT = "localid_conflict"
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


def _lease() -> timedelta:
    """پردازش ناشر پس از time_limit وظیفه‌اش قطعاً کشته شده است؛ پیش از آن پیامش دوباره برداشته نمی‌شود."""
    from app.tasks import publish_messages_task
    return timedelta(seconds=publish_messages_task.time_limit) + LEASE_MARGIN


def new_provider_ref() -> int:
    """عدد تصادفی مثبت ۵۳ بیتی؛ در برابر تکرار مقاوم است، نه تضمین ریاضی. قید یکتای دیتابیس برخورد را می‌گیرد."""
    return 1 + secrets.randbelow(2 ** REF_BITS - 1)


def enqueue(db: Session, channel: str, recipient: str, body: str, *, subject: str | None = None, organization_id: int | None = None,
            sensitive: bool = False, expires_in: timedelta | None = None, dedupe_key: str | None = None,
            password_reset_id: int | None = None) -> OutboundMessage | None:
    """در تراکنش جاری ثبت می‌کند (بدون commit). رویدادی که قبلاً ثبت شده دوباره ثبت نمی‌شود."""
    now = _now()
    # provider_ref تکراری پیش از ثبت سنجیده می‌شود؛ برخورد هم‌زمان بسیار نادر را قید یکتای دیتابیس می‌گیرد
    message = OutboundMessage(organization_id=organization_id, channel=channel, recipient=recipient, subject=subject, body=body,
                              sensitive=sensitive, dedupe_key=dedupe_key, status="pending", created_at=now, next_attempt_at=now,
                              expires_at=now + expires_in if expires_in else None, provider_ref=_fresh_ref(db), password_reset_id=password_reset_id)
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


def _digits(value) -> str:
    return re.sub(r"\D", "", str(value or ""))[-10:]


def _fingerprint(text) -> str:
    """فقط برای مقایسه در حافظه؛ ذخیره یا لاگ نمی‌شود."""
    return hashlib.sha256(" ".join(str(text or "").split()).encode()).hexdigest()


def _conflicts(message: OutboundMessage, entry: dict) -> list[str]:
    """رکوردی که کاوه‌نگار برگرداند باید همین پیام باشد؛ فقط فیلدهای موجود در پاسخ سنجیده می‌شوند."""
    from app.services.messaging import _env
    fields = []
    if entry.get("receptor") and _digits(entry["receptor"]) != _digits(message.recipient):
        fields.append("receptor")
    if entry.get("sender") and _env("SMS_SENDER") and _digits(entry["sender"]) != _digits(_env("SMS_SENDER")):
        fields.append("sender")
    if entry.get("message") and _fingerprint(entry["message"]) != _fingerprint(message.body):
        fields.append("message")
    return fields


def _deliver(message: OutboundMessage):
    from app.services import messaging
    if message.channel == "sms":
        return messaging.deliver_sms(message.recipient, message.body, local_id=message.provider_ref)
    return messaging.deliver_email(message.recipient, message.subject or "", message.body)


def _unconfirmed(db: Session, message: OutboundMessage, note: str) -> None:
    """
    نتیجه نامعلوم: نه تکرار خودکار و نه ناموفق. متن حساس همین حالا و بدون نسخه دیگر پاک می‌شود و کد بازیابی‌ای که
    همین پیام حمل می‌کرد باطل می‌شود؛ کاربر از روند عادی کد تازه می‌گیرد. کدهای دیگر دست نمی‌خورند.
    """
    from app.models import PasswordReset
    from app.services.messaging import mask
    message.status, message.lease_until, message.last_error = MESSAGE_UNCONFIRMED, None, note[:300]
    if message.sensitive:
        message.body = None
        message.recipient = mask(message.recipient)
    if message.password_reset_id is not None:
        reset = db.query(PasswordReset).filter(PasswordReset.id == message.password_reset_id, PasswordReset.used_at.is_(None)).first()
        if reset is not None:
            from app.models import User
            reset.used_at = _now()
            owner = db.query(User).filter(User.id == reset.user_id).execution_options(skip_tenant_filter=True).first()
            audit_service.log(db, None, "auth.reset_invalidated", "کد بازیابی باطل شد؛ نتیجه پیامک آن نامعلوم ماند", target=owner,
                              organization_id=owner.organization_id if owner else None)


def _previous_outcome(message: OutboundMessage, now: datetime) -> str:
    """
    پیش از تکرار ارسالِ مبهم: «accepted» اگر کاوه‌نگار رکورد شناخته‌شده دارد، «resend» فقط برای وضعیت ۱۰۰ در بازه ۱۲ ساعته،
    و «unknown» برای هر پاسخ دیگر (خطا، ۴۲۶، بیرون از بازه یا کد ناشناخته).
    """
    from app.services import messaging
    window = timedelta(hours=messaging.STATUS_LOOKUP_WINDOW_HOURS)
    if message.first_attempt_at is None or message.first_attempt_at < now - window:
        return "unknown"
    # پاسخ وضعیت فقط از همان حسابی معتبر است که پیام با آن رفت؛ پیام قدیمی بدون اثر انگشت هم اعتماد نمی‌گیرد
    if message.provider_account is None or message.provider_account != messaging.provider_account():
        return "unknown"
    status = messaging.sms_status_by_localid(message.provider_ref)
    if status is None:
        return "unknown"
    if status == messaging.PROVIDER_NOT_RECORDED:
        return "resend"
    message.provider_status = status
    return "accepted" if status in messaging.PROVIDER_STATUS_LABELS else "unknown"


def publish_due(db: Session, now: datetime | None = None) -> dict:
    """
    پیام‌های موعدرسیده را می‌فرستد. پیامی که lease آن گذشته (worker مرده) هم برداشته می‌شود، ولی پیامک آن پیش از تکرار
    با localid پرسیده می‌شود. پیام نامعلوم هرگز برداشته نمی‌شود.
    """
    now = now or _now()
    due = db.query(OutboundMessage).filter(or_(
        and_(OutboundMessage.status == "pending", OutboundMessage.next_attempt_at <= now),
        and_(OutboundMessage.status == "sending", OutboundMessage.lease_until <= now),
    )).order_by(OutboundMessage.id).limit(BATCH).with_for_update(skip_locked=True).all()
    result = {"sent": 0, "retry": 0, "failed": 0, "expired": 0, "skipped": 0, "unconfirmed": 0}
    claimed, ambiguous = [], set()
    for message in due:
        # فقط پیامک را می‌شود از سرویس‌دهنده پرسید؛ ایمیل همان «دست‌کم یک‌بار» قبلی است
        if message.channel == "sms" and (message.status == "sending" or (message.last_error or "").startswith(AMBIGUOUS)):
            ambiguous.add(message.id)
        manual = message.last_error == MANUAL_RESEND
        if message.expires_at is not None and message.expires_at <= now and message.id not in ambiguous:
            _finish(message, "expired", now)
            result["expired"] += 1
        elif message.attempts >= MAX_ATTEMPTS and not manual and message.id not in ambiguous:
            _finish(message, "failed", now, message.last_error or "پایان مهلت ارسال")
            result["failed"] += 1
        else:
            message.status, message.lease_until = "sending", now + _lease()
            message.attempts += 1
            if message.first_attempt_at is None:
                message.first_attempt_at = now
                if message.channel == "sms":
                    from app.services.messaging import provider_account
                    message.provider_account = provider_account()
            claimed.append(message.id)
    db.commit()

    for message_id in claimed:
        message = db.get(OutboundMessage, message_id)
        if message_id in ambiguous and message.channel == "sms":
            outcome = _previous_outcome(message, _now())
            if outcome == "accepted":
                _finish(message, "sent", _now())
                result["sent"] += 1
                db.commit()
                continue
            if outcome == "unknown":
                _unconfirmed(db, message, f"{AMBIGUOUS}: نتیجه ارسال قبلی روشن نیست")
                result["unconfirmed"] += 1
                db.commit()
                continue
        if message.expires_at is not None and message.expires_at <= _now():
            _finish(message, "expired", _now())
            result["expired"] += 1
            db.commit()
            continue
        try:
            delivered = _deliver(message)
        except Exception as error:      # شکست یک پیام نباید بقیه را نگه دارد
            from app.services.messaging import AmbiguousSend
            logger.warning("ارسال پیام %s ناموفق بود: %s", message.id, type(error).__name__)
            unclear = isinstance(error, AmbiguousSend)
            if unclear and message.channel == "sms":
                # پاسخ نیامد؛ دور بعد پیش از هر تکراری با localid پرسیده می‌شود
                message.status, message.lease_until, message.last_error = "pending", None, f"{AMBIGUOUS}: {type(error).__name__}: {error}"[:300]
                message.next_attempt_at = _now() + _delay(message.attempts)
                result["retry"] += 1
            elif message.attempts >= MAX_ATTEMPTS:
                _finish(message, "failed", now, _clean_error(error))
                result["failed"] += 1
            else:
                message.status, message.lease_until, message.last_error = "pending", None, _clean_error(error)
                message.next_attempt_at = _now() + _delay(message.attempts)
                result["retry"] += 1
        else:
            if isinstance(delivered, dict) and (fields := _conflicts(message, delivered)):
                logger.error("پاسخ کاوه‌نگار برای پیام %s با خود پیام نمی‌خواند: %s", message.id, ",".join(fields))
                _finish(message, "failed", _now(), f"{CONFLICT}: {','.join(fields)}")
                result["failed"] += 1
            else:
                if isinstance(delivered, dict):
                    message.provider_message_id = _int_or_none(delivered.get("messageid"))
                    message.provider_status = _int_or_none(delivered.get("status"))
                _finish(message, "sent" if delivered else "skipped", _now())
                result["sent" if delivered else "skipped"] += 1
        db.commit()
    return result


def _int_or_none(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def record_failure(db: Session, task_name: str, error: Exception, *, task_id: str | None = None, organization_id: int | None = None) -> None:
    db.add(TaskFailure(task_name=task_name[:80], task_id=task_id, organization_id=organization_id, error=_clean_error(error),
                       created_at=_now(), status="failed"))
    db.commit()


def purge_old(db: Session, now: datetime | None = None) -> dict:
    now = now or _now()
    # پیام نامعلوم تا حل شدن به دست ادمین می‌ماند
    done = db.query(OutboundMessage).filter(OutboundMessage.status.notin_((*MESSAGE_ACTIVE_STATUSES, MESSAGE_UNCONFIRMED)),
                                            OutboundMessage.created_at < now - KEEP_DONE).delete(synchronize_session=False)
    failures = db.query(TaskFailure).filter(TaskFailure.created_at < now - KEEP_FAILURES).delete(synchronize_session=False)
    db.commit()
    return {"messages": done, "failures": failures}


# ---------------------------------------------------------------------------
# دید و اجرای دوباره (کارکنان پلتفرم)
# ---------------------------------------------------------------------------
def _message_out(m: OutboundMessage) -> dict:
    """پذیرش سرویس‌دهنده (status) و وضعیت رسیدن (provider_status) جدا برمی‌گردند؛ کد ناشناخته برچسب ندارد."""
    from app.services.messaging import PROVIDER_STATUS_LABELS, mask
    return {"id": m.id, "channel": m.channel, "recipient": mask(m.recipient), "organization_id": m.organization_id, "status": m.status,
            "attempts": m.attempts, "last_error": m.last_error, "created_at": m.created_at, "first_attempt_at": m.first_attempt_at,
            "sensitive": m.sensitive, "replayable": m.body is not None, "conflict": (m.last_error or "").startswith(CONFLICT),
            "provider_status": m.provider_status, "provider_status_label": PROVIDER_STATUS_LABELS.get(m.provider_status)}


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
        "unconfirmed": [_message_out(m) for m in db.query(OutboundMessage).filter(OutboundMessage.status == MESSAGE_UNCONFIRMED)
                        .order_by(OutboundMessage.id.desc()).limit(LIST_LIMIT).all()],
        "tasks": [_task_out(t) for t in db.query(TaskFailure).filter(TaskFailure.status == "failed")
                  .order_by(TaskFailure.id.desc()).limit(LIST_LIMIT).all()],
    }


def retry_message(db: Session, user, message_id: int, reason: str, conflict_reviewed: bool = False) -> dict:
    """فقط پیام ناموفق. برخورد localid فقط پس از بررسی صریح و با provider_ref تازه دوباره فرستاده می‌شود."""
    message = db.query(OutboundMessage).filter(OutboundMessage.id == message_id).with_for_update().first()
    if message is None:
        raise NotFoundError("این پیام یافت نشد.")
    if message.status != "failed" or message.body is None:
        raise ConflictError("فقط پیام ناموفقِ غیرحساس دوباره ارسال می‌شود؛ رمز موقت و کد بازیابی باید دوباره صادر شوند.")
    conflict = (message.last_error or "").startswith(CONFLICT)
    if conflict and not conflict_reviewed:
        raise ConflictError("پاسخ کاوه‌نگار با این پیام نمی‌خواند؛ پیش از ارسال دوباره، بررسی برخورد شناسه را تأیید کنید.")
    if conflict:
        message.provider_ref = _fresh_ref(db)
    message.status, message.attempts, message.next_attempt_at, message.last_error = "pending", 0, _now(), None
    audit_service.log(db, user, "platform.message_retry", f"ارسال دوباره پیام شماره {message.id}{' با شناسه تازه پس از برخورد' if conflict else ''}",
                      target_type="outbound_message", target_id=message.id, organization_id=message.organization_id, reason=reason)
    db.commit()
    return _message_out(message)


def _fresh_ref(db: Session) -> int:
    for _ in range(REF_RETRIES):
        ref = new_provider_ref()
        if not db.query(OutboundMessage.id).filter(OutboundMessage.provider_ref == ref).first():
            return ref
    raise RuntimeError("provider_ref یکتا پس از چند تلاش ساخته نشد")


def resolve_unconfirmed(db: Session, user, message_id: int, action: str, reason: str, accept_duplicate_risk: bool = False) -> dict:
    """
    حل دستی پیام نامعلوم با دلیل و ثبت در گزارش فعالیت. قفل ردیف و شرط وضعیت، حل دوباره یا هم‌زمان را رد می‌کند.
    confirm_accepted: پذیرش سرویس‌دهنده پس از بررسی ثبت می‌شود و چیزی فرستاده نمی‌شود.
    resend: فقط پیام غیرحساس، با پذیرش صریح احتمال پیامک تکراری و همان provider_ref تا localid کاوه‌نگار اثر کند.
    """
    message = db.query(OutboundMessage).filter(OutboundMessage.id == message_id).with_for_update().first()
    if message is None:
        raise NotFoundError("این پیام یافت نشد.")
    if message.status != MESSAGE_UNCONFIRMED:
        raise ConflictError("این پیام دیگر در وضعیت نامعلوم نیست؛ احتمالاً همکار دیگری آن را حل کرده است.")
    if action == "confirm_accepted":
        if message.channel == "sms" and message.provider_status is None:
            message.provider_status = _lookup_if_in_window(message)
        _finish(message, "sent", _now())
        label = "پذیرش سرویس‌دهنده تأیید شد"
    else:
        if message.sensitive or message.body is None:
            raise ConflictError("پیام حساس دوباره فرستاده نمی‌شود؛ کد یا رمز باید از روند عادی دوباره صادر شود.")
        if not accept_duplicate_risk:
            raise ConflictError("ارسال دوباره ممکن است پیامک تکراری بفرستد؛ این خطر را صریحاً بپذیرید.")
        message.status, message.next_attempt_at, message.last_error = "pending", _now(), MANUAL_RESEND
        label = "ارسال دوباره با پذیرش خطر تکرار"
    audit_service.log(db, user, "platform.message_resolve", f"پیام شماره {message.id}: {label}", target_type="outbound_message",
                      target_id=message.id, organization_id=message.organization_id, reason=reason)
    db.commit()
    return _message_out(message)


def _lookup_if_in_window(message: OutboundMessage) -> int | None:
    from app.services import messaging
    if message.first_attempt_at is None or message.first_attempt_at < _now() - timedelta(hours=messaging.STATUS_LOOKUP_WINDOW_HOURS):
        return None
    status = messaging.sms_status_by_localid(message.provider_ref)
    return None if status in (None, messaging.PROVIDER_NOT_RECORDED) else status


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
