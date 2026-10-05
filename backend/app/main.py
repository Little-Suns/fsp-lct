from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import catalog, config, deps
from app.db import init_db
from app.routers import achievements, candidate, employer, lottery, quest, validation


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="ФСП Карьера API", lifespan=lifespan)

for r in (deps, candidate, employer, quest, achievements, lottery, validation):
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
if Path(config.FRONTEND_DIR).is_dir():
    app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
