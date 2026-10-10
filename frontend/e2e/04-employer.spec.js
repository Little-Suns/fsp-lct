// Работодатель: новая компания по коду (ИНН, домен, потребность, план теста); демо «Ладога Пэй» — подборка и фильтры,
// карточка, приглашение с ошибками вилки, статусы после принятия, поиск по банку, лотерея, вакансии и отклики, задания.
// XSS: название вакансии и задания с <img onerror> показываются как текст у работодателя и у кандидата.
const { test, expect, open, demo, toast, api } = require('./fixtures');
const { XSS, uniq } = require('./helpers');

const noXss = async page => expect(await page.evaluate(() => window.__xss)).toBeUndefined();
const ids = page => page.locator('#app button.cand .id').allTextContents();

test('новая компания: вход по коду → проверка ИНН и домена → потребность: разбор, навыки, план теста → подборка', async ({ page }) => {
  const id = uniq();
  const email = `hr-${id}@acme-${id}.example`;
  await open(page, '/employer/signup');
  await page.getByRole('button', { name: 'Получить код на почту' }).click();
  await expect(toast(page)).toHaveText('Укажите рабочую почту');
  await page.getByLabel('Рабочая почта').fill(email);
  await page.getByRole('button', { name: 'Получить код на почту' }).click();
  await expect(page.getByLabel('Код из письма')).toHaveValue(/^\d{6}$/);
  await page.getByRole('button', { name: 'Отправить код ещё раз' }).click();
  await expect(toast(page)).toContainText('Код уже отправлен — новый можно запросить через');
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  // компании ещё нет — сразу к её данным (has_profile), без тоста об ошибке
  await expect(page).toHaveURL(/\/employer\/company$/);
  await expect(page.getByRole('heading', { name: 'Компания', exact: true })).toBeVisible();
  await expect(page.getByText('Шаг 2 из 2')).toBeVisible();
  await expect(toast(page)).not.toHaveText('Сначала заполните данные компании');
  await expect(page.locator('nav.subnav')).toHaveCount(0);  // разделы — после регистрации
  await expect(page.getByText('Проверки ИНН и домена почты появятся после сохранения.')).toBeVisible();

  await page.getByLabel('ИНН').fill('7704123456');  // контрольные цифры не сходятся
  await page.getByLabel('Название').fill(`Акме ${id}`);
  await page.getByLabel('Рекрутер', { exact: true }).fill('Ирина Тестова');
  await page.getByLabel('Сайт компании').fill(`acme-${id}.example`);
  await page.getByLabel('Рабочая почта рекрутера').fill(email);
  await page.getByLabel('О компании, 1–2 предложения').fill('Тестовая компания e2e');
  await page.getByRole('button', { name: 'Зарегистрировать и описать, кого ищете' }).click();
  await expect(toast(page)).toHaveText('Компания сохранена без подтверждения: квота 3 приглашения в неделю');
  // неподтверждённая компания не застревает: дальше — первая потребность, статус проверки — плашкой
  await expect(page.getByRole('heading', { name: 'Кого ищете?' })).toBeVisible();
  const unverified = page.locator('.alert.warn', { hasText: 'Компания не прошла проверку.' });
  await unverified.getByRole('button', { name: 'Данные компании' }).click();
  await expect(page.locator('nav.subnav .chip.on')).toHaveText('Компания');  // разделы кабинета на экране компании
  await expect(page.locator('.alert.bad', { hasText: 'ИНН: контрольные цифры не сходятся' })).toBeVisible();
  await expect(page.getByText('Компания не прошла проверку.').first()).toBeVisible();
  await expect(page.getByText('Кандидаты видят:')).toBeVisible();
  await expect(page.getByText(/Сейчас: 0 \/ 3/)).toBeVisible();
  await page.getByLabel('ИНН').fill('500100732259');
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
  await expect(toast(page)).toHaveText('Компания проверена');
  await expect(page.locator('.alert.ok', { hasText: 'ИНН: контрольные цифры верны' })).toBeVisible();  // правка — на месте
  await open(page, '/employer/needs/new');

  // потребность: разбор текста правилами, правка навыков, план теста
  await expect(page.getByRole('heading', { name: 'Кого ищете?' })).toBeVisible();
  await expect(page.locator('#need-text')).toHaveValue(/Ищем бэкендера на Python/);
  await page.locator('#need-text').fill('Ищем бэкендера на Python в команду платежей. Нужен опыт с PostgreSQL и Kafka, хорошо бы Kubernetes. ' +
    'Уровень — мидл, до 300 на руки. Гибрид, Москва. Желательно мужчина до 30 лет.');
  const parsed = api(page, 'POST', '/api/employer/needs/parse');
  await page.getByRole('button', { name: 'Разобрать' }).click();
  const p = await (await parsed).json();
  await expect(page.getByRole('heading', { name: 'Структура потребности' })).toBeVisible();
  await expect(page.locator('.parsed .cat')).toContainText('Backend');
  for (const s of p.must) await expect(page.locator('.parsed').getByRole('button', { name: new RegExp('^' + s) })).toBeVisible();
  if (p.ignored && p.ignored.length) await expect(page.getByText(/Не учитываем:/)).toBeVisible();
  await expect(page.getByText(/кандидатов открыты к предложениям/)).toBeVisible();
  await expect(page.getByText('Рынок · Backend')).toBeVisible();
  // категория правится вручную: смена специализации сбрасывает трек, «Отмена» ничего не меняет
  await page.locator('.parsed').getByRole('button', { name: 'Изменить' }).click();
  await page.getByLabel('Специализация').selectOption('Frontend');
  await expect(page.getByLabel('Трек')).toHaveValue('');
  await expect(page.getByLabel('Трек').locator('option').first()).toHaveText('любой трек');
  await expect(page.getByLabel('Трек').locator('option', { hasText: 'React' })).toHaveCount(1);
  await page.locator('.parsed').getByRole('button', { name: 'Отмена' }).click();
  await expect(page.locator('.parsed .cat span')).toHaveText([p.spec, p.track, p.grade]);
  await page.locator('.parsed').getByRole('button', { name: 'Изменить' }).click();
  await page.getByLabel('Трек').selectOption('Go');
  await page.getByLabel('Грейд').selectOption('Senior');
  const cat = api(page, 'POST', '/api/employer/needs/category');
  await page.getByRole('button', { name: 'Применить' }).click();
  expect((await cat).request().postDataJSON()).toMatchObject({ spec: 'Backend', track: 'Go', grade: 'Senior' });
  await expect(page.locator('.parsed .cat span')).toHaveText(['Backend', 'Go', 'Senior']);
  await expect(page.getByText('Рынок · Backend · Senior')).toBeVisible();
  await expect(page.getByText(/В категории Backend · Go · Senior \d+ кандидатов/)).toBeVisible();
  const catPlan = api(page, 'POST', '/api/quest/plan');
  await page.getByRole('button', { name: 'Показать план теста' }).click();
  expect((await catPlan).request().postDataJSON()).toMatchObject({ spec: 'Backend', track: 'Go', grade: 'Senior' });
  await expect(page.locator('.panel', { hasText: 'Как система проверит кандидатов под эту потребность' }).locator('.chip').first()).toHaveText('Backend · Senior');
  // обратно на исходную категорию — дальше сценарий идёт по Python · Middle; правка категории сбрасывает план
  await page.locator('.parsed').getByRole('button', { name: 'Изменить' }).click();
  await page.getByLabel('Трек').selectOption(p.track);
  await page.getByLabel('Грейд').selectOption(p.grade);
  await page.getByRole('button', { name: 'Применить' }).click();
  await expect(page.locator('.parsed .cat span')).toHaveText([p.spec, p.track, p.grade]);
  await expect(page.getByRole('button', { name: 'Показать план теста' })).toBeVisible();

  const firstMust = p.must[0];
  await page.locator('.parsed').getByRole('button', { name: new RegExp('^' + firstMust) }).click();
  await expect(page.locator('.parsed').getByRole('button', { name: new RegExp('^' + firstMust + ' ') })).toHaveCount(0);
  await page.locator('.parsed').getByRole('button', { name: '+ навык' }).first().click();
  await page.getByPlaceholder('навык').fill('docker');
  await page.getByRole('button', { name: 'Добавить' }).click();
  await expect(page.locator('.parsed').getByRole('button', { name: /^Docker/ })).toBeVisible();
  await page.locator('.parsed').getByRole('button', { name: '+ навык' }).last().click();
  await page.locator('.parsed').getByRole('button', { name: '×', exact: true }).click();
  await expect(page.getByPlaceholder('навык')).toHaveCount(0);

  const editedPlan = api(page, 'POST', '/api/quest/plan');
  await page.getByRole('button', { name: 'Показать план теста' }).click();
  expect((await editedPlan).request().postDataJSON().must).toContain('Docker');  // правки навыков попадают в план
  await expect(page.getByRole('heading', { name: 'Как система проверит кандидатов под эту потребность' })).toBeVisible();
  await expect(page.getByText('Вес компетенции')).toBeVisible();
  await expect(page.getByText('Примеры заданий')).toBeVisible();
  await expect(page.getByText(/Сложность заданий \(b по шкале θ\)/)).toBeVisible();

  const saved = api(page, 'POST', '/api/employer/needs');
  await page.getByRole('button', { name: 'Показать подборку' }).click();
  const need = await (await saved).json();
  expect(need.must).toContain('Docker');
  expect(need.must).not.toContain(firstMust);
  await expect(page.getByRole('heading', { name: 'Backend-разработчик (Python)' })).toBeVisible();
  await expect(page.getByText('0 / 10')).toBeVisible();
  await expect(page.getByText('Закрытых приглашений пока нет.')).toBeVisible();
  await expect(page.locator('#app button.cand').first()).toBeVisible();

  // план теста уже сохранённой потребности — по need_id
  await page.getByRole('button', { name: 'Новая потребность' }).click();
  const plan = api(page, 'POST', '/api/quest/plan');
  await page.getByRole('button', { name: 'Показать план теста' }).click();
  expect((await plan).request().postDataJSON()).toEqual({ need_id: need.id });

  // раздел «Потребности»: все потребности компании; рекомендованная категория — новая потребность с той же структурой
  await open(page, '/employer');
  const needs = page.locator('#needs button.chip');
  await expect(needs).toHaveCount(1);
  await expect(page.locator('#needs')).toContainText('Потребности · 1');
  const created = api(page, 'POST', '/api/employer/needs');
  await page.locator('aside button.chip[data-act=need-cat-new]').first().click();
  const other = await (await created).json();
  expect(other).toMatchObject({ spec: need.spec, must: need.must, nice: need.nice, from: need.from, to: need.to });
  expect([other.track, other.grade]).not.toEqual([need.track, need.grade]);
  await expect(toast(page)).toContainText('Новая потребность: ' + [other.spec, other.track, other.grade].filter(Boolean).join(' · '));
  await expect(needs).toHaveCount(2);
  await expect(page.locator('#needs button.chip.on')).toContainText(other.grade);
  await expect(page.locator('aside button.chip[aria-current]').first()).toContainText([other.spec, other.track, other.grade].filter(Boolean).join(' · '));
  // переключение обратно на первую: подборка по ней
  const back = api(page, 'GET', `/api/employer/needs/${need.id}/picks`);
  await page.locator(`#needs button.chip[data-id="${need.id}"]`).click();
  expect((await back).ok()).toBe(true);
  await expect(page.locator('#needs button.chip.on')).toContainText(need.grade);
  await expect(page.locator(`#needs button.chip[data-id="${other.id}"]`)).toBeVisible();
  // карточка из подборки — относительно этой потребности, она в адресе
  await page.locator('#app button.cand').first().click();
  await expect(page).toHaveURL(new RegExp(`/employer/candidates/[^/?]+\\?need=${need.id}$`));
  await expect(page.locator('#app .crumbs')).toContainText('Подборка');
  await expect(page.getByRole('heading', { name: 'Почему в подборке' })).toBeVisible();

  // поиск → приглашение: без потребности, роль по категории кандидата, вилку компания указывает сама (#49)
  await open(page, '/employer/search');
  const found = api(page, 'GET', '/api/employer/search');
  await page.locator('button.chip[data-k=spec][data-v="Design"]').click();
  const des = (await (await found).json()).items.find(c => !c.invited && !c.busy);
  await page.locator(`#app button.cand[data-go="/e/cand/${des.id}"]`).click();
  await expect(page.getByRole('heading', { name: 'Кандидат ' + des.id })).toBeVisible();
  await expect(page.locator('#app .crumbs')).toContainText('Поиск');
  await expect(page.getByRole('heading', { name: 'Почему в подборке' })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'О кандидате' })).toBeVisible();
  await page.getByRole('button', { name: 'Пригласить', exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/employer/candidates/${des.id}/invite$`));
  await expect(page.getByRole('heading', { name: 'Приглашение для ' + des.id })).toBeVisible();
  await expect(page.locator('#app .crumbs')).toContainText('Поиск');
  await expect(page.getByRole('textbox', { name: 'Роль' })).not.toHaveValue(/Backend/);
  await expect(page.getByRole('textbox', { name: 'Роль' })).not.toHaveValue('');
  await expect(page.getByLabel('от', { exact: true })).toHaveValue('');
  await expect(page.locator('#f-msgs')).toContainText('Укажите обе границы вилки.');
  await expect(page.getByText('Рынок · Design')).toBeVisible();
  const p25 = +(await page.locator('dt', { hasText: '25-й перцентиль' }).locator('xpath=following-sibling::dd[1]').textContent()).replace(/\D/g, '');
  const min = +(await page.locator('.panel', { hasText: 'Кандидат ожидает' }).locator('b').textContent()).replace(/\D/g, '');
  const from = Math.max(p25, Math.round(min / 1.3));
  await page.getByLabel('от', { exact: true }).fill(String(from));
  await page.getByLabel('до', { exact: true }).fill(String(Math.round(from * 1.3)));
  await expect(page.locator('#f-msgs .alert.bad')).toHaveCount(0);
  // задача вместо созвона: по умолчанию выключена; у новой компании заданий нет — своим текстом (#50)
  const taskBox = page.getByLabel('Приложить задачу вместо первого созвона');
  await expect(taskBox).not.toBeChecked();
  await expect(page.getByText(/дубл/)).toHaveCount(0);
  await taskBox.check();
  await expect(page.locator('#f-msgs')).toContainText('Опишите задачу или снимите галочку.');
  await expect(page.getByRole('button', { name: 'Отправить приглашение' })).toBeDisabled();
  await page.locator('#f-task-text').fill('Макет экрана оплаты, ~1 час');
  await expect(page.locator('#f-msgs .alert.bad')).toHaveCount(0);
  const sent = api(page, 'POST', '/api/employer/invites');
  await page.getByRole('button', { name: 'Отправить приглашение' }).click();
  const req = (await sent).request().postDataJSON();
  expect(req).toMatchObject({ candidate_id: des.id, need_id: null, lottery_id: null, salary_from: from, task: 'Макет экрана оплаты, ~1 час', task_id: null });
  expect(req.role).not.toMatch(/Backend/);
  await expect(toast(page)).toContainText('Приглашение отправлено');
  await expect(page.getByRole('row', { name: new RegExp(des.id) })).toContainText('отправлено');

  // выход с экрана компании возвращает на вход
  await open(page, '/employer/company');
  await page.locator('#app').getByRole('button', { name: 'Выйти' }).click();
  await expect(toast(page)).toHaveText('Вы вышли');
  await expect(page.getByRole('heading', { name: 'Вход для компаний' })).toBeVisible();
});

test('Ладога: подборка и фильтры, карточка с объяснением и сигналом задачи, приглашение с ошибками вилки', async ({ page }) => {
  test.setTimeout(90_000);
  await demo(page, 'e');
  // подтверждённая компания: проверки пройдены, квота
  await open(page, '/employer/company');
  await expect(page.getByLabel('Название')).toHaveValue('Ладога Пэй');
  await expect(page.locator('.alert.ok', { hasText: 'ИНН: контрольные цифры верны' })).toBeVisible();
  await expect(page.getByText(/Сейчас: 6 \/ \d+/)).toBeVisible();
  await page.locator('.brand').click();
  await expect(page.getByRole('heading', { name: 'Backend-разработчик (Python)' })).toBeVisible();
  await expect(page.locator('aside b.num').first()).toHaveText(/^6 \/ \d+$/);
  await expect(page.getByText(/Принято \d+ % ваших приглашений/)).toBeVisible();
  await expect(page.getByText('Рекомендованные категории')).toBeVisible();
  await expect(page.getByText(/В топе — кандидаты из \d+ городов/)).toBeVisible();

  // фильтр сужает список, порядок сохраняется
  const before = await ids(page);
  expect(before.length).toBeGreaterThan(3);
  const f = api(page, 'GET', /^\/api\/employer\/needs\/\d+\/picks$/);
  await page.getByRole('button', { name: 'Формат совпадает' }).click();
  expect((await f).url()).toContain('filters=fmt');
  const ladNeed = +(await f).url().match(/needs\/(\d+)\/picks/)[1];
  await expect(page.getByRole('button', { name: 'Формат совпадает' })).toHaveClass(/on/);
  await expect(page.locator('#app button.cand').first()).toBeVisible();
  const after = await ids(page);
  expect(after.length).toBeGreaterThan(0);
  expect(after.length).toBeLessThanOrEqual(before.length);
  // кто был в топе до фильтра, идёт в том же порядке
  const kept = after.filter(x => before.includes(x)).map(x => before.indexOf(x));
  expect(kept.length).toBeGreaterThan(0);
  expect(kept).toEqual([...kept].sort((a, b) => a - b));
  await page.getByRole('button', { name: 'Без перегрузки' }).click();
  await expect(page.getByRole('button', { name: 'Без перегрузки' })).toHaveClass(/on/);
  await page.getByRole('button', { name: 'Формат совпадает' }).click();
  await page.getByRole('button', { name: 'Без перегрузки' }).click();
  await expect(page.getByRole('button', { name: 'Без перегрузки' })).not.toHaveClass(/on/);
  await expect.poll(() => ids(page)).toEqual(before);
  await expect(page.locator('#needs button.chip.on')).toContainText('Backend-разработчик (Python)');
  // чипы боковой колонки (потребности, категории): длинное название переносится, дата и число не вылезают за чип
  const spill = els => els.filter(el => { const r = document.createRange(); r.selectNodeContents(el); return r.getBoundingClientRect().right > el.getBoundingClientRect().right + 0.5; }).map(el => el.textContent.trim());
  expect(await page.locator('aside button.chip').evaluateAll(spill)).toEqual([]);

  // карточка демо-кандидата по потребности: объяснение, подтверждённые навыки, сигнал решённой задачи
  await open(page, `/employer/candidates/A-1042?need=${ladNeed}`);
  await expect(page.getByRole('heading', { name: 'Кандидат A-1042' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Почему в подборке' })).toBeVisible();
  await expect(page.getByText(/Обязательные навыки подтверждены тестом: .*Python/)).toBeVisible();
  // последняя оценка — работодателя или автопроверка (сценарий кандидата решает задания с эталоном раньше)
  await expect(page.getByText(/Решил задачу (\d+ дн\. назад|сегодня) · (оценка работодателя|автопроверка): \S+/)).toBeVisible();
  await expect(page.getByText('Итоговая оценка')).toBeVisible();
  const soft = page.locator('aside .panel', { hasText: 'Роли и софт-скиллы' });
  await expect(soft).toContainText('Ментор');
  await expect(soft).toContainText('в оценке не участвуют');
  await expect(page.getByText(/ФСП|Codeforces 1912/).first()).toBeVisible();
  // разряд ФСП — фактом в карточке: чип и строка с дисциплиной и результатом
  await expect(page.locator('.chips .chip', { hasText: '1 разряд' }).first()).toBeVisible();
  await expect(page.getByText(/продуктовое программирование · финалист · .*спортивный разряд: 1 разряд/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Уже приглашён — к статусам' })).toBeVisible();
  await expect(page.getByText(/^грейд подтверждён/)).toBeVisible();
  await expect(page.getByText('экспресс-оценка')).toHaveCount(0);
  // грейд по экспресс-тесту — пометка в карточке (живой express-кандидат не опубликован в демо-данных: поле подменено)
  const candUrl = '**/api/employer/candidates/A-1042*';
  await page.route(candUrl, async r => {
    const real = await (await page.request.get(r.request().url(), { headers: r.request().headers() })).json();
    await r.fulfill({ json: { ...real, express: true } });
  });
  await open(page, '/employer');
  await open(page, '/employer/candidates/A-1042');
  await expect(page.locator('.chip', { hasText: 'экспресс-оценка' })).toBeVisible();
  await expect(page.getByText(/^экспресс-оценка \d+ мес\. назад/)).toBeVisible();
  await page.unroute(candUrl);
  // повторное приглашение — блокирующая ошибка от сервера прямо в форме
  await open(page, `/employer/candidates/A-1042/invite?need=${ladNeed}`);
  await expect(page.getByRole('heading', { name: 'Приглашение для A-1042' })).toBeVisible();
  await page.getByRole('button', { name: 'Отправить приглашение' }).click();
  await expect(page.locator('#f-msgs .alert.bad', { hasText: 'Кандидат уже приглашён' })).toBeVisible();

  // свежий кандидат из подборки: ошибки вилки в форме, затем отправка
  await open(page, '/employer');
  const picks = api(page, 'GET', /^\/api\/employer\/needs\/\d+\/picks$/);
  await page.getByRole('button', { name: 'Формат совпадает' }).click();
  const fresh = (await (await picks).json()).items.find(c => !c.invited && !c.busy && c.inFork);
  await page.locator(`#app button.cand[data-go="/e/cand/${fresh.id}?need=${ladNeed}"]`).click();
  await expect(page.getByRole('heading', { name: 'Кандидат ' + fresh.id })).toBeVisible();
  await page.getByRole('button', { name: 'Пригласить', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Приглашение для ' + fresh.id })).toBeVisible();
  const from = page.getByLabel('от', { exact: true }), to = page.getByLabel('до', { exact: true });
  const send = page.getByRole('button', { name: 'Отправить приглашение' });
  const [f0, t0] = [await from.inputValue(), await to.inputValue()];
  await from.fill('1000');
  await expect(page.locator('#f-msgs')).toContainText('Нижняя граница ниже 25-го перцентиля рынка');
  await expect(send).toBeDisabled();
  await from.fill('');
  await expect(page.locator('#f-msgs')).toContainText('Укажите обе границы вилки.');
  await from.fill(String(+t0 + 10000));
  await expect(page.locator('#f-msgs')).toContainText('Нижняя граница больше верхней.');
  await from.fill(f0);
  await to.fill(String(+f0 * 2));
  await expect(page.locator('#f-msgs')).toContainText('Вилка слишком широкая');
  await to.fill(t0);
  await expect(page.locator('#f-msgs .alert.bad')).toHaveCount(0);
  await expect(send).toBeEnabled();
  await page.getByRole('button', { name: 'Удалённо' }).click();
  await expect(page.getByRole('button', { name: 'Удалённо' })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('textbox', { name: 'Роль' }).fill('Backend (Python), платежи — e2e');
  await page.getByLabel('О работе').fill('Платёжный шлюз, Python 3.12.');
  // задача вместо созвона: по умолчанию выключена, текст — из заданий компании по специализации кандидата
  const taskBox = page.getByLabel('Приложить задачу вместо первого созвона');
  await expect(taskBox).not.toBeChecked();
  await expect(page.getByText(/дубл/)).toHaveCount(0);
  await taskBox.check();
  const mine = (await page.evaluate(() => api('GET', '/api/tasks/mine'))).filter(t => (t.public && t.spec === 'Backend') || t.need_id === ladNeed);  // только те, что кандидат сможет открыть
  const pick = page.locator('#f-task-id');
  await expect(pick.locator('option')).toHaveCount(mine.length);
  await pick.selectOption(String(mine[mine.length - 1].id));
  const inv = api(page, 'POST', '/api/employer/invites');
  await send.click();
  const body = (await inv).request().postDataJSON();
  expect(body).toMatchObject({ candidate_id: fresh.id, need_id: ladNeed, salary_from: +f0, salary_to: +t0, format: 'Удалённо', role: 'Backend (Python), платежи — e2e',
    task: `${mine[mine.length - 1].title}: ~${mine[mine.length - 1].minutes} мин, заменяет первый созвон`, task_id: mine[mine.length - 1].id });
  await expect(toast(page)).toContainText('Приглашение отправлено');
  await expect(toast(page)).toContainText('Кандидат увидит его в кабинете');  // без SMTP письмо не обещаем
  await expect(toast(page)).not.toContainText('Telegram');
  await expect(page).toHaveURL(/\/employer\/invites$/);
  const row = page.getByRole('row', { name: new RegExp(fresh.id) });
  await expect(row).toContainText('отправлено');
  await expect(row).toContainText('скрыты');
  await expect(page.getByText(/квота 7 \/ \d+/)).toBeVisible();
  // из статусов — карточка относительно потребности приглашения
  await row.getByRole('button', { name: fresh.id }).click();
  await expect(page).toHaveURL(new RegExp(`/employer/candidates/${fresh.id}\\?need=${ladNeed}$`));
  await expect(page.getByRole('heading', { name: 'Почему в подборке' })).toBeVisible();
  // потребность — в настоящем адресе: переживает перезагрузку
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Почему в подборке' })).toBeVisible();
  await expect(page.locator('#app .crumbs')).toContainText('Подборка');
  // потребность из адреса, которой нет у компании, — карточка как без потребности
  await open(page, `/employer/candidates/${fresh.id}?need=999999`);
  await expect(page.getByRole('heading', { name: 'О кандидате' })).toBeVisible();

  for (const r of ['/employer/candidates/Z-0000', '/employer/candidates/Z-0000/invite']) {
    await open(page, r);
    await expect(page.getByText('Кандидат не найден или скрыл профиль.')).toBeVisible();
  }
});

test('Ладога ↔ кандидат: принятое приглашение открывает контакты в статусах, отметка после собеседования', async ({ page }) => {
  await demo(page, 'e');
  await page.locator('nav.chips').getByRole('link', { name: 'Приглашения' }).click();
  const orlov = page.getByRole('row', { name: /A-1042/ });
  await expect(orlov).toContainText('скрыты');
  await expect(page.getByText('A-1042 ещё не ответил.')).toBeVisible();
  // отметка после собеседования по уже принятому приглашению
  const anna = page.getByRole('row', { name: /F-0911/ });
  await expect(anna).toContainText('принято');
  await anna.getByRole('button', { name: 'грейд подтвердился' }).click();
  await expect(toast(page)).toHaveText('Спасибо. Отметка уйдёт в калибровку теста');
  await expect(anna.locator('.chip.ok')).toHaveText('грейд подтвердился');
  await expect(page.getByRole('row', { name: /G-2240/ })).toContainText('причина: зарплата');
  // принятое приглашение кандидата, отозвавшего согласие: контактов нет, видна причина
  await page.route('**/api/employer/pipeline', async r => {
    const res = await r.fetch();
    const body = await res.json();
    body.items.push({ ...body.items[0], id: 999999, cid: 'Q-0000', status: 'ok', contact: null, reason: 'кандидат отозвал согласие', fb: null, feedback: null });
    await r.fulfill({ response: res, json: body });
  });
  await open(page, '/employer');
  await open(page, '/employer/invites');
  await expect(page.getByRole('row', { name: /Q-0000/ })).toContainText('кандидат отозвал согласие');
  await page.unroute('**/api/employer/pipeline');

  // кандидат принимает приглашение «Ладога Пэй»
  await demo(page, 'c');
  await page.locator('button.inv', { hasText: 'Ладога Пэй' }).click();
  await page.getByRole('button', { name: 'Принять и открыть мои контакты' }).click();
  await expect(toast(page)).toHaveText('Приглашение принято. Компания получила ваши контакты');
  await expect(page.getByText('Вы приняли приглашение.', { exact: true })).toBeVisible();
  // демо-режим (DEMO=1): отзыв о компании открыт сразу после принятия, без недели ожидания
  await expect(page.getByRole('heading', { name: 'Как прошло общение с компанией?' })).toBeVisible();
  await expect(page.locator('dl.kv', { hasText: 'Компания видит' })).toContainText('Дмитрий Орлов, d.orlov@example.ru, @dorlov_dev');
  await expect(page.locator('aside')).toContainText('m.kovaleva@ladoga-pay.example');
  await expect(page.getByText('Ваши ФИО и контакты: вы приняли приглашение.')).toBeVisible();

  // работодатель видит контакты и может отметить итог
  await demo(page, 'e');
  await open(page, '/employer/invites');
  await expect(orlov).toContainText('принято');
  await expect(orlov).toContainText('Дмитрий Орлов');
  await expect(page.getByText('A-1042 ещё не ответил.')).toHaveCount(0);
  await orlov.getByRole('button', { name: 'наняли' }).click();
  await expect(orlov.locator('.chip.ok')).toHaveText('наняли');
});

test('Ладога: соседняя категория в подборке открывает поиск по банку с её фильтрами', async ({ page }) => {
  // биллинга нет — и обещания оплаты тоже: ни на регистрации, ни в данных компании
  await open(page, '/employer/signup');
  await expect(page.getByText('Проверка компании')).toBeVisible();
  await expect(page.getByText('Оплата')).toHaveCount(0);
  await demo(page, 'e');
  await open(page, '/employer/company');
  await expect(page.getByText(/Принято приглашений: \d+/)).toBeVisible();
  await expect(page.getByText('Оплата')).toHaveCount(0);
  await open(page, '/employer');
  const cat = page.locator('button[data-act=cat-search]').first();
  await expect(cat).toBeVisible();
  const { spec, track, grade, msg } = await cat.evaluate(b => ({ ...b.dataset }));
  const q = api(page, 'GET', '/api/employer/search');
  await cat.click();
  const url = new URL((await q).url());
  expect([url.searchParams.get('spec'), url.searchParams.get('track') || '', url.searchParams.get('grade')]).toEqual([spec, track, grade]);
  await expect(page.getByText(/^Найдено \d+ · сортировка/)).toBeVisible();
  await expect(page.getByLabel('Специализация')).toHaveValue(spec);
  await expect(page.getByLabel('Грейд')).toHaveValue(grade);
  if (track) await expect(page.getByLabel('Трек')).toHaveValue(track);
  await expect(page).toHaveURL(/\/employer\/search$/);
  if (msg) await expect(toast(page)).toHaveText(msg);
});

test('Ладога: повторное приглашение — после истечения можно, после отказа — пауза с датой', async ({ page }) => {
  await demo(page, 'e');
  // G-2240 отклонил приглашение 9 дней назад: кнопки «Пригласить» нет, причина и дата — в подсказке
  await open(page, '/employer/candidates/G-2240');
  await expect(page.getByRole('button', { name: 'Уже приглашён — к статусам' })).toBeVisible();
  await expect(page.getByText(/^Кандидат отклонил приглашение; повторно — не раньше \d+ \S+$/)).toBeVisible();
  // H-1503 не ответил, приглашение истекло — «Пригласить снова» (из подборки: потребность в адресе, вилка из неё)
  await open(page, `/employer/candidates/H-1503?need=${await page.evaluate(() => S.needId)}`);
  await page.getByRole('button', { name: 'Пригласить снова' }).click();
  await expect(page.getByRole('heading', { name: 'Приглашение для H-1503' })).toBeVisible();
  const inv = api(page, 'POST', '/api/employer/invites');
  await page.getByRole('button', { name: 'Отправить приглашение' }).click();
  expect((await inv).status()).toBe(200);
  await expect(toast(page)).toContainText('Приглашение отправлено');
  await expect(page).toHaveURL(/\/employer\/invites$/);
  const rows = page.getByRole('row', { name: /H-1503/ });
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText('отправлено');
  await expect(rows.nth(1)).toContainText('истекло');
  // снова открыто — повтор закрыт, без подсказки о паузе
  await open(page, '/employer/candidates/H-1503');
  await expect(page.getByRole('button', { name: 'Уже приглашён — к статусам' })).toBeVisible();
  await expect(page.getByText(/^Кандидат отклонил/)).toHaveCount(0);
});

test('Ладога: поиск по банку — фасеты, флаги, текст и навыки, страницы', async ({ page }) => {
  await demo(page, 'e');
  await page.locator('nav.chips').getByRole('link', { name: 'Поиск по банку' }).click();
  await expect(page.getByText(/^Найдено \d+ · сортировка по силе подтверждённого профиля/)).toBeVisible();
  const total = async () => +(await page.getByText(/^Найдено \d+/).textContent()).match(/\d+/)[0];
  const all = await total();
  expect(all).toBeGreaterThan(20);

  // страницы
  await expect(page.getByText(/страница 1 из \d+/)).toBeVisible();
  await expect(page.getByRole('button', { name: '← Назад' })).toBeDisabled();
  await page.getByRole('button', { name: 'Дальше →' }).click();
  await expect(page.getByText(/страница 2 из \d+/)).toBeVisible();
  await page.getByRole('button', { name: '← Назад' }).click();
  await expect(page.getByText(/страница 1 из \d+/)).toBeVisible();

  // фасет специализации → трек в фильтре, фасет грейда, флаг ФСП
  let q = api(page, 'GET', '/api/employer/search');
  await page.locator('button.chip[data-k=spec]', { hasText: 'Backend' }).click();
  expect((await q).url()).toContain('spec=Backend');
  await expect(page.locator('button.chip[data-k=spec]', { hasText: 'Backend' })).toHaveClass(/on/);
  await expect(page.getByLabel('Специализация')).toHaveValue('Backend');
  await expect(page.getByLabel('Трек').locator('option', { hasText: 'Python' })).toHaveCount(1);
  const backend = await total();
  expect(backend).toBeLessThan(all);
  q = api(page, 'GET', '/api/employer/search');
  await page.locator('button.chip[data-k=grade]', { hasText: 'Middle' }).click();
  expect((await q).url()).toMatch(/spec=Backend.*grade=Middle|grade=Middle.*spec=Backend/);
  q = api(page, 'GET', '/api/employer/search');
  await page.locator('button.chip[data-act=sf-flag]', { hasText: 'ФСП' }).click();
  expect((await q).url()).toContain('fsp=true');
  await expect(page.locator('button.chip[data-act=sf-flag]', { hasText: 'ФСП' })).toHaveClass(/on/);
  q = api(page, 'GET', '/api/employer/search');
  await page.locator('button.chip[data-act=sf-flag]', { hasText: 'ФСП' }).click();
  await q;  // иначе поздний ответ перерисует форму поверх заполненных ниже полей
  // повторный клик по фасету снимает его
  q = api(page, 'GET', '/api/employer/search');
  await page.locator('button.chip[data-k=grade]', { hasText: 'Middle' }).click();
  await q;
  await expect(page.locator('button.chip[data-k=grade].on')).toHaveCount(0);

  // форма: трек, навыки, текст, формат, город
  await page.getByLabel('Трек').selectOption('Python');
  await page.getByLabel('Навыки через запятую').fill('PostgreSQL, Kafka');
  await page.getByLabel('Текст').fill('платежи');
  await page.getByLabel('Формат').selectOption('Гибрид');
  await page.getByLabel('Город').fill('Москва');
  // ждём ответ именно на этот поиск (с треком): каждый клик по фасету выше уже дождался своего ответа,
  // поэтому поздний ответ не перерисует форму, а ожидание не поймает чужой ответ
  q = page.waitForResponse(r => { const u = new URL(r.url()); return u.pathname === '/api/employer/search' && u.searchParams.get('track') === 'Python'; });
  await page.getByRole('button', { name: 'Найти' }).click();
  const url = new URL((await q).url());
  expect(Object.fromEntries(url.searchParams)).toMatchObject({ spec: 'Backend', track: 'Python', skills: 'PostgreSQL, Kafka', format: 'Гибрид', city: 'Москва' });
  await expect(page.getByText(/навыки: PostgreSQL, Kafka/)).toBeVisible();
  // смена специализации сбрасывает трек
  await page.getByLabel('Специализация').selectOption('Frontend');
  await expect(page.getByLabel('Трек')).toHaveValue('');
  await page.getByLabel('Текст').fill('нет-такого-кандидата-zzz');
  await page.getByRole('button', { name: 'Найти' }).click();
  await expect(page.getByText('Под фильтры никто не подходит.')).toBeVisible();
  await page.getByRole('button', { name: 'Сбросить' }).click();
  await expect.poll(total).toBe(all);
  // поиск по ID (скопирован из воронки или чата): находит ровно его, даже при фильтре другой специализации
  const pid = (await page.locator('#app button.cand').nth(1).textContent()).match(/[A-Z]-\d{4}/)[0];
  await page.getByLabel('Специализация').selectOption('Design');
  await page.getByLabel('Текст').fill(pid.toLowerCase());
  await page.getByRole('button', { name: 'Найти' }).click();
  await expect(page.getByText(/^Найдено 1 · поиск по ID, фильтры не применялись/)).toBeVisible();
  await page.locator('#app button.cand').first().click();
  await expect(page.getByRole('heading', { name: 'Кандидат ' + pid })).toBeVisible();
});

test('Ладога: без теста кандидата не видно нигде; тест ниже заявленного — оба грейда видны', async ({ page }) => {
  await demo(page, 'e');
  await page.locator('.brand').click();
  await expect(page.getByText('В подборке только прошедшие тест: категория — по его результату')).toBeVisible();
  // K-2077 заявил Middle в нужном стеке, но тест не прошёл: ни в подборке, ни в поиске, ни по прямой ссылке
  const P = await page.evaluate(() => api('GET', `/api/employer/needs/${S.needId}/picks?limit=500`));
  expect(P.items.length).toBeGreaterThan(0);
  expect(P.items.every(c => c.grade && c.pct != null && c.theta)).toBe(true);
  expect(P.items.find(c => c.id === 'K-2077')).toBeUndefined();
  const R = await page.evaluate(() => api('GET', '/api/employer/search?spec=Backend&track=Python&grade=Middle&limit=100'));
  expect(R.items.find(c => c.id === 'K-2077')).toBeUndefined();
  expect(R.items.every(c => c.grade === 'Middle')).toBe(true);
  await open(page, '/employer/search');
  await expect(page.getByText(/сортировка по силе подтверждённого профиля, только прошедшие тест/)).toBeVisible();
  await open(page, '/employer/candidates/K-2077');
  await expect(page.getByText('Кандидат не найден или скрыл профиль.')).toBeVisible();
  await expect(page.getByText(/грейд не подтверждён тестом/)).toHaveCount(0);
  // тест показал Middle при заявленном Senior: категория по тесту, заявленный — рядом
  await open(page, '/employer/candidates/L-3141');
  await expect(page.locator('.chip', { hasText: 'заявлен Senior, тест — Middle' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Компетенции' })).toBeVisible();
  // приглашение: рынок и ожидания кандидата подписаны «на руки»
  await page.getByRole('button', { name: 'Пригласить', exact: true }).click();
  await expect(page.getByText(/^от .+ на руки$/)).toBeVisible();
});

test('Ладога: квалифицированная лотерея — пул, жребий, проверка, публичная ссылка, приглашение по жребию', async ({ page }) => {
  await demo(page, 'e');
  const panel = page.locator('.panel', { has: page.getByRole('heading', { name: 'Лотерея среди прошедших порог' }) });
  await expect(panel).toBeVisible();
  const skill = panel.locator('button[data-act=lot-skill]').first();
  await skill.click();
  await expect(skill).not.toHaveClass(/on/);
  await skill.click();
  await expect(skill).toHaveClass(/on/);
  const free = panel.getByRole('switch', { name: /Только без перегрузки/ });
  await free.click();
  await expect(free).toHaveAttribute('aria-checked', 'false');
  await free.click();
  await panel.locator('#lot-fork').fill('');
  await panel.getByRole('button', { name: 'Зафиксировать пул' }).click();
  await expect(toast(page)).toHaveText('Укажите верхнюю границу ожиданий на руки');
  await panel.locator('#lot-fork').fill('290 000');  // не выше верхней границы вилки потребности
  await panel.locator('#lot-k').fill('2');
  const created = api(page, 'POST', '/api/lottery/');
  await panel.getByRole('button', { name: 'Зафиксировать пул' }).click();
  expect((await created).status()).toBe(200);
  const lot = await (await created).json();
  expect(lot.seed_hash).toMatch(/^[0-9a-f]{64}$/);
  await expect(panel).toContainText(`Порог прошли ${lot.pool_size} кандидатов`);
  await expect(panel).toContainText(lot.seed_hash);

  // среди вытянутых может оказаться скрывший профиль: только псевдоним, без «Пригласить»
  await page.route('**/api/lottery/*/draw', async r => {
    const res = await r.fetch();
    const body = await res.json();
    body.drawn.push({ pseudonym: 'f'.repeat(16), hidden: true });
    await r.fulfill({ response: res, json: body });
  });
  await panel.getByRole('button', { name: `Бросить жребий: 2 из ${lot.pool_size}` }).click();
  const gone = panel.locator('.cand', { hasText: 'Кандидат скрыл профиль' });
  await expect(gone).toContainText('ffffffffffffffff');
  await expect(gone.getByRole('button')).toHaveCount(0);
  await page.unroute('**/api/lottery/*/draw');
  await expect(panel.locator('.cand')).toHaveCount(Math.min(2, lot.pool_size) + 1);
  await expect(panel).toContainText('Зерно раскрыто');
  await expect(panel.locator('.cand code').first()).toHaveText(/^[0-9a-f]{16}$/);  // псевдоним в публичной проверке
  await panel.getByRole('button', { name: 'Проверить жеребьёвку' }).click();
  await expect(panel.locator('.alert.ok', { hasText: 'Проверка пройдена' })).toBeVisible();
  const href = await panel.getByRole('link', { name: 'Публичная проверка' }).getAttribute('href');
  expect(href).toBe(`/api/lottery/${lot.id}/public`);
  const pub = await page.request.get(href);
  expect(pub.ok()).toBe(true);
  expect(JSON.stringify(await pub.json())).toContain(lot.seed_hash);

  // приглашение выбранному жребием уходит с lottery_id
  const drawnId = (await panel.locator('.cand .id').first().textContent()).replace('Кандидат ', '');
  await panel.getByRole('button', { name: 'Пригласить' }).first().click();
  await expect(page.getByRole('heading', { name: 'Приглашение для ' + drawnId })).toBeVisible();
  const inv = api(page, 'POST', '/api/employer/invites');
  await page.getByRole('button', { name: 'Отправить приглашение' }).click();
  const res = await inv;
  expect(res.request().postDataJSON().lottery_id).toBe(lot.id);
  if (res.status() === 200) {  // жребий случаен: выбранный мог уже иметь открытое приглашение «Ладоги»
    await expect(page.getByRole('row', { name: new RegExp(drawnId) })).toContainText('по жребию');
  } else {
    await expect(page.locator('#f-msgs .alert.bad')).toBeVisible();
    await open(page, '/employer');
  }
  await open(page, '/employer');
  await panel.getByRole('button', { name: 'Новый розыгрыш' }).click();
  await expect(panel.getByRole('button', { name: 'Зафиксировать пул' })).toBeVisible();
});

test('Ладога ↔ кандидат: вакансии — 422 по вилке, публикация, правка, закрытие, отклики и их статусы; XSS в названии', async ({ page }) => {
  test.setTimeout(120_000);
  const id = uniq();
  const title = `QA ${XSS} вакансия ${id}`;
  await demo(page, 'e');
  await page.locator('nav.chips').getByRole('link', { name: 'Вакансии' }).click();
  await expect(page.getByRole('heading', { name: 'Вакансии' })).toBeVisible();
  await page.getByRole('button', { name: 'Новая вакансия' }).click();
  await expect(page.getByRole('heading', { name: 'Новая вакансия' })).toBeVisible();
  await page.locator('#vac-form').getByRole('button', { name: 'Закрыть' }).click();
  await expect(page.getByRole('heading', { name: 'Новая вакансия' })).toHaveCount(0);

  const create = async (t, from, to) => {
    await page.getByRole('button', { name: 'Новая вакансия' }).click();
    await page.getByLabel('Название').fill(t);
    await page.getByLabel('Специализация').selectOption('Frontend');
    await expect(page.getByLabel('Трек')).toHaveValue('');
    await page.getByLabel('Специализация').selectOption('Backend');
    await page.getByLabel('Трек').selectOption('Python');
    await page.locator('#vac-form').getByRole('button', { name: 'Senior' }).click();
    await page.locator('#vac-form').getByRole('button', { name: 'Middle' }).click();
    await expect(page.locator('#vac-form').getByRole('button', { name: 'Middle' })).toHaveAttribute('aria-pressed', 'true');
    await page.locator('#vac-form').getByRole('button', { name: 'Удалённо' }).click();
    await page.getByLabel('Обязательные навыки').fill('Python; PostgreSQL');
    await page.getByLabel('Желательные навыки').fill('Kafka');
    await page.getByLabel('от', { exact: true }).fill(String(from));
    await page.getByLabel('до', { exact: true }).fill(String(to));
    await page.getByLabel('Город').fill('Москва');
    await page.getByLabel('Описание').fill(`Описание ${t}`);
  };
  // вилка ниже рынка — 422 от сервера, ошибка в форме
  await create(title, 50000, 60000);
  const bad = api(page, 'POST', '/api/vacancies');
  await page.getByRole('button', { name: 'Опубликовать' }).click();
  expect((await bad).status()).toBe(422);
  await expect(page.locator('#vx-msgs .alert.bad', { hasText: '25-го перцентиля' })).toBeVisible();
  await page.getByLabel('до', { exact: true }).fill('');
  await page.getByRole('button', { name: 'Опубликовать' }).click();
  await expect(page.locator('#vx-msgs')).toContainText('Укажите обе границы вилки.');
  await page.getByLabel('от', { exact: true }).fill('250000');
  await page.getByLabel('до', { exact: true }).fill('400000');
  await page.getByRole('button', { name: 'Опубликовать' }).click();
  await expect(page.locator('#vx-msgs')).toContainText('Вилка слишком широкая');
  await page.getByLabel('до', { exact: true }).fill('320000');
  const ok = api(page, 'POST', '/api/vacancies');
  await page.getByRole('button', { name: 'Опубликовать' }).click();
  const vac = await (await ok).json();
  expect(vac).toMatchObject({ title, must: ['Python', 'PostgreSQL'], from: 250000, to: 320000, format: 'Удалённо' });
  await expect(toast(page)).toContainText('Вакансия опубликована');
  const card = page.locator('.panel', { hasText: `вакансия ${id}` }).first();
  await expect(card).toContainText(title);  // нагрузка видна как текст
  await expect(card).toContainText('открыта до');
  await noXss(page);
  // лимит открытых вакансий подтверждённой компании и срок публикации
  const limit = page.locator('.panel', { hasText: 'Открытые вакансии' });
  await expect(limit).toContainText(/\d+ \/ 10/);
  await expect(limit).toContainText('Вакансия публикуется на 30 дней');
  const ext = api(page, 'POST', `/api/vacancies/${vac.id}/extend`);
  await card.getByRole('button', { name: 'Продлить' }).click();
  expect((await ext).status()).toBe(200);
  await expect(toast(page)).toContainText('Вакансия продлена до');

  // правка
  await card.getByRole('button', { name: 'Изменить' }).click();
  await expect(page.getByRole('heading', { name: 'Редактирование вакансии' })).toBeVisible();
  await expect(page.getByLabel('Название')).toHaveValue(title);
  await page.getByLabel('Название').fill(title + ' (ред.)');
  const patch = api(page, 'PATCH', `/api/vacancies/${vac.id}`);
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
  expect((await patch).status()).toBe(200);
  await expect(toast(page)).toContainText('Вакансия сохранена');
  await expect(card).toContainText(title + ' (ред.)');

  // вторая вакансия — для отказа; третья — закрываем
  // тост «Вакансия опубликована» мог остаться от прошлой публикации — ждём сам ответ API
  await create(`QA отказ ${id}`, 250000, 320000);
  let made = api(page, 'POST', '/api/vacancies');
  await page.getByRole('button', { name: 'Опубликовать' }).click();
  expect((await made).status()).toBe(200);
  await expect(page.getByRole('heading', { name: 'Новая вакансия' })).toHaveCount(0);
  const declineCard = page.locator('.panel', { hasText: `QA отказ ${id}` }).first();
  const declineId = (await declineCard.getByRole('button', { name: 'Отклики' }).getAttribute('data-go')).split('/').pop();
  await create(`QA закрыть ${id}`, 250000, 320000);
  made = api(page, 'POST', '/api/vacancies');
  await page.getByRole('button', { name: 'Опубликовать' }).click();
  expect((await made).status()).toBe(200);
  const closeCard = page.locator('.panel', { hasText: `QA закрыть ${id}` }).first();
  await closeCard.getByRole('button', { name: 'Закрыть' }).click();
  await expect(toast(page)).toHaveText('Вакансия закрыта');
  await expect(closeCard).toContainText('закрыта');
  await expect(closeCard.getByRole('button', { name: 'Изменить' })).toHaveCount(0);

  // кандидат видит вакансию с нагрузкой как текст и откликается на обе
  await demo(page, 'c');
  for (const [vid, note] of [[vac.id, 'Готов к задаче вместо созвона'], [declineId, null]]) {
    await open(page, `/candidate/vacancies/${vid}`);
    await expect(page.getByRole('button', { name: 'Откликнуться' })).toBeVisible();
    await noXss(page);
    if (note) await page.getByLabel('Короткая заметка, по желанию').fill(note);
    // одинаковый тост второго отклика неотличим от первого — проверяем ответ API и итог на экране
    const applied = api(page, 'POST', `/api/vacancies/${vid}/apply`);
    await page.getByRole('button', { name: 'Откликнуться' }).click();
    expect((await applied).status()).toBe(200);
    await expect(toast(page)).toHaveText('Отклик отправлен: контакты откроются, когда компания его примет');
    await expect(page.getByText('Вы откликнулись:')).toBeVisible();
  }
  await expect(page.getByRole('heading', { name: `QA отказ ${id}` })).toBeVisible();

  // работодатель: до ответа — анонимная карточка, контакты — после приглашения на интервью
  await demo(page, 'e');
  await open(page, '/employer/vacancies');
  await expect(card).toContainText('Откликов: 1');
  await expect(card).toContainText('новых 1');
  await card.getByRole('button', { name: 'Отклики' }).click();
  await expect(page.getByRole('heading', { name: title + ' (ред.)' })).toBeVisible();
  await noXss(page);
  await expect(page.getByText('ФИО и контакты кандидата откроются, когда вы пригласите его на интервью')).toBeVisible();
  const app = page.locator('.panel', { hasText: 'Кандидат A-1042' });
  await expect(app).toContainText('«Готов к задаче вместо созвона»');
  await expect(app).toContainText('Контакты откроются после приглашения на интервью');
  await expect(page.getByText('d.orlov@example.ru')).toHaveCount(0);
  await app.getByRole('button', { name: 'Просмотрено' }).click();
  await expect(toast(page)).toHaveText('Отмечено как просмотренное');
  await expect(app).toContainText('просмотрен');
  await expect(page.getByText('d.orlov@example.ru')).toHaveCount(0);
  await app.getByRole('button', { name: 'Отклонить…' }).click();
  await expect(app.getByRole('button', { name: 'Отклонить', exact: true })).toBeDisabled();
  await app.getByRole('button', { name: 'Отмена' }).click();
  await app.getByRole('button', { name: 'Пригласить на интервью' }).click();
  await expect(toast(page)).toHaveText('Кандидат приглашён на интервью');
  await expect(app).toContainText('приглашение на интервью');
  await expect(app).toContainText('Дмитрий Орлов · d.orlov@example.ru · @dorlov_dev');

  // отклик кандидата, отозвавшего согласие: ни карточки, ни контактов, ни кнопок
  const appsUrl = `**/api/vacancies/${vac.id}/applications`;
  await page.route(appsUrl, async r => {
    const real = await (await page.request.get(r.request().url(), { headers: r.request().headers() })).json();
    real.items.push({ ...real.items[0], id: 999999, status: 'sent', hidden: true, candidate: null, contacts: null });
    // контакты закрыты при живой карточке: отзыв отклика и «скрыть профиль от компании» объясняются по-разному
    real.items.push({ ...real.items[0], id: 999998, status: 'withdrawn', reason: null, contacts: null, chat_peer: null });
    real.items.push({ ...real.items[0], id: 999997, status: 'accepted', reason: null, contacts: null, chat_peer: null });
    real.items.push({ ...real.items[0], id: 999996, status: 'declined', reason: null, contacts: null, chat_peer: null });
    await r.fulfill({ json: real });
  });
  await open(page, '/employer/vacancies');
  await open(page, `/employer/vacancies/${vac.id}`);
  const gone = page.locator('.panel', { hasText: 'Кандидат скрыл профиль' });
  await expect(gone).toContainText('карточка и контакты недоступны');
  await expect(gone.getByRole('button')).toHaveCount(0);
  await expect(page.getByText('Кандидат отозвал отклик — контакты скрыты')).toHaveCount(1);
  await expect(page.getByText('Кандидат закрыл доступ к контактам')).toHaveCount(1);
  await expect(page.getByText('Отклик отклонён — контакты не открывались')).toHaveCount(1);
  await page.unroute(appsUrl);

  await open(page, `/employer/vacancies/${declineId}`);
  await app.getByRole('button', { name: 'Отклонить…' }).click();
  await app.getByRole('button', { name: 'Стек' }).click();
  await app.getByRole('button', { name: 'Отклонить', exact: true }).click();
  await expect(toast(page)).toHaveText('Отказ отправлен');
  await expect(app).toContainText('причина отказа: стек');

  // кандидат видит итог по обоим откликам
  await demo(page, 'c');
  await open(page, '/candidate/applications');
  await expect(page.locator('.panel', { hasText: `вакансия ${id}` })).toContainText('Компания приняла отклик: ей открыты ваши контакты');
  await expect(page.locator('.panel', { hasText: `QA отказ ${id}` })).toContainText('Отказ: стек.');
  await noXss(page);

  await demo(page, 'e');
  await open(page, '/employer/vacancies/999999');
  await expect(page.getByText('Вакансия не найдена.')).toBeVisible();
});

test('Ладога ↔ кандидат: задание — создание, решение кандидата, оценка, сигнал у кандидата; XSS в названии', async ({ page }) => {
  test.setTimeout(90_000);
  const id = uniq();
  const title = `QA ${XSS} задание ${id}`;
  await demo(page, 'e');
  await page.locator('nav.chips').getByRole('link', { name: 'Задания' }).click();
  await expect(page.getByRole('heading', { name: 'Задания' })).toBeVisible();
  await page.getByRole('button', { name: 'Новое задание' }).click();
  await page.getByRole('button', { name: 'Закрыть', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Новое задание' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Новое задание' }).click();
  await page.getByLabel('Название').fill(title);
  await page.getByLabel('Условие').fill('Опишите, как ограничить частоту запросов к API платежей.');
  await page.getByLabel('Специализация').selectOption('Frontend');
  await expect(page.getByLabel('Компетенция')).toHaveValue('');
  await page.getByLabel('Специализация').selectOption('Backend');
  const comp = await page.getByLabel('Компетенция').locator('option').nth(1).textContent();
  await page.getByLabel('Компетенция').selectOption(comp);
  await page.getByRole('button', { name: 'Решить' }).click();
  await expect(page.getByRole('button', { name: 'Решить' })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: 'Предложить подход' }).click();
  await page.getByLabel('Минут на решение').fill('20');
  const pub = page.getByRole('switch', { name: /На витрине/ });
  await pub.click();
  await expect(pub).toHaveAttribute('aria-checked', 'false');
  await pub.click();
  await page.getByRole('switch', { name: /К потребности/ }).click();
  const made = api(page, 'POST', '/api/tasks');
  await page.getByRole('button', { name: 'Создать задание' }).click();
  const task = await (await made).json();
  expect((await made).request().postDataJSON()).toMatchObject({ title, kind: 'approach', minutes: 20, public: true, competency: comp });
  await expect(toast(page)).toHaveText('Задание создано');
  const card = page.locator('.panel', { hasText: `задание ${id}` });
  await expect(card).toContainText(title);
  await expect(card).toContainText('на витрине');
  await expect(card).toContainText('к потребности');
  await noXss(page);

  // кандидат решает
  await demo(page, 'c');
  await open(page, '/candidate/tasks');
  const sc = page.locator('button.cand', { hasText: `задание ${id}` });
  await expect(sc).toContainText(title);
  await noXss(page);
  await sc.click();
  await expect(page.getByRole('heading', { name: 'Ваш подход' })).toBeVisible();
  await noXss(page);
  await page.getByPlaceholder(/Опишите подход/).fill('Токен-бакет на ключ мерчанта в Redis, 429 с Retry-After.');
  await page.getByRole('button', { name: 'Отправить решение' }).click();
  await expect(toast(page)).toContainText('Решение отправлено');

  // работодатель оценивает анонимное решение
  await demo(page, 'e');
  await open(page, '/employer/tasks');
  await expect(card).toContainText('Решений: 1');
  await card.getByRole('button', { name: 'Решения' }).click();
  await expect(page.getByRole('heading', { name: title })).toBeVisible();
  await noXss(page);
  const sub = page.locator('.panel', { hasText: 'Кандидат A-1042' });
  await expect(sub).toContainText('Токен-бакет на ключ мерчанта');
  await sub.getByPlaceholder('Комментарий кандидату, по желанию').fill('Хорошо про Retry-After.');
  const rv = api(page, 'POST', /* id решения */ '/api/tasks/submissions/' + (await sub.locator('[data-act=review]').first().getAttribute('data-id')) + '/review');
  await sub.getByRole('button', { name: 'сильное решение' }).click();
  expect((await rv).request().postDataJSON()).toEqual({ review: 'strong', comment: 'Хорошо про Retry-After.' });
  await expect(toast(page)).toHaveText('Оценка сохранена');
  await expect(sub.locator('.chip.ok')).toHaveText('сильное решение');
  await expect(sub).toContainText('«Хорошо про Retry-After.»');
  // кандидат скрыл профиль: строка без ответа, карточки и кнопок оценки
  const subsUrl = `**/api/tasks/${task.id}/submissions`;
  await page.route(subsUrl, async r => {
    const real = await (await page.request.get(r.request().url(), { headers: r.request().headers() })).json();
    real.items.push({ ...real.items[0], id: 999999, hidden: true, answer: null, candidate: null, review: null });
    await r.fulfill({ json: real });
  });
  await open(page, '/employer/tasks');  // без reload: перезагрузка страницы теряет собранное покрытие
  await open(page, `/employer/tasks/${task.id}`);
  const hiddenRow = page.locator('.panel', { hasText: 'Кандидат скрыл профиль' });
  await expect(hiddenRow).toBeVisible();
  await expect(hiddenRow.locator('[data-act=review]')).toHaveCount(0);
  await page.unroute(subsUrl);
  await open(page, '/employer/tasks');
  await expect(card).toContainText('средняя оценка');

  // кандидат видит оценку
  await demo(page, 'c');
  await open(page, '/candidate/tasks');
  const mine = page.locator('aside .stack-s', { hasText: `задание ${id}` });
  await expect(mine).toContainText('сильное решение');
  await expect(mine).toContainText('«Хорошо про Retry-After.»');
  await noXss(page);

  await demo(page, 'e');
  await open(page, `/employer/tasks/${task.id + 100000}`);
  await expect(page.getByText('Задание не найдено.')).toBeVisible();
});

test('Ладога ↔ кандидат: задание с эталоном — форма по типам, автопроверка, эталон не уходит кандидату, переоценка', async ({ page }) => {
  test.setTimeout(90_000);
  const id = uniq();
  const title = `Эталон ${XSS} ${id}`;
  const seg = name => page.getByRole('button', { name, exact: true });
  await demo(page, 'e');
  await open(page, '/employer/tasks');
  await page.getByRole('button', { name: 'Новое задание' }).click();
  await page.getByLabel('Название').fill(title);
  await page.getByLabel('Условие').fill('Сервис держит 400 запросов в секунду по 25 мс. Сколько соединений занято?');
  await expect(page.getByText('Открытый ответ: решение оцениваете вы')).toBeVisible();
  // каждый тип — свои поля эталона
  await seg('текст').click();
  await page.getByLabel(/Эталонные ответы/).fill('десять; 10');
  const exact = page.getByRole('switch', { name: /Точное совпадение/ });
  await exact.click();
  await expect(exact).toHaveAttribute('aria-checked', 'true');
  await seg('шаблон').click();
  await page.getByLabel(/Шаблон/).fill('1[0]');
  await seg('один вариант').click();
  await page.getByLabel(/Варианты — по одному на строку/).fill('8\n10\n12');  // верный не отмечен — сервер отвечает 422
  await page.getByRole('button', { name: 'Создать задание' }).click();
  await expect(toast(page)).toHaveText('Эталон: номера верных вариантов из списка');
  await seg('несколько вариантов').click();
  await expect(page.getByLabel(/Варианты — по одному на строку/)).toHaveValue('8\n10\n12');  // введённое не теряется
  await seg('число').click();
  await page.getByLabel('Эталон — число').fill('десять');
  await page.getByRole('button', { name: 'Создать задание' }).click();
  await expect(toast(page)).toHaveText('Эталон и допуск — числа');
  await page.getByLabel('Эталон — число').fill('10');
  await page.getByLabel('Допуск ±').fill('0,5');
  const made = api(page, 'POST', '/api/tasks');
  await page.getByRole('button', { name: 'Создать задание' }).click();
  const task = await (await made).json();
  expect((await made).request().postDataJSON()).toMatchObject({ answer_type: 'number', reference: { value: 10, tolerance: 0.5 } });
  await expect(toast(page)).toHaveText('Задание создано');
  const card = page.locator('.panel', { hasText: id }).filter({ hasText: 'автопроверка: число' });
  await expect(card).toContainText('верно 0 из 0');
  await noXss(page);

  // кандидат: поле для числа, эталон в ответах API не приходит
  await demo(page, 'c');
  await open(page, '/candidate/tasks');
  const got = api(page, 'GET', `/api/tasks/${task.id}`);
  await page.locator('button.cand', { hasText: id }).click();
  expect(await (await got).json()).not.toHaveProperty('reference');
  await noXss(page);
  await page.getByPlaceholder('Число, например 42 или 3,14').fill('10,2');
  const sub = api(page, 'POST', `/api/tasks/${task.id}/submit`);
  await page.getByRole('button', { name: 'Отправить решение' }).click();
  const sj = await (await sub).json();
  expect(sj.task).not.toHaveProperty('reference');
  expect(sj).toMatchObject({ answer: '10,2', auto_ok: true });
  await expect(toast(page)).toHaveText('Решение отправлено. Ответ совпал с эталоном');

  // работодатель: эталон у себя, результат автопроверки, переоценка вручную
  await demo(page, 'e');
  await open(page, '/employer/tasks');
  await expect(card).toContainText('верно 1 из 1');
  await open(page, `/employer/tasks/${task.id}`);
  await expect(page.getByText('Эталон (число): 10 ± 0.5')).toBeVisible();
  await noXss(page);
  const row = page.locator('.panel', { hasText: 'Кандидат A-1042' });
  await expect(row).toContainText('верно · автопроверка');
  await expect(row).toContainText('можно переоценить вручную');
  await row.getByRole('button', { name: 'слабо' }).click();
  await expect(toast(page)).toHaveText('Оценка сохранена');
  await expect(row.locator('.chip.warn')).toHaveText('слабо');
  await expect(row).toContainText('верно · автопроверка');

  // кандидат видит и автопроверку, и оценку компании
  await demo(page, 'c');
  await open(page, `/candidate/tasks/${task.id}`);
  await expect(page.getByText('Ответ совпал с эталоном', { exact: true })).toBeVisible();
  await expect(page.locator('.chip', { hasText: 'слабо' })).toBeVisible();
});
