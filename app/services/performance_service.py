"""
عملکرد رانندگان (مرحله ۸): امتیازدهی سازمان/مشتری/پلتفرم، آمار و پورسانت،
پروفایل کامل راننده برای ادمین، عملکرد من برای راننده و فهرست برترین رانندگان.
"""
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.core.tenancy import SKIP_TENANT_FILTER, set_tenant
from app.models import DriverRating, DriverShift, Order, Organization, User, Vehicle
from app.services import commission_service, driver_service, notification_service
from app.services.dispatch_service import local_to_utc, to_local
from app.services.exceptions import ConflictError, ForbiddenError, GoneError, NotFoundError

RATING_LINK_DAYS = 14   # مهلت ثبت نظر مشتری پس از تحویل

STAFF = ("org_admin", "warehouse_manager")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _require_staff(user: User) -> None:
    if user.role not in STAFF:
        raise ForbiddenError()


def _driver(db: Session, driver_id: int) -> User:
    driver = db.query(User).filter(User.id == driver_id, User.role == "driver").first()
    if driver is None:
        raise NotFoundError("راننده یافت نشد.")
    return driver


def _rating_dict(r: DriverRating, tracking: dict[int, str] | None = None) -> dict:
    return {"id": r.id, "source": r.source, "score": r.score, "comment": r.comment, "tags": r.tags or [], "created_at": r.created_at,
            "order_id": r.order_id, "tracking_code": (tracking or {}).get(r.order_id)}


def month_start_utc() -> datetime:
    local = to_local(_now())
    return local_to_utc(datetime.combine(local.date().replace(day=1), time.min))


def today_start_utc() -> datetime:
    return local_to_utc(datetime.combine(to_local(_now()).date(), time.min))


# ---------------------------------------------------------------------------
# آمار
# ---------------------------------------------------------------------------
def period_stats(db: Session, driver_ids: list[int], since: datetime | None = None) -> dict[int, dict]:
    """برای هر راننده: تحویل موفق/ناموفق، وزن، کرایه، پورسانت و سهم راننده (از سفارش‌های پایان‌یافته)."""
    delivered = Order.status == "delivered"
    q = db.query(
        Order.driver_id,
        func.sum(case((delivered, 1), else_=0)),
        func.sum(case((Order.status == "failed", 1), else_=0)),
        func.sum(case((delivered, Order.total_weight_kg), else_=0)),
        func.sum(case((delivered, Order.delivery_fee), else_=0)),
        func.sum(case((delivered, Order.commission_amount), else_=0)),
        func.sum(case((delivered, Order.driver_earning), else_=0)),
    ).filter(Order.driver_id.in_(driver_ids), Order.status.in_(("delivered", "failed")))
    if since is not None:
        q = q.filter(func.coalesce(Order.delivered_at, Order.updated_at) >= since)
    result = {}
    for driver_id, ok, failed, kg, fees, commission, earnings in q.group_by(Order.driver_id).all():
        ok, failed = int(ok or 0), int(failed or 0)
        result[driver_id] = {
            "deliveries": ok, "failed": failed, "success_rate": round(ok / (ok + failed) * 100, 1) if ok + failed else None,
            "weight_kg": round(float(kg or 0), 2), "fees": float(fees or 0), "commission": float(commission or 0),
            "earnings": float(earnings or 0),
        }
    return result


EMPTY_STATS = {"deliveries": 0, "failed": 0, "success_rate": None, "weight_kg": 0, "fees": 0, "commission": 0, "earnings": 0}


def _performance(db: Session, driver: User, ratings_limit: int = 10, hide_customer_comments: bool = False) -> dict:
    plan = commission_service.get_plan(db)
    ratings = db.query(DriverRating).filter(DriverRating.driver_id == driver.id).order_by(DriverRating.id.desc()).limit(ratings_limit).all()
    order_ids = [r.order_id for r in ratings if r.order_id]
    tracking = dict(db.query(Order.id, Order.tracking_code).filter(Order.id.in_(order_ids)).all()) if order_ids else {}
    recent = [_rating_dict(r, tracking) for r in ratings]
    if hide_customer_comments:
        for r in recent:   # راننده متن نظر مشتری را می‌بیند ولی نه شماره سفارش (حفظ حریم مشتری)
            r["tracking_code"] = None if r["source"] == "customer" else r["tracking_code"]
    return {
        "progress": commission_service.progress(db, driver, plan),
        "all_time": period_stats(db, [driver.id]).get(driver.id, EMPTY_STATS),
        "month": period_stats(db, [driver.id], month_start_utc()).get(driver.id, EMPTY_STATS),
        "today": period_stats(db, [driver.id], today_start_utc()).get(driver.id, EMPTY_STATS),
        "recent_ratings": recent,
    }


