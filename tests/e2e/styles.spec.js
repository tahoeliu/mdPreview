const { test, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const oldCSS = fs.readFileSync(path.join(root, 'tests/fixtures/styles-t02.css'), 'utf8');

for (const theme of ['light', 'dark']) {
  test(`T03 ${theme} 屏幕拆分前后像素与排版一致`, async ({ page }, info) => {
    await page.emulateMedia({ colorScheme: theme });
    await page.goto('/');
    await page.evaluate(async () => {
      window.pywebview = { api: { set_dirty() {}, store_content() {}, startup_ready() {} } };
      await loadContent('/tmp/styles.md', '# 阅读示例\n\n## 二级 Heading\n\n### 三级\n\n正文 **加粗** *斜体* [link](https://example.com)\n\n> 引用\n\n| 列一 | Column |\n| --- | --- |\n| 中文 | Value |\n\n```js\nconst message = "hello";\n```\n\n---\n\n尾部', 720, false, true);
      document.querySelectorAll('.welcome-overlay,.mode-indicator,.edit-hint-bubble').forEach(el => el.remove());
      document.activeElement.blur();
    });
    const current = await page.screenshot({ animations: 'disabled' });
    await page.evaluate(css => {
      document.querySelectorAll('link[rel="stylesheet"]').forEach(el => el.remove());
      const style = document.createElement('style'); style.textContent = css; document.head.append(style);
    }, oldCSS);
    const before = await page.screenshot({ animations: 'disabled' });
    await info.attach('拆分前', { body: before, contentType: 'image/png' });
    await info.attach('拆分后', { body: current, contentType: 'image/png' });
    const difference = await page.evaluate(async ([a, b]) => {
      const read = async base64 => {
        const image = new Image(); image.src = 'data:image/png;base64,' + base64; await image.decode();
        const canvas = document.createElement('canvas'); canvas.width = image.width; canvas.height = image.height;
        const ctx = canvas.getContext('2d'); ctx.drawImage(image, 0, 0);
        return ctx.getImageData(0, 0, image.width, image.height).data;
      };
      const x = await read(a), y = await read(b); let changed = 0;
      for (let i = 0; i < x.length; i += 4) if (Math.max(...[0, 1, 2].map(c => Math.abs(x[i+c]-y[i+c]))) > 16) changed++;
      return changed / (x.length / 4);
    }, [before.toString('base64'), current.toString('base64')]);
    console.log(`T03 像素差 ${info.project.name}/${theme}: ${difference}`);
    expect(difference).toBeLessThan(0.01);
  });
}

test('T03 样式资源顺序与输出浅色隔离', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.goto('/');
  expect(await page.locator('link[rel="stylesheet"]').evaluateAll(nodes => nodes.map(n => n.getAttribute('href'))))
    .toEqual(['css/tokens.css', 'css/content.css', 'css/app.css', 'css/print.css']);
  await page.evaluate(() => document.documentElement.dataset.output = 'print');
  expect(await page.locator('#content').evaluate(el => getComputedStyle(el).color)).toBe('rgb(51, 51, 51)');
  expect(await page.locator('body').evaluate(el => getComputedStyle(el).backgroundColor)).toBe('rgb(255, 255, 255)');
  await page.emulateMedia({ media: 'print', colorScheme: 'dark' });
  await page.evaluate(() => document.documentElement.style.setProperty('--content-font-size', '22px'));
  expect(await page.locator('#content').evaluate(el => parseFloat(getComputedStyle(el).fontSize))).toBeCloseTo(10.75 * 4 / 3, 3);
});
