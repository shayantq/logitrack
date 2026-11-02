"""
ایمنی تمرین بازیابی (BAK-01، BAK-02): تمرین به سرویس زنده دست نمی‌زند و کلید را آشکار نمی‌کند.
اجرای واقعی اسکریپت به docker نیاز دارد و در docs/operations-guide.md ثبت شده است؛ این‌جا متن دستورها سنجیده می‌شود.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / "scripts/verify-backup.sh").read_text(encoding="utf-8")
COMMANDS = "\n".join(line for line in SCRIPT.splitlines() if not line.lstrip().startswith("#"))
WORKFLOW = (ROOT / ".github/workflows/ci-cd.yml").read_text(encoding="utf-8")


def test_drill_never_touches_compose_services():
    assert "docker compose" not in COMMANDS and "docker-compose" not in COMMANDS
    assert not re.search(r"\b(createdb|dropdb|pg_restore)\b", COMMANDS)
    assert "DROP " not in COMMANDS.upper()


def test_restore_container_is_isolated_and_backup_is_read_only():
    run = next(line for line in COMMANDS.splitlines() if "docker run" in line)
    assert "--network none" in run and "target=/backup/source,readonly" in run
    assert not re.search(r"\s(-p|--publish|-P)\s", run)


def test_every_container_command_targets_the_temporary_container():
    for line in COMMANDS.splitlines():
        if "docker exec" in line:
            assert 'docker exec "$NAME"' in line or 'docker exec -i "$NAME"' in line, line


def test_key_only_travels_as_a_file_path():
    assert '-pass "file:$KEY_FILE"' in COMMANDS
    assert not re.search(r"-pass\s+\"?(pass|env|stdin|fd):", COMMANDS)
    assert not re.search(r"(cat|echo|printf)\b.*\$\{?KEY_FILE", COMMANDS)


def test_all_real_backup_names_are_recognized():
    for pattern in ("backups/db-*.sql.gz", "backups/pre-deploy-*.sql.gz", "backups/nightly-*.sql.gz.enc"):
        assert pattern in COMMANDS


def test_truncated_dump_is_detected_and_results_carry_an_environment():
    assert "PostgreSQL database dump complete" in COMMANDS and "ON_ERROR_STOP=1" in COMMANDS
    assert "env=${DRILL_LABEL}" in COMMANDS


def test_security_doc_has_no_restore_on_the_live_service():
    doc = (ROOT / "docs/security.md").read_text(encoding="utf-8")
    assert "restore_check" not in doc and "createdb" not in doc and "dropdb" not in doc


def test_deploy_backup_umask_is_limited_to_the_backup_file():
    """umask در زیرپوسته است تا روی فایل‌هایی که git pull و build بعد از آن می‌سازند اثر نگذارد."""
    backup = next(line for line in WORKFLOW.splitlines() if "pg_dump" in line and "pre-deploy" in line)
    assert re.match(r"\s*\(\s*umask 077;.*pg_dump.*\)\s*$", backup)
    assert "umask" not in "".join(line for line in WORKFLOW.splitlines() if line.strip().startswith("git pull"))


NIGHTLY = (ROOT / "scripts/backup-nightly.sh").read_text(encoding="utf-8")
NIGHTLY_COMMANDS = "\n".join(line for line in NIGHTLY.splitlines() if not line.lstrip().startswith("#"))
PULL = (ROOT / "scripts/pull-backup.sh").read_text(encoding="utf-8")


def test_nightly_backup_is_encrypted_before_touching_disk():
    """متن ساده dump و آرشیو فقط در لوله است؛ تنها فایل نوشته‌شده خروجی gpg است."""
    assert "umask 077" in NIGHTLY_COMMANDS
    assert "--symmetric --cipher-algo AES256" in NIGHTLY_COMMANDS and '--passphrase-file "$KEY_FILE"' in NIGHTLY_COMMANDS
    assert re.search(r"pg_dump .*\| gzip \| encrypt", NIGHTLY_COMMANDS) and re.search(r"tar czf - .*\| encrypt", NIGHTLY_COMMANDS)
    assert not re.search(r">\s*\"?\$?\{?OUT\}?/[^\"]*\.(sql|tar)(\.gz)?\"?\s*$", NIGHTLY_COMMANDS, re.MULTILINE)
    assert not re.search(r"(cat|echo|printf)\b.*\$\{?KEY_FILE", NIGHTLY_COMMANDS)


def test_nightly_backup_is_atomic_locked_and_keeps_old_plain_files():
    assert ".part" in NIGHTLY_COMMANDS and 'mv "$DB.part" "$DB"' in NIGHTLY_COMMANDS and "flock -n 9" in NIGHTLY_COMMANDS
    assert "600|400)" in NIGHTLY_COMMANDS                    # کلید با دسترسی باز پذیرفته نمی‌شود
    deletes = [line for line in NIGHTLY_COMMANDS.splitlines() if "-delete" in line]
    assert deletes and all("nightly-db-" in line and "'db-" not in line and "media-*.tar.gz'" not in line for line in deletes)
    assert "--network none" in NIGHTLY_COMMANDS and "/media:ro" in NIGHTLY_COMMANDS


def test_drill_reads_gpg_backups_with_a_key_path_and_checks_the_checksum():
    assert "backups/nightly-db-*.sql.gz.gpg" in COMMANDS and '--passphrase-file "$KEY_FILE"' in COMMANDS
    assert "sha256sum -c" in COMMANDS and "*.tar.gz.gpg)" in COMMANDS


def test_copy_to_the_owner_computer_stays_out_of_cloud_sync_and_is_verified():
    assert "*OneDrive*" in PULL and '"$REPO"*)' in PULL
    assert "sha256sum -c" in PULL and "df -Pk" in PULL
    scp = next(line for line in PULL.splitlines() if line.strip().startswith("scp "))
    assert ".gpg" not in scp or "$DB" in scp                 # فقط فایل‌های رمزشده و checksum آن‌ها
    commands = "\n".join(line for line in PULL.splitlines() if not line.lstrip().startswith("#"))
    assert not re.search(r"\b(rclone|aws|gsutil|curl|wget)\b", commands)          # هیچ بارگذاری به سرویس بیرونی
