#!/usr/bin/env node
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const indexHtml = fs.readFileSync(path.join(root, 'app.js'), 'utf8');
const stylesCss = fs.readFileSync(path.join(root, 'styles.css'), 'utf8');

function extractFunctionSource(name) {
  const start = indexHtml.indexOf('function ' + name);
  assert(start >= 0, `Function ${name} not found`);
  let i = indexHtml.indexOf('{', start);
  assert(i >= 0, `Function ${name} body not found`);
  let depth = 0;
  for (let j = i; j < indexHtml.length; j++) {
    if (indexHtml[j] === '{') depth += 1;
    else if (indexHtml[j] === '}') {
      depth -= 1;
      if (depth === 0) return indexHtml.slice(start, j + 1);
    }
  }
  throw new Error(`Function ${name} closing brace not found`);
}

const fnSource = [
  extractFunctionSource('renderFrontmatter'),
  extractFunctionSource('resolveBlockScalar'),
  extractFunctionSource('highlightInlineMarkdown'),
  extractFunctionSource('highlightMarkdown'),
  extractFunctionSource('escHtml'),
  extractFunctionSource('slugifyHeading'),
  extractFunctionSource('preprocessMarkdownExtensions'),
  extractFunctionSource('splitMarkdownForFirstScreen'),
  extractFunctionSource('containsMermaidFence'),
  extractFunctionSource('hasRenderableMermaid'),
  extractFunctionSource('isBlockedHref'),
  extractFunctionSource('isExternalHref'),
  extractFunctionSource('t'),
  extractFunctionSource('findNonEditableAncestor'),
  extractFunctionSource('showEditHint'),
  extractFunctionSource('applyFontSize'),
  extractFunctionSource('zoomIn'),
  extractFunctionSource('zoomOut'),
  extractFunctionSource('sanitizeHtmlString'),
].join('\n');

const moduleFactory = new Function(`const FIRST_SCREEN_MARKDOWN_CHARS = 18000;\nlet isZh = false;\nlet editHintTimer = null;\nlet contentFontSize = 16;\nconst FONT_MIN = 12;\nconst FONT_MAX = 24;\nconst FONT_STEP = 1;\nlet lastStatus = '';\nconst showStatus = (text) => { lastStatus = text; };\n${fnSource}\nreturn { renderFrontmatter, resolveBlockScalar, highlightMarkdown, escHtml, slugifyHeading, preprocessMarkdownExtensions, splitMarkdownForFirstScreen, containsMermaidFence, hasRenderableMermaid, isBlockedHref, isExternalHref, t, findNonEditableAncestor, showEditHint, zoomIn, zoomOut, applyFontSize, sanitizeHtmlString, setZh: (v) => { isZh = v; }, resetZoom: () => { contentFontSize = 16; }, getLastStatus: () => lastStatus };`);
const { renderFrontmatter, highlightMarkdown, slugifyHeading, preprocessMarkdownExtensions, splitMarkdownForFirstScreen, containsMermaidFence, hasRenderableMermaid, isBlockedHref, isExternalHref, t, findNonEditableAncestor, showEditHint, zoomIn, zoomOut, applyFontSize, sanitizeHtmlString, setZh, resetZoom, getLastStatus } = moduleFactory();

function test(name, fn) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (err) {
    console.error(`FAIL ${name}`);
    console.error(err.stack || err.message);
    process.exitCode = 1;
  }
}

test('frontmatter folded block scalar >- hides indicator and folds newlines', () => {
  const input = 'description: >-\n  line one\n  line two\nflag: true';
  const out = renderFrontmatter(input);
  assert(out.includes('description: line one line two'));
  assert(out.includes('flag: true'));
  assert(!out.includes('>-'));
});

test('frontmatter literal block scalar | preserves newlines and hides indicator', () => {
  const input = 'body: |\n  a\n  b\nflag: true';
  const out = renderFrontmatter(input);
  assert(out.includes('body: a\nb\n'));
  assert(out.includes('flag: true'));
  assert(!out.includes('body: |'));
});

test('frontmatter strip chomping |- removes final scalar newline', () => {
  const input = 'body: |-\n  a\n  b\nflag: true';
  const out = renderFrontmatter(input);
  assert(out.includes('body: a\nb\nflag: true'));
});

test('source highlight treats * * * as one horizontal rule', () => {
  const out = highlightMarkdown('* * *');
  assert.strictEqual(out, '<span class="syn-hr">* * *</span>');
});

