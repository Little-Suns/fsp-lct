// Новый кандидат: вход по коду с согласиями 152-ФЗ, профиль и PDF-резюме, тест на заявленный грейд до вердикта,
// достижения (внешние API замоканы), настройки приватности, выгрузка данных и удаление аккаунта.
const fs = require('fs');
const { test, expect, open, toast, api } = require('./fixtures');
const { tinyPdf, uniq } = require('./helpers');

// вход по почте: код в демо приходит в ответе и подставляется в поле
async function signup(page, email, { c152 = true, publish = false } = {}) {
  await open(page, '/candidate/signup');
  await page.getByRole('button', { name: 'Получить код на почту' }).click();
  await expect(toast(page)).toHaveText('Укажите почту');
  await page.getByLabel('Почта').fill(email);
  if (c152) await page.getByLabel(/обработку персональных данных по 152-ФЗ/).check();
  if (publish) await page.getByLabel(/Показывать мою обезличенную карточку/).check();
  await page.getByRole('button', { name: 'Получить код на почту' }).click();
  await expect(toast(page)).toHaveText('Код отправлен на ' + email);
  await expect(page.getByLabel('Код из письма')).toHaveValue(/^\d{6}$/);
  await expect(page.getByText('Демо-режим: письма не отправляются')).toBeVisible();
  // повторный код раньше чем через 60 с — 429 с понятным текстом, прежний код остаётся в силе
  const again = api(page, 'POST', '/api/auth/email');
  await page.getByRole('button', { name: 'Отправить код ещё раз' }).click();
  expect((await again).status()).toBe(429);
  await expect(toast(page)).toContainText('Код уже отправлен — новый можно запросить через');
  await expect(page.getByLabel('Код из письма')).toHaveValue(/^\d{6}$/);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Профиль' })).toBeVisible();
}

// все задания до конца: выбор ответа или строка в коде (+ комментарий к ревью); checks — таймер и сюжет посреди теста
async function answerAll(page, checks = false) {
  const finish = page.getByRole('button', { name: 'Посмотреть категорию' });
  let answered = 0;
  for (; answered < 60 && !(await finish.isVisible()); answered++) {
    const next = page.getByRole('button', { name: 'Дальше' });
    if (await page.locator('#code-ed').count()) {  // задача на код (с песочницей, одна за полный тест): отправляем шаблон — разбор в 09-code
      const sent = page.waitForResponse(r => r.url().endsWith('/api/quest/answer') && r.request().method() === 'POST');
      await page.getByRole('button', { name: 'Отправить решение' }).click();
      expect((await sent).ok()).toBe(true);
      await expect(page.locator('#code-ed')).toHaveCount(0);
      continue;
    }
    await expect(next).toBeDisabled();
    const opts = page.locator('.opt');
    if (await opts.count()) await opts.nth(answered % (await opts.count())).click();
    else {
      await page.locator('.code button[data-act=mark]').nth(1).click();
      await expect(page.getByText('Отмечена строка 2.')).toBeVisible();
      if (await page.locator('#rv-comment').count()) await page.locator('#rv-comment').fill('Гонка: нет блокировки строки при повторе.');
    }
    if (checks && answered === 0) {  // таймер сцены идёт; с сюжетом у сцены — часы истории
      const t = await page.locator('#timer span').textContent();
      await expect(page.locator('#timer span')).not.toHaveText(t, { timeout: 3000 });
      await expect(page.locator('.story .t')).toHaveText('02:14');  // первая сцена — начало истории Backend (items.STORY)
    }
    if (checks && answered === 1) {  // сюжет можно выключить посреди теста — задание и его условие те же, без часов и заголовка сцены
      const cond = await page.locator('.story').textContent();
      await page.getByRole('switch', { name: 'сюжет' }).click();
      await expect(page.locator('.crumbs b')).toHaveText(/^Задание \d+$/);
      await expect(page.locator('.story .t')).toHaveCount(0);
      expect(cond).toContain(await page.locator('.story').textContent());
      if (await opts.count()) await opts.first().click(); else await page.locator('.code button[data-act=mark]').nth(1).click();
    }
    await expect(next).toBeEnabled();
    // ждём ответ сервера и новое задание («Дальше» снова неактивна) или финал;
    // заголовок сцены не годится: у соседних заданий он может совпасть — выбор адаптивный и случайный
    const answer = page.waitForResponse(r => r.url().endsWith('/api/quest/answer') && r.request().method() === 'POST');
    await next.click();
    expect((await answer).ok()).toBe(true);
    await expect(async () => {
      expect(await finish.isVisible() || await page.locator('#code-ed').count() > 0 || await next.isDisabled()).toBe(true);
    }).toPass();
  }
  return answered;
}

