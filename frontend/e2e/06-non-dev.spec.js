// Нетехнические роли: потребность «продакт-менеджер» разбирается в Management · Product, план теста — по компетенциям
// менеджера, подборка открывается под заголовком роли, а не «…-разработчик».
const { test, expect, open, demo, api } = require('./fixtures');

test('продакт-менеджер: разбор в Management · Product, план теста и подборка', async ({ page }) => {
  await demo(page, 'e');
  await open(page, '/e/need');
  await page.locator('#need-text').fill('Ищем продакт-менеджера в B2B SaaS. Нужен опыт CustDev и A/B-тестов, хорошо бы Jira. Мидл, до 300 на руки. Удалённо.');
  const parsed = api(page, 'POST', '/api/employer/needs/parse');
  await page.getByRole('button', { name: 'Разобрать' }).click();
  const p = await (await parsed).json();
  expect([p.spec, p.track, p.grade, p.must]).toEqual(['Management', 'Product', 'Middle', ['CustDev', 'A/B-тесты']]);
  await expect(page.locator('.parsed .cat span')).toHaveText(['Management', 'Product', 'Middle']);
  await expect(page.getByText(/В категории Management · Product · Middle \d+ кандидатов/)).toBeVisible();
  await expect(page.getByText('Рынок · Management · Middle')).toBeVisible();

  await page.getByRole('button', { name: 'Показать план теста' }).click();
  await expect(page.locator('.bars')).toContainText('Метрики продукта');
  await expect(page.locator('.bars')).toContainText('A/B-тесты');

  const picks = api(page, 'GET', /^\/api\/employer\/needs\/\d+\/picks$/);
  await page.getByRole('button', { name: 'Показать подборку' }).click();
  expect((await picks).ok()).toBe(true);
  await expect(page.getByRole('heading', { name: 'Product-менеджер' })).toBeVisible();
});
