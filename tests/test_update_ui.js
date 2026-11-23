#!/usr/bin/env node
/*
 * 更新 UI 契约：后台下载静默，权威 ready 状态提供“立即更新 / 稍后”。
 * 保留手动下载百分比、失败原因、进度重置与旧接口关闭行为的有效断言。
 * 气泡正文及旧 installUpdate 不批准安装；只有明确按钮调用 approve_update。
 * 语言切换只重绘状态，不触发保存、快照、恢复或安装。
 *
 * 在 jsdom 中加载真实 index.html、frontend 模块、app.js 与 CSS，后端全部模拟。
 * 运行：node tests/test_update_ui.js
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
    if (typeof window.showUpdateDownloadProgress === 'function' && typeof window.marked !== 'undefined') { ready = true; break; }
    await sleep(100);
  }
  if (!ready) { console.error('FATAL: app.js did not load in jsdom'); process.exit(1); }

  window.pywebview = { api: { set_dirty: async () => true, store_content: async () => true } };

  const bubble = () => doc.getElementById('updateBubble');

  console.log('\n[1] manual download progress (percent only)');
  {
    window.showUpdateDownloadProgress(0);
    ok(bubble().classList.contains('visible'), '1a bubble visible at 0%');
    ok(bubble().classList.contains('downloading'), '1b downloading state');
    window.showUpdateDownloadProgress(37);
    const bar = doc.getElementById('updateProgressBar');
    ok(bar.style.width === '37%', '1c progress bar width 37%', bar.style.width);
    const txt = bubble().querySelector('.update-bubble-text').textContent;
    ok(/37%/.test(txt), '1d text shows percent', txt);
    ok(!/MB|KB/i.test(txt), '1e no MB/KB in text', txt);
  }

  console.log('\n[2] download failure shows reason by code');
  {
    window.showUpdateDownloadFailed('network', 'detail for status bar');
    ok(bubble().classList.contains('visible'), '2a bubble visible after failure');
    ok(!bubble().classList.contains('downloading'), '2b downloading state cleared');
    const txt = bubble().querySelector('.update-bubble-text').textContent;
    ok(/Download failed/.test(txt), '2c failure text', txt);
    ok(/Network error/.test(txt), '2d network reason shown', txt);
    const bar = doc.getElementById('updateProgressBar');
    ok(bar.style.width === '0%', '2e progress reset', bar.style.width);
    // Unknown code falls back gracefully
    window.showUpdateDownloadFailed('weird-code', '');
    ok(/Download failed/.test(bubble().querySelector('.update-bubble-text').textContent), '2f unknown code fallback');
    // Legacy single-string call still safe
    window.showUpdateDownloadFailed('download failed');
    ok(/Download failed/.test(bubble().querySelector('.update-bubble-text').textContent), '2g legacy call safe');
  }

  console.log('\n[3] 旧下载完成通知不能提供批准入口');
  {
    window.showUpdateDownloadProgress(99);
    window.showUpdateBubble();
    const txt = bubble().querySelector('.update-bubble-text').textContent;
    ok(/Update downloaded\. Waiting for a safe restart\./.test(txt), '3a 旧通知只显示等待安全重启', txt);
    ok(bubble().classList.contains('visible'), '3b bubble visible');
    ok(!bubble().classList.contains('downloading'), '3c downloading state cleared');
    const bar = doc.getElementById('updateProgressBar');
    ok(bar.style.width === '0%', '3d progress reset for next use', bar.style.width);
    ok(bubble().querySelector('.update-approve').hidden && bubble().querySelector('.update-later').hidden,
      '3e 缺少权威版本的旧通知不显示批准按钮');
    ok(await window.installUpdate() === false, '3f 旧 installUpdate 不能批准安装');
  }

  console.log('\n[4] dismiss vs progress interplay');
  {
    window.dismissUpdateBubble();
    ok(!bubble().classList.contains('visible'), '4a dismissed hides bubble');
    window.showUpdateBubble(); // dismissed flag blocks it (by design)
    ok(!bubble().classList.contains('visible'), '4b showUpdateBubble stays hidden after dismiss');
    window.showUpdateDownloadProgress(5); // new download resets the flag
    ok(bubble().classList.contains('visible'), '4c progress re-shows bubble after dismiss');
  }

  const text = () => bubble().querySelector('.update-bubble-text').textContent;
  const approve = () => bubble().querySelector('.update-approve');
  const later = () => bubble().querySelector('.update-later');
  const retry = () => bubble().querySelector('.update-retry');
  const flush = () => new Promise(resolve => setImmediate(resolve));
  const calls = [];
  const bridgeCall = window.Bridge.call;
  window.Bridge.call = (name, ...args) => {
    // 窗口获得/失去焦点后会延时采样标题栏颜色，与更新交互无关；在慢机器上它会落进计数窗口。
    if (name !== 'get_chrome_color') calls.push({ name, args });
    return bridgeCall(name, ...args);
  };
  let backendState;
  const push = state => { backendState = { ...state }; return window.updateFeedbackState(backendState); };
  const readyState = version => ({ phase: 'ready', automatic: true, version, armedForQuit: true });
  window.pywebview.api.get_update_state = async () => backendState;
  window.pywebview.api.decline_update = async () => ({ success: true, state: backendState });
  doc.getElementById('textarea').value = '# 测试中的未保存内容';
  const contentBefore = doc.getElementById('textarea').value;
  const modalBefore = doc.getElementById('modalOverlay').className;
  const statusBefore = doc.getElementById('status').textContent;

  console.log('\n[5] 自动检查、下载、重试及失败均静默');
  for (const phase of ['idle', 'checking', 'downloading', 'retrying', 'failed', 'deferred']) {
    const count = calls.length;
    push({ phase, automatic: true, version: '2.1.0', progress: 37, error: 'network', stage: 'download' });
    ok(!bubble().classList.contains('visible') && bubble().getAttribute('aria-hidden') === 'true', `5 ${phase} 不显示气泡`);
    ok(approve().hidden && later().hidden && retry().hidden, `5 ${phase} 不提供动作按钮`);
    ok(calls.length === count && doc.getElementById('modalOverlay').className === modalBefore
      && doc.getElementById('status').textContent === statusBefore, `5 ${phase} 不调用后端、不弹框或显示状态提示`);
  }

  console.log('\n[6] ready 必须通过明确按钮选择，不允许点击正文安装');
  {
    doc.getElementById('textarea').focus();
    const focusBefore = doc.activeElement;
    push(readyState('2.1.0'));
    ok(bubble().classList.contains('visible'), '6a 已安排退出安装的 ready 仍显示选择');
    ok(text() === 'Update 2.1.0 is ready.', '6b 只说版本已就绪，不附加长说明', text());
    const order = [...bubble().querySelectorAll('.update-actions button')].map(button => button.className);
    ok(order.join() === 'update-later,update-approve,update-retry,update-help' && bubble().classList.contains('choosing'),
      '6b2 稍后在前、立即更新在后；选择态不另画关闭按钮', order.join());
    ok(!/click to install|点击安装/i.test(text()), '6c 不再提示点击气泡安装');
    ok(!approve().hidden && !later().hidden && !approve().disabled && !later().disabled && retry().hidden,
      '6d 只显示可用的立即更新和稍后按钮');
    ok(approve().textContent === 'Update now' && later().textContent === 'Later', '6e 按钮文案正确');
    ok(bubble().getAttribute('role') === 'status' && bubble().getAttribute('aria-live') === 'polite'
      && doc.activeElement === focusBefore, '6f ready 使用温和通知且不抢焦点');
    const body = bubble().querySelector('.update-bubble-body');
    ok(!body.hasAttribute('role') && !body.hasAttribute('tabindex'), '6g 正文不是按钮或键盘动作入口');
    const count = calls.length;
    body.click();
    bubble().click();
    for (const key of ['Enter', ' ']) body.dispatchEvent(new window.KeyboardEvent('keydown', { key, bubbles: true }));
    const result = await window.installUpdate();
    await flush();
    ok(result === false && calls.length === count, '6h 正文点击、回车、空格及旧 installUpdate 均不调用安装或批准');
    const style = window.getComputedStyle(bubble());
    const textStyle = window.getComputedStyle(bubble().querySelector('.update-bubble-text'));
    ok(style.cursor === 'default' && style.display === 'flex', '6i 气泡没有整块可点击样式');
    ok(textStyle.whiteSpace === 'normal' && textStyle.overflowWrap === 'anywhere', '6j 多语言长文案允许换行');
  }

  console.log('\n[7] 稍后、关闭和 Escape 只拒绝当前提示，不触发退出');
  for (const [index, action] of ['later', 'close', 'escape'].entries()) {
    const state = readyState(`2.2.${index}`);
    push(state);
    const count = calls.length;
    if (action === 'later') later().click();
    else if (action === 'close') bubble().querySelector('.update-bubble-close').click();
    else bubble().dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await flush();
    ok(calls.length === count + 1 && calls[count].name === 'decline_update' && calls[count].args.length === 0,
      `7 ${action} 只发送一次 decline_update`);
    ok(!bubble().classList.contains('visible'), `7 ${action} 隐藏提示`);
    push(state);
    ok(!bubble().classList.contains('visible'), `7 ${action} 同版本广播不重新打扰`);
    window.showUpdateBubble();
    await flush();
    ok(!bubble().classList.contains('visible') && calls.at(-1).name === 'get_update_state',
      `7 ${action} 旧通知只能读取权威状态`);
  }

  console.log('\n[8] 立即更新只申请原生退出保护，等待期间防止重复点击');
  {
    push(readyState('2.3.0'));
    let finish;
    window.pywebview.api.approve_update = () => new Promise(resolve => { finish = resolve; });
    const count = calls.length;
    approve().click();
    ok(calls.length === count + 1 && calls[count].name === 'approve_update' && calls[count].args.length === 0,
      '8a 立即更新只发送 approve_update，不传文档内容');
    ok(bubble().dataset.phase === 'preparing' && bubble().getAttribute('aria-busy') === 'true'
      && approve().disabled && later().disabled && bubble().querySelector('.update-bubble-close').disabled,
      '8b 等待批准期间保持可见忙状态并禁用动作');
    approve().click(); later().click(); bubble().querySelector('.update-bubble-close').click();
    bubble().dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await window.installUpdate();
    ok(calls.length === count + 1, '8c 等待期间重复点击、Escape 和旧入口均不再调用后端');
    finish({ success: true, state: { ...backendState, phase: 'preparing' } });
    await flush();
    ok(bubble().classList.contains('visible') && bubble().dataset.phase === 'preparing', '8d 等待原生既有保存与退出确认');
    push({ ...readyState('2.3.0'), code: 'quit-cancelled' });
    ok(bubble().classList.contains('visible') && !approve().disabled && !later().disabled,
      '8e 原生退出取消后恢复选择，前端不自行保存或恢复');
  }

  console.log('\n[9] installUpdate 旧名只允许重试手动失败');
  {
    push({ phase: 'failed', automatic: false, stage: 'download', error: 'network', version: '2.4.0' });
    let finish;
    window.pywebview.api.retry_update = () => new Promise(resolve => { finish = resolve; });
    ok(!retry().hidden && !retry().disabled && approve().hidden && later().hidden, '9a 手动失败只显示重试按钮');
    const count = calls.length;
    retry().click();
    ok(calls.length === count + 1 && calls[count].name === 'retry_update', '9b 点击重试只调用 retry_update');
    ok(retry().disabled && retry().textContent === 'Requesting retry…', '9c 重试等待中有反馈且禁止重复');
    ok(await window.installUpdate() === false && calls.length === count + 1, '9d 旧函数名不能重复重试');
    backendState = { phase: 'downloading', automatic: false, progress: 5, version: '2.4.0' };
    finish({ success: true, state: backendState });
    await flush();
    ok(calls.slice(count).map(call => call.name).join(',') === 'retry_update,get_update_state', '9e 重试成功后只刷新状态');
    ok(bubble().dataset.phase === 'downloading' && text().includes('5%') && retry().hidden,
      '9f 手动重试回到百分比下载状态');
    push({ phase: 'failed', automatic: true, error: 'network', version: '2.4.0' });
    const after = calls.length;
    ok(await window.installUpdate() === false && calls.length === after, '9g 自动失败不开放手动重试或安装');
  }

  console.log('\n[10] 八种语言切换保留状态、按钮语义与错误码翻译');
  const readyKey = 'Update {version} is ready.';
  const networkKey = 'Network error. Check your connection.';
  const stateCases = [
    [{ phase: 'idle' }, ['Check for Updates…']],
    [{ phase: 'idle', detail: '状态快照中的旧语言详情' }, ["You're up to date!"]],
    [{ phase: 'checking' }, ['Checking for updates…']],
    [{ phase: 'downloading', progress: 37 }, ['Downloading update... ']],
    [{ phase: 'retrying', error: 'network' }, ['Update will retry later.', networkKey]],
    [{ phase: 'ready', armedForQuit: true }, [readyKey]],
    [{ phase: 'preparing' }, ['Preparing a safe restart…']],
    [{ phase: 'deferred' }, ['Update postponed. Keep editing or retry when ready.']],
    [{ phase: 'installing' }, ['Installing update...']],
    [{ phase: 'failed', stage: 'download', error: 'network' }, ['Download failed: ', networkKey]],
    [{ phase: 'failed', error: 'http', http: 503 }, ['Update failed: ', 'The update server returned an HTTP error.']],
    [{ phase: 'failed', code: 'quit-gap-inconclusive' }, ['Update failed: ', 'Automatic installation is blocked. Installation records are preserved. Use Help > Report an Issue for recovery assistance.']],
    [{ phase: 'failed', code: 'quit-gap-version-unverified' }, ['Update failed: ', 'Automatic installation is blocked. Installation records are preserved. Use Help > Report an Issue for recovery assistance.']],
    [{ phase: 'failed', code: 'helper-handshake-unavailable' }, ['Update failed: ', 'This updater requires a manual installation from github.com/tahoeliu/mdPreview/releases.']],
    [{ phase: 'failed', code: 'release-signing-key-not-configured' }, ['Update failed: ', 'Updates are unavailable: this build has no release signing key.']],
  ];
  const requiredKeys = [...new Set(stateCases.flatMap(([, keys]) => keys).concat([
    'Update now', 'Later', 'Dismiss', 'Retry update', 'Requesting retry…',
    'Retry request failed. Please try again.', 'The update request failed. Please try again.',
    'Could not dismiss the update. Please try again.', 'Too many update requests. Please try again later.',
    'The update file was not found.', 'Access to the update was denied.',
  ]))];
  for (const locale of ['en', 'zh-Hans', 'zh-Hant', 'ja', 'ko', 'de', 'fr', 'es']) {
    const messages = JSON.parse(fs.readFileSync(path.join(REPO, 'frontend', locale + '.json'), 'utf8'));
    const missing = requiredKeys.filter(key => typeof messages[key] !== 'string' || !messages[key].trim());
    ok(missing.length === 0, `10 ${locale} 更新状态及动作翻译完整`, missing.join(' | '));
    for (const [index, [patch, keys]] of stateCases.entries()) {
      const version = `3.${index}.0`;
      window.I18n.configure({ locale: 'en', messages: {} });
      push({ automatic: false, version, code: null, detail: patch.phase === 'idle' ? null : '状态快照中的旧语言详情', ...patch });
      if (patch.code) ok(retry().hidden, `10 ${locale} ${patch.code} 不提供无效重试`);
      const before = [bubble().dataset.phase, bubble().className, approve().hidden, later().hidden,
        retry().hidden, approve().disabled, later().disabled, retry().disabled];
      const count = calls.length;
      window.I18n.configure({ locale, messages });
      window.applyStaticUiLanguage();
      // 完整性单独断言；此处同时检查真实 I18n 的渲染，不能因缺键而跳过状态检查。
      const translated = keys.map(key => (messages[key] ?? key).replace('{version}', version));
      let expected = translated.join(' ');
      if (patch.phase === 'downloading') expected += '37%';
      if (patch.phase === 'failed') expected = translated.join('') + (patch.http ? ' (HTTP 503)' : '');
      ok(text() === expected, `10 ${locale} ${patch.phase}/${index} 文案随语言重绘`, text());
      const after = [bubble().dataset.phase, bubble().className, approve().hidden, later().hidden,
        retry().hidden, approve().disabled, later().disabled, retry().disabled];
      ok(JSON.stringify(before) === JSON.stringify(after) && calls.length === count,
        `10 ${locale} ${patch.phase}/${index} 语言切换不改变状态或调用后端`);
      ok(approve().textContent === (messages['Update now'] ?? 'Update now')
        && later().textContent === messages.Later && retry().textContent === messages['Retry update']
        && bubble().querySelector('.update-bubble-close').getAttribute('aria-label') === messages.Dismiss,
        `10 ${locale} ${patch.phase}/${index} 动作及无障碍名称同步翻译`);
    }
  }
  ok(calls.every(call => ['get_update_state', 'approve_update', 'decline_update', 'retry_update'].includes(call.name)),
    '11a 全部更新交互不调用专用文档保存、快照、恢复或直接安装接口', calls.map(call => call.name).join(','));
  ok(doc.getElementById('textarea').value === contentBefore
    && doc.getElementById('modalOverlay').className === modalBefore,
    '11b 更新 UI 不改写文档、不绕过原生退出保护自行弹出保存流程');
  dom.window.close();

  console.log('\n─────────────────────────────────────');
  console.log('PASSED: ' + passed + '   FAILED: ' + failed);
  if (failures.length) {
    console.log('Failures:');
    failures.forEach(f => console.log('  - ' + f));
    process.exit(1);
  }
  process.exit(0);
})().catch((err) => { console.error('FATAL:', err); process.exit(1); });