async function fillProfile(page) {
  await page.getByLabel('Имя и фамилия').fill('Ева Тестова');
  await page.getByLabel('Telegram').fill('@eva_e2e');
  await page.getByLabel('Минимальная зарплата на руки').fill('150000');
  await page.getByLabel('Город').fill('Казань');
}

test('вход: некорректная почта — текст сервера', async ({ page }) => {
  await open(page, '/candidate/signup');
  await page.getByLabel('Почта').fill('not-an-email');
  await page.getByRole('button', { name: 'Получить код на почту' }).click();
  await expect(toast(page)).toHaveText('Некорректная почта');
  await open(page, '/employer/login');
  await page.getByLabel('Рабочая почта').fill('hr.example.ru');
  await page.getByRole('button', { name: 'Получить код на почту' }).click();
  await expect(toast(page)).toHaveText('Некорректная почта');
});

test('согласия с регистрации доходят до шага «Профиль», но не достаются следующему во вкладке', async ({ page }) => {
  await signup(page, `consent-a-${uniq()}@example.ru`, { publish: true });
  const c152 = page.getByLabel(/обработку персональных данных по 152-ФЗ/), pub = page.getByLabel(/Показывать мою обезличенную карточку/);
  await expect(c152).toBeChecked();  // отмечено на регистрации — тот же человек
  await expect(pub).toBeChecked();
  await page.locator('#me').click();
  await page.locator('#logout').click();
  await expect(page).toHaveURL(/\/candidate\/login$/);
  const email = `consent-b-${uniq()}@example.ru`;
  await page.getByLabel('Почта').fill(email);
  await page.getByRole('button', { name: 'Получить код на почту' }).click();
  await expect(page.getByLabel('Код из письма')).toHaveValue(/^\d{6}$/);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Профиль' })).toBeVisible();
  await expect(c152).not.toBeChecked();  // следующий человек ставит согласия сам
  await expect(pub).not.toBeChecked();
});

test('без согласия на обработку ПДн профиль не сохраняется', async ({ page }) => {
  await signup(page, `noconsent-${uniq()}@example.ru`, { c152: false });
  await fillProfile(page);
  await page.getByRole('button', { name: 'Сохранить и перейти к тесту' }).click();
  await expect(toast(page)).toContainText('Нужно согласие на обработку персональных данных');
  // согласие — здесь же, в шаге «Профиль»: введённое не потерялось
  await expect(page.getByLabel('Имя и фамилия')).toHaveValue('Ева Тестова');
  await expect(page.getByLabel(/обработку персональных данных по 152-ФЗ/)).not.toBeChecked();
  // экраны кабинета без профиля предлагают его заполнить (тест — тоже: без профиля нет специализации)
  for (const r of ['/candidate/test', '/candidate/test/run', '/candidate', '/candidate/vacancies', '/candidate/applications', '/candidate/tasks', '/candidate/settings', '/candidate/vacancies/1', '/candidate/tasks/1']) {
    await open(page, r);
    await expect(page.getByRole('heading', { name: 'Профиль ещё не создан' })).toBeVisible();
  }
  await open(page, '/candidate/test/result');
  await expect(page.getByRole('heading', { name: 'Тест ещё не пройден' })).toBeVisible();
  // согласие в шаге «Профиль» вместо экрана регистрации: профиль сохраняется, дальше — тест
  await open(page, '/candidate/profile');
  await expect(page.getByText('Шаг 2 из 3')).toBeVisible();
  await fillProfile(page);
  await page.getByLabel(/обработку персональных данных по 152-ФЗ/).check();
  const saved = api(page, 'POST', '/api/candidate/profile');
  await page.getByRole('button', { name: 'Сохранить и перейти к тесту' }).click();
  expect((await saved).request().postDataJSON()).toMatchObject({ consent_152: true, consent_publish: false });
  await expect(page).toHaveURL(/\/candidate\/test$/);
  await expect(page.getByRole('heading', { name: '02:14: Рей сбежал, а карта GPS-ошейника пустая' })).toBeVisible();
});

