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
  expect(typeof feed.next).toBe('string');
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

test('Mock ATS: ключ → вакансия из ATS → отклик → событие без контактов → приглашение → контакты', async ({ page }) => {
  await demo(page, 'e');
  await open(page, '/employer/company');
  const panel = page.locator('#ats');
  await panel.locator('#ak-name').fill('e2e-mock-ats');
  for (const s of ['vacancies:write', 'applications:read', 'applications:write']) await panel.locator(`input[data-scope="${s}"]`).check();
  const issued = api(page, 'POST', '/api/employer/api-keys');
  await panel.getByRole('button', { name: 'Выпустить ключ' }).click();
  const { key } = await (await issued).json();
  const { token: empToken } = await (await page.request.post('/api/auth/demo/employer')).json();

  await page.goto('/mock-ats');
  await expect(page.locator('#vac select[name=format] option')).not.toHaveCount(0);  // справочники подгрузились
  await page.locator('#key').fill(key);
  await page.locator('#connect').click();
  await expect(page.locator('#state')).toContainText('Подключено');

  // вакансия из «ATS»: ответ API и запись в кабинете компании
  const title = 'Mock ATS e2e ' + Date.now();
  await page.locator('#vac [name=external_id]').fill('mock-' + Date.now());
  await page.locator('#vac [name=title]').fill(title);
  const put = page.waitForResponse(r => r.request().method() === 'PUT' && r.url().includes('/api/ats/v1/vacancies/'));
  await page.locator('#vac').getByRole('button', { name: 'Опубликовать' }).click();
  const vac = await (await put).json();
  expect(vac.id).toBeGreaterThan(0);
  await expect(page.locator('#vres')).toContainText('Опубликовано: вакансия #' + vac.id);
  {
    const mine = await (await page.request.get('/api/vacancies/mine', { headers: { Authorization: 'Bearer ' + empToken } })).json();
    expect((mine.items || mine).some(v => v.id === vac.id && v.title === title)).toBe(true);
  }

  // демо-кандидат (Орлов: тест пройден, в лимите откликов ~6 из APPLICATIONS_PER_WEEK) откликается; спек идёт до 13-grade-integrity, сбрасывающего его тест
  const cand = await page.request.post('/api/auth/demo/candidate');
  const { token } = await cand.json();
  const applied = await page.request.post(`/api/vacancies/${vac.id}/apply`, { headers: { Authorization: 'Bearer ' + token }, data: {} });
  expect(applied.status()).toBe(200);
  const appId = (await applied.json()).id;

  // событие нового отклика (старые события Орлова из других спеков — с его контактами — в ленте тоже есть, поэтому только по application_id)
  const ev = page.locator(`#feed .ev[data-event-type="application.created"][data-application-id="${appId}"]`);
  await expect(ev).toBeVisible({ timeout: 10_000 });
  await expect(ev).toContainText(title);
  await expect(ev.locator('.contacts')).toHaveCount(0);
  await expect(ev).not.toContainText('d.orlov@example.ru');

  // приглашение на интервью — контакты приходят событием статуса этого отклика
  const st = page.waitForResponse(r => r.request().method() === 'POST' && new RegExp(`/applications/${appId}/status$`).test(r.url()));
  await ev.getByRole('button', { name: 'Пригласить на интервью' }).click();
  expect((await st).ok()).toBe(true);
  const accepted = page.locator(`#feed .ev[data-event-type="application.status"][data-application-id="${appId}"]`).filter({ hasText: 'Статус: accepted' });
  await expect(accepted.locator('.contacts')).toContainText('d.orlov@example.ru', { timeout: 10_000 });
});