test('source highlight treats *** and - - - as horizontal rules', () => {
  assert.strictEqual(highlightMarkdown('***'), '<span class="syn-hr">***</span>');
  assert.strictEqual(highlightMarkdown('- - -'), '<span class="syn-hr">- - -</span>');
});

test('source highlight does not confuse list items with horizontal rules', () => {
  assert.strictEqual(highlightMarkdown('* item'), '<span class="syn-list">*</span> item');
  assert.strictEqual(highlightMarkdown('- item'), '<span class="syn-list">-</span> item');
});

test('heading slugs support English and CJK text', () => {
  assert.strictEqual(slugifyHeading('Hello World!'), 'hello-world');
  assert.strictEqual(slugifyHeading('目录 标题 1'), '目录-标题-1');
});

test('link classifier blocks executable inline hrefs', () => {
  assert.strictEqual(isBlockedHref('javascript:alert(1)'), true);
  assert.strictEqual(isBlockedHref('data:text/html,hi'), true);
  assert.strictEqual(isBlockedHref('#intro'), false);
});

test('link classifier opens any explicit URI scheme externally', () => {
  assert.strictEqual(isExternalHref('https://example.com'), true);
  assert.strictEqual(isExternalHref('mailto:test@example.com'), true);
  assert.strictEqual(isExternalHref('file:///tmp/a.md'), true);
  assert.strictEqual(isExternalHref('custom-scheme://open'), true);
  assert.strictEqual(isExternalHref('#intro'), false);
  assert.strictEqual(isExternalHref('relative.md'), false);
});

test('source highlight skips markdown inside fenced code blocks', () => {
  const out = highlightMarkdown('```\n# not heading\n**not bold**\n```');
  assert(out.includes('# not heading'));
  assert(out.includes('**not bold**'));
  assert(!out.includes('syn-heading">#'));
  assert(!out.includes('syn-bold'));
});

test('source highlight supports frontmatter ellipsis terminator', () => {
  const out = highlightMarkdown('---\ntitle: Test\n...\n# Heading');
  assert(out.includes('<span class="syn-codeblock">...</span>'));
  assert(out.includes('<span class="syn-heading">#</span> Heading'));
});

test('markdown extension preprocessor extracts footnotes and math blocks', () => {
  const result = preprocessMarkdownExtensions('Text[^1]\n\n[^1]: note text\n\n$$a+b$$');
  assert.strictEqual(result.footnotes.length, 1);
  assert.strictEqual(result.footnotes[0].id, '1');
  assert.strictEqual(result.footnotes[0].text, 'note text');
  assert.strictEqual(result.mathBlocks[0], 'a+b');
  assert(result.body.includes('@@MATH_BLOCK_0@@'));
});

test('first-screen splitter stages large markdown at a safe boundary', () => {
  const md = Array.from({ length: 1200 }, (_, i) => `## Heading ${i}\n\nParagraph ${i}`).join('\n\n');
  const split = splitMarkdownForFirstScreen(md);
  assert.strictEqual(split.staged, true);
  assert(split.first.length > 9000, 'first chunk should contain visible first screens');
  assert(split.rest.length > 0, 'remaining content should be deferred');
  assert.strictEqual(split.first + split.rest, md, 'split must be lossless');
});

test('small markdown renders without staging', () => {
  const split = splitMarkdownForFirstScreen('# Short\n\nContent');
  assert.strictEqual(split.staged, false);
  assert.strictEqual(split.rest, '');
});

test('Mermaid preloading detects only Mermaid fences including spaced info strings', () => {
  assert.strictEqual(containsMermaidFence('plain text says graph TD but is not fenced'), false);
  assert.strictEqual(containsMermaidFence('```js\ngraph TD\n```'), false);
  assert.strictEqual(containsMermaidFence('```mermaid\ngraph TD\nA-->B\n```'), true);
  assert.strictEqual(containsMermaidFence('``` mermaid\ngraph TD\nA-->B\n```'), true);
  assert.strictEqual(containsMermaidFence('~~~ mermaid\nsequenceDiagram\n~~~'), true);
});

test('DOM Mermaid detection follows currently renderable code blocks', () => {
  const calls = [];
  const root = { querySelector: (selector) => { calls.push(selector); return selector === 'code.language-mermaid' ? {} : null; } };
  assert.strictEqual(hasRenderableMermaid(root), true);
  assert.deepStrictEqual(calls, ['code.language-mermaid']);
  assert.strictEqual(hasRenderableMermaid(null), false);
});

