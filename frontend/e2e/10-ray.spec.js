// Рей — пёс-талисман теста: сидит на вводной, бежит после ответа (при любом ответе — верность фронт не знает),
// ложится ждать и засыпает без действий, радуется в конце теста и на результате; бегущий Рей — индикатор загрузки экрана.
// Тёмная тема, телефон без горизонтальной прокрутки, prefers-reduced-motion — поза без анимации; иконка вкладки.
const { test, expect, open, demo, api } = require('./fixtures');
const { uniq } = require('./helpers');

const ray = (page, name) => page.getByRole('img', { name });
const IDLE = 'Рей сидит и осматривается', RUN = 'Рей бежит', WAIT = 'Рей лежит и ждёт', SLEEP = 'Рей спит', HAPPY = 'Рей радуется';

async function noHScroll(page, label) {
  const { sw, w } = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, w: document.documentElement.clientWidth }));
  expect(sw, `${label}: ширина страницы ${sw} > окна ${w}`).toBeLessThanOrEqual(w);
}

// ответ на текущее задание: вариант по кругу или строка в коде — Рей реагирует одинаково
async function answer(page, n) {
  const opts = page.locator('.opt');
  if (await opts.count()) await opts.nth(n % (await opts.count())).click();
  else {
    await page.locator('.code button[data-act=mark]').nth(n % 2).click();
    if (await page.locator('#rv-comment').count()) await page.locator('#rv-comment').fill('Нет блокировки строки.');
  }
  const sent = api(page, 'POST', '/api/quest/answer');
  await page.getByRole('button', { name: 'Дальше' }).click();
  return sent;
}

test('Рей в тесте: вводная, бег после ответа, ожидание и сон без действий, финал и результат', async ({ page }) => {
  await page.clock.install();  // часы страницы под контролем теста: минута без действий — без минуты ожидания
  await open(page, '/candidate/signup');
  await page.getByLabel('Почта').fill(`ray-${uniq()}@example.ru`);
  await page.getByLabel(/обработку персональных данных по 152-ФЗ/).check();
  await page.getByRole('button', { name: 'Получить код на почту' }).click();
  await expect(page.getByLabel('Код из письма')).toHaveValue(/^\d{6}$/);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await page.getByLabel('Имя и фамилия').fill('Рита Реева');
  await page.getByLabel('Минимальная зарплата на руки').fill('150000');
  await page.getByRole('button', { name: 'Сохранить и перейти к тесту' }).click();

  // вводная: Рей сидит; на нижней границе широкой вёрстки (1100 px) — справа от текста, внутри карточки теста
  await expect(ray(page, IDLE)).toBeVisible();
  await page.setViewportSize({ width: 1100, height: 800 });
  const [r, q] = await Promise.all([ray(page, IDLE), page.locator('.quest')].map(l => l.evaluate(e => e.getBoundingClientRect().right)));
  expect(r).toBeLessThanOrEqual(q);
  await noHScroll(page, 'вводная на 1100 px');
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.getByRole('button', { name: 'Экспресс-тест для знакомства (3–5 мин)' }).click();
  const pet = page.locator('#qpet');
  await expect(pet.getByRole('img', { name: IDLE })).toBeVisible();

  // минута без действий — лежит и ждёт, ещё две — спит; любое действие — снова сидит; прокрутка колесом — тоже действие
  await page.clock.fastForward('01:01');
  // часы страницы ушли вперёд: таймер задания на нуле, ответы ниже засчитываются как просроченные — здесь это нормально
  await expect(pet.getByRole('img', { name: WAIT })).toBeVisible();
  await page.mouse.wheel(0, 40);
  await expect(pet.getByRole('img', { name: IDLE })).toBeVisible();
  await page.clock.fastForward('01:01');
  await expect(pet.getByRole('img', { name: WAIT })).toBeVisible();
  await page.clock.fastForward('02:00');
  await expect(pet.getByRole('img', { name: SLEEP })).toBeVisible();
  await expect(pet.locator('.ray__zzz')).toHaveCount(1);
  await page.locator('.quest-top .qt-title').click();
  await expect(pet.getByRole('img', { name: IDLE })).toBeVisible();

  // после ответа бежит, пока грузится следующее задание, и снова сидит; на любой ответ — то же самое
  for (let n = 0; n < 2; n++) {
    const prev = await page.evaluate(() => S.quest.item.id);
    expect((await answer(page, n)).ok()).toBe(true);
    await expect.poll(() => page.evaluate(() => S.quest.item && S.quest.item.id)).not.toBe(prev);
    await expect(pet.getByRole('img', { name: RUN })).toBeVisible();
    await expect(pet.locator('.ray__dust')).toHaveCount(1);
    await page.clock.fastForward(1500);
    await expect(pet.getByRole('img', { name: IDLE })).toBeVisible();
  }
  // подпись Рея — только о позе, без оценки ответа
  expect(Object.values(await page.evaluate(() => RAY)).join(' ')).not.toMatch(/верн|ошиб|прав/i);

  // телефон: в задании Рей скрыт — не мешает чтению, страница без горизонтальной прокрутки
  await page.setViewportSize({ width: 375, height: 812 });
  await expect(pet.locator('.ray')).toBeHidden();
  await noHScroll(page, 'задание');
  await page.setViewportSize({ width: 1280, height: 720 });

  // до конца экспресс-теста; в финале и на результате — радуется
  const finish = page.getByRole('button', { name: 'Посмотреть категорию' });
  for (let n = 2; n < 10 && !(await finish.isVisible()); n++) {
    const prev = await page.evaluate(() => S.quest.item && S.quest.item.id);
    expect((await answer(page, n)).ok()).toBe(true);
    await expect.poll(() => page.evaluate(() => S.quest.done || (S.quest.item && S.quest.item.id))).not.toBe(prev);
  }
  await expect(finish).toBeVisible();
  await expect(ray(page, HAPPY)).toBeVisible();
  await expect(page.locator('.ray__hearts')).toHaveCount(1);
  await page.clock.fastForward(1500);  // таймер бега после последнего ответа: финал не трогает
  await expect(ray(page, HAPPY)).toBeVisible();
  const fin = api(page, 'POST', '/api/quest/finish');
  await finish.click();
  expect((await fin).ok()).toBe(true);
  await expect(page.getByText('Ваша категория')).toBeVisible();
  await expect(ray(page, HAPPY)).toBeVisible();
  await expect(page.locator('#qpet')).toHaveCount(0);
});

