"""
IP و مرورگرِ درخواست جاری برای گزارش فعالیت — بدون اینکه همه سرویس‌ها Request بگیرند.
یک ASGI middleware ساده مقدارها را در contextvar می‌گذارد (به threadpool اندپوینت‌های sync هم می‌رسد).
"""
from contextvars import ContextVar

client_ip: ContextVar[str | None] = ContextVar("client_ip", default=None)
user_agent: ContextVar[str | None] = ContextVar("user_agent", default=None)


class RequestContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        client = scope.get("client")
        headers = dict(scope.get("headers") or [])
        ua = headers.get(b"user-agent", b"").decode("latin-1")[:255] or None
        t1 = client_ip.set(client[0] if client else None)
        t2 = user_agent.set(ua)
        try:
            await self.app(scope, receive, send)
        finally:
            client_ip.reset(t1)
            user_agent.reset(t2)
