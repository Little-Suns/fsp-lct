import os

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://fsp:fsp@localhost:5432/fsp")

# LLM необязательна: без неё всё работает на правилах. Провайдер — LLM_PROVIDER:
#   none — только правила (по умолчанию; стенд жюри без GPU и без ключей);
#   ollama — локальная модель на CPU (по умолчанию mistral:7b), данные не покидают инфраструктуру;
#   openai_compatible — любой OpenAI-совместимый шлюз (vLLM и т. п.), LLM_BASE_URL обязателен;
#   yandexgpt — Yandex AI Studio (Foundation Models), OpenAI-совместимый API: LLM_API_KEY + YANDEX_FOLDER_ID;
#   gigachat — GigaChat API (Сбер): ключ авторизации GIGACHAT_AUTH_KEY → OAuth-токен на 30 мин.
# Тексты резюме и потребностей уходят в модель только после маскировки ПДн (parsing.mask_pii).
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "none").strip().lower()
_LLM_PRESETS = {  # провайдер → (адрес API, модель чата, модель эмбеддингов)
    "ollama": (os.environ.get("OLLAMA_URL", "http://localhost:11434/v1"), "mistral:7b", "bge-m3"),
    "openai_compatible": ("", "", ""),
    "yandexgpt": ("https://llm.api.cloud.yandex.net/v1", "yandexgpt-lite/latest", "text-search-doc/latest"),
    "gigachat": ("https://gigachat.devices.sberbank.ru/api/v1", "GigaChat", "Embeddings"),
}
_base, _model, _embed = _LLM_PRESETS.get(LLM_PROVIDER, ("", "", ""))
# пустое значение в окружении (compose передаёт ${X:-}) = «взять из пресета»
LLM_BASE_URL = os.environ.get("LLM_BASE_URL") or _base
LLM_MODEL = os.environ.get("LLM_MODEL") or _model
EMBED_MODEL = os.environ.get("EMBED_MODEL") or _embed
if EMBED_MODEL.lower() in ("none", "off"):  # эмбеддинги выключены — кандидаты ищутся по навыкам
    EMBED_MODEL = ""
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT") or "60")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")  # openai_compatible — Bearer (если нужен), yandexgpt — API-ключ сервисного аккаунта
YANDEX_FOLDER_ID = os.environ.get("YANDEX_FOLDER_ID", "")  # каталог Yandex Cloud: модель gpt://<каталог>/<LLM_MODEL>
GIGACHAT_AUTH_KEY = os.environ.get("GIGACHAT_AUTH_KEY", "")  # «ключ авторизации» из личного кабинета (base64 client_id:secret)
GIGACHAT_SCOPE = os.environ.get("GIGACHAT_SCOPE") or "GIGACHAT_API_PERS"  # GIGACHAT_API_B2B / GIGACHAT_API_CORP для юрлиц
GIGACHAT_OAUTH_URL = os.environ.get("GIGACHAT_OAUTH_URL") or "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
# доп. корневые сертификаты (GigaChat — «Russian Trusted Root CA» Минцифры): добавляются к системным, проверка TLS не отключается
LLM_CA_BUNDLE = os.environ.get("LLM_CA_BUNDLE", "")

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
