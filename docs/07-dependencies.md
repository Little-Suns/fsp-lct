# 7. Используемые библиотеки и компоненты

Раздел перечисляет всё, из чего собирается и чем проверяется решение: библиотеки бэкенда, инструменты тестирования фронта, контейнерные образы, необязательные модели и CI. Версии бэкенда — точные, из файла блокировки `backend/uv.lock` (сборка образа идёт с `uv sync --frozen`, поэтому ставятся ровно они). Лицензии библиотек — из метаданных установленных пакетов (`License-Expression` / `License` в `importlib.metadata`), лицензии образов и моделей — по данным их правообладателей.

ТЗ (п. 3.5) рекомендует открытые лицензии (MIT, Apache-2.0, BSD и аналогичные) или ПО из реестра отечественного ПО. Всё перечисленное ниже — открытое ПО; отступления от «MIT / Apache / BSD» разобраны в конце раздела.

## 7.1. Бэкенд (Python)

Версия Python — 3.12: `requires-python = ">=3.12"` в `backend/pyproject.toml`, базовый образ `python:3.12-slim` в `backend/Dockerfile`, CI гоняет тесты на 3.12. Менеджер зависимостей — `uv` (в образ копируется из `ghcr.io/astral-sh/uv:0.10`).

### Прямые зависимости (работа приложения)

| Компонент | Ограничение в `pyproject.toml` | Версия в `uv.lock` | Лицензия | Назначение |
|---|---|---|---|---|
| fastapi | ≥ 0.115 | 0.142.2 | MIT | HTTP API и автоматическая спецификация OpenAPI (`/docs`) |
| uvicorn[standard] | ≥ 0.32 | 0.54.0 | BSD-3-Clause | ASGI-сервер, один процесс (см. раздел 8) |
| sqlalchemy | ≥ 2.0 | 2.1.3 | MIT | ORM и запросы к PostgreSQL (синхронный режим) |
| psycopg[binary] | ≥ 3.2 | 3.3.6 | LGPL-3.0-only | драйвер PostgreSQL (бинарная сборка с libpq) |
| alembic | ≥ 1.20.0 | 1.20.0 | MIT | миграции схемы БД, накатываются при старте API |
| httpx | ≥ 0.27 | 0.28.1 | BSD-3-Clause | HTTP-клиент: Codeforces, CTFtime, ФСП ID (OIDC), LLM, песочница |
| pyjwt[crypto] | ≥ 2.9 | 2.15.1 | MIT | проверка подписи id_token ФСП ID по JWKS (RS256), подпись токенов мок-провайдера |
| pypdf | ≥ 5.0 | 6.19.0 | BSD-3-Clause | извлечение текста и встроенных картинок из PDF-резюме |
| fpdf2 | ≥ 2.8 | 2.8.9 | LGPL-3.0-only | генерация PDF-профиля кандидата |
| pillow | ≥ 10 | 12.3.0 | MIT-CMU (HPND) | декодирование картинок страниц скана (через `pypdf` `page.images`) и уменьшение до 1600 px перед OCR (`services/ocr.py`) |
| numpy | ≥ 2.0 | 2.5.3 | BSD-3-Clause (с вложенными 0BSD, MIT, Zlib, CC0-1.0) | IRT-расчёты, метрики валидации, синтетика |
| python-multipart | ≥ 0.0.12 | 0.0.32 | Apache-2.0 | приём файлов (резюме, протоколы) в FastAPI |
| regex | ≥ 2024.9 | 2026.9.29 | Apache-2.0 AND CNRI-Python | регулярные выражения с таймаутом сверки: автопроверка ответа на задание работодателя по шаблону (`services/autocheck.py`) |

### Существенные транзитивные зависимости

Ставятся автоматически, перечислены, потому что на них опирается заметная часть функциональности.

