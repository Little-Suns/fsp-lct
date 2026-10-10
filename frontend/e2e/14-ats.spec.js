// Интеграция с ATS: ключ API в кабинете компании (виден один раз), лента событий по ключу, отзыв ключа.
const { test, expect, open, demo, toast, api } = require('./fixtures');

test('ключ API: выпуск, один показ, лента событий по ключу, отзыв', async ({ page }) => {
  await demo(page, 'e');
  await open(page, '/employer/company');
  const panel = page.locator('#ats');
  await expect(panel.getByRole('heading', { name: 'Интеграция с ATS' })).toBeVisible();
  await expect(panel.getByRole('link', { name: 'Открыть Mock ATS' })).toHaveAttribute('href', '/mock-ats');

  // без названия и без областей ключ не выпускается
  await panel.getByRole('button', { name: 'Выпустить ключ' }).click();
  await expect(toast(page)).toContainText('Назовите ключ');
  await panel.locator('#ak-name').fill('e2e-ключ');
  await panel.getByRole('button', { name: 'Выпустить ключ' }).click();
  await expect(toast(page)).toContainText('область');

  await panel.locator('input[data-scope="applications:read"]').check();
  await panel.locator('input[data-scope="invites:read"]').check();
  const issued = api(page, 'POST', '/api/employer/api-keys');
  await panel.getByRole('button', { name: 'Выпустить ключ' }).click();
  const body = await (await issued).json();
  expect(body.key).toMatch(/^fsp_/);
  expect(body).toHaveProperty('prefix');
  await expect(panel.locator('#ak-key')).toHaveText(body.key);
  await expect(panel.getByText('Больше не покажем')).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Скопировать' })).toBeVisible();

  // список: название и начало ключа, полного ключа в нём нет
  const row = panel.locator(`[data-key="${body.id}"]`);
  await expect(row).toContainText('e2e-ключ');
  await expect(row).toContainText(body.prefix);
  await expect(row).toContainText('applications:read');
  await expect(row).toContainText('не вызывался');
  await expect(row).not.toContainText(body.key);

  // лента по ключу: 200, форма ответа — {items, next}
  const ev = await page.request.get('/api/ats/v1/events?after=0&limit=10', { headers: { 'X-Api-Key': body.key } });
  expect(ev.status()).toBe(200);
  const feed = await ev.json();
  expect(Array.isArray(feed.items)).toBe(true);
  expect(typeof feed.next).toBe('number');
  // без ключа и с чужим — 401
  expect((await page.request.get('/api/ats/v1/events')).status()).toBe(401);
  expect((await page.request.get('/api/ats/v1/events', { headers: { 'X-Api-Key': 'fsp_wrong' } })).status()).toBe(401);
  // область не выдана — 403
  const wr = await page.request.put('/api/ats/v1/vacancies/e2e-1', { headers: { 'X-Api-Key': body.key }, data: {} });
  expect(wr.status()).toBe(403);

  // «Я сохранил ключ» — ключ исчезает, после перезагрузки экрана в списке только начало
  await panel.getByRole('button', { name: 'Я сохранил ключ' }).click();
  await expect(panel.locator('#ak-key')).toHaveCount(0);
  await open(page, '/employer');
  await open(page, '/employer/company');
  await expect(panel.locator(`[data-key="${body.id}"]`)).toContainText('последний вызов');
  await expect(panel.locator('#ak-key')).toHaveCount(0);

  // отзыв: ключ перестаёт работать
  const del = api(page, 'DELETE', `/api/employer/api-keys/${body.id}`);
  await panel.locator(`[data-key="${body.id}"]`).getByRole('button', { name: 'Отозвать' }).click();
  expect((await del).ok()).toBe(true);
  await expect(panel.locator(`[data-key="${body.id}"]`)).toContainText('отозван');
  await expect(panel.locator(`[data-key="${body.id}"]`).getByRole('button', { name: 'Отозвать' })).toHaveCount(0);
  const after = await page.request.get('/api/ats/v1/events', { headers: { 'X-Api-Key': body.key } });
  expect(after.status()).toBe(401);
});
