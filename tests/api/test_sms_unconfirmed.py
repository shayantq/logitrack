"""
پیامک با نتیجه نامعلوم (CEL-02، یافته ۳): provider_ref پایدار، پرسیدن وضعیت با localid پیش از تکرار، وضعیت unconfirmed و حل دستی.
کاوه‌نگار ساختگی رفتار مستند را بازی می‌کند: localid تکراری دوباره فرستاده نمی‌شود و رکورد قبلی برمی‌گردد. پیامک واقعی فرستاده نمی‌شود.
"""
import logging
import urllib.error
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core.security import create_access_token
from app.core.tenancy import set_tenant
from app.models import AuditLog, Organization, RoleEnum, User
from app.models_productivity import OutboundMessage
from app.services import messaging, outbox_service

BODY = "پسینه: سفارش شما ثبت شد"
SECRET_CODE = "482913"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.username, user.id, timedelta(minutes=5))}"}


class Kavenegar:
    """رکورد هر localid یک بار ساخته می‌شود؛ lookup=None یعنی پاسخ روشن نیست (۴۲۶، خطا، قطع)."""

    def __init__(self):
        self.records, self.sends, self.lookups = {}, 0, 0
        self.lookup_override = "real"
        self.after_accept = None          # استثنایی که پس از پذیرش، پیش از رسیدن پاسخ رخ می‌دهد
        self.before_accept = None
        self.reply_receptor = None

    def deliver(self, mobile, text, local_id=None):
        if self.before_accept:
            raise self.before_accept
        if local_id not in self.records:
            self.sends += 1
            self.records[local_id] = {"messageid": 9000 + self.sends, "status": 1, "receptor": self.reply_receptor or mobile, "message": text}
        if self.after_accept:
            raise self.after_accept
        return dict(self.records[local_id])

    def lookup(self, local_id):
        self.lookups += 1
        if self.lookup_override != "real":
            return self.lookup_override
        record = self.records.get(local_id)
        return record["status"] if record else messaging.PROVIDER_NOT_RECORDED


@pytest.fixture()
def env(api_env, monkeypatch):
    monkeypatch.setenv("SMS_PROVIDER", "kavenegar")
    monkeypatch.setenv("SMS_API_KEY", "SECRETKEY")
    provider = Kavenegar()
    monkeypatch.setattr(messaging, "deliver_sms", provider.deliver)
    monkeypatch.setattr(messaging, "sms_status_by_localid", provider.lookup)
    client, Session = api_env
    db = Session()
    org = Organization(name="آلفا", slug="alpha")
    db.add(org)
    db.commit()
    set_tenant(db, org.id)
    org_admin = User(username="adm", email="a@x.io", role=RoleEnum.ORG_ADMIN, hashed_password="x")
    db.add(org_admin)
    db.commit()
    set_tenant(db, None)
    root = User(username="root", email="r@x.io", role=RoleEnum.PLATFORM_ADMIN, hashed_password="x")
    support = User(username="sup", email="s@x.io", role=RoleEnum.PLATFORM_SUPPORT, hashed_password="x")
    db.add_all([root, support])
    db.commit()
    yield SimpleNamespace(client=client, db=db, Session=Session, provider=provider, root=root, support=support, org_admin=org_admin)
    db.close()


def _queue(env, body=BODY, **options) -> OutboundMessage:
    message = outbox_service.enqueue(env.db, "sms", "09121112233", body, **options)
    env.db.commit()
    return message


def _row(env, message_id) -> OutboundMessage:
    env.db.expire_all()
    return env.db.get(OutboundMessage, message_id)


def _crash_mid_send(env, message, before_accept=False):
    """worker وسط ارسال می‌میرد: نتیجه commit نمی‌شود و ردیف با lease در sending می‌ماند."""
    setattr(env.provider, "before_accept" if before_accept else "after_accept", SystemExit("worker killed"))
    with pytest.raises(SystemExit):
        outbox_service.publish_due(env.db)
    env.db.rollback()
    env.provider.after_accept = env.provider.before_accept = None
    row = _row(env, message.id)
    assert row.status == "sending" and row.first_attempt_at is not None
    return row


def _after_lease():
    return _now() + outbox_service._lease() + timedelta(seconds=1)


def _resolve(env, message_id, user=None, **body):
    return env.client.post(f"/platform/operations/messages/{message_id}/resolve", headers=_auth(user or env.root), json={"reason": "بررسی شد", **body})


def test_new_reference_is_random_53_bit_and_old_rows_keep_their_id(env):
    message = _queue(env)
    assert 1 <= message.provider_ref < 2 ** 53 and message.provider_ref != message.id
    legacy = OutboundMessage(channel="sms", recipient="09121112233", body=BODY, status="pending", created_at=_now(), next_attempt_at=_now(), provider_ref=0)
    env.db.add(legacy)
    env.db.flush()
    legacy.provider_ref = legacy.id                          # همان پرکردن مایگریشن ۰۰۴۴
    env.db.commit()
    outbox_service.publish_due(env.db)
    assert legacy.id in env.provider.records and message.provider_ref in env.provider.records


