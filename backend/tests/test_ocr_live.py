"""Живой смоук OCR: только с LIVE_LLM=1 и OCR_URL, по умолчанию пропускается (в CI модели нет). Свой vLLM с vision-моделью:

    vllm serve Qwen/Qwen2.5-VL-7B-Instruct --max-model-len 8192
    cd backend && LIVE_LLM=1 OCR_URL=http://localhost:8000/v1 uv run pytest -q -s tests/test_ocr_live.py

Рисует синтетическое резюме картинкой (без текстового слоя), распознаёт его и разбирает правилами. Печатает время. БД не нужна.
"""

import os
import time

import pytest

if os.environ.get("LIVE_LLM") != "1" or not os.environ.get("OCR_URL"):
    pytest.skip("живой смоук OCR — только с LIVE_LLM=1 и OCR_URL", allow_module_level=True)

from fpdf import FPDF  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from app import config  # noqa: E402
from app.services import ocr, profile_pdf  # noqa: E402
from app.services.parsing import parse_cv  # noqa: E402

LINES = [  # синтетика, реальных ПДн нет
    "Смирнов Пётр Ильич",
    "p.smirnov@example.ru · @psmirnov_dev",
    "Backend-разработчик, опыт 4 года",
    "2021 — н.в. ООО «Волна», Go-разработчик",
    "Go, PostgreSQL, Redis, Kafka, Docker",
]


def _scan() -> bytes:
    img = Image.new("L", (1240, 1754), 255)
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(profile_pdf.FONTS / "DejaVuSans.ttf"), 36)
    for i, line in enumerate(LINES):
        draw.text((100, 120 + i * 70), line, fill=0, font=font)
    pdf = FPDF(unit="pt", format=(612, 792))
    pdf.add_page()
    pdf.image(img, x=0, y=0, w=612, h=792)
    return bytes(pdf.output())


def test_live_ocr_scan():
    t0 = time.monotonic()
    text = ocr.recognize(_scan())
    dt = time.monotonic() - t0
    print(f"\nOCR: {len(text or '')} символов за {dt:.1f} с ({config.OCR_MODEL})")
    assert text and "PostgreSQL" in text
    cv = parse_cv(text)
    assert {"Go", "PostgreSQL", "Redis"} <= set(cv["skills"]) and cv["contacts"]["email"] == "p.smirnov@example.ru"
