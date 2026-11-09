/* 小功能集合：快捷键匹配、插入菜单用的片段渲染、顶部栏与系统标题栏同色。 */
// 'cmd+shift+e' style specs; letters match by physical key so a non-Latin input source does not break them
window.shortcutMatches = function (e, spec) {
  const parts = String(spec).split('+'), key = parts.pop();
  const want = { cmd: parts.includes('cmd'), ctrl: parts.includes('ctrl'), alt: parts.includes('alt'), shift: parts.includes('shift') };
  if (e.metaKey !== want.cmd || e.ctrlKey !== want.ctrl || e.altKey !== want.alt || e.shiftKey !== want.shift) return false;
  const code = e.code || '';
  return e.key.toLowerCase() === key || code === 'Key' + key.toUpperCase() || code === 'Digit' + key;
};

// Render a Markdown snippet to HTML (math, diagrams) without touching the open document; used by the top bar's Insert menu.
window.renderFragment = async function (markdown) {
  const holder = document.createElement('div');
  holder.style.cssText = 'position:fixed;left:-99999px;top:0;width:640px;';
  document.body.append(holder);
  try {
    appendParsedMarkdown(markdown, holder, { keepExisting: false });
    finalizeRenderedMarkdown(holder, markdown);
    await MathRenderer.renderMath(holder, { eager: true });
    if (holder.querySelector('code.language-mermaid')) await renderMermaidDiagrams(holder);
    protectComplexBlocks(holder);
    holder.querySelectorAll('.render-caret-spacer').forEach(el => el.remove());
    return holder.innerHTML;
  } finally { holder.remove(); }
};
// The top bar takes the system's title-bar colour so the two read as one piece (also when the window is not focused).
window.applyChromeColor = function () {
  try {
    if (!(window.Bridge && Bridge.ready())) return;
    Bridge.call('get_chrome_color').then(r => {
      const h = r && r.overlay ? r.height : 0;
      document.documentElement.style.setProperty('--titlebar-h', h + 'px');
    }).catch(() => {});
  } catch (e) {}
};
try { matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => setTimeout(applyChromeColor, 120)); } catch (e) {}
const resample = () => { setTimeout(applyChromeColor, 120); setTimeout(applyChromeColor, 500); };
window.addEventListener('focus', resample);
window.addEventListener('blur', resample);
document.addEventListener('visibilitychange', resample);
// the page does not always get a blur event when another app takes focus, so keep the colour in step with the real title bar
setInterval(() => { if (!document.hidden) applyChromeColor(); }, 1200);
document.addEventListener('DOMContentLoaded', () => { setTimeout(applyChromeColor, 300); setTimeout(applyChromeColor, 1500); });

// Grabbing an empty spot on the top bars moves the window, like a title bar.
document.addEventListener('mousedown', (e) => {
  if (e.button !== 0) return;
  const bar = e.target.closest && e.target.closest('.edit-bar');
  if (!bar || e.target.closest('button, input, a, [role="menuitem"]')) return;
  try { Bridge.callSafe('begin_window_drag'); } catch (x) {}
}, true);
