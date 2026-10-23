"""
لایه سرویس درخواست‌های ثبت سازمان (Onboarding)

جریان کار:
  ۱. کسب‌وکار از لندینگ پیج (بدون لاگین) درخواست می‌دهد و کد پیگیری می‌گیرد.
  ۲. ادمین پلتفرم درخواست را بررسی می‌کند:
     - تأیید: سازمان با همه اطلاعات پروفایل درخواست + اولین ادمین سازمان ساخته می‌شود.
     - رد: با ذکر دلیل؛ متقاضی دلیل را با کد پیگیری می‌بیند.
"""
import secrets
import string
from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.security import bcrypt_context
from app.core.tenancy import SKIP_TENANT_FILTER
from app.models import Organization, OrganizationRequest, PROFILE_FIELDS, RoleEnum, User, Warehouse
from app.schemas.organization import (
    OrganizationRequestApprove, OrganizationRequestCreate, OrganizationRequestReject,
)
from app.services import messaging, organization_service
from app.services.exceptions import ConflictError, NotFoundError

_CODE_ALPHABET = string.ascii_uppercase + string.digits


def _new_tracking_code(db: Session) -> str:
    while True:
        code = "REQ-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
        if not db.query(OrganizationRequest).filter(OrganizationRequest.tracking_code == code).first():
            return code


def fake_tracking_code() -> str:
    """برای ربات‌هایی که فیلد تله را پر کرده‌اند — پاسخ عادی می‌گیرند ولی چیزی ذخیره نمی‌شود."""
    return "REQ-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))


def submit_request(db: Session, data: OrganizationRequestCreate, requester_ip: str | None) -> OrganizationRequest:
    duplicate = db.query(OrganizationRequest).filter(
        OrganizationRequest.national_id == data.national_id,
        OrganizationRequest.status == "pending",
    ).first()
    if duplicate:
        raise ConflictError(
            f"برای این شناسه ملی از قبل یک درخواست در حال بررسی وجود دارد (کد پیگیری: {duplicate.tracking_code})."
        )
    if db.query(Organization).filter(Organization.national_id == data.national_id).first():
        raise ConflictError("سازمانی با این شناسه ملی قبلاً در پسینه ثبت شده است.")

    request = OrganizationRequest(
        tracking_code=_new_tracking_code(db),
        status="pending",
        requester_ip=requester_ip,
        **data.model_dump(exclude={"company_fax"}),
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    messaging.organization_request_received(request)
    return request


def get_public_status(db: Session, tracking_code: str) -> OrganizationRequest:
    request = db.query(OrganizationRequest).filter(
        OrganizationRequest.tracking_code == tracking_code.strip().upper()
    ).first()
    if request is None:
        raise NotFoundError("درخواستی با این کد پیگیری یافت نشد.")
    return request


def list_requests(db: Session, status: str | None = None) -> list[OrganizationRequest]:
    query = db.query(OrganizationRequest)
    if status:
        query = query.filter(OrganizationRequest.status == status)
    return query.order_by(OrganizationRequest.created_at.desc(), OrganizationRequest.id.desc()).all()


def get_request(db: Session, request_id: int) -> OrganizationRequest:
    request = db.get(OrganizationRequest, request_id)
    if request is None:
        raise NotFoundError("درخواست مورد نظر یافت نشد.")
    return request


def _pending_request(db: Session, request_id: int) -> OrganizationRequest:
    request = get_request(db, request_id)
    if request.status != "pending":
        raise ConflictError("این درخواست قبلاً بررسی شده است.")
    return request


def _default_username(slug: str) -> str:
    return f"{slug.replace('-', '_')[:14]}_admin"


def approve_request(db: Session, reviewer: User, request_id: int, data: OrganizationRequestApprove) -> dict:
    request = _pending_request(db, request_id)

    if db.query(Organization).filter(Organization.slug == data.slug).first():
        raise ConflictError("سازمانی با این شناسه (slug) قبلاً ثبت شده است.")

    username = data.admin_username or _default_username(data.slug)
    email = str(data.admin_email or request.contact_email)
    existing_user = db.query(User).filter(or_(User.username == username, User.email == email)) \
        .execution_options(**SKIP_TENANT_FILTER).first()
    if existing_user:
        raise ConflictError("کاربری با این نام کاربری یا ایمیل قبلاً ثبت شده است؛ نام کاربری یا ایمیل دیگری وارد کنید.")

    temporary_password = None
    password = data.admin_password
    if password is None:
        temporary_password = password = secrets.token_urlsafe(9)

    try:
        org = Organization(
            name=request.name, slug=data.slug, is_active=True,
            **{field: getattr(request, field) for field in PROFILE_FIELDS},
        )
        db.add(org)
        db.flush()

        # انبار پیش‌فرض در شهر سازمان — مبدأ مسیر سفارش‌ها روی نقشه؛ بعداً قابل ویرایش است
        db.add(Warehouse(organization_id=org.id, code="WH-01", name=f"انبار مرکزی {request.city}", location=request.address,
                         province=request.province, city=request.city))

        db.add(User(
            organization_id=org.id,
            username=username,
            email=email,
            full_name=request.contact_name,
            mobile=request.contact_mobile,
            role=RoleEnum.ORG_ADMIN,
            hashed_password=bcrypt_context.hash(password),
        ))

        request.status = "approved"
        request.reviewed_at = datetime.now(timezone.utc)
        request.reviewed_by_id = reviewer.id
        request.organization_id = org.id
        db.commit()
        db.refresh(org)
    except Exception:
        db.rollback()
        raise

    messaging.organization_request_approved(request, username, temporary_password)
    return {
        "organization": organization_service.get_organization(db, org.id),
        "admin_username": username,
        "temporary_password": temporary_password,
    }


def reject_request(db: Session, reviewer: User, request_id: int, data: OrganizationRequestReject) -> OrganizationRequest:
    request = _pending_request(db, request_id)
    request.status = "rejected"
    request.rejection_reason = data.reason
    request.reviewed_at = datetime.now(timezone.utc)
    request.reviewed_by_id = reviewer.id
    db.commit()
    db.refresh(request)
    messaging.organization_request_rejected(request)
    return request
