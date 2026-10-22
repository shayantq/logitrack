"""
جغرافیای مسیرها (مرحله ۱۰).

- فهرست کامل شهرهای ایران (`app/data/iran_cities.json`، ۱۲۷۷ شهر با مختصات؛ منبع: Wikidata، CC0) برای
  انتخاب شهر در فرم‌ها و نمایش دقیق روی نقشه.
- گراف ساده‌شده جاده‌های اصلی بین ۹۵ شهر بزرگ (CITIES/ROADS). شهری که روی گراف نیست، با فاصله
  مستقیم × ضریب جاده به نزدیک‌ترین شهرهای گراف وصل می‌شود.
- فاصله‌ها تقریبی‌اند و فقط برای نمایش پیشرفت و تخمین زمان رسیدن به کار می‌روند، نه مسیریابی دقیق.
"""
from __future__ import annotations

import heapq
import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.iran import normalize_persian_text


@dataclass(frozen=True)
class City:
    name: str
    province: str
    lat: float
    lon: float
    capital: bool = False


_C = City
# ------------------------------------------------------------------ شهرها (مراکز استان با capital=True)
CITIES: tuple[City, ...] = (
    # مراکز استان
    _C("تبریز", "آذربایجان شرقی", 38.08, 46.29, True),
    _C("ارومیه", "آذربایجان غربی", 37.55, 45.07, True),
    _C("اردبیل", "اردبیل", 38.25, 48.30, True),
    _C("اصفهان", "اصفهان", 32.65, 51.67, True),
    _C("کرج", "البرز", 35.84, 50.94, True),
    _C("ایلام", "ایلام", 33.64, 46.42, True),
    _C("بوشهر", "بوشهر", 28.97, 50.84, True),
    _C("تهران", "تهران", 35.69, 51.39, True),
    _C("شهرکرد", "چهارمحال و بختیاری", 32.33, 50.86, True),
    _C("بیرجند", "خراسان جنوبی", 32.87, 59.22, True),
    _C("مشهد", "خراسان رضوی", 36.30, 59.60, True),
    _C("بجنورد", "خراسان شمالی", 37.47, 57.33, True),
    _C("اهواز", "خوزستان", 31.32, 48.67, True),
    _C("زنجان", "زنجان", 36.68, 48.48, True),
    _C("سمنان", "سمنان", 35.57, 53.39, True),
    _C("زاهدان", "سیستان و بلوچستان", 29.50, 60.86, True),
    _C("شیراز", "فارس", 29.59, 52.58, True),
    _C("قزوین", "قزوین", 36.27, 50.00, True),
    _C("قم", "قم", 34.64, 50.88, True),
    _C("سنندج", "کردستان", 35.31, 46.99, True),
    _C("کرمان", "کرمان", 30.28, 57.08, True),
    _C("کرمانشاه", "کرمانشاه", 34.31, 47.07, True),
    _C("یاسوج", "کهگیلویه و بویراحمد", 30.67, 51.59, True),
    _C("گرگان", "گلستان", 36.84, 54.44, True),
    _C("رشت", "گیلان", 37.28, 49.58, True),
    _C("خرم‌آباد", "لرستان", 33.49, 48.36, True),
    _C("ساری", "مازندران", 36.56, 53.06, True),
    _C("اراک", "مرکزی", 34.09, 49.69, True),
    _C("بندرعباس", "هرمزگان", 27.18, 56.27, True),
    _C("همدان", "همدان", 34.80, 48.52, True),
    _C("یزد", "یزد", 31.90, 54.37, True),
    # شهرهای میانی مسیرها
    _C("آبیک", "قزوین", 36.04, 50.53), _C("تاکستان", "قزوین", 36.07, 49.70),
    _C("میانه", "آذربایجان شرقی", 37.42, 47.72), _C("مرند", "آذربایجان شرقی", 38.43, 45.77),
    _C("مراغه", "آذربایجان شرقی", 37.39, 46.24), _C("خوی", "آذربایجان غربی", 38.55, 44.95),
    _C("مهاباد", "آذربایجان غربی", 36.76, 45.72), _C("آستارا", "گیلان", 38.43, 48.87),
    _C("بندر انزلی", "گیلان", 37.47, 49.46), _C("لاهیجان", "گیلان", 37.20, 50.00),
    _C("منجیل", "گیلان", 36.74, 49.40), _C("چالوس", "مازندران", 36.65, 51.42),
    _C("آمل", "مازندران", 36.47, 52.35), _C("بابل", "مازندران", 36.54, 52.68),
    _C("قائم‌شهر", "مازندران", 36.46, 52.86), _C("بهشهر", "مازندران", 36.69, 53.55),
    _C("فیروزکوه", "تهران", 35.76, 52.77), _C("دماوند", "تهران", 35.72, 52.07),
    _C("گرمسار", "سمنان", 35.22, 52.34), _C("دامغان", "سمنان", 36.17, 54.34),
    _C("شاهرود", "سمنان", 36.42, 54.98), _C("سبزوار", "خراسان رضوی", 36.21, 57.68),
    _C("نیشابور", "خراسان رضوی", 36.21, 58.80), _C("تربت حیدریه", "خراسان رضوی", 35.27, 59.22),
    _C("قوچان", "خراسان رضوی", 37.11, 58.51), _C("گناباد", "خراسان رضوی", 34.35, 58.68),
    _C("گنبد کاووس", "گلستان", 37.25, 55.17), _C("قائن", "خراسان جنوبی", 33.73, 59.18),
    _C("نهبندان", "خراسان جنوبی", 31.54, 60.04), _C("طبس", "خراسان جنوبی", 33.60, 56.92),
    _C("زابل", "سیستان و بلوچستان", 31.03, 61.49), _C("ایرانشهر", "سیستان و بلوچستان", 27.20, 60.69),
    _C("چابهار", "سیستان و بلوچستان", 25.29, 60.64), _C("بم", "کرمان", 29.11, 58.36),
    _C("رفسنجان", "کرمان", 30.41, 55.99), _C("سیرجان", "کرمان", 29.45, 55.68),
    _C("جیرفت", "کرمان", 28.68, 57.74), _C("میناب", "هرمزگان", 27.15, 57.08),
    _C("کاشان", "اصفهان", 33.98, 51.44), _C("نائین", "اصفهان", 32.86, 53.09),
    _C("شهرضا", "اصفهان", 32.01, 51.87), _C("اردکان", "یزد", 32.31, 54.02),
    _C("ساوه", "مرکزی", 35.02, 50.36), _C("دلیجان", "مرکزی", 33.99, 50.68),
    _C("ملایر", "همدان", 34.30, 48.82), _C("بروجرد", "لرستان", 33.90, 48.75),
    _C("پلدختر", "لرستان", 33.15, 47.71), _C("اسلام‌آباد غرب", "کرمانشاه", 34.11, 46.53),
    _C("سقز", "کردستان", 36.25, 46.27), _C("بیجار", "کردستان", 35.87, 47.61),
    _C("دزفول", "خوزستان", 32.38, 48.40), _C("آبادان", "خوزستان", 30.34, 48.30),
    _C("بهبهان", "خوزستان", 30.60, 50.24), _C("دوگنبدان", "کهگیلویه و بویراحمد", 30.36, 50.80),
    _C("کازرون", "فارس", 29.62, 51.65), _C("مرودشت", "فارس", 29.87, 52.80),
    _C("آباده", "فارس", 31.16, 52.65), _C("جهرم", "فارس", 28.50, 53.56),
    _C("فسا", "فارس", 28.94, 53.65), _C("داراب", "فارس", 28.75, 54.54),
    _C("لار", "فارس", 27.68, 54.34), _C("برازجان", "بوشهر", 29.27, 51.22),
    _C("بندر کنگان", "بوشهر", 27.83, 52.06), _C("بروجن", "چهارمحال و بختیاری", 31.97, 51.30),
)

