#!/bin/sh
# Каждый набор тестов пересоздаёт схему в своей базе — так они не мешают друг другу и демо-базе fsp.
# Покрытие копится по всем наборам (--cov-append) и в конце проверяется порог.
set -e
cd "$(dirname "$0")"
export PG=${PG:-postgresql+psycopg://fsp:fsp@localhost:5432}
COV_MIN=${COV_MIN:-80}
# набор → своя база (fsp_<префикс>); test_llm_parsing, test_selfchecks и test_bank базу не трогают
# tests/test_llm_live.py — живой смоук модели, только вручную с LIVE_LLM=1 (без модели pytest вернул бы 5 — «нечего гонять»)
SUITES="flows:test_flows quest:test_quest integ:test_integrations seed:test_lottery valid:test_validation vac:test_vacancies_tasks
auth:test_auth priv:test_privacy gen:test_seed migr:test_migrations flows:test_llm_parsing flows:test_selfchecks chat:test_chat fspid:test_fsp_id
flows:test_bank code:test_code"
uv run python - <<'PY'
import os
import psycopg
c = psycopg.connect(os.environ["PG"].replace("+psycopg", "") + "/fsp", autocommit=True)  # служебная база для CREATE DATABASE
# базы пересоздаются каждый прогон: наборы на create_all не удаляют устаревшие колонки, и старая схема валит тесты
# fsp_validtest, fsp_validday — свои базы засева в test_validation
for n in ("fsp_flows", "fsp_quest", "fsp_integ", "fsp_seed", "fsp_valid", "fsp_validtest", "fsp_validday", "fsp_vac", "fsp_auth", "fsp_priv",
          "fsp_gen", "fsp_migr", "fsp_chat", "fsp_fspid", "fsp_code"):
    c.execute(f"DROP DATABASE IF EXISTS {n} WITH (FORCE)")
    c.execute(f"CREATE DATABASE {n}")
PY
uv run coverage erase
for t in $SUITES; do
  DEMO=1 DATABASE_URL=$PG/fsp_${t%%:*} uv run pytest -q --cov --cov-append --cov-report= "tests/${t##*:}.py"
done
uv run coverage report -m --fail-under="$COV_MIN"
