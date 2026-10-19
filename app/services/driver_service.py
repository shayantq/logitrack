"""
احراز هویت و ثبت‌نام رانندگان (مرحله ۶)

جریان کار:
۱. ادمین سازمان یک لینک/کد دعوت می‌سازد (DriverInvite).
۲. راننده با /join/<code> حساب می‌سازد ← نقش driver با وضعیت «incomplete».
۳. راننده مرحله‌به‌مرحله نوع وسیله، مشخصات هویتی، مدارک (کارت ملی، سلفی، ویدیو، ...)،
   مشخصات خودرو و محل سکونت را تکمیل و «ارسال» می‌کند ← «submitted».
۴. ادمین همان سازمان مدارک را می‌بیند و تأیید (← approved + ساخت خودرو) یا رد (با دلیل) می‌کند.

فقط رانندگان «approved» سفارش می‌گیرند (order_service و vehicle_service).
فایل مدارک فقط برای خود راننده و ادمین همان سازمان قابل دریافت است.
"""
import re
import secrets
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core import storage
from app.core.security import bcrypt_context
from app.core.tenancy import SKIP_TENANT_FILTER
from app.models import DriverDocument, DriverInvite, DriverProfile, Organization, User, Vehicle
from app.schemas.driver import (
    CAR_PLATE, DriverApplicationUpdate, DriverInviteCreate, DriverSignupRequest,
)
from app.services import notification_service
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_VIDEO_BYTES = 30 * 1024 * 1024
MAX_VIDEO_SECONDS = 15   # ویدیوی احراز هویت کوتاه است (۵ تا ۱۰ ثانیه کافی است)

REQUIRED_FIELDS = ("first_name", "last_name", "national_code", "birth_date", "mobile", "province", "city", "address",
                   "vehicle_type", "vehicle_model", "license_plate", "max_weight_kg")
BASE_DOCUMENTS = ("national_card", "selfie", "video", "driving_license", "vehicle_photo", "vehicle_card")
# سقف منطقی بار هر نوع وسیله (کیلوگرم)
WEIGHT_LIMITS = {"motorcycle": 150, "sedan": 500, "pickup": 1500, "van": 3500, "truck": 30000}
VEHICLE_LABELS = {"motorcycle": "موتورسیکلت", "sedan": "سواری", "pickup": "وانت", "van": "ون", "truck": "کامیون"}

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _require_org_admin(user: User) -> None:
    if user.role != "org_admin":
        raise ForbiddenError("فقط ادمین سازمان به این بخش دسترسی دارد.")


def _require_driver(user: User) -> None:
    if user.role != "driver":
        raise ForbiddenError("این بخش مخصوص رانندگان است.")


# ---------------------------------------------------------------------------
# لینک دعوت
# ---------------------------------------------------------------------------
def _is_usable(invite: DriverInvite) -> bool:
    return (invite.is_active
            and (invite.expires_at is None or invite.expires_at > _now())
            and (invite.max_uses is None or invite.uses < invite.max_uses))


def invite_dict(invite: DriverInvite) -> dict:
    data = {c: getattr(invite, c) for c in ("id", "code", "label", "created_at", "expires_at", "max_uses", "uses", "is_active")}
    data["is_usable"] = _is_usable(invite)
    return data


def create_invite(db: Session, user: User, data: DriverInviteCreate) -> dict:
    _require_org_admin(user)
    code = "".join(secrets.choice(_ALPHABET) for _ in range(8))
    while db.query(DriverInvite).filter(DriverInvite.code == code).execution_options(**SKIP_TENANT_FILTER).first():
        code = "".join(secrets.choice(_ALPHABET) for _ in range(8))
    invite = DriverInvite(
        code=code, label=data.label or None, created_by_id=user.id, max_uses=data.max_uses,
        expires_at=_now() + timedelta(days=data.expires_in_days) if data.expires_in_days else None,
    )
    db.add(invite)
    db.commit()
    return invite_dict(invite)


def list_invites(db: Session, user: User) -> list[dict]:
    _require_org_admin(user)
    return [invite_dict(i) for i in db.query(DriverInvite).order_by(DriverInvite.id.desc()).all()]


def set_invite_active(db: Session, user: User, invite_id: int, active: bool) -> dict:
    _require_org_admin(user)
    invite = db.get(DriverInvite, invite_id)
    if invite is None:
        raise NotFoundError("لینک دعوت یافت نشد.")
    invite.is_active = active
    db.commit()
    return invite_dict(invite)


