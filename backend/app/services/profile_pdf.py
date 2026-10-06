"""PDF-профиль кандидата: категория, компетенции, навыки, роли и софт-скиллы, опыт, достижения, ожидания.

Это документ самого кандидата (его право на доступ к своим данным) — с ФИО и контактами; работодателю он не
отдаётся. Фирменный шрифт — JetBrains Mono из брендбука (TTF рядом, OFL), в PDF вшивается подмножество глифов.
"""

import re
from datetime import UTC, datetime
from pathlib import Path

from fpdf import FPDF

from app.models import Candidate
from app.services import matching
from app.services.parsing import cv_experience

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
BLUE, INK, INK2, LINE, MIST = (64, 47, 255), (27, 28, 33), (74, 75, 85), (200, 201, 202), (237, 235, 255)
THETA_MIN, THETA_MAX = -3.0, 3.0  # шкала полос компетенций
SOURCES = {"fsp": "ФСП", "hackathon": "Хакатон", "ctftime": "CTFtime", "codeforces": "Codeforces"}


def dec(v: float, n: int = 2) -> str:
    return f"{v:.{n}f}".replace(".", ",")


def rub(v: int) -> str:
    return f"{v:,}".replace(",", " ") + " ₽"


def upper1(s: str) -> str:
    """Заглавная только первая буква и только кириллица/латиница: θ остаётся θ, остальной регистр не трогаем."""
    return s[:1].upper() + s[1:] if re.match(r"[а-яёa-z]", s) else s


def day(dt: datetime | None) -> str:
    return dt.strftime("%d.%m.%Y") if dt else "—"


class _Doc(FPDF):
    def __init__(self, pid: str, generated: datetime):
        super().__init__(format="A4")
        self.pid, self.generated = pid, generated
        self.add_font("mono", "", FONTS / "JetBrainsMono-Regular.ttf")
        self.add_font("mono", "B", FONTS / "JetBrainsMono-Bold.ttf")
        self.set_margins(16, 16, 16)
        self.set_auto_page_break(True, 18)
        self.set_title(f"Профиль кандидата {pid}")
        self.set_creator("ФСП Карьера")

    def header(self):
        self.set_font("mono", "B", 9)
        self.set_text_color(*BLUE)
        self.cell(0, 5, "ФСП КАРЬЕРА")
        self.set_font("mono", "", 8)
        self.set_text_color(*INK2)
        self.set_x(self.l_margin)
        self.cell(0, 5, f"Профиль кандидата · {self.pid}", align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*BLUE)
        self.set_line_width(0.6)
        self.line(self.l_margin, self.get_y() + 1, self.w - self.r_margin, self.get_y() + 1)
        self.ln(6)

    def footer(self):
        self.set_y(-13)
        self.set_font("mono", "", 7)
        self.set_text_color(*INK2)
        self.cell(0, 4, f"Сформировано {day(self.generated)} · ФСП Карьера", new_x="LMARGIN")
        self.cell(0, 4, f"{self.page_no()} / {{nb}}", align="R")

    def section(self, title: str, note: str | None = None):
        if self.get_y() > self.h - 50:  # заголовок не остаётся один внизу страницы
            self.add_page()
        self.ln(3)
        self.set_font("mono", "B", 10)
        self.set_text_color(*INK)
        self.cell(self.get_string_width(title) + 3, 6, title)
        if note:
            self.set_font("mono", "", 7)
            self.set_text_color(*INK2)
            self.cell(0, 6, note)
        self.ln(7)

    def para(self, s: str, size: float = 8.5, color=INK2, bold: bool = False, h: float = 4.6):
        self.set_font("mono", "B" if bold else "", size)
        self.set_text_color(*color)
        self.multi_cell(0, h, s, new_x="LMARGIN", new_y="NEXT")

    def chips(self, items: list[str], fill=MIST):
        """Ярлыки в строку с переносом."""
        self.set_font("mono", "", 8)
        self.set_text_color(*INK)
        self.set_fill_color(*fill)
        x0, right = self.l_margin, self.w - self.r_margin
        for s in items:
            w = self.get_string_width(s) + 5
            if self.get_x() + w > right and self.get_x() > x0:
                self.ln(7)
            self.cell(w, 5.5, s, fill=True, align="C")
            self.set_x(self.get_x() + 2)
        self.ln(8)

    def comp_rows(self, comps: list[dict]):
        """Компетенция: название, полоса погрешности θ ± SE и точка θ на шкале [−3; 3], число."""
        label_w, bar_w = 62, 80
        for c in comps:
            if self.get_y() > self.h - 26:
                self.add_page()
            y = self.get_y()
            self.set_font("mono", "", 8)
            self.set_text_color(*INK)
            self.cell(label_w, 5, c["n"][:34])
            x0 = self.get_x() + 2
            pos = lambda v: x0 + bar_w * (min(max(v, THETA_MIN), THETA_MAX) - THETA_MIN) / (THETA_MAX - THETA_MIN)  # noqa: E731
            self.set_draw_color(*LINE)
            self.set_line_width(0.3)
            self.line(x0, y + 2.5, x0 + bar_w, y + 2.5)
            self.set_fill_color(*MIST)
            self.rect(pos(c["t"] - c["se"]), y + 1, max(pos(c["t"] + c["se"]) - pos(c["t"] - c["se"]), 0.5), 3, style="F")
            self.set_fill_color(*BLUE)
            self.ellipse(pos(c["t"]) - 1.2, y + 1.3, 2.4, 2.4, style="F")
            self.set_x(x0 + bar_w + 4)
            self.set_text_color(*INK2)
            self.cell(0, 5, f"{dec(c['t'])} ± {dec(c['se'])}", new_x="LMARGIN", new_y="NEXT")
            self.ln(1)


