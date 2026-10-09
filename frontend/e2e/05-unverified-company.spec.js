// Неподтверждённая компания «Новый Стартап»: плашка и квота 3, приглашение A-1042; кандидат видит плашку
// «компания не подтверждена» в приглашении, поле «О компании» с <img onerror> выводится текстом.
const { test, expect, open, demo, toast, api } = require('./fixtures');
const { XSS } = require('./helpers');

const auth = async page => ({ authorization: 'Bearer ' + await page.evaluate(() => localStorage.getItem('fsp.tok.e')) });

test('«Новый Стартап»: плашка, квота 3, приглашение → кандидат видит предупреждение и принимает', async ({ page }) => {
  test.setTimeout(90_000);
  await demo(page, 'newco');
  const banner = page.locator('.alert.warn', { hasText: 'Компания не прошла проверку.' });
  await expect(banner).toContainText('почта на домене не подтверждена');
  await expect(banner).toContainText('Квота — 3 приглашения в неделю');
  await expect(page.locator('aside b.num').first()).toHaveText('0 / 3');
  await expect(page.getByRole('heading', { name: 'Backend-разработчик (Python)' })).toBeVisible();
  for (const r of ['/e/search', '/e/vacancies', '/e/need']) {
    await open(page, r);
    await expect(banner).toBeVisible();
  }

  // данные компании: проверки не пройдены; «О компании» с HTML-нагрузкой
  await banner.getByRole('button', { name: 'Данные компании' }).click();
  await expect(page.locator('.alert.bad', { hasText: 'ИНН' }).or(page.locator('.alert.bad', { hasText: 'почт' })).first()).toBeVisible();
  await page.getByLabel('О компании, 1–2 предложения').fill(`Edtech, MVP ${XSS}`);
  await page.getByRole('button', { name: 'Сохранить и перейти к поиску' }).click();
  await expect(toast(page)).toHaveText('Компания сохранена без подтверждения: квота 3 приглашения в неделю');
  await expect(page.getByLabel('О компании, 1–2 предложения')).toHaveValue(`Edtech, MVP ${XSS}`);
  expect(await page.evaluate(() => window.__xss)).toBeUndefined();

  // приглашение A-1042 по потребности (адрес с ?need=): вилка от 25-го перцентиля рынка его грейда
  const needId = (await (await page.request.get('/api/employer/needs', { headers: await auth(page) })).json())[0].id;
  await open(page, `/e/invite/A-1042?need=${needId}`);
  await expect(page.getByRole('heading', { name: 'Приглашение для A-1042' })).toBeVisible();
  await expect(banner).toBeVisible();
  await expect(page.locator('#f-msgs .alert.bad')).toContainText('ниже 25-го перцентиля');  // вилка потребности джуна
  const p25 = +(await page.locator('dt', { hasText: '25-й перцентиль' }).locator('xpath=following-sibling::dd[1]').textContent()).replace(/\D/g, '');
  await page.getByLabel('от', { exact: true }).fill(String(p25));
  await page.getByLabel('до', { exact: true }).fill(String(Math.max(Math.round(p25 * 1.3), 240000)));
  await expect(page.locator('#f-msgs .alert.bad')).toHaveCount(0);
  await expect(page.getByText('после отправки: 1')).toBeVisible();
  const inv = api(page, 'POST', '/api/employer/invites');
  await page.getByRole('button', { name: 'Отправить приглашение' }).click();
  expect((await inv).status()).toBe(200);
  await expect(toast(page)).toContainText('Приглашение отправлено');
  await expect(page.getByRole('row', { name: /A-1042/ })).toContainText('отправлено');
  await expect(page.getByText(/квота 1 \/ 3/)).toBeVisible();

  // ещё два приглашения из подборки исчерпывают квоту 3: четвёртое отправить нельзя
  const fork = async () => {
    const p = +(await page.locator('dt', { hasText: '25-й перцентиль' }).locator('xpath=following-sibling::dd[1]').textContent()).replace(/\D/g, '');
    const min = +(await page.locator('.panel', { hasText: 'Кандидат ожидает' }).locator('b').textContent()).replace(/\D/g, '');
    const from = Math.max(p, Math.round(min / 1.3));
    await page.getByLabel('от', { exact: true }).fill(String(from));
    await page.getByLabel('до', { exact: true }).fill(String(Math.round(from * 1.3)));
  };
  await open(page, '/e/picks');
  const picks = (await (await page.request.get('/api/employer/needs', { headers: await auth(page) })).json())[0];
  const list = (await (await page.request.get(`/api/employer/needs/${picks.id}/picks?limit=20`, { headers: await auth(page) })).json()).items
    .filter(c => !c.invited && !c.busy && c.id !== 'A-1042');
  for (const c of list.slice(0, 2)) {
    await open(page, `/e/invite/${c.id}?need=${picks.id}`);
    await expect(page.getByRole('heading', { name: 'Приглашение для ' + c.id })).toBeVisible();
    await fork();
    await page.getByRole('button', { name: 'Отправить приглашение' }).click();
    await expect(page.getByRole('row', { name: new RegExp(c.id) })).toBeVisible();
  }
  await expect(page.getByText(/квота 3 \/ 3/)).toBeVisible();
  await open(page, `/e/invite/${list[2].id}?need=${picks.id}`);
  await expect(page.getByText('Квота на неделю исчерпана. Обновится в понедельник.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Отправить приглашение' })).toBeDisabled();

  // кандидат: приглашение помечено, внутри — плашка и описание компании текстом
  await demo(page, 'c');
  const card = page.locator('button.inv', { hasText: 'Новый Стартап' });
  await expect(card).toContainText('почта на домене не подтверждена');
  await card.click();
  await expect(page.locator('.alert.warn', { hasText: 'Почта на домене не подтверждена.' })).toContainText('Не передавайте паспортные и платёжные данные');
  await expect(page.locator('.chip.warn', { hasText: 'почта на домене не подтверждена' })).toBeVisible();
  await expect(page.getByText(`Edtech, MVP ${XSS}`)).toBeVisible();
  expect(await page.evaluate(() => window.__xss)).toBeUndefined();
  await expect(page.locator('aside')).toContainText('Алина Мельникова');
  await page.getByRole('button', { name: 'Принять и открыть мои контакты' }).click();
  await expect(page.getByText('Вы приняли приглашение.', { exact: true })).toBeVisible();

  // компания видит контакты после принятия
  await demo(page, 'newco');
  await open(page, '/e/pipeline');
  await expect(page.getByRole('row', { name: /A-1042/ })).toContainText('Дмитрий Орлов');
});

