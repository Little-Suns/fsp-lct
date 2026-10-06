"""Песочница против настоящего nsjail (только в контейнере --privileged, см. Dockerfile, target test).

Проверяются вердикты (ok, wrong, tle, mle, re, ce) и попытки выхода: сеть, fork-бомба, бесконечный цикл, память,
запись вне /tmp, чтение файлов хоста, os.system, ptrace/unshare, секрет из окружения, поток вывода.
"""

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

os.environ.setdefault("SANDBOX_TOKEN", "test-token")
os.environ.setdefault("SANDBOX_RUN_ROOT", "/tmp/sbx-test")
os.environ.setdefault("SANDBOX_PORT", "18080")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import server  # noqa: E402

Path(os.environ["SANDBOX_RUN_ROOT"]).mkdir(parents=True, exist_ok=True)


def run(lang, code, tests=None, entry="f", **kw):
    req = {"lang": lang, "code": code, "harness": {"entry": entry}, "tests": tests or [{"args": [], "expected": "ok"}], **kw}
    return server.run(server.validate(req))


def one(lang, code, expected="ok", args=None, **kw):
    r = run(lang, code, [{"args": args or [], "expected": expected}], **kw)
    return r["results"][0]["status"], r


# ---------- вердикты ----------

LB_PY = "from bisect import bisect_left\n\ndef lower_bound(a: list[int], x: int) -> int:\n    return bisect_left(a, x)\n"
LB_TS = """interface Range { lo: number; hi: number }
function lower_bound(a: number[], x: number): number {
  const r: Range = { lo: 0, hi: a.length };
  while (r.lo < r.hi) { const m = (r.lo + r.hi) >> 1; if (a[m] < x) r.lo = m + 1; else r.hi = m; }
  return r.lo;
}
"""
LB_TESTS = [{"args": [[1, 3, 3, 5], 3], "expected": 1}, {"args": [[1, 3, 3, 5], 6], "expected": 4}, {"args": [[], 1], "expected": 0}]


@pytest.mark.parametrize("lang,code", [("python", LB_PY), ("typescript", LB_TS)])
def test_ok_and_wrong(lang, code):
    r = run(lang, code, LB_TESTS, entry="lower_bound", echo=True)
    assert r["status"] == "ok" and r["passed"] == 3 and r["total"] == 3, r
    assert r["results"][0]["got"] == "1" and all(x["time_ms"] > 0 for x in r["results"])
    bad = [dict(t, expected=t["expected"] + 1) for t in LB_TESTS]
    r = run(lang, code, bad, entry="lower_bound", fail_fast=True)
    assert r["status"] == "wrong" and r["passed"] == 0
    assert [x["status"] for x in r["results"]] == ["wrong", "skip", "skip"]


def test_typescript_features_of_strip_types():
    code = """type Pair<T> = [T, T];
function g<T>(x: T): Pair<T> { return [x, x]; }
export function f(xs: readonly number[], k?: number): number {
  const m = new Map<number, number>();
  for (const x of xs) m.set(x, (m.get(x) ?? 0) + 1);
  return (g(m.size) as Pair<number>)[0] + (k ?? 0);
}
"""
    assert one("typescript", code, 3, [[1, 2, 2, 3]])[0] == "ok"
    # enum и namespace strip-types не поддерживает — ошибка компиляции с понятным текстом
    st, r = one("typescript", "enum C { A }\nfunction f(): number { return C.A; }", 0)
    assert st == "ce" and "TypeScript" in (r["stderr"] or ""), r


def test_bool_is_not_int_and_float_integral_is_int():
    assert one("python", "def f():\n    return True\n", 1)[0] == "wrong"
    assert one("python", "def f():\n    return 3.0\n", 3)[0] == "ok"
    assert one("typescript", "function f(): boolean { return true; }", True)[0] == "ok"


