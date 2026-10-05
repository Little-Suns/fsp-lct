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
