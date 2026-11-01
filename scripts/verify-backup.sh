#!/usr/bin/env bash
# تمرین بازیابی بکاپ (فصل ۳۴): بکاپ را در کانتینر موقت PostgreSQL بدون شبکه بازیابی و سالم بودنش را می‌سنجد.
# این اسکریپت به دیتابیس زنده وصل نمی‌شود و دستوری روی سرویس‌های در حال کار اجرا نمی‌کند.
#
#   cd /opt/logitrack && DRILL_ENV=production bash scripts/verify-backup.sh    # تازه‌ترین بکاپ
#   DRILL_ENV=local bash scripts/verify-backup.sh backups/db-20261026-0300.sql.gz
#
# نام‌های شناخته‌شده: db-*.sql.gz، pre-deploy-*.sql.gz و nightly-*.sql.gz.enc.
# فایل .enc با BACKUP_KEY_FILE (پیش‌فرض /root/.pasineh-backup-key) باز می‌شود. مسیر کلید به openssl داده می‌شود و خود کلید در
# آرگومان پردازش، خروجی یا لاگ نمی‌آید.
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."

FILE="${1:-$(ls -1t backups/db-*.sql.gz backups/pre-deploy-*.sql.gz backups/nightly-*.sql.gz.enc 2>/dev/null | head -n 1 || true)}"
if [ -z "$FILE" ] || [ ! -f "$FILE" ]; then
  echo "❌ فایل بکاپ پیدا نشد (backups/db-*.sql.gz، pre-deploy-*.sql.gz، nightly-*.sql.gz.enc)." >&2
  exit 1
fi
case "$FILE" in
  *.sql.gz.enc)
    KEY_FILE="${BACKUP_KEY_FILE:-/root/.pasineh-backup-key}"
    if [ ! -r "$KEY_FILE" ]; then
      echo "❌ فایل کلید خوانده نشد؛ مسیر آن را در BACKUP_KEY_FILE بدهید." >&2
      exit 1
    fi
    ;;
  *.sql.gz) ;;
  *)
    echo "❌ قالب فایل شناخته نشد؛ فقط .sql.gz و .sql.gz.enc پذیرفته می‌شود." >&2
    exit 1
    ;;
esac

SOURCE="$(cd "$(dirname "$FILE")" && (pwd -W 2>/dev/null || pwd))/$(basename "$FILE")"
NAME="pasineh_backup_verify_$$"
TABLES="organizations users products warehouses inventories stock_movements stock_documents orders audit_logs"
REQUIRED="organizations alembic_version"
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "📦 بکاپ: $FILE ($(du -h "$FILE" | cut -f1))"
# بدون شبکه و بدون پورت باز: این کانتینر به هیچ سرویسی دسترسی ندارد. بکاپ فقط‌خواندنی وصل می‌شود.
docker run -d --name "$NAME" --network none --mount "type=bind,source=$SOURCE,target=/backup/source,readonly" \
  -e POSTGRES_PASSWORD=verify -e POSTGRES_DB=logitrack postgres:16-alpine >/dev/null
ready=0
for _ in $(seq 1 60); do
  if docker exec "$NAME" sh -c 'pg_isready -q -U postgres -d logitrack && psql -U postgres -d logitrack -c "select 1"' >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [ "$ready" -ne 1 ]; then
  echo "❌ کانتینر موقت بالا نیامد." >&2
  exit 1
fi

RESTORE_STARTED=$(date +%s)
case "$FILE" in
  *.enc)
    # تصویر postgres ابزار openssl ندارد: روی میزبان باز می‌شود و فقط داخل همین کانتینر موقت می‌ماند
    openssl enc -d -aes-256-cbc -pbkdf2 -pass "file:$KEY_FILE" -in "$FILE" | docker exec -i "$NAME" sh -c 'cat > /tmp/restore.sql.gz'
    ;;
  *)
    docker exec "$NAME" cp /backup/source /tmp/restore.sql.gz
    ;;
esac
docker exec "$NAME" gzip -t /tmp/restore.sql.gz
# فایل نیمه‌کاره ممکن است gzip سالم داشته باشد؛ pg_dump فقط در پایان کار این خط را می‌نویسد
if ! docker exec "$NAME" sh -c 'gunzip -c /tmp/restore.sql.gz | tail -n 5 | grep -q "PostgreSQL database dump complete"'; then
  echo "❌ dump ناقص است: خط پایان pg_dump در فایل نیست." >&2
  exit 1
fi
echo "♻️  بازیابی در دیتابیس موقت..."
docker exec "$NAME" sh -c 'gunzip -c /tmp/restore.sql.gz | psql -q -v ON_ERROR_STOP=1 -U postgres -d logitrack' >/dev/null
RESTORE_SECONDS=$(( $(date +%s) - RESTORE_STARTED ))

count() { docker exec "$NAME" psql -U postgres -d logitrack -tAc "SELECT count(*) FROM $1" 2>/dev/null | tr -d '[:space:]'; }
status=0
printf "%-18s %12s\n" "جدول" "ردیف"
for TABLE in $TABLES; do
  restored=$(count "$TABLE" || true)
  mark="✓"
  if [ -z "$restored" ]; then mark="✗"; status=1; fi
  printf "%-18s %12s  %s\n" "$TABLE" "${restored:-?}" "$mark"
done
for TABLE in $REQUIRED; do
  restored=$(count "$TABLE" || true)
  if [ -z "$restored" ] || [ "$restored" = "0" ]; then
    echo "✗ جدول $TABLE خالی است یا وجود ندارد." >&2
    status=1
  fi
done

BACKUP_AGE_MINUTES=$(( ( $(date +%s) - $(date -r "$FILE" +%s) ) / 60 ))
DRILL_LABEL="${DRILL_ENV:-unlabeled}"
echo "🏷️  محیط: $DRILL_LABEL"
echo "⏱️  عمر بکاپ هنگام تمرین: ${BACKUP_AGE_MINUTES} دقیقه — زمان باز کردن و بازیابی: ${RESTORE_SECONDS} ثانیه"
mkdir -p backups
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) env=${DRILL_LABEL} file=$(basename "$FILE") rpo_minutes=${BACKUP_AGE_MINUTES} rto_seconds=${RESTORE_SECONDS} status=${status}" >> backups/restore-drills.log
version=$(docker exec "$NAME" psql -U postgres -d logitrack -tAc "SELECT version_num FROM alembic_version" | tr -d '[:space:]')
echo "🧬 نسخه دیتابیس در بکاپ: $version"
if [ "$status" -eq 0 ]; then
  echo "✅ بکاپ سالم است و قابل بازیابی است. فقط دیتابیس سنجیده شد؛ بکاپ فایل‌ها (media-*) جداست."
else
  echo "❌ بکاپ ناقص است؛ اسکریپت بکاپ شبانه را بررسی کنید." >&2
fi
exit "$status"
