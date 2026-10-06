// Общие фикстуры: страница со сбором V8-покрытия, помощники входа и навигации по хеш-маршрутам.
const base = require('@playwright/test');
const MCR = require('monocart-coverage-reports');
const { options, APP_JS, isAppScript } = require('./coverage');

const test = base.test.extend({
  page: async ({ page, baseURL }, use) => {
    // SLOW=4 — замедлить CPU страницы в 4 раза (как медленный раннер CI), чтобы ловить гонки локально
    // LATENCY=150 — задержка каждого ответа, мс (медленный бэкенд/сеть раннера)
    if (process.env.SLOW || process.env.LATENCY) {
      const cdp = await page.context().newCDPSession(page);
      if (process.env.SLOW) await cdp.send('Emulation.setCPUThrottlingRate', { rate: +process.env.SLOW || 4 });
      if (process.env.LATENCY) {
        await cdp.send('Network.enable');
        await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: +process.env.LATENCY, downloadThroughput: -1, uploadThroughput: -1 });
      }
    }
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

// приложение дорисовало экран: пока грузится следующий, #app помечен aria-busy (и inert)
const settled = page => expect(page.locator('#app')).not.toHaveAttribute('aria-busy', 'true');

// экран по хеш-маршруту и ожидание его загрузки (без входа приложение само уводит на экран входа)
async function open(page, route) {
  if (!page.url().startsWith('http')) await page.goto('/#' + route);
  else {
    // busy ставим синхронно вместе со сменой хеша: иначе ожидание успело бы увидеть прежний, уже готовый экран
    await page.evaluate(r => {
      if (location.hash === '#' + r) return;
      document.getElementById('app').setAttribute('aria-busy', 'true');
      location.hash = '#' + r;
    }, route);
  }
  await settled(page);
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
  // ждём сам экран после входа (крошки), а не любой заголовок: на экране входа тоже есть h1
  await expect(page.locator('#app .crumbs b')).toHaveText(who === 'c' ? 'Кабинет кандидата' : 'Подборка');
  await settled(page);
}

// ответ API, на который ждём после клика (путь — строка или RegExp)
const api = (page, method, path) => page.waitForResponse(r => {
  const p = new URL(r.url()).pathname;
  return r.request().method() === method && (path instanceof RegExp ? path.test(p) : p === path);
});

module.exports = { test, expect, open, demo, toast, api, settled };
