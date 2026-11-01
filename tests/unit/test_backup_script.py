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
