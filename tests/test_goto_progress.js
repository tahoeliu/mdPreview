// 跳转标题的匹配排序与阅读时间估算（纯函数，不依赖浏览器）。
const assert = require('node:assert/strict');
const { JSDOM } = require('jsdom');
const fs = require('node:fs');
const path = require('node:path');
const dom = new JSDOM('<body><div id="content"></div></body>', { runScripts: 'outside-only' });
for (const file of ['frontend/goto.js', 'frontend/reading-progress.js'])
  dom.window.eval(fs.readFileSync(path.join(__dirname, '..', file), 'utf8'));
const { GoToHeading, ReadingProgress } = dom.window;
const items = ['Install', 'Installation notes', '使用说明', 'Uninstall'].map(text => ({ text }));
assert.deepEqual(GoToHeading.rank(items, 'inst').map(x => x.text), ['Install', 'Installation notes', 'Uninstall']);
assert.deepEqual(GoToHeading.rank(items, 'insn').map(x => x.text), ['Installation notes']);  // 模糊匹配
assert.deepEqual(GoToHeading.rank(items, '说明').map(x => x.text), ['使用说明']);
assert.equal(GoToHeading.rank(items, 'zzz').length, 0);
assert.equal(GoToHeading.rank(items, '').length, 4);
const root = dom.window.document.getElementById('content');
root.innerHTML = '<p>' + '字'.repeat(900) + '</p><pre>' + 'x'.repeat(1800) + '</pre><div class="math-block">' + 'a'.repeat(5000) + '</div>';
const minutes = ReadingProgress.estimateMinutes(root);
assert.ok(minutes > 2.9 && minutes < 3.1, 'CJK 900/450 + code 1800/2/900 = 3 分钟，公式不计: ' + minutes);
root.innerHTML = '<p>' + 'word '.repeat(460) + '</p>';
assert.ok(Math.abs(ReadingProgress.estimateMinutes(root) - 2) < 0.01);
console.log('goto / reading-progress: ok');
