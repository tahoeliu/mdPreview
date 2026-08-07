#!/usr/bin/env node
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const indexHtml = fs.readFileSync(path.join(root, 'index.html'), 'utf8');

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
  extractFunctionSource('highlightMarkdown'),
  extractFunctionSource('escHtml'),
].join('\n');

const moduleFactory = new Function(`${fnSource}\nreturn { renderFrontmatter, resolveBlockScalar, highlightMarkdown, escHtml };`);
const { renderFrontmatter, highlightMarkdown } = moduleFactory();

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

if (process.exitCode) process.exit(process.exitCode);
console.log('All regression tests passed.');