def my_performance(db: Session, user: User) -> dict:
    if user.role != "driver":
        raise ForbiddenError("این بخش مخصوص رانندگان است.")
    return _performance(db, user, hide_customer_comments=True)


def overview(db: Session, user: User, driver_id: int) -> dict:
    """پروفایل کامل راننده برای ادمین/مدیر انبار: مدارک، خودروها، آمار، امتیاز، پورسانت، سفارش‌ها و شیفت."""
    _require_staff(user)
    driver = _driver(db, driver_id)
    data = _performance(db, driver, ratings_limit=30)
    profile = driver_service.application_dict(db, driver)
    profile["email"] = driver.email
    # فیلد profile یک dict آزاد است؛ اشیای ORM مدارک باید پیش از خروجی به dict تبدیل شوند
    profile["documents"] = [{"kind": d.kind, "content_type": d.content_type, "size_bytes": d.size_bytes,
                             "uploaded_at": d.uploaded_at} for d in profile["documents"]]
    data["profile"] = profile
    data["vehicles"] = [{"id": v.id, "license_plate": v.license_plate, "type": v.type, "model": v.model,
                         "capacity_kg": v.capacity_kg, "status": v.status, "city": v.city}
                        for v in db.query(Vehicle).filter(Vehicle.driver_id == driver.id).order_by(Vehicle.id.desc()).all()]
    data["recent_orders"] = [{c: getattr(o, c) for c in (
        "id", "tracking_code", "status", "destination_city", "delivery_window_start", "delivered_at", "total_weight_kg",
        "delivery_fee", "commission_level", "day_trip_number", "commission_percent", "commission_amount", "driver_earning")}
        for o in db.query(Order).filter(Order.driver_id == driver.id).order_by(Order.id.desc()).limit(15).all()]
    data["shifts"] = [{"weekday": s.weekday, "start_time": s.start_time.strftime("%H:%M"), "end_time": s.end_time.strftime("%H:%M")}
                      for s in db.query(DriverShift).filter(DriverShift.user_id == driver.id).order_by(DriverShift.weekday).all()]
    db.commit()
    return data


def leaderboard(db: Session, user: User, period: str = "month", sort: str = "deliveries", limit: int = 50) -> list[dict]:
    _require_staff(user)
    drivers = db.query(User).filter(User.role == "driver", User.driver_status == "approved").all()
    if not drivers:
        return []
    ids = [d.id for d in drivers]
    stats = period_stats(db, ids, month_start_utc() if period == "month" else None)
    plan = commission_service.get_plan(db)
    rows = []
    for d in drivers:
        s = stats.get(d.id, EMPTY_STATS)
        rating, by_source = commission_service.weighted_rating(db, d.id)
        level = plan["levels"][commission_service.level_for(
            plan["levels"], commission_service.delivered_count(db, d.id), commission_service.tenure_days(d), rating)]
        rows.append({"driver_id": d.id, "driver_name": d.full_name or d.username, "driver_code": d.driver_code, "city": d.city,
                     "level_code": level["code"], "level_name": level["name"], **{k: s[k] for k in (
                         "deliveries", "failed", "success_rate", "earnings", "commission")},
                     "rating": rating, "ratings_count": sum(v["count"] for v in by_source.values())})
    keys = {
        "deliveries": lambda r: (r["deliveries"], r["rating"] or 0),
        "rating": lambda r: (r["rating"] or 0, r["ratings_count"], r["deliveries"]),
        "earnings": lambda r: (r["earnings"], r["deliveries"]),
        "success": lambda r: (r["success_rate"] or 0, r["deliveries"]),
    }
    rows.sort(key=keys.get(sort, keys["deliveries"]), reverse=True)
    for i, r in enumerate(rows[:limit], 1):
        r["rank"] = i
    return rows[:limit]


# ---------------------------------------------------------------------------
# امتیازدهی
# ---------------------------------------------------------------------------
def _order_driver(db: Session, order: Order) -> int:
    driver_id = commission_service.driver_of(db, order)
    if driver_id is None:
        raise ConflictError("این سفارش راننده‌ای نداشته است.")
    return driver_id


def order_ratings(db: Session, user: User, order_id: int) -> dict:
    _require_staff(user)
    order = db.get(Order, order_id)
    if order is None:
        raise NotFoundError("سفارش یافت نشد.")
    rows = {r.source: r for r in db.query(DriverRating).filter(DriverRating.order_id == order.id).all()}
    tracking = {order.id: order.tracking_code}
    return {
        "organization": _rating_dict(rows["organization"], tracking) if "organization" in rows else None,
        "customer": _rating_dict(rows["customer"], tracking) if "customer" in rows else None,
        "customer_link_token": order.rating_token if order.status == "delivered" else None,
    }


