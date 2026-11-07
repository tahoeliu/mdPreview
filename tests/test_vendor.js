const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');
const root = path.resolve(__dirname, '..');
const read = p => fs.readFileSync(path.join(root, p));
const json = p => JSON.parse(read(p));
const manifest = json('vendor/manifest.json');
const expected = ['docx', 'dompurify', 'katex', 'marked', 'marked-footnote', 'mermaid', 'turndown'];
assert.deepEqual(manifest.libraries.map(p => p.name).sort(), expected);
assert.equal(json('package.json').devDependencies.marked, '12.0.0');
for (const lib of manifest.libraries) {
  assert.equal(json('package.json').devDependencies[lib.name], lib.version);
  assert.ok(lib.files.length > 0);
  assert.ok(manifest.packages.some(p => p.name === lib.name && p.version === lib.version));
}
for (const pkg of manifest.packages) {
  assert.ok(pkg.integrity && pkg.resolved, pkg.name);
  assert.ok(read(pkg.licenseFile).length > 100, pkg.name);
  for (const dependency of pkg.dependencies) assert.ok(manifest.packages.some(p => p.id === dependency), dependency);
}
assert.ok(manifest.packages.filter(p => p.usedBy.includes('mermaid')).length > 20);
for (const name of manifest.libraries.find(p => p.name === 'mermaid').bundledPackages) {
  assert.ok(manifest.packages.some(p => p.name === name && p.usedBy.includes('mermaid')), name);
}
const checks = json('vendor/checksums.json');
assert.ok(!Object.keys(checks).some(p => p.includes('html2canvas')));
for (const [file, hash] of Object.entries(checks)) {
  assert.equal(crypto.createHash('sha256').update(read(file)).digest('hex'), hash, file);
}
const css = read('vendor/katex/katex.min.css').toString();
for (const match of css.matchAll(/url\(([^)]+)\)/g)) {
  assert.ok(fs.existsSync(path.join(root, 'vendor/katex', match[1].replace(/["']/g, ''))));
}
assert.ok(read('THIRD_PARTY_NOTICES.md').toString().includes('emStrong'));
assert.ok(read('vendor/Credits.rtf').toString().startsWith('{\\rtf1'));
const before = new Map([...Object.keys(checks), 'vendor/checksums.json', 'vendor/Credits.rtf'].map(p => [p, read(p)]));
for (const args of [[], ['--check']]) {
  const run = spawnSync(process.execPath, ['scripts/vendor.mjs', ...args], { cwd: root, encoding: 'utf8' });
  assert.equal(run.status, 0, run.stdout + run.stderr);
  for (const [p, bytes] of before) assert.deepEqual(read(p), bytes, p);
}
const vm = require('node:vm');
const { TextEncoder, TextDecoder } = require('node:util');
const sandbox = vm.createContext({ TextEncoder, TextDecoder, Uint8Array, ArrayBuffer, Blob, setTimeout, clearTimeout, crypto: crypto.webcrypto, btoa, atob, console });
vm.runInContext(read('vendor/docx.umd.js').toString(), sandbox);
assert.equal(typeof sandbox.docx.Document, 'function');
assert.equal(typeof sandbox.docx.Packer.toBase64String, 'function');
vm.runInContext(read('vendor/katex/katex.min.js').toString(), sandbox);
assert.ok(sandbox.katex.renderToString('x^2', { throwOnError: true }).includes('katex'));
(async () => {
  const document = new sandbox.docx.Document({ sections: [{ children: [new sandbox.docx.Paragraph('T30 OOXML smoke')] }] });
  const bytes = Buffer.from(await sandbox.docx.Packer.toBase64String(document), 'base64');
  assert.equal(bytes.subarray(0, 2).toString(), 'PK');
  const { unzipSync, strFromU8 } = require('fflate');
  const xml = strFromU8(unzipSync(bytes)['word/document.xml']);
  assert.ok(xml.includes('T30 OOXML smoke') && !xml.includes('altChunk'));
  console.log('T30 资源、许可证、字体引用、浏览器构建及重复生成校验通过');
})().catch(error => { console.error(error); process.exitCode = 1; });