test('render pipeline defers TOC and Mermaid after first paint', () => {
  assert(indexHtml.includes('const FIRST_SCREEN_MARKDOWN_CHARS = 18000'), 'first-screen threshold missing');
  assert(indexHtml.includes('function scheduleDeferredEnhancements'), 'deferred enhancement scheduler missing');
  assert(indexHtml.includes('buildToc(container);\n      if (hasRenderableMermaid(container))'), 'TOC must build before DOM-gated Mermaid enhancement');
  assert(indexHtml.includes('requestAnimationFrame(() => {\n        setTimeout(() => {'), 'full document must render after first paint');
  assert(indexHtml.includes('appendParsedMarkdown(content, container, { keepExisting: false })'), 'deferred pass must reparse the full document for correctness');
  assert(!indexHtml.includes("content.includes('graph") && !indexHtml.includes('content.includes("graph'), 'ordinary graph text must not trigger Mermaid');
});


test('TOC layout: page hugs sidebar right edge and centers on full window when wide enough', () => {
  // Requirement: with TOC open, content centers relative to the FULL window width.
  // When centering would overlap the 200px sidebar, left edge stays pinned at 200px
  // and growth only happens on the right; once (vw - 720px)/2 >= 200px it centers.
  const hasTocRule = stylesCss.match(/body\.has-toc \.page \{[^}]+\}/);
  assert(hasTocRule, 'body.has-toc .page rule missing');
  const rule = hasTocRule[0];
  assert(rule.includes('margin-left: max(200px, calc((100vw - var(--page-width, 720px)) / 2))'),
    'margin-left must max(200px, (100vw - page-width)/2) for full-window centering with degradation');
  assert(rule.includes('width: min(var(--page-width, 720px), calc(100vw - 200px))'),
    'width must cap at page-width and never exceed viewport minus sidebar');
  assert(rule.includes('margin-right: auto'), 'margin-right auto absorbs remaining space');
});

test('save flow handles external modification conflicts', () => {
  assert(indexHtml.includes('function showSaveConflictDialog(path, markdown, options = {})'), 'conflict dialog function missing');
  assert(indexHtml.includes("result.conflict"), 'save result conflict branch missing');
  assert(indexHtml.includes("save_file(filePath, markdown, !!force)"), 'save must pass force flag to native API');
  assert(indexHtml.includes("await saveFile(true, markdown)"), 'overwrite action must force save current content');
  assert(indexHtml.includes("await saveAsFile(markdown)"), 'conflict Save As must preserve current markdown');
  assert(indexHtml.includes("Save Current"), 'overwrite label missing');
  assert(indexHtml.includes("Save cancelled"), 'cancel branch missing');
});

test('modal supports reusable headers and actions', () => {
  assert(indexHtml.includes('function setModal(title, bodyHtml, actionsHtml)'), 'setModal helper missing');
  assert(indexHtml.includes('modalHeader'), 'modal header hook missing');
  assert(indexHtml.includes('modalActions'), 'modal action hook missing');
});

test('dirty close flow prompts before closing', () => {
  assert(indexHtml.includes('function promptBeforeClose(force = false)'), 'close prompt function missing');
  assert(indexHtml.includes('Save Changes?'), 'close prompt title missing');
  assert(indexHtml.includes('closeCancel'), 'close cancel action missing');
  assert(indexHtml.includes('closeDiscard'), 'close discard action missing');
  assert(indexHtml.includes('closeSave'), 'close save action missing');
  assert(indexHtml.includes('force_close_window'), 'confirmed close must call native force close');
  assert(indexHtml.includes('await forceCloseWindow(true)'), 'discard close must tell native side to drop drafts');
  assert(indexHtml.includes('if (isDirty) {\n      promptBeforeClose();\n      return;\n    }'), 'closeWindow must prompt when dirty');
  assert(indexHtml.includes('closeOnSuccess: true'), 'close save must close only after successful save');
});

test('close-conflict combined flow keeps window open until resolved', () => {
  assert(indexHtml.includes('const result = await saveFile(false, null, { closeOnSuccess: true })'),
    'close Save must use close-aware save flow');
  assert(indexHtml.includes('showSaveConflictDialog(result.path || filePath, markdown, options)'),
    'save conflict must preserve close flow options');
  assert(indexHtml.includes('if (options.closeOnSuccess && result && result.saved) await forceCloseWindow()'),
    'conflict Save As/Overwrite must close only after successful save');
  assert(!indexHtml.includes('if (result.conflict) await forceCloseWindow'),
    'window must not close immediately on conflict');
});

