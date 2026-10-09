"""Публичные контракты подбора и приглашений. Поля с ПДн не входят в анонимную карточку."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class ErrorResponse(BaseModel):
    detail: str | dict[str, JsonValue] | list[dict[str, JsonValue]]


ERROR_RESPONSES = {
    code: {"model": ErrorResponse, "description": description}
    for code, description in {
        401: "Нет действующей сессии: войдите снова",
        403: "Недостаточно прав, отозвано согласие или компания заблокирована",
        404: "Запись не найдена либо недоступна текущему пользователю",
        409: "Конфликт состояния: дубликат, завершённая сессия или лимит открытых приглашений",
        413: "Размер запроса или файла превышает ограничение",
        422: "Неверные поля запроса или нарушение правил предметной области; detail — строка, errors/warnings или список ошибок полей",
        429: "Исчерпана квота или превышена допустимая частота запросов",
        503: "Не настроен или временно недоступен внешний компонент",
    }.items()
}


class CandidateCard(BaseModel):
    # Полный набор дополнительных полей карточки сохраняется; базовые поля обязательны.
    model_config = ConfigDict(extra="allow")
    id: str
    public_id: str
    spec: str
    track: str | None
    grade: str
    grade_claimed: str | None
    pct: int | None
    theta: str | None
    skills: list[str]
    claimed: list[str]
    roles: list[str]
    soft: list[str]
    gaps: list[str]
    fsp: str | None
    cf: float | None
    badges: list[dict[str, JsonValue]]
    sport_rank: str | None
    salary: int
    formats: list[str]
    city: str | None
    format: str
    fmtOk: bool | None
    inFork: bool | None
    load: int | None
    busy: bool
    match: float | None
    accept: float | None
    score: float | None
    confirmed: str | None
    express: bool
    trust: dict[str, JsonValue]


class SearchResult(BaseModel):
    items: list[CandidateCard]
    total: int
    page: int
    limit: int
    skills: list[str]
    facets: dict[str, dict[str, int]]
    cap: int


class NeedView(BaseModel):
    id: int
    text: str
    spec: str
    track: str | None
    grade: str
    must: list[str]
    nice: list[str]
    salary_from: int | None = Field(alias="from")
    salary_to: int | None = Field(alias="to")
    format: str | None
    city: str | None
    parsed_by: str
    created_at: datetime


class QuotaView(BaseModel):
    used: int
    max: int
    left: int
    resets_at: datetime
    accepted_share: float | None
    next_max: int
    paid_accepts: int
    reputation: dict[str, JsonValue | datetime]


class PicksResult(BaseModel):
    need: NeedView
    total: int
    items: list[CandidateCard]
    filters: list[str]
    categories: list[dict[str, JsonValue]]
    market: dict[str, JsonValue]
    quota: QuotaView
    cap: int


class InvitationView(BaseModel):
    id: int
    cid: str
    need_id: int | None
    lottery_id: int | None
    role: str
    salary_from: int = Field(alias="from")
    salary_to: int = Field(alias="to")
    format: str
    status: str
    reason: str | None
    when: str
    sent_at: datetime
    expires_at: datetime
    contact: dict[str, JsonValue] | None
    fb: str | None
    feedback: str | None


class InviteResult(BaseModel):
    invite: InvitationView
    warnings: list[str]
    quota: QuotaView
