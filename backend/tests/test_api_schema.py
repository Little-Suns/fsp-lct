"""Контракт OpenAPI: успешные ответы подбора и реальные форматы ошибок, без запуска БД."""

from app.main import app
from app.api_schemas import ErrorResponse


def test_employer_response_contracts():
    schema = app.openapi()
    expected = {
        ("/api/employer/search", "get"): "SearchResult",
        ("/api/employer/needs/{need_id}/picks", "get"): "PicksResult",
        ("/api/employer/candidates/{public_id}", "get"): "CandidateCard",
        ("/api/employer/invites", "post"): "InviteResult",
    }
    for (path, method), model in expected.items():
        responses = schema["paths"][path][method]["responses"]
        assert responses["200"]["content"]["application/json"]["schema"] == {"$ref": f"#/components/schemas/{model}"}
        for code in ("401", "403", "404", "409", "422", "429", "503"):
            assert responses[code]["description"]
            assert responses[code]["content"]["application/json"]["schema"]
    card = schema["components"]["schemas"]["CandidateCard"]
    assert {"id", "spec", "grade", "grade_tested", "skills"} <= set(card["required"])
    assert {"name", "email", "tg", "truth"}.isdisjoint(card["properties"])


def test_documented_error_variants():
    for detail in ("Кандидат не найден", {"errors": ["Укажите обе границы вилки."], "warnings": []},
                   [{"loc": ["body", "salary_from"], "msg": "Неверное значение", "type": "value_error"}]):
        assert ErrorResponse(detail=detail).model_dump()["detail"] == detail
