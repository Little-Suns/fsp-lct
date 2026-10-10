"""Демо-приёмник «Mock ATS»: одна страница, которая по ключу API читает ленту событий /api/ats/v1/events и отвечает на неё.

Показывает работодателю, как выглядит интеграция, без настоящей ATS: опрос раз в 3 с, анонимные карточки, контакты (если пришли),
кнопки «Пригласить на интервью» / «Отказ» / «Вышел на работу» и публикация вакансии из «ATS» (PUT по external_id).
Ключ хранится только в sessionStorage вкладки. Включается ATS_MOCK=1 (по умолчанию — при DEMO=1), иначе путь — 404.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from app import catalog, config


def _enabled() -> None:
    if not config.ATS_MOCK:
        raise HTTPException(404)


router = APIRouter(include_in_schema=False, dependencies=[Depends(_enabled)])

PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mock ATS</title><style>
body{font:15px system-ui,sans-serif;background:#f4f4f7;color:#1b1c21;margin:0}
header{background:#1b1c21;color:#fff;padding:14px 20px}header b{font-size:18px}header span{opacity:.7;margin-left:10px;font-size:13px}
main{max-width:860px;margin:0 auto;padding:16px}
section,.ev{background:#fff;border-radius:12px;padding:16px;margin:0 0 12px}
h2{font-size:15px;margin:0 0 10px}input,select,button{font:inherit;padding:8px 10px;border:1px solid #d0d0da;border-radius:8px;background:#fff}
input{min-width:0}button{cursor:pointer}button.main{background:#402fff;color:#fff;border-color:#402fff}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:6px 0}.row label{display:flex;flex-direction:column;font-size:12px;color:#666;gap:3px}
.ev h3{margin:0 0 4px;font-size:15px}.meta{color:#777;font-size:12px}.card{background:#f4f4f7;border-radius:8px;padding:8px 10px;margin:8px 0;font-size:14px}
.contacts{background:#fff3c4;border:1px solid #e8c84a}.revoked{background:#fde7e7;border:1px solid #e0a4a0}.err{color:#b3261e;margin:6px 0}.ok{color:#1a7f37;margin:6px 0}
@media(max-width:560px){main{padding:10px}}
</style></head><body>
<header><b>Mock ATS</b><span>демо-приёмник, не настоящая ATS</span></header>
<main>
<section><h2>Подключение</h2>
<div class="row"><input id="key" type="password" placeholder="Ключ API (fsp_…)" size="40" autocomplete="off">
<button id="connect" class="main">Подключить</button><span id="state" class="meta"></span></div>
<div class="meta">Ключ выпускается в кабинете работодателя, «Интеграция с ATS». Нужны области чтения событий и записи. Ключ живёт только в этой вкладке.</div>
<div id="err" class="err"></div></section>
<section><h2>Опубликовать вакансию из ATS</h2>
<form id="vac"><div class="row">
<label>external_id<input name="external_id" value="ATS-1001" required maxlength="128"></label>
<label>Название<input name="title" value="Backend-разработчик (Python)" required minlength="3"></label>
<label>Специализация<select name="spec"></select></label>
<label>Грейд<select name="grade"></select></label>
<label>Формат<select name="format"></select></label>
<label>Вилка от<input name="salary_from" type="number" value="240000" min="1"></label>
<label>до<input name="salary_to" type="number" value="300000" min="1"></label>
<button class="main">Опубликовать</button></div></form>
<div id="vres" class="meta"></div></section>
<div id="feed"></div>
</main>
<script>
const API = "/api/ats/v1", LABEL = {
  "application.created": "Новый отклик", "application.withdrawn": "Отклик отозван", "application.status": "Статус отклика",
  "invitation.seen": "Приглашение просмотрено", "invitation.accepted": "Приглашение принято", "invitation.declined": "Приглашение отклонено",
  "invitation.expired": "Приглашение истекло", "candidate.access_revoked": "Кандидат закрыл доступ к контактам"};
const REASON = __REASON__;
const $ = id => document.getElementById(id);
let cursor = 0, timer = null, key = "", gen = 0;  // gen — поколение подключения: ответ старого ключа в новую ленту не попадает
try { key = sessionStorage.getItem("ats_key") || ""; } catch (e) {}
$("key").value = key;

const text = (el, s) => { el.textContent = s; return el; };
function detail(r, j) {
  const d = j && j.detail;
  return typeof d === "string" ? d : d ? JSON.stringify(d) : "Ошибка " + r.status;
}
async function call(method, path, body, k = key) {
  const r = await fetch(API + path, {method, headers: {"X-Api-Key": k, "Content-Type": "application/json"}, body: body ? JSON.stringify(body) : undefined});
  const j = await r.json().catch(() => null);
  if (!r.ok) throw new Error(detail(r, j));
  return j;
}
function el(tag, cls, s) { const e = document.createElement(tag); if (cls) e.className = cls; if (s != null) e.textContent = s; return e; }

function card(c) {
  if (!c) return el("div", "card", "Кандидат закрыл доступ или удалён — карточки нет.");
  const d = el("div", "card");
  d.textContent = [c.public_id, c.spec, c.track, c.grade, c.salary ? "от " + c.salary + " ₽" : null, c.city, (c.skills || []).slice(0, 6).join(", ")]
    .filter(Boolean).join(" · ");
  return d;
}
function act(box, label, fn, cls) {
  const b = el("button", cls, label);
  b.onclick = async () => {
    try { await fn(); box.err.textContent = ""; box.ok.textContent = "Готово: " + label; await poll(); }
    catch (e) { box.ok.textContent = ""; box.err.textContent = e.message; }
  };
  box.row.append(b);
}
// карточки событий по public_id кандидата: при отзыве доступа контакты и данные в прежних карточках убираются
const byCand = {}, revoked = new Set();
const candId = e => e.type === "candidate.access_revoked" ? e.data.public_id : (e.data.candidate || {}).public_id;
function render(e) {
  const d = e.data, ev = el("div", "ev"), box = {row: el("div", "row"), err: el("div", "err"), ok: el("div", "ok")};
  ev.dataset.eventType = e.type;  // стабильные атрибуты для тестов и скриптов
  if (d.application_id) ev.dataset.applicationId = d.application_id;
  if (d.invitation_id) ev.dataset.invitationId = d.invitation_id;
  ev.append(el("h3", null, LABEL[e.type] || e.type), el("div", "meta", "#" + e.id + " · " + e.type + " · " + e.at));
  if (d.vacancy) ev.append(el("div", "meta", "Вакансия: " + (d.vacancy.title || "удалена") + (d.vacancy.external_id ? " (" + d.vacancy.external_id + ")" : "")));
  if (d.invitation) ev.append(el("div", "meta", "Приглашение: " + d.invitation.role + ", " + d.invitation.salary_from + "–" + d.invitation.salary_to));
  if (d.status) ev.append(el("div", "meta", "Статус: " + d.status + (d.reason ? " (" + d.reason + ")" : "")));
  const pid = candId(e), mine = (byCand[pid] = byCand[pid] || []);
  if (e.type === "candidate.access_revoked") {
    revoked.add(pid);
    ev.append(el("div", "card revoked", "Кандидат " + pid + ": доступ отозван, контакты больше не показывать (" + d.why + ")."));
    for (const old of mine) {
      if (old.contacts) old.contacts.remove();
      old.card.textContent = "Доступ отозван — данные кандидата " + pid + " удалены.";
      old.card.classList.add("revoked");
    }
  } else {
    if (d.candidate || d.contacts) revoked.delete(pid);  // API отдал карточку или контакты — доступ сейчас есть; старые очищенные карточки остаются очищенными
    const c = card(d.candidate), ct = d.contacts && !revoked.has(pid) ? el("div", "card contacts", "Контакты: " + [d.contacts.name, d.contacts.email, d.contacts.tg].filter(Boolean).join(" · ")) : null;
    if (revoked.has(pid)) c.textContent = "Доступ отозван — данные кандидата " + pid + " удалены.";
    ev.append(c); if (ct) ev.append(ct);
    mine.push({card: c, contacts: ct});
  }
  if (e.type === "application.created" || e.type === "application.status") {
    const id = d.application_id, set = (status, reason) => () => call("POST", "/applications/" + id + "/status", {status, reason});
    act(box, "Просмотрено", set("seen"));
    act(box, "Пригласить на интервью", set("accepted"), "main");
    act(box, "Отказ", set("declined", REASON));
  }
  if (e.type === "invitation.accepted") act(box, "Вышел на работу", () => call("POST", "/invites/" + d.invitation_id + "/feedback", {value: "hired"}), "main");
  ev.append(box.row, box.err, box.ok);
  return ev;
}
let polling = false;
async function poll() {
  if (polling) return;  // act() и таймер не должны опрашивать параллельно: курсор один, события не задвоятся
  polling = true;
  const g = gen;
  try {
    const j = await call("GET", "/events?limit=100&after=" + cursor, undefined, key);
    if (g !== gen) return;  // за время запроса подключили другой ключ
    $("err").textContent = ""; $("state").textContent = "Подключено, курсор " + j.next;
    for (const e of j.items) $("feed").prepend(render(e));
    cursor = j.next;
  } catch (e) { if (g === gen) { $("err").textContent = e.message; $("state").textContent = ""; } }
  finally { if (g === gen) polling = false; }
}
$("connect").onclick = () => {
  key = $("key").value.trim();
  try { sessionStorage.setItem("ats_key", key); } catch (e) {}
  gen++; polling = false; cursor = 0; $("feed").textContent = ""; clearInterval(timer);
  for (const k in byCand) delete byCand[k];
  revoked.clear();
  poll(); timer = setInterval(poll, 3000);
};
$("vac").onsubmit = async ev => {
  ev.preventDefault();
  const f = new FormData(ev.target), body = Object.fromEntries(f);
  const id = body.external_id; delete body.external_id;
  body.salary_from = +body.salary_from; body.salary_to = +body.salary_to;
  try {
    const v = await call("PUT", "/vacancies/" + encodeURIComponent(id), body);
    $("vres").className = "ok"; $("vres").textContent = "Опубликовано: вакансия #" + v.id + (v.warnings.length ? ". " + v.warnings.join(" ") : "");
  } catch (e) { $("vres").className = "err"; $("vres").textContent = e.message; }
};
fetch("/api/meta").then(r => r.json()).then(m => {
  const fill = (name, list, pick) => { const s = document.querySelector("[name=" + name + "]"); list.forEach(x => { const o = el("option", null, x); o.value = x; s.append(o); }); s.value = pick; };
  fill("spec", m.specs, "Backend"); fill("grade", m.grades, "Middle"); fill("format", m.formats, m.formats[0]);
});
if (key) $("connect").click();
</script></body></html>"""


@router.get("/mock-ats", response_class=HTMLResponse)
def page():
    return HTMLResponse(PAGE.replace("__REASON__", repr(next(iter(catalog.DECLINE_REASONS)))))