# ------------------------------------------------------------------ جاده‌های اصلی (کیلومتر تقریبی)
ROADS: tuple[tuple[str, str, int], ...] = (
    # شمال‌غرب
    ("تهران", "کرج", 45), ("کرج", "آبیک", 70), ("آبیک", "قزوین", 55), ("قزوین", "تاکستان", 35),
    ("تاکستان", "زنجان", 145), ("زنجان", "میانه", 155), ("میانه", "تبریز", 175), ("تبریز", "مرند", 70),
    ("مرند", "خوی", 80), ("خوی", "ارومیه", 145), ("تبریز", "ارومیه", 145), ("تبریز", "مراغه", 130),
    ("مراغه", "مهاباد", 130), ("ارومیه", "مهاباد", 120), ("مهاباد", "سقز", 115), ("سقز", "سنندج", 190),
    ("زنجان", "بیجار", 140), ("بیجار", "سنندج", 140), ("میانه", "اردبیل", 190), ("تبریز", "اردبیل", 210),
    ("اردبیل", "آستارا", 75),
    # گیلان و مازندران
    ("آستارا", "بندر انزلی", 135), ("بندر انزلی", "رشت", 40), ("رشت", "منجیل", 75), ("منجیل", "قزوین", 105),
    ("رشت", "لاهیجان", 45), ("لاهیجان", "چالوس", 170), ("چالوس", "کرج", 165), ("چالوس", "آمل", 110),
    ("تهران", "دماوند", 60), ("دماوند", "آمل", 120), ("آمل", "بابل", 25), ("بابل", "قائم‌شهر", 20),
    ("قائم‌شهر", "ساری", 25), ("ساری", "بهشهر", 50), ("بهشهر", "گرگان", 85), ("قائم‌شهر", "فیروزکوه", 120),
    ("دماوند", "فیروزکوه", 75),
    # شرق و شمال‌شرق
    ("فیروزکوه", "سمنان", 110), ("تهران", "گرمسار", 110), ("گرمسار", "سمنان", 115), ("سمنان", "دامغان", 110),
    ("دامغان", "شاهرود", 65), ("شاهرود", "سبزوار", 255), ("سبزوار", "نیشابور", 115), ("نیشابور", "مشهد", 125),
    ("شاهرود", "گرگان", 160), ("گرگان", "گنبد کاووس", 90), ("گنبد کاووس", "بجنورد", 240), ("بجنورد", "قوچان", 125),
    ("قوچان", "مشهد", 130), ("مشهد", "تربت حیدریه", 155), ("تربت حیدریه", "گناباد", 140), ("گناباد", "قائن", 105),
    ("قائن", "بیرجند", 100), ("بیرجند", "نهبندان", 160), ("نهبندان", "زاهدان", 190), ("زاهدان", "زابل", 205),
    ("زاهدان", "بم", 320), ("زاهدان", "ایرانشهر", 345), ("ایرانشهر", "چابهار", 310), ("یزد", "طبس", 320),
    ("طبس", "بیرجند", 360),
    # مرکز
    ("تهران", "قم", 145), ("قم", "کاشان", 105), ("کاشان", "اصفهان", 210), ("قم", "دلیجان", 110),
    ("دلیجان", "اصفهان", 200), ("دلیجان", "اراک", 100), ("قم", "اراک", 135), ("تهران", "ساوه", 135),
    ("ساوه", "همدان", 215), ("ساوه", "اراک", 130), ("قزوین", "همدان", 240), ("اراک", "ملایر", 125),
    ("ملایر", "همدان", 85), ("ملایر", "بروجرد", 75), ("بروجرد", "خرم‌آباد", 95), ("همدان", "کرمانشاه", 185),
    ("کرمانشاه", "سنندج", 135), ("همدان", "سنندج", 180), ("کرمانشاه", "اسلام‌آباد غرب", 65),
    ("اسلام‌آباد غرب", "ایلام", 110), ("خرم‌آباد", "پلدختر", 100), ("پلدختر", "دزفول", 115),
    ("اصفهان", "نائین", 140), ("نائین", "اردکان", 135), ("اردکان", "یزد", 60),
    # جنوب‌غرب و جنوب
    ("دزفول", "اهواز", 150), ("اهواز", "آبادان", 120), ("اهواز", "بهبهان", 200), ("بهبهان", "دوگنبدان", 95),
    ("دوگنبدان", "یاسوج", 120), ("یاسوج", "شیراز", 175), ("بوشهر", "برازجان", 70), ("برازجان", "کازرون", 100),
    ("کازرون", "شیراز", 115), ("بوشهر", "بندر کنگان", 220), ("اصفهان", "شهرکرد", 100), ("شهرکرد", "بروجن", 60),
    ("بروجن", "شهرضا", 80), ("اصفهان", "شهرضا", 85), ("شهرضا", "آباده", 130), ("آباده", "مرودشت", 230),
    ("مرودشت", "شیراز", 45), ("یزد", "آباده", 260), ("شیراز", "جهرم", 190), ("جهرم", "لار", 180),
    ("لار", "بندرعباس", 320), ("شیراز", "فسا", 150), ("جهرم", "فسا", 70), ("فسا", "داراب", 100),
    ("داراب", "بندرعباس", 330),
    # جنوب‌شرق
    ("یزد", "رفسنجان", 270), ("رفسنجان", "کرمان", 110), ("رفسنجان", "سیرجان", 120), ("سیرجان", "بندرعباس", 300),
    ("کرمان", "بم", 195), ("کرمان", "جیرفت", 230), ("جیرفت", "میناب", 240), ("میناب", "بندرعباس", 100),
)

