"""
IP، مرورگر و شناسه پیگیری درخواست جاری — برای گزارش فعالیت و پیام‌های خطا، بدون اینکه همه سرویس‌ها Request بگیرند.
یک ASGI middleware ساده مقدارها را در contextvar می‌گذارد (به threadpool اندپوینت‌های sync هم می‌رسد) و شناسه پیگیری
را در هدر X-Request-ID پاسخ برمی‌گرداند (اگر کلاینت خودش شناسه معتبری فرستاده باشد، همان استفاده می‌شود).
"""
import re
import secrets
from contextvars import ContextVar

client_ip: ContextVar[str | None] = ContextVar("client_ip", default=None)
user_agent: ContextVar[str | None] = ContextVar("user_agent", default=None)
request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

_VALID_ID = re.compile(rb"^[A-Za-z0-9._:-]{8,64}$")


class RequestContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        client = scope.get("client")
        headers = dict(scope.get("headers") or [])
        ua = headers.get(b"user-agent", b"").decode("latin-1")[:255] or None
        incoming = headers.get(b"x-request-id", b"")
        rid = incoming.decode("latin-1") if _VALID_ID.match(incoming) else secrets.token_hex(6)
        t1 = client_ip.set(client[0] if client else None)
        t2 = user_agent.set(ua)
        t3 = request_id.set(rid)

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"] = list(message["headers"]) + [(b"x-request-id", rid.encode("latin-1"))]
            await send(message)
        try:
            await self.app(scope, receive, send_with_id)
        finally:
            client_ip.reset(t1)
            user_agent.reset(t2)
            request_id.reset(t3)