def test_crash_after_acceptance_is_settled_by_lookup_without_resending(env):
    message = _queue(env)
    _crash_mid_send(env, message)
    assert outbox_service.publish_due(env.db, _after_lease())["sent"] == 1
    row = _row(env, message.id)
    assert row.status == "sent" and row.provider_status == 1 and env.provider.sends == 1


def test_status_100_inside_the_window_resends_with_the_same_reference(env):
    message = _queue(env)
    _crash_mid_send(env, message, before_accept=True)
    assert outbox_service.publish_due(env.db, _after_lease())["sent"] == 1
    assert env.provider.sends == 1 and list(env.provider.records) == [message.provider_ref]


def test_outside_the_lookup_window_the_outcome_stays_unknown(env):
    message = _queue(env)
    row = _crash_mid_send(env, message)
    row.first_attempt_at = _now() - timedelta(hours=13)
    env.db.commit()
    assert outbox_service.publish_due(env.db, _after_lease())["unconfirmed"] == 1
    row = _row(env, message.id)
    assert row.status == "unconfirmed" and env.provider.lookups == 0 and env.provider.sends == 1


@pytest.mark.parametrize("answer", [None])
def test_http_426_or_unclear_lookup_is_unknown_not_failed(env, answer):
    message = _queue(env)
    _crash_mid_send(env, message)
    env.provider.lookup_override = answer
    outbox_service.publish_due(env.db, _after_lease())
    row = _row(env, message.id)
    assert row.status == "unconfirmed" and row.status != "failed" and env.provider.sends == 1


def test_unconfirmed_is_never_picked_up_again(env):
    message = _queue(env)
    _crash_mid_send(env, message)
    env.provider.lookup_override = None
    outbox_service.publish_due(env.db, _after_lease())
    for days in (1, 30, 400):
        assert outbox_service.publish_due(env.db, _now() + timedelta(days=days))["sent"] == 0
    assert _row(env, message.id).status == "unconfirmed" and env.provider.sends == 1
    assert env.client.post(f"/platform/operations/messages/{message.id}/retry", headers=_auth(env.root), json={"reason": "دوباره"}).status_code == 400


def test_lost_response_is_looked_up_before_any_retry(env):
    message = _queue(env)
    env.provider.after_accept = messaging.AmbiguousSend("TimeoutError")
    outbox_service.publish_due(env.db)
    env.provider.after_accept = None
    row = _row(env, message.id)
    assert row.status == "pending" and row.last_error.startswith("ambiguous")
    outbox_service.publish_due(env.db, _now() + timedelta(hours=1))
    assert _row(env, message.id).status == "sent" and env.provider.sends == 1 and env.provider.lookups == 1


@pytest.mark.parametrize("code,delivered", [(6, False), (10, True), (11, False), (13, False), (14, False)])
def test_provider_status_is_kept_apart_from_acceptance(env, code, delivered):
    message = _queue(env)
    _crash_mid_send(env, message)
    env.provider.records[message.provider_ref]["status"] = code
    outbox_service.publish_due(env.db, _after_lease())
    row = _row(env, message.id)
    assert row.status == "sent" and row.provider_status == code
    label = outbox_service._message_out(row)["provider_status_label"]
    assert (label == "رسیده به گیرنده") is delivered


def test_unknown_future_provider_code_is_not_treated_as_success(env):
    message = _queue(env)
    _crash_mid_send(env, message)
    env.provider.records[message.provider_ref]["status"] = 42
    outbox_service.publish_due(env.db, _after_lease())
    row = _row(env, message.id)
    assert row.status == "unconfirmed" and row.provider_status == 42 and outbox_service._message_out(row)["provider_status_label"] is None


def test_matching_reply_is_sent_and_conflicting_reply_needs_review(env):
    good = _queue(env)
    outbox_service.publish_due(env.db)
    assert _row(env, good.id).status == "sent" and _row(env, good.id).provider_message_id == 9001
    env.provider.reply_receptor = "09350000000"
    bad = _queue(env, body="پیام دیگر")
    outbox_service.publish_due(env.db)
    row = _row(env, bad.id)
    assert row.status == "failed" and row.last_error.startswith("localid_conflict") and "receptor" in row.last_error
    url = f"/platform/operations/messages/{bad.id}/retry"
    assert env.client.post(url, headers=_auth(env.root), json={"reason": "بررسی"}).status_code == 400
    old_ref = row.provider_ref
    res = env.client.post(url, headers=_auth(env.root), json={"reason": "برخورد بررسی شد", "conflict_reviewed": True})
    assert res.status_code == 200, res.text
    assert _row(env, bad.id).provider_ref != old_ref and _row(env, bad.id).status == "pending"


