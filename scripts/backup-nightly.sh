#!/usr/bin/env bash
# بکاپ شبانه رمزگذاری‌شده: دیتابیس و فایل‌های آپلودی، هر کدام با GPG متقارن AES256. متن ساده هیچ‌وقت روی دیسک نوشته نمی‌شود.
#
#   cron کاربر root:   0 3 * * * /opt/logitrack/scripts/backup-nightly.sh >> /var/log/logitrack-backup.log 2>&1
#   آزمون دستی:        sudo /opt/logitrack/scripts/backup-nightly.sh
#
# کلید: BACKUP_KEY_FILE (پیش‌فرض /root/.pasineh-backup-key)، فقط با دسترسی 600 یا 400. مسیر کلید به gpg داده می‌شود و خود کلید
# در آرگومان پردازش، خروجی یا لاگ نمی‌آید. نسخه بازیابی کلید جای دیگری (مدیر رمز یا کاغذ) است، نه کنار بکاپ‌ها.
# خروجی: nightly-db-<زمان>.sql.gz.gpg و nightly-media-<زمان>.tar.gz.gpg، هر کدام با فایل .sha256 کنارش.
# نگه‌داری: BACKUP_KEEP_DAYS روز (پیش‌فرض ۱۴). بکاپ‌های قدیمی بی‌رمز (db-*، media-*) را این اسکریپت دست نمی‌زند.
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."

KEY_FILE="${BACKUP_KEY_FILE:-/root/.pasineh-backup-key}"
OUT="${BACKUP_DIR:-backups}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
MEDIA_VOLUME="${MEDIA_VOLUME:-logitrack_media_data}"

if [ ! -r "$KEY_FILE" ]; then
  echo "❌ فایل کلید خوانده نشد؛ مسیر آن را در BACKUP_KEY_FILE بدهید." >&2
  exit 1
fi
case "$(stat -c %a "$KEY_FILE" 2>/dev/null || echo unknown)" in
  600|400) ;;
  *) [ "${BACKUP_ALLOW_LOOSE_KEY:-}" = "1" ] || { echo "❌ دسترسی فایل کلید باید 600 یا 400 باشد." >&2; exit 1; } ;;
esac
mkdir -p "$OUT"

# دو اجرای هم‌زمان (cron و اجرای دستی) روی هم نمی‌نویسند
if command -v flock >/dev/null 2>&1; then
  exec 9>"$OUT/.backup.lock"
  flock -n 9 || { echo "❌ بکاپ دیگری در حال اجراست." >&2; exit 1; }
fi

STAMP=$(date -u +%Y%m%d-%H%M)
DB="$OUT/nightly-db-$STAMP.sql.gz.gpg"
MEDIA="$OUT/nightly-media-$STAMP.tar.gz.gpg"
# فایل نیمه‌کاره با پسوند .part نوشته می‌شود و فقط پس از موفقیت کامل نام نهایی می‌گیرد
trap 'rm -f "$DB.part" "$MEDIA.part"' EXIT

encrypt() {
  gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-file "$KEY_FILE" \
    --symmetric --cipher-algo AES256 --compress-algo none --output "$1"
}

docker compose exec -T db pg_dump -U postgres -d logitrack | gzip | encrypt "$DB.part"
mv "$DB.part" "$DB"
docker run --rm --network none -v "$MEDIA_VOLUME":/media:ro alpine tar czf - -C /media . | encrypt "$MEDIA.part"
mv "$MEDIA.part" "$MEDIA"
for file in "$DB" "$MEDIA"; do
  (cd "$(dirname "$file")" && sha256sum "$(basename "$file")" > "$(basename "$file").sha256")
done

find "$OUT" -maxdepth 1 -type f \( -name 'nightly-db-*.sql.gz.gpg*' -o -name 'nightly-media-*.tar.gz.gpg*' \) -mtime +"$KEEP_DAYS" -delete
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) backup ok: $STAMP db=$(du -h "$DB" | cut -f1) media=$(du -h "$MEDIA" | cut -f1)"
