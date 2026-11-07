const { test, expect } = require('../node_modules/@playwright/test');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const diagram = '```mermaid\nflowchart LR\n A[开始 Start] --> B{条件 Condition}\n B --> C[执行 Action]\n B --> D[结束 End]\n```';
const svgImage = (w = 1600, h = 1000) => `http://127.0.0.1:29381/viewer-fixture.svg?w=${w}&h=${h}`;
const imageMD = (w, h) => `![测试图片](${svgImage(w, h)})`;
const viewer = page => page.locator('#imageLightbox');
const scale = async page => parseInt(await page.locator('.image-viewer-scale').textContent());
const transform = page => page.locator('.image-viewer-surface').evaluate(node => node.style.transform);
async function load(page, md) { await page.evaluate(md => loadContent('/tmp/viewer.md', md, 720, false, true), md); }
async function openImage(page, w, h) {
  await load(page, imageMD(w, h)); await page.locator('#content img').click();
  await expect.poll(() => page.locator('.image-viewer-scale').textContent()).not.toBe('加载中…');
}
async function wheel(page, options) {
  await page.locator('.image-viewer-stage').evaluate((stage, options) => {
    const r = stage.getBoundingClientRect();
    stage.dispatchEvent(new WheelEvent('wheel', { clientX: r.x + r.width / 2, clientY: r.y + r.height / 2, bubbles: true, cancelable: true, ...options }));
  }, options);
}
test.beforeEach(async ({ page }) => {
  await page.route('**/viewer-fixture.svg?*', route => {
    const params = new URL(route.request().url()).searchParams;
    return route.fulfill({contentType:'image/svg+xml', body:`<svg xmlns="http://www.w3.org/2000/svg" width="${Number(params.get('w'))}" height="${Number(params.get('h'))}"><rect width="100%" height="100%" fill="#e9f1ff"/><circle cx="800" cy="500" r="250" fill="#4675bd"/></svg>`});
  });
  await page.goto('/'); await page.waitForFunction(() => typeof loadContent === 'function');
  await page.evaluate(async () => {
    window.__dirty = false; window.__writes = [];
    window.pywebview = { api: { set_dirty(d) { window.__dirty = d; return Promise.resolve(true); }, store_content() { return Promise.resolve({success:true}); }, startup_ready() {}, save_file(p,c) { window.__writes.push(c); return Promise.resolve({success:true}); }, export_as_write(p,f,c) { window.__export = c; return Promise.resolve({success:true}); } } };
    await ensureTurndown();
  });
});
test('ordinary images: zoom, anchor, limits, pan, reset, reopen, unchanged source', async ({ page }) => {
  await openImage(page); const initial = await scale(page);
  await page.mouse.move(600, 320); await page.mouse.wheel(0, -200);
  await expect.poll(() => scale(page)).toBeGreaterThan(initial);
  const before = await page.locator('.image-viewer-surface').boundingBox();
  await page.mouse.move(600, 320); await page.mouse.wheel(0, -100);
  await expect.poll(() => scale(page)).toBeGreaterThan(initial * 1.5);
  const after = await page.locator('.image-viewer-surface').boundingBox();
  expect(Math.abs((600-before.x)/before.width - (600-after.x)/after.width)).toBeLessThan(0.01);
  expect(Math.abs((320-before.y)/before.height - (320-after.y)/after.height)).toBeLessThan(0.01);
  const old = await transform(page);
  await page.mouse.move(500, 300); await page.mouse.down(); await page.mouse.move(680, 450, {steps:8}); await page.mouse.up();
  await expect.poll(() => transform(page)).not.toBe(old); await expect(viewer(page)).toBeVisible();
  await page.locator('[data-viewer="fit"]').click(); await expect.poll(() => scale(page)).toBe(initial);
  for (let i=0; i<20; i++) await wheel(page, {deltaY:-1e6, deltaMode:2});
  await expect.poll(() => scale(page)).toBe(1600); await expect(page.locator('[data-viewer="in"]')).toBeDisabled();
  for (let i=0; i<20; i++) await wheel(page, {deltaY:1e6, deltaMode:1});
  await expect.poll(() => scale(page)).toBe(10); await expect(page.locator('[data-viewer="out"]')).toBeDisabled();
  expect(await transform(page)).not.toMatch(/NaN|Infinity/);
  await page.keyboard.press('Escape'); await expect(viewer(page)).toBeHidden();
  await page.locator('#content img').click(); await expect.poll(() => scale(page)).toBe(initial);
  await page.locator('[data-viewer="close"]').click();
  expect(await page.evaluate(() => getCurrentMarkdown())).toBe(imageMD());
  expect(await page.evaluate(() => window.__dirty)).toBe(false);
});
test('Mermaid remains vector, IDs unique, source/export intact, visual evidence', async ({ page }, info) => {
  await load(page, diagram); await page.locator('#content .mermaid-diagram .node').first().click();
  await expect(viewer(page)).toBeVisible(); await expect(page.locator('.image-viewer-surface svg')).toBeVisible();
  await expect(page.locator('.image-viewer-surface')).toContainText('开始 Start');
  const result = await page.evaluate(() => {
    const ids = [...document.querySelectorAll('[id]')].map(n=>n.id);
    return {unique:new Set(ids).size===ids.length, unresolved:[...document.querySelectorAll('.image-viewer-surface [marker-end]')].filter(n=>!document.querySelector(n.getAttribute('marker-end').match(/#[^)]+/)[0])).length};
  });
  expect(result).toEqual({unique:true,unresolved:0});
  await page.locator('[data-viewer="in"]').click();
  await page.screenshot({path:path.join(root, 'WorkSpace/outputs/' + info.project.name + '-image-viewer-light.png')});
  await page.evaluate(() => exportAsWrite('/tmp/preview.html', 'html'));
  expect(await page.evaluate(()=>window.__export)).not.toContain('image-viewer-surface');
  expect(await page.evaluate(()=>window.__export)).toContain('<svg');
  await page.keyboard.press('Escape');
  expect(await page.evaluate(()=>getCurrentMarkdown())).toBe(diagram);
  await page.emulateMedia({colorScheme:'dark'});
  await load(page, diagram); await page.locator('#content .mermaid-diagram').click();
  await page.screenshot({path:path.join(root, 'WorkSpace/outputs/' + info.project.name + '-image-viewer-dark.png')});
});
test('keyboard focus, no edit/paste/undo leakage, native zoom, background scroll restore', async ({ page }) => {
  await load(page, '# Top\n\n' + 'Paragraph\n\n'.repeat(60) + imageMD());
  await page.locator('#content img').scrollIntoViewIfNeeded();
  const pos = await page.locator('.scroll-wrap').evaluate(n=>n.scrollTop);
  await page.locator('#content img').click(); await expect(page.locator('[data-viewer="in"]')).toBeEnabled();
  await expect(page.locator('[data-viewer="close"]')).toBeFocused();
  await page.keyboard.press('Tab'); await expect(page.locator('[data-viewer="out"]')).toBeFocused();
  await page.keyboard.press('Shift+Tab'); await expect(page.locator('[data-viewer="close"]')).toBeFocused();
  for (const key of ['a','Backspace','Meta+z','Meta+v','Meta+e','Meta+s']) await page.keyboard.press(key);
  await expect(viewer(page)).toBeVisible(); expect(await page.evaluate(()=>window.__writes.length)).toBe(0);
  const initial = await scale(page); await page.evaluate(()=>zoomIn()); await expect.poll(()=>scale(page)).toBeGreaterThan(initial);
  await page.keyboard.press('Escape'); expect(await page.locator('.scroll-wrap').evaluate(n=>n.scrollTop)).toBe(pos);
  expect(await page.evaluate(()=>window.__dirty)).toBe(false);
  expect(await page.locator('.scroll-wrap').evaluate(n=>n.inert)).toBe(false);
});
test('trackpad deltas, shift-scroll, horizontal scroll, pointer cancellation and edge drag', async ({ page }) => {
  await openImage(page); await page.locator('[data-viewer="actual"]').click();
  await expect.poll(()=>scale(page)).toBe(100);
  const before = await transform(page); await wheel(page,{deltaX:60,deltaY:80,shiftKey:true});
  await expect.poll(()=>transform(page)).not.toBe(before); expect(await scale(page)).toBe(100);
  const moved = await transform(page); await wheel(page,{deltaX:90,deltaY:0}); await expect.poll(()=>transform(page)).not.toBe(moved);
  await wheel(page,{deltaY:-1,deltaMode:1}); await expect.poll(()=>scale(page)).toBeGreaterThan(100);
  await wheel(page,{deltaY:-100,ctrlKey:true}); await expect.poll(()=>scale(page)).toBeGreaterThan(120);
  await page.mouse.move(400,300); await page.mouse.down(); await page.mouse.move(700,10); await page.mouse.up();
  await expect(page.locator('.image-viewer-stage')).not.toHaveClass(/dragging/);
  await page.mouse.move(450,300); await page.mouse.down();
  await page.locator('.image-viewer-stage').dispatchEvent('pointercancel');
  await expect(page.locator('.image-viewer-stage')).not.toHaveClass(/dragging/); await page.mouse.up();
  await page.mouse.move(450,300); await page.mouse.down(); await page.evaluate(()=>window.dispatchEvent(new Event('blur')));
  await expect(page.locator('.image-viewer-stage')).not.toHaveClass(/dragging/); await page.mouse.up();
  await page.keyboard.press('ArrowLeft'); await page.keyboard.press('ArrowUp');
  await page.keyboard.press('0'); await expect(viewer(page)).toBeVisible();
});
test('slow/error images, cancellation, stale load never reopens, missing Mermaid', async ({ page }) => {
  let release; const blocked = new Promise(resolve=>release=resolve);
  await page.route('**/slow-viewer.svg', async route=>{await blocked; await route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"/>'});});
  await load(page,'<img src="http://127.0.0.1:29381/slow-viewer.svg" width="100" height="100">');
  await page.locator('#content img').dispatchEvent('click'); await expect(viewer(page)).toBeVisible();
  await expect(page.locator('[data-viewer="in"]')).toBeDisabled(); await page.keyboard.press('Escape'); release();
  await expect(viewer(page)).toBeHidden();
  await load(page,'![broken](http://127.0.0.1:29381/no-such-image.png)'); await page.locator('#content img').dispatchEvent('click');
  await expect(viewer(page)).toBeHidden(); await expect(page.locator('#status')).toContainText('无法预览');
  await load(page,'```mermaid\nnot a valid graph ???\n```'); await expect(page.locator('.mermaid-error')).toBeVisible();
  await page.locator('.mermaid-error').click(); await expect(viewer(page)).toBeHidden();
});
test('document replacement, mode switch, close while dragging release all state', async ({ page }) => {
  await openImage(page); await page.evaluate(()=>toggleView()); await expect(viewer(page)).toBeHidden(); await expect(page.locator('#textarea')).toBeVisible();
  await page.locator('#content img').dispatchEvent('click'); await expect(viewer(page)).toBeHidden();
  await openImage(page); await load(page,'Replacement'); await expect(viewer(page)).toBeHidden(); await expect(page.locator('#content')).toHaveText('Replacement');
  await openImage(page); await page.mouse.move(400,300); await page.mouse.down(); await page.evaluate(()=>prepareForClose());
  await expect(viewer(page)).toBeHidden(); await page.mouse.up();
  expect(await page.locator('.scroll-wrap').evaluate(n=>n.inert)).toBe(false);
});
test('small windows, wide/tall images, repeated reopen, double-click fit', async ({ page }) => {
  await page.setViewportSize({width:360,height:480});
  for (const [w,h] of [[8000,100],[100,8000],[1,1]]) {
    await openImage(page,w,h); expect(await transform(page)).not.toMatch(/NaN|Infinity/);
    const fitted = await page.locator('.image-viewer-surface').boundingBox();
    const stage = await page.locator('.image-viewer-stage').boundingBox();
    expect(fitted.width).toBeLessThanOrEqual(stage.width); expect(fitted.height).toBeLessThanOrEqual(stage.height);
    await page.locator('[data-viewer="actual"]').click(); await expect.poll(()=>scale(page)).toBe(100);
    await page.locator('.image-viewer-stage').dblclick(); await expect(viewer(page)).toBeVisible();
    const close = await page.locator('[data-viewer="close"]').boundingBox(); expect(close.x+close.width).toBeLessThanOrEqual(360);
    await page.keyboard.press('Escape');
  }
  for (let i=0;i<15;i++) { await page.locator('#content img').click(); await page.keyboard.press('Escape'); }
  expect(await page.locator('.image-viewer-surface > *').count()).toBe(0);
  expect(await page.evaluate(()=>window.__dirty)).toBe(false);
});
test('image inside link does not navigate; dangerous attributes do not survive preview', async ({ page }) => {
  await load(page, `[${imageMD()}](https://example.com)\n\n<img src="bad" onerror="window.__attacked=true">`);
  await page.locator('#content img').first().click(); await expect(viewer(page)).toBeVisible(); expect(page.url()).toContain('127.0.0.1');
  expect(await page.evaluate(()=>window.__attacked)).toBeUndefined(); expect(await page.locator('.image-viewer-surface [onerror]').count()).toBe(0);
});
test('fit tracks resize, pinch gesture scales, native modal remains usable', async ({ page }) => {
  await openImage(page); const original = await scale(page);
  await page.setViewportSize({width:640,height:460}); await expect.poll(()=>scale(page)).toBeLessThan(original);
  const fitted = await scale(page);
  await page.locator('.image-viewer-stage').evaluate(stage => {
    stage.dispatchEvent(new Event('gesturestart', {cancelable:true}));
    const event = new Event('gesturechange', {cancelable:true}); Object.defineProperty(event,'scale',{value:2}); stage.dispatchEvent(event);
    stage.dispatchEvent(new Event('gestureend', {cancelable:true}));
  });
  await expect.poll(()=>scale(page)).toBeGreaterThan(fitted * 1.8);
  await page.evaluate(()=>setModal('Test','Test body')); await expect(viewer(page)).toBeHidden();
  await expect(page.locator('#modalOverlay')).toBeVisible();
  expect(await page.locator('#modalOverlay').evaluate(n=>n.inert)).toBe(false);
});
test('network timeout recovers focus, image deletion closes viewer', async ({ page }) => {
  await page.clock.install();
  await page.route('**/never-viewer.png', route=>new Promise(()=>{}));
  await load(page,'<img src="http://127.0.0.1:29381/never-viewer.png" width="100" height="100">');
  await page.locator('#content img').dispatchEvent('click'); await expect(viewer(page)).toBeVisible();
  await page.clock.fastForward(15001); await expect(viewer(page)).toBeHidden(); await expect(page.locator('#status')).toContainText('无法预览');
  await load(page,diagram); await page.locator('#content .mermaid-diagram').dispatchEvent('click'); await expect(viewer(page)).toBeVisible();
  await page.locator('#content .mermaid-diagram').evaluate(n=>n.remove()); await expect(viewer(page)).toBeHidden();
});
test('large Mermaid opens promptly and burst wheel updates are coalesced', async ({ page }, info) => {
  await load(page,'```mermaid\nflowchart TD\n'+Array.from({length:80},(_,i)=>`N${i}[节点 ${i}] --> N${i+1}`).join('\n')+'\n```');
  const result = await page.evaluate(async()=>{
    const started=performance.now(); document.querySelector('#content .mermaid-diagram').dispatchEvent(new MouseEvent('click',{bubbles:true}));
    await new Promise(requestAnimationFrame); const openMs=performance.now()-started;
    const surface=document.querySelector('.image-viewer-surface'); let updates=0;
    const observer=new MutationObserver(records=>updates+=records.length); observer.observe(surface,{attributes:true});
    const stage=document.querySelector('.image-viewer-stage'); const t=performance.now();
    for(let i=0;i<1000;i++) stage.dispatchEvent(new WheelEvent('wheel',{deltaY:i%2?-2:2,cancelable:true,clientX:500,clientY:300}));
    await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame); observer.disconnect();
    return {openMs,burstMs:performance.now()-t,updates,transform:surface.style.transform};
  });
  expect(result.openMs).toBeLessThan(2500); expect(result.burstMs).toBeLessThan(2500); expect(result.updates).toBeLessThan(15);
  expect(result.transform).not.toMatch(/NaN|Infinity/);
  await info.attach('large-diagram-performance',{body:JSON.stringify(result),contentType:'application/json'});
  await page.keyboard.press('Escape');
});
test('sequence and class diagrams preserve native SVG labels', async ({page})=>{
  for(const md of ['```mermaid\nsequenceDiagram\n Alice->>Bob: Hello\n Bob-->>Alice: Done\n```','```mermaid\nclassDiagram\n class Animal\n Animal : +eat()\n```']) {
    await load(page,md); await page.locator('#content .mermaid-diagram').click(); await expect(viewer(page)).toBeVisible();
    const labels=await page.locator('.image-viewer-surface svg text').allTextContents(); expect(labels.join(' ')).toMatch(/Alice|Animal/);
    await page.keyboard.press('Escape'); expect(await page.evaluate(()=>getCurrentMarkdown())).toBe(md);
  }
});
test('selection and scroll survive keyboard close; print hides viewer', async ({ page }) => {
  await load(page,'Selected text\n\n'+imageMD());
  await page.evaluate(()=>{const p=document.querySelector('#content p'); const range=document.createRange();range.selectNodeContents(p);getSelection().removeAllRanges();getSelection().addRange(range);document.getElementById('content').focus();});
  await page.locator('#content img').dispatchEvent('click'); await expect(viewer(page)).toBeVisible();
  await page.emulateMedia({media:'print'}); await expect(viewer(page)).toBeHidden();
  await page.emulateMedia({media:'screen'}); await page.keyboard.press('Escape');
  expect(await page.evaluate(()=>getSelection().toString())).toBe('Selected text');
});