def _unconfirmed(env, **options) -> OutboundMessage:
    message = _queue(env, **options)
    _crash_mid_send(env, message)
    env.provider.lookup_override = None
    outbox_service.publish_due(env.db, _after_lease())
    env.provider.lookup_override = "real"
    assert _row(env, message.id).status == "unconfirmed"
    return message


def test_confirming_acceptance_is_admin_only_audited_and_happens_once(env):
    message = _unconfirmed(env)
    assert _resolve(env, message.id, env.support, action="confirm_accepted").status_code == 403
    assert _resolve(env, message.id, env.org_admin, action="confirm_accepted").status_code == 403
    res = _resolve(env, message.id, action="confirm_accepted")
    assert res.status_code == 200, res.text
    row = _row(env, message.id)
    assert row.status == "sent" and row.provider_status == 1 and row.body is None and env.provider.sends == 1
    assert _resolve(env, message.id, action="confirm_accepted").status_code == 400
    assert env.db.query(AuditLog).filter(AuditLog.action == "platform.message_resolve").count() == 1


def test_resend_needs_risk_acceptance_and_keeps_reference_and_history(env):
    message = _unconfirmed(env)
    before = _row(env, message.id)
    ref, attempts = before.provider_ref, before.attempts
    assert _resolve(env, message.id, action="resend").status_code == 400
    assert _resolve(env, message.id, action="resend", accept_duplicate_risk=True).status_code == 200
    row = _row(env, message.id)
    assert row.status == "pending" and row.provider_ref == ref and row.attempts == attempts
    outbox_service.publish_due(env.db)
    assert _row(env, message.id).status == "sent" and env.provider.sends == 1     # localid تکراری دوباره فرستاده نشد


def test_sensitive_message_is_erased_and_never_resent(env):
    message = _unconfirmed(env, body=f"کد بازیابی: {SECRET_CODE}", sensitive=True, expires_in=timedelta(minutes=10))
    row = _row(env, message.id)
    assert row.body is None and "***" in row.recipient
    assert _resolve(env, message.id, action="resend", accept_duplicate_risk=True).status_code == 400
    assert _resolve(env, message.id, action="confirm_accepted").status_code == 200


def test_restored_database_reuses_ids_but_not_provider_references(env):
    first = _queue(env)
    outbox_service.publish_due(env.db)
    first_id, first_ref = first.id, first.provider_ref
    env.db.query(OutboundMessage).delete()                     # بازیابی بکاپ قدیمی: شناسه ردیف دوباره از همان عدد شروع می‌شود
    env.db.commit()
    second = _queue(env, body="پیام تازه پس از بازیابی")
    assert second.id == first_id and second.provider_ref != first_ref
    outbox_service.publish_due(env.db)
    assert _row(env, second.id).status == "sent" and env.provider.sends == 2


def test_no_message_text_code_or_key_reaches_the_logs(env, caplog):
    caplog.set_level(logging.DEBUG)
    _unconfirmed(env, body=f"کد بازیابی: {SECRET_CODE}", sensitive=True)
    env.provider.reply_receptor = "09350000000"
    _queue(env, body=f"رمز موقت: {SECRET_CODE}x", sensitive=True)
    outbox_service.publish_due(env.db)
    assert SECRET_CODE not in caplog.text and "SECRETKEY" not in caplog.text and "رمز موقت" not in caplog.text


def test_transport_errors_are_classified(monkeypatch):
    monkeypatch.setenv("SMS_PROVIDER", "kavenegar")
    monkeypatch.setenv("SMS_API_KEY", "SECRETKEY")

    def raising(error):
        def urlopen(*_a, **_k):
            raise error
        return urlopen
    monkeypatch.setattr(messaging.urllib.request, "urlopen", raising(TimeoutError()))
    with pytest.raises(messaging.AmbiguousSend):
        messaging.deliver_sms("09121112233", BODY, local_id=5)
    monkeypatch.setattr(messaging.urllib.request, "urlopen", raising(urllib.error.URLError(ConnectionRefusedError())))
    with pytest.raises(ConnectionError):
        messaging.deliver_sms("09121112233", BODY, local_id=5)
    monkeypatch.setattr(messaging.urllib.request, "urlopen", raising(urllib.error.HTTPError("u", 426, "Upgrade", {}, None)))
    assert messaging.sms_status_by_localid(5) is None
    with pytest.raises(RuntimeError) as error:
        messaging.deliver_sms("09121112233", BODY, local_id=5)
    assert "SECRETKEY" not in str(error.value)