# متوسط سرعت حرکت بار بین‌شهری با احتساب توقف‌ها (برای تخمین پیشرفت بین دو گزارش راننده)
AVERAGE_SPEED_KMH = 60
# فاصله جاده‌ای ≈ فاصله مستقیم × این ضریب (برای اتصال شهرهای خارج از گراف)
ROAD_FACTOR = 1.25
# نام‌های رایج دیگر ← نام رسمی در فهرست
ALIASES = {"گچساران": "دوگنبدان", "کنگان": "بندر کنگان", "بندر بوشهر": "بوشهر"}
DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "iran_cities.json"


def _key(name: str | None) -> str:
    """کلید مقایسه نام شهر: ی/ک یکسان، بدون فاصله و نیم‌فاصله (بندر عباس = بندرعباس، خرم آباد = خرم‌آباد)."""
    return re.sub(r"[\s‌‍\-]+", "", normalize_persian_text(name or ""))


@lru_cache(maxsize=1)
def _alias_keys() -> dict[str, str]:
    return {_key(a): _key(b) for a, b in ALIASES.items()}


@lru_cache(maxsize=1)
def all_cities() -> tuple[City, ...]:
    """همه شهرهای ایران (مرکز استان اول، سپس به ترتیب جمعیت)."""
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))["cities"]
    return tuple(City(n, p, lat, lon, bool(cap)) for n, p, lat, lon, cap in data)


