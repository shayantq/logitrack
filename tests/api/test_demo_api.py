"""نسخه نمایشی خصوصی: ورود فقط با لینک درست، پنهان در مستندات API، مسیریابی به دیتابیس دمو و محدودیت‌ها."""
import pytest
from fastapi import HTTPException
from jose import jwt
from starlette.requests import Request

from app.core import demo
from app.core.security import ALGORITHM, SECRET_KEY, bcrypt_context
from app.database import get_db
from app.models import Organization, RoleEnum, User

TOKEN = "demo-link-" + "z" * 30


@pytest.fixture()
def demo_env(api_env, monkeypatch):
    client, Session = api_env
    monkeypatch.setenv("DEMO_ACCESS_TOKEN", TOKEN)
    monkeypatch.setenv("DEMO_DATABASE_URL", "postgresql://u:p@db:5432/pasineh_demo")
    monkeypatch.setattr(demo, "session_factory", lambda: Session)
    db = Session()
    org = Organization(name="پخش سراسری آریا", slug="arya-demo")
    db.add(org)
    db.flush()
    db.add(User(username=demo.DEMO_USERNAME, role=RoleEnum.ORG_ADMIN, organization_id=org.id, hashed_password=bcrypt_context.hash("x")))
    db.commit()
    db.close()
    return client


def test_hidden_without_valid_link(demo_env, monkeypatch):
    assert demo_env.post("/demo/session", json={"token": "wrong"}).status_code == 404
    assert "/demo/session" not in demo_env.get("/openapi.json").json()["paths"]
    monkeypatch.delenv("DEMO_ACCESS_TOKEN")
    assert demo_env.post("/demo/session", json={"token": TOKEN}).status_code == 404


def test_link_opens_admin_session(demo_env):
    res = demo_env.post("/demo/session", json={"token": TOKEN})
    assert res.status_code == 200, res.text
    claims = jwt.decode(res.json()["access_token"], SECRET_KEY, algorithms=[ALGORITHM])
    assert claims["demo"] is True and claims["sub"] == demo.DEMO_USERNAME
    assert res.json()["reset_minutes"] == 30


def _request(token: str, method: str, path: str) -> Request:
    return Request({"type": "http", "method": method, "path": path, "query_string": b"",
                    "headers": [(b"authorization", f"Bearer {token}".encode())]})


def test_demo_requests_use_demo_database_and_guard(demo_env, monkeypatch):
    token = demo_env.post("/demo/session", json={"token": TOKEN}).json()["access_token"]
    gen = get_db(_request(token, "GET", "/orders/"))
    db = next(gen)
    assert db.info.get("demo") is True
    gen.close()
    with pytest.raises(HTTPException) as e:
        next(get_db(_request(token, "POST", "/catalog/import")))
    assert e.value.status_code == 403
    normal = jwt.encode({"sub": "someone"}, SECRET_KEY, algorithm=ALGORITHM)
    gen = get_db(_request(normal, "POST", "/catalog/import"))
    assert not next(gen).info.get("demo")
    gen.close()
