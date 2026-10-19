"""اسکیماهای مرحله ۸: قوانین سطح و پورسانت، امتیاز راننده، پروفایل کامل و برترین رانندگان."""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, StringConstraints, model_validator
from typing_extensions import Annotated

from app.schemas.organization import Text

LevelCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8)]


class LevelRule(BaseModel):
    code: LevelCode = Field(examples=["C"])
    name: Text(2, 40) = Field(examples=["نقره‌ای"])
    min_deliveries: int = Field(ge=0, le=1_000_000)
    min_days: int = Field(ge=0, le=36500)
    min_rating: Optional[float] = Field(None, ge=1, le=5)
    commission_percent: float = Field(ge=0, le=100)


class TierRule(BaseModel):
    from_trip: int = Field(ge=1, le=1000, description="از چندمین تحویل روز")
    multiplier_percent: float = Field(ge=0, le=100, description="ضریب درصد سطح (۱۰۰ = کامل، ۰ = بدون پورسانت)")


class CommissionPlanIn(BaseModel):
    base_fare: float = Field(ge=0, le=10_000_000_000)
    fare_per_kg: float = Field(ge=0, le=100_000_000)
    levels: list[LevelRule] = Field(min_length=1, max_length=10)
    tiers: list[TierRule] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def check(self):
        first = self.levels[0]
        if first.min_deliveries or first.min_days or first.min_rating is not None:
            raise ValueError("سطح اول باید بدون شرط باشد (همه رانندگان از آن شروع می‌کنند).")
        if len({lv.code for lv in self.levels}) != len(self.levels):
            raise ValueError("کد سطح‌ها باید یکتا باشد.")
        for a, b in zip(self.levels, self.levels[1:]):
            if b.min_deliveries < a.min_deliveries or b.min_days < a.min_days:
                raise ValueError("شرط هر سطح نباید از سطح پایین‌تر کمتر باشد (سطح‌ها را از پایین به بالا مرتب کنید).")
        trips = [t.from_trip for t in self.tiers]
        if trips != sorted(set(trips)) or trips[0] != 1:
            raise ValueError("پله‌های روزانه باید از سفر ۱ شروع شوند و به ترتیب صعودی و بدون تکرار باشند.")
        return self


class CommissionPlanOut(CommissionPlanIn):
    updated_at: Optional[datetime] = None
    is_default: bool = False


# برچسب‌های آماده نظرسنجی: ستاره خوب ← فقط مثبت، ستاره بد ← فقط منفی، ۳ ستاره ← هر دو
GOOD_TAGS = ("به‌موقع رسید", "برخورد محترمانه", "بسته سالم بود", "هماهنگی خوب پیش از رسیدن")
BAD_TAGS = ("دیر رسید", "برخورد نامناسب", "بسته آسیب دیده بود", "بدون هماهنگی آمد")


def allowed_tags(score: int) -> tuple[str, ...]:
    return GOOD_TAGS if score >= 4 else BAD_TAGS if score <= 2 else GOOD_TAGS + BAD_TAGS


class RatingIn(BaseModel):
    score: int = Field(ge=1, le=5)
    comment: Optional[Text(0, 500)] = None
    tags: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def check_tags(self):
        wrong = [t for t in self.tags if t not in allowed_tags(self.score)]
        if wrong:
            raise ValueError("برچسب‌های انتخاب‌شده با تعداد ستاره هم‌خوانی ندارند.")
        self.tags = list(dict.fromkeys(self.tags))
        return self


class RatingOut(BaseModel):
    id: int
    source: str
    score: int
    comment: Optional[str] = None
    tags: list[str] = []
    created_at: Optional[datetime] = None
    order_id: Optional[int] = None
    tracking_code: Optional[str] = None


class OrderRatings(BaseModel):
    organization: Optional[RatingOut] = None
    customer: Optional[RatingOut] = None
    customer_link_token: Optional[str] = None


class PublicRatingInfo(BaseModel):
    tracking_code: str
    organization_name: str
    driver_name: Optional[str] = None
    delivered_at: Optional[datetime] = None
    rated: bool
    score: Optional[int] = None
    good_tags: list[str] = list(GOOD_TAGS)
    bad_tags: list[str] = list(BAD_TAGS)


class PeriodStats(BaseModel):
    deliveries: int
    failed: int
    success_rate: Optional[float] = None
    weight_kg: float
    fees: float
    commission: float
    earnings: float


class LevelProgress(BaseModel):
    level: LevelRule
    level_index: int
    levels_count: int
    next_level: Optional[LevelRule] = None
    needs: list[str]
    deliveries: int
    days: int
    rating: Optional[float] = None
    ratings_by_source: dict[str, Any]
    trips_today: int
    next_trip_percent: float
    next_tier: Optional[TierRule] = None


class PerformanceResponse(BaseModel):
    progress: LevelProgress
    all_time: PeriodStats
    month: PeriodStats
    today: PeriodStats
    recent_ratings: list[RatingOut]


class DriverOverview(PerformanceResponse):
    profile: dict[str, Any]
    vehicles: list[dict[str, Any]]
    recent_orders: list[dict[str, Any]]
    shifts: list[dict[str, Any]]


class LeaderboardRow(BaseModel):
    rank: int
    driver_id: int
    driver_name: str
    driver_code: Optional[str] = None
    city: Optional[str] = None
    level_code: str
    level_name: str
    deliveries: int
    failed: int
    success_rate: Optional[float] = None
    rating: Optional[float] = None
    ratings_count: int
    earnings: float
    commission: float