| Компонент | Версия | Лицензия | Откуда и зачем |
|---|---|---|---|
| starlette | 1.7.0 | BSD-3-Clause | основа FastAPI: маршрутизация, статика, SSE (`StreamingResponse`) |
| pydantic | 2.13.5 | MIT | валидация входных данных API (через FastAPI) |
| pydantic-core | 2.46.5 | MIT | ядро pydantic |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | RSA для JWT (через `pyjwt[crypto]`) |
| uvloop | 0.23.0 | MIT / Apache-2.0 | цикл событий uvicorn (`[standard]`, Linux) |
| httptools | 0.8.0 | MIT | разбор HTTP в uvicorn (`[standard]`) |
| websockets | 17.2 | BSD-3-Clause | из `uvicorn[standard]`, приложением не используется |
| watchfiles | 1.3.0 | MIT | из `uvicorn[standard]` (перезапуск при разработке) |
| python-dotenv | 1.2.4 | BSD-3-Clause | из `uvicorn[standard]` |
| pyyaml | 6.0.3 | MIT | из `uvicorn[standard]` |
| mako | 1.4.3 | MIT | шаблоны ревизий Alembic |
| fonttools | 4.66.1 | MIT | работа со шрифтами в fpdf2 |
| defusedxml | 0.7.1 | PSF | безопасный разбор XML в fpdf2 |
| greenlet | 3.5.6 | MIT AND PSF-2.0 | зависимость SQLAlchemy |
| anyio / h11 / httpcore | 4.15.1 / 0.16.0 / 1.0.9 | MIT / MIT / BSD-3-Clause | сетевой стек httpx и uvicorn |
| certifi | 2026.7.22 | MPL-2.0 | корневые сертификаты для HTTPS-запросов httpx |

Всего в `uv.lock` 79 пакетов (вместе с dev-зависимостями).

Отправка писем (`app/mail.py`, `smtplib`), HMAC и хеши (`hmac`, `hashlib`), CSV/JSON протоколов, маскировка ПДн (`re`) — стандартная библиотека Python, отдельных пакетов нет.

### Зависимости для разработки и тестов (`[dependency-groups] dev`)

В боевой образ не попадают (`uv sync --frozen --no-dev`).

| Компонент | Ограничение | Версия в `uv.lock` | Лицензия | Назначение |
|---|---|---|---|---|
| pytest | ≥ 8.0 | 9.1.1 | MIT | тесты бэкенда (`backend/tests/`) |
| pytest-cov | ≥ 7.1.0 | 7.1.0 | MIT | покрытие тестами, порог 80 % в `backend/test.sh` |
| coverage | (через pytest-cov) | 7.16.2 | Apache-2.0 | сбор и отчёт покрытия |
| locust | ≥ 2.46.7 | 2.46.7 | MIT | нагрузочный прогон `backend/loadtest/locustfile.py` |

Locust тянет за собой gevent 26.9.0 (MIT), flask 3.1.3 (BSD-3-Clause) и др. — только для нагрузочного прогона.

## 7.2. Фронтенд

Фронт — один файл `frontend/index.html` с встроенными стилями и скриптом на чистом JavaScript: без сборщика, без фреймворков и без npm-зависимостей во время работы. Внешних загрузок нет: в `index.html` нет `<script src>` и `<link>` на CDN или Google Fonts, все ресурсы лежат в `frontend/assets/` и отдаются тем же сервером.

| Ресурс | Лицензия | Где |
|---|---|---|
| Шрифт JetBrains Mono (Regular, Medium, SemiBold, Bold, woff2) | SIL Open Font License 1.1 (`OFL.txt` рядом) | `frontend/assets/fonts/` |
| Логотип, иконки, иллюстрации (`logo.svg`, `mark.png`, `icon-*.png` и т. п.) | фирменный стиль и логотип — из брендбука ФСП, предоставленного организатором (ТЗ, п. 4) | `frontend/assets/` |

`frontend/package.json` нужен только для e2e-тестов (Playwright) и замера покрытия JS; в образ `api` попадают лишь `index.html` и `assets/` (`.dockerignore` отсекает `node_modules`, `e2e`, отчёты). Требование к Node — `>=22` (`engines`).

