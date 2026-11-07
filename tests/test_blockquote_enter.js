#!/usr/bin/env node
/*
 * Quality gate for blockquote Enter handling + markdown round trip (mdPreview).
 *
 * Bug being covered: pressing Enter inside a blockquote in the rendered
 * (preview) view let WKWebView insert <div>/<p> junk — and on an empty quote
 * line a nested blockquote. turndown wrote those back as stray "> " blank
 * lines, so the source gained lines the user never typed and the preview
 * showed extra blank lines after re-render.
 *
 * Loads the REAL index.html + app.js inside jsdom and drives the actual
 * handlers (handleRenderedEnter, normalizeRenderedHtmlForTurndown,
 * getCurrentMarkdown, renderMarkdown, ensureTurndown).
 *
 * Run:
 *   <node> tests/test_blockquote_enter.js
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
  for (let i = 0; i < 100; i++) {
    if (typeof window.renderMarkdown === 'function' && typeof window.marked !== 'undefined') { ready = true; break; }
    await sleep(100);
  }
  if (!ready) { console.error('FATAL: app.js did not load in jsdom'); process.exit(1); }

  window.pywebview = {
    api: {
      read_clipboard: async () => ({ format: 'none', content: '' }),
      set_dirty: async () => true,
      store_content: async () => true,
    },
  };

  const content = doc.getElementById('content');
  const textarea = doc.getElementById('textarea');

  await window.ensureTurndown();

  function setPreviewMode() { window.eval('isSource = false'); }
  async function render(md) {
    setPreviewMode();
    await window.renderMarkdown(md, content);
    window.eval('renderedDirty = false');
  }
  function caretAtEndOf(el) {
    const sel = window.getSelection();
    const r = doc.createRange();
    r.selectNodeContents(el);
    r.collapse(false);
    sel.removeAllRanges();
    sel.addRange(r);
  }
  function caretAtStartOf(el) {
    const sel = window.getSelection();
    const r = doc.createRange();
    r.selectNodeContents(el);
    r.collapse(true);
    sel.removeAllRanges();
    sel.addRange(r);
  }
  function pressEnter() {
    const e = new window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
    Object.defineProperty(e, 'target', { value: content });
    doc.dispatchEvent(e);
    return e.defaultPrevented;
  }
  function quote() { return content.querySelector('blockquote'); }

  // Rendered DOM -> markdown via the app's real path.
  function currentMd() {
    window.eval('renderedDirty = true');
    return window.getCurrentMarkdown();
  }

  console.log('\n[1] normalizeRenderedHtmlForTurndown: WebKit junk shapes');
  {
    const norm = (h) => window.normalizeRenderedHtmlForTurndown(h);

    // 1a. trailing <div><br></div> junk inside quote is stripped
    const a = norm('<blockquote><p>引用行1</p><div><br></div></blockquote><p>正文段落</p>');
    ok(!/<div>/.test(a) && a.includes('<p>引用行1</p></blockquote>'), '1a trailing div junk stripped', a);

    // 1b. multiple trailing empties stripped
    const b = norm('<blockquote><p>引用行1</p><div><br></div><p><br></p><div><br></div></blockquote><p>正文段落</p>');
    ok(/<blockquote><p>引用行1<\/p><\/blockquote>/.test(b), '1b multiple trailing empties stripped', b);

    // 1c. fully empty quote removed
    const c = norm('<p>正文</p><blockquote><div><br></div></blockquote><p>正文2</p>');
    ok(!c.includes('blockquote'), '1c empty quote removed', c);

    // 1d. empty nested blockquote removed
    const d = norm('<blockquote><p>引用行1</p><blockquote><br></blockquote></blockquote><p>正文段落</p>');
    ok((d.match(/<blockquote>/g) || []).length === 1, '1d empty nested quote removed', d);
    // 1e. MIDDLE empty line preserved (user-intended blank quote line)
    const e1 = norm('<blockquote><p>a</p><p><br></p><p>b</p></blockquote>');
    ok(/<p>a<\/p><p>(<br>)?<\/p><p>b<\/p>/.test(e1), '1e mid-quote blank line kept', e1);

    // 1f. quote <div> converted to <p>
    const f = norm('<blockquote><p>a</p><div>b</div></blockquote>');
    ok(/<p>a<\/p><p>b<\/p>/.test(f) && !/<div>/.test(f), '1f quote div -> p', f);

    // 1g. trailing <br> inside a quote line stripped
    const g = norm('<blockquote><p>a<br></p></blockquote>');
    ok(/<p>a<\/p>/.test(g), '1g trailing br stripped', g);

    // 1h. non-quote divs (table-wrap / mermaid) untouched
    const h = norm('<div class="table-wrap"><table><tr><td>x</td></tr></table></div><blockquote><p>a</p><div><br></div></blockquote>');
    ok(h.includes('table-wrap'), '1h table-wrap untouched', h);
  }

  console.log('\n[2] handleRenderedEnter: continuation inside quote');
  {
    await render('> 引用行1\n\n正文段落');
    const p1 = quote().querySelector('p');
    caretAtEndOf(p1);
    const prevented = pressEnter();
    ok(prevented, '2a Enter inside quote preventDefault-ed');
    const ps = quote().querySelectorAll('p');
    ok(ps.length === 2 && ps[1].tagName === 'P' && quote().contains(ps[1]), '2b new empty line inside quote', quote().innerHTML);
    ok(content.querySelectorAll(':scope > p').length === 1, '2c no paragraph leaked after quote');
  }

  console.log('\n[3] handleRenderedEnter: exit quote on empty last line');
  {
    // Simulate: quote with a trailing empty line (as after continuation)
    await render('> 引用行1\n\n正文段落');
    const p1 = quote().querySelector('p');
    caretAtEndOf(p1);
    pressEnter();                       // creates empty line inside quote
    const emptyP = quote().querySelectorAll('p')[1];
    ok(!emptyP.textContent.trim(), '3a empty line exists');
    pressEnter();                       // Enter on the empty line -> exit
    ok(!emptyP.parentNode, '3b empty line removed');
    const next = quote().nextElementSibling;
    ok(next && next.tagName === 'P', '3c new paragraph after quote', quote().outerHTML + ' || next: ' + (next && next.outerHTML));
    // Quote still intact with its content
    ok(quote() && quote().textContent.trim() === '引用行1', '3d quote content intact');
  }

  console.log('\n[4] handleRenderedEnter: mid-line split');
  {
    await render('> 引用行\n\n正文段落');
    const p1 = quote().querySelector('p');
    const textNode = p1.firstChild;
    const sel = window.getSelection();
    const r = doc.createRange();
    r.setStart(textNode, 2); // after "引用"
    r.collapse(true);
    sel.removeAllRanges();
    sel.addRange(r);
    pressEnter();
    const ps = Array.from(quote().querySelectorAll('p'));
    ok(ps.length === 2 && ps[0].textContent === '引用' && ps[1].textContent === '行', '4a split at caret', JSON.stringify(ps.map(p => p.textContent)));
  }

  console.log('\n[5] full round trip: Enter junk no longer corrupts the source');
  {
    // 5a. continuation round trip: quote + one empty continuation line ->
    //     trailing empties dropped, source stays clean
    await render('> 引用行1\n\n正文段落');
    caretAtEndOf(quote().querySelector('p'));
    pressEnter(); // empty continuation line
    const md = currentMd();
    ok(md.trim() === '> 引用行1\n\n正文段落', '5a continuation round trip clean', JSON.stringify(md));

    // 5b. exit round trip: quote + paragraph after it
    await render('> 引用行1\n\n正文段落');
    caretAtEndOf(quote().querySelector('p'));
    pressEnter(); pressEnter(); // exit quote
    const md2 = currentMd();
    ok(/^> 引用行1\n\n\n?正文段落$/.test(md2.trim()), '5b exit round trip', JSON.stringify(md2));

    // 5c. pre-polluted DOM (old junk from previous app versions) round trips clean
    await render('> 引用行1\n\n正文段落');
    const junk = doc.createElement('div');
    junk.innerHTML = '<br>';
    quote().appendChild(junk); // WebKit-style junk
    const junk2 = doc.createElement('p');
    junk2.innerHTML = '<br>';
    quote().appendChild(junk2);
    const md3 = currentMd();
    ok(!/\n>\s*\n?\s*$/.test(md3.trim()) && md3.trim() === '> 引用行1\n\n正文段落', '5c polluted DOM round trip clean', JSON.stringify(md3));

    // 5d. pristine round trip stability (regression: multi-paragraph quote)
    await render('> 引用行1\n>\n> 引用行2\n\n正文');
    window.eval('renderedDirty = true');
    const md4 = currentMd();
    ok(/^> 引用行1\n> ?\n> 引用行2\n\n正文$/.test(md4.trim()), '5d multi-paragraph quote stable', JSON.stringify(md4));

    // 5e. empty quote fully removed by round trip
    await render('> 引用行1\n\n正文段落');
    quote().querySelector('p').remove(); // quote now empty
    window.eval('renderedDirty = true');
    const md5 = currentMd();
    ok(!md5.includes('>'), '5e empty quote dropped', JSON.stringify(md5));
  }

  console.log('\n[6] Enter outside quotes stays native');
  {
    await render('> 引用行1\n\n正文段落');
    const paras = content.querySelectorAll(':scope > p');
    const last = paras[paras.length - 1];
    caretAtEndOf(last);
    const prevented = pressEnter();
    ok(!prevented, '6a Enter outside quote not intercepted');
  }

  console.log('\n[7] keydown interception guards');
  {
    await render('> 引用行1\n\n正文段落');
    caretAtEndOf(quote().querySelector('p'));
    // Shift+Enter must NOT be intercepted (soft line break stays native)
    const e2 = new window.KeyboardEvent('keydown', { key: 'Enter', shiftKey: true, bubbles: true, cancelable: true });
    doc.dispatchEvent(e2);
    ok(!e2.defaultPrevented, '7a Shift+Enter not intercepted');
    // In source mode Enter must not be intercepted
    window.eval('isSource = true');
    const e3 = new window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
    doc.dispatchEvent(e3);
    ok(!e3.defaultPrevented, '7b source mode not intercepted');
    setPreviewMode();
  }

  console.log('\n[8] repeated Enter/round-trip cycles do not grow the document');
  {
    await render('> 引用行1\n\n正文段落');
    let lastMd = '';
    for (let i = 0; i < 3; i++) {
      caretAtEndOf(quote().querySelector('p'));
      pressEnter(); pressEnter(); // continue + exit
      lastMd = currentMd();
      // Write back and re-render like a real toggle cycle
      await render(lastMd);
    }
    ok(lastMd.trim() === '> 引用行1\n\n正文段落', '8a no growth over 3 cycles', JSON.stringify(lastMd));
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
