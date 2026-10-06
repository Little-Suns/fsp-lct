import os

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://fsp:fsp@localhost:5432/fsp")

# OpenAI-совместимый эндпоинт локальной модели (Ollama / vLLM). Пусто или недоступен → правила.
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen2.5:32b-instruct")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "bge-m3")
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "60"))

FRONTEND_DIR = os.environ.get("FRONTEND_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))

# Демо-режим (стенд для жюри): вход за демо-персонажей, код почты в ответе, мок-провайдер ФСП ID. По умолчанию выключен.
DEMO = os.environ.get("DEMO", "0") == "1"

# Письма с кодом входа. Без SMTP_HOST и вне DEMO вход по почте недоступен (503).
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "no-reply@fsp-career.local")
SMTP_STARTTLS = os.environ.get("SMTP_STARTTLS", "1") == "1"

# Серверный «перец» для HMAC кодов входа. Без него ключ случайный на процесс: коды сгорают при рестарте — для демо не страшно.
SECRET_KEY = os.environ.get("SECRET_KEY") or __import__("secrets").token_hex(32)

# Адрес, по которому браузер видит приложение: из него собираются redirect_uri ФСП ID и issuer мок-провайдера.
PUBLIC_URL = (os.environ.get("PUBLIC_URL") or "http://localhost:8000").rstrip("/")

# ФСП ID — Keycloak, OpenID Connect (Authorization Code + PKCE S256). Боевой Keycloak: FSP_ID_ISSUER=https://<host>/realms/<realm>,
# клиент (confidential) и секрет — из консоли Keycloak, redirect URI клиента — FSP_ID_REDIRECT_URI.
# FSP_ID_MOCK=1 (по умолчанию — при DEMO=1) включает встроенный мок-провайдер /mock-fsp-id; без FSP_ID_ISSUER клиент ходит в него.
MOCK_FSP_ID_ISSUER = PUBLIC_URL + "/mock-fsp-id"
_issuer = (os.environ.get("FSP_ID_ISSUER") or "").rstrip("/")
# пустое значение из compose — как не задано; рядом с боевым Keycloak мок выключен: он принял бы боевой секрет клиента
FSP_ID_MOCK = (os.environ.get("FSP_ID_MOCK") or ("1" if DEMO else "0")) == "1" and _issuer in ("", MOCK_FSP_ID_ISSUER)
FSP_ID_ISSUER = _issuer or (MOCK_FSP_ID_ISSUER if FSP_ID_MOCK else "")
FSP_ID_CLIENT_ID = os.environ.get("FSP_ID_CLIENT_ID") or "fsp-career"
# мок и клиент живут в одном процессе — для мока секрет случайный на процесс; боевой — только из окружения
FSP_ID_CLIENT_SECRET = os.environ.get("FSP_ID_CLIENT_SECRET") or (__import__("secrets").token_urlsafe(32) if FSP_ID_MOCK else "")
FSP_ID_REDIRECT_URI = os.environ.get("FSP_ID_REDIRECT_URI") or PUBLIC_URL + "/api/auth/fsp/callback"
FSP_ID_SCOPE = os.environ.get("FSP_ID_SCOPE") or "openid email profile"
