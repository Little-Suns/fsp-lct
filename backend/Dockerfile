# контекст сборки — корень репозитория (compose: build.context: .)
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /bin/uv
WORKDIR /srv/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ .
# фронт — в образе, а не томом с хоста: пересозданный каталог на хосте не оставляет контейнер без index.html
COPY frontend/index.html /srv/frontend/index.html
COPY frontend/assets /srv/frontend/assets
ENV PATH=/srv/backend/.venv/bin:$PATH FRONTEND_DIR=/srv/frontend
# uvicorn берёт число процессов из WEB_CONCURRENCY; больше одного нельзя — SSE чата и троттлинг внешних API в памяти процесса
ENV WEB_CONCURRENCY=1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
