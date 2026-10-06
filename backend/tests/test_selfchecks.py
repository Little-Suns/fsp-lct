"""Самопроверки модулей (`python -m <модуль>`) внутри pytest — чтобы их ветки считались в покрытии.
CI гоняет их и отдельным шагом. БД не нужна."""

import runpy
import warnings

import pytest

MODULES = ["app.integrations.scoring", "app.services.parsing", "app.services.lottery", "app.services.irt", "app.routers.employer", "seed.gold"]


@pytest.mark.parametrize("module", MODULES)
def test_selfcheck(module, capsys, monkeypatch):
    monkeypatch.setattr("app.config.LLM_BASE_URL", "")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # «found in sys.modules» — модуль уже импортирован тестами
        runpy.run_module(module, run_name="__main__")
    assert capsys.readouterr().out.rstrip().endswith("ok")