def _usable_invite(db: Session, code: str) -> tuple[DriverInvite, Organization]:
    """دعوت معتبر + سازمانش (درخواست عمومی است و سازمان جاری ندارد)."""
    invite = db.query(DriverInvite).filter(DriverInvite.code == code.strip().upper()) \
        .execution_options(**SKIP_TENANT_FILTER).first()
    org = db.get(Organization, invite.organization_id) if invite else None
    if invite is None or org is None:
        raise NotFoundError("لینک دعوت معتبر نیست.")
    if not org.is_active or not _is_usable(invite):
        raise ConflictError("این لینک دعوت منقضی یا غیرفعال شده است؛ از سازمان لینک جدید بگیرید.")
    return invite, org


def invite_info(db: Session, code: str) -> dict:
    invite, org = _usable_invite(db, code)
    return {"code": invite.code, "organization_name": org.name}


def signup(db: Session, code: str, data: DriverSignupRequest) -> User:
    """ساخت حساب راننده با لینک دعوت (وضعیت «incomplete» — هنوز سفارش نمی‌گیرد)."""
    invite, org = _usable_invite(db, code)
    duplicate = db.query(User).filter(or_(
        User.username == data.username, *( [User.email == data.email] if data.email else [] ),
    )).execution_options(**SKIP_TENANT_FILTER).first()
    if duplicate:
        raise ConflictError("این نام کاربری یا ایمیل قبلاً ثبت شده است.")

    user = User(
        username=data.username, email=data.email, full_name=data.full_name, role="driver",
        organization_id=org.id, hashed_password=bcrypt_context.hash(data.password), driver_status="incomplete",
    )
    db.add(user)
    db.flush()
    user.driver_code = f"DRV-{user.id:04d}"
    names = data.full_name.split(" ", 1)
    db.add(DriverProfile(
        user_id=user.id, organization_id=org.id, invite_id=invite.id, mobile=data.mobile,
        first_name=names[0], last_name=names[1] if len(names) > 1 else None,
    ))
    invite.uses += 1
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# پرونده راننده
# ---------------------------------------------------------------------------
def _profile_of(db: Session, driver: User) -> DriverProfile:
    profile = db.query(DriverProfile).filter(DriverProfile.user_id == driver.id).first()
    if profile is None:
        # راننده‌ای که ادمین مستقیماً ساخته هنوز پرونده ندارد — یک پرونده خالی برایش ساخته می‌شود
        profile = DriverProfile(user_id=driver.id, organization_id=driver.organization_id)
        db.add(profile)
        db.flush()
    return profile


def required_documents(vehicle_type: str | None) -> list[str]:
    docs = list(BASE_DOCUMENTS)
    if vehicle_type != "motorcycle":
        docs.append("technical_inspection")   # معاینه فنی برای خودروها
    return docs


def _documents(db: Session, driver_id: int) -> list[DriverDocument]:
    return db.query(DriverDocument).filter(DriverDocument.user_id == driver_id).order_by(DriverDocument.id).all()


def _missing(profile: DriverProfile, documents: list[DriverDocument]) -> list[str]:
    missing = [f for f in REQUIRED_FIELDS if getattr(profile, f) in (None, "")]
    if profile.vehicle_type != "motorcycle" and profile.inspection_expiry is None:
        missing.append("inspection_expiry")
    have = {d.kind for d in documents}
    missing += [k for k in required_documents(profile.vehicle_type) if k not in have]
    return missing


def application_dict(db: Session, driver: User, profile: DriverProfile | None = None) -> dict:
    profile = profile or _profile_of(db, driver)
    documents = _documents(db, driver.id)
    data = {c: getattr(profile, c) for c in (
        "first_name", "last_name", "national_code", "birth_date", "mobile", "province", "city", "address",
        "postal_code", "vehicle_type", "vehicle_model", "vehicle_color", "license_plate", "max_weight_kg",
        "intercity", "inspection_expiry", "submitted_at", "reviewed_at", "rejection_reason", "vehicle_id",
    )}
    invite = db.get(DriverInvite, profile.invite_id) if profile.invite_id else None
    data.update(
        user_id=driver.id, username=driver.username, full_name=driver.full_name, driver_code=driver.driver_code,
        driver_status=driver.driver_status, created_at=driver.created_at, intercity=bool(profile.intercity),
        invite_label=(invite.label or invite.code) if invite else None,
        documents=documents, missing=_missing(profile, documents),
        required_documents=required_documents(profile.vehicle_type),
    )
    return data


