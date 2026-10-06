// Покрытие JS: V8-покрытие каждой страницы → monocart (кэш в coverage/.cache) → отчёт и порог в global-teardown.
// Считается только inline-скрипт index.html: у него url страницы, у остальных скриптов (если появятся) — свой файл.
const path = require('path');

const COV_MIN = Number(process.env.COV_MIN || 80);
const APP_JS = 'index.html.inline.js';

const options = {
  name: 'ФСП Карьера — покрытие JS фронта (inline-скрипт index.html)',
  outputDir: path.join(__dirname, '..', 'coverage'),
  reports: ['console-summary', 'v8', 'lcovonly'],
  // inline-скрипт страницы приходит с url документа (с хешем маршрута) — сводим к одному «файлу»
  entryFilter: e => e.url.endsWith(APP_JS),
  cleanCache: false,
};

// url V8-записи inline-скрипта — сам документ: http://host:port/ или http://host:port/#/…
function isAppScript(url, baseURL) {
  const u = new URL(url);
  return u.origin === new URL(baseURL).origin && (u.pathname === '/' || u.pathname === '/index.html');
}

module.exports = { options, COV_MIN, APP_JS, isAppScript };
