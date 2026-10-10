// Чат: работодатель ↔ кандидат на принятом приглашении «Ладога Пэй» ↔ A-1042 (его принимает 04-employer).
const { test, expect, demo, open, api, settled, toast } = require('./fixtures');

// сообщение кандидата A-1042 компании «Ладога Пэй» его токеном (оба токена лежат в localStorage одной страницы)
const candidateSays = (page, text) => page.evaluate(async t => {
  const h = { Authorization: 'Bearer ' + localStorage.getItem('fsp.tok.c'), 'Content-Type': 'application/json' };
  const { contacts } = await (await fetch('/api/chat/contacts', { headers: h })).json();
  const r = await fetch('/api/chat/' + contacts[0].peer_id, { method: 'POST', headers: h, body: JSON.stringify({ text: t }) });
  if (!r.ok) throw new Error('POST ' + r.status);
}, text);

// обратимое скрытие профиля кандидата от компании «Ладога Пэй» на живом бэкенде (PATCH /api/candidate/hidden-from):
// после него диалог для работодателя недоступен (403). Возвращает токен кандидата и прежний список ИНН для restoreHidden.
const hideFromCompany = page => page.evaluate(async () => {
  const h = who => ({ Authorization: 'Bearer ' + localStorage.getItem('fsp.tok.' + who), 'Content-Type': 'application/json' });
  const { inn } = await (await fetch('/api/employer/company', { headers: h('e') })).json();
  const prev = (await (await fetch('/api/candidate/me', { headers: h('c') })).json()).hidden_from || [];
  const r = await fetch('/api/candidate/hidden-from', { method: 'PATCH', headers: h('c'), body: JSON.stringify({ inns: [...prev, inn] }) });
  if (!r.ok) throw new Error('PATCH ' + r.status);
  return { token: localStorage.getItem('fsp.tok.c'), prev };
});
// возврат — через APIRequestContext с заранее считанным токеном: срабатывает и если страница уже закрыта
const restoreHidden = async (request, { token, prev }) => {
  const r = await request.patch('/api/candidate/hidden-from', { headers: { Authorization: 'Bearer ' + token }, data: { inns: prev } });
  if (!r.ok()) throw new Error('PATCH ' + r.status());
};
// сигнал «вернулись на вкладку» запускает перечитывание (SSE о скрытии профиля событие не шлёт)
const recheck = page => page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));

const XSS = '<img src=x onerror="window.__xss=1">';

test('Чат: сообщение, красная точка, прочитано, ответ', async ({ page }) => {
  // работодатель пишет из строки приглашения
  await demo(page, 'e');
  await open(page, '/employer/invites');
  await page.getByRole('row', { name: /A-1042/ }).getByRole('button', { name: 'Написать в чат' }).click();
  await settled(page);
  await expect(page).toHaveURL(/\/employer\/chat\/A-1042$/);
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

  // кандидат видит красную точку на кружке чата (число — в подписи) и список диалогов; в разделах кабинета «Чата» нет
  await demo(page, 'c');
  const fab = page.locator('#chat-fab');
  await expect(fab).toBeVisible();
  await expect(fab).toHaveAttribute('aria-label', 'Чат, непрочитанных: 1');
  await expect(fab.locator('.dot')).toBeVisible();
  await expect(page.locator('nav.subnav').getByRole('link', { name: /Чат/ })).toHaveCount(0);
  // цифра помещается в бейдж у диалога: раньше точка блока достижений .dot (14×14 с рамкой) перебивала стиль бейджа
  const fits = el => el.scrollWidth <= el.clientWidth && el.scrollHeight <= el.clientHeight && el.clientWidth >= 18;
  await open(page, '/candidate/chat');
  await expect(fab).toBeHidden();  // на самом экране чата кружок не нужен
  await expect(page.locator('.chat-peer', { hasText: 'Ладога Пэй' })).toContainText('Здравствуйте!');
  await expect.poll(() => page.locator('.chat-peer', { hasText: 'Ладога Пэй' }).locator('.unread').evaluate(fits)).toBe(true);
  await expect(page.locator('.chat-box')).toContainText('выберите диалог', { ignoreCase: true });
  await page.locator('.chat-peer', { hasText: 'Ладога Пэй' }).click();
  await settled(page);
  await expect(page.locator('#chat-messages')).toContainText('Здравствуйте! Это Ладога.');

  // Enter отправляет, Shift+Enter — перенос строки
  await page.locator('#chat-input').fill('Добрый день');
  await page.locator('#chat-input').press('Shift+Enter');
  await page.locator('#chat-input').type('Готов обсудить.');
  await page.locator('#chat-input').press('Enter');
  await expect(page.locator('.msg.me').last()).toContainText('Добрый день');
  await expect(page.locator('.msg.me').last()).toContainText('Готов обсудить.');
  await open(page, '/candidate');  // сообщение компании прочитано при открытии диалога: точка погасла
  await expect(fab).toBeVisible();
  await expect(fab).toHaveAttribute('aria-label', 'Чат');
  await expect(fab.locator('.dot')).toBeHidden();

  // работодатель: красная точка, ответ, и его сообщение отмечено прочитанным
  await demo(page, 'e');
  await expect(fab).toHaveAttribute('aria-label', 'Чат, непрочитанных: 1');
  await expect(fab.locator('.dot')).toBeVisible();
  await open(page, '/employer/chat');
  await page.locator('.chat-peer', { hasText: 'Дмитрий Орлов' }).click();
  await settled(page);
  await expect(page.locator('#chat-messages')).toContainText('Готов обсудить.');
  await expect(page.locator('.msg.me time span[title="прочитано"]')).toHaveCount(1);

  // новое сообщение от кандидата приходит само (push по SSE), черновик не теряется
  await page.locator('#chat-input').fill('черновик ответа');
  await candidateSays(page, 'Ещё вопрос про вилку');
  await expect(page.locator('#chat-messages')).toContainText('Ещё вопрос про вилку');
  await expect(page.locator('#chat-input')).toHaveValue('черновик ответа');

  // вне чата красная точка появляется сама, без перехода по экранам; открытый диалог был прочитан сразу — точки до этого нет
  await open(page, '/employer/invites');
  await expect(fab.locator('.dot')).toBeHidden();
  await candidateSays(page, 'Вы здесь?');
  await expect(fab).toHaveAttribute('aria-label', 'Чат, непрочитанных: 1');
  await expect(fab.locator('.dot')).toBeVisible();
});

