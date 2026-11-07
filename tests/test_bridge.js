const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'frontend/bridge.js'), 'utf8');
const listeners = {};
const timers = [];
const window = { addEventListener: (name, fn) => { listeners[name] = fn; } };
vm.runInNewContext(source, { window, setTimeout: (fn, ms) => timers.push({ fn, ms }), clearTimeout() {} });
const bridge = window.Bridge;
(async () => {
  assert.equal(bridge.ready(), false);
  await assert.rejects(bridge.call('save_file'), /bridge-not-ready/);
  assert.equal(await bridge.callSafe('save_file'), null);
  const logs = [];
  const api = {
    log_js_error(...args) { logs.push(args); return Promise.resolve(true); },
    save_file(...args) { assert.equal(this, api); return args; },
    store_content() { throw new TypeError('用户正文 SECRET'); },
  };
  window.pywebview = { api };
  assert.equal(bridge.ready(), true);
  assert.deepEqual(Array.from(await bridge.call('save_file', '路径', { text: '正文' }, 0, false)), ['路径', { text: '正文' }, 0, false]);
  await assert.rejects(bridge.call('missing'), /bridge-missing:missing/);
  await assert.rejects(bridge.call('constructor'), /bridge-missing/);
  await assert.rejects(bridge.call('store_content'), /SECRET/);
  const before = logs.length;
  assert.equal(await bridge.callSafe('store_content'), null);
  assert.equal(logs.length, before + 1, '安全调用只记录一次');
  api.store_content = () => Promise.reject(new Error('SECRET'));
  assert.equal(await bridge.callSafe('store_content'), null);
  api.save_file = () => ({ success: false, conflict: true });
  assert.deepEqual(await bridge.call('save_file'), { success: false, conflict: true });
  for (const name of ['save_as_choose', 'export_as_choose', 'export_as_write', 'native_save_prompt', 'native_conflict_prompt', 'open_file_dialog', 'perform_auto_install']) {
    let finish;
    api[name] = () => new Promise(resolve => { finish = resolve; });
    let settled = false;
    const pending = bridge.call(name).then(value => { settled = true; return value; });
    for (const timer of timers.splice(0)) timer.fn();
    await Promise.resolve();
    assert.equal(settled, false, name + '不能超时误报');
    finish('完成');
    assert.equal(await pending, '完成');
  }
  const error = { name: 'TypeError', message: 'SECRET', stack: 'TypeError: SECRET\nSECRET\n    at SECRET (file:///Users/SECRET/app.js:12:34)\nSECRET@file:///Users/SECRET/frontend/bridge.js:2:3\n at SECRET (https://SECRET/evil.js:3:4)\n at SECRET (file:///SECRET/app.js?SECRET:2:3)' };
  await bridge.logError('window', 'SECRET', error);
  assert.equal(logs.at(-1)[0], 'window');
  assert.equal(logs.at(-1)[1], 'error');
  const diagnostic = JSON.parse(logs.at(-1)[2]);
  assert.equal(diagnostic.type, 'TypeError');
  assert.deepEqual(diagnostic.frames.map(f => f.file), ['app.js', 'frontend/bridge.js']);
  listeners.error({ message: 'SECRET', error });
  listeners.unhandledrejection({ reason: 'SECRET' });
  assert(!JSON.stringify(logs).includes('SECRET'));
  api.log_js_error = () => Promise.reject(new Error('SECRET'));
  await bridge.logError('bridge', 'save_file', error);
  await bridge.callSafe('store_content');
  api.log_js_error = () => { throw new Error('SECRET'); };
  await bridge.logError('bridge', 'save_file', error);
  await bridge.logError('SECRET', 'SECRET', { get stack() { throw new Error('SECRET'); } });
  delete api.log_js_error;
  await bridge.logError('window', 'error', error);
  window.pywebview = null;
  assert.equal(bridge.ready(), false);
  assert(!fs.readFileSync(path.join(root, 'app.js'), 'utf8').includes('window.pywebview'));
  const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
  assert(html.indexOf('frontend/bridge.js') >= 0 && html.indexOf('frontend/bridge.js') < html.indexOf('src="app.js"'));
  console.log('T02 桥接契约、隐私、长操作和资源加载测试通过');
})().catch(error => { console.error(error); process.exitCode = 1; });