@lru_cache(maxsize=1)
def _by_key() -> dict[str, list[City]]:
    index: dict[str, list[City]] = {}
    for c in all_cities():
        index.setdefault(_key(c.name), []).append(c)
    return index


@lru_cache(maxsize=1)
def _road_index() -> dict[str, City]:
    return {_key(c.name): c for c in CITIES}


@lru_cache(maxsize=1)
def _capitals() -> dict[str, City]:
    return {c.province: c for c in all_cities() if c.capital}


@lru_cache(maxsize=1)
def _graph() -> dict[str, list[tuple[str, int]]]:
    names = {c.name for c in CITIES}
    graph: dict[str, list[tuple[str, int]]] = {n: [] for n in names}
    for a, b, km in ROADS:
        assert a in names and b in names, (a, b)
        graph[a].append((b, km))
        graph[b].append((a, km))
    return graph


def find_city(name: str | None, province: str | None = None) -> City | None:
    """شهر با نام (و در صورت وجود، استان)؛ نام‌های مستعار هم شناخته می‌شوند."""
    if not name:
        return None
    key = _key(name)
    key = _alias_keys().get(key, key)
    matches = _by_key().get(key, [])
    if province:
        province = normalize_persian_text(province)
        matches = [c for c in matches if c.province == province]
    if not matches:
        return None
    return max(matches, key=lambda c: (c.capital, _key(c.name) in _road_index()))