test('главная: шаг «Тест-квест» — про день с Реем, Рей у заголовка декоративный (текст уже о нём)', async ({ page }) => {
  await open(page, '/');
  await expect(page.getByText('Один день с вашим джек-расселом Реем')).toBeVisible();
  await expect(page.locator('.steps .ray[aria-hidden="true"]')).toBeVisible();
});

test('загрузка экрана: бегущий Рей с «Загрузка…», экран помечен aria-busy; иконка вкладки — Рей', async ({ page }) => {
  await demo(page, 'c');
  const icon = await page.locator('link[rel=icon]').getAttribute('href');
  expect(icon).toBe('/assets/ray.svg');
  const svg = await page.request.get(icon);
  expect(svg.ok()).toBe(true);
  expect(svg.headers()['content-type']).toContain('image/svg+xml');

  let release;
  const held = new Promise(r => { release = r; });
  await page.route('**/api/vacancies?*', async r => { await held; await r.continue(); }, { times: 1 });
  await page.getByRole('link', { name: 'Вакансии' }).first().click();
  const status = page.getByRole('status');
  await expect(status).toContainText('Загрузка…');
  await expect(status.getByRole('img', { name: RUN })).toBeVisible();
  await expect(page.locator('#app')).toHaveAttribute('aria-busy', 'true');
  release();
  await expect(page.locator('#app')).not.toHaveAttribute('aria-busy', 'true');
  await expect(page.locator('#loader')).toBeEmpty();  // пустой лоадер скрыт и для скринридера
});

test.describe('тёмная тема, телефон, без анимации', () => {
  test.use({ colorScheme: 'dark', reducedMotion: 'reduce', viewport: { width: 375, height: 812 } });
  test('Рей на вводной и результате: поза без анимации, шерсть — тёмный вариант, без горизонтальной прокрутки', async ({ page }) => {
    await demo(page, 'c');
    await open(page, '/candidate/test');
    const idle = ray(page, IDLE);
    await expect(idle).toBeVisible();
    const st = await idle.evaluate(r => {
      const head = getComputedStyle(r.querySelector('.ray__head')), body = getComputedStyle(r.querySelector('.ray__body'));
      return { anim: head.animationName, pose: body.transform, fur: body.backgroundColor };
    });
    expect(st.anim).toBe('none');           // prefers-reduced-motion: без анимации
    expect(st.pose).not.toBe('none');       // но сидит: поза осталась
    expect(st.fur).toBe('rgb(242, 238, 231)');  // --ray-fur тёмной темы
    await noHScroll(page, 'вводная теста');
    await open(page, '/candidate/test/result');
    await expect(ray(page, HAPPY)).toBeVisible();
    await expect(page.locator('.ray__hearts span').first()).toHaveCSS('opacity', '1');  // без анимации сердечко видно сразу
    await noHScroll(page, 'результат теста');
  });
});