def render(c: Candidate, *, now: datetime | None = None) -> bytes:
    now = now or datetime.now(UTC)
    pdf = _Doc(c.public_id, now)
    pdf.add_page()

    # кто и как связаться
    pdf.para(c.name, size=16, color=INK, bold=True, h=8)
    pdf.para(" · ".join(x for x in (c.email, c.tg) if x), size=9)
    pdf.ln(3)

    # категория по тесту
    if c.grade:
        pdf.para(" · ".join(x for x in (c.spec, c.track, c.grade) if x), size=13, color=BLUE, bold=True, h=7)
        facts = [f"перцентиль {c.percentile}" if c.percentile is not None else None,
                 f"θ {dec(c.theta)} ± {dec(c.se)}" if c.theta is not None and c.se is not None else None,
                 f"тест пройден {day(c.tested_at)}"]
        pdf.para(upper1(" · ".join(x for x in facts if x)), size=8.5)
        trust = [f"разбор решения: {'пройден' if c.review_passed else 'нет'}",
                 f"подтверждений грейда от работодателей: {c.employer_confirmed or 0}"]
        pdf.para(upper1("; ".join(trust)), size=8)
    else:
        pdf.para(" · ".join(x for x in (c.spec, c.track, c.grade_claimed) if x), size=13, color=BLUE, bold=True, h=7)
        pdf.para(f"Тест ещё не пройден: грейд {c.grade_claimed} заявлен кандидатом и не подтверждён.", size=8.5)

    if c.competencies:
        pdf.section("Компетенции", "  точка — оценка θ, полоса — погрешность, шкала от −3 до 3")
        pdf.comp_rows(c.competencies)

    confirmed = c.skills_confirmed or []
    claimed = [s for s in c.skills_claimed or [] if s not in confirmed]
    if confirmed or claimed:
        pdf.section("Навыки")
        if confirmed:
            pdf.para("Подтверждены тестом", size=7.5)
            pdf.chips(confirmed)
        if claimed:
            pdf.para("Заявлены, тестом не проверены", size=7.5)
            pdf.chips(claimed, fill=(240, 240, 241))

    if c.roles or c.soft_skills:
        pdf.section("Роли и софт-скиллы", "  со слов кандидата, тестом не проверяются")
        if c.roles:
            pdf.para("Роли", size=7.5)
            pdf.chips(c.roles, fill=(240, 240, 241))
        if c.soft_skills:
            pdf.para("Софт-скиллы", size=7.5)
            pdf.chips(c.soft_skills, fill=(240, 240, 241))

    jobs = cv_experience(c.cv_text)[:12] if c.cv_text else []
    if c.years_exp is not None or jobs:
        pdf.section("Опыт", f"  стаж {dec(c.years_exp, 1).removesuffix(',0')} г." if c.years_exp is not None else None)
        for j in jobs:
            period = f"{j['from']} — {j['to'] or 'н. в.'}"
            pdf.para(f"{period:<14}{j['title'] or ''}", size=8.5, color=INK)

    achs = sorted(c.achievements, key=lambda a: (not a.verified, -a.weight))
    cf = matching.cf_account(c)
    if achs or cf:
        pdf.section("Достижения", "  влияют на место в выдаче, но не на грейд")
        for a in achs:
            parts = [a.title, f"{a.place} место" if a.place else None, a.team, a.role]
            mark = "✓ подтверждено" if a.verified else "не подтверждено"
            pdf.para(f"{SOURCES.get(a.source, a.source)}: " + " · ".join(p for p in parts if p) + f"  ({mark})", size=8.5, color=INK)
        if cf:
            pdf.para(f"Codeforces: {cf.handle}, рейтинг {round(cf.rating or 0)}" + (f" ({cf.rank})" if cf.rank else "") + "  (✓ владение подтверждено)",
                     size=8.5, color=INK)

    pdf.section("Ожидания")
    pdf.para(f"От {rub(c.min_salary)} на руки · {matching.format_text(c.formats, c.city)}", size=8.5, color=INK)

    pdf.ln(4)
    pdf.para("Грейд и компетенции — по адаптивному тесту ФСП Карьера (IRT): θ — оценка уровня, ± — погрешность. "
             "Грейд повышается, только когда вся полоса погрешности выше порога. Заявленные навыки, роли и софт-скиллы — со слов кандидата.",
             size=7, h=3.8)
    return bytes(pdf.output())
