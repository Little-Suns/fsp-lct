"""OCR скана резюме: картинки страниц PDF → текст vision-моделью (по умолчанию Qwen2.5-VL-7B-Instruct) на своём vLLM.

Протокол — OpenAI-совместимый `/chat/completions` с `image_url` (base64), конфиг отдельный от LLM_PROVIDER (`config.OCR_*`).
Скан уходит в модель неотмаскированным — на картинке ФИО и контакты не замазать, — поэтому `OCR_URL` только self-hosted
(152-ФЗ). Распознанный текст дальше идёт обычным путём: `parse_cv` маскирует ПДн перед любым вызовом LLM.
Любой сбой (модель недоступна, таймаут, пустой ответ) → None, вызывающий отвечает 422. В логи — только тип ошибки и код.
"""

import base64
import io
import logging
import time

import httpx
from pypdf import PdfReader

from app import config

log = logging.getLogger(__name__)
MAX_PAGES = 4  # резюме — 1–2 страницы; дальше не распознаём (и не держим запрос минутами)
MAX_IMAGES_PER_PAGE = 4  # декодируем не больше стольких картинок страницы — защита от PDF из тысячи мелких картинок
MAX_SIDE = 1600  # px по длинной стороне: текст резюме читается, картинка ~1,5–2 тыс. токенов у Qwen2.5-VL
MIN_SIDE = 300  # меньше — логотип или фото, а не страница
MAX_TOKENS = 2048  # ответ на страницу
PROMPT = ("Перепиши весь текст с изображения страницы резюме как есть, на языке оригинала, сохраняя переносы строк. "
          "Без комментариев, пояснений и разметки.")


def enabled() -> bool:
    return bool(config.OCR_URL)


def page_images(data: bytes) -> list[bytes]:
    """По самой большой картинке на страницу, JPEG не больше MAX_SIDE по длинной стороне.
    Распаковку потоков ограничивает pypdf (75 МБ), размер картинки в пикселях — Pillow (DecompressionBombError)."""
    # ponytail: берём встроенные растровые картинки страницы (page.images) — так устроен типичный скан, без рендера страницы.
    # Не распознаются: текст в кривых (вектор), страница из нескольких тайлов (берём один, самый большой), форматы, которые
    # pypdf/Pillow не декодируют (JBIG2 без jbig2dec, часть CCITT). Расширять — рендер страницы (pypdfium2) вместо извлечения.
    out = []
    for page in PdfReader(io.BytesIO(data)).pages[:MAX_PAGES]:
        best = None
        for i in range(min(len(page.images), MAX_IMAGES_PER_PAGE)):
            try:
                img = page.images[i].image
            except Exception as e:  # noqa: BLE001 — pypdf и Pillow бросают десяток типов на битых и экзотических картинках
                log.info("OCR: картинка страницы не декодируется (%s)", type(e).__name__)
                continue
            if img is not None and min(img.size) >= MIN_SIDE and (best is None or img.width * img.height > best.width * best.height):
                best = img
        if best is None:
            continue
        best = best.convert("RGB")  # CMYK, палитра, 1 бит → JPEG
        best.thumbnail((MAX_SIDE, MAX_SIDE))
        buf = io.BytesIO()
        best.save(buf, "JPEG", quality=85)
        out.append(buf.getvalue())
    return out


def _page_text(jpeg: bytes, timeout: float) -> str:
    body = {
        "model": config.OCR_MODEL,
        "temperature": 0,
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()}},
            {"type": "text", "text": PROMPT},
        ]}],
    }
    headers = {"Authorization": f"Bearer {config.OCR_API_KEY}"} if config.OCR_API_KEY else {}
    r = httpx.post(config.OCR_URL.rstrip("/") + "/chat/completions", json=body, headers=headers, timeout=timeout)
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    return content.strip() if isinstance(content, str) else ""


def recognize(data: bytes) -> str | None:
    """Текст скана или None (OCR выключен, картинок нет, модель недоступна, не успела за OCR_TIMEOUT или ответила пусто).
    Страницы — по одной в запросе (у vLLM по умолчанию одна картинка на промпт), под общим сроком на документ."""
    if not enabled():
        return None
    try:
        images = page_images(data)
    except Exception as e:  # noqa: BLE001 — PDF уже прочитан при извлечении текста; сюда — только экзотика pypdf
        log.warning("OCR: не удалось достать картинки (%s)", type(e).__name__)
        return None
    if not images:
        return None
    deadline = time.monotonic() + config.OCR_TIMEOUT
    parts = []
    try:
        for jpeg in images:
            left = deadline - time.monotonic()
            if left <= 0:
                raise httpx.TimeoutException("общий срок OCR истёк")
            parts.append(_page_text(jpeg, left))
    # ValueError — не JSON; KeyError/IndexError/TypeError — неожиданная форма ответа
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as e:
        status = getattr(getattr(e, "response", None), "status_code", "")  # только тип и код: текст скана и ответа в лог не идёт
        log.warning("OCR недоступен (%s %s)", type(e).__name__, status)
        return None
    return "\n".join(p for p in parts if p) or None
