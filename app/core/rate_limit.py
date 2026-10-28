"""
محدودیت تعداد درخواست برای endpointهای عمومی و ورود — مثل فرم درخواست سازمان، ردیابی، بازیابی رمز —
تا از اسپم، حدس رمز و ثبت انبوه جلوگیری شود.

اگر REDIS_URL تنظیم باشد شمارش در Redis است و بین همه پروسس‌ها و نمونه‌های وب مشترک می‌ماند
(پنجره لغزان با یک اسکریپت Lua اتمی). بدون Redis یا اگر Redis لحظه‌ای در دسترس نباشد، شمارش
در حافظه همان پروسس انجام می‌شود تا درخواست‌ها هرگز به‌خاطر نبودِ Redis خطا ندهند.
"""
import logging
import os
import threading
import time
import uuid
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

# ۱ = مجاز (و در صورت record ثبت شد)، ۰ = سقف پر است
_SLIDING_WINDOW = """
local key, now, window, limit, record = KEYS[1], tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3]), ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
if redis.call('ZCARD', key) >= limit then return 0 end
if record == '1' then
  redis.call('ZADD', key, now, ARGV[5])
  redis.call('EXPIRE', key, math.ceil(window))
end
return 1
"""

_redis_client = None
_redis_checked = False
_redis_lock = threading.Lock()


def _redis():
    global _redis_client, _redis_checked
    if _redis_checked:
        return _redis_client
    with _redis_lock:
        if not _redis_checked:
            url = os.getenv("REDIS_URL", "").strip()
            if url:
                import redis
                _redis_client = redis.Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5)
            _redis_checked = True
    return _redis_client


class RateLimiter:
    def __init__(self, name: str, max_requests: int, window_seconds: int):
        self.name = name
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    # --- Redis ---------------------------------------------------------------
    def _shared(self, key: str, record: bool) -> bool | None:
        client = _redis()
        if client is None:
            return None
        try:
            ok = client.eval(_SLIDING_WINDOW, 1, f"rl:{self.name}:{key}", time.time(), self.window_seconds,
                             self.max_requests, "1" if record else "0", uuid.uuid4().hex)
            return bool(ok)
        except Exception:
            logger.warning("rate limiter %s: Redis unavailable, falling back to in-process counting", self.name)
            return None

    # --- حافظه همان پروسس -----------------------------------------------------
    def _local(self, key: str, record: bool) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window_seconds:
                hits.popleft()
            if len(hits) >= self.max_requests:
                return False
            if record:
                hits.append(now)
            return True

    def allow(self, key: str) -> bool:
        """اگر سقف پر نشده، این تلاش را ثبت می‌کند و True می‌دهد."""
        shared = self._shared(key, record=True)
        return self._local(key, record=True) if shared is None else shared

    def blocked(self, key: str) -> bool:
        """آیا سقف پر شده؟ بدون ثبت تلاش جدید (برای قفل‌هایی که فقط تلاش ناموفق را می‌شمارند)."""
        shared = self._shared(key, record=False)
        return (not self._local(key, record=False)) if shared is None else (not shared)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
        client = _redis()
        if client is not None:
            try:
                for k in client.scan_iter(match=f"rl:{self.name}:*"):
                    client.delete(k)
            except Exception:
                pass


# فرم عمومی درخواست سازمان: حداکثر ۵ درخواست در ساعت از هر IP
organization_request_limiter = RateLimiter("org-request", max_requests=5, window_seconds=3600)

# ثبت‌نام عمومی راننده با لینک دعوت: حداکثر ۱۰ حساب در ساعت از هر IP
driver_signup_limiter = RateLimiter("driver-signup", max_requests=10, window_seconds=3600)

# بازیابی رمز: درخواست کد و تأیید کد از هر IP
password_reset_request_limiter = RateLimiter("reset-request", max_requests=10, window_seconds=3600)
password_reset_confirm_limiter = RateLimiter("reset-confirm", max_requests=30, window_seconds=3600)

# ورود: بیش از ۳۰ تلاش ناموفق در ۱۵ دقیقه از یک IP (روی هر نام کاربری) ← ورود از آن IP موقتاً بسته
login_failure_limiter = RateLimiter("login-fail", max_requests=30, window_seconds=900)
