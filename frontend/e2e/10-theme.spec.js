// Тёмная тема: системная настройка, переключатель в шапке, выбор переживает перезагрузку.
const { test, expect, open } = require('./fixtures');

const bg = page => page.evaluate(() => getComputedStyle(document.body).backgroundColor);
const LIGHT = 'rgb(246, 246, 248)';  // --ground
const DARK = 'rgb(15, 16, 19)';

test.describe('системная светлая', () => {
  test.use({ colorScheme: 'light' });
  test('по умолчанию светлая; переключатель включает тёмную и выбор переживает перезагрузку', async ({ page }) => {
    await open(page, '/');
    const btn = page.getByRole('button', { name: 'Тёмная тема' });
    await expect(btn).toHaveText(/Тёмная/);
    expect(await bg(page)).toBe(LIGHT);
    await btn.click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await expect(btn).toHaveText(/Светлая/);
    await expect(btn).toHaveAttribute('aria-pressed', 'true');
    expect(await bg(page)).toBe(DARK);
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    expect(await bg(page)).toBe(DARK);
    await page.getByRole('button', { name: 'Тёмная тема' }).click();  // обратно
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
    const btn = page.getByRole('button', { name: 'Тёмная тема' });
    await expect(btn).toHaveText(/Светлая/);
    await btn.click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    expect(await bg(page)).toBe(LIGHT);
    await page.reload();
    expect(await bg(page)).toBe(LIGHT);
  });

  test('смена системной темы на лету обновляет подпись переключателя', async ({ page }) => {
    await open(page, '/');
    await page.emulateMedia({ colorScheme: 'light' });
    await expect(page.getByRole('button', { name: 'Тёмная тема' })).toHaveText(/Тёмная/);
  });

  test('приватный режим: хранилище недоступно — переключатель всё равно работает', async ({ page }) => {
    await page.addInitScript(() => {
      Object.defineProperty(window, 'localStorage', { get() { throw new Error('denied'); } });
    });
    await open(page, '/');
    await page.getByRole('button', { name: 'Тёмная тема' }).click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  });
});
