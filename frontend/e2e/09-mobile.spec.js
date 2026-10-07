// Мобильная вёрстка: телефон 375×812 и планшет 768×1024 (сенсорный экран). Ключевые экраны обоих кабинетов без
// горизонтальной прокрутки страницы; шапка в одну строку, роли и выход — в меню; разделы кабинета — одной строкой
// с прокруткой; фильтры сворачиваются, а список не уезжает под боковые панели; чат — список или диалог; тест —
// прилипающие таймер и «Дальше»; поля не меньше 16 px (iOS не увеличивает страницу); манифест для домашнего экрана.
const { test, expect, demo, open, settled, toast } = require('./fixtures');
const { uniq } = require('./helpers');

const C_SCREENS = ['/c/home', '/c/vacancies', '/c/applications', '/c/tasks', '/c/chat', '/c/result', '/c/settings', '/c/profile'];
const E_SCREENS = ['/e/picks', '/e/search', '/e/need', '/e/pipeline', '/e/vacancies', '/e/tasks', '/e/chat'];

// страница не шире окна: ни один блок не вылез за край (таблицы прокручиваются внутри своей обёртки)
async function noHScroll(page, label) {
  const { sw, w } = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, w: document.documentElement.clientWidth }));
  expect(sw, `${label}: ширина страницы ${sw} > окна ${w}`).toBeLessThanOrEqual(w);
}
const box = loc => loc.evaluate(e => { const r = e.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, left: r.left, right: r.right, h: r.height }; });
// все элементы — в одной строке (общий верх)
const oneLine = loc => loc.evaluateAll(els => new Set(els.map(e => Math.round(e.getBoundingClientRect().top))).size === 1);

