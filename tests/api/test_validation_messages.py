"""
پیام فارسی خطای اعتبارسنجی (۴۲۲): به‌جای متن انگلیسی Pydantic (مثل «String should match pattern ...») کاربر یک جمله
فارسی با نام فیلد می‌بیند. شکل پاسخ همان است (loc و type می‌مانند، field_label اضافه شده) و هیچ قاعده‌ای عوض نشده است.
"""
import importlib
import inspect
import pkgutil
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Literal
from uuid import UUID

import pytest
from fastapi.dependencies.utils import get_flat_params
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, ValidationError

import app as app_package
from app.core.security import create_access_token
from app.core.tenancy import set_tenant
from app.core.validation_messages import PATTERN_RULES, persian_message, translate
from app.main import app
from app.models import Organization, Partner, Product, RoleEnum, User
from app.schemas.product import LotNumber
from tests.factories import default_warehouse

ROOT = Path(__file__).resolve().parents[2]
PERSIAN = re.compile(r"[؀-ۿ]")
ENGLISH_PHRASE = re.compile(r"[A-Za-z]{2,}[ ,]+[A-Za-z]{2,}")


def _readable(msg: str) -> bool:
    """جمله فارسی است و هیچ عبارت انگلیسی چندکلمه‌ای (مثل متن Pydantic) ندارد."""
    return bool(PERSIAN.search(msg)) and not ENGLISH_PHRASE.search(msg)


class Status(str, Enum):
    available = "available"
    damaged = "damaged"


class Sample(BaseModel):
    """نام فیلدها نام واقعی فیلدهای برنامه است تا برچسب فارسی‌شان سنجیده شود."""
    model_config = ConfigDict(extra="forbid")
    username: Annotated[str, StringConstraints(min_length=3, max_length=20)] = "ali"
    quantity: int = Field(1, gt=0)
    weight_kg: float = Field(1, ge=0, le=1000)
    max_stock: int = Field(1, lt=100)
    price: Decimal = Decimal(1)
    is_active: bool = True
    lines: list[int] = Field([1], min_length=1, max_length=2)
    receipt_type: Literal["purchase", "return"] = "purchase"
    stock_status: Status = Status.available
    expiry_date: date = date(2026, 1, 1)
    starts_at: datetime = datetime(2026, 1, 1)
    plan_id: UUID = UUID(int=1)
    lot_number: LotNumber = "L-1"
    email: EmailStr = "a@x.io"
    name: str = "x"


CASES = [
    ("missing", {"username": ...}, "نام کاربری را وارد کنید."),
    ("string_type", {"name": 5}, "نام باید متن باشد."),
    ("int_parsing", {"quantity": "چند"}, "تعداد باید عدد صحیح باشد."),
    ("float_parsing", {"weight_kg": "سنگین"}, "وزن باید عدد باشد."),
    ("decimal_parsing", {"price": "گران"}, "قیمت باید عدد باشد."),
    ("bool_parsing", {"is_active": "شاید"}, "باید بله یا خیر باشد."),
    ("string_too_short", {"username": "ab"}, "نام کاربری باید دست‌کم ۳ نویسه باشد."),
    ("string_too_long", {"username": "a" * 21}, "نام کاربری حداکثر ۲۰ نویسه می‌تواند باشد."),
    ("string_pattern_mismatch", {"lot_number": "L 2026"},
     "شماره بچ فقط می‌تواند حرف انگلیسی، عدد و نشانه‌های . _ / - داشته باشد (بدون فاصله)."),
    ("greater_than", {"quantity": 0}, "تعداد باید بیشتر از صفر باشد."),
    ("greater_than_equal", {"weight_kg": -1}, "وزن نمی‌تواند منفی باشد."),
    ("less_than", {"max_stock": 100}, "حداکثر موجودی باید کمتر از ۱۰۰ باشد."),
    ("less_than_equal", {"weight_kg": 1001}, "وزن نباید بیشتر از ۱٬۰۰۰ باشد."),
    ("too_short", {"lines": []}, "دست‌کم یک مورد برای سطرها لازم است."),
    ("too_long", {"lines": [1, 2, 3]}, "سطرها حداکثر ۲ مورد می‌تواند داشته باشد."),
    ("literal_error", {"receipt_type": "gift"}, "از گزینه‌های مجاز نیست"),
    ("enum", {"stock_status": "lost"}, "از گزینه‌های مجاز نیست"),
    ("date_from_datetime_parsing", {"expiry_date": "فردا"}, "تاریخ انقضا باید تاریخ درست باشد."),
    ("datetime_from_date_parsing", {"starts_at": "صبح"}, "شروع باید تاریخ و ساعت درست باشد."),
    ("uuid_parsing", {"plan_id": "abc"}, "طرح شناسه معتبری نیست."),
    ("extra_forbidden", {"hacked": 1}, "در این درخواست پذیرفته نمی‌شود."),
    ("value_error", {"email": "not-an-email"}, "ایمیل معتبر نیست."),
]


