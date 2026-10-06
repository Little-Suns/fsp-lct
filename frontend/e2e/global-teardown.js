// Сводный отчёт покрытия и порог: ниже COV_MIN (80 %) строк inline-скрипта index.html — прогон падает.
// Строки — метрика V8 (monocart): каждая непустая строка скрипта, частично выполненная считается непокрытой.
// Номера непокрытых строк index.html — в coverage/uncovered-lines.txt.
const fs = require('fs');
const path = require('path');
const MCR = require('monocart-coverage-reports');
const { options, COV_MIN } = require('./coverage');

module.exports = async () => {
  const report = MCR({ ...options });
  if (!report.hasCache()) throw new Error('Покрытие не собрано: ни один тест не открыл страницу');
  const res = await report.generate();
  const pct = res.summary.lines.pct;

  // строка 1 inline-скрипта — строка тега <script> в index.html
  const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
  const shift = html.slice(0, html.indexOf('<script>')).split('\n').length - 1;
  const lines = (res.files[0] && res.files[0].data && res.files[0].data.lines) || {};
  // значение — число выполнений или доля «1/2» для частично выполненной строки
  const miss = Object.entries(lines).filter(([, v]) => v === 0 || typeof v === 'string').map(([n, v]) => `${+n + shift}${v ? ` (частично ${v})` : ''}`);
  fs.writeFileSync(path.join(options.outputDir, 'uncovered-lines.txt'), miss.join('\n') + '\n');

  const S = res.summary, row = k => `${S[k].pct} % (${S[k].covered} из ${S[k].total})`;
  fs.writeFileSync(path.join(options.outputDir, 'summary.md'), `### Покрытие JS фронта (inline-скрипт index.html, V8)\n\n` +
    `| Строки (порог ${COV_MIN} %) | Операторы | Ветви | Функции |\n|---|---|---|---|\n| **${row('lines')}** | ${row('statements')} | ${row('branches')} | ${row('functions')} |\n`);
  console.log(`Покрытие строк JS index.html: ${pct} % (порог ${COV_MIN} %) · отчёт: frontend/coverage/index.html`);
  if (pct < COV_MIN) throw new Error(`Покрытие строк JS ${pct} % ниже порога ${COV_MIN} %`);
};
