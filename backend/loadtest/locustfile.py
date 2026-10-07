"""Нагрузочный прогон «десятки одновременных пользователей» (locust).

Стенд: API с DEMO=1 поверх полного сида (`seed.generate --reset`: 1500 кандидатов, 250 потребностей). Прогон:

    cd backend && uv run locust -f loadtest/locustfile.py --headless -u 50 -r 10 -t 2m \
        --host http://127.0.0.1:8000 --csv var/load

Смесь — как у людей на стенде жюри: каждый виртуальный пользователь входит за демо-персонажа (все за одного и того же —
так и будет на показе) и думает 1–3 с между действиями. Кандидат: профиль, приглашения, текущий тест. Работодатель:
подборка под потребность, карточка кандидата из подборки, поиск по банку, воронка. Все: публичные справочники /api/meta.
Без пауз (предельная пропускная способность) — `LOAD_WAIT=0`. Итог — p50/p95/p99 и ошибки по эндпоинтам в
`var/load_stats.csv`; ответ не 2xx — ошибка (кроме штатного 404 «нет активного теста»)."""

import os
import random

from locust import HttpUser, between, constant, task

WAIT = float(os.environ.get("LOAD_WAIT", "1"))
SPECS = ["Backend", "Frontend", "Mobile", "ML / DS", "Data Eng / Analytics", "DevOps / SRE", "QA", "Security"]
QUERIES = ["", "python postgres", "kafka", "react typescript", "kubernetes", "go"]


class _Demo(HttpUser):
    abstract = True
    role = ""
    wait_time = between(WAIT, WAIT * 3) if WAIT else constant(0)

    def on_start(self):
        r = self.client.post(f"/api/auth/demo/{self.role}", name="/api/auth/demo/{role}")
        self.client.headers["Authorization"] = f"Bearer {r.json()['token']}"

    @task(1)
    def meta(self):
        self.client.get("/api/meta")


class Candidate(_Demo):
    role = "candidate"

    @task(3)
    def me(self):
        self.client.get("/api/auth/me")
        self.client.get("/api/candidate/me")

    @task(3)
    def invites(self):
        self.client.get("/api/candidate/invites")

    @task(2)
    def quest(self):
        with self.client.get("/api/quest/current", catch_response=True) as r:
            if r.status_code == 404:  # активного теста нет — штатный ответ
                r.success()


class Employer(_Demo):
    role = "employer"

    def on_start(self):
        super().on_start()
        self.needs = [n["id"] for n in self.client.get("/api/employer/needs").json()]
        self.need, self.seen = None, []

    @task(4)
    def picks(self):
        nid = random.choice(self.needs)
        r = self.client.get(f"/api/employer/needs/{nid}/picks", name="/api/employer/needs/{id}/picks")
        if r.ok and r.json()["items"]:
            self.need, self.seen = nid, [c["id"] for c in r.json()["items"][:10]]

    @task(3)
    def card(self):
        if not self.seen:
            return self.picks()
        self.client.get(
            f"/api/employer/candidates/{random.choice(self.seen)}",
            params={"need_id": self.need},
            name="/api/employer/candidates/{public_id}",
        )

    @task(3)
    def search(self):
        params = {"spec": random.choice(SPECS), "q": random.choice(QUERIES)}
        self.client.get("/api/employer/search", params=params, name="/api/employer/search")

    @task(2)
    def pipeline(self):
        self.client.get("/api/employer/pipeline")
