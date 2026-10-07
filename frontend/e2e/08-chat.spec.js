// Чат: работодатель ↔ кандидат на принятом приглашении «Ладога Пэй» ↔ A-1042 (его принимает 04-employer).
const { test, expect, demo, open, api, settled, toast } = require('./fixtures');

// сообщение кандидата A-1042 компании «Ладога Пэй» его токеном (оба токена лежат в localStorage одной страницы)
const candidateSays = (page, text) => page.evaluate(async t => {
  const h = { Authorization: 'Bearer ' + localStorage.getItem('fsp.tok.c'), 'Content-Type': 'application/json' };
  const { contacts } = await (await fetch('/api/chat/contacts', { headers: h })).json();
  const r = await fetch('/api/chat/' + contacts[0].peer_id, { method: 'POST', headers: h, body: JSON.stringify({ text: t }) });
  if (!r.ok) throw new Error('POST ' + r.status);
}, text);

const XSS = '<img src=x onerror="window.__xss=1">';

test('Чат: сообщение, бейдж, прочитано, ответ', async ({ page }) => {
  // работодатель пишет из строки приглашения
  await demo(page, 'e');
  await open(page, '/e/pipeline');
  await page.getByRole('row', { name: /A-1042/ }).getByRole('button', { name: 'Написать в чат' }).click();
  await settled(page);
  await expect(page).toHaveURL(/#\/e\/chat\/A-1042$/);
  await expect(page.locator('.chat-box')).toContainText('Дмитрий Орлов');  // принял приглашение — имя открыто
  await expect(page.locator('#chat-messages')).toContainText('Здесь будет история переписки');
  await page.locator('#chat-input').fill(`Здравствуйте! Это Ладога. ${XSS}`);
  const sent = api(page, 'POST', '/api/chat/A-1042');
  await page.getByRole('button', { name: 'Отправить' }).click();
  expect((await sent).status()).toBe(200);
  await expect(page.locator('#chat-messages')).toContainText('Здравствуйте! Это Ладога.');
  await expect(page.locator('#chat-messages img')).toHaveCount(0);  // текст экранирован
  expect(await page.evaluate(() => window.__xss)).toBeUndefined();
  await expect(page.locator('#chat-input')).toHaveValue('');

  // кандидат видит бейдж в разделах и список диалогов, открытие гасит бейдж
  await demo(page, 'c');
  const chip = page.locator('nav.chips').getByRole('button', { name: /^Чат/ });
  await expect(chip).toContainText('1');
  // цифра помещается в бейдж: раньше .dot таймлайна (14×14 с рамкой) перебивал стиль бейджа
  const fits = el => el.scrollWidth <= el.clientWidth && el.scrollHeight <= el.clientHeight && el.clientWidth >= 18;
  expect(await chip.locator('.unread').evaluate(fits)).toBe(true);
  await chip.click();
  await settled(page);
  await expect(page.locator('.chat-peer', { hasText: 'Ладога Пэй' })).toContainText('Здравствуйте!');
  expect(await page.locator('.chat-peer', { hasText: 'Ладога Пэй' }).locator('.unread').evaluate(fits)).toBe(true);
  await expect(page.locator('.chat-box')).toContainText('выберите диалог', { ignoreCase: true });
  await page.locator('.chat-peer', { hasText: 'Ладога Пэй' }).click();
  await settled(page);
  await expect(page.locator('#chat-messages')).toContainText('Здравствуйте! Это Ладога.');
  await expect(page.locator('nav.chips').getByRole('button', { name: /^Чат$/ })).toBeVisible();

  // Enter отправляет, Shift+Enter — перенос строки
  await page.locator('#chat-input').fill('Добрый день');
  await page.locator('#chat-input').press('Shift+Enter');
  await page.locator('#chat-input').type('Готов обсудить.');
  await page.locator('#chat-input').press('Enter');
  await expect(page.locator('.msg.me').last()).toContainText('Добрый день');
  await expect(page.locator('.msg.me').last()).toContainText('Готов обсудить.');

  // работодатель: бейдж, ответ, и его сообщение отмечено прочитанным
  await demo(page, 'e');
  await expect(page.locator('nav.chips').getByRole('button', { name: /^Чат/ })).toContainText('1');
  await page.locator('nav.chips').getByRole('button', { name: /^Чат/ }).click();
  await settled(page);
  await page.locator('.chat-peer', { hasText: 'Дмитрий Орлов' }).click();
  await settled(page);
  await expect(page.locator('#chat-messages')).toContainText('Готов обсудить.');
  await expect(page.locator('.msg.me time span[title="прочитано"]')).toHaveCount(1);

  // новое сообщение от кандидата приходит само (push по SSE), черновик не теряется
  await page.locator('#chat-input').fill('черновик ответа');
  await candidateSays(page, 'Ещё вопрос про вилку');
  await expect(page.locator('#chat-messages')).toContainText('Ещё вопрос про вилку');
  await expect(page.locator('#chat-input')).toHaveValue('черновик ответа');
  await expect(page.locator('nav.chips').getByRole('button', { name: /^Чат$/ })).toBeVisible();  // открытый диалог сразу прочитан

  // вне чата бейдж появляется сам, без перехода по экранам
  await open(page, '/e/pipeline');
  await candidateSays(page, 'Вы здесь?');
  await expect(page.locator('nav.chips').getByRole('button', { name: /^Чат/ })).toContainText('1');
});

test('Чат: кнопки «Написать», недоступный диалог, догрузка истории', async ({ page }) => {
  await demo(page, 'c');  // токен кандидата нужен candidateSays
  await demo(page, 'e');
  // карточка кандидата с принятым приглашением
  await open(page, '/e/cand/A-1042');
  await expect(page.getByRole('button', { name: 'Написать в чат' })).toBeVisible();
  // чужой кандидат без связи: кнопки нет, а прямой переход показывает понятное сообщение
  await open(page, '/e/search');
  const other = await page.evaluate(async () => {
    const r = await fetch('/api/employer/search?limit=5', { headers: { Authorization: 'Bearer ' + localStorage.getItem('fsp.tok.e') } });
    return (await r.json()).items.map(c => c.id).find(id => id !== 'A-1042');
  });
  await open(page, '/e/cand/' + other);
  await expect(page.getByRole('button', { name: 'Написать в чат' })).toHaveCount(0);
  await open(page, '/e/chat/' + other);
  await expect(page.locator('.chat-box')).toContainText('Диалог недоступен');

  // «Показать ранее»: бэкенд отдаёт more=true, старая страница подгружается перед текущими
  await page.route('**/api/chat/A-1042*', async r => {
    if (r.request().method() !== 'GET') return r.fallback();
    if (r.request().url().includes('before_id=')) {
      return r.fulfill({ json: { peer: { id: 'A-1042', name: 'Дмитрий Орлов' }, more: false, messages: [{ id: 1, sender: 'candidate', text: 'Самое раннее сообщение', created_at: '2026-01-01T10:00:00+03:00', read_at: null }] } });
    }
    const res = await r.fetch();
    await r.fulfill({ response: res, json: { ...(await res.json()), more: true } });
  });
  await open(page, '/e/chat/A-1042');
  await page.getByRole('button', { name: 'Показать ранее' }).click();
  await expect(page.locator('#chat-messages')).toContainText('Самое раннее сообщение');
  await expect(page.getByRole('button', { name: 'Показать ранее' })).toHaveCount(0);
  await page.unroute('**/api/chat/A-1042*');

  // писать больше нельзя (can_write=false): вместо поля ввода пояснение
  await page.route('**/api/chat/A-1042', async r => {
    if (r.request().method() !== 'GET') return r.fallback();
    const res = await r.fetch();
    await r.fulfill({ response: res, json: { ...(await res.json()), can_write: false } });
  });
  await open(page, '/e/pipeline');
  await open(page, '/e/chat/A-1042');
  await expect(page.getByText('Писать больше нельзя')).toBeVisible();
  await expect(page.locator('#chat-input')).toHaveCount(0);
  await page.unroute('**/api/chat/A-1042');

  // доступ закрыт посреди сессии: уведомление приходит, перечитывание отдаёт 403 — загруженная переписка убирается с экрана
  await open(page, '/e/pipeline');
  await open(page, '/e/chat/A-1042');
  await expect(page.locator('#chat-input')).toBeVisible();
  await page.route('**/api/chat/A-1042', r => r.request().method() === 'GET' ? r.fulfill({ status: 403, json: { detail: 'закрыт' } }) : r.fallback());
  await candidateSays(page, 'Последнее сообщение');
  await expect(page.locator('.chat-box')).toContainText('Диалог недоступен');
  await page.unroute('**/api/chat/A-1042');

  // кандидат: кнопка в приглашении и в списке диалогов; ошибка отправки — тостом
  await demo(page, 'c');
  await page.locator('button.inv', { hasText: 'Ладога Пэй' }).click();
  await page.getByRole('button', { name: 'Написать в чат' }).click();
  await settled(page);
  await expect(page).toHaveURL(/#\/c\/chat\/\d+$/);
  await page.route('**/api/chat/*', r => r.request().method() === 'POST' && !r.request().url().endsWith('/read') ? r.fulfill({ status: 429, json: { detail: 'Слишком часто: подождите минуту' } }) : r.fallback());
  await page.locator('#chat-input').fill('спам');
  await page.getByRole('button', { name: 'Отправить' }).click();
  await expect(toast(page)).toHaveText('Слишком часто: подождите минуту');
  await expect(page.locator('#chat-input')).toHaveValue('спам');
  await page.unroute('**/api/chat/*');
});
