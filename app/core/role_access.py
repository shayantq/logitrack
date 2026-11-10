"""
فهرست مجاز مسیرها برای نقش‌های محدود (ت۱۸ و ت۲۰): مسیری که این‌جا نیست پیش از رسیدن به سرویس با ۴۰۳ رد می‌شود.
بررسی نقش در سرویس‌ها سر جایش می‌ماند؛ این لایه جلوی این را می‌گیرد که نقش تازه از مسیری بدون بررسی نقش داده بیشتری ببیند.
"""
import re

_COMMON = (
    r"GET /users/me", r"(GET|POST|PUT|PATCH|DELETE) /users/me/.+", r"(GET|POST) /auth/.+", r"(GET|POST|PUT|PATCH|DELETE) /notifications(/.*)?",
    r"GET /organization/(profile|logo)",
)
_OPERATOR = (
    r"GET /picking/lists(/\d+)?", r"POST /picking/lines/\d+/(pick|short|claim|release)",
    r"GET /putaway/tasks(/\d+)?", r"GET /putaway/tasks/\d+/suggestions", r"POST /putaway/tasks/\d+/(execute|problem|claim|release)",
    r"GET /inbound/receipts(/\d+)?", r"POST /inbound/receipts/\d+/receive",
)
_FLEET = (
    r"GET /orders(/page|/\d+)?", r"PUT /orders/\d+/(assign|status)", r"POST /orders/\d+/resolve-failure", r"GET /orders/\d+/attempts",
    r"GET /orders/\d+/attempts/\d+/photo", r"GET /orders/\d+/attempts/\d+/evidence(/\d+/file)?", r"(GET|POST) /orders/\d+/contacts", r"GET /orders/\d+/handovers",
    r"GET /orders/\d+/route", r"POST /orders/\d+/checkpoints", r"DELETE /orders/\d+/checkpoints/last", r"GET /map/orders", r"GET /geo/.+",
    r"POST /dispatch/suggest", r"GET /dispatch/orders/\d+/suggestions", r"GET /dispatch/schedules", r"PUT /dispatch/schedules/\d+",
    r"POST /dispatch/schedules/\d+/time-off", r"DELETE /dispatch/schedules/\d+/time-off/\d+",
    r"GET /vehicles(/\d+)?", r"POST /vehicles", r"PUT /vehicles/\d+/(status|driver)", r"POST /vehicles/\d+/out-of-service",
    r"GET /exceptions(/\d+)?", r"PATCH /exceptions/\d+", r"(GET|POST|PUT|PATCH|DELETE) /saved-views(/\d+)?", r"GET /planning/capacity",
)
_RULES = {"warehouse_operator": re.compile("|".join(_COMMON + _OPERATOR)), "fleet_manager": re.compile("|".join(_COMMON + _FLEET))}


def is_restricted(role: str) -> bool:
    return role in _RULES


def allows(role: str, method: str, path: str) -> bool:
    rule = _RULES.get(role)
    return rule is None or rule.fullmatch(f"{method} {path.rstrip('/') or '/'}") is not None
