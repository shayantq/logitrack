"""
ذخیره‌سازی فایل‌های آپلودی (لوگو سازمان و مدارک احراز هویت رانندگان).

فایل‌ها در MEDIA_ROOT (داخل داکر: volume مشترک /code/media) نگه داشته
می‌شوند و هرگز مستقیماً به‌صورت عمومی سرو نمی‌شوند؛ هر فایل فقط از طریق
endpointی که دسترسی کاربر را بررسی می‌کند قابل دریافت است.
"""
import os
from pathlib import Path

MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", Path(__file__).resolve().parent.parent.parent / "media"))

# امضای ابتدای فایل (magic bytes) — به پسوند یا Content-Type ارسالی کاربر اعتماد نمی‌کنیم
_IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
)
MEDIA_TYPES = {
    "png": "image/png", "jpg": "image/jpeg", "webp": "image/webp",
    "mp4": "video/mp4", "mov": "video/quicktime", "webm": "video/webm",
}


class InvalidFileError(ValueError):
    pass


def detect_image(data: bytes) -> str:
    """پسوند واقعی تصویر را از محتوای فایل تشخیص می‌دهد (png/jpg/webp) یا خطا می‌دهد."""
    for signature, ext, _ in _IMAGE_SIGNATURES:
        if data.startswith(signature):
            return ext
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    raise InvalidFileError("فقط تصویر PNG، JPG یا WEBP قابل قبول است.")


def detect_video(data: bytes) -> str:
    """پسوند واقعی ویدیو را از محتوای فایل تشخیص می‌دهد (mp4/mov/webm) یا خطا می‌دهد."""
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "mov" if data[8:12] == b"qt  " else "mp4"
    if data.startswith(b"\x1a\x45\xdf\xa3"):   # Matroska/WebM (ضبط مرورگر)
        return "webm"
    raise InvalidFileError("فقط ویدیوی MP4، MOV یا WEBM قابل قبول است.")


def _mp4_duration(data: bytes) -> float | None:
    """مدت ویدیوی MP4/MOV از جعبه moov/mvhd (moov ممکن است آخر فایل باشد)."""
    def boxes(start: int, end: int):
        pos = start
        while pos + 8 <= end:
            size = int.from_bytes(data[pos:pos + 4], "big")
            kind = data[pos + 4:pos + 8]
            header = 8
            if size == 1 and pos + 16 <= end:
                size = int.from_bytes(data[pos + 8:pos + 16], "big")
                header = 16
            elif size == 0:
                size = end - pos
            if size < header:
                return
            yield kind, pos + header, min(pos + size, end)
            pos += size

    for kind, body, end in boxes(0, len(data)):
        if kind != b"moov":
            continue
        for inner, ibody, iend in boxes(body, end):
            if inner != b"mvhd" or iend - ibody < 20:
                continue
            if data[ibody] == 1:   # نسخه ۱: زمان‌ها ۸ بایتی
                timescale = int.from_bytes(data[ibody + 20:ibody + 24], "big")
                duration = int.from_bytes(data[ibody + 24:ibody + 32], "big")
            else:
                timescale = int.from_bytes(data[ibody + 12:ibody + 16], "big")
                duration = int.from_bytes(data[ibody + 16:ibody + 20], "big")
            return duration / timescale if timescale else None
    return None


def _ebml_vint(data: bytes, pos: int, keep_marker: bool = False):
    first = data[pos]
    length = 1
    while length <= 8 and not first & (0x80 >> (length - 1)):
        length += 1
    if length > 8 or pos + length > len(data):
        raise ValueError
    value = first if keep_marker else first & ((0x80 >> (length - 1)) - 1)
    for b in data[pos + 1:pos + length]:
        value = (value << 8) | b
    return value, length


def _webm_duration(data: bytes) -> float | None:
    """مدت WebM از Segment/Info/Duration؛ ضبط مرورگر (MediaRecorder) معمولاً آن را ندارد ← None."""
    import struct
    i = data.find(b"\x15\x49\xa9\x66")   # Info
    if i < 0:
        return None
    try:
        size, n = _ebml_vint(data, i + 4)
        pos, end = i + 4 + n, min(i + 4 + n + size, len(data))
        scale, duration = 1_000_000, None
        while pos < end:
            element, n1 = _ebml_vint(data, pos, keep_marker=True)
            length, n2 = _ebml_vint(data, pos + n1)
            payload = data[pos + n1 + n2:pos + n1 + n2 + length]
            if element == 0x2AD7B1:
                scale = int.from_bytes(payload, "big")
            elif element == 0x4489 and length in (4, 8):
                duration = struct.unpack(">f" if length == 4 else ">d", payload)[0]
            pos += n1 + n2 + length
        return duration * scale / 1e9 if duration else None
    except (ValueError, IndexError, struct.error):
        return None


def video_duration(data: bytes, ext: str) -> float | None:
    """مدت ویدیو به ثانیه، یا None اگر از روی فایل قابل تشخیص نبود."""
    try:
        return _mp4_duration(data) if ext in ("mp4", "mov") else _webm_duration(data)
    except (ValueError, IndexError):
        return None


def _resolve(relative_path: str) -> Path:
    root = MEDIA_ROOT.resolve()
    path = (root / relative_path).resolve()
    if root not in path.parents:
        raise InvalidFileError("مسیر فایل نامعتبر است.")
    return path


def save(relative_path: str, data: bytes) -> str:
    path = _resolve(relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)  # جایگزینی اتمی: فایل نیمه‌نوشته هرگز خوانده نمی‌شود
    return relative_path


def path_of(relative_path: str) -> Path | None:
    path = _resolve(relative_path)
    return path if path.is_file() else None


def delete(relative_path: str | None) -> None:
    if not relative_path:
        return
    path = _resolve(relative_path)
    if path.is_file():
        path.unlink()
