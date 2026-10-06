from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import catalog, config, deps
from app.db import init_db
from app.routers import achievements, candidate, chat, employer, lottery, quest, tasks, vacancies, validation


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

for r in (deps, candidate, employer, quest, achievements, lottery, validation, vacancies, tasks, chat):
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
        "competencies": catalog.COMPETENCIES,
        "skills": sorted(catalog.SKILLS),
        "cap": catalog.CANDIDATE_CAP,
        "invite_ttl_days": catalog.INVITE_TTL_DAYS,
        "fork_max_width": catalog.FORK_MAX_WIDTH,
    }


# фронт раздаётся тем же сервером, чтобы не возиться с CORS; монтируется последним
# наружу — только страница и ассеты: в frontend/ лежат ещё node_modules, e2e и отчёты тестов
_front = Path(config.FRONTEND_DIR)
if (_front / "index.html").is_file():
    app.mount("/assets", StaticFiles(directory=_front / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(_front / "index.html")
