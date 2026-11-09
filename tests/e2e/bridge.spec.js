const { test, expect } = require('@playwright/test');

test('T02 桥接错误安全上报且长导出不提前恢复布局', async ({ page }) => {
  await page.goto('/');
  await page.waitForFunction(() => typeof Bridge !== 'undefined');
  await page.clock.install();
  await page.evaluate(async () => {
    window.__logs = [];
    window.pywebview = { api: {
      set_dirty() {}, startup_ready() {}, store_content() { return { success: true }; },
      get_output_settings() { return { font: 'normal', pdf_layout: 'paged' }; },
      log_js_error(...args) { window.__logs.push(args); },
      export_as_write() { return new Promise(resolve => { window.__finishExport = resolve; }); },
    } };
    await ensureTurndown();
    await loadContent('/tmp/t02.md', '# 桥接测试\n\n内容', 720, false, true);
    await toggleView();
    window.__exportDone = false;
    window.__pendingExport = exportAsWrite('/tmp/t02.pdf', 'pdf').then(() => { window.__exportDone = true; });
  });
  await expect.poll(() => page.evaluate(() => typeof window.__finishExport)).toBe('function');
  await page.clock.fastForward(20000);
  expect(await page.evaluate(() => window.__exportDone)).toBe(false);
  await expect(page.locator('#textarea')).not.toBeVisible();
  await page.evaluate(async () => { window.__finishExport({ success: true }); await window.__pendingExport; });
  await expect(page.locator('#textarea')).toBeVisible();
  const logs = await page.evaluate(async () => {
    window.__logs = []; // count only the errors raised below, not any from the export above
    window.dispatchEvent(new ErrorEvent('error', { message: 'SECRET正文', error: new TypeError('SECRET正文') }));
    const event = new Event('unhandledrejection');
    event.reason = new Error('SECRET正文');
    window.dispatchEvent(event);
    await Bridge.callSafe('missing');
    pywebview.api.log_js_error = () => Promise.reject(new Error('SECRET正文'));
    await Bridge.callSafe('missing');
    return window.__logs;
  });
  expect(logs.length).toBe(3);
  expect(JSON.stringify(logs)).not.toContain('SECRET');
});
