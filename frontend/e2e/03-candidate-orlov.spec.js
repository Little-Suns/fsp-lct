// Демо-кандидат Дмитрий Орлов (A-1042): кабинет и приглашения, профиль и результат, вакансии и отклики, витрина задач, выход.
// Приглашение «Ладога Пэй» здесь только открываем: принимает его сценарий работодателя (04), отклоняем — «Кипрей».
const { test, expect, open, demo, toast, api } = require('./fixtures');

test('приглашения: открыть → просмотрено, отказ с причиной, тест по приглашению', async ({ page }) => {
  await demo(page, 'c');
  await expect(page.getByText('Дмитрий Орлов · виден как A-1042')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Приглашения' })).toBeVisible();
  const lad = page.locator('button.inv', { hasText: 'Ладога Пэй' });
  const kip = page.locator('button.inv', { hasText: 'Кипрей Логистик' });
  await expect(lad).toContainText('новое');
  await expect(lad).toContainText('есть задача');
  await expect(page.getByText('Ничего делать не нужно. Новые приглашения появятся в этом кабинете.')).toBeVisible();
  await expect(page.getByText(/Telegram/)).toHaveCount(0);  // макета Telegram-уведомления больше нет: бот не сделан

  // «Ладога Пэй»: контакт рекрутера виден до принятия, открытие помечает «просмотрено»
  const seen = api(page, 'GET', '/api/candidate/invites/' + (await lad.getAttribute('data-go')).split('/').pop());
  await lad.click();
  expect((await (await seen).json()).status).toBe('seen');
  await expect(page.getByRole('heading', { name: /Backend-разработчик \(Python\), команда платежей/ })).toBeVisible();
  await expect(page.getByText('240 000 ₽ — 300 000 ₽')).toBeVisible();
  await expect(page.locator('aside')).toContainText('Мария Ковалёва');
  await expect(page.locator('aside')).toContainText('Только анонимную карточку A-1042');
  await expect(page.locator('.chip.ok', { hasText: 'почта на домене подтверждена' })).toBeVisible();
  // задания по приглашению: решение уходит с invitation_id
  const invId = page.url().split('/').pop();
  const tasks = page.locator('.panel', { has: page.getByRole('heading', { name: 'Задания по приглашению' }) });
  await expect(tasks).toBeVisible();
  const first = tasks.locator('button[data-go^="/c/task/"]').first();
  const taskTitle = await first.textContent();
  await first.click();
  await expect(page.getByRole('heading', { name: taskTitle })).toBeVisible();
  await expect(page.getByText('Задание из приглашения.')).toBeVisible();
  await page.locator('#tk-answer').fill('Разбор: дубли из-за ретрая без ключа идемпотентности; ключ + уникальный индекс.');
  const sub = api(page, 'POST', /^\/api\/tasks\/\d+\/submit$/);
  await page.getByRole('button', { name: 'Отправить решение' }).click();
  expect((await sub).request().postDataJSON()).toMatchObject({ invitation_id: +invId });
  await expect(page.getByRole('heading', { name: 'Ваше решение' })).toBeVisible();
  await page.getByRole('button', { name: 'К приглашению' }).click();
  await expect(tasks.getByText('ждёт оценки').first()).toBeVisible();
  await page.getByRole('button', { name: 'Пройти тест по приглашению' }).click();
  await expect(page.getByText('Тест по приглашению: выбор заданий смещён')).toBeVisible();
  // срок повышения — из профиля (кулдаун 90 дн. от теста); после этой даты строки нет — проверка не завязана на сегодняшний день
  const until = await page.evaluate(() => ME.next_upgrade_at && new Date(ME.next_upgrade_at) > new Date() ? DATE(ME.next_upgrade_at) : null);
  if (until) await expect(page.getByText('Смена возможна с ' + until)).toBeVisible();
  await page.locator('.brand').click();
  await expect(lad).toContainText('просмотрено');

  // «Кипрей»: отказ — причина обязательна, отмена, затем отказ с комментарием
  await kip.click();
  await page.getByRole('button', { name: 'Нет: указать причину' }).click();
  await expect(page.getByRole('heading', { name: 'Почему нет?' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Отклонить' })).toBeDisabled();
  await page.getByRole('button', { name: 'Отмена' }).click();
  await expect(page.getByRole('heading', { name: 'Почему нет?' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Нет: указать причину' }).click();
  await page.getByRole('button', { name: 'Зарплата' }).click();
  await expect(page.getByRole('button', { name: 'Зарплата' })).toHaveClass(/on/);
  await page.getByPlaceholder('Комментарий, по желанию').fill('Ищу от 260 тыс.');
  const dec = api(page, 'POST', /* id из маршрута */ '/api/candidate/invites/' + page.url().split('/').pop() + '/decline');
  await page.getByRole('button', { name: 'Отклонить' }).click();
  expect((await dec).request().postDataJSON()).toEqual({ reason: 'salary', comment: 'Ищу от 260 тыс.' });
  await expect(toast(page)).toHaveText('Отказ отправлен. Компания видит только причину');
  await expect(page.getByText('Вы отклонили приглашение. Причина «Зарплата» передана компании')).toBeVisible();
  await page.getByRole('link', { name: 'Кабинет', exact: true }).first().click();
  await expect(kip).toContainText('отклонено');

  await open(page, '/candidate/invites/999999');
  await expect(page.getByText('Приглашение не найдено.')).toBeVisible();
});

test('отзыв о компании по давно принятому приглашению: по желанию, один раз', async ({ page }) => {
  await demo(page, 'c');
  const old = page.locator('button.inv', { hasText: 'Python-разработчик, внутренние сервисы' });
  await expect(old).toContainText('принято');
  await old.click();
  await expect(page.getByRole('heading', { name: 'Как прошло общение с компанией?' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Отправить отзыв' })).toBeDisabled();
  await page.getByRole('button', { name: 'Не вышли на связь' }).click();
  await expect(page.getByRole('button', { name: 'Не вышли на связь' })).toHaveClass(/on/);
  const sent = api(page, 'POST', '/api/candidate/invites/' + page.url().split('/').pop() + '/company-feedback');
  await page.getByRole('button', { name: 'Отправить отзыв' }).click();
  expect((await sent).request().postDataJSON()).toEqual({ value: 'no_contact' });
  await expect(toast(page)).toHaveText('Спасибо! Отзыв учтён');
  await expect(page.getByText('Спасибо, отзыв о компании учтён.')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Как прошло общение с компанией?' })).toHaveCount(0);
});

test('вход по почте в существующий аккаунт ведёт в кабинет, а не на регистрацию', async ({ page }) => {
  await open(page, '/candidate/login');
  await page.getByLabel('Почта').fill('d.orlov@example.ru');
  await page.getByRole('button', { name: 'Получить код на почту' }).click();
  await expect(page.getByLabel('Код из письма')).toHaveValue(/^\d{6}$/);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(toast(page)).toHaveText('Вход выполнен');
  await expect(page.getByText('Дмитрий Орлов · виден как A-1042')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Профиль' })).toHaveCount(0);
  await expect(page).toHaveURL(/\/candidate$/);
});

test('сбой /api/candidate/me: «Не удалось загрузить профиль · Повторить», а не «Профиль ещё не создан»', async ({ page }) => {
  // вход по почте, а /me отвечает 500: кабинет с ошибкой и повтором, не регистрация и не noProfile
  await page.route('**/api/candidate/me', r => r.fulfill({ status: 500, json: { detail: 'Внутренняя ошибка сервера' } }));
  await open(page, '/candidate/login');
  await page.getByLabel('Почта').fill('d.orlov@example.ru');
  await page.getByRole('button', { name: 'Получить код на почту' }).click();
  await expect(page.getByLabel('Код из письма')).toHaveValue(/^\d{6}$/);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page).toHaveURL(/\/candidate$/);
  await expect(page.getByRole('heading', { name: 'Не удалось загрузить профиль' })).toBeVisible();
  await expect(page.getByText('Профиль ещё не создан')).toHaveCount(0);
  await expect(toast(page)).toHaveText('Внутренняя ошибка сервера');
  await page.unroute('**/api/candidate/me');
  const me = api(page, 'GET', '/api/candidate/me');
  await page.getByRole('button', { name: 'Повторить', exact: true }).click();
  expect((await me).ok()).toBe(true);
  await expect(page.getByText('Дмитрий Орлов · виден как A-1042')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Не удалось загрузить профиль' })).toHaveCount(0);

  // обрыв сети на другом экране кандидата — та же ошибка с повтором вместо прежних данных
  await page.route('**/api/candidate/me', r => r.abort('connectionrefused'));
  await open(page, '/candidate/settings');
  await expect(toast(page)).toHaveText('Сервер недоступен');
  await expect(page.getByRole('heading', { name: 'Не удалось загрузить профиль' })).toBeVisible();
  await expect(page.getByRole('switch', { name: /Обработка персональных данных/ })).toHaveCount(0);
  await page.unroute('**/api/candidate/me');
  await page.getByRole('button', { name: 'Повторить', exact: true }).click();
  await expect(page.getByRole('switch', { name: /Обработка персональных данных/ })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Не удалось загрузить профиль' })).toHaveCount(0);

  // действие сохранилось, а перечитать /me не вышло — экран сразу сменяется ошибкой, а не остаётся с устаревшим переключателем
  const pub = page.getByRole('switch', { name: /Публикация обезличенной карточки/ });
  const was = await pub.getAttribute('aria-checked');
  await page.route('**/api/candidate/me', r => r.fulfill({ status: 503, json: { detail: 'Сервис временно недоступен' } }));
  const patched = api(page, 'PATCH', '/api/candidate/consents');
  await pub.click();
  expect((await patched).ok()).toBe(true);
  await expect(toast(page)).toHaveText('Сервис временно недоступен');
  await expect(page.getByRole('heading', { name: 'Не удалось загрузить профиль' })).toBeVisible();
  await page.unroute('**/api/candidate/me');
  await page.getByRole('button', { name: 'Повторить', exact: true }).click();
  await expect(pub).toHaveAttribute('aria-checked', was === 'true' ? 'false' : 'true');  // сервер изменение принял
  await pub.click();  // вернуть как было: от публикации Орлова зависят другие сценарии
  await expect(pub).toHaveAttribute('aria-checked', was);

  // холодный старт при упавшем /api/meta: до /me не дошли — та же ошибка, а не «Профиль ещё не создан»
  await page.route('**/api/meta', r => r.fulfill({ status: 500, json: { detail: 'Внутренняя ошибка сервера' } }));
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Не удалось загрузить профиль' })).toBeVisible();
  await expect(page.getByText('Профиль ещё не создан')).toHaveCount(0);
  await page.unroute('**/api/meta');
  await page.getByRole('button', { name: 'Повторить', exact: true }).click();
  await expect(pub).toBeVisible();
});

test('профиль и результат теста демо-кандидата', async ({ page }) => {
  await demo(page, 'c');
  await open(page, '/candidate/profile');
  await expect(page.getByText('orlov_cv.pdf')).toBeVisible();
  await expect(page.getByText('Навыки из резюме:')).toBeVisible();
  await expect(page.getByText('Владение подтверждено кодом в профиле Codeforces')).toBeVisible();
  await expect(page.getByText('FSP-7Q2K')).toHaveCount(0);  // код подтверждения в ответах API больше не отдаётся
  await expect(page.getByText(/подтверждено протоколом/).first()).toBeVisible();
  const card = page.locator('aside');
  await expect(card).toContainText('Кандидат A-1042');
  await expect(card).toContainText('Перцентиль 78');
  await expect(card.getByText('не подтверждено')).toBeVisible();
  await expect(card.locator('.chip', { hasText: 'ФСП' })).toBeVisible();
  // данные ФСП из протокола: результат, дисциплина и разряд — факты; разряд — и чипом в превью карточки
  await expect(page.getByText('Спортивный разряд: 1 разряд')).toBeVisible();
  await expect(page.getByText(/финалист · продуктовое программирование · 1 разряд/)).toBeVisible();
  await expect(card.locator('.chip', { hasText: '1 разряд' })).toBeVisible();
  // роли и софт-скиллы из сида: отмечены в форме и видны в превью карточки
  await expect(page.locator('button.chip[data-act=ptoggle]', { hasText: 'Ментор' })).toHaveClass(/on/);
  await expect(page.locator('button.chip[data-act=ptoggle]', { hasText: 'Работа в команде' })).toHaveClass(/on/);
  await expect(card.locator('.chip', { hasText: 'Капитан команды' })).toBeVisible();
  // смена трека сбрасывает категорию: предупреждение до сохранения, возврат трека его убирает
  const reset = page.getByText(/Смена специализации или трека сбросит категорию/);
  await expect(reset).toHaveCount(0);
  const track = await page.locator('#p-track').inputValue();
  const other = await page.locator('#p-track option').evaluateAll((os, cur) => os.map(o => o.value).find(v => v !== cur), track);
  await page.locator('#p-track').selectOption(other);
  await expect(reset).toBeVisible();
  await page.locator('#p-track').selectOption(track);
  await expect(reset).toHaveCount(0);
  // «Опыт» PDF-профиля: ровно распознанное из резюме, с пометкой; исключение сохраняется сразу, без сохранения профиля
  const exp = page.locator('.field', { hasText: 'Опыт в PDF-профиле' });
  await expect(exp).toContainText('2023 — н. в. · Финтех «Волна Пэй», бэкенд-разработчик платёжного шлюза');
  await expect(exp).toContainText('2021 — 2023 · Интернет-магазин «Полка», Python-разработчик');
  await expect(exp).toContainText('Распознано из резюме автоматически — проверьте');
  const sw = exp.getByRole('switch', { name: 'Включать места работы в PDF-профиль' });
  await expect(sw).toHaveAttribute('aria-checked', 'true');
  const off = api(page, 'PATCH', '/api/candidate/pdf');
  await sw.click();
  expect(await (await off).json()).toEqual({ pdf_experience: false });
  await expect(toast(page)).toHaveText('Места работы исключены из PDF-профиля');
  await expect(sw).toHaveAttribute('aria-checked', 'false');
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
  await expect(toast(page)).toHaveText('Профиль сохранён');
  await expect(page).toHaveURL(/\/candidate\/profile$/);  // раздел кабинета: остаёмся на месте
  await expect(page.locator('nav.subnav .chip.on')).toHaveText('Профиль');

  await open(page, '/candidate/test/result');
  await expect(page.getByText('Ваша категория')).toBeVisible();
  await expect(page.locator('.cat').first()).toHaveText('BackendPythonMiddle');
  await expect(page.getByText('Перцентиль в категории').or(page.getByText('Перцентиль в специализации'))).toBeVisible();
  await expect(page.getByText(/До Senior не хватает уверенности/)).toBeVisible();
  await expect(page.getByText('Codeforces · 1912')).toBeVisible();
  await page.getByRole('button', { name: 'Готово, жду приглашений' }).click();
  await expect(page).toHaveURL(/\/candidate$/);
  await expect(page.getByText('Места работы из резюме исключены — включить можно в профиле.')).toBeVisible();

  // PDF-профиль из кабинета: файл; ошибка сервера и обрыв сети — понятный тост
  const dl = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Скачать PDF' }).click();
  expect((await dl).suggestedFilename()).toBe('fsp-career-A-1042.pdf');
  await expect(toast(page)).toHaveText('PDF-профиль сформирован');
  await page.route('**/api/candidate/profile.pdf', r => r.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Сервис PDF недоступен' }) }));
  await page.getByRole('button', { name: 'Скачать PDF' }).click();
  await expect(toast(page)).toHaveText('Сервис PDF недоступен');
  await page.unroute('**/api/candidate/profile.pdf');
  await page.route('**/api/candidate/profile.pdf', r => r.fulfill({ status: 502, contentType: 'text/html', body: '<h1>Bad gateway</h1>' }));
  await page.getByRole('button', { name: 'Скачать PDF' }).click();
  await expect(toast(page)).toHaveText('Ошибка 502');
  await page.unroute('**/api/candidate/profile.pdf');
  await page.route('**/api/candidate/profile.pdf', r => r.abort());
  await page.getByRole('button', { name: 'Скачать PDF' }).click();
  await expect(toast(page)).toHaveText('Сервер недоступен');
  await page.unroute('**/api/candidate/profile.pdf');
  // протухшая сессия — на вход, как в остальных запросах
  await page.route('**/api/candidate/profile.pdf', r => r.fulfill({ status: 401, contentType: 'application/json', body: '{"detail":"Нужен вход"}' }));
  await page.getByRole('button', { name: 'Скачать PDF' }).click();
  await expect(toast(page)).toHaveText('Сессия истекла: войдите снова');
  await expect(page).toHaveURL(/\/candidate\/login\?next=%2Fcandidate$/);
  await page.unroute('**/api/candidate/profile.pdf');
  // вернуть места работы в PDF: состояние Орлова для следующих сценариев — как в сиде
  await demo(page, 'c');
  await open(page, '/candidate/profile');
  await page.getByRole('switch', { name: 'Включать места работы в PDF-профиль' }).click();
  await expect(toast(page)).toHaveText('Места работы будут в PDF-профиле');
  await open(page, '/candidate');
  await expect(page.getByText('Места работы распознаны из резюме автоматически — проверьте их в профиле.')).toBeVisible();
});

test('вакансии: фильтры, отклик с заметкой, отзыв отклика', async ({ page }) => {
  await demo(page, 'c');
  await page.locator('nav.chips').getByRole('link', { name: 'Вакансии' }).click();
  await expect(page.getByText(/\d+ из \d+ · по соответствию вашему профилю/)).toBeVisible();
  await expect(page.getByText('Отклики за 7 дней')).toBeVisible();

  await page.getByLabel('Поиск').fill('zzzz-нет-такого');
  let q = api(page, 'GET', '/api/vacancies');
  await page.getByRole('button', { name: 'Показать' }).click();
  expect((await q).url()).toContain('q=zzzz');
  await expect(page.getByText('Под фильтры ничего не нашлось.')).toBeVisible();
  await page.getByRole('button', { name: 'Сбросить' }).click();
  await expect(page.getByLabel('Поиск')).toHaveValue('');

  await page.getByLabel('Специализация').selectOption('Backend');
  await page.getByLabel('Грейд').selectOption('Middle');
  await page.getByLabel('Формат').selectOption('Гибрид');
  await page.getByLabel('Город').fill('Москва');
  q = api(page, 'GET', '/api/vacancies');
  await page.getByRole('button', { name: 'Показать' }).click();
  const list = await (await q).json();
  expect(list.items.length).toBeGreaterThan(0);
  expect(list.items.every(v => v.spec === 'Backend' && v.grade === 'Middle')).toBe(true);
  const target = list.items.find(v => !v.applied && v.status === 'open');
  await page.locator(`button.cand[data-go="/c/vacancy/${target.id}"]`).click();

  await expect(page.getByRole('heading', { name: target.title })).toBeVisible();
  await expect(page.getByText('Вилка на руки')).toBeVisible();
  await expect(page.getByText('Соответствие вашему профилю')).toBeVisible();
  await expect(page.getByText('Ответы на отклики')).toBeVisible();
  await expect(page.getByText('ФИО, почта и Telegram откроются, только когда компания примет отклик.')).toBeVisible();
  await page.getByLabel('Короткая заметка, по желанию').fill('Интересен высоконагруженный бэкенд');
  await expect(page.getByText(`${300 - 'Интересен высоконагруженный бэкенд'.length} символов`)).toBeVisible();
  const ap = api(page, 'POST', `/api/vacancies/${target.id}/apply`);
  await page.getByRole('button', { name: 'Откликнуться' }).click();
  expect((await ap).status()).toBe(200);
  await expect(toast(page)).toHaveText('Отклик отправлен: контакты откроются, когда компания его примет');
  await expect(page.getByText('Вы откликнулись:')).toBeVisible();

  await page.getByRole('button', { name: 'Мои отклики' }).last().click();
  await expect(page.getByRole('heading', { name: 'Мои отклики' })).toBeVisible();
  const row = page.locator('.panel', { has: page.getByRole('button', { name: target.title }) });
  await expect(row).toContainText('Ваша заметка: Интересен высоконагруженный бэкенд');
  await expect(row).toContainText('Компания видит анонимную карточку. Контакты откроются, когда она примет отклик.');
  await row.getByRole('button', { name: 'Отозвать отклик' }).click();
  await expect(toast(page)).toHaveText('Отклик отозван');
  await expect(row).toContainText('отозван');

  await open(page, '/candidate/vacancies/999999');
  await expect(page.getByText('Вакансия не найдена.')).toBeVisible();
});

test('витрина задач: свои решения с оценкой, отправка нового решения', async ({ page }) => {
  await demo(page, 'c');
  await open(page, '/candidate/tasks');
  await expect(page.getByRole('heading', { name: 'Витрина задач' })).toBeVisible();
  const done = page.locator('button.cand', { hasText: 'Идемпотентность платёжного API' });
  await expect(done).toContainText('решение отправлено');
  await expect(done).toContainText('сильное решение');
  const mine = page.locator('aside');
  await expect(mine).toContainText('Мои решения');
  await expect(mine).toContainText('«Чёткий план: уникальный индекс');
  await done.click();
  await expect(page.getByRole('heading', { name: 'Ваше решение' })).toBeVisible();
  await expect(page.getByText(/Комментарий компании: Чёткий план/)).toBeVisible();
  await expect(page.getByText(/оценено/)).toBeVisible();

  await page.locator('nav.chips').getByRole('link', { name: 'Задачи' }).click();
  await page.locator('button.cand', { hasText: 'Кэш маршрутов при пиковой нагрузке' }).click();
  await expect(page.getByRole('heading', { name: 'Решение', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Отправить решение' }).click();
  await expect(toast(page)).toHaveText('Напишите решение');
  await page.getByPlaceholder('Код или решение').fill('single-flight: словарь future по ключу, первый считает, остальные ждут; TTL 60 с.');
  const sub = api(page, 'POST', page.url().replace(/^.*\/candidate\/tasks\//, '/api/tasks/') + '/submit');
  await page.getByRole('button', { name: 'Отправить решение' }).click();
  expect((await sub).status()).toBe(200);
  await expect(toast(page)).toHaveText('Решение отправлено. Оценка появится в «Моих решениях»');
  await expect(page.getByRole('heading', { name: 'Ваше решение' })).toBeVisible();
  await expect(page.getByText('ждёт оценки')).toBeVisible();

  // задание с эталоном, один вариант: кнопки выбора, проверяет система, эталон не приходит
  await page.locator('nav.chips').getByRole('link', { name: 'Задачи' }).click();
  const iso = page.locator('button.cand', { hasText: 'Уровень изоляции для двух счетов' });
  await expect(iso).toContainText('проверяет система');
  const got = api(page, 'GET', /^\/api\/tasks\/\d+$/);
  await iso.click();
  const tj = await (await got).json();
  expect(tj).not.toHaveProperty('reference');
  expect(tj).toMatchObject({ answer_type: 'choice', options: ['Read Committed', 'Repeatable Read', 'Serializable'] });
  await expect(page.getByRole('heading', { name: 'Ответ', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Отправить решение' }).click();
  await expect(toast(page)).toHaveText('Выберите вариант ответа');
  await page.getByRole('button', { name: 'Read Committed' }).click();
  await page.getByRole('button', { name: 'Serializable' }).click();  // один вариант: выбор заменяется
  await expect(page.getByRole('button', { name: 'Read Committed' })).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByRole('button', { name: 'Serializable' })).toHaveAttribute('aria-pressed', 'true');
  const isoSub = api(page, 'POST', `/api/tasks/${tj.id}/submit`);
  await page.getByRole('button', { name: 'Отправить решение' }).click();
  expect((await isoSub).request().postDataJSON()).toEqual({ choices: [2], invitation_id: null });
  await expect(toast(page)).toHaveText('Решение отправлено. Ответ совпал с эталоном');
  await expect(page.locator('.chip', { hasText: 'верно · автопроверка' })).toBeVisible();
  await expect(page.getByText('Ответ совпал с эталоном', { exact: true })).toBeVisible();

  // число: неверный ответ — «не совпало», без подсказки эталона
  await page.locator('nav.chips').getByRole('link', { name: 'Задачи' }).click();
  await page.locator('button.cand', { hasText: 'Сколько соединений занято' }).click();
  await page.getByPlaceholder('Число, например 42 или 3,14').fill('16');
  await page.getByRole('button', { name: 'Отправить решение' }).click();
  await expect(toast(page)).toHaveText('Решение отправлено. Ответ не совпал с эталоном');
  await expect(page.locator('.chip', { hasText: 'неверно · автопроверка' })).toBeVisible();
  await page.locator('nav.chips').getByRole('link', { name: 'Задачи' }).click();
  await expect(page.locator('aside')).toContainText('неверно · автопроверка');

  await open(page, '/candidate/tasks/999999');
  await expect(page.getByText('Задача не найдена.')).toBeVisible();
});

test('новая редакция согласия: баннер, блокировка правок, подтверждение', async ({ page }) => {
  await demo(page, 'c');
  // GET /me помечает, что текст согласия обновился (needs_reconsent) — подменяем только этот флаг
  await page.route('**/api/candidate/me', async r => {
    const real = await (await page.request.get(r.request().url(), { headers: r.request().headers() })).json();
    await r.fulfill({ json: { ...real, needs_reconsent: true } });
  });
  await open(page, '/candidate/profile');
  const banner = page.locator('.alert.warn', { hasText: 'Текст согласия обновился — подтвердите согласия.' });
  await expect(banner).toBeVisible();
  await expect(page.getByRole('button', { name: 'Сохранить', exact: true })).toBeDisabled();
  await open(page, '/candidate');
  await expect(banner).toBeVisible();
  await expect(page.getByRole('switch', { name: 'Почта' })).toBeDisabled();
  await page.unroute('**/api/candidate/me');
  const patch = api(page, 'PATCH', '/api/candidate/consents');
  await banner.getByRole('button', { name: 'Подтвердить согласия' }).click();
  expect((await patch).request().postDataJSON()).toEqual({ consent_152: true, consent_publish: true });
  await expect(toast(page)).toHaveText('Согласия подтверждены');
  await expect(banner).toHaveCount(0);
  await expect(page.getByRole('switch', { name: 'Почта' })).toBeEnabled();
});

test('выход: из шапки и из настроек', async ({ page }) => {
  await demo(page, 'c');
  await expect(page.locator('#logout')).toBeVisible();
  await page.locator('#logout').click();
  await expect(toast(page)).toHaveText('Вы вышли');
  await expect(page).toHaveURL(/\/candidate\/login$/);
  await expect(page.locator('#logout')).toBeHidden();

  await demo(page, 'c');
  await open(page, '/candidate/settings');
  await expect(page.getByText('d.orlov@example.ru')).toBeVisible();
  await page.locator('aside').getByRole('button', { name: 'Выйти' }).click();
  await expect(page).toHaveURL(/\/candidate\/login$/);
  // экран входа с живым токеном показывает «Вы уже вошли»
  await demo(page, 'c');
  await open(page, '/candidate/login');
  await expect(page.getByText('Вы уже вошли.')).toBeVisible();
  await page.getByRole('link', { name: 'В кабинет' }).click();
  await expect(page).toHaveURL(/\/candidate$/);
});