test('save functions return status for close prompt flow', () => {
  assert(indexHtml.includes('return { saved: true }'), 'save success status missing');
  assert(indexHtml.includes('return { saved: false, cancelled: true }'), 'save cancel status missing');
  assert(indexHtml.includes('return { saved: false, conflict: true }'), 'save conflict status missing');
});

test('prepareForClose stops timers and guards bridge calls', () => {
  // The native side calls prepareForClose() during window closing; it must
  // cancel every timer and prevent new JS->Python bridge traffic so teardown
  // cannot deadlock on an in-flight non-daemon bridge thread.
  assert(indexHtml.includes('function prepareForClose()'), 'prepareForClose missing');
  assert(indexHtml.includes('closing = true'), 'closing flag not set in prepareForClose');
  assert(indexHtml.includes('clearTimeout(pythonSyncTimer)'), 'python sync timer not cleared');
  assert(indexHtml.includes('clearTimeout(highlightTimer)'), 'highlight timer not cleared');
  assert(indexHtml.includes('clearTimeout(statusTimer)'), 'status timer not cleared');
  assert(indexHtml.includes('clearTimeout(deferredRenderTimer)'), 'deferred render timer not cleared');
  assert(indexHtml.includes('clearInterval(keepAliveTimer)'), 'keep-alive interval not cleared');
  assert(indexHtml.includes('if (closing) return;'), 'pushContentToPython not guarded by closing');
  assert(indexHtml.includes('if (closing) return;'), 'schedulePythonSync not guarded by closing');
  assert(/keepAliveTimer = setInterval\(\(\) => \{ if \(!closing && isSource\)/.test(indexHtml),
    'keep-alive interval must be cancelled and guarded by closing');
});

// ── Bilingual helper ──
test('bilingual t() switches by isZh', () => {
  setZh(false);
  assert.strictEqual(t('Save', '保存'), 'Save');
  assert.strictEqual(t('Open File…', '打开文件…'), 'Open File…');
  setZh(true);
  assert.strictEqual(t('Save', '保存'), '保存');
  assert.strictEqual(t('Open File…', '打开文件…'), '打开文件…');
  setZh(false); // restore
});

// ── Non-editable click hint ──
test('non-editable ancestor detection walks up the DOM', () => {
  const content = { getAttribute: () => null };
  const ne = { getAttribute: (a) => (a === 'contenteditable' ? 'false' : null), parentNode: content };
  const leaf = { nodeType: 1, getAttribute: () => null, parentNode: ne };
  const before = global.document;
  global.document = { getElementById: (id) => (id === 'content' ? content : null), body: null };
  try {
    assert.strictEqual(findNonEditableAncestor(leaf), ne);
    assert.strictEqual(findNonEditableAncestor(content), null);
  } finally {
    global.document = before;
  }
});

test('edit hint bubble shows bilingual text and auto-hides after 1.6s', () => {
  const beforeDoc = global.document;
  const beforeWin = global.window;
  const timers = [];
  const origSetTimeout = global.setTimeout;
  const origClearTimeout = global.clearTimeout;
  global.setTimeout = (fn, ms) => { timers.push({ fn, ms }); return timers.length; };
  global.clearTimeout = () => {};
  global.window = { innerWidth: 800, innerHeight: 600 };
  const bubble = {
    textContent: '',
    innerHTML: '',
    style: {},
    offsetHeight: 36,
    classList: {
      add() {}, remove() {}, toggle() {},
    },
  };
  let added = false;
  let removed = false;
  const toggled = [];
  bubble.classList.add = () => { added = true; };
  bubble.classList.remove = () => { removed = true; };
  bubble.classList.toggle = (name, on) => { toggled.push([name, on]); };
  global.document = { getElementById: (id) => (id === 'editHintBubble' ? bubble : null) };
  const anchor = { getBoundingClientRect: () => ({ left: 100, top: 200, width: 50, height: 30, bottom: 230 }) };
  try {
    setZh(false);
    showEditHint(anchor);
    assert.strictEqual(bubble.innerHTML, '<span class="edit-hint-key">⌘E</span><span>to edit in Source</span>');
    assert.strictEqual(added, true, 'bubble should become visible');
    assert.strictEqual(timers.length, 1, 'one auto-hide timer scheduled');
    assert.strictEqual(timers[0].ms, 1600, 'auto-hide after 1600ms');
    setZh(true);
    showEditHint(anchor);
    assert.strictEqual(bubble.innerHTML, '<span class="edit-hint-key">⌘E</span><span>使用源码模式编辑</span>');
    timers[0].fn(); // fire the hide timer
    assert.strictEqual(removed, true, 'bubble hides after 1.6s');
  } finally {
    global.document = beforeDoc;
    global.window = beforeWin;
    global.setTimeout = origSetTimeout;
    global.clearTimeout = origClearTimeout;
    setZh(false);
  }
});

// ── Static wiring checks ──
test('index.html declares the edit hint bubble and bilingual strings are wired', () => {
  const realIndexHtml = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
  assert(realIndexHtml.includes('id="editHintBubble"'), 'edit hint bubble element missing');
  assert(indexHtml.includes('applyStaticUiLanguage'), 'static UI language updater missing');
  assert(indexHtml.includes('findNonEditableAncestor'), 'non-editable detection missing');
  assert(indexHtml.includes('showEditHint(ne)'), 'click handler must call showEditHint');
  assert(indexHtml.includes('t(\'Save\''), 'save status should be bilingual');
  assert(stylesCss.includes('.edit-hint-bubble'), 'edit hint bubble styles missing');
});

test('click handler excludes interactive elements but NOT contenteditable', () => {
  // Regression: putting [contenteditable="true"] in the exclusion list matched
  // #content itself (closest() walks up), silently disabling the hint for every
  // click — the bubble never appeared. Editable-vs-not is decided inside
  // findNonEditableAncestor instead.
  const m = indexHtml.match(/if \(!isSource && !e\.target\.closest\('([^']*)'\)\)/);
  assert(m, 'click guard not found');
  assert(!m[1].includes('contenteditable'), 'contenteditable must NOT be in the exclusion list');
  assert(m[1].includes('button'), 'interactive elements must still be excluded');
});

// ── Font size (⌘= / ⌘-) ──
test('font size steps ±1px and clamps within range', () => {
  const beforeDoc = global.document;
  let captured = null;
  global.document = { documentElement: { style: { setProperty: (k, v) => { captured = v; } } } };
  try {
    resetZoom();
    setZh(true);
    zoomIn();
    assert.strictEqual(captured, '17px', 'zoom in should increase font by 1px');
    assert.strictEqual(getLastStatus(), '字号 17px', 'status should show font size in Chinese');
    setZh(false);
    zoomIn();
    assert.strictEqual(getLastStatus(), 'Font 18px', 'english status');
    zoomIn(); // 19
    for (let i = 0; i < 20; i++) zoomOut();
    assert.strictEqual(captured, '12px', 'zoom out clamps at 12px');
    for (let i = 0; i < 20; i++) zoomIn();
    assert.strictEqual(captured, '24px', 'zoom in clamps at 24px');
  } finally {
    global.document = beforeDoc;
    resetZoom();
    setZh(false);
  }
});

test('keyboard wiring: zoom on ⌘= / ⌘-, width on ⌘. / ⌘,', () => {
  assert(/e\.key === '='/.test(indexHtml) && /zoomIn\(\)/.test(indexHtml), '⌘= must zoom in');
  assert(/e\.key === '-'/.test(indexHtml) && /zoomOut\(\)/.test(indexHtml), '⌘- must zoom out');
  assert(/e\.key === '\.'/.test(indexHtml) && /adjustPageWidth\(40\)/.test(indexHtml), '⌘. must increase width');
  assert(/e\.key === ','/.test(indexHtml) && /adjustPageWidth\(-40\)/.test(indexHtml), '⌘, must decrease width');
  assert(!/e\.key === ','[^]*?showPreferences/.test(indexHtml), '⌘, must no longer open preferences');
  assert(/zoomIn\(\)/.test(indexHtml) && /zoomOut\(\)/.test(indexHtml), 'zoom functions must exist');
});

test('edit hint bubble: no arrow, fixed centered-bottom, Apple HUD style', () => {
  const bubble = stylesCss.match(/\.edit-hint-bubble\s*\{[^}]*\}/);
  assert(bubble, 'edit-hint-bubble rule must exist');
  const rule = bubble[0];
  assert(/position:\s*fixed/.test(rule) && /left:\s*50%/.test(rule) && /bottom:\s*72px/.test(rule),
    'bubble must be fixed and centered near the bottom of the screen');
  assert(!/\.edit-hint-bubble::before/.test(stylesCss), 'bubble must not have an arrow (::before removed)');
  assert(!/\.above/.test(stylesCss), 'above/below anchor-following must be removed');
  assert(/backdrop-filter/.test(rule), 'bubble should use a frosted blur for the Apple look');
  const hintSrc = extractFunctionSource('showEditHint');
  assert(!hintSrc.includes('placeAbove'), 'showEditHint must not position relative to the anchor');
  assert(!hintSrc.includes('getBoundingClientRect'), 'showEditHint must not read anchor rect');
});

// ── Render-time sanitizer (stored-XSS defense) ──
test('sanitizer strips active tags, event handlers and unsafe URLs (string level)', () => {
  // Active elements removed entirely
  assert(!sanitizeHtmlString('<script>alert(1)</script><iframe src="https://e.com"></iframe><embed src="x"><object data="x"></object><link rel=stylesheet href="https://e.com/x.css"><svg onload=alert(2)></svg><style>body{}</style>').includes('<script'));
  assert(!sanitizeHtmlString('<iframe src="https://e.com"></iframe>').includes('iframe'));
  assert(!sanitizeHtmlString('<embed src="x">').includes('embed'));
  assert(!sanitizeHtmlString('<object data="x"></object>').includes('object'));
  assert(!sanitizeHtmlString('<link rel="stylesheet" href="https://e.com/x.css">').includes('link'));
  assert(!sanitizeHtmlString('<svg onload="alert(2)"></svg>').includes('svg'));
  assert(!sanitizeHtmlString('<style>body{background:url(javascript:1)}</style>').includes('<style'));
  // Event handlers stripped
  assert(!sanitizeHtmlString('<img src=x onerror=alert(1)>').includes('onerror'));
  assert(!sanitizeHtmlString('<button onclick="evil()">b</button>').includes('onclick'));
  assert(!sanitizeHtmlString('<div onmouseover="x">d</div>').includes('onmouseover'));
  // Dangerous hrefs neutralized to "#"
  assert(sanitizeHtmlString('<a href="javascript:alert(1)">x</a>').includes('href="#"'));
  assert(sanitizeHtmlString('<a href="data:text/html;base64,PHNjcmlwdD4=">x</a>').includes('href="#"'));
  assert(sanitizeHtmlString('<a href="file:///etc/passwd">x</a>').includes('href="#"'));
  assert(sanitizeHtmlString('<a href="vbscript:msgbox(1)">x</a>').includes('href="#"'));
  // Dangerous img src dropped entirely (not "#", which would be re-rewritten)
  assert(!sanitizeHtmlString('<img src="file:///etc/passwd">').includes('src'));
  assert(!sanitizeHtmlString('<img src="data:text/html;base64,PHNjcmlwdD4=">').includes('src'));
  assert(!sanitizeHtmlString('<img src="javascript:alert(1)">').includes('src'));
  // Safe forms preserved
  assert(sanitizeHtmlString('<img src="data:image/png;base64,iVBORw0KGgo=">').includes('data:image/png'));
  assert(sanitizeHtmlString('<a href="https://example.com">x</a>').includes('https://example.com'));
  assert(sanitizeHtmlString('<a href="./rel.md">x</a>').includes('./rel.md'));
  assert(sanitizeHtmlString('<a href="#anchor">x</a>').includes('#anchor'));
  // Normal text untouched
  assert(sanitizeHtmlString('<p>hello <strong>world</strong></p>') === '<p>hello <strong>world</strong></p>');
});

test('sanitizer survives hostile/malformed input without throwing', () => {
  const hostile = [
    '<img src=x onerror=alert(1)>',
    '<<script>>alert(1)</script>',
    '<svg><script>alert(1)</script></svg>',
    '<img src="data:text/html;base64,PHNjcmlwdD4=" onerror="x">',
    '<a href="JaVaScRiPt:alert(1)">x</a>',           // case-insensitive
    '<img SRC="FILE:///etc/passwd">',                  // mixed case attr
    '<img src=javascript:alert(1)>',                   // unquoted
    '<iframe srcdoc="<script>alert(1)</script>"></iframe>',
    '<img src=x onerror=alert(1) onload=alert(2) style="background:url(javascript:x)">',
    '',
    null,
    undefined,
  ];
  for (const input of hostile) {
    const out = sanitizeHtmlString(input);
    assert(typeof out === 'string', 'must return string for ' + JSON.stringify(input));
    assert(!/<script|javascript:|onerror|onload|srcdoc/i.test(out), 'must not retain active content for ' + JSON.stringify(input));
  }
});

if (process.exitCode) process.exit(process.exitCode);
console.log('All regression tests passed.');
