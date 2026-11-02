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
_RULES = {"warehouse_operator": re.compile("|".join(_COMMON + _OPERATOR))}


def is_restricted(role: str) -> bool:
    return role in _RULES


def allows(role: str, method: str, path: str) -> bool:
    rule = _RULES.get(role)
    return rule is None or rule.fullmatch(f"{method} {path.rstrip('/') or '/'}") is not None
