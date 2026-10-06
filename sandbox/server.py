"""Песочница задач на код: HTTP API поверх nsjail (только стандартная библиотека Python).

POST /run  (заголовок X-Sandbox-Token)
  {"lang": "python"|"typescript", "code": str, "harness": {"entry": имя функции},
   "tests": [{"args": [...], "expected": ...}], "limits": {"time_ms", "memory_mb"}, "fail_fast": bool, "echo": bool}
→ {"status": итог, "passed": k, "total": n, "results": [{"status", "time_ms", "got"?}], "stderr": фрагмент | null}
  статус теста: ok | wrong | tle | mle | re | ce (+ skip — не запускался после первой ошибки при fail_fast)
GET /health → {"ok", "workers", "busy"}

Каждый тест — отдельный запуск nsjail: свои пространства имён (сети нет), seccomp, cgroup (память, процессы),
rlimit (CPU, размер файлов, дескрипторы), корень только на чтение, запись — в tmpfs /tmp, uid 65534.
Ожидаемые ответы внутрь не передаются: сравнение здесь, снаружи. Время меряется снаружи по стенке.
"""

import hmac
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOKEN = os.environ.get("SANDBOX_TOKEN", "")
WORKERS = int(os.environ.get("SANDBOX_WORKERS", "4"))  # одновременных запусков nsjail (каждый — 1 CPU)
RUN_ROOT = Path(os.environ.get("SANDBOX_RUN_ROOT", "/run/sbx"))
PORT = int(os.environ.get("SANDBOX_PORT", "8080"))

MAX_BODY = 8 * 1024 * 1024
MAX_CODE = 20_000  # байт исходника
MAX_TESTS = 50
MAX_PENDING = 32  # запросов в работе и в очереди; больше — сразу 503
QUEUE_WAIT_S = 20  # ожидание свободного исполнителя
REQUEST_BUDGET_S = 60  # стенка на весь запрос; не успевшие тесты — skip
TIME_MS = (200, 2000, 5000)  # min, по умолчанию, max на тест
MEMORY_MB = (64, 256, 512)
OUT_MAX = 4 * 1024 * 1024  # stdout решения читаем не больше (rlimit_fsize ограничивает запись)
SNIPPET_MAX = 400
MARK = "\x1eRESULT "
ENTRY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
LANGS = ("python", "typescript")

_slots = threading.BoundedSemaphore(WORKERS)
_pending_lock = threading.Lock()
_pending = 0
_busy = 0


class BadRequest(Exception):
    pass


class JailError(Exception):
    """nsjail не смог подготовить песочницу (политика, cgroup, монтирование) — сбой стенда, а не решения."""


def _jail(task: Path, time_ms: int, memory_mb: int) -> list[str]:
    secs = math.ceil(time_ms / 1000)
    cmd = [
        "nsjail", "-Mo", "-Q",
        "--use_cgroupv2", "--cgroup_mem_max", str(memory_mb * 1024 * 1024), "--cgroup_mem_swap_max", "0", "--cgroup_pids_max", "32",
        "-t", str(secs + 1), "--rlimit_cpu", str(secs + 1), "--rlimit_as", "max", "--rlimit_fsize", "8", "--rlimit_nofile", "64",
        "--rlimit_stack", "64", "--max_cpus", "1",
        "-u", "65534:65534", "-g", "65534:65534", "-H", "sandbox",
        "-R", "/usr", "-R", "/lib", "-R", "/bin", "-R", "/dev/null", "-R", "/dev/urandom", "-R", "/dev/zero",
        "-R", f"{task}:/task", "-m", "none:/tmp:tmpfs:size=8388608", "-D", "/task",
        "-E", "HOME=/tmp", "-E", "PATH=/usr/local/bin:/usr/bin:/bin", "-E", "LANG=C.UTF-8",
        "--seccomp_policy", str(HERE / "policy.kafel"),
    ]
    if Path("/lib64").exists():
        cmd += ["-R", "/lib64"]
    return cmd


