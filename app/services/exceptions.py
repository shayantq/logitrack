"""
خطاهای دامنه (Domain Errors)
این کلاس‌ها مستقل از FastAPI هستند — لایه سرویس (business logic) از این‌ها
استفاده می‌کند، نه از HTTPException. تبدیل به HTTPException فقط در لایه
روتر (API layer) اتفاق می‌افتد. این جداسازی باعث می‌شود بتوان لایه سرویس
را بدون نیاز به FastAPI یا HTTP، مستقیماً در تست‌های واحد (unit tests) صدا زد.
"""


class DomainError(Exception):
    """کلاس پایه برای همه خطاهای منطق تجاری."""
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class NotFoundError(DomainError):
    def __init__(self, message: str = "مورد درخواستی یافت نشد."):
        super().__init__(message, status_code=404)


class ForbiddenError(DomainError):
    def __init__(self, message: str = "شما مجوز انجام این عملیات را ندارید."):
        super().__init__(message, status_code=403)


class GoneError(DomainError):
    """منبعی که دیگر در دسترس نیست (مثلاً لینک یک‌بارمصرفِ استفاده‌شده یا منقضی)."""
    def __init__(self, message: str = "این لینک منقضی شده است."):
        super().__init__(message, status_code=410)


class ConflictError(DomainError):
    """برای خطاهایی مثل موجودی ناکافی، ظرفیت ناکافی، تکراری بودن مقدار و ..."""
    def __init__(self, message: str = "امکان انجام این عملیات وجود ندارد."):
        super().__init__(message, status_code=400)