@pytest.mark.parametrize("kind,data,expected", CASES, ids=[c[0] for c in CASES])
def test_each_error_type_becomes_one_persian_sentence(kind, data, expected):
    payload = {k: v for k, v in data.items() if v is not ...}
    if any(v is ... for v in data.values()):
        model = type("Required", (Sample,), {"__annotations__": {"username": str}})
        call = lambda: model(**payload)  # noqa: E731
    else:
        call = lambda: Sample(**payload)  # noqa: E731
    with pytest.raises(ValidationError) as caught:
        call()
    errors = [e for e in translate(caught.value.errors()) if e["type"] == kind]
    assert errors, [e["type"] for e in caught.value.errors()]
    error = errors[0]
    assert expected in error["msg"] and _readable(error["msg"]), error["msg"]
    assert "loc" in error and error["field_label"]


def test_unknown_type_and_unknown_field_still_get_persian_text():
    msg = persian_message({"type": "some_future_type", "loc": ("body", "brand_new_field"), "msg": "Input is weird"})
    assert msg == "این فیلد معتبر نیست."
    assert persian_message({"type": "missing", "loc": ("body",), "msg": "Field required"}).startswith("اطلاعات فرم کامل نیست")


def test_custom_persian_validator_text_is_kept():
    assert persian_message({"type": "value_error", "loc": ("body",), "msg": "Value error, پایان مرخصی باید بعد از شروع آن باشد."}) \
        == "پایان مرخصی باید بعد از شروع آن باشد."


def test_field_inside_a_list_row_uses_its_own_label():
    assert translate([{"type": "string_too_long", "loc": ("body", "lines", 2, "lot_number"), "msg": "x", "ctx": {"max_length": 64}}])[0]["msg"] \
        == "شماره بچ حداکثر ۶۴ نویسه می‌تواند باشد."


# ---------------------------------------------------------------------------
# فهرست همه الگوهای واقعی: هر الگو باید شرح فارسی داشته باشد
# ---------------------------------------------------------------------------
def _patterns_in(node, found: set):
    if isinstance(node, dict):
        pattern = node.get("pattern")
        if pattern is not None:
            found.add(pattern if isinstance(pattern, str) else pattern.pattern)
        for value in node.values():
            _patterns_in(value, found)
    elif isinstance(node, list):
        for value in node:
            _patterns_in(value, found)


def _api_routes(routes):
    # FastAPI روترهای include شده را تنبل نگه می‌دارد؛ مسیرهای اصلی هر روتر از original_router خوانده می‌شوند
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from _api_routes(route.original_router.routes)


def _body_params(dependant):
    yield from dependant.body_params
    for sub in dependant.dependencies:
        yield from _body_params(sub)


def _all_patterns() -> set:
    found: set = set()
    for module in pkgutil.walk_packages(app_package.__path__, "app."):
        mod = importlib.import_module(module.name)
        for _, cls in inspect.getmembers(mod, inspect.isclass):
            if issubclass(cls, BaseModel) and cls.__module__ == mod.__name__ and not getattr(cls, "__pydantic_generic_metadata__", {}).get("parameters"):
                _patterns_in(cls.__pydantic_core_schema__, found)
    for route in _api_routes(app.routes):
        for param in get_flat_params(route.dependant) + list(_body_params(route.dependant)):
            for meta in param.field_info.metadata:
                if getattr(meta, "pattern", None):
                    found.add(meta.pattern)
            _patterns_in(param._type_adapter.core_schema, found)
    return found


def test_every_real_pattern_has_a_persian_description():
    found = _all_patterns()
    # خود فهرست کار می‌کند: الگوی schema، پارامتر مسیر و هدر هر سه پیدا می‌شوند
    assert {r"^[0-9A-Za-z._/-]+$", r"^09\d{9}$", r"^[a-z0-9_-]{1,40}$", r"^[A-Za-z0-9._:-]{8,64}$"} <= found
    assert found - set(PATTERN_RULES) == set()


