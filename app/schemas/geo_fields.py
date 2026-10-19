"""فیلدهای شهر: فقط شهرهای فهرست رسمی (app/core/geo.py) پذیرفته و به نام رسمی تبدیل می‌شوند."""
from typing import Annotated, Optional

from pydantic import AfterValidator

from app.core import geo


def _any_province(value: Optional[str]) -> Optional[str]:
    return geo.canonical_city(value, None) if value else value


# شهر بدون استان مشخص (مثلاً شهر فعالیت راننده یا خودرو)
KnownCity = Annotated[str, AfterValidator(_any_province)]


def city_in_province(model, city_attr: str, province_attr: str) -> None:
    """برای model_validator: اگر شهر و استان هر دو داده شده‌اند، شهر باید در همان استان باشد."""
    city, province = getattr(model, city_attr, None), getattr(model, province_attr, None)
    if city:
        setattr(model, city_attr, geo.canonical_city(city, province or None))