// мини-окно чата над кружком: список, диалог, отправка, «Раскрыть», закрытие; переживает смену экрана
test('Чат: плавающее окно над кружком', async ({ page }) => {
  await demo(page, 'c');
  await demo(page, 'e');
  await open(page, '/employer/invites');
  await expect(page.locator('#chat-dock')).toBeHidden();
  const fab = page.locator('#chat-fab'), dock = page.locator('#chat-dock');
  await fab.click();
  await expect(dock).toBeVisible();
  await expect(fab).toHaveAttribute('aria-expanded', 'true');
  // список диалогов; кружок с окном не пересекаются
  await expect(dock.locator('.chat-peer', { hasText: 'Дмитрий Орлов' })).toBeVisible();
  await expect(dock.getByRole('button', { name: 'Раскрыть' })).toBeVisible();
  const [fb, db] = [await fab.boundingBox(), await dock.boundingBox()];
  expect(db.y + db.height).toBeLessThanOrEqual(fb.y);
  // Escape закрывает, фокус возвращается на кружок; повторный клик по кружку тоже закрывает
  await page.keyboard.press('Escape');
  await expect(dock).toBeHidden();
  await expect(fab).toBeFocused();
  await fab.click();
  await fab.click();
  await expect(dock).toBeHidden();
  // «×»
  await fab.click();
  await dock.getByRole('button', { name: 'Закрыть чат' }).click();
  await expect(dock).toBeHidden();

  // диалог: отправка в окне (Enter), набранное не теряется при смене экрана
  await fab.click();
  await dock.locator('.chat-peer', { hasText: 'Дмитрий Орлов' }).click();
  await expect(dock.locator('#dock-input')).toBeVisible();
  await expect(dock.locator('.dock-head b')).toHaveText('Дмитрий Орлов');
  const text = 'Из окна ' + Date.now();
  const sent = api(page, 'POST', '/api/chat/A-1042');
  await dock.locator('#dock-input').fill(text);
  await dock.locator('#dock-input').press('Enter');
  expect((await sent).status()).toBe(200);
  await expect(dock.locator('.msg.me').last()).toContainText(text);
  await expect(dock.locator('#dock-input')).toHaveValue('');
  // окно переживает переход между экранами, диалог остаётся открытым
  await dock.locator('#dock-input').fill('черновик');
  await page.locator('nav.subnav').getByRole('link', { name: 'Подборка' }).click();
  await expect(page.locator('#app .crumbs b')).toHaveText('Подборка');
  await expect(dock.locator('.dock-head b')).toHaveText('Дмитрий Орлов');
  // сообщение собеседника подтягивается само, набранное и фокус на месте
  await dock.locator('#dock-input').focus();
  await candidateSays(page, 'Ответ в окно');
  await expect(dock.locator('.msg').last()).toContainText('Ответ в окно');
  await expect(dock.locator('#dock-input')).toHaveValue('черновик');
  await expect(dock.locator('#dock-input')).toBeFocused();
  await expect(fab.locator('.dot')).toBeHidden();  // открытый диалог прочитан сразу
  // «←» к списку, снова в диалог
  await dock.locator('#dock-input').fill('недописанное');
  await dock.getByRole('button', { name: 'К списку диалогов' }).click();
  await expect(dock.locator('.dock-head b')).toHaveText('Чат');
  // открыт список: новое сообщение приходит само — красная точка на кружке и число у диалога
  await candidateSays(page, 'Новое при открытом списке');
  await expect(fab.locator('.dot')).toBeVisible();
  await expect(fab).toHaveAttribute('aria-label', 'Чат, непрочитанных: 1');
  await expect(dock.locator('.chat-peer', { hasText: 'Дмитрий Орлов' }).locator('.unread')).toHaveText('1');
  await dock.locator('.chat-peer', { hasText: 'Дмитрий Орлов' }).click();
  await expect(dock.locator('#dock-input')).toBeVisible();
  await expect(dock.locator('#dock-input')).toHaveValue('недописанное');  // «←» не теряет черновик
  await expect(fab.locator('.dot')).toBeHidden();  // диалог открыт — прочитан

  // «Раскрыть»: полный экран с этим диалогом, окно закрыто, кружка на экране чата нет
  await dock.getByRole('button', { name: 'Раскрыть' }).click();
  await expect(page).toHaveURL(/\/employer\/chat\/A-1042$/);
  await settled(page);
  await expect(page.locator('#chat-messages')).toContainText(text);
  await expect(dock).toBeHidden();
  await expect(fab).toBeHidden();
  await expect(page.locator('#chat-input')).toBeFocused();  // фокус после «Раскрыть» не на body

  // переключение кабинета из меню профиля закрывает окно
  await open(page, '/employer/invites');
  await fab.click();
  await expect(dock).toBeVisible();
  await page.locator('#me').click();
  await page.getByRole('link', { name: 'Перейти в кабинет кандидата' }).click();
  await expect(page.locator('#app .crumbs b')).toHaveText('Кабинет кандидата');
  await expect(dock).toBeHidden();
  await expect(fab).toBeVisible();

  // из кабинета кандидата окно открывается на его диалогах, а при выходе закрывается
  await demo(page, 'c');
  await fab.click();
  await expect(dock.locator('.chat-peer', { hasText: 'Ладога Пэй' })).toBeVisible();
  // на экране «Не найдено» (как на входе и в тесте) окно закрывается и кружка нет
  await open(page, '/candidate/nope');
  await expect(dock).toBeHidden();
  await expect(fab).toBeHidden();
  await open(page, '/candidate');
  await fab.click();
  await expect(dock.locator('.chat-peer', { hasText: 'Ладога Пэй' })).toBeVisible();
  await page.locator('#me').click();
  await page.locator('#logout').click();
  await expect(dock).toBeHidden();
  await expect(fab).toBeHidden();
});