def test_frontend_format_hints_match_the_server_sentences():
    text = (ROOT / "frontend/src/lib/validation.ts").read_text(encoding="utf-8")
    hints = dict(re.findall(r'^\s*(\w+): "([^"]+)",$', text, re.M))
    fields = {"sku": ("sku", r"^\S+$"), "warehouseCode": ("code", r"^[A-Z0-9][A-Z0-9-]*$"),
              "locationCode": ("code", r"^[0-9A-Za-z._/-]+$"), "slug": ("slug", r"^[a-z0-9][a-z0-9-]*$"),
              "mobile": ("mobile", r"^09\d{9}$"), "nationalId": ("national_id", r"^\d{11}$"),
              "economicCode": ("economic_code", r"^\d{11,14}$"), "postalCode": ("postal_code", r"^\d{10}$")}
    assert set(hints) == set(fields)
    for key, (field, pattern) in fields.items():
        server = persian_message({"type": "string_pattern_mismatch", "loc": ("body", field), "ctx": {"pattern": pattern}})
        assert hints[key] == server, key


# ---------------------------------------------------------------------------
# مسیر واقعی API
# ---------------------------------------------------------------------------
def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.username, user.id, timedelta(minutes=5))}"}


@pytest.fixture()
def env(api_env):
    client, Session = api_env
    db = Session()
    org = Organization(name="آلفا", slug="alpha")
    db.add(org)
    db.commit()
    set_tenant(db, org.id)
    warehouse = default_warehouse(db, org.id)
    admin = User(username="adm", email="a@x.io", role=RoleEnum.ORG_ADMIN, hashed_password="x")
    lot = Product(name="دارو", sku="MED-1", barcode="62610001", price=1, weight_kg=1, lot_tracked=True)
    serial = Product(name="گوشی", sku="PHONE-1", barcode="62610003", price=1, weight_kg=1, serial_tracked=True)
    partner = Partner(code="SUP-1", name="تأمین", is_supplier=True)
    db.add_all([admin, lot, serial, partner])
    db.commit()
    res = client.post("/inbound/receipts", headers=_auth(admin), json={
        "receipt_type": "purchase", "warehouse_id": warehouse.id, "partner_id": partner.id, "external_ref": "BL-V",
        "lines": [{"product_id": p.id, "expected_quantity": 10} for p in (lot, serial)]})
    assert res.status_code == 201, res.text
    receipt = res.json()
    lines = {ln["product_sku"]: ln["id"] for ln in receipt["lines"]}
    yield SimpleNamespace(client=client, admin=admin, receipt=receipt, lines=lines)
    db.close()


def _receive(env, sku, **line):
    body = {"lines": [{"line_id": env.lines[sku], "quantity": 2, "entry_mode": "scan", "product_scan": sku, **line}]}
    return env.client.post(f"/inbound/receipts/{env.receipt['id']}/receive", headers=_auth(env.admin), json=body)


def _assert_validation(res) -> list[dict]:
    assert res.status_code == 422, res.text
    body = res.json()
    assert body["code"] == "validation" and "request_id" in body and isinstance(body["detail"], list)
    for item in body["detail"]:
        assert {"loc", "type", "msg", "field_label"} <= set(item) and _readable(item["msg"]), item
    return body["detail"]


def test_invalid_lot_number_in_receiving_is_readable(env):
    detail = _assert_validation(_receive(env, "MED-1", lot_number="L 2026/01"))
    assert detail[0]["type"] == "string_pattern_mismatch" and detail[0]["loc"][-1] == "lot_number"
    assert detail[0]["field_label"] == "شماره بچ"
    assert detail[0]["msg"] == "شماره بچ فقط می‌تواند حرف انگلیسی، عدد و نشانه‌های . _ / - داشته باشد (بدون فاصله)."


def test_duplicate_serials_keep_their_own_persian_message(env):
    detail = _assert_validation(_receive(env, "PHONE-1", serial_numbers=["SN-1", "SN-1"]))
    assert detail[0]["msg"] == "شماره سریال تکراری وارد شده است."


def test_query_param_and_broken_json_are_readable(env):
    detail = _assert_validation(env.client.get("/inbound/receipts", headers=_auth(env.admin), params={"warehouse_id": "abc"}))
    assert detail[0]["msg"] == "انبار باید عدد صحیح باشد."
    res = env.client.post(f"/inbound/receipts/{env.receipt['id']}/receive", headers={**_auth(env.admin), "Content-Type": "application/json"},
                          content=b"{not json")
    assert _assert_validation(res)[0]["msg"].startswith("اطلاعات ارسال‌شده خوانا نیست")
