#!/usr/bin/env bash
# نسخه بکاپ رمزگذاری‌شده روی کامپیوتر خود مالک (Git Bash ویندوز). فقط فایل .gpg و .sha256 جابه‌جا می‌شود و چیزی روی سرور تغییر نمی‌کند.
#
#   BACKUP_HOST=root@passineh.ir bash scripts/pull-backup.sh /c/PasinehBackups
#
# مقصد نباید داخل OneDrive یا این مخزن باشد. پیش از دریافت، فضای خالی سنجیده می‌شود و پس از دریافت، checksum.
# نگه‌داری: BACKUP_KEEP_COPIES نسخه آخر (پیش‌فرض ۷).
set -euo pipefail

HOST="${BACKUP_HOST:?مقدار BACKUP_HOST را بدهید، مثلاً root@passineh.ir}"
DEST="${1:-/c/PasinehBackups}"
KEEP="${BACKUP_KEEP_COPIES:-7}"
REMOTE_DIR="${BACKUP_REMOTE_DIR:-/opt/logitrack/backups}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"

case "$(cd "$(dirname "$DEST")" 2>/dev/null && pwd)/$(basename "$DEST")" in
  *OneDrive*|*onedrive*) echo "❌ مقصد داخل OneDrive است؛ بکاپ نباید به سرویس بیرونی همگام شود." >&2; exit 1 ;;
  "$REPO"*) echo "❌ مقصد داخل مخزن است؛ جای دیگری بدهید." >&2; exit 1 ;;
esac
mkdir -p "$DEST"

DB=$(ssh "$HOST" "ls -1t '$REMOTE_DIR'/nightly-db-*.sql.gz.gpg 2>/dev/null | head -n 1")
[ -n "$DB" ] || { echo "❌ بکاپ رمزگذاری‌شده‌ای روی سرور نیست." >&2; exit 1; }
STAMP=$(basename "$DB" | sed -E 's/^nightly-db-(.*)\.sql\.gz\.gpg$/\1/')
MEDIA="$REMOTE_DIR/nightly-media-$STAMP.tar.gz.gpg"

need_kb=$(ssh "$HOST" "du -k '$DB' '$MEDIA' | awk '{s+=\$1} END {print s*3}'")
free_kb=$(df -Pk "$DEST" | awk 'NR==2 {print $4}')
if [ "$free_kb" -lt "$need_kb" ]; then
  echo "❌ فضای خالی کافی نیست: ${free_kb}KB موجود، دست‌کم ${need_kb}KB لازم." >&2
  exit 1
fi

scp -p "$HOST:$DB" "$HOST:$DB.sha256" "$HOST:$MEDIA" "$HOST:$MEDIA.sha256" "$DEST/"
(cd "$DEST" && sha256sum -c "nightly-db-$STAMP.sql.gz.gpg.sha256" "nightly-media-$STAMP.tar.gz.gpg.sha256")

# فقط KEEP نسخه آخر می‌ماند؛ هر نسخه چهار فایل دارد
ls -1t "$DEST"/nightly-db-*.sql.gz.gpg 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do
  stamp=$(basename "$old" | sed -E 's/^nightly-db-(.*)\.sql\.gz\.gpg$/\1/')
  rm -f "$DEST/nightly-db-$stamp.sql.gz.gpg" "$DEST/nightly-db-$stamp.sql.gz.gpg.sha256" \
        "$DEST/nightly-media-$stamp.tar.gz.gpg" "$DEST/nightly-media-$stamp.tar.gz.gpg.sha256"
done
echo "✅ نسخه $STAMP دریافت و سنجیده شد. عمر این نسخه همان RPO بیرون از سرور است."
