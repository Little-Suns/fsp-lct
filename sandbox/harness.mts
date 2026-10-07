
// ---- обвязка песочницы: дописывается после кода кандидата (тот же модуль, поэтому видна его функция) ----
import * as __sbx_fs from "node:fs";
{
  const emit = (o: unknown) => { __sbx_fs.writeSync(1, "\x1eRESULT " + JSON.stringify(o) + "\n"); };
  const data = JSON.parse(__sbx_fs.readFileSync("/task/input.json", "utf8"));
  const fn = typeof __ENTRY__ === "function" ? __ENTRY__ : undefined;
  if (!fn) emit({ error: "ce", msg: "Не найдена функция " + data.entry });
  else {
    try {
      const res = fn(...data.args);
      const s = JSON.stringify(res ?? null);
      if (s === undefined) emit({ error: "re", msg: "Результат не переводится в JSON" });
      else __sbx_fs.writeSync(1, "\x1eRESULT {\"ok\":" + s + "}\n");
    } catch (e) {
      const name = e && (e as Error).name ? (e as Error).name : "Error";
      const msg = e && (e as Error).message ? String((e as Error).message).slice(0, 200) : String(e).slice(0, 200);
      if (e instanceof RangeError && /call stack/.test(msg)) emit({ error: "re", msg: "RangeError: слишком глубокая рекурсия" });
      else emit({ error: "re", msg: name + ": " + msg });
    }
  }
}
