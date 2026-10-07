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
      await expect(roles.getByRole('button', { name: 'Валидация' })).toHaveAttribute('aria-current', 'true');
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

      // вакансии: на телефоне и планшете (одна колонка) фильтры свёрнуты, список — сразу под ними
      await open(page, '/c/vacancies');
      const q = page.locator('#vf-q');
      const vacancies = qv => page.waitForResponse(r => new URL(r.url()).pathname === '/api/vacancies' && (new URL(r.url()).searchParams.get('q') || '') === qv);
      await expect(q).toBeHidden();
      const fold = page.getByRole('button', { name: 'Развернуть фильтры' });
      await fold.click();
      await expect(q).toBeVisible();
      await expect(page.getByRole('button', { name: 'Свернуть фильтры' })).toBeFocused();  // разворачивается на месте, фокус не теряется
      await expect(page.getByRole('button', { name: 'Свернуть фильтры' })).toHaveAttribute('aria-expanded', 'true');
      expect(await q.evaluate(e => parseFloat(getComputedStyle(e).fontSize))).toBeGreaterThanOrEqual(16);  // iOS не увеличивает страницу при фокусе
      await q.fill('платежи');
      const found = vacancies('платежи');
      await q.press('Enter');  // клавиша «Найти» на телефоне — применить фильтр
      expect((await found).ok()).toBe(true);
      await expect(page.getByText('Фильтры · 1')).toBeVisible();
      const reset = vacancies('');
      await page.getByRole('button', { name: 'Сбросить' }).click();
      expect((await reset).ok()).toBe(true);
      await expect(page.getByText('Фильтры · 1')).toHaveCount(0);

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
      await page.getByRole('button', { name: 'Развернуть лотерею' }).click();
      await expect(lot).toBeVisible();

      // поиск по банку: фильтры свёрнуты, Enter в поле — «Найти»
      await open(page, '/e/search');
      await expect(page.locator('#sf-q')).toBeHidden();
      await page.getByRole('button', { name: 'Развернуть фильтры' }).click();
      await page.locator('#sf-skills').fill('Kafka');
      const searched = page.waitForResponse(r => new URL(r.url()).pathname === '/api/employer/search' && new URL(r.url()).searchParams.get('skills') === 'Kafka');
      await page.locator('#sf-skills').press('Enter');
      expect((await searched).ok()).toBe(true);
      await expect(page.getByText('Фильтры · 1')).toBeVisible();
      // потребность: навык добавляется клавишей Enter
      await open(page, '/e/need');
      await page.getByRole('button', { name: 'Разобрать' }).click();
      await page.locator('button.chip.dim', { hasText: '+ навык' }).first().click();
      await page.locator('#need-skill').fill('Redis');
      await page.locator('#need-skill').press('Enter');
      await expect(page.locator('button.chip.on', { hasText: 'Redis' })).toBeVisible();
      await open(page, '/e/picks');

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

    test(`${name}: чат — список или диалог`, async ({ page }) => {
      await demo(page, 'e');
      await open(page, '/e/chat');
      // без открытого диалога — только список, пустой панели «Выберите диалог» нет
      await expect(page.locator('.chat-box')).toBeHidden();
      await expect(page.locator('#chat-list')).toBeVisible();
      await page.locator('.chat-peer', { hasText: 'Анна Смирнова' }).click();
      await settled(page);
      // открыт диалог: списка и строки разделов нет, поле ввода — в пределах экрана
      await expect(page.locator('#chat-list')).toBeHidden();
      await expect(page.locator('nav.subnav')).toBeHidden();
      await expect(page.locator('#chat-messages')).toContainText('Пришлю приглашение в календарь');
      expect((await box(page.locator('#chat-input'))).bottom).toBeLessThanOrEqual(viewport.height);
      await noHScroll(page, 'диалог');
      if (phone) {
        // сенсорная клавиатура: Enter — перенос строки, отправка — кнопкой
        const input = page.locator('#chat-input');
        await expect(page.getByText('Отправить — кнопкой, Enter — перенос строки')).toBeVisible();
        await input.fill('Анна, добрый день!');
        await input.press('Enter');
        await input.pressSequentially('Ссылка на встречу придёт письмом.');
        await expect(input).toHaveValue('Анна, добрый день!\nСсылка на встречу придёт письмом.');
        await page.getByRole('button', { name: 'Отправить' }).click();
        await expect(page.locator('.msg.me').last()).toContainText('Ссылка на встречу придёт письмом.');
        await expect(input).toHaveValue('');
      }
      await page.getByRole('button', { name: '← Диалоги' }).click();
      await settled(page);
      await expect(page).toHaveURL(/#\/e\/chat$/);
      await expect(page.locator('#chat-list')).toBeVisible();

      if (phone) {
        // непрочитанное у кандидата: цифра помещается в бейдж и в строке разделов, и в списке диалогов на узком экране.
        // Переписка «Ладога Пэй» ↔ A-1042 открывается принятием приглашения (в полном прогоне его уже принял 04-employer)
        await demo(page, 'c');
        await page.evaluate(async () => {
          const h = who => ({ Authorization: 'Bearer ' + localStorage.getItem('fsp.tok.' + who), 'Content-Type': 'application/json' });
          const { items } = await (await fetch('/api/candidate/invites', { headers: h('c') })).json();
          const inv = items.find(i => i.company === 'Ладога Пэй' && i.status !== 'accepted');
          if (inv) {
            const a = await fetch(`/api/candidate/invites/${inv.id}/accept`, { method: 'POST', headers: h('c') });
            if (!a.ok) throw new Error(`приглашение «Ладога Пэй» (${inv.status}) не принимается: ${a.status}`);
          }
          const r = await fetch('/api/chat/A-1042', { method: 'POST', headers: h('e'), body: JSON.stringify({ text: 'Дмитрий, добрый день! Удобно созвониться завтра?' }) });
          if (!r.ok) throw new Error('POST ' + r.status);
        });
        await open(page, '/c/chat');
        const fits = el => el.scrollWidth <= el.clientWidth && el.scrollHeight <= el.clientHeight && el.clientWidth >= 18;
        const badge = page.locator('nav.subnav').getByRole('button', { name: /^Чат/ }).locator('.unread');
        await expect(badge).toHaveText(/^\d+$/);
        expect(await badge.evaluate(fits)).toBe(true);
        expect(await page.locator('.chat-peer', { hasText: 'Ладога Пэй' }).locator('.unread').evaluate(fits)).toBe(true);

        // новое сообщение приходит само (SSE) — бейдж в строке разделов обновляется, прокрутка строки не сбрасывается
        await open(page, '/c/settings');
        const nav = page.locator('nav.subnav'), before = Number(await badge.textContent());
        const x = await nav.evaluate(n => n.scrollLeft);
        expect(x).toBeGreaterThan(0);  // «Настройки и приватность» в конце строки — прокручено к ним
        await page.evaluate(() => fetch('/api/chat/A-1042', { method: 'POST', headers: { Authorization: 'Bearer ' + localStorage.getItem('fsp.tok.e'), 'Content-Type': 'application/json' }, body: JSON.stringify({ text: 'И ещё: пришлю задачу заранее.' }) }));
        await expect(badge).toHaveText(String(before + 1));
        expect(Math.abs((await nav.evaluate(n => n.scrollLeft)) - x)).toBeLessThanOrEqual(1);
      }
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

    // прогресс не вылезает за край карточки
    const quest = await box(page.locator('.quest'));
    expect((await box(page.locator('.quest-top .pr'))).right).toBeLessThanOrEqual(quest.right);
    // шапка задания с таймером прилипает под шапкой сайта, «Дальше» — к нижнему краю экрана
    const sticky = sel => page.locator(sel).evaluate(e => { const s = getComputedStyle(e); return [s.position, s.top, s.bottom].join(' '); });
    expect(await sticky('.quest-top')).toMatch(/^sticky 56px /);
    expect(await sticky('.quest-foot')).toMatch(/^sticky .* 0px$/);
    // задание выше экрана (так почти всегда, но длина зависит от выпавшего задания): проверяем и на деле
    // (poll: карточка появляется с анимацией сдвига на 4 px)
    if (quest.bottom > 812) await expect.poll(async () => Math.round((await box(page.locator('.quest-foot'))).bottom)).toBe(812);
    const room = await page.evaluate(() => document.documentElement.scrollHeight - innerHeight);
    if (room > quest.top) {
      await page.evaluate(y => scrollTo(0, y), Math.round(quest.top));
      await expect.poll(async () => Math.round((await box(page.locator('.quest-top'))).top)).toBe(56);
    }
    // ответ и переход к следующему заданию с нижней панели
    const opts = page.locator('.opt');
    if (await opts.count()) await opts.first().click(); else await page.locator('.code button[data-act=mark]').nth(1).click();
    if (await page.locator('#rv-comment').count()) await page.locator('#rv-comment').fill('Нет блокировки строки.');
    const prev = await page.evaluate(() => S.quest.item.id);
    await page.getByRole('button', { name: 'Дальше' }).click();
    await expect.poll(() => page.evaluate(() => S.quest.item && S.quest.item.id)).not.toBe(prev);
  });
});

