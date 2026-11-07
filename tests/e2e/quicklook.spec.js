// Finder 空格预览页（quicklook/web）：与主应用同一条净化管线，必须渲染正确、不联网、不执行文档里的脚本。
const { test, expect } = require('@playwright/test');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const root = path.resolve(__dirname, '../..');

// 与 quicklook/build.sh 使用同一份资源清单，组装出和扩展里一模一样的 web 目录。
function assemble(folder) {
  fs.mkdirSync(path.join(folder, 'fonts'), { recursive: true });
  for (const line of fs.readFileSync(path.join(root, 'quicklook/resources.txt'), 'utf8').split('\n')) {
    const [source, first, second] = line.trim().split(/\s+/);
    if (!source || source.startsWith('#')) continue;
    if (source === '@fonts') {
      for (const file of fs.readdirSync(path.join(root, first)).filter(name => name.endsWith('.woff2'))) fs.copyFileSync(path.join(root, first, file), path.join(folder, second, file));
    } else fs.copyFileSync(path.join(root, source), path.join(folder, first));
  }
}

let page_url;
test.beforeAll(() => {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'mdpreview-ql-'));
  assemble(folder);
  page_url = pathToFileURL(path.join(folder, 'preview.html')).href;
});

async function open(page, markdown) {
  const requests = [];
  page.on('request', request => { if (/^https?:/i.test(request.url())) requests.push(request.url()); });
  await page.goto(page_url);
  await page.waitForFunction(() => typeof window.renderMarkdownPreview === 'function');
  const result = await page.evaluate(text => window.renderMarkdownPreview(text), markdown);
  return { result, requests };
}

const SAMPLE = '# 标题 Title\n\n## 小节\n\n正文 **粗体** *斜体* `code` [链接](https://example.com)\n\n- 列表一\n- 列表二\n\n| 列 A | 列 B |\n| --- | --- |\n| 一 | 二 |\n\n```js\nconst answer = 42;\n```\n\n> 引用文字\n\n脚注[^1]\n\n[^1]: 脚注内容';

test('渲染标题、列表、表格、代码、引用和脚注', async ({ page }) => {
  const { result } = await open(page, SAMPLE);
  expect(result.headings).toBe(3); // h1 + h2 + 脚注扩展自带的“Footnotes”标题
  await expect(page.locator('h1')).toHaveText('标题 Title');
  await expect(page.locator('table th')).toHaveCount(2);
  await expect(page.locator('pre code')).toContainText('const answer = 42;');
  await expect(page.locator('blockquote')).toContainText('引用文字');
  await expect(page.locator('.footnotes')).toContainText('脚注内容');
  expect(result.elements).toBeGreaterThan(20);
});

test('公式被 KaTeX 渲染，四种分隔符都支持', async ({ page }) => {
  const { result } = await open(page, '行内 $a^2+b^2=c^2$ 与 \\(E=mc^2\\)\n\n$$\n\\sum_{i=1}^n i = \\frac{n(n+1)}{2}\n$$\n\n\\[\n\\int_0^1 x^2 dx\n\\]');
  expect(result.formulas).toBe(4);
  expect(await page.locator('.katex').count()).toBeGreaterThanOrEqual(4);
  await expect(page.locator('.math-block[data-rendered="1"]')).toHaveCount(2);
});

test('前置元数据显示为独立块，正文不受影响', async ({ page }) => {
  await open(page, '---\ntitle: 示例\ntags: [a, b]\n---\n\n# 正文标题');
  await expect(page.locator('.frontmatter')).toContainText('title: 示例');
  await expect(page.locator('h1')).toHaveText('正文标题');
});

test('文档里的脚本、事件属性、iframe 和 javascript: 链接都无效', async ({ page }) => {
  const payload = '<script>window.__pwn = 1</script>\n\n<img src="x" onerror="window.__pwn = 2">\n\n<iframe src="https://example.com"></iframe>\n\n[点我](javascript:window.__pwn=3)\n\n<a href="javascript:window.__pwn=4" onclick="window.__pwn=5">x</a>\n\n<svg onload="window.__pwn=6"></svg>\n\n<form action="https://example.com"><input name="a"></form>';
  const { requests } = await open(page, payload);
  await page.waitForTimeout(300);
  expect(await page.evaluate(() => window.__pwn)).toBeUndefined();
  expect(await page.locator('iframe, script:not([src]), form, input').count()).toBe(0);
  const hrefs = await page.locator('a[href]').evaluateAll(links => links.map(a => a.getAttribute('href')));
  expect(hrefs.filter(href => /^\s*javascript:/i.test(href))).toEqual([]);
  expect(requests).toEqual([]);
});

test('远程图片不发请求，替换为带 alt 的占位；data: 图片保留', async ({ page }) => {
  const dot = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==';
  const { result, requests } = await open(page, `![远程图](https://example.com/a.png)\n\n![本地图](./local.png)\n\n![内嵌图](${dot})`);
  expect(result.blocked_images).toBe(2);
  await expect(page.locator('.blocked-image')).toHaveCount(2);
  await expect(page.locator('.blocked-image').first()).toHaveText('远程图');
  await expect(page.locator('img')).toHaveCount(1);
  expect(requests).toEqual([]);
});

test('CSP 阻止联网和内联脚本', async ({ page }) => {
  await open(page, '# x');
  const outcome = await page.evaluate(async () => {
    const report = {};
    try { await fetch('https://example.com/'); report.fetch = 'allowed'; } catch (error) { report.fetch = 'blocked'; }
    const script = document.createElement('script');
    script.textContent = 'window.__inline = true';
    document.head.append(script);
    report.inline = window.__inline === true ? 'ran' : 'blocked';
    return report;
  });
  expect(outcome).toEqual({ fetch: 'blocked', inline: 'blocked' });
});

test('深色模式下背景与文字都切换', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' });
  await open(page, '# 标题\n\n正文');
  const colors = await page.evaluate(() => ({ background: getComputedStyle(document.body).backgroundColor, text: getComputedStyle(document.querySelector('.markdown')).color }));
  expect(colors.background).not.toBe('rgb(255, 255, 255)');
  expect(colors.text).not.toBe(colors.background);
});

test('2MB 大文件能在合理时间内渲染完成', async ({ page }) => {
  test.setTimeout(120000);
  const paragraph = '这是一段用于压力测试的正文，包含 **粗体**、`行内代码` 和 English words.\n\n';
  const big = ('## 小节\n\n' + paragraph.repeat(8)).repeat(Math.ceil(2 * 1024 * 1024 / 600));
  const begin = Date.now();
  const { result } = await open(page, big);
  expect(result.headings).toBeGreaterThan(1000);
  expect(Date.now() - begin).toBeLessThan(60000);
});
