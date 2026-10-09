// Организатор: импорт протоколов ФСП и хакатонов и подтверждение CTFtime со страницы /org.
// Токен организатора — ORGANIZER_TOKEN из e2e/server.sh; сопоставляется демо-кандидат Орлов (ФСП ID FSP-1042).
const { test, expect, open, toast, api } = require('./fixtures');
const { XSS } = require('./helpers');

const TOKEN = 'e2e-organizer-token';

async function login(page, token = TOKEN) {
  await page.getByLabel('Токен организатора').fill(token);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
}

test('организатор: вход по токену, импорт примера протокола ФСП и повтор', async ({ page }) => {
  await open(page, '/v');
  await page.getByRole('button', { name: 'Организатору: импорт протоколов →' }).click();
  await expect(page.getByRole('heading', { name: 'Импорт протоколов соревнований' })).toBeVisible();
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(toast(page)).toHaveText('Введите токен организатора');
  // неверный токен: сервер отвечает 401 — назад ко входу, кабинеты кандидата и работодателя не трогаются
  await login(page, 'wrong-token');
  // пусто — ошибка до запроса
  await page.getByRole('button', { name: 'Импортировать' }).click();
  await expect(page.getByRole('alert')).toHaveText(/Вставьте протокол/);
  await page.getByRole('button', { name: 'Демо: подставить пример' }).click();
  const bad = api(page, 'POST', '/api/achievements/import');
  await page.getByRole('button', { name: 'Импортировать' }).click();
  expect((await bad).status()).toBe(401);
  await expect(page.getByRole('alert')).toHaveText(/Токен организатора не подошёл/);
  await expect(page).toHaveURL(/#\/org$/);
  // токен организатора не попадает в localStorage
  expect(await page.evaluate(() => Object.keys(localStorage).filter(k => k.includes('org')))).toEqual([]);

  await login(page);
  await expect(page.getByRole('alert')).toBeHidden();
  // форма пережила неудачный вход: пример на месте
  await expect(page.getByLabel('Источник')).toHaveValue('fsp');
  await expect(page.getByLabel('CSV или JSON, до 2 МБ')).toHaveValue(/FSP-1042/);
  const ok = api(page, 'POST', '/api/achievements/import');
  await page.getByRole('button', { name: 'Импортировать' }).click();
  expect((await ok).status()).toBe(200);
  await expect(toast(page)).toHaveText('Протокол импортирован');
  const res = page.locator('#org-res');
  await expect(res).toContainText('Протокол загружен');
  await expect(res).toContainText('Строк: 2');
  await expect(res).toContainText('Сопоставлено с кандидатами: 1');
  await expect(res).toContainText('Новых достижений: 1 · обновлено: 0');
  await expect(res).toContainText('Не привязано: 1');
  await expect(res.getByRole('row', { name: /2 кандидат не найден/ })).toBeVisible();
  await expect(res).not.toContainText('FSP-0000');  // идентификаторы участников обратно не выводятся
  // повторный импорт того же события обновляет, а не дублирует
  await page.getByRole('button', { name: 'Импортировать' }).click();
  await expect(res).toContainText('Новых достижений: 0 · обновлено: 1');
  // событие видно в публичном списке с одним кандидатом платформы
  const events = await (await page.request.get('/api/achievements/events?source=fsp')).json();
  expect(events.find(e => e.external_id === 'demo-cup-2026').candidates).toBe(1);

  await page.getByRole('button', { name: 'Выйти', exact: true }).click();
  await expect(page.getByLabel('Токен организатора')).toBeVisible();
});

test('организатор: подтверждение CTFtime файлом JSON, ошибки формата без XSS', async ({ page }) => {
  await open(page, '/');
  await page.getByRole('button', { name: 'Экраны' }).click();
  await page.getByRole('dialog', { name: 'Карта экранов' }).getByRole('button', { name: /Импорт протоколов/ }).click();
  await expect(page).toHaveURL(/#\/org$/);
  await login(page);
  await page.getByLabel('Источник').selectOption('ctftime');
  await page.getByLabel('Идентификатор события').fill('2950');
  await page.getByLabel('Название').fill('CTF-турнир, финал');
  await page.getByLabel('Участников всего').fill('300');
  // файл попадает в поле текста; JSON-массив строк уходит вместе с полями события
  await page.locator('#org-file').setInputFiles({ name: 'ctf.json', mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify([{ email: 'd.orlov@example.ru', team: 'Сапсан', place: 4 }, { fsp_id: '' }])) });
  await expect(page.getByLabel('CSV или JSON, до 2 МБ')).toHaveValue(/d\.orlov@example\.ru/);
  await expect(page.getByLabel('Название')).toHaveValue('CTF-турнир, финал');  // ввод не потерялся при перерисовке
  await page.getByRole('button', { name: 'Импортировать' }).click();
  const res = page.locator('#org-res');
  await expect(res).toContainText('Сопоставлено с кандидатами: 1');
  await expect(res.getByRole('row', { name: /2 нет email и fsp_id/ })).toBeVisible();

  // битый JSON — ошибка на клиенте
  await page.getByLabel('CSV или JSON, до 2 МБ').fill('[{"email": ');
  await page.getByRole('button', { name: 'Импортировать' }).click();
  await expect(page.getByRole('alert')).toHaveText(/похож на JSON, но не разбирается/);
  await expect(res).toBeHidden();
  // ошибка сервера с эхом ввода (неизвестная дисциплина) выводится текстом, а не разметкой
  await page.getByLabel('Дисциплина ФСП').fill(XSS);
  await page.getByLabel('CSV или JSON, до 2 МБ').fill('email,fsp_id\nd.orlov@example.ru,');
  const bad = api(page, 'POST', '/api/achievements/import');
  await page.getByRole('button', { name: 'Импортировать' }).click();
  expect((await bad).status()).toBe(422);
  await expect(page.getByRole('alert')).toContainText('discipline: «<img');
  expect(await page.evaluate(() => window.__xss)).toBeUndefined();
});
