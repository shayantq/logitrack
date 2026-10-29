"""
رمز یک‌بارمصرف زمانی (TOTP، RFC 6238) برای ورود دومرحله‌ای — سازگار با Google Authenticator، Microsoft Authenticator و ...

کد ۶ رقمی هر ۳۰ ثانیه عوض می‌شود؛ یک گام قبل و بعد هم برای اختلاف ساعت گوشی پذیرفته است.
هر کد فقط یک بار پذیرفته می‌شود: شماره آخرین گام مصرف‌شده نگه داشته می‌شود و کد هم‌گام یا قدیمی‌تر رد می‌شود.
"""
import base64
import hashlib
import hmac
import io
import secrets
import struct
import time
import urllib.parse

STEP = 30
DIGITS = 6
WINDOW = 1
ISSUER = "Pasineh"


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** DIGITS).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((now if now is not None else time.time()) // STEP)


def code_at(secret: str, now: float | None = None) -> str:
    return _code(secret, current_step(now))


def verify(secret: str, code: str, last_step: int | None, now: float | None = None) -> int | None:
    """شماره گام کد درست را برمی‌گرداند (برای جلوگیری از استفاده دوباره) یا None."""
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != DIGITS or not secret:
        return None
    step = current_step(now)
    for candidate in range(step - WINDOW, step + WINDOW + 1):
        if last_step is not None and candidate <= last_step:
            continue
        if hmac.compare_digest(_code(secret, candidate), code):
            return candidate
    return None


def provisioning_uri(secret: str, account: str) -> str:
    label = urllib.parse.quote(f"{ISSUER}:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={ISSUER}&digits={DIGITS}&period={STEP}"


def qr_svg_data_uri(uri: str) -> str:
    """کد QR به‌صورت SVG درون‌خطی (بدون هیچ سرویس بیرونی که راز را ببیند)."""
    import qrcode
    import qrcode.image.svg

    image = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    out = io.BytesIO()
    image.save(out)
    return "data:image/svg+xml;base64," + base64.b64encode(out.getvalue()).decode()