def _program(lang: str, memory_mb: int) -> list[str]:
    if lang == "python":
        return ["/usr/bin/python3", "-I", "-S", "-B", "/task/harness.py"]
    heap = max(32, memory_mb - 64)  # куча V8 меньше лимита cgroup: нехватка памяти — понятная ошибка, а не SIGKILL
    return ["/usr/local/bin/node", "--experimental-strip-types", "--disable-warning=ExperimentalWarning", "--no-addons",
            f"--max-old-space-size={heap}", "/task/main.mts"]


def _prepare(task: Path, lang: str, code: str, entry: str):
    task.mkdir(mode=0o755)
    if lang == "python":
        (task / "solution.py").write_text(code, encoding="utf-8")
        shutil.copy(HERE / "harness.py", task / "harness.py")
    else:
        harness = (HERE / "harness.mts").read_text(encoding="utf-8").replace("__ENTRY__", entry)
        (task / "main.mts").write_text(code + "\n" + harness, encoding="utf-8")
    for p in task.iterdir():
        p.chmod(0o644)


def _norm(v):
    """Сравнение без сюрпризов JSON: bool ≠ int, 3.0 == 3."""
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, list):
        return [_norm(x) for x in v]
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in v.items()}
    return v


def _same(a, b) -> bool:
    return json.dumps(_norm(a), sort_keys=True) == json.dumps(_norm(b), sort_keys=True)


def _snippet(text: str) -> str | None:
    """Короткий кусок stderr без путей и внутренностей Node — для подсказки кандидату на открытых примерах."""
    lines = [ln.replace("file:///task/main.mts", "solution.ts").replace("/task/main.mts", "solution.ts").replace("/task/", "")
             for ln in text.splitlines()]
    where = next((ln.strip() for ln in lines if re.match(r"^solution\.ts:\d+", ln.strip())), None)
    error = next((ln.strip() for ln in lines if re.match(r"^[A-Z]\w*(Error|Exception)\b", ln.strip())), None)
    s = "\n".join(x for x in (where, error) if x)
    return s[:SNIPPET_MAX] or None


def _classify(rc: int, wall_ms: int, time_ms: int, out: str, err: str) -> tuple[str, object, str | None]:
    """(статус, значение, сообщение) по коду выхода, стенке и выводу обвязки."""
    lines = [ln for ln in out.split("\n") if ln.startswith(MARK)]
    res = None
    if lines:
        try:
            res = json.loads(lines[-1][len(MARK):])
        except ValueError:
            res = None
    if isinstance(res, dict) and "ok" in res:
        return "ok", res["ok"], None
    if wall_ms >= time_ms:
        return "tle", None, None
    if isinstance(res, dict) and res.get("error") in ("ce", "re", "mle"):
        return res["error"], None, res.get("msg")
    if "heap out of memory" in err or "Allocation failed" in err or "Cannot allocate Wasm memory" in err:
        return "mle", None, None
    if "SyntaxError" in err or "ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX" in err or "ERR_INVALID_TYPESCRIPT_SYNTAX" in err:
        return "ce", None, _snippet(err)
    if rc in (137, -9):  # SIGKILL без превышения времени — OOM-killer cgroup
        return "mle", None, None
    if rc in (152, -24):  # SIGXCPU — исчерпан RLIMIT_CPU
        return "tle", None, None
    if rc in (153, -25):  # SIGXFSZ — превышен размер вывода/файла
        return "re", None, "Превышен объём вывода"
    return "re", None, _snippet(err)


