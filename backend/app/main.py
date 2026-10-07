from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import catalog, config, deps
from app.db import init_db
from app.integrations import fsp_id as fsp_id_client
from app.routers import achievements, candidate, chat, employer, fsp_id, lottery, mock_fsp_id, quest, tasks, vacancies, validation
from app.services import sandbox


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="ФСП Карьера API", lifespan=lifespan)
MAX_BODY = 6 * 1024 * 1024  # резюме до 5 МБ + запас


@app.middleware("http")
async def limit_body(request: Request, call_next):
    # ponytail: проверяется только Content-Length; chunked без длины режет reverse proxy (client_max_body_size)
    if int(request.headers.get("content-length") or 0) > MAX_BODY:
        return JSONResponse({"detail": "Слишком большой запрос"}, status_code=413)
    return await call_next(request)

for r in (deps, fsp_id, mock_fsp_id, candidate, employer, quest, achievements, lottery, validation, vacancies, tasks, chat):
    app.include_router(r.router)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/meta")
def meta():
    """Справочники для форм фронта."""
    return {
        "specs": catalog.SPECS,
        "tracks": catalog.TRACKS,
        "grades": catalog.GRADES,
        "grade_th": catalog.GRADE_TH,
        "formats": catalog.FORMATS,
        "decline_reasons": catalog.DECLINE_REASONS,
        "feedback": catalog.FEEDBACK,
        "company_feedback": catalog.COMPANY_FEEDBACK,
        "competencies": catalog.COMPETENCIES,
        "skills": sorted(catalog.SKILLS),
        "roles": list(catalog.ROLES),
        "soft_skills": list(catalog.SOFT_SKILLS),
        "cap": catalog.CANDIDATE_CAP,
        "invite_ttl_days": catalog.INVITE_TTL_DAYS,
        "fork_max_width": catalog.FORK_MAX_WIDTH,
        "code_tasks": sandbox.enabled(),  # в тесте есть задача на код (песочница настроена)
        "fsp_id": fsp_id_client.enabled(),  # кнопка «Войти через ФСП ID»
        "fsp_idps": [{"alias": a, "label": l} for a, l in config.FSP_ID_IDPS.items()] if fsp_id_client.enabled() else [],  # брокер Keycloak
        "demo": config.DEMO,  # кнопка «Запустить прогон» на /v
    }


# фронт раздаётся тем же сервером, чтобы не возиться с CORS; монтируется последним
# наружу — только страница и ассеты: в frontend/ лежат ещё node_modules, e2e и отчёты тестов
_front = Path(config.FRONTEND_DIR)
if (_front / "index.html").is_file():
    app.mount("/assets", StaticFiles(directory=_front / "assets"), name="assets")


# маршрут есть всегда, файл проверяется на каждый запрос: исчезнувший каталог даёт 503, а не 500 из FileResponse
@app.get("/", include_in_schema=False)
def index():
    page = _front / "index.html"
    if not page.is_file():
        raise HTTPException(503, f"Фронт недоступен: нет файла {page}. Пересоберите образ api (docker compose up -d --build) или задайте FRONTEND_DIR.")
    return FileResponse(page)
