(function () {
  'use strict';

  const errorTypes = new Set(['Error', 'TypeError', 'RangeError', 'ReferenceError', 'SyntaxError', 'URIError', 'EvalError', 'AggregateError']);
  const scriptPattern = /^(?:app\.js|(?:frontend|vendor)\/[A-Za-z0-9_.\/-]+\.js)$/;

  function ready() {
    return !!(window.pywebview && window.pywebview.api);
  }

  async function call(name, ...args) {
    try {
      if (!ready()) throw new Error('bridge-not-ready');
      const api = window.pywebview.api;
      if (typeof name !== 'string' || !Object.prototype.hasOwnProperty.call(api, name) || typeof api[name] !== 'function') {
        throw new Error('bridge-missing:' + (typeof name === 'string' ? name : 'invalid'));
      }
      // 面板、保存、导出和更新必须等原生完成；前端超时不能取消原生操作。
      return await api[name].apply(api, args);
    } catch (error) {
      logError('bridge', name, error);
      throw error;
    }
  }

  function callSafe(name, ...args) {
    return call(name, ...args).catch(() => null);
  }

  function logError(scope, what, error) {
    try {
      if (!ready()) return;
      const api = window.pywebview.api;
      if (typeof api.log_js_error !== 'function') return;
      const safeScope = ['bridge', 'window', 'promise'].includes(scope) ? scope : 'unknown';
      const safeWhat = safeScope === 'bridge' && typeof what === 'string' && /^[a-z_]{1,64}$/.test(what) && Object.prototype.hasOwnProperty.call(api, what) && typeof api[what] === 'function'
        ? what : (safeScope === 'promise' ? 'unhandled' : 'error');
      const type = error && errorTypes.has(error.name) ? error.name : 'Error';
      const frames = [];
      // stack 的首行、函数名、URL 路径和源码片段均可能含文档文本，不得转发。
      const stack = error && typeof error.stack === 'string' ? error.stack.slice(0, 16384) : '';
      for (const line of stack.split('\n').slice(0, 64)) {
        const match = line.match(/(?:\/|^)((?:(?:frontend|vendor)\/(?:[A-Za-z0-9_.-]+\/)*)?[A-Za-z0-9_.-]+\.js):([0-9]{1,7}):([0-9]{1,7})\)?$/);
        if (match && scriptPattern.test(match[1])) frames.push({ file: match[1], line: Number(match[2]), column: Number(match[3]) });
        if (frames.length === 16) break;
      }
      // 日志端点的同步异常和异步拒绝都在这里消化，避免递归上报。
      return Promise.resolve(api.log_js_error(safeScope, safeWhat, JSON.stringify({ type, frames }))).catch(() => {});
    } catch (_) {
      // 日志不可用不影响编辑、保存或错误传播。
    }
  }

  window.addEventListener('error', event => { logError('window', 'error', event.error); });
  window.addEventListener('unhandledrejection', event => { logError('promise', 'unhandled', event.reason); });
  window.Bridge = { ready, call, callSafe, logError };
})();