// самый узкий телефон (320 px) и телефон боком (812×375, маленький — 568×320): без горизонтальной прокрутки;
// на низком экране шапка сайта не прилипает, а у маленького боком — и шапка задания с «Дальше»
for (const [name, viewport] of [['узкий телефон', { width: 320, height: 568 }], ['телефон боком', { width: 812, height: 375 }], ['маленький телефон боком', { width: 568, height: 320 }]]) {
  test.describe(name, () => {
    test.use({ viewport, hasTouch: true, isMobile: true });

    test(`${name}: экраны без горизонтальной прокрутки`, async ({ page }) => {
      for (const r of ['/', '/c/signup', '/e/signup', '/v']) {
        await open(page, r);
        await noHScroll(page, r);
      }
      // Enter в почте компании — «Получить код»
      await page.goto('/#/e/signup');
      await settled(page);
      const email = `hr-${uniq()}@example.ru`;
      await page.getByLabel('Рабочая почта').fill(email);
      await page.getByLabel('Рабочая почта').press('Enter');
      await expect(toast(page)).toHaveText('Код отправлен на ' + email);
      await demo(page, 'c');
      for (const r of ['/c/home', '/c/vacancies', '/c/profile', '/c/quest', '/c/settings']) {
        await open(page, r);
        await noHScroll(page, r);
      }
      await demo(page, 'e');
      for (const r of ['/e/picks', '/e/search', '/e/pipeline', '/e/vacancies', '/e/chat']) {
        await open(page, r);
        await noHScroll(page, r);
      }
      const pos = sel => page.locator(sel).evaluate(e => getComputedStyle(e).position);
      if (viewport.height < 480) expect(await pos('header.top')).toBe('static');  // телефон боком: шапка сайта не прилипает
      if (viewport.width <= 640 && viewport.height < 480) {  // и шапка задания с «Дальше» — иначе съели бы пол-экрана
        await demo(page, 'c');
        await open(page, '/c/quest');
        await page.getByRole('button', { name: 'Полный тест (~40 мин)' }).click();
        await settled(page);
        await noHScroll(page, 'задание');
        expect([await pos('.quest-top'), await pos('.quest-foot')]).toEqual(['static', 'static']);
      }
    });
  });
}
