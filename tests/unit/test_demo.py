"""نسخه نمایشی خصوصی: لینک مخفی، مسیر مجاز و محدودیت‌های سمت سرور (app/core/demo.py)."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from jose import jwt
from starlette.requests import Request

from app.core import demo
from app.core.security import ALGORITHM, SECRET_KEY

TOKEN = "x" * 32


@pytest.fixture
def demo_on(monkeypatch):
    monkeypatch.setenv("DEMO_ACCESS_TOKEN", TOKEN)
    monkeypatch.setenv("DEMO_DATABASE_URL", "postgresql://u:p@db:5432/pasineh_demo")


def _request(token: str | None, method: str = "GET", path: str = "/orders/") -> Request:
    headers = [(b"authorization", f"Bearer {token}".encode())] if token else []
    return Request({"type": "http", "method": method, "path": path, "headers": headers, "query_string": b""})


def _jwt(**claims) -> str:
    return jwt.encode({"sub": "arya_admin", "exp": datetime.now(timezone.utc) + timedelta(hours=1), **claims}, SECRET_KEY, algorithm=ALGORITHM)


def test_disabled_without_token(monkeypatch):
    monkeypatch.delenv("DEMO_ACCESS_TOKEN", raising=False)
    assert not demo.enabled()
    assert not demo.token_matches("")
    assert not demo.is_demo_request(_request(_jwt(demo=True)))


def test_short_token_does_not_enable(monkeypatch):
    monkeypatch.setenv("DEMO_ACCESS_TOKEN", "short")
    monkeypatch.setenv("DEMO_DATABASE_URL", "postgresql://u:p@db/pasineh_demo")
    assert not demo.enabled()


def test_token_and_demo_claim(demo_on):
    assert demo.token_matches(TOKEN)
    assert not demo.token_matches(TOKEN + "y")
    assert demo.is_demo_request(_request(_jwt(demo=True)))
    assert not demo.is_demo_request(_request(_jwt()))
    assert not demo.is_demo_request(_request(None))
    forged = jwt.encode({"sub": "arya_admin", "demo": True}, "another-key", algorithm=ALGORITHM)
    assert not demo.is_demo_request(_request(forged))


@pytest.mark.parametrize("method,path", [
    ("GET", "/orders/"), ("GET", "/reports/stats"), ("GET", "/users/me"), ("GET", "/users/"), ("GET", "/map/orders"),
    ("POST", "/orders/"), ("PUT", "/orders/12/status"), ("POST", "/inbound/receipts/3/receive"), ("POST", "/picking/lines/9/pick"),
    ("POST", "/stocktakes/4/approve"), ("POST", "/drivers/applications/7/approve"), ("POST", "/driver-requests/2/reject"),
    ("POST", "/tickets/5/messages"), ("PUT", "/notifications/read-all"), ("DELETE", "/notifications/"),
])
def test_core_actions_allowed(method, path):
    demo.guard(method, path)


@pytest.mark.parametrize("method,path", [
    ("GET", "/reports/finance"), ("POST", "/reports/generate"), ("GET", "/catalog/export"), ("POST", "/catalog/import"),
    ("POST", "/labels/print"), ("GET", "/valuation/"), ("GET", "/users/activity-log"), ("GET", "/users/5"),
    ("PUT", "/permissions/warehouse_manager/audit.view"), ("POST", "/users/3/reset-password"), ("PUT", "/users/me/password"),
    ("PUT", "/organization/profile"), ("POST", "/inventory/products"), ("DELETE", "/orders/4"), ("POST", "/warehouses/"),
    ("POST", "/readiness/import/locations"), ("GET", "/inventory/movements"), ("GET", "/shipping/orders/3/packing-slip"),
    ("POST", "/inventory/documents/2/reverse"), ("GET", "/platform/organizations"),
])
def test_everything_else_blocked(method, path):
    with pytest.raises(HTTPException) as e:
        demo.guard(method, path)
    assert e.value.status_code == 403
