// Задача на код в тесте: условие и примеры, переключатель Python / TypeScript, редактор с Tab, «Запустить на примерах»
// в настоящей песочнице (nsjail), отказ песочницы при отправке (инъекция 503), отправка на скрытые тесты.
// Нужна песочница: SANDBOX_URL и SANDBOX_TOKEN в окружении npm test (в CI её поднимает job frontend-e2e; локально — README, «Песочница»).
const { test, expect, open, toast, api } = require('./fixtures');
const { uniq } = require('./helpers');

test.skip(!process.env.SANDBOX_URL && !process.env.CI, 'нет песочницы: задайте SANDBOX_URL и SANDBOX_TOKEN');

const itemId = page => page.evaluate(() => S.quest && S.quest.item && S.quest.item.id);

test('задача на код: редактор, запуск на примерах в песочнице, отправка', async ({ page }) => {
  expect(process.env.SANDBOX_URL, 'в CI сценарий идёт с настоящей песочницей').toBeTruthy();
  // новый кандидат: вход по коду и минимальный профиль (Backend · Python по умолчанию)
  await open(page, '/c/signup');
  await page.getByLabel('Почта').fill(`code-${uniq()}@example.ru`);
  await page.getByLabel(/обработку персональных данных по 152-ФЗ/).check();
  await page.getByLabel('Присылать приглашения в Telegram').uncheck();
  await page.getByRole('button', { name: 'Получить код на почту' }).click();
  await expect(page.getByLabel('Код из письма')).toHaveValue(/^\d{6}$/);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await page.getByLabel('Имя и фамилия').fill('Кира Кодова');
  await page.getByLabel('Минимальная зарплата на руки').fill('150000');
  await page.getByRole('button', { name: 'Сохранить и перейти к тесту' }).click();
  await expect(page.getByText(/Одна за тест, на Python или TypeScript/)).toBeVisible();  // песочница включена — вводная говорит о задаче на код
  await page.getByRole('button', { name: 'Начать смену' }).click();

  // обычные задания до задачи на код: она идёт после четырёх рабочих (слот irt.CODE_AT), пилотная — раньше
  const ed = page.locator('#code-ed');
  for (let i = 0; i < 8; i++) {
    await expect.poll(() => itemId(page)).toBeTruthy();
    if (await page.evaluate(() => S.quest.item.kind === 'code')) break;
    const prev = await itemId(page);
    const opts = page.locator('.opt');
    if (await opts.count()) await opts.first().click(); else await page.locator('.code button[data-act=mark]').nth(1).click();
    const ans = api(page, 'POST', '/api/quest/answer');
    await page.getByRole('button', { name: 'Дальше' }).click();
    expect((await ans).ok()).toBe(true);
    await expect.poll(() => itemId(page)).not.toBe(prev);
  }
  await expect(ed).toBeVisible();
  const item = await page.evaluate(() => S.quest.item);
  const py = item.code.entry.python, ts = item.code.entry.typescript;
  expect(JSON.stringify(item)).not.toMatch(/"key"|"seed"|"tests"/);  // наружу — только открытая часть
  await expect(page.locator('.quest-foot')).toContainText('проверяется на скрытых тестах');
  await expect(page.locator('.term').first()).toContainText(py + '(');
  await expect(ed).toHaveValue(new RegExp('^def ' + py + '\\('));

  // Tab — отступ, а не переход фокуса; Esc, затем Tab — выход из редактора
  await ed.focus();
  await ed.evaluate(el => el.setSelectionRange(el.value.length, el.value.length));
  await page.keyboard.press('Tab');
  await expect(ed).toBeFocused();
  expect(await ed.inputValue()).toMatch(/\n {4}$/);
  await page.keyboard.press('Escape');
  await page.keyboard.press('Tab');
  await expect(ed).not.toBeFocused();

  // TypeScript: свой шаблон, имя функции в примерах и пометка про strip-types
  const langs = page.getByRole('group', { name: 'Язык решения' });
  await langs.getByRole('button', { name: 'TypeScript' }).click();
  await expect(langs.getByRole('button', { name: 'TypeScript' })).toHaveAttribute('aria-pressed', 'true');
  await expect(ed).toHaveValue(new RegExp('^function ' + ts + '\\('));
  await expect(page.locator('.term').first()).toContainText(ts + '(');
  await expect(page.getByText(/enum и namespace не поддерживаются/)).toBeVisible();

  // синтаксическая ошибка → «ошибка компиляции» с фрагментом из песочницы
  await ed.fill(`function ${ts}(a: number[]): number { return ; }}`);
  let run = api(page, 'POST', '/api/quest/run');
  await page.getByRole('button', { name: 'Запустить на примерах' }).click();
  let res = await run;
  expect(res.status()).toBe(200);
  expect(res.request().postDataJSON()).toMatchObject({ item_id: item.id, lang: 'typescript' });
  await expect(page.locator('#run-res')).toContainText('ошибка компиляции');
  await expect(page.locator('#run-res .term')).toContainText('Error');
  await expect(page.locator('#run-res')).toContainText(`Осталось запусков: ${(await res.json()).runs_left}`);

  // назад на Python: черновик сохранён; неверный ответ — «ожидалось / получено»
  await langs.getByRole('button', { name: 'Python' }).click();
  expect(await ed.inputValue()).toMatch(/\n {4}$/);
  await ed.fill(`def ${py}(*args):\n    return None\n`);
  // чаще раза в 3 с — 429 с понятным текстом, запуск не списан
  run = api(page, 'POST', '/api/quest/run');
  await page.getByRole('button', { name: 'Запустить на примерах' }).click();
  expect((await run).status()).toBe(429);
  await expect(toast(page)).toHaveText('Слишком часто: подождите пару секунд');
  await page.waitForTimeout(3100);  // пауза между запусками — RUN_GAP_S на сервере
  run = api(page, 'POST', '/api/quest/run');
  await page.getByRole('button', { name: 'Запустить на примерах' }).click();
  res = await run;
  expect((await res.json()).results[0].status).toBe('wrong');
  await expect(page.locator('#run-res')).toContainText('неверный ответ: ожидалось');
  await expect(page.locator('#run-res')).toContainText('получено null');

  // вставка из буфера считается (сигнал для флага code_pasted)
  await ed.evaluate(el => {
    const dt = new DataTransfer();
    dt.setData('text/plain', 'x'.repeat(30));
    el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true }));
  });

  // отказ песочницы при отправке (инъекция 503): тост, задание перечитывается с сервера
  const down = 'Песочница для проверки кода сейчас недоступна. Задание не засчитано ни в плюс, ни в минус — переходим к следующему.';
  await page.route('**/api/quest/answer', r => r.fulfill({ status: 503, json: { detail: down } }));
  const cur = api(page, 'GET', '/api/quest/current');
  await page.getByRole('button', { name: 'Отправить решение' }).click();
  await cur;
  await expect(toast(page)).toHaveText(down);
  await page.unroute('**/api/quest/answer');
  await expect(ed).toBeVisible();  // сервер ничего не записал — та же задача, черновик на месте
  expect(await ed.inputValue()).toContain('return None');

  // настоящая отправка: скрытые тесты в песочнице, ответ без вердикта, дальше — обычное задание
  const sent = api(page, 'POST', '/api/quest/answer');
  await page.getByRole('button', { name: 'Отправить решение' }).click();
  const r = await sent;
  expect(r.ok()).toBe(true);
  expect(r.request().postDataJSON()).toMatchObject({ item_id: item.id, lang: 'python', pasted: 30 });
  expect(JSON.stringify(await r.json())).not.toMatch(/"correct"|"tests"|"seed"/);
  await expect(ed).toHaveCount(0);
  await expect.poll(() => itemId(page)).not.toBe(item.id);
});
