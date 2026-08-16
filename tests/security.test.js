#!/usr/bin/env node
/* Release-gate security suite: hostile markdown through the REAL render
   pipeline must never leave executable content in the DOM, while legitimate
   content (data:image, relative images, normal links) is preserved. */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const appJs = fs.readFileSync(path.join(root, 'app.js'), 'utf8');
const markedJs = fs.readFileSync(path.join(root, 'marked.min.js'), 'utf8');

const dom = new JSDOM(html, { runScripts: 'outside-only', pretendToBeVisual: true });
const { window } = dom;
window.matchMedia = window.matchMedia || (() => ({ matches: false, addEventListener() {}, addListener() {} }));
window.eval(markedJs);
window.eval('const _loadScript = () => Promise.resolve();');
window.pywebview = {
  api: {
    get_initial_content: () => Promise.resolve({ path: '/tmp/x.md', content: '', pageWidth: 720, draftRecovered: false, isZh: false }),
    set_dirty: () => Promise.resolve({}),
    store_content: () => Promise.resolve({}),
    reset_to_untitled: () => Promise.resolve({}),
    native_save_prompt: () => Promise.resolve(nativePromptResult),
    save_file: (p, c) => { savedPath = p; saveCalls.push(c); return Promise.resolve({ success: true }); },
    force_close_window: (d) => { forceCalls.push(!!d); return Promise.resolve({ success: true }); },
  },
};

let nativePromptResult = null;
let savedPath = null;
const saveCalls = [];
const forceCalls = [];
window.eval(appJs);
window.dispatchEvent(new window.Event('pywebviewready'));

let pass = 0, fail = 0;
function check(name, cond) {
  if (cond) { pass++; console.log('PASS ' + name); }
  else { fail++; console.log('FAIL ' + name); }
}

const HOSTILE = `<img src=x onerror=alert(1)>
<svg onload=alert(2)></svg>
<iframe src="https://evil.com"></iframe>
<object data="x"></object>
<embed src="x">
<script>alert(9)</script>
<link rel="stylesheet" href="https://evil.com/x.css">
<form action="https://evil.com"><input name="x"></form>

[js](javascript:alert(4))
[bad-href](data:text/html;base64,PHNjcmlwdD4=)
![bad](data:text/html;base64,PHNjcmlwdD4=)
![f](file:///etc/passwd)
[file](file:///etc/hosts)
<img src="JaVaScRiPt:alert(5)">`;

const SAFE = `# T

![img](data:image/png;base64,iVBORw0KGgo=)
![rel](./pic.png)
[ok](https://example.com)
**bold** and *italic*`;

