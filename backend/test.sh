#!/bin/sh
# Каждый набор тестов пересоздаёт схему в своей базе — так они не мешают друг другу и демо-базе fsp.
set -e
cd "$(dirname "$0")"
PG=${PG:-postgresql+psycopg://fsp:fsp@localhost:5432}
uv run python - <<'PY'
import psycopg
c = psycopg.connect("postgresql://fsp:fsp@localhost:5432/fsp", autocommit=True)
have = {r[0] for r in c.execute("SELECT datname FROM pg_database")}
for n in ("fsp_flows", "fsp_quest", "fsp_integ", "fsp_seed", "fsp_valid"):
    if n not in have:
        c.execute(f"CREATE DATABASE {n}")
PY
for t in flows:test_flows quest:test_quest integ:test_integrations seed:test_lottery valid:test_validation; do
  DEMO=1 DATABASE_URL=$PG/fsp_${t%%:*} uv run pytest -q "tests/${t##*:}.py"
done
