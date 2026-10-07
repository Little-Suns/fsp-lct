// Перерисовка того же экрана не «перезапускает» его: нет анимации появления, прокрутка, фокус и ввод на месте.
const { test, expect, demo, open } = require('./fixtures');

const anim = (page, sel) => page.locator(sel).first().evaluate(el => getComputedStyle(el).animationName);

test('клик по чипу в анкете: без анимации, прокрутка, фокус и ввод сохранены; смена экрана — с анимацией', async ({ page }) => {
  await demo(page, 'c');
  await open(page, '/c/profile');
  expect(await anim(page, '#app .fade')).toBe('fade');  // смена экрана — анимация есть

  const name = page.locator('#p-name');
  await name.fill('Тест Перерисовки');
  const chip = page.locator('button.chip[data-act="ptoggle"][data-k="roles"]').first();
  await chip.scrollIntoViewIfNeeded();
  await page.evaluate(() => scrollBy(0, 60));
  const y = await page.evaluate(() => scrollY);
  expect(y).toBeGreaterThan(0);
  const was = await chip.getAttribute('class');
  const v = await chip.getAttribute('data-v');

  await chip.click();
  const same = page.locator(`button.chip[data-act="ptoggle"][data-k="roles"][data-v="${v}"]`);
  await expect(same).not.toHaveClass(was);  // состояние чипа переключилось, экран перерисован
  expect(await anim(page, '#app .fade')).toBe('none');
  expect(await page.evaluate(() => scrollY)).toBe(y);
  expect(await page.evaluate(() => document.activeElement.dataset.v)).toBe(v);
  await expect(name).toHaveValue('Тест Перерисовки');

  // выбор грейда — тоже rerender: фокус остаётся на нажатой кнопке
  await page.locator('button[data-act="pgrade"]').first().click();
  expect(await page.evaluate(() => document.activeElement.dataset.act)).toBe('pgrade');

  // смена специализации: change → rerender, фокус остаётся на селекте
  await page.locator('#p-spec').focus();
  await page.locator('#p-spec').selectOption({ index: 1 });
  await expect(page.locator('#p-spec')).toBeFocused();
  await expect(name).toHaveValue('Тест Перерисовки');

  // смена экрана снова с анимацией
  await open(page, '/c/home');
  expect(await anim(page, '#app .fade')).toBe('fade');
});