| Компонент (devDependencies) | Ограничение | Версия в `package-lock.json` | Лицензия | Назначение |
|---|---|---|---|---|
| @playwright/test | ^1.63.0 | 1.63.0 | Apache-2.0 | e2e-сценарии кандидата и работодателя в Chromium (`frontend/e2e/`) |
| monocart-coverage-reports | ^2.13.0 | 2.13.0 | MIT | V8-покрытие inline-скрипта `index.html`, порог 80 % строк |

Транзитивные пакеты (22 в `package-lock.json`): playwright и playwright-core 1.63.0 (Apache-2.0), istanbul-lib-* (BSD-3-Clause), acorn (MIT), semver и signal-exit (ISC), foreground-child (BlueOak-1.0.0) и другие под MIT. Браузер Chromium ставится командой `npx playwright install chromium`.

## 7.3. Шрифты PDF-профиля (бэкенд)

| Ресурс | Лицензия | Где |
|---|---|---|
| JetBrains Mono (Regular, Bold, ttf) | SIL OFL 1.1 (`OFL.txt`) | `backend/app/assets/fonts/` |
| DejaVu Sans — запасные глифы (арабица, грузинский, часть эмодзи) | лицензия Bitstream Vera / Arev, изменения DejaVu — public domain (`DejaVu-LICENSE.txt`) | `backend/app/assets/fonts/` |

## 7.4. Инфраструктура: контейнеры

Сервисы описаны в `docker-compose.yml`, подробности запуска — в разделе 8.

| Компонент | Версия (тег) | Лицензия | Где используется |
|---|---|---|---|
| PostgreSQL | `postgres:16-alpine` | PostgreSQL License | сервис `db`; та же версия — service-контейнер в CI |
| Python (образ API) | `python:3.12-slim` (Debian) | PSF License | `backend/Dockerfile`, сервис `api` |
| uv | `ghcr.io/astral-sh/uv:0.10` | MIT / Apache-2.0 | установка зависимостей при сборке образа `api` |
| nsjail | ветка/тег `3.4` репозитория `github.com/google/nsjail`, собирается из исходников | Apache-2.0 | `sandbox/Dockerfile`, этап `nsjail`: изоляция каждого запуска кода кандидата |
| Debian | `debian:bookworm-slim` | свободные лицензии Debian | этап сборки nsjail |
| Node.js | `node:22-bookworm-slim` (Node 22) | MIT | сервис `sandbox`: исполнение TypeScript (`--experimental-strip-types`) |
| Python в песочнице | `python3` из Debian bookworm (3.11) | PSF License | сервис `sandbox`: HTTP-сервер песочницы на stdlib и исполнение решений на Python |
| libprotobuf32, libnl-route-3-200 | пакеты Debian bookworm | BSD-3-Clause / LGPL-2.1 | библиотеки времени выполнения nsjail |

Сервер песочницы (`sandbox/server.py`, `harness.py`, `harness.mts`) написан на стандартной библиотеке Python и Node без сторонних пакетов. Тестовый этап образа песочницы (`--target test`) добавляет `python3-pytest` из Debian.

Теги образов не закреплены по дайджесту, а nsjail клонируется по тегу `3.4` без фиксации коммита: пересборка через полгода может взять более новый патч-релиз базового образа. Для воспроизводимости боевой сборки теги стоит закрепить (`image@sha256:…`) — это доводка за рамками MVP.

## 7.5. Необязательные модели (LLM, эмбеддинги, OCR)

По умолчанию (`LLM_PROVIDER=none`, `OCR_URL` пустой) ни одна модель не используется и не скачивается — работают правила (подробно — раздел 10). Если провайдер включён, имена моделей по умолчанию заданы пресетами в `backend/app/config.py`; клиент — OpenAI-совместимый HTTP через httpx (`backend/app/services/llm.py`), отдельной SDK-библиотеки нет.

