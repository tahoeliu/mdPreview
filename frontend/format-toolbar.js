/* 预览模式的选区工具栏：像 Word 一样选中文字即可加粗、改标题、做列表、加链接，
   无需认识 Markdown 语法。只调用浏览器原生编辑命令，修改经现有输入管线写回 Markdown。 */
window.FormatToolbar = (() => {
  const BLOCKED = 'pre, .math-block, .math-inline, .mermaid-diagram, .frontmatter, table th, .footnotes';
  function safeHref(value) {
    const text = String(value || '').trim();
    if (!text) return '';
    if (/^(https?:|mailto:|#|\.{0,2}\/)/i.test(text)) return text;
    if (/^[a-z][a-z0-9+.-]*:/i.test(text)) return '';            // 其他协议一律拒绝
    return /^[\w.-]+\.[a-z]{2,}(\/|$)/i.test(text) ? 'https://' + text : text;
  }
  function create(deps = {}) {
    const content = deps.content || document.getElementById('content');
    const t = deps.t || ((en, zh) => (window.I18n && I18n.t ? I18n.t(en, zh) : en));
    if (!content) return null;
    const bar = document.createElement('div');
    bar.className = 'format-toolbar'; bar.setAttribute('role', 'toolbar'); bar.setAttribute('aria-label', t('Format', '格式')); bar.hidden = true;
    document.body.append(bar);

    function run(command, value) { content.focus(); document.execCommand(command, false, value); }
    function inside(tag) {
      const node = getSelection().anchorNode, el = node && (node.nodeType === 1 ? node : node.parentElement);
      return el && el.closest ? el.closest(tag) : null;
    }
    function toggleBlock(tag) { run('formatBlock', inside(tag) ? 'p' : tag); }
    function toggleCode() {
      const existing = inside('code');
      if (existing && !existing.closest('pre')) { existing.replaceWith(document.createTextNode(existing.textContent)); content.dispatchEvent(new Event('input', { bubbles: true })); return; }
      const text = getSelection().toString();
      if (text) run('insertHTML', '<code>' + text.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c])) + '</code>');
    }
    function linkEditor() {
      const selection = getSelection(), range = selection.rangeCount ? selection.getRangeAt(0).cloneRange() : null;
      if (!range) return;
      const existing = inside('a');
      bar.textContent = '';
      const input = document.createElement('input'); input.type = 'text'; input.placeholder = t('Paste a link and press Enter', '粘贴链接后按回车');
      input.value = existing ? existing.getAttribute('href') || '' : ''; input.setAttribute('aria-label', input.placeholder);
      bar.append(input); input.focus();
      const restore = () => { selection.removeAllRanges(); selection.addRange(range); content.focus(); };
      input.addEventListener('keydown', e => {
        if (e.key === 'Escape') { e.preventDefault(); restore(); build(); }
        else if (e.key === 'Enter') {
          e.preventDefault(); const href = safeHref(input.value); restore();
          if (href) run('createLink', href); else if (existing || !input.value.trim()) run('unlink');
          build();
        }
      });
    }
    const buttons = [
      ['B', t('Bold (⌘B)', '加粗 (⌘B)'), () => run('bold'), 'bold'],
      ['I', t('Italic (⌘I)', '斜体 (⌘I)'), () => run('italic'), 'italic'],
      ['S', t('Strikethrough', '删除线'), () => run('strikeThrough'), 'strike'],
      ['</>', t('Code', '代码'), toggleCode, 'code'],
      ['Link', t('Link', '链接'), linkEditor, 'link'],
      ['H2', t('Heading', '标题'), () => toggleBlock('h2'), 'h2'],
      ['H3', t('Subheading', '小标题'), () => toggleBlock('h3'), 'h3'],
      ['•', t('Bulleted list', '无序列表'), () => run('insertUnorderedList'), 'ul'],
      ['1.', t('Numbered list', '有序列表'), () => run('insertOrderedList'), 'ol'],
      ['❝', t('Quote', '引用'), () => toggleBlock('blockquote'), 'quote'],
    ];
    function build() {
      bar.textContent = '';
      for (const [label, title, action, kind] of buttons) {
        // 可访问名称须包含可见文字
        const button = document.createElement('button'); button.type = 'button'; button.textContent = label; button.title = title; button.setAttribute('aria-label', /^[A-Za-z0-9]/.test(label) ? label + ' ' + title : title); button.dataset.kind = kind;
        button.addEventListener('mousedown', e => e.preventDefault());       // 保持选区
        button.addEventListener('click', () => { action(); if (kind !== 'link') requestAnimationFrame(refresh); });
        bar.append(button);
      }
    }
    function eligible() {
      const selection = getSelection();
      if (!selection || selection.isCollapsed || !selection.rangeCount || content.classList.contains('hidden')) return null;
      const range = selection.getRangeAt(0);
      if (!content.contains(range.commonAncestorContainer)) return null;
      const node = range.commonAncestorContainer, el = node.nodeType === 1 ? node : node.parentElement;
      if (el && el.closest && el.closest(BLOCKED)) return null;
      if (!selection.toString().trim()) return null;
      return range;
    }
    function refresh() {
      if (bar.querySelector('input')) return;                                // 正在输入链接时不要重建
      const range = eligible();
      if (!range) { bar.hidden = true; return; }
      if (!bar.firstChild) build();
      const active = { bold: document.queryCommandState('bold'), italic: document.queryCommandState('italic'), strike: document.queryCommandState('strikeThrough'),
        code: !!inside('code'), link: !!inside('a'), h2: !!inside('h2'), h3: !!inside('h3'), ul: !!inside('ul'), ol: !!inside('ol'), quote: !!inside('blockquote') };
      for (const button of bar.querySelectorAll('button')) button.classList.toggle('on', !!active[button.dataset.kind]);
      const rect = range.getBoundingClientRect();
      bar.hidden = false;
      const width = bar.offsetWidth, height = bar.offsetHeight;
      const left = Math.min(Math.max(8, rect.left + rect.width / 2 - width / 2), window.innerWidth - width - 8);
      const top = rect.top - height - 8 < 8 ? rect.bottom + 8 : rect.top - height - 8;
      bar.style.left = left + 'px'; bar.style.top = top + 'px';
    }
    // 切换到源码模式时 #content 会被隐藏，工具栏必须随之消失。
    new MutationObserver(() => { if (content.classList.contains('hidden')) bar.hidden = true; }).observe(content, { attributes: true, attributeFilter: ['class'] });
    let timer = 0;
    document.addEventListener('selectionchange', () => { clearTimeout(timer); timer = setTimeout(refresh, 90); });
    document.addEventListener('mouseup', () => setTimeout(refresh, 0));
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && !bar.hidden && !bar.querySelector('input')) bar.hidden = true; });
    const scroller = document.querySelector('.scroll-wrap');
    if (scroller) scroller.addEventListener('scroll', () => { if (!bar.querySelector('input')) bar.hidden = true; }, { passive: true });
    return { refresh, bar, safeHref };
  }
  return { create, safeHref };
})();
document.addEventListener('DOMContentLoaded', () => { window.formatToolbar = FormatToolbar.create(); });
