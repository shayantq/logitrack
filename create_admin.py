"""
ساخت حساب ادمین پلتفرم LogiTrack (کارکنان پلتفرم سازمان ندارند و از پنل
/platform سازمان‌ها را می‌سازند و مدیریت می‌کنند).

نحوه اجرا (داخل کانتینر داکر):
    docker compose exec web python create_admin.py <username> <password> [email]

بدون آرگومان، نام کاربری superadmin و یک رمز تصادفی ساخته و چاپ می‌شود.
"""
import secrets
import sys

from app.core.security import bcrypt_context
from app.core.tenancy import SKIP_TENANT_FILTER
from app.database import SessionLocal
from app.models import User, RoleEnum


def create_platform_admin(username: str, password: str, email: str | None = None) -> None:
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == username).execution_options(**SKIP_TENANT_FILTER).first()
        if existing:
            print(f"👤 کاربر «{username}» از قبل وجود دارد (نقش: {existing.role.value}).")
            return

        db.add(User(
            username=username,
            email=email or f"{username}@logitrack.local",
            full_name="ادمین پلتفرم",
            role=RoleEnum.PLATFORM_ADMIN,
            organization_id=None,
            hashed_password=bcrypt_context.hash(password),
        ))
        db.commit()
        print("✅ ادمین پلتفرم ساخته شد.")
        print(f"   نام کاربری: {username}")
        print(f"   رمز عبور:   {password}")
    except Exception as e:
        db.rollback()
        print(f"❌ خطا در ساخت ادمین پلتفرم: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    args = sys.argv[1:]
    username = args[0] if len(args) > 0 else "superadmin"
    password = args[1] if len(args) > 1 else secrets.token_urlsafe(12)
    email = args[2] if len(args) > 2 else None
    create_platform_admin(username, password, email)