| Провайдер / назначение | Модель по умолчанию | Лицензия модели | Где задаётся |
|---|---|---|---|
| `ollama`, чат (разбор текста, реранк) | `mistral:7b` | Apache-2.0 | `LLM_MODEL` |
| `ollama`, эмбеддинги | `bge-m3` | MIT | `EMBED_MODEL` |
| `yandexgpt`, чат / эмбеддинги | `yandexgpt-lite/latest` / `text-search-doc/latest` | облачный сервис Yandex AI Studio (по договору) | `LLM_MODEL` / `EMBED_MODEL` |
| `gigachat`, чат / эмбеддинги | `GigaChat` / `Embeddings` | облачный сервис Сбера (по договору) | `LLM_MODEL` / `EMBED_MODEL` |
| `openai_compatible` (vLLM и т. п.) | не задана — указывается явно | по выбранной модели | `LLM_BASE_URL`, `LLM_MODEL`, `EMBED_MODEL` |
| OCR сканов резюме (свой vLLM) | `Qwen/Qwen2.5-VL-7B-Instruct` | Apache-2.0 | `OCR_URL`, `OCR_MODEL` |

Ollama и vLLM в `docker-compose.yml` не входят: их поднимают отдельно (Ollama — на хосте, адрес `OLLAMA_URL`; vLLM — свой сервер с GPU).

## 7.6. CI (GitHub Actions)

Файл `.github/workflows/ci.yml`; запускается на каждый PR и на пуш в `main`, e2e — только вручную.

| Компонент | Версия | Где |
|---|---|---|
| Раннер | `ubuntu-latest` | все задачи |
| actions/checkout | v4 | все задачи |
| astral-sh/setup-uv | v6, Python 3.12 | `backend`, `frontend-e2e` |
| actions/setup-node | v4, Node 22 | `frontend-syntax`, `frontend-e2e` |
| actions/upload-artifact | v4 | отчёты покрытия и Playwright |
| PostgreSQL (service-контейнер) | `postgres:16-alpine` | `backend`, `frontend-e2e` |
| Docker / Docker Compose раннера | версии раннера GitHub | `sandbox` (тесты против настоящего nsjail, privileged), `frontend-e2e` (песочница для e2e) |

## 7.7. Лицензионная чистота и открытые вопросы

- **Лицензия самого проекта не указана**: файла `LICENSE` в корне репозитория нет. Код открыт (публичный репозиторий `github.com/Little-Suns/fsp-lct`, без компиляции и обфускации — как требует п. 3.5), но условия использования формально не заданы. Это открытый хвост: нужно выбрать лицензию (например, MIT или Apache-2.0, совместимые со всеми зависимостями) и положить `LICENSE` в корень.
- **LGPL-3.0: psycopg и fpdf2.** Это не «MIT / Apache / BSD», но LGPL разрешает использовать библиотеку в приложении под любой лицензией, если библиотека подключается как отдельный модуль и её можно заменить: обе ставятся из PyPI как есть, без изменений и без статической сборки в наш код. Ограничений на открытие нашего кода это не накладывает. Если потребуется строго пермиссивный набор: альтернатива psycopg — psycopg2 тоже LGPL, поэтому реальная замена — asyncpg (Apache-2.0) с переходом SQLAlchemy на async; fpdf2 можно заменить на reportlab (BSD).
- **Прочие нестандартные лицензии** — пермиссивные: MIT-CMU (Pillow, разновидность HPND), PSF (defusedxml, Python), MPL-2.0 (certifi — набор сертификатов, файловый copyleft не затрагивает наш код), CNRI-Python (часть кода `regex`), ISC и BlueOak-1.0.0 (транзитивные пакеты тестов фронта), SIL OFL 1.1 (шрифты).
- **Отечественные облачные LLM** (YandexGPT, GigaChat) — внешние сервисы, а не встраиваемое ПО; подключаются только по желанию и по договору с провайдером. По умолчанию выключены.
