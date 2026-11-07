#!/usr/bin/env node
/*
 * Quality gate for the rendered-mode code-block language badge (mdPreview).
 *
 * Loads the REAL index.html + marked.min.js + app.js inside jsdom and drives
 * the actual render pipeline (appendParsedMarkdown -> finalizeRenderedMarkdown)
 * with hand-written markdown, then asserts:
 *   - `text` blocks: NO badge, NO token coloring (plain text only).
 *   - non-text blocks (sql/js/python/...): a `.code-lang-label` badge showing
 *     the canonical language, marked contenteditable=false + aria-hidden so it
 *     is never captured by a text selection / copy of the code.
 *   - empty-language fences: no badge.
 *   - the badge is a direct child of <pre> (the gray background), not inside
 *     <code>, so selecting/copying the code excludes it.
 *
 * Run:
 *   <node> tests/test_code_block_badge.js
 */
'use strict';

const { JSDOM } = require('jsdom');
const fs = require('fs');
const path = require('path');

const REPO = path.resolve(__dirname, '..');

let passed = 0;
let failed = 0;
const failures = [];

function ok(cond, name, detail) {
  if (cond) { passed++; console.log('  PASS  ' + name); }
  else { failed++; failures.push(name + (detail ? ' :: ' + detail : '')); console.log('  FAIL  ' + name + (detail ? ' :: ' + detail : '')); }
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

(async () => {
  const htmlSrc = fs.readFileSync(path.join(REPO, 'index.html'), 'utf8');
  const dom = new JSDOM(htmlSrc, {
    runScripts: 'dangerously',
    resources: 'usable',
    pretendToBeVisual: true,
    url: 'file://' + REPO + '/index.html',
    beforeParse(window) {
      window.matchMedia = window.matchMedia || function (q) {
        return { matches: false, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} };
      };
    },
  });
  const { window } = dom;
  const doc = window.document;

  let ready = false;
  for (let i = 0; i < 150; i++) {
    if (typeof window.appendParsedMarkdown === 'function' &&
        typeof window.finalizeRenderedMarkdown === 'function' &&
        typeof window.marked !== 'undefined') { ready = true; break; }
    await sleep(100);
  }
  if (!ready) { console.error('FATAL: app.js did not load in jsdom'); process.exit(1); }

  function render(md) {
    const container = doc.createElement('div');
    window.appendParsedMarkdown(md, container);
    window.finalizeRenderedMarkdown(container, md);
    return container;
  }

  // ── 1. `text` block: no badge, no token colors, plain text preserved ──
  console.log('\n[1] text block');
  {
    const md = '```text\nSELECT * FROM users WHERE id = 1;\n```';
    const c = render(md);
    const code = c.querySelector('pre code');
    ok(!!code, 'code element present');
    ok(code.classList.contains('syntax-lang-text'), 'text class applied', code.className);
    ok(!c.querySelector('.code-lang-label'), 'NO language badge for text');
    ok(code.querySelectorAll('.tok').length === 0, 'NO token spans for text', 'toks=' + code.querySelectorAll('.tok').length);
    ok(/SELECT \* FROM users WHERE id = 1;/.test(code.textContent), 'source text preserved verbatim');
  }

  // ── 2. `sql` block: badge "sql", tokens colored, non-selectable attributes ──
  console.log('\n[2] sql block');
  {
    const md = '```sql\nSELECT * FROM users WHERE id = 1;\n```';
    const c = render(md);
    const code = c.querySelector('pre code');
    ok(code.classList.contains('language-sql'), 'sql class present', code.className);
    const label = c.querySelector('.code-lang-label');
    ok(!!label, 'language badge present');
    ok(label && label.textContent === 'sql', 'badge text is "sql"', label && label.textContent);
    ok(label && label.getAttribute('contenteditable') === 'false', 'badge is contenteditable=false');
    ok(label && label.getAttribute('aria-hidden') === 'true', 'badge is aria-hidden');
    ok(code.querySelectorAll('.tok').length > 0, 'tokens colored for sql', 'toks=' + code.querySelectorAll('.tok').length);
  }

  // ── 3. empty-language fence: no badge ──
  console.log('\n[3] plain fence (no language)');
  {
    const md = '```\nsome plain code line\n```';
    const c = render(md);
    ok(!!c.querySelector('pre code'), 'code present');
    ok(!c.querySelector('.code-lang-label'), 'no badge when language is empty');
  }

  // ── 4. multiple languages -> canonical badge label ──
  console.log('\n[4] language aliases map to canonical badge label');
  {
    const cases = [
      ['js', 'javascript'],
      ['jsx', 'javascript'],
      ['ts', 'typescript'],
      ['py', 'python'],
      ['python', 'python'],
      ['json', 'json'],
      ['yaml', 'yaml'],
      ['yml', 'yaml'],
      ['bash', 'shell'],
      ['sh', 'shell'],
      ['css', 'css'],
      ['html', 'html'],
      ['sql', 'sql'],
    ];
    for (const [fence, lang] of cases) {
      const c = render('```' + fence + '\nfoo bar baz\n```');
      const label = c.querySelector('.code-lang-label');
      ok(label && label.textContent === lang, '```' + fence + ' -> "' + lang + '"', label && label.textContent);
    }
  }

  // ── 5. badge placement: direct child of <pre>, not inside <code> ──
  console.log('\n[5] badge placement');
  {
    const md = '```sql\nSELECT 1;\n```';
    const c = render(md);
    const pre = c.querySelector('pre');
    const label = c.querySelector('.code-lang-label');
    ok(label && label.parentElement === pre, 'badge is a direct child of <pre> (gray background)');
    ok(label && !label.closest('code'), 'badge is NOT inside <code> (so copying code excludes it)');
  }

  // ── 6. badge must not appear twice if the pipeline runs again on new content ──
  console.log('\n[6] no duplicate badges across re-renders');
  {
    const c1 = render('```sql\nSELECT 1;\n```');
    ok(c1.querySelectorAll('.code-lang-label').length === 1, 'exactly one badge for a single sql block');
    // Re-render into a fresh container (simulating a reload) should also be one.
    const c2 = render('```python\nprint(1)\n```');
    ok(c2.querySelectorAll('.code-lang-label').length === 1, 'exactly one badge after re-render');
  }

  // ── 7. CSS guarantees the badge is non-selectable + pinned top-right ──
  console.log('\n[7] CSS contract for the badge');
  {
    const css = ['tokens', 'content', 'app', 'print'].map(name => fs.readFileSync(path.join(REPO, 'css', name + '.css'), 'utf8')).join('\n');
    ok(/\.markdown pre\s*\{[^}]*position:\s*relative/.test(css), 'pre is position:relative (anchors absolute badge)');
    ok(/\.markdown pre\s+code\s*\{[^}]*display:\s*block/.test(css), 'pre>code is display:block (scroller, keeps badge pinned)');
    ok(/\.markdown pre \.code-lang-label\s*\{[^}]*position:\s*absolute/.test(css), 'badge is position:absolute');
    ok(/\.markdown pre \.code-lang-label\s*\{[^}]*user-select:\s*none/.test(css), 'badge has user-select:none (non-selectable)');
    ok(/\.markdown pre \.code-lang-label\s*\{[^}]*pointer-events:\s*none/.test(css), 'badge has pointer-events:none');
    ok(/@media print[\s\S]*?\.code-lang-label[^{}]*\{\s*display:\s*none/.test(css), 'badge hidden in print');
    ok(/prefers-color-scheme:\s*dark[\s\S]*?\.markdown pre \.code-lang-label\s*\{\s*color:\s*var\(--dark-15\)/.test(css) && /--dark-15:\s*rgba\(255,\s*255,\s*255/.test(css), 'badge has a dark-mode color');
  }

  console.log('\n==== ' + passed + ' passed, ' + failed + ' failed ====');
  if (failures.length) { console.log('FAILURES:'); failures.forEach(f => console.log('  - ' + f)); }
  process.exit(failed ? 1 : 0);
})();
