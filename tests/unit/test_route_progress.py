"""مرحله ۱۰: مسیریابی روی گراف شهرها و قاعده پیشرفت (وضعیت + گزارش راننده + زمان)."""
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.core import geo
from app.services import route_service

NOW = datetime(2026, 10, 12, 12, 0)


def _route(origin="تهران", dest="تبریز"):
    warehouse = SimpleNamespace(name="انبار", city=origin, province=None, location=None)
    return route_service.plan(warehouse, dest, None)


def _cp(seq, hours_ago, route):
    return SimpleNamespace(seq=seq, city=route["points"][seq]["label"], reached_at=NOW - timedelta(hours=hours_ago))


def test_shortest_path_and_name_normalization():
    route = _route()
    assert [p["city"] for p in route["points"]] == ["تهران", "کرج", "آبیک", "قزوین", "تاکستان", "زنجان", "میانه", "تبریز"]
    assert route["total_km"] == route["points"][-1]["km"] > 600
    # «بندر عباس» با فاصله و «ي/ك» عربی همان شهر است
    assert geo.find_city("بندر عباس").name == "بندرعباس"
    assert geo.find_city("كرمانشاه").name == "کرمانشاه"


def test_unknown_city_falls_back_to_province_capital_and_keeps_label():
    warehouse = SimpleNamespace(name="انبار", city="قزوین", province="قزوین", location=None)
    route = route_service.plan(warehouse, "روستای ناشناخته", "اصفهان")
    last = route["points"][-1]
    assert last["city"] == "اصفهان" and last["label"] == "روستای ناشناخته" and last["approx"] is True


def test_no_route_without_known_origin():
    warehouse = SimpleNamespace(name="انبار", city=None, province=None, location="خیابان آزادی")
    assert route_service.plan(warehouse, "تبریز", None) is None


def test_progress_before_departure_and_after_delivery():
    route = _route()
    for status in ("pending", "assigned", "picking_up", "picked_up"):
        p = route_service.progress(SimpleNamespace(status=status), route, [], None, NOW)
        assert p["fraction"] == 0 and p["passed_seq"] == -1 and p["eta"] is None
    p = route_service.progress(SimpleNamespace(status="delivered"), route, [], NOW - timedelta(hours=9), NOW)
    assert p["fraction"] == 1 and p["passed_seq"] == len(route["points"]) - 1


def test_in_transit_advances_with_time_but_never_passes_unreported_city():
    route = _route()
    order = SimpleNamespace(status="in_transit")
    first_city_km = route["points"][1]["km"]          # کرج
    early = route_service.progress(order, route, [], NOW - timedelta(minutes=30), NOW)
    assert 0 < early["km_done"] <= first_city_km and early["estimated"] is True and early["next_seq"] == 1
    # ده ساعت بدون گزارش: پشت شهر بعدی می‌ماند
    stuck = route_service.progress(order, route, [], NOW - timedelta(hours=10), NOW)
    assert stuck["km_done"] < first_city_km and stuck["passed_seq"] == 0
    assert stuck["eta"] > NOW


def test_driver_report_moves_progress_to_that_city():
    route = _route()
    order = SimpleNamespace(status="in_transit")
    p = route_service.progress(order, route, [_cp(5, 0, route)], NOW - timedelta(hours=8), NOW)   # زنجان، همین الان
    assert p["passed_seq"] == 5 and p["km_done"] == route["points"][5]["km"]
    assert p["last_report"]["city"] == "زنجان" and p["next_seq"] == 6
    later = route_service.progress(order, route, [_cp(5, 1, route)], NOW - timedelta(hours=9), NOW)
    assert route["points"][5]["km"] < later["km_done"] < route["points"][6]["km"]


def test_stopped_orders_freeze_at_last_report():
    route = _route()
    p = route_service.progress(SimpleNamespace(status="failed"), route, [_cp(3, 2, route)], NOW - timedelta(hours=5), NOW)
    assert p["passed_seq"] == 3 and p["km_done"] == route["points"][3]["km"] and p["eta"] is None


def test_same_city_route_uses_status():
    route = _route("قزوین", "قزوین")
    assert route["total_km"] == 0 and len(route["points"]) == 1
    assert route_service.progress(SimpleNamespace(status="in_transit"), route, [], NOW, NOW)["fraction"] == 0.5
    assert route_service.progress(SimpleNamespace(status="delivered"), route, [], NOW, NOW)["fraction"] == 1
