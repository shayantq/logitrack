#!/usr/bin/env bash
# تأیید بکاپ (فصل ۳۴): آخرین بکاپ شبانه دیتابیس را در یک کانتینر PostgreSQL موقت و جدا بازیابی می‌کند و
# تعداد ردیف جدول‌های اصلی را با دیتابیس در حال کار مقایسه می‌کند. هیچ چیزی در دیتابیس اصلی تغییر نمی‌کند.
#
#   cd /opt/logitrack && bash scripts/verify-backup.sh            # آخرین backups/db-*.sql.gz
#   bash scripts/verify-backup.sh backups/db-20261026-0300.sql.gz # یک فایل مشخص
#
# بکاپ شبانه بعد از بازیابی کمی از دیتابیس زنده عقب‌تر است؛ پس فقط «کمتر یا مساوی بودن» و خالی نبودن بررسی می‌شود.
set -euo pipefail
cd "$(dirname "$0")/.."

FILE="${1:-$(ls -1t backups/db-*.sql.gz 2>/dev/null | head -n 1 || true)}"
if [ -z "$FILE" ] || [ ! -f "$FILE" ]; then
  echo "❌ فایل بکاپ پیدا نشد (backups/db-*.sql.gz)." >&2
  exit 1
fi
NAME="pasineh_backup_verify_$$"
TABLES="organizations users products warehouses inventories stock_movements stock_documents orders audit_logs"
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "📦 بکاپ: $FILE ($(du -h "$FILE" | cut -f1))"
gzip -t "$FILE"
docker run -d --name "$NAME" -e POSTGRES_PASSWORD=verify -e POSTGRES_DB=logitrack postgres:16-alpine >/dev/null
for _ in $(seq 1 30); do
  docker exec "$NAME" pg_isready -U postgres -d logitrack >/dev/null 2>&1 && break
  sleep 1
done
echo "♻️  بازیابی در دیتابیس موقت..."
gunzip -c "$FILE" | docker exec -i "$NAME" psql -q -v ON_ERROR_STOP=1 -U postgres -d logitrack >/dev/null

count() { "$@" psql -U postgres -d logitrack -tAc "SELECT count(*) FROM $TABLE" 2>/dev/null | tr -d '[:space:]'; }
status=0
printf "%-18s %12s %12s\n" "جدول" "بکاپ" "زنده"
for TABLE in $TABLES; do
  restored=$(count docker exec "$NAME")
  live=$(count docker compose exec -T db)
  mark="✓"
  if [ -z "$restored" ]; then mark="✗"; status=1; fi
  if [ "$restored" = "0" ] && [ "${live:-0}" != "0" ]; then mark="✗"; status=1; fi
  if [ -n "$restored" ] && [ -n "$live" ] && [ "$restored" -gt "$live" ]; then mark="✗"; status=1; fi
  printf "%-18s %12s %12s  %s\n" "$TABLE" "${restored:-?}" "${live:-?}" "$mark"
done
version=$(docker exec "$NAME" psql -U postgres -d logitrack -tAc "SELECT version_num FROM alembic_version" | tr -d '[:space:]')
echo "🧬 نسخه دیتابیس در بکاپ: $version"
if [ "$status" -eq 0 ]; then
  echo "✅ بکاپ سالم است و قابل بازیابی است. در «آمادگی راه‌اندازی» مورد «بکاپ بازیابی آزمایشی شد» را تیک بزنید."
else
  echo "❌ بکاپ ناقص است؛ اسکریپت بکاپ شبانه را بررسی کنید." >&2
fi
exit "$status"