def canonical_city(name: str | None, province: str | None) -> str:
    """نام رسمی شهر در استان؛ اگر در فهرست نباشد ValueError (برای اعتبارسنجی فرم‌ها)."""
    city = find_city(name, province)
    if city is None:
        where = f" در استان {province}" if province else ""
        raise ValueError(f"شهر «{(name or '').strip()}»{where} در فهرست شهرها نیست؛ از فهرست انتخاب کنید.")
    return city.name


def resolve(city: str | None, province: str | None) -> tuple[City | None, bool]:
    """
    نقطه روی نقشه برای یک (شهر، استان). خروجی: (شهر، دقیق؟).
    اگر شهر در فهرست نباشد، مرکز استان برگردانده می‌شود (دقیق=False).
    """
    found = find_city(city, province) if province else find_city(city)
    if found:
        return found, True
    capital = _capitals().get(normalize_persian_text(province or "")) if province else None
    return (capital, False) if capital else (None, False)


def _distance_km(a: City, b: City) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def _road_km(a: City, b: City) -> int:
    return max(1, round(_distance_km(a, b) * ROAD_FACTOR))


def _road_node(city: City) -> City | None:
    node = _road_index().get(_key(city.name))
    return node if node and node.province == city.province else None


def _entries(city: City) -> list[tuple[str, int]]:
    """گره‌های گراف که این شهر از آن‌ها وارد/خارج می‌شود: خودش، یا ۳ شهر نزدیک گراف."""
    node = _road_node(city)
    if node:
        return [(node.name, 0)]
    nearest = sorted(CITIES, key=lambda c: _distance_km(city, c))[:3]
    return [(c.name, _road_km(city, c)) for c in nearest]


def _dijkstra(origin: str) -> tuple[dict[str, int], dict[str, str]]:
    graph = _graph()
    dist, prev = {origin: 0}, {}
    heap = [(0, origin)]
    while heap:
        d, node = heapq.heappop(heap)
        if d > dist[node]:
            continue
        for nxt, km in graph[node]:
            nd = d + km
            if nd < dist.get(nxt, 1 << 30):
                dist[nxt], prev[nxt] = nd, node
                heapq.heappush(heap, (nd, nxt))
    return dist, prev


def route(origin: City, destination: City) -> list[tuple[City, int]]:
    """مسیر جاده‌ای تقریبی بین دو شهر دلخواه؛ خروجی: [(شهر، کیلومتر تجمعی از مبدأ)]."""
    if _key(origin.name) == _key(destination.name) and origin.province == destination.province:
        return [(origin, 0)]
    road = _road_index()
    best: tuple[int, list[City]] | None = None
    # دو شهر نزدیک به هم: مستقیم
    direct = _road_km(origin, destination)
    if direct < 120 and not (_road_node(origin) and _road_node(destination)):
        best = (direct, [origin, destination])
    for start, lead in _entries(origin):
        dist, prev = _dijkstra(start)
        for end, tail in _entries(destination):
            if end not in dist:
                continue
            total = lead + dist[end] + tail
            if best is None or total < best[0]:
                names = [end]
                while names[-1] != start:
                    names.append(prev[names[-1]])
                nodes = [road[_key(n)] for n in reversed(names)]
                best = (total, ([origin] if lead else []) + nodes + ([destination] if tail else []))
    assert best is not None
    path = list(best[1])
    path[0], path[-1] = origin, destination          # مختصات دقیق مبدأ و مقصد
    graph = _graph()
    result, km = [(path[0], 0)], 0.0
    for a, b in zip(path, path[1:], strict=False):
        edge = next((k for n, k in graph.get(a.name, []) if n == b.name), None) if _road_node(a) and _road_node(b) else None
        km += edge if edge is not None else _road_km(a, b)
        result.append((b, round(km)))
    return result


def shortest_path(origin: str, destination: str) -> list[tuple[City, int]]:
    """مسیر بین دو شهر با نام."""
    a, b = find_city(origin), find_city(destination)
    return route(a, b) if a and b else []


def cities_of(province: str | None = None) -> list[City]:
    """شهرهای یک استان برای فهرست انتخاب: مرکز استان اول، بقیه به ترتیب الفبا."""
    cities = [c for c in all_cities() if not province or c.province == province]
    return sorted(cities, key=lambda c: (not c.capital, c.province, normalize_persian_text(c.name)))
