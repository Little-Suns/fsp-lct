// Тёмная тема: системная настройка, переключатель в шапке, выбор переживает перезагрузку.
const { test, expect, open } = require('./fixtures');

const bg = page => page.evaluate(() => getComputedStyle(document.body).backgroundColor);
const LIGHT = 'rgb(246, 246, 248)';  // --ground
const DARK = 'rgb(15, 16, 19)';
const toggle = page => page.locator('#theme');

test.describe('системная светлая', () => {
  test.use({ colorScheme: 'light' });
  test('по умолчанию светлая; переключатель включает тёмную и выбор переживает перезагрузку', async ({ page }) => {
    await open(page, '/');
    await expect(toggle(page)).toHaveText(/Тёмная тема/);
    expect(await bg(page)).toBe(LIGHT);
    await toggle(page).click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await expect(toggle(page)).toHaveText(/Светлая тема/);
    expect(await bg(page)).toBe(DARK);
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    expect(await bg(page)).toBe(DARK);
    await toggle(page).click();  // обратно
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    await page.reload();
    expect(await bg(page)).toBe(LIGHT);
  });
});

test.describe('системная тёмная', () => {
  test.use({ colorScheme: 'dark' });
  test('системная тёмная применяется без выбора, явная светлая её перекрывает', async ({ page }) => {
    await open(page, '/');
    expect(await bg(page)).toBe(DARK);
    await expect(page.locator('html')).not.toHaveAttribute('data-theme', /.+/);
    await expect(toggle(page)).toHaveText(/Светлая тема/);
    await toggle(page).click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    expect(await bg(page)).toBe(LIGHT);
    await page.reload();
    expect(await bg(page)).toBe(LIGHT);
  });

  test('смена системной темы на лету обновляет подпись переключателя', async ({ page }) => {
    await open(page, '/');
    await page.emulateMedia({ colorScheme: 'light' });
    await expect(toggle(page)).toHaveText(/Тёмная тема/);
  });

  test('приватный режим: хранилище недоступно — переключатель всё равно работает', async ({ page }) => {
    await page.addInitScript(() => {
      Object.defineProperty(window, 'localStorage', { get() { throw new Error('denied'); } });
    });
    await open(page, '/');
    await toggle(page).click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  });

  test('hover основной кнопки: фон отличается от текста и от --blue-ink', async ({ page }) => {
    await open(page, '/');
    const btn = page.getByRole('button', { name: 'Я разработчик' });
    await btn.hover();
    await page.waitForTimeout(300);
    const s = await btn.evaluate(el => ({ bg: getComputedStyle(el).backgroundColor, fg: getComputedStyle(el).color }));
    expect(s.bg).not.toBe(s.fg);
    expect(s.bg).not.toBe('rgb(181, 175, 255)');  // --blue-ink: белый на нём ≈ 2:1
    expect(s.bg).toBe('rgb(75, 61, 240)');  // --blue-hover
  });
});
