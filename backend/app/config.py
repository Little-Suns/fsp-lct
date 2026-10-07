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

# Песочница задач на код (сервис sandbox в compose, только внутренняя сеть). Пусто — задачи на код не выдаются.
SANDBOX_URL = os.environ.get("SANDBOX_URL", "").rstrip("/")
SANDBOX_TOKEN = os.environ.get("SANDBOX_TOKEN", "")  # общий секрет API ↔ песочница (заголовок X-Sandbox-Token)
SANDBOX_TIMEOUT = float(os.environ.get("SANDBOX_TIMEOUT", "90"))  # очередь песочницы ≤ 20 с + прогон ≤ 60 с
SANDBOX_API_SLOTS = int(os.environ.get("SANDBOX_API_SLOTS", "8"))  # одновременных обращений API к песочнице (пул FastAPI — 40 потоков)
