// Публичные экраны: главная с входами двух кабинетов, отдельные вход и регистрация каждой роли, адреса кабинетов
// (History API: ?next=, старые #/-ссылки, «Не найдено»), шапка, дашборд валидации по прямой ссылке /v;
// пути ошибок (401, 5xx, сеть, сломанный ответ).
const fs = require('fs');
const path = require('path');
const { test, expect, open, demo, toast } = require('./fixtures');

const VAL = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'validation.json'), 'utf8'));
const HOME = /:\d+\/$/;  // главная: адрес без пути

// вход по почте на открытом экране входа (в демо код подставляется из ответа сервера)
async function codeLogin(page, label, email) {
  await page.getByLabel(label).fill(email);
  await page.getByRole('button', { name: 'Получить код на почту' }).click();
  await expect(page.getByLabel('Код из письма')).toHaveValue(/^\d{6}$/);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
}

test('главная: «Кандидатам» и «Компаниям» → отдельные регистрация и вход каждой роли', async ({ page }) => {
  await open(page, '/');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('работодатели сами приходят');
  await expect(page.getByText('У кандидата не больше 4 открытых приглашений')).toBeVisible();
  const cand = page.getByRole('region', { name: 'Кандидатам' }), comp = page.getByRole('region', { name: 'Компаниям' });
  // двери — ссылки с настоящими адресами: открываются и в новой вкладке
  await expect(cand.getByRole('link', { name: 'Создать профиль' })).toHaveAttribute('href', '/candidate/signup');
  await expect(cand.getByRole('link', { name: 'Войти' })).toHaveAttribute('href', '/candidate/login');
  await expect(comp.getByRole('link', { name: 'Зарегистрировать компанию' })).toHaveAttribute('href', '/employer/signup');
  await expect(comp.getByRole('link', { name: 'Войти' })).toHaveAttribute('href', '/employer/login');
  // стенд жюри (DEMO=1): тестовые входы прямо на главной, валидация — по ссылке
  const jury = page.locator('.alert', { hasText: 'Стенд жюри.' });
  await expect(jury).toContainText('d.orlov@example.ru');
  await expect(jury).toContainText('m.kovaleva@ladoga-pay.example');
  await expect(jury).toContainText('newco.hr@gmail.com');
  await expect(jury.getByRole('link', { name: '/v' })).toHaveAttribute('href', '/v');

  // кандидат: регистрация — с согласиями 152-ФЗ, вход — без них
  await cand.getByRole('link', { name: 'Создать профиль' }).click();
  await expect(page).toHaveURL(/\/candidate\/signup$/);
  await expect(page.getByRole('heading', { name: 'Создайте профиль' })).toBeVisible();
  await expect(page.getByLabel(/обработку персональных данных по 152-ФЗ/)).toBeVisible();
  await expect(page.getByRole('button', { name: /Войти через ФСП ID/ })).toBeVisible();  // сам вход — 09-fsp-id.spec.js
  await page.locator('#app .prose').getByRole('link', { name: 'войдите' }).click();
  await expect(page).toHaveURL(/\/candidate\/login$/);
  await expect(page.getByRole('heading', { name: 'Вход для кандидатов' })).toBeVisible();
  await expect(page.getByLabel(/152-ФЗ/)).toHaveCount(0);
  await expect(page.getByRole('button', { name: /Войти через ФСП ID/ })).toBeVisible();
  // «Назад» браузера — предыдущий экран, без перезагрузки
  await page.goBack();
  await expect(page.getByRole('heading', { name: 'Создайте профиль' })).toBeVisible();
  await page.goForward();
  await expect(page.getByRole('heading', { name: 'Вход для кандидатов' })).toBeVisible();

  // компания: регистрация и вход — свои экраны
  await page.locator('.brand').click();
  await expect(page).toHaveURL(HOME);
  await comp.getByRole('link', { name: 'Зарегистрировать компанию' }).click();
  await expect(page).toHaveURL(/\/employer\/signup$/);
  await expect(page.getByRole('heading', { name: 'Регистрация компании' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Войти через SSO (Keycloak)' })).toBeVisible();
  await page.locator('#app .prose').getByRole('link', { name: 'войдите' }).click();
  await expect(page).toHaveURL(/\/employer\/login$/);
  await expect(page.getByRole('heading', { name: 'Вход для компаний' })).toBeVisible();
  await expect(page.getByLabel('Рабочая почта')).toBeVisible();

  // Ctrl/⌘-клик по двери — новая вкладка браузера, текущая остаётся на месте
  await page.locator('.brand').click();
  const [tab] = await Promise.all([page.context().waitForEvent('page'), cand.getByRole('link', { name: 'Войти' }).click({ modifiers: ['ControlOrMeta'] })]);
  await tab.waitForLoadState();
  expect(new URL(tab.url()).pathname).toBe('/candidate/login');
  await tab.close();
  await expect(page).toHaveURL(HOME);
});

test('адреса кабинетов: вход с ?next= и возврат, «Не найдено», старые #/-ссылки, учётка другой роли', async ({ page }) => {
  // кабинет кандидата без входа → вход кандидата с адресом возврата → после входа — исходный экран
  await open(page, '/candidate/settings');
  await expect(page).toHaveURL(/\/candidate\/login\?next=%2Fcandidate%2Fsettings$/);
  await expect(page.getByRole('heading', { name: 'Вход для кандидатов' })).toBeVisible();
  await codeLogin(page, 'Почта', 'd.orlov@example.ru');
  await expect(page).toHaveURL(/\/candidate\/settings$/);
  await expect(page.locator('#app .crumbs b')).toHaveText('Настройки и приватность');
  // шапка кабинета: подпись кабинета, логотип — в его дом, переключателя ролей нет
  await expect(page.locator('#cab')).toHaveText('Кабинет кандидата');
  await expect(page.locator('.brand')).toHaveAttribute('href', '/candidate');
  // разделы кабинета — ссылки в порядке пути кандидата; «Профиль» — раздел кабинета, а не шаг регистрации
  await expect(page.locator('nav.subnav a')).toHaveText(['Кабинет', 'Тест', 'Профиль', 'Вакансии', 'Мои отклики', /^Чат/, 'Задачи', 'Настройки и приватность']);
  await page.locator('nav.subnav').getByRole('link', { name: 'Профиль' }).click();
  await expect(page).toHaveURL(/\/candidate\/profile$/);
  await expect(page.getByText('Шаг 2 из 3')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Сохранить', exact: true })).toBeVisible();
  // перезагрузка на адресе кабинета: сервер отдаёт страницу, экран тот же
  await page.reload();
  await expect(page.locator('#app .crumbs b')).toHaveText('Профиль');
  await page.locator('.brand').click();
  await expect(page).toHaveURL(/\/candidate$/);
  // неизвестный адрес внутри кабинета — «Не найдено» со ссылкой в кабинет
  await open(page, '/candidate/nope');
  await expect(page.getByRole('heading', { name: 'Страница не найдена' })).toBeVisible();
  await expect(page.getByText('Такого адреса в кабинете кандидата нет')).toBeVisible();
  await page.getByRole('link', { name: 'В кабинет' }).click();
  await expect(page.locator('#app .crumbs b')).toHaveText('Кабинет кандидата');

  // старые ссылки вида /#/…: тот же экран по новому адресу
  await page.goto('/#/c/settings');
  await expect(page).toHaveURL(/\/candidate\/settings$/);
  await expect(page.locator('#app .crumbs b')).toHaveText('Настройки и приватность');
  await page.goto('/#/e/signup');  // старый вход компании без входа — новый экран входа
  await expect(page).toHaveURL(/\/employer\/login$/);
  await page.goto('/#/c/chat/12');
  await expect(page).toHaveURL(/\/candidate\/chat\/12$/);
  await page.goto('/#/c/nope');  // неизвестный старый ключ кабинета — «Не найдено» в кабинете
  await expect(page).toHaveURL(/\/candidate\/nope$/);
  await expect(page.getByRole('heading', { name: 'Страница не найдена' })).toBeVisible();
  await page.goto('/#/x/y');  // вне кабинетов — главная
  await expect(page).toHaveURL(HOME);
  await page.goto('/#/e/pipeline');  // кабинет компании без входа — вход компании с возвратом
  await expect(page).toHaveURL(/\/employer\/login\?next=%2Femployer%2Finvites$/);
  await codeLogin(page, 'Рабочая почта', 'm.kovaleva@ladoga-pay.example');
  await expect(page).toHaveURL(/\/employer\/invites$/);
  await expect(page.getByRole('heading', { name: 'Приглашения' })).toBeVisible();
  await expect(page.locator('#cab')).toHaveText('Кабинет компании');
  await expect(page.locator('nav.subnav a')).toHaveText(['Подборка', 'Поиск по банку', 'Приглашения', /^Чат/, 'Вакансии', 'Задания', 'Компания']);
  await open(page, '/employer/candidates/A-1042/nope');
  await expect(page.getByRole('heading', { name: 'Страница не найдена' })).toBeVisible();
  await expect(page.getByText('Такого адреса в кабинете компании нет')).toBeVisible();
  // чужой адрес в ?next= не уводит: только экраны своего кабинета
  await page.evaluate(() => { localStorage.removeItem('fsp.tok.e'); TOK.e = null; });
  await page.goto('/employer/login?next=%2F%2Fevil.example');
  await codeLogin(page, 'Рабочая почта', 'm.kovaleva@ladoga-pay.example');
  await expect(page).toHaveURL(/\/employer$/);
  await expect(page.locator('#app .crumbs b')).toHaveText('Подборка');

  // учётка другой роли: вход кандидата почтой компании — отказ и ссылка на вход компании с той же почтой
  await page.evaluate(() => { localStorage.removeItem('fsp.tok.c'); TOK.c = null; });
  await open(page, '/candidate/login');
  await codeLogin(page, 'Почта', 'm.kovaleva@ladoga-pay.example');
  await expect(toast(page)).toHaveText('Эта почта зарегистрирована как работодатель');
  const refuse = page.getByRole('alert');
  await expect(refuse).toContainText('Эта учётная запись зарегистрирована как компания.');
  await refuse.getByRole('link', { name: 'Войти как компания' }).click();
  await expect(page).toHaveURL(/\/employer\/login$/);
  await expect(page.getByLabel('Рабочая почта')).toHaveValue('m.kovaleva@ladoga-pay.example');
  expect(await page.evaluate(() => localStorage.getItem('fsp.tok.c'))).toBeNull();  // токен чужой роли кандидату не достался
});

test('шапка: без переключателя ролей и карты экранов; два кабинета в одном браузере', async ({ page }) => {
  await open(page, '/');
  await expect(page.getByRole('navigation', { name: 'Роль' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Экраны' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /Валидация|дашборд валидации/ })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /^Демо: войти как/ })).toHaveCount(0);
  await expect(page.locator('#cab')).toHaveText('обратный найм в ИТ');
  await expect(page.locator('.brand')).toHaveAttribute('href', '/');
  // на экранах входа — только ФСП ID / SSO и почта, без легаси-кнопок демо-входа; вне кабинета логотип — на главную
  for (const p of ['/candidate/signup', '/candidate/login', '/employer/signup', '/employer/login']) {
    await open(page, p);
    await expect(page.getByRole('button', { name: /^Демо: войти как/ })).toHaveCount(0);
    await expect(page.locator('.brand')).toHaveAttribute('href', '/');
    await expect(page.locator('#logout')).toBeHidden();
  }
  await expect(page.getByText('Демо-вход работает только')).toHaveCount(0);
  // вход обеих ролей: на главной — «Продолжить в кабинете», логотип в кабинете — в его дом
  await demo(page, 'c');
  await demo(page, 'e');
  await page.locator('nav.subnav').getByRole('link', { name: 'Поиск по банку' }).click();
  await page.locator('.brand').click();
  await expect(page).toHaveURL(/\/employer$/);
  await open(page, '/');
  await page.getByRole('region', { name: 'Кандидатам' }).getByRole('link', { name: 'Продолжить в кабинете кандидата' }).click();
  await expect(page.locator('#app .crumbs b')).toHaveText('Кабинет кандидата');
  await open(page, '/');
  await page.getByRole('region', { name: 'Компаниям' }).getByRole('link', { name: 'Продолжить в кабинете компании' }).click();
  await expect(page.locator('#app .crumbs b')).toHaveText('Подборка');
  // на экране входа с живым токеном — «Вы уже вошли»
  await open(page, '/employer/login');
  await page.getByRole('link', { name: 'В кабинет' }).click();
  await expect(page).toHaveURL(/\/employer$/);
});

test('валидация /v по прямой ссылке без входа: без прогона — подсказка, с прогоном — цифры', async ({ page }) => {
  // результат прогона лежит в общем backend/var/validation.json — не трогаем его, ответ API подменяем
  await page.route('**/api/validation', r => r.fulfill({ status: 404, json: { detail: 'Прогона ещё не было' } }));
  await page.goto('/v');
  await expect(page.getByRole('heading', { name: 'Валидация подбора и теста' })).toBeVisible();
  await expect(page).toHaveURL(/\/v$/);  // без входа не уводит на экран входа
  await expect(page.getByText('прогон не запускался')).toBeVisible();
  await expect(page.getByText('Нет данных. Нажмите «Запустить прогон»')).toHaveCount(5);
  await expect(page.locator('#cab')).toHaveText('обратный найм в ИТ');  // вне кабинетов

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
  await open(page, '/candidate/vacancies');
  await expect(page).toHaveURL(/\/candidate\/login\?next=%2Fcandidate%2Fvacancies$/);  // после входа — обратно сюда
  await expect(page.getByRole('heading', { name: 'Вход для кандидатов' })).toBeVisible();
  await expect(toast(page)).toBeVisible();
  await open(page, '/employer');
  await expect(page).toHaveURL(/\/employer\/login\?next=%2Femployer$/);
  await expect(page.getByRole('heading', { name: 'Вход для компаний' })).toBeVisible();
  expect(await page.evaluate(() => [localStorage.getItem('fsp.tok.c'), localStorage.getItem('fsp.tok.e')])).toEqual([null, null]);
});

test('ошибки сервера: тост на 5xx, «Сервер недоступен», экран «Повторить» при сломанном ответе', async ({ page }) => {
  await demo(page, 'c');
  await page.route('**/api/candidate/invites', r => r.fulfill({ status: 500, json: { detail: 'Внутренняя ошибка сервера' } }));
  await open(page, '/candidate/vacancies');
  await open(page, '/candidate');
  await expect(toast(page)).toHaveText('Внутренняя ошибка сервера');
  await expect(page.getByText('Не удалось загрузить приглашения')).toBeVisible();
  await expect(page.getByText('Приглашений пока нет')).toHaveCount(0);
  await page.unroute('**/api/candidate/invites');
  await page.getByRole('button', { name: 'Повторить' }).click();
  await expect(page.getByText('Не удалось загрузить приглашения')).toHaveCount(0);

  await page.route('**/api/candidate/invites', r => r.fulfill({ status: 502, contentType: 'text/html', body: '<h1>Bad gateway</h1>' }));
  await open(page, '/candidate/vacancies');
  await open(page, '/candidate');
  await expect(toast(page)).toHaveText('Ошибка 502');
  await page.unroute('**/api/candidate/invites');

  await page.route('**/api/candidate/invites', r => r.abort('connectionrefused'));
  await open(page, '/candidate/vacancies');
  await open(page, '/candidate');
  await expect(toast(page)).toHaveText('Сервер недоступен');
  await page.unroute('**/api/candidate/invites');

  // ответ не той формы — экран не падает, предлагает повторить
  await demo(page, 'e');
  await page.route('**/api/employer/pipeline', r => r.fulfill({ json: { items: null, quota: null } }));
  await open(page, '/employer/invites');
  await expect(page.getByText('Не удалось показать экран: данные не загрузились.')).toBeVisible();
  await page.unroute('**/api/employer/pipeline');
  await page.getByRole('button', { name: 'Повторить' }).click();
  await expect(page.getByRole('heading', { name: 'Приглашения' })).toBeVisible();
  await expect(page.locator('table.tbl')).toBeVisible();
});
