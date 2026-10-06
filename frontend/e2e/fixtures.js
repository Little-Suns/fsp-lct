// Общие фикстуры: страница со сбором V8-покрытия, помощники входа и навигации по хеш-маршрутам.
const base = require('@playwright/test');
const MCR = require('monocart-coverage-reports');
const { options, APP_JS, isAppScript } = require('./coverage');

const test = base.test.extend({
  page: async ({ page, baseURL }, use) => {
    await page.coverage.startJSCoverage({ resetOnNavigation: false });
    await use(page);
    const entries = (await page.coverage.stopJSCoverage())
      .filter(e => isAppScript(e.url, baseURL))
      .map(e => ({ ...e, url: `${baseURL}/${APP_JS}` }));
    // по одной записи: после reload у страницы два экземпляра скрипта с одним url — в одном add() выжил бы последний
    for (const e of entries) await MCR({ ...options }).add([e]);
  },
});
const { expect } = base;

// экран по хеш-маршруту (дальше ждут локаторы: без входа приложение само уводит на экран входа)
async function open(page, route) {
  if (!page.url().startsWith('http')) await page.goto('/#' + route);
  else await page.evaluate(r => { location.hash = '#' + r; }, route);
}

const toast = page => page.locator('#toast');

// демо-вход кнопками экрана входа: c — Дмитрий Орлов (A-1042), e — «Ладога Пэй», newco — «Новый Стартап»
async function demo(page, who) {
  const signup = who === 'c' ? '/c/signup' : '/e/signup';
  await open(page, signup);
  if (who !== 'c') {  // работодатель уже вошёл — на экране компании сначала «Выйти»
    const out = page.locator('#app').getByRole('button', { name: 'Выйти' });
    await expect(page.getByRole('heading', { name: 'Вход для компаний' }).or(out)).toBeVisible();
    if (await out.isVisible()) {
      await out.click();
      await expect(page.getByRole('heading', { name: 'Вход для компаний' })).toBeVisible();
    }
  }
  const label = { c: 'Демо: войти как Дмитрий Орлов', e: 'Демо: войти как «Ладога Пэй»', newco: 'Демо: войти как «Новый Стартап»' }[who];
  await page.getByRole('button', { name: label }).click();
  await page.waitForFunction(w => location.hash === (w === 'c' ? '#/c/home' : '#/e/picks'), who);
  await expect(page.locator('#app h2, #app h1').first()).toBeVisible();
}

// ответ API, на который ждём после клика (путь — строка или RegExp)
const api = (page, method, path) => page.waitForResponse(r => {
  const p = new URL(r.url()).pathname;
  return r.request().method() === method && (path instanceof RegExp ? path.test(p) : p === path);
});

module.exports = { test, expect, open, demo, toast, api };