test('«Новый Стартап»: лимит 2 открытых вакансии — кабинет показывает лимит, третья — 409, закрытие освобождает место', async ({ page }) => {
  await demo(page, 'newco');
  const h = await auth(page);
  const body = t => ({ data: { title: t, spec: 'QA', track: 'Manual', grade: 'Junior', salary_from: 90000, salary_to: 110000, format: 'Удалённо' }, headers: h });
  for (const t of ['QA лимит первая', 'QA лимит вторая']) expect((await page.request.post('/api/vacancies', body(t))).status()).toBe(200);
  const over = await page.request.post('/api/vacancies', body('QA лимит третья'));
  expect(over.status()).toBe(409);
  expect((await over.json()).detail).toContain('Подтвердите компанию');

  await open(page, '/e/vacancies');
  const limit = page.locator('.panel', { hasText: 'Открытые вакансии' });
  await expect(limit).toContainText('2 / 2');
  await expect(limit).toContainText('Сейчас лимит исчерпан');
  await expect(limit).toContainText('Подтвердите компанию (ИНН и рабочая почта на домене сайта) — лимит вырастет.');
  await expect(page.getByRole('button', { name: 'Новая вакансия' })).toBeDisabled();
  await page.locator('.panel', { hasText: 'QA лимит первая' }).getByRole('button', { name: 'Закрыть' }).click();
  await expect(toast(page)).toHaveText('Вакансия закрыта');
  await expect(limit).toContainText('1 / 2');
  await expect(page.getByRole('button', { name: 'Новая вакансия' })).toBeEnabled();
  // вторую тоже закрываем: вакансии «Нового Стартапа» не должны попадать в списки кандидатов в следующих сценариях
  await page.locator('.panel', { hasText: 'QA лимит вторая' }).getByRole('button', { name: 'Закрыть' }).click();
  await expect(limit).toContainText('0 / 2');
});
