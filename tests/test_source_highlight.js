#!/usr/bin/env node
/*
 * Quality gate for source-mode syntax highlighting (mdPreview).
 *
 * Bug covered: single-underscore italic (_like this_) had no highlight rule,
 * while single-star italic (*like this*) did. The fix adds a single-underscore
 * rule that runs after the bold rule and must NOT match intraword underscores
 * (snake_case_words) or the __ of already-highlighted bold spans.
 *
 * Loads the REAL index.html + app.js inside jsdom and drives the actual
 * highlightMarkdown / highlightInlineMarkdown functions.
 *
 * Run:
 *   <node> tests/test_source_highlight.js
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

  let ready = false;
  for (let i = 0; i < 100; i++) {
    if (typeof window.highlightMarkdown === 'function' && typeof window.marked !== 'undefined') { ready = true; break; }
    await sleep(100);
  }
  if (!ready) { console.error('FATAL: app.js did not load in jsdom'); process.exit(1); }

  const hl = (line) => window.highlightInlineMarkdown(line);
  const count = (s, needle) => s.split(needle).length - 1;

  console.log('\n[1] single-underscore italic is highlighted');
  {
    const h = hl('some _italic_ text');
    ok(count(h, 'syn-italic') === 2, '1a _italic_ gets 2 italic spans', h);
    ok(h.includes('>_<span') || /<span class="syn-italic">_<\/span>italic<span class="syn-italic">_<\/span>/.test(h), '1b markers wrapped, content plain', h);
    // Line-start and line-end positions
    ok(count(hl('_a_ at start'), 'syn-italic') === 2, '1c line-start underscore', hl('_a_ at start'));
    ok(count(hl('end with _b_'), 'syn-italic') === 2, '1d line-end underscore', hl('end with _b_'));
    // Multiple pairs on one line
    ok(count(hl('_a_ then _b_'), 'syn-italic') === 4, '1e two pairs on one line', hl('_a_ then _b_'));
    // Punctuation after closing marker
    ok(count(hl('call _fn_(x)'), 'syn-italic') === 2, '1f closing _ followed by punctuation', hl('call _fn_(x)'));
  }

  console.log('\n[2] intraword underscores stay plain (CommonMark)');
  {
    ok(count(hl('snake_case_word here'), 'syn-italic') === 0, '2a snake_case not italic', hl('snake_case_word here'));
    ok(count(hl('file_name.txt and _real_'), 'syn-italic') === 2, '2b intraword skipped, real pair still matched', hl('file_name.txt and _real_'));
    ok(count(hl('a_b_c'), 'syn-italic') === 0, '2c pure intraword chain', hl('a_b_c'));
  }

  console.log('\n[3] bold interactions');
  {
    const b = hl('__bold__ text');
    ok(count(b, 'syn-bold') === 2, '3a __bold__ still bold', b);
    ok(count(b, 'syn-italic') === 0, '3b bold underscores not re-matched as italic', b);
    const mixed = hl('__bold__ and _em_');
    ok(count(mixed, 'syn-bold') === 2 && count(mixed, 'syn-italic') === 2, '3c bold + single-underscore italic coexist', mixed);
    const starBold = hl('**bold** and _em_');
    ok(count(starBold, 'syn-bold') === 2 && count(starBold, 'syn-italic') === 2, '3d **bold** + _em_ coexist', starBold);
  }

  console.log('\n[4] star italic regression');
  {
    ok(count(hl('a *em* b'), 'syn-italic') === 2, '4a *em* still italic', hl('a *em* b'));
    ok(count(hl('2 * 3 * 4'), 'syn-italic') === 0, '4b spaced asterisks (math) not italic', hl('2 * 3 * 4'));
  }

  console.log('\n[5] other rules unaffected');
  {
    ok(count(hl('# Heading'), 'syn-heading') === 1, '5a heading rule', hl('# Heading'));
    ok(count(hl('> quoted'), 'syn-quote') === 1, '5b quote rule', hl('> quoted'));
    ok(count(hl('- item'), 'syn-list') === 1, '5c list rule', hl('- item'));
    const code = hl('use `cmd_here` now');
    ok(count(code, 'syn-code') === 2, '5d inline code rule', code);
    const link = hl('see [docs](http://x) ok');
    ok(count(link, 'syn-link') === 4, '5e link rule', link);
    const esc = hl('a <b> & c _d_');
    ok(esc.includes('&lt;b&gt;') && esc.includes('&amp;'), '5f html escaping preserved', esc);
  }

  console.log('\n[6] highlightMarkdown layer integrity (offsets must not change)');
  {
    // The highlight layer's textContent must equal the source text exactly,
    // otherwise caret/line mapping (syncHighlight) breaks.
    const md = '# T\n\ntext _a_ and __b__\n\n> quote\n- list\n```\ncode _x_\n```\nplain _y_';
    const layer = window.document.createElement('div');
    layer.innerHTML = window.highlightMarkdown(md);
    ok(layer.textContent === md, '6a textContent identical to source', JSON.stringify(layer.textContent));
    const fenced = window.highlightMarkdown('```\ncode _x_\n```');
    ok(count(fenced, 'syn-codeblock') >= 2 && !fenced.includes('syn-italic'), '6b no inline highlight inside fences', fenced);
  }

  console.log('\n─────────────────────────────────────');
  console.log('PASSED: ' + passed + '   FAILED: ' + failed);
  if (failures.length) {
    console.log('Failures:');
    failures.forEach(f => console.log('  - ' + f));
    process.exit(1);
  }
  process.exit(0);
})().catch((err) => { console.error('FATAL:', err); process.exit(1); });