def _ensure_editable(driver: User) -> None:
    if driver.driver_status not in ("incomplete", "rejected"):
        raise ConflictError("پرونده شما ارسال شده و تا پایان بررسی قابل ویرایش نیست."
                            if driver.driver_status == "submitted" else "پرونده شما تأیید شده است.")


def get_my_application(db: Session, user: User) -> dict:
    _require_driver(user)
    data = application_dict(db, user)
    db.commit()   # اگر پرونده تازه ساخته شد
    return data


def update_my_application(db: Session, user: User, data: DriverApplicationUpdate) -> dict:
    _require_driver(user)
    _ensure_editable(user)
    profile = _profile_of(db, user)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(profile, key, value)
    db.commit()
    return application_dict(db, user, profile)


def upload_document(db: Session, user: User, kind: str, data: bytes) -> dict:
    _require_driver(user)
    _ensure_editable(user)
    if not data:
        raise ConflictError("فایل خالی است.")
    limit = MAX_VIDEO_BYTES if kind == "video" else MAX_IMAGE_BYTES
    if len(data) > limit:
        raise ConflictError(f"حجم فایل نباید بیشتر از {limit // (1024 * 1024)} مگابایت باشد.")
    try:
        ext = storage.detect_video(data) if kind == "video" else storage.detect_image(data)
    except storage.InvalidFileError as e:
        raise ConflictError(str(e))
    if kind == "video":
        seconds = storage.video_duration(data, ext)
        if seconds is not None and seconds > MAX_VIDEO_SECONDS + 0.5:
            raise ConflictError(f"ویدیو باید حداکثر {MAX_VIDEO_SECONDS} ثانیه باشد (این ویدیو حدود {round(seconds)} ثانیه است).")

    # نام تصادفی: آدرس قابل حدس نیست و نسخه قبلی در کش مرورگر نمی‌ماند
    path = f"drivers/{user.organization_id}/{user.id}/{kind}-{secrets.token_hex(6)}.{ext}"
    storage.save(path, data)
    document = db.query(DriverDocument).filter(DriverDocument.user_id == user.id, DriverDocument.kind == kind).first()
    old_path = document.file_path if document else None
    if document is None:
        document = DriverDocument(user_id=user.id, kind=kind)
        db.add(document)
    document.file_path = path
    document.content_type = storage.MEDIA_TYPES[ext]
    document.size_bytes = len(data)
    document.uploaded_at = _now()
    db.commit()
    storage.delete(old_path)
    return application_dict(db, user)


def submit_my_application(db: Session, user: User) -> dict:
    _require_driver(user)
    _ensure_editable(user)
    profile = _profile_of(db, user)
    missing = _missing(profile, _documents(db, user.id))
    if missing:
        raise ConflictError("پرونده کامل نیست؛ همه مراحل و مدارک لازم را تکمیل کنید.")

    errors = []
    limit = WEIGHT_LIMITS.get(profile.vehicle_type)
    if limit and profile.max_weight_kg > limit:
        errors.append(f"سقف بار {VEHICLE_LABELS[profile.vehicle_type]} حداکثر {limit:,} کیلوگرم است.")
    is_car_plate = bool(re.match(CAR_PLATE, profile.license_plate))
    if (profile.vehicle_type == "motorcycle") == is_car_plate:
        errors.append("قالب پلاک با نوع وسیله مطابقت ندارد.")
    today = date.today()
    age = today.year - profile.birth_date.year - ((today.month, today.day) < (profile.birth_date.month, profile.birth_date.day))
    if not 18 <= age <= 75:
        errors.append("سن راننده باید بین ۱۸ تا ۷۵ سال باشد.")
    if profile.inspection_expiry and profile.inspection_expiry < today:
        errors.append("اعتبار معاینه فنی به پایان رسیده است.")
    if errors:
        raise ConflictError(" ".join(errors))

    user.driver_status = "submitted"
    user.full_name = f"{profile.first_name} {profile.last_name}"
    profile.submitted_at = _now()
    profile.rejection_reason = None
    notification_service.driver_application(db, user, profile)
    db.commit()
    return application_dict(db, user, profile)