test('кандидат: регистрация → профиль и PDF → тест на грейд → вердикт и история → настройки → выгрузка → удаление', async ({ page }) => {
  test.setTimeout(180_000);
  const email = `eva-${uniq()}@example.ru`;
  await signup(page, email);

  // профиль: проверки формы, резюме PDF, поля
  await expect(page.getByText('Сохраните профиль, чтобы подключить ФСП')).toBeVisible();
  await page.getByRole('button', { name: 'Сохранить и перейти к тесту' }).click();
  await expect(toast(page)).toHaveText('Укажите имя');
  await page.getByLabel('Имя и фамилия').fill('Ева Тестова');
  await page.getByRole('button', { name: 'Сохранить и перейти к тесту' }).click();
  await expect(toast(page)).toHaveText('Укажите минимальную зарплату');

  const cv = api(page, 'POST', '/api/candidate/cv');
  await page.locator('#cv-file').setInputFiles({ name: 'eva_cv.pdf', mimeType: 'application/pdf',
    buffer: tinyPdf('Eva Testova. eva@example.ru, tg: eva_dev. 2021 - present Acme Corp. Python developer, 4 years of experience. '
      + 'Django, PostgreSQL, Docker, Kafka. Team lead, mentor. Communication skills, ownership.') });
  const parsed = (await (await cv).json()).parsed;
  expect(parsed.contacts).toEqual({ name: 'Eva Testova', email: 'eva@example.ru', tg: '@eva_dev' });
  expect([parsed.roles, parsed.soft_skills]).toEqual([['Тимлид', 'Ментор'], ['Коммуникация', 'Самостоятельность']]);
  await expect(toast(page)).toHaveText('Резюме разобрано: проверьте поля');
  await expect(page.getByText('eva_cv.pdf')).toBeVisible();
  await expect(page.getByText(/Распознано: .*Python/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Заменить' })).toBeVisible();
  // подсказка грейда по резюме: предвыбор с объяснением, выбирает кандидат, тест подтверждает
  expect(parsed.grade_hint).toEqual({ grade: 'Lead', why: 'в резюме — руководство командой; опыт 4 г. (по стажу — скорее Middle)' });
  await expect(page.locator('#grade-hint')).toHaveText('По резюме похоже на Lead: в резюме — руководство командой; опыт 4 г. (по стажу — скорее Middle). Это подсказка — выберите сами, тест подтвердит или нет.');
  await expect(page.getByRole('button', { name: 'Lead', exact: true })).toHaveAttribute('aria-pressed', 'true');
  // расширенный разбор: контакты и места работы видны, имя уже введено — не перетираем, пустой Telegram — заполняем
  await expect(page.getByText('Контакты: Eva Testova · eva@example.ru · @eva_dev')).toBeVisible();
  await expect(page.getByText('Места работы: 2021 — н. в. · Acme Corp')).toBeVisible();
  await expect(page.getByLabel('Имя и фамилия')).toHaveValue('Ева Тестова');
  await expect(page.getByLabel('Telegram')).toHaveValue('@eva_dev');
  const chip = name => page.locator('button.chip[data-act=ptoggle]', { hasText: name });
  await expect(chip('Тимлид')).toHaveClass(/on/);
  await expect(chip('Коммуникация')).toHaveClass(/on/);
  await chip('Коммуникация').click();
  await expect(chip('Коммуникация')).not.toHaveClass(/on/);
  await chip('Обучаемость').click();
  await expect(chip('Обучаемость')).toHaveClass(/on/);
  await expect(page.locator('aside')).toContainText('со слов кандидата');
  // не PDF — понятная ошибка
  await page.locator('#cv-file').setInputFiles({ name: 'cv.txt', mimeType: 'application/pdf', buffer: Buffer.from('hello') });
  await expect(toast(page)).toHaveText('Нужен PDF-файл');

  await fillProfile(page);
  await page.getByLabel('Специализация').selectOption('Frontend');
  await expect(page.getByLabel('Стек-трек')).not.toHaveValue('Python');
  await page.getByLabel('Специализация').selectOption('Backend');
  await page.getByLabel('Стек-трек').selectOption('Python');
  await page.getByRole('button', { name: 'Junior', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Junior', exact: true })).toHaveAttribute('aria-pressed', 'true');
  // форматы: снять оба по умолчанию — ошибка, затем выбрать
  await page.locator('.chips').getByRole('button', { name: 'Гибрид' }).click();
  await page.locator('.chips').getByRole('button', { name: 'Удалённо' }).click();
  await page.getByRole('button', { name: 'Сохранить и перейти к тесту' }).click();
  await expect(toast(page)).toHaveText('Выберите хотя бы один формат');
  await page.locator('.chips').getByRole('button', { name: 'Удалённо' }).click();
  await expect(page.locator('.chips').getByRole('button', { name: 'Удалённо' })).toHaveClass(/on/);
  const saved = api(page, 'POST', '/api/candidate/profile');
  await page.getByRole('button', { name: 'Сохранить и перейти к тесту' }).click();
  // резюме загружено до профиля: сервер его не хранил, приходит в POST /profile и сохраняется с согласием
  expect((await saved).request().postDataJSON()).toMatchObject({ cv_filename: 'eva_cv.pdf', cv_text: expect.stringContaining('Acme Corp') });
  const prof = await (await saved).json();
  expect(prof.cv_filename).toBe('eva_cv.pdf');
  expect(prof.experience).toEqual([expect.objectContaining({ from: 2021, to: null, title: expect.stringContaining('Acme Corp') })]);
  expect(prof).toMatchObject({ name: 'Ева Тестова', spec: 'Backend', track: 'Python', min: 150000, consent_152: true, consent_publish: false,
    roles: ['Тимлид', 'Ментор'], soft_skills: ['Самостоятельность', 'Обучаемость'] });
  await expect(toast(page)).toHaveText('Профиль сохранён');

  // тест-квест: вводная, выбор грейда, сюжет
  await expect(page.getByRole('heading', { name: '02:14: Рей сбежал, а карта GPS-ошейника пустая' })).toBeVisible();
  await page.getByRole('group', { name: 'Грейд теста' }).getByRole('button', { name: 'Middle' }).click();
  await expect(page.getByRole('group', { name: 'Грейд теста' }).getByRole('button', { name: 'Middle' })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('switch', { name: /Сюжет включён/ }).click();
  await expect(page.getByRole('switch', { name: /Сюжет выключен/ })).toHaveAttribute('aria-checked', 'false');
  await page.getByRole('switch', { name: /Сюжет выключен/ }).click();
  // экспресс-тест для знакомства: 5 заданий по минуте, предварительная категория с пометкой
  await expect(page.getByRole('group', { name: 'Режим теста' })).toContainText('Кулдаун 90 дней не запускает');
  const exStart = api(page, 'POST', '/api/quest/start');
  await page.getByRole('button', { name: 'Экспресс-тест для знакомства (3–5 мин)' }).click();
  expect((await exStart).request().postDataJSON()).toMatchObject({ story: true, target_grade: 'Middle', mode: 'express' });
  expect(await (await exStart).json()).toMatchObject({ mode: 'express', time_limit_s: 60, progress: { total: 5 } });
  await expect(page.locator('.quest-top')).toContainText('экспресс · ');
  await expect(page.locator('#timer span')).toHaveText(/^(1:00|0:5\d)$/);
  await expect(page.locator('#tmo')).toBeHidden();
  // таймер на нуле: плашка про льготные секунды, после них — «не засчитается» (минуту не ждём: остаток подменён при продолжении сессии)
  await page.route('**/api/quest/start', async r => {
    const res = await r.fetch();
    await r.fulfill({ response: res, json: { ...(await res.json()), remaining_s: 1, deadline_s: 5 } });
  }, { times: 1 });
  await page.getByRole('switch', { name: 'сюжет' }).click();
  await expect(page.locator('#tmo.warn')).toContainText(/Время вышло\. Ответ засчитается, если отправить его в ближайшие [12] с\./);
  await expect(page.locator('#timer span')).toHaveText('0:00');
  await expect(page.locator('#tmo.bad')).toContainText('Время вышло, ответ не засчитается — переходите к следующему.', { timeout: 5000 });
  await page.getByRole('switch', { name: 'сюжет' }).click();  // настоящий остаток: плашки нет
  await expect(page.locator('#tmo')).toBeHidden();
  expect(await answerAll(page)).toBe(5);
  await expect(page.getByText('Экспресс-тест · Все задания пройдены · 5 из 5')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Рей дома, сервис жив' })).toBeVisible();  // финал сюжета Backend (items.STORY)
  const exFin = api(page, 'POST', '/api/quest/finish');
  await page.getByRole('button', { name: 'Посмотреть категорию' }).click();
  expect(await (await exFin).json()).toMatchObject({ applied: true, express: true, mode: 'express', assessment_label: 'экспресс-оценка' });
  await expect(page.getByText('Экспресс-оценка.')).toBeVisible();
  await expect(page.locator('.trust')).toContainText('Экспресс-оценка');
  await expect(page.locator('table.tbl tbody tr').first()).toContainText('экспресс');
  // полный тест сразу после экспресса: кулдаун не запущен, повторный экспресс предварительную категорию не изменит
  await page.getByRole('button', { name: 'Пройти тест ещё раз' }).click();
  await expect(page.getByRole('group', { name: 'Режим теста' })).toContainText('Предварительная категория уже есть');
  const start = api(page, 'POST', '/api/quest/start');
  await page.getByRole('button', { name: 'Полный тест (~40 мин)' }).click();
  expect((await start).request().postDataJSON()).toMatchObject({ story: true, target_grade: 'Middle', mode: 'full' });

  const answered = await answerAll(page, true);
  expect(answered).toBeGreaterThan(3);
  await expect(page.getByRole('heading', { name: 'Тест закончен' })).toBeVisible();
  const fin = api(page, 'POST', '/api/quest/finish');
  await page.getByRole('button', { name: 'Посмотреть категорию' }).click();
  const res = await (await fin).json();
  expect(res.target.grade).toBe('Middle');
  await expect(page.getByText('Ваша категория')).toBeVisible();
  // повторный finish (двойной клик, гонка) — сервер отвечает 409: тост и экран результата без падения
  await page.route('**/api/quest/finish', r => r.fulfill({ status: 409, json: { detail: 'Тест уже завершён: начните новый' } }));
  await page.evaluate(() => ACT.finish());
  await expect(toast(page)).toHaveText('Тест уже завершён: начните новый');
  await page.unroute('**/api/quest/finish');

  // результат: категория, вердикт по заявленному грейду, история
  await expect(page.getByText('Ваша категория')).toBeVisible();
  await expect(page.locator('.cat').first()).toContainText('Backend');
  await expect(page.getByText(`Тест на Middle, результат попытки — ${res.target.result_grade}.`)).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Компетенции' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'История тестов' })).toBeVisible();
  await expect(page.getByText('Экспресс-оценка.')).toHaveCount(0);  // полный тест снял пометку
  await expect(page.locator('table.tbl tbody tr')).toHaveCount(2);
  await expect(page.locator('table.tbl tbody tr').first()).toContainText('Middle');
  // PDF-профиль: файл с авторизацией, имя по анонимному коду
  const pdf = page.waitForEvent('download');
  await page.getByRole('button', { name: 'PDF-профиль' }).click();
  const pdfFile = await pdf;
  expect(pdfFile.suggestedFilename()).toMatch(/^fsp-career-[A-Z]-\d{4}\.pdf$/);
  expect(fs.readFileSync(await pdfFile.path()).subarray(0, 5).toString()).toBe('%PDF-');
  await expect(toast(page)).toHaveText('PDF-профиль сформирован');
  await page.getByRole('button', { name: 'Пройти тест ещё раз' }).click();
  await expect(page.getByRole('heading', { name: 'История тестов' })).toBeVisible();
  await expect(page.getByRole('group', { name: 'Режим теста' })).toContainText('уже подтверждён полным тестом');
  await expect(page.locator('table.tbl tbody tr').first()).toContainText(/категория обновлена|не применён/);

  // кабинет: карточка не опубликована → предупреждение; статус и уведомления
  await page.locator('.brand').click();  // логотип в кабинете — его дом
  await expect(page.getByText('Карточка не опубликована')).toBeVisible();
  await expect(page.getByText('Приглашений пока нет.', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Не ищу' }).click();
  await expect(page.getByText('Профиль скрыт из подборок')).toBeVisible();
  await page.getByRole('button', { name: 'Открыт к предложениям' }).click();
  await expect(page.getByText('Ничего делать не нужно. Новые приглашения появятся в этом кабинете.')).toBeVisible();
  // письма о приглашениях: без SMTP стенд честно говорит, что не шлёт; Telegram-уведомлений нет
  await expect(page.getByText('На этом стенде письма не отправляются (почтовый сервер не настроен): приглашения — только в кабинете.')).toBeVisible();
  await expect(page.getByRole('switch', { name: 'Telegram' })).toHaveCount(0);
  await expect(page.getByRole('switch', { name: 'Почта' })).toHaveAttribute('aria-checked', 'true');
  await page.getByRole('switch', { name: 'Почта' }).click();
  await expect(page.getByRole('switch', { name: 'Почта' })).toHaveAttribute('aria-checked', 'false');

  // достижения: согласие на внешние профили, Codeforces и CTFtime (живые API подменены)
  await open(page, '/candidate/profile');
  await expect(page.getByRole('heading', { name: 'Достижения' })).toBeVisible();
  await expect(page.getByText('Опыт в PDF-профиле')).toBeVisible();  // места работы из резюме, загруженного до профиля
  await expect(page.getByPlaceholder('хэндл')).toBeDisabled();
  await page.getByRole('switch', { name: /внешних профилей/ }).click();
  await expect(page.getByPlaceholder('хэндл')).toBeEnabled();
  await page.getByPlaceholder('хэндл').fill('eva_e2e');
  await page.getByRole('button', { name: 'Подключить' }).first().click();
  await expect(toast(page)).toContainText('Хэндл сохранён');
  await expect(page.getByText(/Codeforces · eva_e2e, не подтверждён/)).toBeVisible();
  // код подтверждения — только в ответе link: показан один раз со сроком; «Получить новый код» выдаёт другой
  const code1 = await page.locator('code', { hasText: /\S/ }).first().textContent();
  await expect(page.getByText(/Код действует до/)).toBeVisible();
  await expect(page.getByText('Код показывается один раз — сохраните его.')).toBeVisible();
  const relink = api(page, 'POST', '/api/achievements/codeforces/link');
  await page.getByRole('button', { name: 'Получить новый код' }).click();
  const code2 = (await (await relink).json()).code;
  expect(code2).not.toBe(code1);
  await expect(page.locator('code', { hasText: code2 })).toBeVisible();
  // после ухода с экрана код уже не показывается: в GET /api/achievements его нет
  await open(page, '/candidate/settings');
  await open(page, '/candidate/profile');
  await expect(page.getByText('Код подтверждения показывается один раз, сразу после запроса.')).toBeVisible();
  // истёкший код — 400 с текстом сервера
  await page.route('**/api/achievements/codeforces/verify', r => r.fulfill({ status: 400, json: { detail: 'Код истёк — запросите новый' } }));
  await page.getByRole('button', { name: 'Проверить' }).click();
  await expect(toast(page)).toHaveText('Код истёк — запросите новый');
  await page.unroute('**/api/achievements/codeforces/verify');
  // ответ = настоящий GET /api/achievements с подменёнными полями (вместо похода в Codeforces / CTFtime)
  const fake = async (route, patch) => {
    const real = await page.request.get('/api/achievements', { headers: { authorization: route.request().headers().authorization } });
    await route.fulfill({ json: patch(await real.json()) });
  };
  await page.route('**/api/achievements/codeforces/verify', r => fake(r, a => ({ ...a,
    codeforces: { ...a.codeforces, verified: true, rating: 1820, rank: 'expert', achievements: [{ title: 'Codeforces Round 999', place: 41, verified: true, date: '2026-09-01' }] } })));
  await page.getByRole('button', { name: 'Проверить' }).click();
  await expect(toast(page)).toContainText('Владение подтверждено');
  await expect(page.getByText('рейтинг 1820 (expert)')).toBeVisible();
  await expect(page.locator('aside .chip', { hasText: 'CF 1820' })).toBeVisible();
  await page.getByRole('button', { name: 'Подключить' }).first().click();
  await expect(toast(page)).toHaveText('Укажите ID команды CTFtime');
  await page.route('**/api/achievements/ctftime/link', r => fake(r, a => ({ ...a,
    ctftime: { team: 'E2E Crew', team_id: 4242, rating: 33.5, role: 'web', achievements: [{ title: 'E2E CTF 2026', place: 7, team: 'E2E Crew', verified: false }] } })));
  await page.getByPlaceholder('ID команды').fill('4242');
  await page.getByPlaceholder('роль: web, pwn…').fill('web');
  await page.getByRole('button', { name: 'Подключить' }).first().click();
  await expect(toast(page)).toHaveText('Команда CTFtime привязана');
  await expect(page.getByText('CTFtime · E2E Crew, рейтинг 33,5 · web')).toBeVisible();
  await expect(page.getByText('Kaggle')).toHaveCount(0);  // не подключается — строки-заглушки нет
  await page.unrouteAll();

  // настройки: публикация карточки, отзыв и возврат согласий, скрытие от компаний
  await open(page, '/candidate/settings');
  await expect(page.getByRole('heading', { name: 'Согласия' })).toBeVisible();
  await expect(page.getByText(email)).toBeVisible();
  const pub = page.getByRole('switch', { name: /Публикация обезличенной карточки/ });
  await expect(pub).toHaveAttribute('aria-checked', 'false');
  await pub.click();
  await expect(toast(page)).toHaveText('Карточка опубликована: работодатели вас видят');
  await expect(pub).toHaveAttribute('aria-checked', 'true');
  await pub.click();
  await expect(toast(page)).toHaveText('Карточка скрыта от работодателей');

  const ext = page.getByRole('switch', { name: /Данные внешних профилей/ });
  await ext.click();
  const dlg = page.getByRole('alertdialog', { name: 'Подтверждение' });
  await expect(dlg).toContainText('Привязки Codeforces и CTFtime');
  await dlg.getByRole('button', { name: 'Отмена' }).click();
  await expect(dlg).toBeHidden();
  await ext.click();
  await dlg.getByRole('button', { name: 'Отозвать' }).click();
  await expect(ext).toHaveAttribute('aria-checked', 'false');
  await ext.click();
  await expect(ext).toHaveAttribute('aria-checked', 'true');

  const c152 = page.getByRole('switch', { name: /Обработка персональных данных/ });
  await c152.click();
  await expect(dlg).toContainText('Профиль будет скрыт и снят с публикации');
  await dlg.getByRole('button', { name: 'Отозвать' }).click();
  await expect(toast(page)).toHaveText('Согласие отозвано: профиль скрыт');
  await expect(page.getByText('Не дано: профиль скрыт')).toBeVisible();
  await expect(pub).toBeDisabled();
  // журнал согласий по каждой цели: дата и версия последнего события
  await expect(page.locator('[data-consent=processing]')).toContainText(/Журнал: отозвано .*версия \S+/);
  await expect(page.locator('[data-consent=publish]')).toContainText(/Журнал: (отозвано|дано)/);
  // отзыв обработки гасит и внешние данные — восстанавливаются они только отдельным согласием
  await expect(page.locator('[data-consent=external]')).toContainText(/Журнал: отозвано/);
  await expect(ext).toHaveAttribute('aria-checked', 'false');
  // после отзыва ПДн менять нельзя: плашка, заблокированные формы, восстановить можно из плашки
  const banner = page.locator('.alert.bad', { hasText: 'Согласие на обработку отозвано: восстановите его или удалите аккаунт' });
  await expect(banner).toBeVisible();
  await expect(page.getByRole('button', { name: 'Изменить список' })).toBeDisabled();
  await open(page, '/candidate');
  await expect(banner).toBeVisible();
  await expect(page.getByRole('switch', { name: 'Почта' })).toBeDisabled();
  await open(page, '/candidate/profile');
  await expect(banner).toBeVisible();
  await expect(page.getByLabel('Имя и фамилия')).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Сохранить', exact: true })).toBeDisabled();
  await open(page, '/candidate/settings');
  // без согласия на обработку ПДн откликнуться нельзя: ошибка прямо в форме отклика
  await open(page, '/candidate/vacancies');
  await page.locator('#app button.cand').first().click();
  await page.getByRole('button', { name: 'Откликнуться' }).click();
  await expect(page.locator('.alert.bad', { hasText: 'Нужно согласие на обработку персональных данных' })).toBeVisible();
  await open(page, '/candidate/settings');
  await c152.click();
  await expect(toast(page)).toHaveText('Согласие дано');
  await expect(page.getByText(/Дано .*версия текста/)).toBeVisible();

  await page.getByRole('button', { name: 'Изменить список' }).click();
  await page.getByLabel('ИНН через запятую').fill('7700000001, 7700000002');
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
  await expect(page.getByText('Сейчас скрыт от: 7700000001, 7700000002')).toBeVisible();
  await page.getByRole('button', { name: 'Изменить список' }).click();
  await page.getByRole('button', { name: 'Отмена' }).click();
  await expect(page.getByLabel('ИНН через запятую')).toHaveCount(0);

  // выгрузка своих данных: JSON-файл
  const dl = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Скачать мои данные' }).click();
  const file = await dl;
  expect(file.suggestedFilename()).toMatch(/^fsp-career-.+\.json$/);
  const data = JSON.parse(fs.readFileSync(await file.path(), 'utf8'));
  expect(JSON.stringify(data)).toContain('Ева Тестова');
  expect(JSON.stringify(data)).toContain(email);
  expect(data).toHaveProperty('account');
  expect(Array.isArray(data.consents) && data.consents.length).toBeTruthy();
  expect(data).toHaveProperty('audit');
  await expect(toast(page)).toHaveText('Файл с вашими данными сформирован');

  // удаление аккаунта через инлайн-диалог
  await page.getByRole('button', { name: 'Удалить аккаунт' }).click();
  await expect(dlg).toContainText('Удалить аккаунт навсегда?');
  await dlg.getByRole('button', { name: 'Отмена' }).click();
  await page.getByRole('button', { name: 'Удалить аккаунт' }).click();
  const del = api(page, 'DELETE', '/api/candidate/me');
  await dlg.getByRole('button', { name: 'Удалить навсегда' }).click();
  expect((await del).status()).toBe(200);
  await expect(toast(page)).toHaveText('Аккаунт удалён');
  await expect(page).toHaveURL(/:\d+\/$/);
  await expect(page.locator('#me')).toBeHidden();
  expect(await page.evaluate(() => localStorage.getItem('fsp.tok.c'))).toBeNull();
});
