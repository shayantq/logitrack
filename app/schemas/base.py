from datetime import datetime, timezone

from pydantic import BaseModel, field_serializer


class BaseModelWithDateFormatting(BaseModel):
    """تاریخ‌ها در خروجی JSON به فرمت استاندارد ISO 8601 (UTC) برگردانده می‌شوند تا کلاینت‌ها بتوانند آن‌ها را پارس کنند."""

    @field_serializer("*", when_used="json")
    def serialize_datetime(self, value, _info):
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.isoformat()
        return value