# ---------------------------------------------------------------------------
# بررسی توسط ادمین سازمان
# ---------------------------------------------------------------------------
def _driver(db: Session, driver_id: int) -> User:
    driver = db.query(User).filter(User.id == driver_id, User.role == "driver").first()
    if driver is None:
        raise NotFoundError("راننده یافت نشد.")
    return driver


def list_applications(db: Session, user: User, status: str | None = None) -> list[dict]:
    _require_org_admin(user)
    query = db.query(User, DriverProfile).join(DriverProfile, DriverProfile.user_id == User.id).filter(User.role == "driver")
    if status:
        query = query.filter(User.driver_status == status)
    rows = query.order_by(DriverProfile.submitted_at.desc().nulls_last(), User.id.desc()).all()
    return [application_dict(db, driver, profile) for driver, profile in rows]


def get_application(db: Session, user: User, driver_id: int) -> dict:
    _require_org_admin(user)
    driver = _driver(db, driver_id)
    data = application_dict(db, driver)
    db.commit()
    return data


def approve(db: Session, user: User, driver_id: int) -> dict:
    """تأیید پرونده: راننده فعال می‌شود و خودرویش از روی پرونده در ناوگان ساخته می‌شود."""
    _require_org_admin(user)
    driver = _driver(db, driver_id)
    if driver.driver_status != "submitted":
        raise ConflictError("فقط پرونده‌های ارسال‌شده قابل تأیید هستند.")
    profile = _profile_of(db, driver)

    if profile.vehicle_id is None:
        if db.query(Vehicle).filter(Vehicle.license_plate == profile.license_plate).first():
            raise ConflictError("خودرویی با این پلاک در ناوگان سازمان وجود دارد؛ ابتدا آن را بررسی کنید.")
        vehicle = Vehicle(
            license_plate=profile.license_plate, type=profile.vehicle_type, model=profile.vehicle_model,
            capacity_kg=profile.max_weight_kg, status="available", driver_id=driver.id, city=profile.city,
        )
        db.add(vehicle)
        db.flush()
        profile.vehicle_id = vehicle.id

    driver.driver_status = "approved"
    driver.city = profile.city
    driver.full_name = f"{profile.first_name} {profile.last_name}"
    profile.reviewed_at = _now()
    profile.reviewed_by_id = user.id
    profile.rejection_reason = None
    notification_service.application_result(db, driver, True, None, user)
    db.commit()
    return application_dict(db, driver, profile)


def reject(db: Session, user: User, driver_id: int, reason: str) -> dict:
    _require_org_admin(user)
    driver = _driver(db, driver_id)
    if driver.driver_status != "submitted":
        raise ConflictError("فقط پرونده‌های ارسال‌شده قابل رد هستند.")
    profile = _profile_of(db, driver)
    driver.driver_status = "rejected"
    profile.rejection_reason = reason
    profile.reviewed_at = _now()
    profile.reviewed_by_id = user.id
    notification_service.application_result(db, driver, False, reason, user)
    db.commit()
    return application_dict(db, driver, profile)


def document_file(db: Session, viewer: User, driver_id: int, kind: str):
    """
    (مسیر، media type) فایل یک مدرک. فقط خود راننده یا ادمین «همان سازمان»
    (فیلتر سازمان روی کوئری، رکورد سازمان دیگر را اصلاً پیدا نمی‌کند).
    """
    if not (viewer.role == "org_admin" or (viewer.role == "driver" and viewer.id == driver_id)):
        raise ForbiddenError("مدارک رانندگان فقط برای ادمین سازمان قابل مشاهده است.")
    document = db.query(DriverDocument).filter(DriverDocument.user_id == driver_id, DriverDocument.kind == kind).first()
    path = storage.path_of(document.file_path) if document else None
    if path is None:
        raise NotFoundError("این مدرک بارگذاری نشده است.")
    return path, document.content_type


def pending_count(db: Session, user: User) -> int:
    _require_org_admin(user)
    return db.query(User).filter(User.role == "driver", User.driver_status == "submitted").count()


def is_assignable_driver(db: Session, driver_id: int | None) -> bool:
    """خودروی بدون راننده یا با راننده تأییدشده می‌تواند سفارش بگیرد."""
    if driver_id is None:
        return True
    driver = db.get(User, driver_id)
    return driver is not None and driver.driver_status == "approved" and driver.is_active is not False