def _run_one(task: Path, io: Path, lang: str, entry: str, args: list, time_ms: int, memory_mb: int) -> tuple[str, int, object, str | None]:
    (task / "input.json").write_text(json.dumps({"entry": entry, "args": args}), encoding="utf-8")
    (task / "input.json").chmod(0o644)
    out_p, err_p = io / "out", io / "err"
    t0 = time.monotonic()
    with open(out_p, "wb") as fo, open(err_p, "wb") as fe:
        proc = subprocess.Popen(_jail(task, time_ms, memory_mb) + ["--"] + _program(lang, memory_mb),
                                stdin=subprocess.DEVNULL, stdout=fo, stderr=fe, env={"PATH": "/usr/local/bin:/usr/bin:/bin"},
                                start_new_session=True)
        try:
            rc = proc.wait(timeout=time_ms / 1000)
        except subprocess.TimeoutExpired:
            proc.terminate()  # nsjail по SIGTERM убивает процессы песочницы и чистит cgroup
            try:
                rc = proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                rc = proc.wait()
    wall = int((time.monotonic() - t0) * 1000)
    with open(out_p, "rb") as f:
        out = f.read(OUT_MAX).decode("utf-8", "replace")
    with open(err_p, "rb") as f:
        err = f.read(64 * 1024).decode("utf-8", "replace")
    if MARK not in out and re.search(r"^\[F\]\[", err, re.M):  # с -Q nsjail пишет только фатальные ошибки: «[F][время]…»
        raise JailError(err[:300])
    status, got, msg = _classify(rc, wall, time_ms, out, err)
    return status, min(wall, time_ms), got, msg


def _clamp(v, lo_def_hi) -> int:
    lo, default, hi = lo_def_hi
    try:
        return max(lo, min(hi, int(v))) if v is not None else default
    except (TypeError, ValueError):
        raise BadRequest("limits: нужны целые числа") from None


def validate(req) -> dict:
    if not isinstance(req, dict):
        raise BadRequest("Ожидается JSON-объект")
    lang, code = req.get("lang"), req.get("code")
    if lang not in LANGS:
        raise BadRequest(f"lang — одно из: {', '.join(LANGS)}")
    if not isinstance(code, str) or not code.strip():
        raise BadRequest("Пустой код")
    if len(code.encode("utf-8")) > MAX_CODE:
        raise BadRequest(f"Код длиннее {MAX_CODE // 1000} КБ")
    if "\x00" in code:
        raise BadRequest("Недопустимый символ в коде")
    entry = (req.get("harness") or {}).get("entry") if isinstance(req.get("harness"), dict) else None
    if not isinstance(entry, str) or not ENTRY_RE.match(entry):
        raise BadRequest("harness.entry — имя функции")
    tests = req.get("tests")
    if not isinstance(tests, list) or not 1 <= len(tests) <= MAX_TESTS:
        raise BadRequest(f"tests — от 1 до {MAX_TESTS}")
    for t in tests:
        if not isinstance(t, dict) or not isinstance(t.get("args"), list) or "expected" not in t:
            raise BadRequest("Тест — {args: [...], expected}")
    limits = req.get("limits") or {}
    if not isinstance(limits, dict):
        raise BadRequest("limits — объект")
    return {"lang": lang, "code": code, "entry": entry, "tests": tests, "fail_fast": bool(req.get("fail_fast")),
            "echo": bool(req.get("echo")), "time_ms": _clamp(limits.get("time_ms"), TIME_MS), "memory_mb": _clamp(limits.get("memory_mb"), MEMORY_MB)}


def run(req: dict) -> dict:
    """Прогон проверенного запроса (validate). Исполнитель занимается на весь запрос: тесты идут последовательно."""
    deadline = time.monotonic() + REQUEST_BUDGET_S
    results, stderr = [], None
    work = Path(tempfile.mkdtemp(dir=RUN_ROOT))
    work.chmod(0o711)  # nsjail монтирует task от непривилегированного uid: нужен проход по пути, но не листинг
    try:
        task, io = work / "task", work / "io"
        io.mkdir(mode=0o700)
        _prepare(task, req["lang"], req["code"], req["entry"])
        stop = None
        for t in req["tests"]:
            if stop or time.monotonic() + req["time_ms"] / 1000 > deadline:
                results.append({"status": stop or "skip", "time_ms": 0})
                continue
            status, ms, got, msg = _run_one(task, io, req["lang"], req["entry"], t["args"], req["time_ms"], req["memory_mb"])
            if status == "ok" and not _same(got, t["expected"]):
                status = "wrong"
            r = {"status": status, "time_ms": ms}
            if req["echo"]:
                r["got"] = json.dumps(got, ensure_ascii=False)[:200] if status in ("ok", "wrong") else None
            results.append(r)
            if msg and stderr is None:
                stderr = msg[:SNIPPET_MAX]
            if status == "ce":
                stop = "ce"  # ошибка компиляции одна на все тесты
            elif status != "ok" and req["fail_fast"]:
                stop = "skip"
    finally:
        shutil.rmtree(work, ignore_errors=True)
    passed = sum(r["status"] == "ok" for r in results)
    first_bad = next((r["status"] for r in results if r["status"] not in ("ok", "skip")), None)
    return {"status": "ok" if passed == len(results) else first_bad or "tle", "passed": passed, "total": len(results),
            "results": results, "stderr": stderr}


