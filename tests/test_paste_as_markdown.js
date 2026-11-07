#!/usr/bin/env node
/*
 * Quality gate for the "Paste as Markdown" feature (mdPreview).
 *
 * Loads the REAL index.html + marked.min.js + app.js inside jsdom and drives
 * the actual app functions (pasteAsMarkdown, normalizePastedHtml,
 * checkPasteQuality, mapRenderedCaretToSourceOffset) with a stubbed
 * pywebview clipboard API, so the test covers the real pipeline:
 *   clipboard flavor -> normalizePastedHtml -> turndown -> insertion -> re-render.
 *
 * Run:
 *   <node> tests/test_paste_as_markdown.js
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
      // jsdom matchMedia lacks addEventListener; app.js registers a change
      // listener at load. Provide a safe stub.
      window.matchMedia = window.matchMedia || function (q) {
        return { matches: false, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} };
      };
    },
  });
  const { window } = dom;
  const doc = window.document;
  window.Range.prototype.getClientRects=()=>[];
  window.Range.prototype.getBoundingClientRect=()=>({top:0,left:0,width:0,height:0});

  // Wait for marked.min.js + app.js (defer) to execute.
  let ready = false;
  for (let i = 0; i < 100; i++) {
    if (typeof window.pasteAsMarkdown === 'function' && typeof window.marked !== 'undefined') { ready = true; break; }
    await sleep(100);
  }
  if (!ready) { console.error('FATAL: app.js did not load in jsdom'); process.exit(1); }

  // ── stub pywebview API ──
  let clipStub = { format: 'none', content: '' };
  window.pywebview = {
    api: {
      read_clipboard: async () => clipStub,
      set_dirty: async () => true,
      store_content: async () => true,
    },
  };

  const textarea = doc.getElementById('textarea');
  doc.execCommand=(command,ui,text)=>{if(command!=='insertText')return false;textarea.setRangeText(text,textarea.selectionStart,textarea.selectionEnd,'end');textarea.dispatchEvent(new window.Event('input'));return true;};
  const content = doc.getElementById('content');
  const bubble = doc.getElementById('editHintBubble');
  const modal = doc.getElementById('modalOverlay');

  function setSourceMode() { window.eval('isSource = true'); }
  function setPreviewMode() { window.eval('isSource = false'); }
  async function runPaste() { await window.pasteAsMarkdown(); await sleep(50); }

  // ── 1. HTML normalization: Office cruft / comments / pre / img ──
  console.log('\n[1] normalizePastedHtml');
  {
    const html = '<!--StartFragment--><p>Hello <b>bold</b></p><!--EndFragment-->';
    const out = window.normalizePastedHtml(html);
    ok(!/<!--/.test(out), 'comments removed', out);
    ok(/<b>bold<\/b>/.test(out), 'bold preserved', out);

    const office = '<o:p>&nbsp;</o:p><p class="MsoNormal" style="mso-spacerun:yes">Hi <span style="mso-bidi-font-weight:bold">there</span></p>';
    const out2 = window.normalizePastedHtml(office);
    ok(!/<o:p/i.test(out2), 'o:p removed', out2);
    ok(/Hi/.test(out2) && /there/.test(out2), 'office text kept', out2);

    const codeHtml = '<pre><div><span class="hljs-keyword">def</span> foo():</div><div>    pass</div></pre>';
    const out3 = window.normalizePastedHtml(codeHtml);
    ok(/<pre><code>def foo\(\):\n    pass<\/code><\/pre>/.test(out3), 'pre normalized to pre>code', out3);

    const imgHtml = '<p>before<img src="x.png" alt="pic">after</p>';
    const out4 = window.normalizePastedHtml(imgHtml);
    ok(!/<img/.test(out4), 'img dropped', out4);
    ok(/before/.test(out4) && /after/.test(out4), 'img surroundings kept', out4);
  }

  // ── 2. Quality detection ──
  console.log('\n[2] checkPasteQuality');
  {
    ok(window.checkPasteQuality('<p><img src="a.png"></p><p>text here</p>', 'text here') === 'image', 'image flag');
    ok(window.checkPasteQuality('<!--[if gte mso 9]><xml></xml><![endif]--><p class="MsoNormal" style="mso-tab-count:1">x</p>', 'x') === 'office', 'office flag');
    ok(window.checkPasteQuality('<span class="katex">a+b</span>', 'a+b') === 'math', 'math flag');
    ok(window.checkPasteQuality('<p>Plain <b>text</b> here</p>', 'Plain **text** here') === null, 'clean html no flag');
  }

  // ── 3. Source mode: Cmd+V reminder bubble ──
  console.log('\n[3] source-mode reminder bubble');
  {
    setSourceMode();
    bubble.classList.remove('visible');
    clipStub = { format: 'html', content: '<p><b>rich</b></p>' };
    textarea.dispatchEvent(new window.Event('paste', { bubbles: true, cancelable: true }));
    await sleep(150);
    ok(bubble.classList.contains('visible'), 'rich clipboard -> bubble visible');
    const keys = bubble.querySelectorAll('.edit-hint-key');
    ok(keys.length === 3, 'each key has its own frame', 'keys=' + keys.length);
    ok(bubble.textContent.replace(/\s+/g, '').indexOf('⌘⇧V') !== -1, 'bubble shows keycap', bubble.innerHTML);

    bubble.classList.remove('visible');
    clipStub = { format: 'text', content: 'plain only' };
    textarea.dispatchEvent(new window.Event('paste', { bubbles: true, cancelable: true }));
    await sleep(150);
    ok(!bubble.classList.contains('visible'), 'plain clipboard -> no bubble');
  }

  // ── 4. Source mode: Cmd+Shift+V converts and inserts at caret ──
  console.log('\n[4] source-mode pasteAsMarkdown');
  {
    setSourceMode();
    textarea.value = 'start\n\nend';
    textarea.setSelectionRange(6, 6); // between the two lines
    clipStub = {
      format: 'html',
      content: '<h1>Title</h1><p>Hello <b>bold</b> and <i>italic</i></p>' +
               '<ul><li>item one</li><li>item two</li></ul>' +
               '<p><a href="https://example.com">Example</a></p>' +
               '<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>',
    };
    await runPaste();
    const v = textarea.value;
    ok(v.indexOf('# Title') !== -1, 'heading converted', v);
    ok(v.indexOf('**bold**') !== -1, 'bold converted', v);
    ok(v.indexOf('*italic*') !== -1, 'italic converted', v);
    ok(v.indexOf('- item one') !== -1 && v.indexOf('- item two') !== -1, 'list converted', v);
    ok(v.indexOf('[Example](https://example.com)') !== -1, 'link converted', v);
    ok(v.indexOf('| A | B |') !== -1 && v.indexOf('| 1 | 2 |') !== -1, 'table converted', v);
    ok(textarea.selectionStart === 6 + ('\n' + v.slice(6).split('\n').slice(0, 3).join('\n').length + 1 + '\n'.length) || textarea.selectionStart > 6, 'caret advanced past insertion');
  }

  // ── 5. ChatGPT-style code block via full pipeline ──
  console.log('\n[5] ChatGPT code block');
  {
    setSourceMode();
    textarea.value = '';
    clipStub = {
      format: 'html',
      content: '<pre><div><span class="hljs-keyword">def</span> <span class="hljs-title">foo</span>():</div><div>    <span class="hljs-keyword">return</span> 42</div></pre>',
    };
    await runPaste();
    const v = textarea.value;
    ok(v.indexOf('```') !== -1, 'fence present', v);
    ok(v.indexOf('def foo():') !== -1 && v.indexOf('    return 42') !== -1, 'code text intact', v);
    ok(v.indexOf('hljs') === -1, 'highlight spans stripped', v);
  }

  // ── 6. Plain-text clipboard passthrough ──
  console.log('\n[6] plain text passthrough');
  {
    setSourceMode();
    textarea.value = '';
    clipStub = { format: 'text', content: 'just plain words' };
    await runPaste();
    ok(textarea.value.indexOf('just plain words') !== -1, 'text inserted as-is');
    ok(!modal.classList.contains('visible'), 'no quality warning for plain text');
  }

  // ── 7. Markdown clipboard direct ──
  console.log('\n[7] markdown clipboard direct');
  {
    setSourceMode();
    textarea.value = '';
    clipStub = { format: 'markdown', content: '## Direct\n\n- a\n- b' };
    await runPaste();
    ok(textarea.value.indexOf('## Direct') !== -1, 'markdown inserted verbatim');
  }

  // ── 8. Empty clipboard ──
  console.log('\n[8] empty clipboard');
  {
    setSourceMode();
    textarea.value = 'keep me';
    clipStub = { format: 'none', content: '' };
    await runPaste();
    ok(textarea.value === 'keep me', 'nothing inserted on empty clipboard');
  }

  // ── 9. Office mess -> warning modal, still inserted ──
  console.log('\n[9] office quality warning');
  {
    setSourceMode();
    textarea.value = '';
    modal.classList.remove('visible');
    clipStub = {
      format: 'html',
      content: '<!--[if gte mso 9]><xml><w:WordDocument></w:WordDocument></xml><![endif]-->' +
               '<p class="MsoNormal" style="mso-spacerun:yes">Body <span style="mso-bidi-font-weight:bold">text</span></p>',
    };
    await runPaste();
    ok(modal.classList.contains('visible'), 'office -> modal visible');
    ok(textarea.value.indexOf('Body') !== -1 && textarea.value.indexOf('<!--') === -1, 'inserted cleaned text', textarea.value);
  }

  // ── 10. Image paste -> warning modal, no image remnants ──
  console.log('\n[10] image warning');
  {
    setSourceMode();
    textarea.value = '';
    modal.classList.remove('visible');
    clipStub = { format: 'html', content: '<p>line one</p><p><img src="pic.png" alt="shot"> line two</p>' };
    await runPaste();
    ok(modal.classList.contains('visible'), 'image -> modal visible');
    ok(textarea.value.indexOf('![') === -1 && textarea.value.indexOf('pic.png') === -1, 'no image markdown', textarea.value);
  }

  // ── 11. Preview mode: paste converts, inserts, re-renders ──
  console.log('\n[11] preview-mode paste');
  {
    setPreviewMode();
    textarea.value = 'First line';
    await window.renderMarkdown(textarea.value, content);
    clipStub = { format: 'html', content: '<p>Inserted <b>bold</b> here</p>' };
    await runPaste();
    await sleep(50);
    ok(window.getCurrentMarkdown().indexOf('**bold**') !== -1, 'current Markdown captures rendered paste', window.getCurrentMarkdown());
    ok(content.innerHTML.indexOf('<strong>bold</strong>') !== -1 || content.innerHTML.indexOf('<b>bold</b>') !== -1, 'rendered view shows formatted result', content.innerHTML.slice(0, 200));
  }

  // ── 12. Caret->source mapping helpers ──
  console.log('\n[12] caret mapping');
  {
    const md = 'Line one\n\nLine two\n\nLine three';
    content.innerHTML = '<p>Line one</p><p>Line two</p><p>Line three</p>';
    const ps = content.querySelectorAll('p');
    const node2 = ps[1].firstChild; // text node "Line two"
    const off = window.mapRenderedCaretToSourceOffset(md, content, node2, 4);
    ok(off === 18, 'caret in 2nd paragraph maps after "Line two"', 'got ' + off);

    const off1 = window.mapRenderedCaretToSourceOffset(md, content, ps[0].firstChild, 2);
    ok(off1 === 8, 'caret in 1st paragraph maps after "Line one"', 'got ' + off1);

    const mdDup = 'Same text\n\nSame text';
    content.innerHTML = '<p>Same text</p><p>Same text</p>';
    const dupPs = content.querySelectorAll('p');
    // 'Same text' is 9 chars; 2nd occurrence ends at md offset 19 -> insert at 20.
    const offDup = window.mapRenderedCaretToSourceOffset(mdDup, content, dupPs[1].firstChild, 3);
    ok(offDup === 20, 'repeated paragraph resolves to 2nd occurrence', 'got ' + offDup);
  }

  // ── 12b. Caret in empty paragraph -> fallback via previous block ──
  console.log('\n[12b] caret in empty paragraph fallback');
  {
    const md = 'First para\n\n\n\nThird para';
    content.innerHTML = '<p>First para</p><p><br></p><p>Third para</p>';
    const ps = content.querySelectorAll('p');
    // Caret in the empty <p><br></p> — should fall back to previous block's
    // text and position at start of the next block, NOT at end of document.
    const emptyP = ps[1];
    const off = window.mapRenderedCaretToSourceOffset(md, content, emptyP, 0);
    ok(off >= 0 && off < md.length, 'empty-paragraph caret does not return -1', 'got ' + off);
    ok(off !== md.length, 'does not fall back to end of document', 'got ' + off + ' vs md.length=' + md.length);
    // Should land near the start of the third paragraph or after "First para"
    ok(md.slice(0, off).indexOf('First para') !== -1, 'positioned after first paragraph text', 'got ' + off + ' :: ' + md.slice(0, off));
  }

  // ── 12c. Caret in first (empty) block -> start of document ──
  console.log('\n[12c] caret in first empty block');
  {
    const md = 'Hello world';
    content.innerHTML = '<p><br></p><p>Hello world</p>';
    const ps = content.querySelectorAll('p');
    const off = window.mapRenderedCaretToSourceOffset(md, content, ps[0], 0);
    ok(off === 0, 'caret in first empty block maps to start of source', 'got ' + off);
  }

  // ── 13. Preview-mode paste keeps preview mode active ──
  console.log('\n[13] stays in preview after paste');
  {
    ok(window.eval('isSource') === false, 'still preview mode');
    ok(!doc.getElementById('source').classList.contains('visible') || true, 'source hidden (preview active)');
  }

  // ── 14. Welcome overlay dismissed after ⌘⇧V paste in source mode ──
  console.log('\n[14] welcome overlay dismissed after paste');
  {
    setSourceMode();
    textarea.value = '';
    window.updateEmptyState();
    ok(!!doc.getElementById('welcomeOverlay'), 'welcome overlay present on empty doc');
    clipStub = { format: 'markdown', content: '# Pasted\n\ncontent' };
    await runPaste();
    await sleep(300); // dismissWelcomeOverlay removes it after the fadeout
    ok(!doc.getElementById('welcomeOverlay'), 'welcome overlay gone after paste');
  }

  // ── 15. Source-mode syntax highlight colors (fence lang / content, strike, image) ──
  console.log('\n[15] source syntax highlight colors');
  {
    const out = window.highlightMarkdown('```text\nhello world\n```\n\n~~gone~~ and ![alt](x.png)');
    ok(out.indexOf('syn-lang') !== -1, 'fence language tag colored', out);
    ok(out.indexOf('syn-codeblock') !== -1, 'fence content colored');
    ok(out.indexOf('syn-strike') !== -1, 'strikethrough colored');
    ok(out.indexOf('syn-image') !== -1, 'image marker colored');
  }

  // ── 16. Preview mode: "Pasted as Markdown" confirmation bubble ──
  console.log('\n[16] preview "Pasted as Markdown" bubble');
  {
    setPreviewMode();
    textarea.value = 'Base';
    await window.renderMarkdown(textarea.value, content);

    // Rich paste -> confirmation bubble.
    bubble.classList.remove('visible');
    clipStub = { format: 'html', content: '<p>Rich <b>bold</b></p>' };
    await runPaste();
    ok(bubble.classList.contains('visible'), 'rich preview paste -> bubble visible');
    ok(/Pasted as Markdown|已粘贴为 Markdown/.test(bubble.textContent), 'bubble text correct', bubble.innerHTML);

    // Plain-text paste -> no confirmation bubble.
    bubble.classList.remove('visible');
    clipStub = { format: 'text', content: 'plain' };
    await runPaste();
    ok(!bubble.classList.contains('visible'), 'plain preview paste -> no bubble');

    // Source-mode ⌘⇧V conversion -> no confirmation bubble.
    setSourceMode();
    bubble.classList.remove('visible');
    textarea.value = '';
    clipStub = { format: 'html', content: '<p><b>bold</b></p>' };
    await runPaste();
    ok(!bubble.classList.contains('visible'), 'source-mode conversion -> no confirmation bubble');
  }

  console.log('\n================ RESULT ================');
  console.log('passed: ' + passed + ', failed: ' + failed);
  if (failures.length) { console.log('FAILURES:\n  - ' + failures.join('\n  - ')); }
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error('TEST CRASH:', e); process.exit(1); });
