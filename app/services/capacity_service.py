"""
ظرفیت خودرو: یک تعریف برای پیشنهاد راننده، ساخت محموله و پیش‌نمایش آن (docs/productivity.md، B3).

سقف وزن = max_weight_kg و در نبود آن capacity_kg؛ سقف حجم = max_volume_m3 اگر ثبت شده باشد.
حجم سفارش از بسته‌ها می‌آید و پیش از بسته‌بندی از ابعاد کالا برآورد می‌شود؛ اگر ابعاد همه اقلام ثبت نشده باشد
حجم نامعلوم است و فقط وزن سنجیده می‌شود.
"""
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import OrderItem, Package, Product, Vehicle

EPSILON = 1e-9


def weight_limit(vehicle: Vehicle) -> float | None:
    return vehicle.max_weight_kg or vehicle.capacity_kg


def _pct(value: float, limit: float | None) -> float | None:
    return round(100 * value / limit, 1) if limit else None


@dataclass
class CapacityCheck:
    weight_kg: float
    volume_m3: float | None
    max_weight_kg: float | None
    max_volume_m3: float | None

    @property
    def weight_pct(self) -> float | None:
        return _pct(self.weight_kg, self.max_weight_kg)

    @property
    def volume_pct(self) -> float | None:
        return _pct(self.volume_m3 or 0, self.max_volume_m3) if self.volume_m3 is not None else None

    @property
    def weight_over(self) -> bool:
        return bool(self.max_weight_kg) and self.weight_kg > self.max_weight_kg + EPSILON

    @property
    def volume_over(self) -> bool:
        return bool(self.max_volume_m3) and self.volume_m3 is not None and self.volume_m3 > self.max_volume_m3 + EPSILON

    @property
    def ok(self) -> bool:
        return not self.weight_over and not self.volume_over


def check(vehicle: Vehicle, weight_kg: float, volume_m3: float | None = None, other_weight: float = 0,
          other_volume: float = 0) -> CapacityCheck:
    """بار تازه + بار دیگر همان خودرو در برابر سقف‌ها. volume_m3=None یعنی حجم نامعلوم است و سنجیده نمی‌شود."""
    return CapacityCheck(weight_kg + other_weight, None if volume_m3 is None else volume_m3 + other_volume,
                         weight_limit(vehicle), vehicle.max_volume_m3)


def items_volume(db: Session, quantities: dict[int, int]) -> float | None:
    """برآورد حجم از ابعاد کالا؛ None اگر ابعاد حتی یک قلم ثبت نشده باشد."""
    if not quantities:
        return None
    products = {p.id: p for p in db.query(Product).filter(Product.id.in_(list(quantities))).all()}
    total = 0.0
    for product_id, quantity in quantities.items():
        product = products.get(product_id)
        if product is None or not (product.length_cm and product.width_cm and product.height_cm):
            return None
        total += product.length_cm * product.width_cm * product.height_cm / 1_000_000 * quantity
    return total


def order_volumes(db: Session, order_ids) -> dict[int, float | None]:
    """حجم هر سفارش: جمع بسته‌ها اگر بسته‌بندی شده، وگرنه برآورد از ابعاد کالا."""
    order_ids = list(order_ids)
    if not order_ids:
        return {}
    result: dict[int, float | None] = {}
    for package in db.query(Package).filter(Package.order_id.in_(order_ids)).all():
        result[package.order_id] = (result.get(package.order_id) or 0) + package.volume_m3
    missing = [i for i in order_ids if i not in result]
    if missing:
        rows = db.query(OrderItem.order_id, OrderItem.quantity, Product.length_cm, Product.width_cm, Product.height_cm) \
            .outerjoin(Product, Product.id == OrderItem.product_id).filter(OrderItem.order_id.in_(missing)).all()
        for order_id, quantity, length, width, height in rows:
            if order_id in result and result[order_id] is None:
                continue
            if length and width and height:
                result[order_id] = (result.get(order_id) or 0) + length * width * height / 1_000_000 * quantity
            else:
                result[order_id] = None
    return {i: result.get(i) for i in order_ids}