def handle_run(req) -> tuple[int, dict]:
    global _pending, _busy
    try:
        r = validate(req)
    except BadRequest as e:
        return 422, {"detail": str(e)}
    with _pending_lock:
        if _pending >= MAX_PENDING:
            return 503, {"detail": "Песочница перегружена"}
        _pending += 1
    try:
        if not _slots.acquire(timeout=QUEUE_WAIT_S):
            return 503, {"detail": "Песочница перегружена"}
        with _pending_lock:
            _busy += 1
        try:
            return 200, run(r)
        except JailError as e:
            print(f"sandbox: сбой nsjail: {e}", file=sys.stderr, flush=True)
            return 503, {"detail": "Песочница неисправна"}
        finally:
            with _pending_lock:
                _busy -= 1
            _slots.release()
    finally:
        with _pending_lock:
            _pending -= 1


class Handler(BaseHTTPRequestHandler):
    server_version = "sandbox"
    sys_version = ""

    def _send(self, code: int, obj: dict):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # без тел запросов и кода кандидата в логах
        sys.stderr.write(f"{self.command} {self.path} {args[1] if len(args) > 1 else ''}\n")

    def do_GET(self):
        if self.path == "/health":
            ok = HEALTH["ok"]
            return self._send(200 if ok else 503, {"ok": ok, "workers": WORKERS, "busy": _busy})
        self._send(404, {"detail": "Не найдено"})

    def do_POST(self):
        if self.path != "/run":
            return self._send(404, {"detail": "Не найдено"})
        if not TOKEN or not hmac.compare_digest(self.headers.get("X-Sandbox-Token", ""), TOKEN):
            return self._send(401, {"detail": "Нет доступа"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if not 0 < n <= MAX_BODY:
            return self._send(413, {"detail": "Слишком большой или пустой запрос"})
        try:
            req = json.loads(self.rfile.read(n))
        except ValueError:
            return self._send(400, {"detail": "Некорректный JSON"})
        code, obj = handle_run(req)
        self._send(code, obj)


HEALTH = {"ok": False}


def selfcheck() -> bool:
    """Пробный прогон обоих языков: без cgroup/привилегий nsjail не стартует — песочница честно «нездорова»."""
    probe = [{"args": [2], "expected": 3}]
    try:
        py = run(validate({"lang": "python", "code": "def f(x):\n    return x + 1\n", "harness": {"entry": "f"}, "tests": probe}))
        ts = run(validate({"lang": "typescript", "code": "function f(x: number): number { return x + 1; }", "harness": {"entry": "f"}, "tests": probe}))
    except JailError as e:
        print(f"sandbox: сбой nsjail: {e}", file=sys.stderr, flush=True)
        return False
    return py["status"] == "ok" and ts["status"] == "ok"


def main():
    if not TOKEN:
        sys.exit("SANDBOX_TOKEN не задан: без общего секрета песочница не стартует")
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    HEALTH["ok"] = selfcheck()
    print(f"sandbox: workers={WORKERS} selfcheck={'ok' if HEALTH['ok'] else 'FAIL'}", file=sys.stderr, flush=True)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    srv.daemon_threads = True
    srv.serve_forever()


if __name__ == "__main__":
    main()
