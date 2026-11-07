// 每次职责迁移后串行运行同一组应用回归；不运行会重写 vendor 的测试。
const fs = require('node:fs');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const tests = fs.readdirSync('tests').filter(name => /^test_.*\.js$/.test(name) && name !== 'test_vendor.js').sort();
assert.equal(tests.length, 20);
for (const name of tests) {
  console.log('运行', name);
  const result = spawnSync(process.execPath, ['tests/' + name], { encoding: 'utf8' });
  process.stdout.write(result.stdout || '');
  process.stderr.write(result.stderr || '');
  if (result.status !== 0 || /Uncaught \[/.test(result.stderr || '')) process.exit(result.status || 1);
}
console.log('20组应用JS通过；app.js', fs.readFileSync('app.js', 'utf8').split('\n').length - 1, '行');
