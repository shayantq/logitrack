"""clean city data against the official city list; default warehouse for organizations without one

Revision ID: 0015_clean_cities
Revises: 0014_order_routes
Create Date: 2026-10-12

از این مرحله شهرها فقط از فهرست رسمی (app/data/iran_cities.json) انتخاب می‌شوند. داده‌های قبلی:
۱. نام شهرهای معتبر به املای رسمی تبدیل می‌شود (مثلاً «بندر عباس» ← «بندرعباس»).
۲. شهر ناشناخته («سسس»، «مم»، ...) ← مرکز همان استان؛ اگر استان هم معلوم نباشد ← خالی.
۳. پروفایل رانندگانی که استان/شهر ندارند از شهر حساب کاربری‌شان پر می‌شود.
۴. سازمانی که هیچ انباری ندارد یک «انبار مرکزی» در شهر سازمان (یا تهران) می‌گیرد.
"""

from alembic import op
import sqlalchemy as sa

from app.core import geo

revision = '0015_clean_cities'
down_revision = '0014_order_routes'
branch_labels = None
depends_on = None


def _fix(city: str | None, province: str | None) -> tuple[str | None, str | None]:
    """(شهر، استان) اصلاح‌شده."""
    if not city and not province:
        return city, province
    found = geo.find_city(city, province) if province else geo.find_city(city)
    if found:
        return found.name, found.province
    capital, _ = geo.resolve(None, province)
    return (capital.name, capital.province) if capital else (None, province)


def _rows(bind, sql):
    return bind.execute(sa.text(sql)).fetchall()


def upgrade():
    bind = op.get_bind()

    # سفارش‌ها، انبارها، سازمان‌ها، درخواست‌های ثبت سازمان، پروفایل رانندگان (جفت شهر/استان)
    for table, city_col, prov_col in (("orders", "destination_city", "destination_province"),
                                      ("warehouses", "city", "province"),
                                      ("organizations", "city", "province"),
                                      ("organization_requests", "city", "province"),
                                      ("driver_profiles", "city", "province")):
        for rid, city, prov in _rows(bind, f"SELECT id, {city_col}, {prov_col} FROM {table}"):
            if not city:
                continue
            new_city, new_prov = _fix(city, prov)
            if (new_city, new_prov) != (city, prov) and new_city is not None:
                bind.execute(sa.text(f"UPDATE {table} SET {city_col} = :c, {prov_col} = :p WHERE id = :id"),
                             {"c": new_city, "p": new_prov, "id": rid})

    # شهر حساب کاربری و خودرو (بدون استان): نام رسمی، یا مرکز استان پروفایل راننده، یا خالی
    profile_prov = {uid: prov for uid, prov in _rows(bind, "SELECT user_id, province FROM driver_profiles")}
    for uid, city in _rows(bind, "SELECT id, city FROM users WHERE city IS NOT NULL AND city <> ''"):
        found = geo.find_city(city, profile_prov.get(uid)) or geo.find_city(city)
        new = found.name if found else (_fix(None, profile_prov.get(uid))[0] if profile_prov.get(uid) else None)
        if new != city:
            bind.execute(sa.text("UPDATE users SET city = :c WHERE id = :id"), {"c": new, "id": uid})
    for vid, city, driver_id in _rows(bind, "SELECT id, city, driver_id FROM vehicles WHERE city IS NOT NULL AND city <> ''"):
        found = geo.find_city(city, profile_prov.get(driver_id)) or geo.find_city(city)
        new = found.name if found else (_fix(None, profile_prov.get(driver_id))[0] if profile_prov.get(driver_id) else None)
        if new != city:
            bind.execute(sa.text("UPDATE vehicles SET city = :c WHERE id = :id"), {"c": new, "id": vid})

    # پروفایل راننده بدون استان/شهر ← از شهر حساب کاربری
    for pid, user_city in _rows(bind, """SELECT dp.id, u.city FROM driver_profiles dp JOIN users u ON u.id = dp.user_id
                                         WHERE (dp.city IS NULL OR dp.city = '') AND u.city IS NOT NULL AND u.city <> ''"""):
        found = geo.find_city(user_city)
        if found:
            bind.execute(sa.text("UPDATE driver_profiles SET city = :c, province = :p WHERE id = :id"),
                         {"c": found.name, "p": found.province, "id": pid})

    # سازمان بدون انبار ← «انبار مرکزی» در شهر سازمان (یا تهران)
    for oid, city, prov, address in _rows(bind, """SELECT o.id, o.city, o.province, o.address FROM organizations o
                                                   WHERE NOT EXISTS (SELECT 1 FROM warehouses w WHERE w.organization_id = o.id)"""):
        place = geo.find_city(city, prov) if city else None
        place = place or geo.resolve(None, prov)[0] or geo.find_city("تهران")
        bind.execute(sa.text("INSERT INTO warehouses (organization_id, name, location, province, city) "
                             "VALUES (:o, :n, :l, :p, :c)"),
                     {"o": oid, "n": f"انبار مرکزی {place.name}", "l": address or place.name,
                      "p": place.province, "c": place.name})


def downgrade():
    # اصلاح داده برگشت‌پذیر نیست (مقادیر قبلی نامعتبر بودند)
    pass
