#!/bin/sh
# Бэкенд для e2e: своя база (по умолчанию fsp_e2e), пересев на каждый прогон, DEMO=1, без LLM (правила — детерминированно).
# Демо-база fsp здесь не используется никогда.
set -e
cd "$(dirname "$0")/../../backend"
PG=${PG:-postgresql+psycopg://fsp:fsp@localhost:5432}
DB=${E2E_DB:-fsp_e2e}
PORT=${E2E_PORT:-8010}
if [ "$DB" = fsp ]; then echo "e2e не запускается на демо-базе fsp" >&2; exit 1; fi
uv run python - "$DB" "$PG" <<'PY'
import sys, psycopg
c = psycopg.connect(sys.argv[2].replace("+psycopg", "") + "/fsp", autocommit=True)
if not c.execute("SELECT 1 FROM pg_database WHERE datname = %s", (sys.argv[1],)).fetchone():
    c.execute(f'CREATE DATABASE "{sys.argv[1]}"')
PY
export DATABASE_URL="$PG/$DB" DEMO=1 LLM_BASE_URL=
uv run python -m seed.generate --reset --candidates 200 --needs 20 > /dev/null
exec uv run uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
