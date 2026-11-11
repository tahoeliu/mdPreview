const { test, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const oldCSS = fs.readFileSync(path.join(root, 'tests/fixtures/styles-t02.css'), 'utf8');

for (const theme of ['light', 'dark']) {
  test(`T03 ${theme} 非标题区域保留历史视觉基线`, async ({ page }, info) => {
    await page.emulateMedia({ colorScheme: theme });
    await page.goto('/');
    await page.evaluate(async () => {
      window.pywebview = { api: { set_dirty() {}, store_content() {}, startup_ready() {} } };
      await loadContent('/tmp/styles.md', '正文 **加粗** *斜体* [link](https://example.com)\n\n> 引用\n\n| 列一 | Column |\n| --- | --- |\n| 中文 | Value |\n\n```js\nconst message = "hello";\n```\n\n---\n\n尾部', 720, false, true);
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

// Headings intentionally changed after the original stylesheet split. Assert
// the approved design directly instead of comparing it with obsolete pixels.
for (const theme of ['light', 'dark']) {
  test(`T208 ${theme} 标题阶梯、连续间距与任务框对齐`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: theme });
    await page.goto('/');
    await page.evaluate(async () => {
      window.pywebview = { api: { set_dirty() {}, store_content() {}, startup_ready() {} } };
      await loadContent('/tmp/typography.md', '# Title\n## Section\n### Topic\n#### Detail\n##### Note\n###### Point\n\n正文\n\n- [ ] Task text\n- [x] 已完成任务', 720, false, true);
    });
    for (const size of [12, 14, 16, 18, 20, 24]) {
      await page.evaluate(size => document.documentElement.style.setProperty('--content-font-size', `${size}px`), size);
      const measured = await page.locator('#content').evaluate(root => {
        const headings = [...root.querySelectorAll('h1,h2,h3,h4,h5,h6')];
        const boxes = [...root.querySelectorAll('.task-toggle')];
        return {
          sizes: headings.map(h => parseFloat(getComputedStyle(h).fontSize)),
          gaps: headings.slice(1).map((h, i) => h.getBoundingClientRect().top - headings[i].getBoundingClientRect().bottom),
          body: parseFloat(getComputedStyle(root).fontSize),
          boxes: boxes.map(box => ({ align: getComputedStyle(box).verticalAlign, top: parseFloat(getComputedStyle(box).top), width: box.getBoundingClientRect().width, height: box.getBoundingClientRect().height }))
        };
      });
      expect(measured.body).toBe(size);
      [1.75, 1.5, 1.375, 1.25, 1.1875, 1.125].forEach((ratio, i) => expect(measured.sizes[i]).toBeCloseTo(size * ratio, 2));
      [.875, .75, .625, .5, .5].forEach((ratio, i) => expect(Math.abs(measured.gaps[i] - (i === 4 ? Math.max(8, size * ratio) : size * ratio))).toBeLessThan(.06));
      expect(measured.boxes).toHaveLength(2);
      for (const box of measured.boxes) {
        expect(box.align).toBe('middle');
        expect(box.top).toBeCloseTo(-size * .08, 2);
        expect(box.width).toBeCloseTo(box.height, 2);
      }
      expect(measured.boxes[0].height).toBe(measured.boxes[1].height);
    }
    // Exhaust all heading pairs, with and without a real intervening block.
    const pairs = await page.evaluate(() => {
      document.documentElement.style.setProperty('--content-font-size', '16px');
      const root = document.getElementById('content');
      root.replaceChildren();
      const result = [];
      for (let a = 1; a <= 6; a++) for (let b = 1; b <= 6; b++) {
        for (const separated of [false, true]) {
          const section = document.createElement('section');
          section.style.display = 'flow-root';
          section.innerHTML = `<h${a}>First</h${a}>${separated ? '<p>Body</p>' : ''}<h${b}>Second</h${b}>`;
          root.append(section);
          const second = section.lastElementChild;
          result.push({ a, b, separated, top: parseFloat(getComputedStyle(second).marginTop) });
        }
      }
      return result;
    });
    for (const pair of pairs) {
      const expected = !pair.separated && pair.a < pair.b ? [0, 14, 12, 10, 8, 8][pair.a] : [0, 0, 32.64, 25.92, 20.8, 18, 18][pair.b];
      // WebKit quantizes computed margins to fractional layout units.
      expect(Math.abs(pair.top - expected)).toBeLessThan(.03);
    }
  });
}

test('T208 输出态标题保留原排版', async ({ page }) => {
  await page.goto('/');
  await page.evaluate(async () => {
    window.pywebview = { api: { set_dirty() {}, store_content() {}, startup_ready() {} } };
    await loadContent('/tmp/output-style.md', '# One\n## Two\n### Three\n#### Four\n##### Five\n###### Six\n\nBody', 720, false, true);
    document.documentElement.style.setProperty('--content-font-size', '16px');
    document.documentElement.dataset.output = 'png';
  });
  const snapshot = () => page.locator('#content h1,#content h2,#content h3,#content h4,#content h5,#content h6').evaluateAll(nodes => nodes.map(h => {
    const s = getComputedStyle(h); return [s.fontSize, s.lineHeight, s.marginTop, s.marginBottom];
  }));
  const current = await snapshot();
  expect(current.map(s => parseFloat(s[0]))).toEqual([30, 23, 18, 15, 14, 13]);
  await page.evaluate(css => {
    document.querySelectorAll('link[rel="stylesheet"]').forEach(el => el.remove());
    const style = document.createElement('style'); style.textContent = css; document.head.append(style);
  }, oldCSS);
  expect(await snapshot()).toEqual(current);
});

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
