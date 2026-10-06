import os

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://fsp:fsp@localhost:5432/fsp")

# OpenAI-совместимый эндпоинт локальной модели (Ollama / vLLM). Пусто или недоступен → правила.
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen2.5:32b-instruct")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "bge-m3")
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "60"))

FRONTEND_DIR = os.environ.get("FRONTEND_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))

# Демо-режим (стенд для жюри): вход за демо-персонажей, код почты в ответе, ФСП ID без OAuth. По умолчанию выключен.
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

# Песочница задач на код (сервис sandbox в compose, только внутренняя сеть). Пусто — задачи на код не выдаются.
SANDBOX_URL = os.environ.get("SANDBOX_URL", "").rstrip("/")
SANDBOX_TOKEN = os.environ.get("SANDBOX_TOKEN", "")  # общий секрет API ↔ песочница (заголовок X-Sandbox-Token)
SANDBOX_TIMEOUT = float(os.environ.get("SANDBOX_TIMEOUT", "90"))  # очередь песочницы ≤ 20 с + прогон ≤ 60 с
SANDBOX_API_SLOTS = int(os.environ.get("SANDBOX_API_SLOTS", "8"))  # одновременных обращений API к песочнице (пул FastAPI — 40 потоков)