def test_compile_and_runtime_errors():
    st, r = one("python", "def f(:\n    pass\n")
    assert st == "ce" and "строка 1" in r["stderr"]
    st, r = one("python", "def g():\n    return 1\n")
    assert st == "ce" and "Не найдена функция f" in r["stderr"]
    r = run("python", "def f(:\n", [{"args": [], "expected": 1}] * 3)
    assert [x["status"] for x in r["results"]] == ["ce", "ce", "ce"]  # одна компиляция на все тесты
    st, r = one("python", "def f():\n    return [1][5]\n")
    assert st == "re" and "IndexError" in r["stderr"] and "строка 2" in r["stderr"]
    st, r = one("python", "def f():\n    return f()\n")
    assert st == "re" and "рекурсия" in r["stderr"]
    st, r = one("typescript", "function f(): number { const x = ; }")
    assert st == "ce" and "/task" not in (r["stderr"] or "")
    st, r = one("typescript", "function f(): number { throw new TypeError('плохо'); }")
    assert st == "re" and r["stderr"] == "TypeError: плохо"
    assert one("python", "def f():\n    return {1, 2}\n")[0] == "re"  # set не переводится в JSON


def test_time_limit():
    t0 = time.monotonic()
    st, r = one("python", "def f():\n    while True:\n        pass\n", limits={"time_ms": 500})
    assert st == "tle" and r["results"][0]["time_ms"] == 500
    assert time.monotonic() - t0 < 4
    # sched_setaffinity запрещён: решение не выйдет за --max_cpus 1
    assert one("python", "import os\n\ndef f():\n    try:\n        os.sched_setaffinity(0, set(range(os.cpu_count() or 1)))\n        return 'set'\n    except OSError:\n        return 'denied'\n", "denied")[0] == "ok"
    assert one("typescript", "function f(): number { for (;;) {} }", limits={"time_ms": 700})[0] == "tle"
    # после убийства по таймауту в контейнере не остаётся процессов решения
    time.sleep(0.5)
    alive = [p for p in Path("/proc").iterdir() if p.name.isdigit() and b"harness" in (p / "cmdline").read_bytes()]
    assert not alive


def test_memory_limit():
    assert one("python", "def f():\n    x = b'x' * (1 << 31)\n    return len(x)\n", limits={"memory_mb": 128})[0] == "mle"
    assert one("python", "def f():\n    x = [0] * (10 ** 9)\n    return len(x)\n", limits={"memory_mb": 128})[0] == "mle"
    st, _ = one("typescript", "function f(): number { const a: number[][] = []; for (;;) a.push(new Array(1e6).fill(1)); }",
                limits={"memory_mb": 128, "time_ms": 4000})
    assert st == "mle"


# ---------- попытки выхода ----------

def test_no_network():
    code = """import socket

def f():
    out = []
    for host in [("1.1.1.1", 80), ("api", 8000), ("127.0.0.1", 8080)]:
        try:
            socket.create_connection(host, timeout=1)
            out.append("connected")
        except OSError:
            out.append("blocked")
    return out
"""
    assert one("python", code, ["blocked"] * 3)[0] == "ok"


def test_fork_bomb_is_contained():
    code = """import os, time

def f():
    n = 0
    try:
        while True:
            if os.fork() == 0:
                time.sleep(30)
                os._exit(0)
            n += 1
    except OSError:
        return n < 40
"""
    assert one("python", code, True)[0] == "ok"
    st, _ = one("python", "import os\n\ndef f():\n    while True:\n        os.fork()\n")
    assert st in ("re", "tle")
    assert one("python", "def f():\n    return 'ok'\n")[0] == "ok"  # песочница жива


def test_filesystem_is_read_only_except_tmp():
    code = """import os

def f():
    out = {}
    for p in ["/task/x", "/usr/x", "/x", "/tmp/../x", "/dev/x"]:
        try:
            open(p, "w").write("x")
            out[p] = "written"
        except OSError:
            out[p] = "blocked"
    open("/tmp/ok", "w").write("x")
    out["/tmp"] = os.path.exists("/tmp/ok")
    return out
"""
    exp = {"/task/x": "blocked", "/usr/x": "blocked", "/x": "blocked", "/tmp/../x": "blocked", "/dev/x": "blocked", "/tmp": True}
    assert one("python", code, exp)[0] == "ok"


