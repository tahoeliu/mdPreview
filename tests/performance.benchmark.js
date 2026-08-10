#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
const root = path.resolve(__dirname, '..');
const indexHtml = fs.readFileSync(path.join(root, 'app.js'), 'utf8');

function extractFunctionSource(name) {
  const start = indexHtml.indexOf('function ' + name);
  if (start < 0) throw new Error(`Function ${name} not found`);
  let i = indexHtml.indexOf('{', start);
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
  extractFunctionSource('escHtml'),
  extractFunctionSource('highlightInlineMarkdown'),
  extractFunctionSource('highlightMarkdown'),
].join('\n');
const { highlightMarkdown } = new Function(`${fnSource}\nreturn { highlightMarkdown };`)();

for (const mb of [1, 5]) {
  const unit = '# Heading\n\nSome **bold** text and [link](https://example.com).\n\n```js\nconst x = "**not markdown**";\n```\n\n';
  const target = mb * 1024 * 1024;
  const text = unit.repeat(Math.ceil(target / unit.length)).slice(0, target);
  const started = Date.now();
  highlightMarkdown(text);
  const elapsed = Date.now() - started;
  console.log(`${mb}MB source highlight: ${elapsed}ms`);
}