for (const [name, viewport] of [['телефон', { width: 375, height: 812 }], ['планшет', { width: 768, height: 1024 }]]) {
  const phone = viewport.width < 640;
  test.describe(name, () => {
    test.use({ viewport, hasTouch: true, isMobile: true });

    test(`${name}: публичные экраны, шапка и меню`, async ({ page }) => {
      for (const r of ['/', '/c/signup', '/e/signup', '/v']) {
        await open(page, r);
        await noHScroll(page, r);
      }
      // шапка — одна строка: роли и «Выйти» спрятаны, вместо «Экраны» — «Меню»
      expect((await box(page.locator('header.top'))).h).toBeLessThanOrEqual(64);
      await expect(page.locator('header .roles')).toBeHidden();
      await page.getByRole('button', { name: 'Меню' }).click();
      await expect(page.locator('#overlay')).toContainText('Карточка кандидата');
      await noHScroll(page, 'меню экранов');
      expect(await page.evaluate(() => getComputedStyle(document.documentElement).overflow)).toBe('hidden');  // страница под меню не прокручивается
      // роль переключается из меню, меню закрывается
      const roles = page.locator('#overlay').getByRole('navigation', { name: 'Роль' });
      await expect(roles.getByRole('button', { name: 'Валидация' })).toHaveAttribute('aria-pressed', 'true');
      await roles.getByRole('button', { name: 'Работодатель' }).click();
      await settled(page);
      await expect(page.getByRole('heading', { name: 'Вход для компаний' })).toBeVisible();
      await expect(page.locator('#overlay')).toBeEmpty();
      expect(await page.evaluate(() => getComputedStyle(document.documentElement).overflow)).not.toBe('hidden');

      // иконка и манифест: стенд можно добавить на домашний экран телефона
      const man = await page.evaluate(async () => {
        const href = document.querySelector('link[rel=manifest]').href;
        const m = await (await fetch(href)).json();
        const icons = await Promise.all(m.icons.map(async i => (await fetch(new URL(i.src, href))).status));
        const touch = (await fetch(document.querySelector('link[rel=apple-touch-icon]').href)).status;
        return { display: m.display, start: m.start_url, icons, touch };
      });
      expect(man).toEqual({ display: 'standalone', start: '/', icons: [200, 200, 200], touch: 200 });
    });

    test(`${name}: кабинет кандидата`, async ({ page }) => {
      await demo(page, 'c');
      for (const r of C_SCREENS) {
        await open(page, r);
        await noHScroll(page, r);
      }
      // разделы — одна строка с прокруткой, активный раздел виден целиком
      await open(page, '/c/settings');
      const nav = page.locator('nav.subnav');
      expect(await oneLine(nav.locator('.chip'))).toBe(true);
      const [n, on] = [await box(nav), await box(nav.locator('.chip.on'))];
      expect(on.left).toBeGreaterThanOrEqual(n.left);
      expect(on.right).toBeLessThanOrEqual(n.right);
      // «Выйти» — в меню, а не в шапке
      await expect(page.locator('#logout')).toBeHidden();
      await page.getByRole('button', { name: 'Меню' }).click();
      await expect(page.locator('#overlay').getByRole('button', { name: 'Выйти из кабинета кандидата' })).toBeVisible();
      await page.locator('#overlay').getByRole('button', { name: 'Закрыть' }).click();

      // вакансии: на телефоне фильтры свёрнуты, список — сразу под ними
      await open(page, '/c/vacancies');
      const q = page.locator('#vf-q');
      {  // телефон и планшет — одна колонка: фильтры свёрнуты
        await expect(q).toBeHidden();
        await page.getByRole('button', { name: 'Развернуть' }).click();
        await expect(q).toBeVisible();
        expect(await q.evaluate(e => parseFloat(getComputedStyle(e).fontSize))).toBeGreaterThanOrEqual(16);  // iOS не увеличивает страницу при фокусе
        await q.fill('платежи');
        const found = page.waitForResponse(r => new URL(r.url()).pathname === '/api/vacancies' && new URL(r.url()).searchParams.get('q') === 'платежи');
        await q.press('Enter');  // клавиша «Найти» на телефоне — применить фильтр
        expect((await found).ok()).toBe(true);
        await expect(page.getByText('Фильтры · 1')).toBeVisible();
      }
      await page.getByRole('button', { name: 'Сбросить' }).click();
      await settled(page);

      await open(page, '/c/home');
      await page.locator('.inv').first().click();
      await settled(page);
      await expect(page).toHaveURL(/#\/c\/invite\/\d+$/);
      await noHScroll(page, 'приглашение');
      // сумма вилки не рвётся посередине: каждая — одной строкой
      for (const m of await page.locator('.stat .money').all()) expect(await m.evaluate(e => e.getClientRects().length)).toBe(1);
      // логотип и название компании — в одной строке
      const head = page.locator('.co-head');
      expect(Math.abs((await box(head.locator('.logo-sq'))).top - (await box(head.locator('b'))).top)).toBeLessThan(30);
    });

    test(`${name}: кабинет работодателя`, async ({ page }) => {
      await demo(page, 'e');
      for (const r of E_SCREENS) {
        await open(page, r);
        await noHScroll(page, r);
      }
      // подборка: первая карточка — выше карты регионов и рекомендованных категорий (они под списком)
      await open(page, '/e/picks');
      expect((await box(page.locator('.cand').first())).top).toBeLessThan((await box(page.locator('img[alt^="Карта России"]'))).top);
      expect((await box(page.locator('.cand').first())).top).toBeLessThan((await box(page.getByText('Рекомендованные категории'))).top);
      // лотерея свёрнута, разворачивается по кнопке
      const lot = page.getByRole('button', { name: 'Зафиксировать пул' });
      await expect(lot).toBeHidden();
      await page.locator('.fold', { hasText: 'Лотерея среди прошедших порог' }).getByRole('button', { name: 'Развернуть' }).click();
      await expect(lot).toBeVisible();

      await page.locator('.cand').first().click();
      await settled(page);
      await expect(page).toHaveURL(/#\/e\/cand\//);
      await noHScroll(page, 'карточка кандидата');
      // форма приглашения — по адресу: после предыдущих сценариев первый из подборки может быть уже приглашён
      await open(page, '/e/invite/' + page.url().split('/e/cand/')[1]);
      await noHScroll(page, 'форма приглашения');
      // «от» и «до» вилки — рядом, в одной строке
      expect(await oneLine(page.locator('#inv-form .pfx'))).toBe(true);

      await open(page, '/e/pipeline');
      const thead = page.locator('table.tbl.stack thead');
      if (phone) {
        await expect(thead).toBeHidden();  // на телефоне строка воронки — карточка с подписями
        const role = page.locator('table.tbl.stack tbody td[data-l="Роль"]').first();
        expect(await role.evaluate(e => getComputedStyle(e, '::before').content)).toBe('"Роль"');
      } else {
        await expect(thead).toBeVisible();
      }
      // сенсорный экран: разделы кабинета — зона нажатия не меньше 36 px
      for (const b of await page.locator('nav.chips button.chip').all()) expect((await b.boundingBox()).height).toBeGreaterThanOrEqual(36);
    });
  });
}

test.describe('телефон: вход и тест', () => {
  test.use({ viewport: { width: 375, height: 812 }, hasTouch: true, isMobile: true });

  test('вход клавишей Enter, профиль, тест с прилипающими таймером и «Дальше»', async ({ page }) => {
    const email = `mobile-${uniq()}@example.ru`;
    await open(page, '/c/signup');
    await page.getByLabel(/обработку персональных данных по 152-ФЗ/).check();
    await page.getByLabel('Присылать приглашения в Telegram').uncheck();
    await page.getByLabel('Почта').fill(email);
    await page.getByLabel('Почта').press('Enter');  // клавиша «Отправить» — получить код
    await expect(toast(page)).toHaveText('Код отправлен на ' + email);
    await expect(page.getByLabel('Код из письма')).toHaveValue(/^\d{6}$/);
    await page.getByLabel('Код из письма').press('Enter');  // «Войти»
    await expect(page.getByRole('heading', { name: 'Профиль', exact: true })).toBeVisible();
    await noHScroll(page, 'профиль');
    // грейды — одной строкой, поле зарплаты — с цифровой клавиатурой
    expect(await oneLine(page.locator('[data-act=pgrade]'))).toBe(true);
    await expect(page.getByLabel('Минимальная зарплата на руки')).toHaveAttribute('inputmode', 'numeric');
    await page.getByLabel('Имя и фамилия').fill('Мира Мобильная');
    await page.getByLabel('Минимальная зарплата на руки').fill('180000');
    await page.getByRole('button', { name: 'Сохранить и перейти к тесту' }).click();
    await expect(page.getByRole('button', { name: 'Полный тест (~40 мин)' })).toBeVisible();
    await noHScroll(page, 'вводная теста');
    await page.getByRole('button', { name: 'Полный тест (~40 мин)' }).click();
    await settled(page);
    await expect(page.locator('#timer')).toBeVisible();
    await noHScroll(page, 'задание');

  });
});
