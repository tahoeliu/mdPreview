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
    // ----- 表格 -----（一律经 insertHTML 写入，这样 ⌘Z / ⇧⌘Z 能撤销和重做）
    function topBlock() { let el = currentElement(); while (el && el.parentElement !== content) el = el.parentElement; return el; }
    function placeCaret(el) { const r = document.createRange(); r.selectNodeContents(el); r.collapse(true); const s = getSelection(); s.removeAllRanges(); s.addRange(r); }
    function insertHTML(html) { content.focus(); document.execCommand('insertHTML', false, html); }
    function insertTable() {
      const block = topBlock(); if (!block || blocked()) return;
      const head = [1, 2, 3].map(i => '<th>' + t('Column', '列') + ' ' + i + '</th>').join('');
      const row = '<tr>' + '<td><br></td>'.repeat(3) + '</tr>';
      const r = document.createRange(); r.setStartAfter(block); r.collapse(true);
      const s = getSelection(); s.removeAllRanges(); s.addRange(r);
      const count = [...content.querySelectorAll('table')].filter(x => x === block || x.compareDocumentPosition(block) & Node.DOCUMENT_POSITION_FOLLOWING).length;
      insertHTML('<table><thead><tr>' + head + '</tr></thead><tbody>' + row + row + '</tbody></table>' + (block.nextElementSibling ? '' : '<p><br></p>'));
      const fresh = content.querySelectorAll('table')[count];
      if (fresh) placeCaret(fresh.querySelector('td, th'));
      changed();
    }
    function cellInfo() { const cell = inside('td, th'); return cell ? { cell, row: cell.parentElement, table: cell.closest('table'), index: cell.cellIndex, rowIndex: cell.parentElement.rowIndex } : null; }
    // 复制整张表、改完后整体替换：浏览器把它记成一步可撤销的编辑
    function rewrite(info, mutate, rowIndex, colIndex) {
      const tableIndex = [...content.querySelectorAll('table')].indexOf(info.table);
      const copy = info.table.cloneNode(true); mutate(copy);
      const r = document.createRange(); r.selectNode(info.table);
      const s = getSelection(); s.removeAllRanges(); s.addRange(r);
      insertHTML(copy.rows.length ? copy.outerHTML : '<p><br></p>');
      const fresh = content.querySelectorAll('table')[tableIndex];
      if (fresh && rowIndex != null) { const row = fresh.rows[Math.min(rowIndex, fresh.rows.length - 1)]; if (row) placeCaret(row.cells[Math.min(colIndex, row.cells.length - 1)]); }
      changed();
    }
    function blankCell(head) { const cell = document.createElement(head ? 'th' : 'td'); if (head) cell.textContent = t('Column', '列'); else cell.innerHTML = '<br>'; return cell; }
    function addRow() {
      const info = cellInfo(); if (!info) return;
      const inHead = info.row.parentElement.tagName === 'THEAD';
      rewrite(info, copy => {
        const fresh = document.createElement('tr');
        for (let i = 0; i < info.row.cells.length; i++) fresh.append(blankCell(false));
        if (inHead) (copy.tBodies[0] || copy.createTBody()).prepend(fresh); else copy.rows[info.rowIndex].after(fresh);
      }, info.rowIndex + 1, info.index);
    }
    function removeRow() {
      const info = cellInfo(); if (!info || info.row.parentElement.tagName === 'THEAD') return;
      rewrite(info, copy => copy.rows[info.rowIndex].remove(), info.rowIndex, info.index);
    }
    function addColumn() {
      const info = cellInfo(); if (!info) return;
      rewrite(info, copy => { for (const row of copy.rows) row.cells[info.index].after(blankCell(row.parentElement.tagName === 'THEAD')); }, info.rowIndex, info.index + 1);
    }
    function removeColumn() {
      const info = cellInfo(); if (!info || info.row.cells.length < 2) return;
      rewrite(info, copy => { for (const row of copy.rows) row.cells[info.index]?.remove(); }, info.rowIndex, info.index);
    }
    function removeTable() {
      const info = cellInfo(); if (!info) return;
      rewrite(info, copy => copy.replaceChildren());
    }
    function clearFormat() {
      if (blocked()) return;
      run('removeFormat'); if (inside('h1, h2, h3, blockquote')) run('formatBlock', 'p'); run('unlink'); changed();
    }
    function addTask() {
      if (blocked()) return;
      if (!inside('ul, ol')) run('insertUnorderedList');
      const li = inside('li'); if (!li || li.querySelector(':scope > .task-toggle, :scope > p > .task-toggle')) return;
      const box = document.createElement('button'); box.className = 'task-toggle'; box.contentEditable = 'false'; box.setAttribute('role', 'checkbox');
      box.setAttribute('aria-label', t('Toggle task', '切换任务状态')); box.setAttribute('aria-checked', 'false'); box.textContent = '☐'; box.dataset.taskMarker = '[ ] ';
      box.addEventListener('click', e => { e.preventDefault(); const on = box.getAttribute('aria-checked') !== 'true'; box.setAttribute('aria-checked', String(on)); box.textContent = on ? '☑' : '☐'; box.dataset.taskMarker = on ? '[x] ' : '[ ] '; changed(); });
      li.setAttribute('data-task', ''); li.prepend(box); changed();
    }
    function inList() { return !!inside('li'); }
    // ----- 图标（细线条）-----
    const ICONS = {
      plus: '<circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/>',
      undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
      redo: '<path d="m15 14 5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
      eraser: '<path d="m7 21-4.3-4.3a1 1 0 0 1 0-1.4l9-9a1 1 0 0 1 1.4 0l5.2 5.2a1 1 0 0 1 0 1.4L13 21"/><path d="M22 21H7M5 11l9 9"/>',
      bold: '<path d="M6 12h9a4 4 0 0 1 0 8H7a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h7a4 4 0 0 1 0 8"/>',
      italic: '<path d="M19 4h-9M14 20H5M15 4 9 20"/>',
      strike: '<path d="M16 4H9a3 3 0 0 0-2.83 4M14 12a4 4 0 0 1 0 8H6M4 12h16"/>',
      code: '<path d="m16 18 6-6-6-6M8 6l-6 6 6 6"/>',
      ul: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
      ol: '<path d="M10 6h11M10 12h11M10 18h11M4 6h1v4M4 10h2M6 18H4c0-1 2-2 2-3s-1-1.5-2-1"/>',
      task: '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
      outdent: '<path d="M21 6H11M21 12h-8M21 18H11M7 8l-4 4 4 4"/>',
      indent: '<path d="M21 6H11M21 12h-8M21 18H11M3 8l4 4-4 4"/>',
      link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
      quote: '<path d="M4 5v14M9 8h11M9 12h11M9 16h7"/>',
      table: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M3 15h18M9 4v16"/>',
      rule: '<path d="M3 12h18M5 6h.01M12 6h.01M19 6h.01M5 18h.01M12 18h.01M19 18h.01"/>',
      rowAdd: '<rect x="3" y="3" width="18" height="12" rx="2"/><path d="M3 9h18M12 18v4M10 20h4"/>',
      rowDel: '<rect x="3" y="3" width="18" height="12" rx="2"/><path d="M3 9h18M10 20h4"/>',
      colAdd: '<rect x="3" y="3" width="12" height="18" rx="2"/><path d="M9 3v18M18 10v4M16 12h4"/>',
      colDel: '<rect x="3" y="3" width="12" height="18" rx="2"/><path d="M9 3v18M16 12h4"/>',
      trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    };
    function icon(name) { return '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + ICONS[name] + '</svg>'; }
    const CARET = '<svg class="edit-caret" viewBox="0 0 10 6" width="8" height="5" aria-hidden="true"><path d="M0 0h10L5 6z" fill="currentColor"/></svg>';
    // ----- 下拉菜单 -----
    let menu = null;
    function closeMenu() { if (menu) { menu.remove(); menu = null; } }
    function openMenu(anchor, items) {
      const same = menu && menu.anchor === anchor; closeMenu(); if (same) return;
      menu = document.createElement('div'); menu.className = 'edit-menu'; menu.setAttribute('role', 'menu'); menu.anchor = anchor;
      for (const [label, action, kind, iconName] of items) {
        const item = document.createElement('button'); item.type = 'button'; item.setAttribute('role', 'menuitem'); item.dataset.kind = kind;
        item.innerHTML = (iconName ? icon(iconName) : '') + '<span></span>'; item.lastChild.textContent = label;
        item.addEventListener('mousedown', e => e.preventDefault());
        item.addEventListener('click', () => { closeMenu(); action(); requestAnimationFrame(refresh); });
        menu.append(item);
      }
      document.body.append(menu);
      const box = anchor.getBoundingClientRect(); menu.style.left = Math.max(8, Math.min(box.left, innerWidth - menu.offsetWidth - 8)) + 'px'; menu.style.top = (box.bottom + 4) + 'px';
    }
    document.addEventListener('mousedown', e => { if (menu && !menu.contains(e.target) && !(menu.anchor && menu.anchor.contains(e.target))) closeMenu(); }, true);
    const insertItems = () => [[t('Table', '表格'), insertTable, 'table', 'table'], [t('Divider', '分隔线'), () => run('insertHorizontalRule'), 'rule', 'rule']];
    const styleItems = () => [[t('Body', '正文'), () => run('formatBlock', 'p'), 'p'], [t('Title', '大标题'), () => { if (!inside('h1')) run('formatBlock', 'h1'); }, 'h1'], [t('Heading', '标题'), () => { if (!inside('h2')) run('formatBlock', 'h2'); }, 'h2'], [t('Subheading', '小标题'), () => { if (!inside('h3')) run('formatBlock', 'h3'); }, 'h3']];
    // type: icon = 单个图标；menu = 带文字和下拉箭头
    const buttons = [
      { type: 'menu', icon: 'plus', label: () => t('Insert', '插入'), title: t('Insert', '插入'), items: insertItems, kind: 'insert' },
      '|',
      { icon: 'undo', title: t('Undo (⌘Z)', '撤销 (⌘Z)'), action: () => { content.focus(); document.execCommand('undo'); }, kind: 'undo' },
      { icon: 'redo', title: t('Redo (⇧⌘Z)', '重做 (⇧⌘Z)'), action: () => { content.focus(); document.execCommand('redo'); }, kind: 'redo' },
      { icon: 'eraser', title: t('Clear formatting', '清除格式'), action: clearFormat, kind: 'clear' },
      '|',
      { type: 'menu', label: () => inside('h1') ? t('Title', '大标题') : inside('h2') ? t('Heading', '标题') : inside('h3') ? t('Subheading', '小标题') : t('Body', '正文'), title: t('Text style', '文字样式'), items: styleItems, kind: 'style' },
      '|',
      { icon: 'bold', title: t('Bold (⌘B)', '加粗 (⌘B)'), action: () => run('bold'), kind: 'bold' },
      { icon: 'italic', title: t('Italic (⌘I)', '斜体 (⌘I)'), action: () => run('italic'), kind: 'italic' },
      { icon: 'strike', title: t('Strikethrough', '删除线'), action: () => run('strikeThrough'), kind: 'strike' },
      { icon: 'code', title: t('Code', '代码'), action: toggleCode, kind: 'code' },
      '|',
      { icon: 'ul', title: t('Bulleted list', '无序列表'), action: () => run('insertUnorderedList'), kind: 'ul' },
      { icon: 'ol', title: t('Numbered list', '有序列表'), action: () => run('insertOrderedList'), kind: 'ol' },
      { icon: 'task', title: t('Task list', '任务列表'), action: addTask, kind: 'task' },
      { icon: 'outdent', title: t('Decrease indent', '减少缩进'), action: () => run('outdent'), kind: 'outdent' },
      { icon: 'indent', title: t('Increase indent', '增加缩进'), action: () => run('indent'), kind: 'indent' },
      '|',
      { icon: 'link', title: t('Link', '链接'), action: linkEditor, kind: 'link' },
      { icon: 'quote', title: t('Quote', '引用'), action: () => toggleBlock('blockquote'), kind: 'quote' },
    ];
    const tableButtons = [
      { icon: 'rowAdd', title: t('Add row below', '在下方加一行'), action: addRow, kind: 'addrow' },
      { icon: 'rowDel', title: t('Delete row', '删除此行'), action: removeRow, kind: 'delrow' },
      { icon: 'colAdd', title: t('Add column right', '在右侧加一列'), action: addColumn, kind: 'addcol' },
      { icon: 'colDel', title: t('Delete column', '删除此列'), action: removeColumn, kind: 'delcol' },
      { icon: 'trash', title: t('Delete table', '删除表格'), action: removeTable, kind: 'deltable' },
    ];
    function addButton(parent, spec) {
      const button = document.createElement('button'); button.type = 'button'; button.title = spec.title; button.dataset.kind = spec.kind;
      if (spec.type === 'menu') {
        button.className = 'edit-menu-btn';
        button.innerHTML = (spec.icon ? icon(spec.icon) : '') + '<span class="edit-label"></span>' + CARET;
        const label = button.querySelector('.edit-label');
        const paint = () => { const text = spec.label(); label.textContent = text; button.setAttribute('aria-label', spec.kind === 'style' ? text + ', ' + spec.title : text); };
        paint(); button.labelFn = paint; button.setAttribute('aria-haspopup', 'menu');
        button.addEventListener('mousedown', e => e.preventDefault());
        button.addEventListener('click', () => openMenu(button, spec.items()));
      } else {
        button.innerHTML = icon(spec.icon); button.setAttribute('aria-label', spec.title);
        button.addEventListener('mousedown', e => e.preventDefault());       // 保持选区
        button.addEventListener('click', () => { closeMenu(); spec.action(); if (spec.kind !== 'link') requestAnimationFrame(refresh); });
      }
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
      const enabled = name => { try { return document.queryCommandEnabled(name); } catch (e) { return true; } };
      const active = { bold: document.queryCommandState('bold'), italic: document.queryCommandState('italic'), strike: document.queryCommandState('strikeThrough'),
        code: !!inside('code'), link: !!inside('a'), ul: !!inside('ul'), ol: !!inside('ol'), quote: !!inside('blockquote'), task: !!inside('li[data-task]') };
      const off = blocked();
      for (const button of bar.querySelectorAll('button')) {
        const kind = button.dataset.kind;
        button.classList.toggle('on', !!active[kind]);
        if (button.labelFn) button.labelFn();
        if (kind === 'done') continue;
        button.disabled = off || (kind === 'undo' && !enabled('undo')) || (kind === 'redo' && !enabled('redo')) || ((kind === 'outdent' || kind === 'indent') && !inList());
      }
      const group = bar.querySelector('.edit-table-group'); if (group) group.hidden = !inside('table');
    }
    function show() {
      if (content.classList.contains('hidden')) return;
      editing = true; document.body.classList.add('is-editing');
      if (bar.hidden) { bar.hidden = false; if (!bar.firstChild) build(); }
      refresh();
    }
    function hide() { closeMenu(); bar.hidden = true; document.body.classList.remove('is-editing'); bar.textContent = ''; editing = false; }
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
    new MutationObserver(() => document.body.classList.toggle('has-edit-bar', !bar.hidden)).observe(bar, { attributes: true, attributeFilter: ['hidden'] });
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
