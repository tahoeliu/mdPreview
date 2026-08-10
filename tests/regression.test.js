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
  extractFunctionSource('isBlockedHref'),
  extractFunctionSource('isExternalHref'),
].join('\n');

const moduleFactory = new Function(`${fnSource}\nreturn { renderFrontmatter, resolveBlockScalar, highlightMarkdown, escHtml, slugifyHeading, preprocessMarkdownExtensions, isBlockedHref, isExternalHref };`);
const { renderFrontmatter, highlightMarkdown, slugifyHeading, preprocessMarkdownExtensions, isBlockedHref, isExternalHref } = moduleFactory();

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

test('prepareForClose stops timers and guards bridge calls', () => {
  // The native side calls prepareForClose() during window closing; it must
  // cancel every timer and prevent new JS->Python bridge traffic so teardown
  // cannot deadlock on an in-flight non-daemon bridge thread.
  assert(indexHtml.includes('function prepareForClose()'), 'prepareForClose missing');
  assert(indexHtml.includes('closing = true'), 'closing flag not set in prepareForClose');
  assert(indexHtml.includes('clearTimeout(pythonSyncTimer)'), 'python sync timer not cleared');
  assert(indexHtml.includes('clearTimeout(highlightTimer)'), 'highlight timer not cleared');
  assert(indexHtml.includes('clearTimeout(statusTimer)'), 'status timer not cleared');
  assert(indexHtml.includes('clearInterval(keepAliveTimer)'), 'keep-alive interval not cleared');
  assert(indexHtml.includes('if (closing) return;'), 'pushContentToPython not guarded by closing');
  assert(indexHtml.includes('if (closing) return;'), 'schedulePythonSync not guarded by closing');
  assert(/keepAliveTimer = setInterval\(\(\) => \{ if \(!closing && isSource\)/.test(indexHtml),
    'keep-alive interval must be cancelled and guarded by closing');
});

if (process.exitCode) process.exit(process.exitCode);
console.log('All regression tests passed.');
