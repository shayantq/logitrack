"""
مدرک تحویل تغییرناپذیر (POD-01): هر آپلود مستقل است، آپلودکننده و مشخصات فایل در سرور ثبت می‌شود، و سفارش یا کاربر دارای مدرک حذف واقعی نمی‌شود.
"""
import hashlib

import pytest

from app.core import storage
from app.models_productivity import DeliveryEvidence, DeliveryEvidenceEvent, DeliveryEvidenceNote
from app.services import platform_service
from tests.api.test_operations_reliability import PNG, _auth, _order, _status, env  # noqa: F401

SECOND_PNG = PNG + b"second"


@pytest.fixture()
def delivered(env, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr("app.core.storage.MEDIA_ROOT", tmp_path)
    order = _order(env)
    assert _status(env, order["id"], "picked_up").status_code == 200
    assert _status(env, order["id"], "in_transit").status_code == 200
    assert _status(env, order["id"], "delivered", recipient_name="نگهبان", recipient_role="guard").status_code == 200
    return order


def _upload(env, order, data=PNG, user=None, **form):  # noqa: F811
    form.setdefault("delivery_method", "handed_to_recipient")
    return env.client.post(f"/orders/{order['id']}/attempts/1/photo", headers=_auth(user or env.driver), data=form,
                           files={"file": ("a.png", data, "image/png")})


def _rows(env):  # noqa: F811
    env.db.expire_all()
    return env.db.query(DeliveryEvidence).order_by(DeliveryEvidence.id).all()


def test_second_upload_keeps_the_first_record_and_file(env, delivered):  # noqa: F811
    assert _upload(env, delivered).status_code == 200
    assert _upload(env, delivered, SECOND_PNG, delivery_method="left_at_door").status_code == 200
    first, second = _rows(env)
    assert first.storage_key != second.storage_key
    assert storage.path_of(first.storage_key).read_bytes() == PNG
    assert storage.path_of(second.storage_key).read_bytes() == SECOND_PNG


def test_server_records_uploader_method_and_file_details(env, delivered):  # noqa: F811
    assert _upload(env, delivered, delivery_method="left_at_door").status_code == 200
    row = _rows(env)[0]
    assert row.uploaded_by_id == env.driver.id and row.uploaded_at is not None and row.delivery_method == "left_at_door"
    assert row.sha256 == hashlib.sha256(PNG).hexdigest() and row.size_bytes == len(PNG) and row.media_type == "image/png"


def test_client_supplied_media_type_is_not_trusted(env, delivered):  # noqa: F811
    res = env.client.post(f"/orders/{delivered['id']}/attempts/1/photo", headers=_auth(env.driver), data={"delivery_method": "left_at_door"},
                          files={"file": ("a.png", b"not an image", "image/png")})
    assert res.status_code == 400 and _rows(env) == []


@pytest.mark.parametrize("form", [{"delivery_method": "unrecorded"}, {"delivery_method": "verified_identity"}])
def test_invalid_methods_are_rejected(env, delivered, form):  # noqa: F811
    assert _upload(env, delivered, **form).status_code == 422
    assert _rows(env) == []


def test_method_is_required_for_new_uploads(env, delivered):  # noqa: F811
    res = env.client.post(f"/orders/{delivered['id']}/attempts/1/photo", headers=_auth(env.driver), files={"file": ("a.png", PNG, "image/png")})
    assert res.status_code == 422 and _rows(env) == []


def test_other_needs_an_explanation_kept_outside_the_record(env, delivered):  # noqa: F811
    assert _upload(env, delivered, delivery_method="other").status_code == 400
    assert _upload(env, delivered, delivery_method="other", method_note="  ").status_code == 400
    assert _upload(env, delivered, delivery_method="left_at_door", method_note="متن اضافه").status_code == 400
    res = _upload(env, delivered, delivery_method="other", method_note="تحویل به واحد نگهبانی")
    assert res.status_code == 200
    assert not hasattr(DeliveryEvidence, "note")
    assert env.db.query(DeliveryEvidenceNote).one().note == "تحویل به واحد نگهبانی"
    assert res.json()["evidence"][0]["method_note"] == "تحویل به واحد نگهبانی"


def test_only_the_attempt_driver_or_admin_can_upload_and_view(env, delivered):  # noqa: F811
    url = f"/orders/{delivered['id']}/attempts/1/evidence"
    assert _upload(env, delivered, user=env.manager).status_code == 403
    assert _upload(env, delivered, user=env.rival).status_code == 404
    assert _upload(env, delivered).status_code == 200
    evidence_id = _rows(env)[0].id
    assert env.client.get(f"{url}/{evidence_id}/file", headers=_auth(env.rival)).status_code == 404
    assert env.client.get(url, headers=_auth(env.rival)).status_code == 404
    seen = env.client.get(f"{url}/{evidence_id}/file", headers=_auth(env.admin))
    assert seen.status_code == 200 and seen.content == PNG


def test_old_photo_path_serves_the_newest_file(env, delivered):  # noqa: F811
    _upload(env, delivered)
    _upload(env, delivered, SECOND_PNG)
    res = env.client.get(f"/orders/{delivered['id']}/attempts/1/photo", headers=_auth(env.admin))
    assert res.status_code == 200 and res.content == SECOND_PNG


def test_changed_file_is_refused(env, delivered):  # noqa: F811
    _upload(env, delivered)
    row = _rows(env)[0]
    storage.path_of(row.storage_key).write_bytes(SECOND_PNG)
    res = env.client.get(f"/orders/{delivered['id']}/attempts/1/evidence/{row.id}/file", headers=_auth(env.admin))
    assert res.status_code == 400 and "hash" in res.json()["detail"]


def test_order_with_evidence_cannot_be_deleted(env, delivered):  # noqa: F811
    _upload(env, delivered)
    res = env.client.delete(f"/orders/{delivered['id']}", headers=_auth(env.admin))
    assert res.status_code == 400 and "مدرک تحویل" in res.json()["detail"]
    assert len(_rows(env)) == 1


def test_order_without_evidence_keeps_its_delete_rule(env, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr("app.core.storage.MEDIA_ROOT", tmp_path)
    order = _order(env)
    assert env.client.delete(f"/orders/{order['id']}", headers=_auth(env.admin)).status_code in (200, 204)


def test_uploader_cannot_be_hard_deleted(env, delivered):  # noqa: F811
    _upload(env, delivered, user=env.admin)
    from app.models import RoleEnum, User
    other = User(username="adm_other", email="adm_other@x.io", role=RoleEnum.ORG_ADMIN, hashed_password="x")
    env.db.add(other)
    env.db.commit()
    res = env.client.delete(f"/users/{env.admin.id}", headers=_auth(other))
    assert res.status_code == 400 and "غیرفعال" in res.json()["detail"]
    assert len(_rows(env)) == 1


def test_organization_erasure_keeps_the_record_and_logs_redaction(env, delivered):  # noqa: F811
    _upload(env, delivered, delivery_method="other", method_note="نام شخصی گیرنده")
    row = _rows(env)[0]
    key, sha, method = row.storage_key, row.sha256, row.delivery_method
    file_path = storage.path_of(key)
    platform_service.erase_organization(env.db, row.organization_id)
    env.db.expire_all()
    kept = env.db.get(DeliveryEvidence, row.id)
    assert kept.storage_key == key and kept.sha256 == sha and kept.delivery_method == method
    assert env.db.query(DeliveryEvidenceNote).count() == 0 and not file_path.exists()
    assert {e.event_type for e in env.db.query(DeliveryEvidenceEvent).all()} == {"file_deleted", "note_redacted"}
