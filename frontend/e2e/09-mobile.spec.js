// Мобильная вёрстка: телефон 375×812 и планшет 768×1024 (сенсорный экран). Ключевые экраны обоих кабинетов без
// горизонтальной прокрутки страницы; широкая таблица воронки на телефоне — карточки; пустая панель чата не занимает экран.
const { test, expect, demo, open, settled } = require('./fixtures');

const C_SCREENS = ['/c/home', '/c/vacancies', '/c/applications', '/c/tasks', '/c/chat', '/c/result', '/c/settings', '/c/profile'];
const E_SCREENS = ['/e/picks', '/e/search', '/e/need', '/e/pipeline', '/e/vacancies', '/e/tasks', '/e/chat'];

// страница не шире окна: ни один блок не вылез за край (таблицы прокручиваются внутри своей обёртки)
async function noHScroll(page, label) {
  const { sw, w } = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, w: document.documentElement.clientWidth }));
  expect(sw, `${label}: ширина страницы ${sw} > окна ${w}`).toBeLessThanOrEqual(w);
}

for (const [name, viewport] of [['телефон', { width: 375, height: 812 }], ['планшет', { width: 768, height: 1024 }]]) {
  test.describe(name, () => {
    test.use({ viewport, hasTouch: true, isMobile: true });

    test(`${name}: публичные экраны и меню`, async ({ page }) => {
      for (const r of ['/', '/c/signup', '/e/signup', '/v']) {
        await open(page, r);
        await noHScroll(page, r);
      }
      await page.getByRole('button', { name: 'Экраны' }).click();
      await expect(page.locator('#overlay')).toContainText('Карточка кандидата');
      await noHScroll(page, 'меню экранов');
    });

    test(`${name}: кабинет кандидата`, async ({ page }) => {
      await demo(page, 'c');
      for (const r of C_SCREENS) {
        await open(page, r);
        await noHScroll(page, r);
      }
      await open(page, '/c/home');
      await page.locator('.inv').first().click();
      await settled(page);
      await expect(page).toHaveURL(/#\/c\/invite\/\d+$/);
      await noHScroll(page, 'приглашение');
      // сумма вилки не рвётся посередине: каждая — одной строкой
      for (const m of await page.locator('.stat .money').all()) expect(await m.evaluate(e => e.getClientRects().length)).toBe(1);
    });

    test(`${name}: кабинет работодателя`, async ({ page }) => {
      await demo(page, 'e');
      for (const r of E_SCREENS) {
        await open(page, r);
        await noHScroll(page, r);
      }
      await open(page, '/e/picks');
      await page.locator('.cand').first().click();
      await settled(page);
      await expect(page).toHaveURL(/#\/e\/cand\//);
      await noHScroll(page, 'карточка кандидата');
      // форма приглашения — по адресу: после предыдущих сценариев первый из подборки может быть уже приглашён
      await open(page, '/e/invite/' + page.url().split('/e/cand/')[1]);
      await noHScroll(page, 'форма приглашения');

      await open(page, '/e/pipeline');
      const head = page.locator('table.tbl.stack thead');
      if (viewport.width < 640) {
        await expect(head).toBeHidden();  // на телефоне строка воронки — карточка с подписями
        const role = page.locator('table.tbl.stack tbody td[data-l="Роль"]').first();
        expect(await role.evaluate(e => getComputedStyle(e, '::before').content)).toBe('"Роль"');
      } else {
        await expect(head).toBeVisible();
      }

      await open(page, '/e/chat');
      const box = await page.locator('.chat-box').boundingBox();
      expect(box.height).toBeLessThan(200);  // пустая панель «Выберите диалог» не растягивается на экран
      // сенсорный экран: разделы кабинета — зона нажатия не меньше 36 px
      for (const b of await page.locator('nav.chips button.chip').all()) expect((await b.boundingBox()).height).toBeGreaterThanOrEqual(36);
    });
  });
}
