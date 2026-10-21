"""
محدودیت ساده تعداد درخواست برای endpointهای عمومی (بدون لاگین) — مثل فرم
درخواست سازمان — تا از اسپم و ثبت انبوه جلوگیری شود.

حافظه‌ای و درون همان پروسس است (برای یک نمونه uvicorn کافی است). اگر
بعداً چند نمونه وب اجرا شد، باید به Redis منتقل شود.
"""
import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window_seconds:
                hits.popleft()
            if len(hits) >= self.max_requests:
                return False
            hits.append(now)
            return True

    def blocked(self, key: str) -> bool:
        """آیا سقف پر شده؟ بدون ثبت تلاش جدید (برای قفل‌هایی که فقط تلاش ناموفق را می‌شمارند)."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits.get(key)
            if not hits:
                return False
            while hits and now - hits[0] > self.window_seconds:
                hits.popleft()
            return len(hits) >= self.max_requests

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


# فرم عمومی درخواست سازمان: حداکثر ۵ درخواست در ساعت از هر IP
organization_request_limiter = RateLimiter(max_requests=5, window_seconds=3600)

# ثبت‌نام عمومی راننده با لینک دعوت: حداکثر ۱۰ حساب در ساعت از هر IP
driver_signup_limiter = RateLimiter(max_requests=10, window_seconds=3600)

# بازیابی رمز: درخواست کد و تأیید کد از هر IP
password_reset_request_limiter = RateLimiter(max_requests=10, window_seconds=3600)
password_reset_confirm_limiter = RateLimiter(max_requests=30, window_seconds=3600)
