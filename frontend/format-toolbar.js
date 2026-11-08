/* 预览模式的顶部格式工具条：光标落在正文里就是编辑状态，工具条出现；Esc、「完成」或点正文以外就回到阅读。
   像 Word 一样加粗、改标题、做列表、插入并编辑表格，无需认识 Markdown 语法。
   只调用浏览器原生编辑命令与少量 DOM 操作，修改经现有 input 管线写回 Markdown。 */
window.FormatToolbar = (() => {
  const BLOCKED = 'pre, .math-block, .math-inline, .mermaid-diagram, .frontmatter, .footnotes, .markdown-alert';
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
    const storage = deps.setPinned || (() => {});
    if (!content) return null;
    const bar = document.createElement('div');
    bar.className = 'edit-bar'; bar.setAttribute('role', 'toolbar'); bar.setAttribute('aria-label', t('Format', '格式')); bar.hidden = true;
    document.body.append(bar);
    let pinned = false, editing = false, lastRange = null;

    function currentElement() {
      const node = getSelection().anchorNode;
      return node && (node.nodeType === 1 ? node : node.parentElement);
    }
    function inside(tag) { const el = currentElement(); return el && el.closest && content.contains(el) ? el.closest(tag) : null; }
    function blocked() { const el = currentElement(); return !!(el && el.closest && el.closest(BLOCKED)); }
    function changed() { content.dispatchEvent(new Event('input', { bubbles: true })); }
    function run(command, value) { if (blocked()) return; content.focus(); document.execCommand(command, false, value); }
    function toggleBlock(tag) { run('formatBlock', inside(tag) ? 'p' : tag); }
    function toggleCode() {
      if (blocked()) return;
      const existing = inside('code');
      if (existing && !existing.closest('pre')) { existing.replaceWith(document.createTextNode(existing.textContent)); changed(); return; }
      const text = getSelection().toString();
      if (text) run('insertHTML', '<code>' + text.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c])) + '</code>');
    }
    function linkEditor() {
      const selection = getSelection(), range = selection.rangeCount ? selection.getRangeAt(0).cloneRange() : null;
      if (!range || blocked()) return;
      const existing = inside('a');
      bar.textContent = '';
      const input = document.createElement('input'); input.type = 'text'; input.placeholder = t('Paste a link and press Enter', '粘贴链接后按回车');
      input.value = existing ? existing.getAttribute('href') || '' : ''; input.setAttribute('aria-label', input.placeholder);
      bar.append(input); input.focus();
      const restore = () => { selection.removeAllRanges(); selection.addRange(range); content.focus(); };
      input.addEventListener('keydown', e => {
        e.stopPropagation();
        if (e.key === 'Escape') { e.preventDefault(); restore(); build(); }
        else if (e.key === 'Enter') {
          e.preventDefault(); const href = safeHref(input.value); restore();
          if (href) run('createLink', href); else if (existing || !input.value.trim()) run('unlink');
          build(); refresh();
        }
      });
    }
    // ----- 表格 -----
    function topBlock() { let el = currentElement(); while (el && el.parentElement !== content) el = el.parentElement; return el; }
    function placeCaret(el) { const r = document.createRange(); r.selectNodeContents(el); r.collapse(true); const s = getSelection(); s.removeAllRanges(); s.addRange(r); }
    function insertTable() {
      const block = topBlock(); if (!block || blocked()) return;
      const table = document.createElement('table');
      const head = ['', '', ''].map((_, i) => '<th>' + t('Column', '列') + ' ' + (i + 1) + '</th>').join('');
      const row = '<tr>' + '<td><br></td>'.repeat(3) + '</tr>';
      table.innerHTML = '<thead><tr>' + head + '</tr></thead><tbody>' + row + row + '</tbody>';
      block.after(table);
      if (!table.nextElementSibling) table.after(Object.assign(document.createElement('p'), { innerHTML: '<br>' }));
      placeCaret(table.querySelector('td')); changed();
    }
    function cellInfo() { const cell = inside('td, th'); return cell ? { cell, row: cell.parentElement, table: cell.closest('table'), index: cell.cellIndex } : null; }
    function addRow() {
      const info = cellInfo(); if (!info) return;
      const body = info.table.tBodies[0] || info.table.createTBody();
      const fresh = document.createElement('tr');
      for (let i = 0; i < info.row.cells.length; i++) fresh.append(Object.assign(document.createElement('td'), { innerHTML: '<br>' }));
      if (info.row.parentElement.tagName === 'THEAD') body.prepend(fresh); else info.row.after(fresh);
      placeCaret(fresh.cells[Math.min(info.index, fresh.cells.length - 1)]); changed();
    }
    function removeRow() {
      const info = cellInfo(); if (!info || info.row.parentElement.tagName === 'THEAD') return;
      const next = info.row.nextElementSibling || info.row.previousElementSibling;
      info.row.remove(); if (next) placeCaret(next.cells[Math.min(info.index, next.cells.length - 1)]); changed();
    }
    function addColumn() {
      const info = cellInfo(); if (!info) return;
      for (const row of info.table.rows) { const th = row.parentElement.tagName === 'THEAD'; const cell = document.createElement(th ? 'th' : 'td'); cell.innerHTML = th ? t('Column', '列') : '<br>'; row.cells[info.index].after(cell); }
      placeCaret(info.row.cells[info.index + 1]); changed();
    }
    function removeColumn() {
      const info = cellInfo(); if (!info || info.row.cells.length < 2) return;
      for (const row of info.table.rows) row.cells[info.index]?.remove();
      placeCaret(info.row.cells[Math.min(info.index, info.row.cells.length - 1)]); changed();
    }
    function removeTable() {
      const info = cellInfo(); if (!info) return;
      const next = info.table.nextElementSibling || info.table.previousElementSibling; info.table.remove();
      if (next) placeCaret(next); changed();
    }
    const buttons = [
      ['B', t('Bold (⌘B)', '加粗 (⌘B)'), () => run('bold'), 'bold'],
      ['I', t('Italic (⌘I)', '斜体 (⌘I)'), () => run('italic'), 'italic'],
      ['S', t('Strikethrough', '删除线'), () => run('strikeThrough'), 'strike'],
      ['</>', t('Code', '代码'), toggleCode, 'code'],
      ['Link', t('Link', '链接'), linkEditor, 'link'],
      '|',
      ['H1', t('Title', '大标题'), () => toggleBlock('h1'), 'h1'],
      ['H2', t('Heading', '标题'), () => toggleBlock('h2'), 'h2'],
      ['H3', t('Subheading', '小标题'), () => toggleBlock('h3'), 'h3'],
      '|',
      ['•', t('Bulleted list', '无序列表'), () => run('insertUnorderedList'), 'ul'],
      ['1.', t('Numbered list', '有序列表'), () => run('insertOrderedList'), 'ol'],
      ['❝', t('Quote', '引用'), () => toggleBlock('blockquote'), 'quote'],
      ['Table', t('Insert table', '插入表格'), insertTable, 'table'],
    ];
    const tableButtons = [
      ['+Row', t('Add row below', '在下方加一行'), addRow, 'addrow'],
      ['−Row', t('Delete row', '删除此行'), removeRow, 'delrow'],
      ['+Col', t('Add column right', '在右侧加一列'), addColumn, 'addcol'],
      ['−Col', t('Delete column', '删除此列'), removeColumn, 'delcol'],
      ['✕', t('Delete table', '删除表格'), removeTable, 'deltable'],
    ];
    function addButton(parent, [label, title, action, kind]) {
      const button = document.createElement('button'); button.type = 'button'; button.textContent = label; button.title = title;
      button.setAttribute('aria-label', /^[A-Za-z0-9+−]/.test(label) ? label + ' ' + title : title); button.dataset.kind = kind;
      button.addEventListener('mousedown', e => e.preventDefault());       // 保持选区
      button.addEventListener('click', () => { action(); if (kind !== 'link') requestAnimationFrame(refresh); });
      parent.append(button);
    }
    function build() {
      bar.textContent = '';
      for (const item of buttons) {
        if (item === '|') { bar.append(Object.assign(document.createElement('span'), { className: 'edit-sep' })); continue; }
        addButton(bar, item);
      }
      const group = document.createElement('span'); group.className = 'edit-table-group'; group.hidden = true;
      group.append(Object.assign(document.createElement('span'), { className: 'edit-sep' }));
      for (const item of tableButtons) addButton(group, item);
      bar.append(group);
      const done = document.createElement('button'); done.type = 'button'; done.className = 'edit-done'; done.textContent = t('Done', '完成'); done.dataset.kind = 'done';
      done.addEventListener('mousedown', e => e.preventDefault());
      done.addEventListener('click', () => { leave(true); });
      bar.append(done);
    }
    function refresh() {
      if (bar.querySelector('input') || bar.hidden) return;
      if (!bar.firstChild) build();
      const active = { bold: document.queryCommandState('bold'), italic: document.queryCommandState('italic'), strike: document.queryCommandState('strikeThrough'),
        code: !!inside('code'), link: !!inside('a'), h1: !!inside('h1'), h2: !!inside('h2'), h3: !!inside('h3'), ul: !!inside('ul'), ol: !!inside('ol'), quote: !!inside('blockquote') };
      const off = blocked();
      for (const button of bar.querySelectorAll('button')) {
        button.classList.toggle('on', !!active[button.dataset.kind]);
        if (button.dataset.kind !== 'done') button.disabled = off;
      }
      const group = bar.querySelector('.edit-table-group'); if (group) group.hidden = !inside('table');
    }
    function show() {
      if (content.classList.contains('hidden')) return;
      editing = true; document.body.classList.add('is-editing');
      if (bar.hidden) { bar.hidden = false; if (!bar.firstChild) build(); }
      refresh();
    }
    function hide() { bar.hidden = true; document.body.classList.remove('is-editing'); bar.textContent = ''; editing = false; }
    // 回到阅读：隐藏工具条并收起光标（固定显示时只放下光标）
    function leave(blur) {
      if (blur) { const a = document.activeElement; if (a && content.contains(a)) a.blur(); getSelection().removeAllRanges(); }
      if (!pinned) hide();
    }
    function setPinned(value, persist = true) {
      pinned = !!value; document.body.classList.toggle('edit-pinned', pinned);
      if (pinned) { if (bar.hidden) { bar.hidden = false; build(); } refresh(); } else if (!editing) hide();
      if (persist) storage(pinned);
    }
    function togglePinned() { setPinned(!pinned); return pinned; }
    new MutationObserver(() => { if (content.classList.contains('hidden')) { if (pinned) bar.hidden = true; else hide(); } else if (pinned && bar.hidden) { bar.hidden = false; build(); refresh(); } }).observe(content, { attributes: true, attributeFilter: ['class'] });

    // 只有用户亲手点击/键入才算进入编辑；程序自动移动光标（打开文件、跳转标题）不触发
    content.addEventListener('mouseup', e => {
      if (e.button !== 0) return;
      const target = e.target.nodeType === 1 ? e.target : e.target.parentElement;
      if (target && target.closest('a, .task-toggle, input, button, .code-copy-btn, .fold-toggle, .remote-image-bar, img, .mermaid-diagram')) return;
      setTimeout(() => { const s = getSelection(); if (s && s.rangeCount && content.contains(s.anchorNode)) show(); }, 0);
    });
    content.addEventListener('keydown', e => {
      if (e.metaKey || e.ctrlKey || e.altKey || e.key === 'Escape' || e.key.length > 1 && !['Enter', 'Backspace', 'Delete'].includes(e.key)) return;
      if (!editing) show();
    });
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && (editing || !bar.hidden) && !document.querySelector('.modal-overlay.visible, .find-bar.visible, .goto-overlay:not([hidden])')) leave(true); });
    content.addEventListener('focusout', () => setTimeout(() => {
      const a = document.activeElement;
      if (a && (content.contains(a) || bar.contains(a))) return;
      if (!pinned) hide(); else editing = false;
    }, 0));
    document.addEventListener('selectionchange', () => { if (!bar.hidden) setTimeout(refresh, 40); });
    return { refresh, bar, safeHref, setPinned, togglePinned, isEditing: () => editing, isPinned: () => pinned, leave };
  }
  return { create, safeHref };
})();
document.addEventListener('DOMContentLoaded', () => { window.formatToolbar = FormatToolbar.create({ setPinned: v => { try { Bridge.callSafe('set_settings', { format_bar: v }); } catch (e) {} } }); });