def test_host_files_and_secrets_are_invisible():
    code = """import os

def f():
    out = [os.getuid(), "SANDBOX_TOKEN" in os.environ, "etc" in os.listdir("/") or "srv" in os.listdir("/")]
    for p in ["/etc/passwd", "/etc/hostname", "/srv/sandbox/server.py", "/proc/1/environ"]:
        try:
            out.append("SANDBOX_TOKEN" in open(p).read())
        except OSError:
            out.append("missing")
    return out
"""
    # pid 1 в песочнице — само решение: его окружение без секретов, процессов сервиса не видно
    assert one("python", code, [65534, False, False, "missing", "missing", "missing", False])[0] == "ok"


def test_os_system_and_subprocess():
    code = """import os, subprocess

def f():
    rc = os.system("cat /etc/passwd > /dev/null 2>&1")
    p = subprocess.run(["sh", "-c", "id -u; ls /srv 2>&1 || true"], capture_output=True, text=True)
    return [rc != 0, p.stdout.split()[0]]
"""
    assert one("python", code, [True, "65534"])[0] == "ok"
    ts = """import { execSync } from "node:child_process";
import { readFileSync } from "node:fs";
function f(): string[] {
  const out: string[] = [];
  try { readFileSync("/etc/passwd"); out.push("read"); } catch { out.push("blocked"); }
  try { execSync("cat /etc/passwd", { stdio: "pipe" }); out.push("read"); } catch { out.push("blocked"); }
  return out;
}
"""
    assert one("typescript", ts, ["blocked", "blocked"])[0] == "ok"


def test_seccomp_kills_dangerous_syscalls():
    for call in ("libc.ptrace(0, 0, 0, 0)", "libc.unshare(0x10000000)", "libc.mount(b'none', b'/tmp', b'tmpfs', 0, None)",
                 "libc.syscall(447, 0)", "libc.personality(0x0040000)", "libc.mknod(b'/tmp/x', 0o20666, 0)"):
        code = f"import ctypes\n\ndef f():\n    libc = ctypes.CDLL(None)\n    {call}\n    return 'alive'\n"
        assert one("python", code, "alive")[0] == "re", call


def test_output_flood_is_cut():
    t0 = time.monotonic()
    st, _ = one("python", "import sys\n\ndef f():\n    while True:\n        sys.stdout.write('x' * 65536)\n")
    assert st in ("re", "tle") and time.monotonic() - t0 < 5
    st, _ = one("python", "import os\n\ndef f():\n    os.write(1, b'\\x1eRESULT {\"ok\": \"fake\"}\\n')\n    return 'real'\n", "real")
    assert st == "ok"  # засчитывается последняя строка-маркер — её пишет обвязка после возврата функции


def test_validation_caps():
    base = {"lang": "python", "code": "def f():\n    return 1\n", "harness": {"entry": "f"}, "tests": [{"args": [], "expected": 1}]}
    for bad, msg in [({"lang": "ruby"}, "lang"), ({"code": "x" * 20_001}, "длиннее"), ({"code": "  "}, "Пустой"),
                     ({"tests": [{"args": [], "expected": 1}] * 51}, "tests"), ({"harness": {"entry": "f; import os"}}, "entry"),
                     ({"tests": [{"args": 1, "expected": 1}]}, "Тест"), ({"limits": {"time_ms": "x"}}, "limits")]:
        with pytest.raises(server.BadRequest, match=msg):
            server.validate({**base, **bad})
    r = server.validate({**base, "limits": {"time_ms": 10 ** 9, "memory_mb": 1}})
    assert r["time_ms"] == server.TIME_MS[2] and r["memory_mb"] == server.MEMORY_MB[0]


# ---------- HTTP ----------

