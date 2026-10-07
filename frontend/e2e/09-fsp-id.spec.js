// ФСП ID (OIDC, code + PKCE) против встроенного мок-провайдера «ФСП ID (демо)»: отмена, вход Орловым,
// отвязка и привязка в настройках с подтягиванием достижений, новый человек → профиль → согласие → достижения,
// устаревший билет и ошибки возврата; затем вход компании (SSO) и сторонние провайдеры брокера. Идёт последним: меняет привязку ФСП ID Орлова и возвращает её.
const { test, expect, open, toast, api } = require('./fixtures');
const { uniq } = require('./helpers');

const fspButton = page => page.getByRole('button', { name: /Войти через ФСП ID/ });
const provider = page => expect(page.getByRole('heading', { name: 'ФСП ID (демо)' })).toBeVisible();

test('ФСП ID: отмена, вход Орловым, отвязка и привязка в настройках', async ({ page }) => {
  await open(page, '/c/signup');
  await fspButton(page).click();
  await provider(page);
  await page.getByRole('button', { name: 'Отмена' }).click();
  await expect(toast(page)).toHaveText('Вход через ФСП ID отменён');
  await expect(page).toHaveURL(/#\/c\/signup$/);

  // Орлов: ФСП ID уже связан с аккаунтом из сида; билет обменивается на токен, из адреса он стёрт
  await fspButton(page).click();
  await provider(page);
  const ex = api(page, 'POST', '/api/auth/fsp/exchange');
  await page.getByRole('button', { name: /Дмитрий Орлов/ }).click();
  const r = await ex;
  expect(r.status()).toBe(200);
  expect(await r.json()).toMatchObject({ role: 'candidate', has_profile: true });
  await expect(page.locator('#app .crumbs b')).toHaveText('Кабинет кандидата');
  await expect(toast(page)).toHaveText('Вход через ФСП ID. Подтверждено достижений ФСП: 2');
  expect(page.url()).not.toContain('fsp=');

  // настройки: отвязать → связать снова; подтягивается новое достижение из реестра
  await open(page, '/c/settings');
  const aside = page.locator('aside');
  await expect(aside).toContainText('Привязан FSP-1042');
  await aside.getByRole('button', { name: 'Отвязать', exact: true }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Отвязать' }).click();
  await expect(toast(page)).toHaveText('ФСП ID отвязан');
  await expect(aside).toContainText('Свяжите аккаунт с ФСП ID');
  await aside.getByRole('button', { name: 'Связать с ФСП ID' }).click();
  await provider(page);
  await page.getByRole('button', { name: /Дмитрий Орлов/ }).click();
  await expect(toast(page)).toHaveText('ФСП ID привязан. Подтверждено достижений ФСП: 2');
  await expect(page.locator('#app .crumbs b')).toHaveText('Настройки и приватность');
  await expect(aside).toContainText('Привязан FSP-1042');
  await open(page, '/c/profile');
  await expect(page.getByText('Региональный этап ФСП 2024, Москва')).toBeVisible();
});

test('ФСП ID: новый человек → профиль → согласие на внешние данные → достижения', async ({ page }) => {
  await open(page, '/c/signup');
  // согласия с экрана регистрации переживают уход к провайдеру
  await page.getByLabel(/обработку персональных данных по 152-ФЗ/).check();
  await fspButton(page).click();
  await provider(page);
  await page.getByRole('button', { name: /Анна Соколова/ }).click();
  await expect(toast(page)).toHaveText('Вход через ФСП ID: заполните профиль');
  await expect(page.getByRole('heading', { name: 'Профиль' })).toBeVisible();
  await page.getByLabel('Имя и фамилия').fill('Анна Соколова');
  await page.getByLabel('Минимальная зарплата на руки').fill('180000');
  await page.getByLabel('Город').fill('Томск');
  const saved = api(page, 'POST', '/api/candidate/profile');
  await page.getByRole('button', { name: 'Сохранить и перейти к тесту' }).click();
  expect(await (await saved).json()).toMatchObject({ email: 'a.sokolova@example.ru', consent_152: true });
  await expect(toast(page)).toHaveText('Профиль сохранён');

  await open(page, '/c/settings');
  await expect(page.locator('aside')).toContainText('Привязан FSP-2077');
  await page.getByRole('switch', { name: /Данные внешних профилей/ }).click();
  await expect(page.getByRole('switch', { name: /Данные внешних профилей/ })).toHaveAttribute('aria-checked', 'true');
  await page.locator('aside').getByRole('button', { name: 'Обновить достижения' }).click();
  await provider(page);
  await page.getByRole('button', { name: /Анна Соколова/ }).click();
  await expect(toast(page)).toHaveText('ФСП ID привязан. Подтверждено достижений ФСП: 1');
  await open(page, '/c/profile');
  await expect(page.getByText('Чемпионат России ФСП 2025, информационная безопасность')).toBeVisible();
});

test('ФСП ID: устаревший билет и ошибки возврата', async ({ page }) => {
  await page.goto('/?n=1#fsp=login&t=' + uniq() + '&ach=0');
  await expect(toast(page)).toHaveText('Вход через ФСП ID устарел — начните заново');
  await expect(page).toHaveURL(/#\/c\/signup$/);
  await page.goto('/?n=2#fsp=error&e=taken');
  await expect(toast(page)).toHaveText('Этот ФСП ID уже привязан к другому аккаунту');
  await page.goto('/?n=3#fsp=error&e=constructor');
  await expect(toast(page)).toHaveText('Не удалось войти через ФСП ID');
});

test('SSO компании: Белов входит через мок Keycloak и попадает к данным компании', async ({ page }) => {
  await open(page, '/e/signup');
  await page.getByRole('button', { name: 'Войти через SSO (Keycloak)' }).click();
  await provider(page);
  // аккаунты на странице провайдера разделены на кандидатов и компании
  await expect(page.getByRole('heading', { name: 'Компании' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Кандидаты' })).toBeVisible();
  const ex = api(page, 'POST', '/api/auth/fsp/exchange');
  await page.getByRole('button', { name: /Игорь Белов/ }).click();
  const r = await ex;
  expect(r.status()).toBe(200);
  expect(await r.json()).toMatchObject({ role: 'employer', has_profile: false });
  await expect(toast(page)).toHaveText('Вход через SSO: укажите данные компании');
  await expect(page.getByRole('heading', { name: 'Компания', exact: true })).toBeVisible();
  expect(page.url()).not.toContain('fsp=');
  await page.locator('#app').getByRole('button', { name: 'Выйти' }).click();
  await expect(toast(page)).toHaveText('Вы вышли');

  // демо-работодатель из сида привязан к мок-аккаунту: сразу кабинет компании
  await page.getByRole('button', { name: 'Войти через SSO (Keycloak)' }).click();
  await provider(page);
  await page.getByRole('button', { name: /Мария Ковалёва/ }).click();
  await expect(toast(page)).toHaveText('Вход через SSO');
  await expect(page).toHaveURL(/#\/e\/picks$/);
  await expect(page.locator('#app .crumbs')).toContainText('Ладога Пэй');  // кабинет компании из сида
});

test('SSO компании: вход через провайдера брокера — kc_idp_hint виден на странице мока', async ({ page }) => {
  await open(page, '/e/signup');
  const start = api(page, 'POST', '/api/auth/fsp/start');
  await page.getByRole('button', { name: 'Войти через Яндекс ID' }).click();
  expect((await start).request().postDataJSON()).toMatchObject({ role: 'employer', idp: 'yandex' });
  await provider(page);
  await expect(page.getByText('Вход через yandex (демо, брокер Keycloak)')).toBeVisible();
  expect(page.url()).toContain('kc_idp_hint=yandex');
  await page.getByRole('button', { name: 'Отмена' }).click();
  await expect(toast(page)).toHaveText('Вход через ФСП ID отменён');
  await expect(page).toHaveURL(/#\/e\/signup$/);  // возврат — на сторону компании

  // у кандидата те же провайдеры рядом с «Войти через ФСП ID»
  await open(page, '/c/signup');
  await page.getByRole('button', { name: 'Войти через Корпоративный SSO' }).click();
  await expect(page.getByText('Вход через corp (демо, брокер Keycloak)')).toBeVisible();
});

test('SSO компании: кандидат не входит через компанию, ошибка роли понятна', async ({ page }) => {
  await open(page, '/e/signup');
  await page.getByRole('button', { name: 'Войти через SSO (Keycloak)' }).click();
  await provider(page);
  await page.getByRole('button', { name: /Дмитрий Орлов/ }).click();  // Орлов — кандидат с профилем
  await expect(toast(page)).toHaveText('Этот аккаунт уже зарегистрирован с другой ролью (кандидат или работодатель) — войдите по коду');
  await expect(page).toHaveURL(/#\/e\/signup$/);
});
