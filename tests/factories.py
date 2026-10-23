"""سازنده‌های مشترک داده تست (ساختار جدید سفارش چندقلمی)."""
from datetime import datetime, timedelta, timezone

from app.models import Warehouse
from app.schemas.order import OrderRequest

CITY_PROVINCE = {
    "تهران": "تهران", "تبریز": "آذربایجان شرقی", "اصفهان": "اصفهان", "قم": "قم",
    "قزوین": "قزوین", "کرج": "البرز",
}


def default_warehouse(db, organization_id: int | None = None) -> Warehouse:
    """انبار عمومی پیش‌فرض سازمان جاری (هر ردیف موجودی باید انبار داشته باشد)."""
    query = db.query(Warehouse).filter(Warehouse.code == "WH-TEST")
    if organization_id is not None:
        query = query.filter(Warehouse.organization_id == organization_id)
    warehouse = query.first()
    if warehouse is None:
        warehouse = Warehouse(name="انبار مرکزی", location="تهران", province="تهران", city="تهران", code="WH-TEST")
        if organization_id is not None:
            warehouse.organization_id = organization_id
        db.add(warehouse)
        db.flush()
    return warehouse


def order_request(product_id: int | None = None, vehicle_id: int | None = None, city: str = "تهران",
                  quantity: int = 1, items: list[tuple[int, int]] | None = None, mobile: str = "09120000000",
                  **overrides) -> OrderRequest:
    """یک OrderRequest معتبر؛ items = [(product_id, quantity), ...] برای سفارش چندقلمی."""
    return OrderRequest(**order_payload(product_id, vehicle_id, city=city, quantity=quantity, items=items,
                                        mobile=mobile, **overrides))


def order_payload(product_id: int | None = None, vehicle_id: int | None = None, city: str = "تهران",
                  quantity: int = 1, items: list[tuple[int, int]] | None = None, mobile: str = "09120000000",
                  **overrides) -> dict:
    now = datetime.now(timezone.utc)
    payload = {
        "items": [{"product_id": pid, "quantity": qty} for pid, qty in (items or [(product_id, quantity)])],
        "customer": {"name": "مشتری تست", "mobile": mobile},
        "destination_province": CITY_PROVINCE.get(city, "تهران"),
        "destination_city": city,
        "destination_address": "خیابان آزمایش، پلاک ۱",
        "size": "m",
        "priority": False,
        "delivery_window_start": now.isoformat(),
        "delivery_window_end": (now + timedelta(days=1)).isoformat(),
    }
    if vehicle_id is not None:
        payload["vehicle_id"] = vehicle_id
    payload.update(overrides)
    return payload
