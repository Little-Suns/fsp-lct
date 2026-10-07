// Публичные экраны: главная, карта экранов, дашборд валидации; пути ошибок (401, 5xx, сеть, сломанный ответ).
const fs = require('fs');
const path = require('path');
const { test, expect, open, demo, toast } = require('./fixtures');

const VAL = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'validation.json'), 'utf8'));

test('главная: герой, двери ролей и ссылка на валидацию', async ({ page }) => {
  await open(page, '/');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('работодатели сами приходят');
  await expect(page.getByText('У кандидата не больше 4 открытых приглашений')).toBeVisible();
  await page.getByRole('button', { name: 'Я разработчик' }).click();
  await expect(page.getByRole('heading', { name: 'Создайте профиль' })).toBeVisible();
  await expect(page.getByRole('button', { name: /Войти через ФСП ID/ })).toBeVisible();  // сам вход — 09-fsp-id.spec.js
  await page.locator('.brand').click();
  await page.getByRole('button', { name: 'Я нанимаю' }).click();
  await expect(page.getByRole('heading', { name: 'Вход для компаний' })).toBeVisible();
  // без входа кабинет уводит на экран входа своей роли
  await open(page, '/e/pipeline');
  await expect(page).toHaveURL(/#\/e\/signup$/);
  await open(page, '/c/home');
  await expect(page).toHaveURL(/#\/c\/signup$/);
});

test('карта экранов: открытие, переход, закрытие по Esc и по фону', async ({ page }) => {
  await open(page, '/');
  await page.getByRole('button', { name: 'Экраны' }).click();
  const drawer = page.getByRole('dialog', { name: 'Карта экранов' });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole('button', { name: /Главная/ })).toHaveAttribute('aria-current', 'true');
  await drawer.getByRole('button', { name: /Дашборд валидации/ }).click();
  await expect(drawer).toBeHidden();
  await expect(page).toHaveURL(/#\/v$/);
  await page.getByRole('button', { name: 'Экраны' }).click();
  await page.keyboard.press('Escape');
  await expect(drawer).toBeHidden();
  await page.getByRole('button', { name: 'Экраны' }).click();
  await page.locator('.overlay').click({ position: { x: 10, y: 10 } });
  await expect(drawer).toBeHidden();
  await page.getByRole('button', { name: 'Экраны' }).click();
  // переход на текущий экран просто закрывает карту
  await drawer.getByRole('button', { name: /Дашборд валидации/ }).click();
  await expect(drawer).toBeHidden();
  await page.getByRole('button', { name: 'Экраны' }).click();
  await drawer.getByRole('button', { name: 'Закрыть' }).click();
  await expect(drawer).toBeHidden();
});

test('валидация /v: без прогона — подсказка, с прогоном — цифры', async ({ page }) => {
  // результат прогона лежит в общем backend/var/validation.json — не трогаем его, ответ API подменяем
  await page.route('**/api/validation', r => r.fulfill({ status: 404, json: { detail: 'Прогона ещё не было' } }));
  await open(page, '/v');
  await expect(page.getByRole('heading', { name: 'Валидация подбора и теста' })).toBeVisible();
  await expect(page.getByText('прогон не запускался')).toBeVisible();
  await expect(page.getByText('Нет данных. Нажмите «Запустить прогон»')).toHaveCount(5);
  await expect(page.locator('.roles button[data-role=v]')).toHaveAttribute('aria-current', 'true');

  // демо-стенд (DEMO=1): прогон кнопкой; ответ подменён — настоящий пересчёт писал бы в общий validation.json
  const RUN = '**/api/validation/run*';
  await page.route(RUN, r => r.fulfill({ status: 409, json: { detail: 'В базе нет синтетики: сначала засейте её' } }));
  await page.getByRole('button', { name: 'Запустить прогон' }).click();
  await expect(page.getByText('В базе нет синтетики: сначала засейте её')).toBeVisible();
  await page.unroute(RUN);
  let release;
  const held = new Promise(res => { release = res; });
  await page.route(RUN, async r => { await held; await r.fulfill({ json: VAL }); });
  await page.getByRole('button', { name: 'Запустить прогон' }).click();
  await expect(page.getByRole('button', { name: 'Считаем… до минуты' })).toBeDisabled();
  release();
  await expect(page.getByText('1500 синтетических кандидатов · 250 потребностей')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Пересчитать' })).toBeEnabled();
  await page.unroute(RUN);

  await page.unroute('**/api/validation');
  await page.route('**/api/validation', r => r.fulfill({ json: VAL }));
  await page.reload();
  await expect(page.getByText('1500 синтетических кандидатов · 250 потребностей')).toBeVisible();
  await expect(page.getByText(/синтетика · прогон/)).toBeVisible();
  const quality = page.locator('.panel', { has: page.getByRole('heading', { name: 'Качество выдачи, top-10' }) });
  await expect(quality.locator('.bar .v').last()).toHaveText('0,68');
  await expect(quality.getByText('Релевантной считаем оценку ≥ 2')).toBeVisible();
  await expect(quality.getByRole('cell', { name: 'вилка ниже рынка' })).toBeVisible();
  const market = page.locator('.panel', { has: page.getByRole('heading', { name: 'Симуляция рынка' }) });
  await expect(market.getByRole('columnheader', { name: 'Только квота' })).toBeVisible();
  await expect(market.getByRole('row', { name: /Доля принятых/ })).toContainText('9 %');
  await expect(market.getByText('Раундов симуляции: 4')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Симуляция: LLM-«читер»' })).toBeVisible();
  await expect(page.getByText('Поймано проверкой на несогласованность')).toBeVisible();
  await expect(page.getByText(/Ложные срабатывания на честных кандидатах/)).toBeVisible();
  await expect(page.getByText('Тот же грейд при пересдаче')).toBeVisible();
  await expect(page.getByText('Оценка θ и «истинный» θ')).toBeVisible();
  // разделяющая сила: матрица «истинный грейд × грейд теста» (доли строки), соседние грейды, специализации, задания
  const sep = page.locator('.panel', { has: page.getByRole('heading', { name: 'Разделяющая сила теста' }) });
  const heat = sep.locator('table.heat');
  await expect(heat.locator('caption')).toContainText('Строки — истинный грейд');
  await expect(heat.getByRole('columnheader', { name: 'Lead' })).toBeVisible();
  const intern = heat.getByRole('row', { name: /^Intern/ });
  await expect(intern.getByRole('rowheader')).toHaveText('Intern');
  await expect(intern.locator('td.diag')).toHaveText('97 %');  // 194 из 200 — на диагонали
  await expect(intern.locator('td.diag')).toHaveAttribute('aria-label', '97 %, совпадение');  // рамку скринридер не видит
  await expect(heat.locator('td.diag')).toHaveCount(5);
  await expect(sep.getByText('Точное совпадение грейда')).toBeVisible();
  await expect(sep.getByText(/по θ̂ без запаса SE — \d+ %/)).toBeVisible();
  await expect(sep.getByRole('row', { name: /Intern \| Junior/ })).toContainText('0,88');
  await expect(sep.getByRole('row', { name: /^Backend/ })).toContainText('24');
  await expect(sep.getByRole('row', { name: /крутизна кривой 2PL/ })).toBeVisible();
  await expect(sep.getByText(/Слабо различающих заданий/)).toBeVisible();

  // второй вариант отчёта: эксперты с каппой, без «только квоты», эксперимент вместо симуляции
  const alt = structuredClone(VAL);
  Object.assign(alt.dataset, { gold_experts: 120, kappa: 0.71, with_achievements: 400, with_cf: 160 });
  delete alt.quality.by_kind; delete alt.quality.relevant_threshold;
  alt.market.rows.forEach(r => { delete r.quota_only; });
  delete alt.market.top5_share;
  alt.cheater.simulated = false; delete alt.cheater.false_alarm;
  delete alt.stability.theta_corr; delete alt.stability.retest_same_grade_no_hysteresis;
  alt.separation.simulated = false;
  ['accuracy_point', 'adjacent', 'by_spec', 'items'].forEach(k => { delete alt.separation[k]; });
  await page.unroute('**/api/validation');
  await page.route('**/api/validation', r => r.fulfill({ json: alt }));
  await page.reload();
  await expect(page.getByText('120 «золотых» пар с экспертами, κ Коэна = 0,71')).toBeVisible();
  await expect(page.getByRole('columnheader', { name: 'Только квота' })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Эксперимент: LLM-«читер»' })).toBeVisible();
  // старый отчёт без деталей разделяющей силы: матрица есть, дополнительных таблиц нет
  await expect(page.locator('table.heat td.diag')).toHaveCount(5);
  await expect(page.getByText('грейд по θ − SE', { exact: true })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: 'AUC по θ̂' })).toHaveCount(0);
  await expect(page.getByText(/Слабо различающих заданий/)).toHaveCount(0);
});

test('401: протухший токен кандидата и работодателя — обратно на вход', async ({ page }) => {
  await page.addInitScript(() => { localStorage.setItem('fsp.tok.c', 'stale'); localStorage.setItem('fsp.tok.e', 'stale'); });
  await open(page, '/c/home');
  await expect(page).toHaveURL(/#\/c\/signup$/);
  await expect(page.getByRole('heading', { name: 'Создайте профиль' })).toBeVisible();
  await expect(toast(page)).toBeVisible();
  await open(page, '/e/picks');
  await expect(page).toHaveURL(/#\/e\/signup$/);
  await expect(page.getByRole('heading', { name: 'Вход для компаний' })).toBeVisible();
  expect(await page.evaluate(() => [localStorage.getItem('fsp.tok.c'), localStorage.getItem('fsp.tok.e')])).toEqual([null, null]);
});

test('ошибки сервера: тост на 5xx, «Сервер недоступен», экран «Повторить» при сломанном ответе', async ({ page }) => {
  await demo(page, 'c');
  await page.route('**/api/candidate/invites', r => r.fulfill({ status: 500, json: { detail: 'Внутренняя ошибка сервера' } }));
  await open(page, '/c/vacancies');
  await open(page, '/c/home');
  await expect(toast(page)).toHaveText('Внутренняя ошибка сервера');
  await expect(page.getByText('Не удалось загрузить приглашения')).toBeVisible();
  await expect(page.getByText('Приглашений пока нет')).toHaveCount(0);
  await page.unroute('**/api/candidate/invites');
  await page.getByRole('button', { name: 'Повторить' }).click();
  await expect(page.getByText('Не удалось загрузить приглашения')).toHaveCount(0);

  await page.route('**/api/candidate/invites', r => r.fulfill({ status: 502, contentType: 'text/html', body: '<h1>Bad gateway</h1>' }));
  await open(page, '/c/vacancies');
  await open(page, '/c/home');
  await expect(toast(page)).toHaveText('Ошибка 502');
  await page.unroute('**/api/candidate/invites');

  await page.route('**/api/candidate/invites', r => r.abort('connectionrefused'));
  await open(page, '/c/vacancies');
  await open(page, '/c/home');
  await expect(toast(page)).toHaveText('Сервер недоступен');
  await page.unroute('**/api/candidate/invites');

  // ответ не той формы — экран не падает, предлагает повторить
  await demo(page, 'e');
  await page.route('**/api/employer/pipeline', r => r.fulfill({ json: { items: null, quota: null } }));
  await open(page, '/e/pipeline');
  await expect(page.getByText('Не удалось показать экран: данные не загрузились.')).toBeVisible();
  await page.unroute('**/api/employer/pipeline');
  await page.getByRole('button', { name: 'Повторить' }).click();
  await expect(page.getByRole('heading', { name: 'Приглашения' })).toBeVisible();
  await expect(page.locator('table.tbl')).toBeVisible();
});
