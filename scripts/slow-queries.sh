#!/usr/bin/env bash
# گران‌ترین کوئری‌ها از pg_stat_statements (فقط خواندنی). روی سرور: cd /opt/logitrack && bash scripts/slow-queries.sh
set -euo pipefail
cd "$(dirname "$0")/.."
LIMIT="${1:-15}"
docker compose exec -T db psql -U postgres -d logitrack -c "
SELECT round(total_exec_time::numeric, 0) AS total_ms, calls, round(mean_exec_time::numeric, 1) AS mean_ms,
       rows, left(regexp_replace(query, '\s+', ' ', 'g'), 110) AS query
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = 'logitrack') AND query NOT ILIKE '%pg_stat_statements%'
ORDER BY total_exec_time DESC LIMIT ${LIMIT};"