test('Чат: кнопки «Написать», недоступный диалог, догрузка истории', async ({ page, request }) => {
  await demo(page, 'c');  // токен кандидата нужен candidateSays
  await demo(page, 'e');
  // карточка кандидата с принятым приглашением
  await open(page, '/employer/candidates/A-1042');
  await expect(page.getByRole('button', { name: 'Написать в чат' })).toBeVisible();
  // чужой кандидат без связи: кнопки нет, а прямой переход показывает понятное сообщение
  await open(page, '/employer/search');
  const other = await page.evaluate(async () => {
    const r = await fetch('/api/employer/search?limit=5', { headers: { Authorization: 'Bearer ' + localStorage.getItem('fsp.tok.e') } });
    return (await r.json()).items.map(c => c.id).find(id => id !== 'A-1042');
  });
  await open(page, '/employer/candidates/' + other);
  await expect(page.getByRole('button', { name: 'Написать в чат' })).toHaveCount(0);
  await open(page, '/employer/chat/' + other);
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
  await open(page, '/employer/chat/A-1042');
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
  await open(page, '/employer/invites');
  await open(page, '/employer/chat/A-1042');
  await expect(page.getByText('Писать больше нельзя')).toBeVisible();
  await expect(page.locator('#chat-input')).toHaveCount(0);
  await page.unroute('**/api/chat/A-1042');

  // доступ закрыт посреди сессии (кандидат скрыл профиль от компании): перечитывание по событию видимости отдаёт 403 — загруженная переписка убирается с экрана
  await open(page, '/employer/invites');
  await open(page, '/employer/chat/A-1042');
  await expect(page.locator('#chat-input')).toBeVisible();
  const prevHidden = await hideFromCompany(page);
  try {
    await recheck(page);
    await expect(page.locator('.chat-box')).toContainText('Диалог недоступен');
  } finally { await restoreHidden(request, prevHidden); }

  // то же в мини-окне: при открытом диалоге доступ закрылся — имя и переписка из окна убираются
  await open(page, '/employer/invites');
  await page.locator('#chat-fab').click();
  await page.locator('#chat-dock .chat-peer', { hasText: 'Дмитрий Орлов' }).click();
  await expect(page.locator('#dock-input')).toBeVisible();
  const prevHidden2 = await hideFromCompany(page);
  try {
    await recheck(page);
    await expect(page.locator('#chat-dock')).toContainText('Диалог недоступен');
    await expect(page.locator('#chat-dock')).not.toContainText('Дмитрий Орлов');
    await expect(page.locator('#dock-messages')).toHaveCount(0);
    await page.getByRole('button', { name: 'К списку диалогов' }).click();
    await expect(page.locator('#chat-dock .chat-peer', { hasText: 'Дмитрий Орлов' })).toHaveCount(0);  // скрытого кандидата в списке нет
  } finally { await restoreHidden(request, prevHidden2); }
  await page.getByRole('button', { name: 'Закрыть чат' }).click();
  // доступ вернулся, пока окно было закрыто: окно открывается на списке, Орлов снова в нём
  await page.locator('#chat-fab').click();
  await expect(page.locator('#chat-dock .chat-peer', { hasText: 'Дмитрий Орлов' })).toBeVisible();
  // окно перечитывает диалог при смене экрана: открыть диалог, закрыть доступ, перейти на другой экран — диалог убран
  await page.locator('#chat-dock .chat-peer', { hasText: 'Дмитрий Орлов' }).click();
  await expect(page.locator('#dock-input')).toBeVisible();
  const prevHidden3 = await hideFromCompany(page);
  try {
    await page.locator('nav.subnav').getByRole('link', { name: 'Подборка' }).click();
    await expect(page.locator('#chat-dock')).toContainText('Диалог недоступен');
  } finally { await restoreHidden(request, prevHidden3); }
  await page.getByRole('button', { name: 'Закрыть чат' }).click();

  // «Показать ранее» в окне: страница подгружается перед текущими (тот же приём, что на полном экране)
  await page.route('**/api/chat/A-1042*', async r => {
    if (r.request().method() !== 'GET') return r.fallback();
    if (r.request().url().includes('before_id=')) {
      return r.fulfill({ json: { peer: { id: 'A-1042', name: 'Дмитрий Орлов' }, more: false, messages: [{ id: 1, sender: 'candidate', text: 'Самое раннее в окне', created_at: '2026-01-01T10:00:00+03:00', read_at: null }] } });
    }
    const res = await r.fetch();
    await r.fulfill({ response: res, json: { ...(await res.json()), more: true } });
  });
  await page.locator('#chat-fab').click();
  await page.locator('#chat-dock .chat-peer', { hasText: 'Дмитрий Орлов' }).click();
  await page.locator('#chat-dock').getByRole('button', { name: 'Показать ранее' }).click();
  await expect(page.locator('#dock-messages')).toContainText('Самое раннее в окне');
  await expect(page.locator('#chat-dock').getByRole('button', { name: 'Показать ранее' })).toHaveCount(0);
  await page.unroute('**/api/chat/A-1042*');
  await page.getByRole('button', { name: 'Закрыть чат' }).click();

  // кандидат: кнопка в приглашении и в списке диалогов; ошибка отправки — тостом
  await demo(page, 'c');
  await page.locator('button.inv', { hasText: 'Ладога Пэй' }).click();
  await page.getByRole('button', { name: 'Написать в чат' }).click();
  await settled(page);
  await expect(page).toHaveURL(/\/candidate\/chat\/\d+$/);
  await page.route('**/api/chat/*', r => r.request().method() === 'POST' && !r.request().url().endsWith('/read') ? r.fulfill({ status: 429, json: { detail: 'Слишком часто: подождите минуту' } }) : r.fallback());
  await page.locator('#chat-input').fill('спам');
  await page.getByRole('button', { name: 'Отправить' }).click();
  await expect(toast(page)).toHaveText('Слишком часто: подождите минуту');
  await expect(page.locator('#chat-input')).toHaveValue('спам');
  await page.unroute('**/api/chat/*');
});