setTimeout(async () => {
  const el = window.document.getElementById('content');

  // ── Hostile content must be neutralized ──
  await window.renderMarkdown(HOSTILE, el);
  const q = (s) => el.querySelectorAll(s).length;
  check('no event handlers survive', q('[onerror]') === 0 && q('[onload]') === 0 && q('[onclick]') === 0 && q('[onmouseover]') === 0);
  check('no active elements survive', q('script') === 0 && q('iframe') === 0 && q('object') === 0 && q('embed') === 0 && q('svg') === 0 && q('link') === 0 && q('style') === 0 && q('form') === 0);
  check('no javascript:/data:text/html/file: hrefs', q('a[href*="javascript:"]') === 0 && q('a[href*="data:text/html"]') === 0 && q('a[href*="file:"]') === 0);
  check('no hostile img srcs', q('img[src*="/etc/passwd"]') === 0 && q('img[src*="data:text/html"]') === 0 && q('img[src*="javascript:"]') === 0);
  // javascript:/data: links, if rendered as anchors at all, must be neutralized to "#"
  const badAnchors = Array.from(el.querySelectorAll('a')).filter(a => /^\s*(?:javascript:|vbscript:|data:(?!image\/)|file:)/i.test(a.getAttribute('href') || '')).length;
  check('no active-dangerous anchors survive', badAnchors === 0);

  // ── Legitimate content must survive ──
  await window.renderMarkdown(SAFE, el);
  const q2 = (s) => el.querySelectorAll(s).length;
  check('data:image preserved (legit feature)', q2('img[src*="data:image"]') === 1);
  check('relative image rewrite preserved (legit feature)', q2('img[src*="pic.png"]') === 1);
  check('normal https link preserved', q2('a[href*="https://example.com"]') === 1);
  check('normal content survives', q2('h1') === 1 && q2('strong') === 1);

  // ── Blank-document reset must clear the previous document's TOC ──
  // Regression: closing the last document and reopening via Dock showed the
  // previous file's outline on the blank Untitled document.
  await window.renderMarkdown('# A\n\n## B\n\n### C\n\nbody', el);
  await new Promise((r) => setTimeout(r, 250)); // deferred TOC build
  const toc = window.document.getElementById('tocSidebar');
  const toggle = window.document.getElementById('tocToggle');
  const tocBefore = toc.querySelectorAll('a').length;
  window.convertToBlankDocument();
  await new Promise((r) => setTimeout(r, 50));
  check('TOC built before blank (3 items)', tocBefore === 3);
  check('TOC cleared after blank', toc.querySelectorAll('a').length === 0);
  check('TOC hidden after blank', toc.classList.contains('hidden'));
  check('layout restored (no has-toc)', !window.document.body.classList.contains('has-toc'));
  check('TOC toggle hidden after blank', toggle.style.display === 'none');

  // ── New documents default to Source mode; the hint shows only there ──
  const sourceEl = window.document.getElementById('source');
  const contentEl = window.document.getElementById('content');
  await window.loadContent('/tmp/newdoc.md', '# Title\n\nbody', 720, false, false);
  await new Promise((r) => setTimeout(r, 250)); // allow hint fadeout from blank state
  check('opened doc starts in Preview mode', !sourceEl.classList.contains('visible') && !contentEl.classList.contains('hidden'));
  check('no hint overlay on non-empty doc', !window.document.getElementById('welcomeOverlay'));

  await window.loadContent('Untitled.md', '', 720, false, false);
  check('blank doc starts in Source mode', sourceEl.classList.contains('visible'));
  const hint = window.document.getElementById('welcomeOverlay');
  check('empty-doc hint shows in Source mode', !!hint);
  check('hint uses keycap style and says preview', !!hint && /<kbd>/.test(hint.innerHTML) && /to preview/.test(hint.innerHTML));
  check('hint no longer uses literal CMD E text', !!hint && !/CMD E to preview/.test(hint.innerHTML));
  check('hint no longer says toggle source', !!hint && !/toggle source/.test(hint.innerHTML) && !/切换源码/.test(hint.innerHTML));

  await window.toggleView();
  await new Promise((r) => setTimeout(r, 250));
  check('Preview mode hides the hint', !window.document.getElementById('welcomeOverlay'));
  check('Preview mode shows rendered content only', !sourceEl.classList.contains('visible') && !contentEl.classList.contains('hidden'));

  // ── Source-mode highlight must follow fast typing (no transparent text) ──
  // Regression: fast typing showed invisible text because the highlight layer
  // (which paints the colors under the transparent-text textarea) waited on a
  // 120ms debounce. It must re-sync on the next animation frame instead.
  const textarea = window.document.getElementById('textarea');
  const layer = window.document.getElementById('highlightLayer');
  await window.loadContent('Untitled.md', '', 720, false, false);
  const t0 = Date.now();
  for (let i = 0; i < 10; i++) {
    textarea.value = textarea.value + 'x';
    textarea.dispatchEvent(new window.Event('input'));
    await new Promise((r) => setTimeout(r, 5));
  }
  await new Promise((r) => setTimeout(r, 30)); // allow one rAF frame
  const fastElapsed = Date.now() - t0;
  const layerText = layer.textContent || '';
  check('fast typing is highlighted quickly', layerText.includes('xxxxxxxxxx') && fastElapsed < 160);

  // ── New blank doc: caret auto-focuses; hint hides only when typing ──
  await window.loadContent('Untitled.md', '', 720, false, false);
  await new Promise((r) => setTimeout(r, 50));
  const ta2 = window.document.getElementById('textarea');
  const hintGet = () => window.document.getElementById('welcomeOverlay');
  check('new doc auto-focuses the source textarea', window.document.activeElement === ta2);
  check('hint stays while caret is placed (no typing)', !!hintGet());
  if (hintGet()) hintGet().click();
  await new Promise((r) => setTimeout(r, 30));
  check('hint click does not dismiss it (only typing does)', !!hintGet());
  ta2.value = 'typed';
  ta2.dispatchEvent(new window.Event('input'));
  await new Promise((r) => setTimeout(r, 250));
  check('hint dismissed once typing starts', !hintGet());

  // ── Native save prompt flow: save / delete / cancel ──
  window.convertToBlankDocument();
  await new Promise((r) => setTimeout(r, 50));
  const ta3 = window.document.getElementById('textarea');
  ta3.value = '# draft';
  ta3.dispatchEvent(new window.Event('input'));
  nativePromptResult = { action: 'save', path: '/Users/t/Desktop/note.md' };
  await window.promptBeforeClose(true);
  await new Promise((r) => setTimeout(r, 100));
  check('save: writes to the path chosen in the native dialog', savedPath === '/Users/t/Desktop/note.md');
  check('save: closes the window after saving', forceCalls.length === 1 && forceCalls[0] === false);

  forceCalls.length = 0;
  nativePromptResult = { action: 'delete' };
  await window.promptBeforeClose(true);
  await new Promise((r) => setTimeout(r, 100));
  check('delete: discards and closes (force close, discard=true)', forceCalls.length === 1 && forceCalls[0] === true);

  forceCalls.length = 0;
  saveCalls.length = 0;
  nativePromptResult = { action: 'cancel' };
  await window.promptBeforeClose(true);
  await new Promise((r) => setTimeout(r, 100));
  check('cancel: neither saves nor closes', forceCalls.length === 0 && saveCalls.length === 0);

  window.close();
  console.log(`\nSECURITY SUITE: ${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
}, 500);
