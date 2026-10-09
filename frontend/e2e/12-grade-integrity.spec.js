// Целостность грейда (идёт последним: меняет демо-кандидата Орлова). Слабая пересдача грейд не понижает — нижний
// кандидат принимает сам; смена специализации сбрасывает тест, и до нового теста работодатели кандидата не видят.
const { test, expect, open, demo, toast, api } = require('./fixtures');

// все задания до конца, ответы «по кругу» (слабая попытка: верных мало); задачу на код — шаблоном
async function answerWeak(page) {
  const finish = page.getByRole('button', { name: 'Посмотреть категорию' });
  for (let n = 0; n < 60 && !(await finish.isVisible()); n++) {
    if (await page.locator('#code-ed').count()) {
      const sent = api(page, 'POST', '/api/quest/answer');
      await page.getByRole('button', { name: 'Отправить решение' }).click();
      await sent;
      await expect(page.locator('#code-ed')).toHaveCount(0);
      continue;
    }
    const opts = page.locator('.opt');
    if (await opts.count()) await opts.nth(n % (await opts.count())).click();
    else {
      await page.locator('.code button[data-act=mark]').first().click();
      if (await page.locator('#rv-comment').count()) await page.locator('#rv-comment').fill('Не вижу проблемы.');
    }
    const sent = api(page, 'POST', '/api/quest/answer');
    await page.getByRole('button', { name: 'Дальше' }).click();
    await sent;
  }
}

test('слабая пересдача: грейд не понижен, «Принять грейд» — по решению кандидата', async ({ page }) => {
  test.setTimeout(180_000);
  await demo(page, 'c');
  await open(page, '/candidate/test');
  await expect(page.getByText(/Слабая попытка грейд не понижает — принять нижний грейд можете только вы/)).toBeVisible();
  const start = api(page, 'POST', '/api/quest/start');
  await page.getByRole('button', { name: 'Полный тест (~40 мин)' }).click();
  await start;
  await answerWeak(page);
  const fin = api(page, 'POST', '/api/quest/finish');
  await page.getByRole('button', { name: 'Посмотреть категорию' }).click();
  const res = await (await fin).json();
  // ответы по кругу почти всегда дают ниже Middle; иначе понижать нечего — сценарий не про это
  test.skip(!res.lower_offer, `попытка не ниже Middle (${res.attempt.theta})`);
  expect(res).toMatchObject({ applied: false, category: { grade: 'Middle' } });
  const low = res.lower_offer.grade;
  await expect(page.getByText(/Грейд не понижен: категория и место в выдаче прежние/)).toBeVisible();
  await expect(page.locator('.cat').first()).toHaveText('BackendPythonMiddle');
  await expect(page.locator('#lower-offer')).toContainText(`Последняя попытка показала ${low}`);
  await expect(page.locator('table.tbl tbody tr').first()).toContainText('не применён');
  // понижение — только после подтверждения; «Отмена» ничего не меняет
  await page.getByRole('button', { name: `Принять грейд ${low}` }).click();
  await expect(page.getByRole('alertdialog')).toContainText(`Принять грейд ${low} вместо Middle?`);
  await page.getByRole('button', { name: 'Отмена' }).click();
  await expect(page.getByRole('alertdialog')).toHaveCount(0);
  await expect(page.locator('.cat').first()).toHaveText('BackendPythonMiddle');
  await page.getByRole('button', { name: `Принять грейд ${low}` }).click();
  const acc = api(page, 'POST', '/api/quest/accept-lower');
  await page.getByRole('button', { name: `Принять ${low}`, exact: true }).click();
  expect(await (await acc).json()).toMatchObject({ applied: true, category: { grade: low }, lower_offer: null });
  await expect(toast(page)).toHaveText(`Грейд ${low} принят`);
  await expect(page.locator('.cat').first()).toHaveText(`BackendPython${low}`);
  await expect(page.getByText(`Грейд ${low} принят по вашему решению.`)).toBeVisible();
  await expect(page.locator('#lower-offer')).toHaveCount(0);
  await expect(page.locator('table.tbl tbody tr').first()).toContainText('категория обновлена');
});

test('смена специализации: тест не переносится, до нового теста работодатели не видят', async ({ page }) => {
  await demo(page, 'c');
  await expect(page.getByText('Работодатели вас не видят, пока вы не пройдёте тест')).toHaveCount(0);
  await open(page, '/candidate/profile');
  await expect(page.locator('#spec-reset')).toHaveCount(0);
  await page.getByLabel('Специализация').selectOption('Frontend');
  await expect(page.locator('#spec-reset')).toContainText('Результат теста привязан к специализации Backend');
  await expect(page.locator('#spec-reset')).toContainText('в Frontend не переносится');
  await page.getByLabel('Специализация').selectOption('Backend');
  await expect(page.locator('#spec-reset')).toHaveCount(0);
  await page.getByLabel('Специализация').selectOption('Frontend');
  const saved = api(page, 'POST', '/api/candidate/profile');
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
  expect(await (await saved).json()).toMatchObject({ test_reset: true, spec: 'Frontend', grade: null, visible: false, skills_confirmed: [] });
  await expect(toast(page)).toHaveText('Специализация изменена: пройдите тест по Frontend — до него работодатели вас не видят');
  await open(page, '/candidate');
  await expect(page.getByText('Работодатели вас не видят, пока вы не пройдёте тест по специализации Frontend.')).toBeVisible();
  await open(page, '/candidate/test/result');
  await expect(page.getByRole('heading', { name: 'Тест ещё не пройден' })).toBeVisible();

  // работодатель: A-1042 нет ни в поиске, ни по прямой ссылке
  await demo(page, 'e');
  const R = await page.evaluate(() => api('GET', '/api/employer/search?limit=100&q=Kafka'));
  expect(R.items.find(c => c.id === 'A-1042')).toBeUndefined();
  await open(page, '/employer/candidates/A-1042');
  await expect(page.getByText('Кандидат не найден или скрыл профиль.')).toBeVisible();
});