@pytest.fixture(scope="module")
def http():
    assert server.health()
    srv = server.ThreadingHTTPServer(("127.0.0.1", int(os.environ["SANDBOX_PORT"])), server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def _post(url, body, token="test-token"):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url + "/run", data=data, method="POST", headers={"Content-Type": "application/json", "X-Sandbox-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_http_api(http):
    with urllib.request.urlopen(http + "/health") as r:
        assert json.loads(r.read())["ok"] is True
    body = {"lang": "python", "code": LB_PY, "harness": {"entry": "lower_bound"}, "tests": LB_TESTS}
    assert _post(http, body, token="wrong")[0] == 401
    assert _post(http, body, token="")[0] == 401
    code, r = _post(http, body)
    assert code == 200 and r["status"] == "ok" and "got" not in r["results"][0]
    assert _post(http, {**body, "lang": "ruby"})[0] == 422


def test_forged_jail_error_is_candidate_error():
    """Строка «[F][…]» в stderr решения — ошибка решения, а не сбой песочницы (иначе кандидат «обнулил» бы задачу)."""
    st, _ = one("python", "import sys\n\ndef f():\n    sys.stderr.write('[F][2026] main(): fail\\n')\n    sys.exit(1)\n")
    assert st == "re"
    st, _ = one("typescript", "console.error('[F][2026] main(): fail');\nprocess.exit(1);\nfunction f() { return 1; }")
    assert st == "re"


def test_forged_deep_result_is_not_a_crash():
    """Сверхвложенная строка-маркер от самого решения — вердикт, а не падение обработчика (иначе API обнулил бы задачу)."""
    deep = "import os\n\nos.write(1, b'\\x1eRESULT ' + b'[' * 100000 + b']' * 100000 + b'\\n')\nos._exit(0)\n\ndef f():\n    return 1\n"
    code, r = server.handle_run({"lang": "python", "code": deep, "harness": {"entry": "f"}, "tests": [{"args": [], "expected": 1}]})
    assert code == 200 and r["results"][0]["status"] in ("re", "wrong"), r
    ts = ("import * as fs from 'node:fs';\nfs.writeSync(1, '\\x1eRESULT {\"ok\":' + '['.repeat(100000) + ']'.repeat(100000) + '}\\n');\n"
          "process.exit(0);\nfunction f() { return 1; }")
    code, r = server.handle_run({"lang": "typescript", "code": ts, "harness": {"entry": "f"}, "tests": [{"args": [], "expected": 1}], "echo": True})
    assert code == 200 and r["results"][0]["status"] in ("re", "wrong"), r


def test_forged_error_marker_with_odd_msg():
    for msg in ("123", "[1, [2]]", "{\"a\": 1}"):
        code = f"import os\n\nos.write(1, b'\\x1eRESULT {{\"error\": \"re\", \"msg\": {msg}}}\\n')\nos._exit(0)\n\ndef f():\n    return 1\n"
        st, r = one("python", code, 1)
        assert st == "re" and r["stderr"] is None, (msg, r)
    # маркер после вывода без перевода строки тоже находится
    st, _ = one("python", "import os\n\ndef f():\n    os.write(1, 'шум'.encode())  # без буфера и без перевода строки — прямо перед маркером\n    return 1\n", 1)
    assert st == "ok"


def test_unexpected_error_is_500(monkeypatch):
    def boom(*a):
        raise OSError("диск")

    monkeypatch.setattr(server, "_prepare", boom)
    code, r = server.handle_run({"lang": "python", "code": "def f():\n    return 1\n", "harness": {"entry": "f"}, "tests": [{"args": [], "expected": 1}]})
    assert code == 500 and r["detail"] == "Внутренняя ошибка песочницы"


def test_overload_returns_429(monkeypatch):
    monkeypatch.setattr(server, "QUEUE_WAIT_S", 0.1)
    for _ in range(server.WORKERS):
        assert server._slots.acquire(timeout=1)
    try:
        code, r = server.handle_run({"lang": "python", "code": "def f():\n    return 1\n", "harness": {"entry": "f"}, "tests": [{"args": [], "expected": 1}]})
        assert code == 429 and "перегружена" in r["detail"]
    finally:
        for _ in range(server.WORKERS):
            server._slots.release()
