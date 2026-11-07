const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const modules = {
  syntax: 'SyntaxHighlight', tables: 'TableLayout', updates: 'UpdateFeedback',
  find: 'DocumentFind', paste: 'MarkdownPaste', outline: 'DocumentOutline',
  output: 'DocumentOutput', 'rendered-editing': 'RenderedEditing',
  conversion: 'MarkdownConversion', rendering: 'MarkdownRendering',
  feedback: 'EditorFeedback', 'save-dialogs': 'SaveDialogs',
};
module.exports = async function verifyModules(w) {
  const app = fs.readFileSync('app.js', 'utf8');
  assert.ok(app.split('\n').length - 1 < 1500, '入口必须通过职责拆分控制在1500行以下');
  assert.equal((app.match(/new DocumentSession\(/g) || []).length, 1);
  const html = fs.readFileSync('index.html', 'utf8');
  const gate = fs.readFileSync('scripts/check_release.py', 'utf8');
  for (const [file, namespace] of Object.entries(modules)) {
    const source = fs.readFileSync('frontend/' + file + '.js', 'utf8');
    assert.ok(!/\beval\s*\(|new\s+Function\s*\(|new DocumentSession\(/.test(source));
    assert.ok(html.includes('src="frontend/' + file + '.js"'));
    assert.equal(gate.split("'frontend/" + file + ".js'").length - 1, 2, '源码和包资源门禁均须覆盖模块');
    const sandbox = { window: {} };
    vm.runInNewContext(source, sandbox, { codeGeneration: { strings: false, wasm: false } });
    assert.equal(typeof sandbox.window[namespace].create, 'function');
    assert.equal(typeof w[namespace].create, 'function');
  }
  // 无头与菜单仍可使用原全局函数入口，词法绑定不得截断替换入口。
  const originalExport = w.exportAsWrite;
  let called = false;
  w.exportAsWrite = async () => { called = true; return { success: true }; };
  const choose = w.pywebview.api.save_as_choose;
  w.pywebview.api.save_as_choose = () => ({ success: true, path: '/tmp/t32.txt', format: 'txt' });
  await w.saveAsFile();
  assert.ok(called);
  w.exportAsWrite = originalExport;
  w.pywebview.api.save_as_choose = choose;

  // 每个工厂必须读取传入的实时状态，而非创建时复制状态。
  const state = { isSource: true };
  const find = w.DocumentFind.create({ document: w.document, window: w, state,
    scrollTextareaToLine() {}, findRangeBetween: w.findRangeBetween });
  assert.equal(find.getSearchableText().id, 'textarea');
  state.isSource = false;
  assert.equal(find.getSearchableText().id, 'content');

  // Word 导出失败时必须释放同一个输出忙状态。
  const outputState = { outputBusy: false, closing: false, isSource: false, filePath: '/tmp/t32.md' };
  let requested = null;
  const output = w.DocumentOutput.create({ document: w.document, window: w, state: outputState,
    ensureTurndown: async () => {}, ensureLib: async (...args) => { requested = args; },
    getCurrentMarkdown: () => '# t32', documentSession: { id: 't32' }, buildDocxFromMarkdown: async () => { throw new Error('测试加载失败'); },
    Bridge: { call: async () => ({}) }, OutputPrep: { prepare: async () => () => {} } });
  await assert.rejects(output.exportAsWrite('/tmp/t32.docx', 'docx'), /测试加载失败/);
  assert.equal(outputState.outputBusy, false);
  outputState.closing = true;
  assert.equal((await output.exportAsWrite('/tmp/t32.txt', 'txt')).error, 'output-busy');
  console.log('T32 十二模块加载、禁动态代码、单一会话、实时状态与输出入口契约通过');
};