def rate_order(db: Session, user: User, order_id: int, score: int, comment: str | None, tags: list[str] | None = None) -> dict:
    """امتیاز سازمان به راننده برای یک سفارش پایان‌یافته (ثبت دوباره = ویرایش)."""
    _require_staff(user)
    order = db.get(Order, order_id)
    if order is None:
        raise NotFoundError("سفارش یافت نشد.")
    if order.status not in ("delivered", "failed"):
        raise ConflictError("فقط سفارش تحویل‌شده یا ناموفق قابل امتیازدهی است.")
    driver_id = _order_driver(db, order)
    rating = db.query(DriverRating).filter(DriverRating.order_id == order.id, DriverRating.source == "organization").first()
    if rating is None:
        rating = DriverRating(order_id=order.id, driver_id=driver_id, source="organization")
        db.add(rating)
    rating.score, rating.comment, rating.tags, rating.created_by_id = score, comment or None, tags or None, user.id
    notification_service.rating_event(db, order, driver_id, score, comment, "organization", user)
    db.commit()
    return order_ratings(db, user, order.id)


def _order_by_token(db: Session, token: str) -> Order:
    order = db.query(Order).filter(Order.rating_token == token).execution_options(**SKIP_TENANT_FILTER).first()
    if order is None or order.status != "delivered":
        raise NotFoundError("لینک نظرسنجی معتبر نیست.")
    return order


def _open_rating_order(db: Session, token: str) -> Order:
    """سفارشِ لینکِ هنوز معتبر؛ لینک پس از ثبت نظر یا پایان مهلت «منقضی» است (410)."""
    order = _order_by_token(db, token)
    set_tenant(db, order.organization_id)
    if db.query(DriverRating).filter(DriverRating.order_id == order.id, DriverRating.source == "customer").first():
        raise GoneError("نظر شما برای این سفارش قبلاً ثبت شده است و این لینک دیگر قابل استفاده نیست. سپاسگزاریم!")
    if order.delivered_at and order.delivered_at < _now() - timedelta(days=RATING_LINK_DAYS):
        raise GoneError(f"مهلت ثبت نظر برای این سفارش ({RATING_LINK_DAYS} روز پس از تحویل) تمام شده است.")
    return order


def _info(db: Session, order: Order, rated: bool = False, score: int | None = None) -> dict:
    org = db.get(Organization, order.organization_id)
    driver = db.get(User, order.driver_id) if order.driver_id else None
    first_name = (driver.full_name or "").split(" ")[0] if driver else None
    return {"tracking_code": order.tracking_code, "organization_name": org.name, "driver_name": first_name or None,
            "delivered_at": order.delivered_at, "rated": rated, "score": score}


def public_rating_info(db: Session, token: str) -> dict:
    return _info(db, _open_rating_order(db, token))


def submit_public_rating(db: Session, token: str, score: int, comment: str | None, tags: list[str] | None = None) -> dict:
    order = _open_rating_order(db, token)
    driver_id = _order_driver(db, order)
    db.add(DriverRating(organization_id=order.organization_id, order_id=order.id, driver_id=driver_id,
                        source="customer", score=score, comment=comment or None, tags=tags or None))
    notification_service.rating_event(db, order, driver_id, score, comment, "customer", None)
    db.commit()
    return _info(db, order, rated=True, score=score)


def platform_rate_driver(db: Session, user: User, organization_id: int, driver_id: int, score: int, comment: str | None) -> dict:
    """ارزیابی کیفی پلتفرم (مستقل از سفارش) — فقط کارکنان پلتفرم."""
    if user.role not in ("platform_admin", "platform_support"):
        raise ForbiddenError()
    driver = db.query(User).filter(User.id == driver_id, User.role == "driver", User.organization_id == organization_id).first()
    if driver is None:
        raise NotFoundError("راننده‌ای با این مشخصات در این سازمان یافت نشد.")
    rating = DriverRating(organization_id=organization_id, driver_id=driver.id, source="platform", score=score,
                          comment=comment or None, created_by_id=user.id)
    db.add(rating)
    db.commit()
    return _rating_dict(rating)


def platform_driver_ratings(db: Session, user: User, organization_id: int) -> list[dict]:
    """رانندگان یک سازمان با میانگین امتیاز (برای ارزیابی پلتفرم)."""
    if user.role not in ("platform_admin", "platform_support"):
        raise ForbiddenError()
    drivers = db.query(User).filter(User.role == "driver", User.organization_id == organization_id).order_by(User.id).all()
    out = []
    for d in drivers:
        rating, by_source = commission_service.weighted_rating(db, d.id)
        out.append({"driver_id": d.id, "driver_name": d.full_name or d.username, "driver_code": d.driver_code,
                    "driver_status": d.driver_status, "rating": rating, "by_source": by_source,
                    "deliveries": commission_service.delivered_count(db, d.id)})
    return out

