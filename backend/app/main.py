import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import catalog, config, deps
from app.api_schemas import ERROR_RESPONSES
from app.db import SessionLocal, init_db
from app.integrations import fsp_id as fsp_id_client
from app.routers import achievements, candidate, chat, employer, fsp_id, lottery, mock_fsp_id, quest, tasks, vacancies, validation
from app.services import items, sandbox


log = logging.getLogger("uvicorn.error")  # логгер uvicorn: сообщение видно в выводе сервера без настройки logging


def startup() -> None:
    """Миграции, затем банк заданий: на новом стенде без засева тест иначе отвечает 503 «Банк заданий пуст».
    seed_items идемпотентен (повторный старт ничего не меняет) и приводит засеянный банк к текущим шаблонам —
    так изменённые задания доезжают на стенд с каждой выкладкой без ручного python -m app.services.items."""
    init_db()
    with SessionLocal() as db:
        if n := items.seed_items(db):
            log.info("Банк заданий: добавлено и обновлено %d заданий", n)


@asynccontextmanager
async def lifespan(_: FastAPI):
    startup()
    yield


app = FastAPI(title="ФСП Карьера API", lifespan=lifespan, responses=ERROR_RESPONSES)
MAX_BODY = 6 * 1024 * 1024  # резюме до 5 МБ + запас


@app.middleware("http")
async def limit_body(request: Request, call_next):
    # ponytail: проверяется только Content-Length; chunked без длины режет reverse proxy (client_max_body_size)
    if int(request.headers.get("content-length") or 0) > MAX_BODY:
        return JSONResponse({"detail": "Слишком большой запрос"}, status_code=413)
    return await call_next(request)


# заголовки безопасности на каждый ответ (объявлен после limit_body — внешний, 413 тоже получает; 500 из ServerErrorMiddleware — нет);
# роутер, поставивший свой (no-referrer у ФСП ID), не перетирается
SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",  # кликджекинг: чужой сайт не встроит кабинет и не подставит «Принять и открыть контакты»
    "Content-Security-Policy": "frame-ancestors 'none'",  # ponytail: только запрет фреймов; полный CSP — с хэшем inline-скрипта (table.md)
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",  # адреса кабинетов с id не уходят на чужие сайты
}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    r = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        r.headers.setdefault(k, v)
    return r

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
        "mail": bool(config.SMTP_HOST),  # письма о приглашениях уходят: без SMTP фронт их не обещает
        # сюжет теста по специализации — вводная и финал на фронте; часы сцен подставляет /api/quest
        "stories": {spec: {k: v for k, v in st.items() if k != "clock"} for spec, st in items.STORY.items()},
    }


# фронт раздаётся тем же сервером, чтобы не возиться с CORS; монтируется последним
# наружу — только страница и ассеты: в frontend/ лежат ещё node_modules, e2e и отчёты тестов
_front = Path(config.FRONTEND_DIR)
if (_front / "index.html").is_file():
    app.mount("/assets", StaticFiles(directory=_front / "assets"), name="assets")


# маршрут есть всегда, файл проверяется на каждый запрос: исчезнувший каталог даёт 503, а не 500 из FileResponse.
# Страница — и на адресах кабинетов (маршруты фронта через History API): только явные префиксы, без catch-all —
# опечатка в /api/…, /docs и /mock-fsp-id по-прежнему отвечают своим 404, а не страницей
@app.get("/", include_in_schema=False)
@app.get("/v", include_in_schema=False)
@app.get("/org", include_in_schema=False)  # импорт протоколов организатором
@app.get("/candidate", include_in_schema=False)
@app.get("/candidate/{rest:path}", include_in_schema=False)
@app.get("/employer", include_in_schema=False)
@app.get("/employer/{rest:path}", include_in_schema=False)
def index(rest: str = ""):  # rest — хвост адреса кабинета: роутинг на фронте, сервер его не читает
    page = _front / "index.html"
    if not page.is_file():
        raise HTTPException(503, f"Фронт недоступен: нет файла {page}. Пересоберите образ api (docker compose up -d --build) или задайте FRONTEND_DIR.")
    return FileResponse(page)
