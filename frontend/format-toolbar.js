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
      closeMenu();
      bar.textContent = '';
      const back = document.createElement('button'); back.type = 'button'; back.className = 'edit-link-back'; back.dataset.tip = t('Back', '返回'); back.setAttribute('aria-label', back.dataset.tip); back.innerHTML = icon('back');
      const input = document.createElement('input'); input.type = 'text'; input.placeholder = t('Paste a link and press Enter', '粘贴链接后按回车');
      input.value = existing ? existing.getAttribute('href') || '' : ''; input.setAttribute('aria-label', input.placeholder);
      const apply = document.createElement('button'); apply.type = 'button'; apply.className = 'edit-done'; apply.textContent = t('Apply', '应用');
      bar.append(back, input, apply);
      if (existing) { const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'edit-link-remove'; remove.textContent = t('Remove link', '移除链接'); bar.append(remove); remove.addEventListener('mousedown', e => e.preventDefault()); remove.addEventListener('click', () => { restore(); run('unlink'); build(); refresh(); }); }
      input.focus(); input.select();
      const restore = () => { selection.removeAllRanges(); selection.addRange(range); content.focus(); };
      const finish = () => { const href = safeHref(input.value); restore(); if (href) run('createLink', href); else if (existing || !input.value.trim()) run('unlink'); build(); refresh(); };
      back.addEventListener('mousedown', e => e.preventDefault());
      back.addEventListener('click', () => { restore(); build(); refresh(); });
      apply.addEventListener('mousedown', e => e.preventDefault());
      apply.addEventListener('click', finish);
      input.addEventListener('keydown', e => {
        e.stopPropagation();
        if (e.key === 'Escape') { e.preventDefault(); restore(); build(); refresh(); }
        else if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); finish(); }
      });
    }
    // ----- 表格 -----（一律经 insertHTML 写入，这样 ⌘Z / ⇧⌘Z 能撤销和重做）
    function topBlock() { let el = currentElement(); while (el && el.parentElement !== content) el = el.parentElement; return el; }
    function placeCaret(el) { const r = document.createRange(); r.selectNodeContents(el); r.collapse(true); const s = getSelection(); s.removeAllRanges(); s.addRange(r); }
    function insertHTML(html) { content.focus(); document.execCommand('insertHTML', false, html); }
    // Where a new block goes: at the end of the current text block (the engines then split it cleanly), or right after other blocks.
    function placeInsertionPoint(block) {
      const r = document.createRange();
      if (/^(P|H[1-6])$/.test(block.tagName)) { r.selectNodeContents(block); r.collapse(false); } else { r.setStartAfter(block); r.collapse(true); }
      const s = getSelection(); s.removeAllRanges(); s.addRange(r);
    }
    function insertTable(rows = 3, cols = 3) {
      const block = topBlock(); if (!block || blocked()) return;
      rows = Math.max(1, Math.min(rows, 30)); cols = Math.max(1, Math.min(cols, 12));
      const head = Array.from({ length: cols }, (_, i) => '<th>' + t('Column', '列') + ' ' + (i + 1) + '</th>').join('');
      const row = '<tr>' + '<td><br></td>'.repeat(cols) + '</tr>';
      placeInsertionPoint(block);
      const count = [...content.querySelectorAll('table')].filter(x => x === block || x.compareDocumentPosition(block) & Node.DOCUMENT_POSITION_FOLLOWING).length;
      insertHTML('<table><thead><tr>' + head + '</tr></thead>' + (rows > 1 ? '<tbody>' + row.repeat(rows - 1) + '</tbody>' : '') + '</table>' + (block.nextElementSibling ? '' : '<p><br></p>'));
      const fresh = content.querySelectorAll('table')[count];
      if (fresh) placeCaret(fresh.querySelector('tbody td') || fresh.querySelector('th'));
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

    // ----- 在光标所在块之后插入整块内容（均可 ⌘Z 撤销）-----
    function insertBlockHTML(html, caretSelector) {
      const block = topBlock(); if (!block || blocked()) return;
      placeInsertionPoint(block);
      const before = content.children.length;
      insertHTML(html + (block.nextElementSibling ? '' : '<p><br></p>'));
      if (caretSelector) {
        const target = [...content.querySelectorAll(caretSelector)].find(el => block.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING);
        if (target) placeCaret(target);
      }
      changed();
      return before;
    }
    function insertCodeBlock() { insertBlockHTML('<pre><code><br></code></pre>', 'pre code'); }
    async function insertRendered(markdown) {
      if (!window.renderFragment) return;
      const html = await window.renderFragment(markdown);
      if (html) insertBlockHTML(html);
    }
    const insertDiagram = () => insertRendered('```mermaid\ngraph TD\n  A[Start] --> B[Next step]\n  B --> C[Finish]\n```');
    const insertMath = () => insertRendered('$$\nE = mc^2\n$$');
    const insertNote = () => insertRendered('> [!NOTE]\n> ' + t('Write your note here.', '在这里写提示内容。'));
    function insertImage() {
      const picker = document.createElement('input'); picker.type = 'file'; picker.accept = 'image/png,image/jpeg,image/gif,image/webp';
      picker.addEventListener('change', async () => {
        const file = picker.files && picker.files[0]; if (!file) return;
        try {
          if (!window.filePath || window.filePath === 'Untitled.md') { showStatus(t('Save the document before inserting an image', '请先保存文档再插入图片'), true); return; }
          const data = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(file); });
          const ext = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/gif': 'gif', 'image/webp': 'webp' }[file.type]; if (!ext) throw new Error('unsupported');
          const saved = await Bridge.call('save_image_asset', window.filePath, data, ext, file.name, documentSession.id);
          if (!saved || !saved.success) throw new Error('save-failed');
          const base = window.filePath.split('/').slice(0, -1).join('/');
          const img = document.createElement('img'); img.setAttribute('src', 'file://' + base + '/' + saved.path); img.setAttribute('data-original-src', saved.path); img.alt = (file.name || '').replace(/\.[^.]+$/, '');
          insertBlockHTML('<p>' + img.outerHTML + '</p>');
        } catch (e) { showStatus(t('Image save failed', '图片保存失败'), true); }
      });
      picker.click();
    }
    // 缩进：列表里是嵌套；普通段落先变成列表项（Markdown 里段落本身没有缩进）
    function indentMore() { if (blocked()) return; if (inside('li')) run('indent'); else run('insertUnorderedList'); changed(); }
    function indentLess() { if (blocked()) return; if (inside('li')) run('outdent'); else if (inside('blockquote')) run('formatBlock', 'p'); changed(); }
    function canOutdent() { return !!(inside('li') || inside('blockquote')); }
    function clearFormat() {
      if (blocked()) return;
      run('removeFormat'); if (inside('h1, h2, h3, blockquote')) run('formatBlock', 'p'); run('unlink'); changed();
    }
    function addTask() {
      if (blocked()) return;
      const existingBox = (inside('li') || {}).querySelector && inside('li').querySelector(':scope > .task-toggle, :scope > p > .task-toggle');
      if (existingBox) { existingBox.remove(); inside('li').removeAttribute('data-task'); changed(); return; }   // second click: back to a plain bullet
      if (!inside('ul, ol')) run('insertUnorderedList');
      const li = inside('li'); if (!li) return;
      const box = document.createElement('button'); box.className = 'task-toggle'; box.contentEditable = 'false'; box.setAttribute('role', 'checkbox');
      box.setAttribute('aria-label', t('Toggle task', '切换任务状态')); box.setAttribute('aria-checked', 'false'); box.textContent = '\u2610'; box.dataset.taskMarker = '[ ] ';
      box.addEventListener('click', e => { e.preventDefault(); const on = box.getAttribute('aria-checked') !== 'true'; box.setAttribute('aria-checked', String(on)); box.textContent = on ? '\u2611' : '\u2610'; box.dataset.taskMarker = on ? '[x] ' : '[ ] '; changed(); });
      li.setAttribute('data-task', ''); li.prepend(box); changed();
    }
    function inList() { return !!inside('li'); }
    // ----- 图标（细线条）-----
    const ICONS = {
      plus: '<circle cx="12" cy="12" r="9" fill="currentColor" stroke="none" opacity=".38"/><path d="M12 8v8M8 12h8" stroke="#fff" stroke-width="1.6"/>',
      undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10a5.5 5.5 0 0 1 0 11h-3.5"/>',
      redo: '<path d="m15 14 5-5-5-5"/><path d="M20 9H10a5.5 5.5 0 0 0 0 11h3.5"/>',
      eraser: '<path d="m7 21-4-4a1.6 1.6 0 0 1 0-2.2l9.8-9.8a1.6 1.6 0 0 1 2.2 0l5.6 5.6a1.6 1.6 0 0 1 0 2.2L13 21"/><path d="M21 21H7M5.5 11.5l9 9"/>',
      bold: '<path d="M7 4.5h6a3.4 3.4 0 0 1 0 6.8H7zM7 11.3h7.2a3.6 3.6 0 0 1 0 7.2H7z"/>',
      italic: '<path d="M10 5h7M7 19h7M14 5 10 19"/>',
      strike: '<path d="M16.8 7.4C16.3 5.6 14.6 4.5 12.2 4.5 9.6 4.5 7.8 5.8 7.8 7.7c0 1.5 1 2.4 2.7 3M13.8 13.2c1.8.6 2.8 1.6 2.8 3.2 0 2-2 3.3-4.6 3.3-2.5 0-4.3-1.1-4.9-3M3.5 12h17"/>',
      code: '<path d="m8 8-4 4 4 4M16 8l4 4-4 4M13.6 6.5l-3.2 11"/>',
      ul: '<path d="M11 5h9M11 12h9M11 19h9"/><circle cx="5.2" cy="5" r="1.2" fill="currentColor" stroke="none"/><circle cx="5.2" cy="12" r="1.2" fill="currentColor" stroke="none"/><circle cx="5.2" cy="19" r="1.2" fill="currentColor" stroke="none"/>',
      ol: '<path d="M11 5h9M11 12h9M11 19h9"/><path stroke-width=".9" d="M3.9 4 5.2 3v4M3.9 10.9c.1-.7.6-1.1 1.3-1.1s1.2.4 1.2 1.1c0 .4-.3.8-.7 1.1L3.9 13.6h2.7M3.9 17.6c.2-.6.6-.9 1.2-.9.8 0 1.2.4 1.2.9s-.4.9-1.1.9c.7 0 1.3.3 1.3.9s-.6 1-1.4 1c-.7 0-1.1-.3-1.3-.8"/>',
      task: '<path d="M18.5 12.5v4.8a2.2 2.2 0 0 1-2.2 2.2H6.7a2.2 2.2 0 0 1-2.2-2.2V7.7a2.2 2.2 0 0 1 2.2-2.2h8.8"/><path d="m8.5 11.5 3 3L20 6"/>',
      outdent: '<path d="M20 5H9M20 12h-7M20 19H9M7 9.5 3.5 12 7 14.5"/>',
      indent: '<path d="M20 5H9M20 12h-7M20 19H9M3.5 9.5 7 12l-3.5 2.5"/>',
      link: '<path d="M10 13.5a4.2 4.2 0 0 0 6 .3l3-3a4.2 4.2 0 0 0-6-6l-1.2 1.2M14 10.5a4.2 4.2 0 0 0-6-.3l-3 3a4.2 4.2 0 0 0 6 6l1.2-1.2"/>',
      quote: '<path d="M4.5 11V8.4c0-1.4.9-2.5 2.3-2.9M4.5 11h3v3.5h-3zM10.5 11V8.4c0-1.4.9-2.5 2.3-2.9M10.5 11h3v3.5h-3zM17 8h3M16 11.5h4M4.5 19h15.5"/>',
      table: '<rect x="3" y="4" width="18" height="16" rx="2.2"/><path d="M3 9.5h18M3 14.5h18M9 4v16"/>',
      rule: '<path d="M3 12h18M5 6.5h2.5M10.8 6.5h2.4M16.5 6.5H19M5 17.5h2.5M10.8 17.5h2.4M16.5 17.5H19"/>',
      rowAdd: '<rect x="3" y="3" width="18" height="12" rx="2"/><path d="M3 9h18M12 18v4M10 20h4"/>',
      rowDel: '<rect x="3" y="3" width="18" height="12" rx="2"/><path d="M3 9h18M10 20h4"/>',
      colAdd: '<rect x="3" y="3" width="12" height="18" rx="2"/><path d="M9 3v18M18 10v4M16 12h4"/>',
      colDel: '<rect x="3" y="3" width="12" height="18" rx="2"/><path d="M9 3v18M16 12h4"/>',
      codeblock: '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="m10 9-3 3 3 3M14 9l3 3-3 3"/>',
      image: '<rect x="3" y="4" width="18" height="16" rx="3"/><circle cx="9" cy="10" r="1.6"/><path d="m4 18 5-5 4 4 3-3 4 4"/>',
      diagram: '<rect x="3" y="3.5" width="7" height="5.5" rx="1.5"/><rect x="14" y="3.5" width="7" height="5.5" rx="1.5"/><rect x="8.5" y="15" width="7" height="5.5" rx="1.5"/><path d="M6.5 9v2.5h11V9M12 11.5V15"/>',
      formula: '<path d="M18 5H7l5.5 7L7 19h11"/>',
      note: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
      back: '<path d="m15 5-7 7 7 7"/>',
      trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    };
    // Every icon is drawn on a 24-grid and then fitted to the same 18-unit square with the same stroke weight,
    // so none looks bigger or heavier than its neighbours.
    function icon(name) { return '<svg class="edit-icon" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><g>' + ICONS[name] + '</g></svg>'; }
    function fitIcons(root) {
      for (const svg of root.querySelectorAll('svg.edit-icon:not([data-fit])')) {
        const g = svg.firstElementChild; if (!g) continue;
        try {
          const box = g.getBBox(); if (!box.width && !box.height) continue;
          const scale = Math.min(17 / Math.max(box.width, 1), 17 / Math.max(box.height, 1), 1.6);
          const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
          g.setAttribute('transform', 'translate(12 12) scale(' + scale.toFixed(4) + ') translate(' + (-cx).toFixed(3) + ' ' + (-cy).toFixed(3) + ')');
          svg.setAttribute('data-fit', '1');
        } catch (e) { /* not rendered yet: retried on the next build / refresh */ }
      }
    }
    const CARET = '<svg class="edit-caret" viewBox="0 0 10 6" width="8" height="5" aria-hidden="true"><path d="M0 0h10L5 6z" fill="currentColor"/></svg>';
    // ----- 下拉菜单 -----
    let menu = null;
    // ----- 表格大小选择（悬停表格项，在右侧弹出网格）-----
    let picker = null;
    function closePicker() { if (picker) { picker.remove(); picker = null; } }
    function showPicker(anchorItem) {
      if (picker) return;
      const SIZE = 8;
      picker = document.createElement('div'); picker.className = 'edit-menu edit-picker'; picker.setAttribute('aria-label', t('Table size', '表格大小'));
      const head = document.createElement('div'); head.className = 'edit-picker-head';
      const title = document.createElement('span'); title.textContent = t('Table', '表格');
      const size = document.createElement('span'); size.className = 'edit-picker-size'; size.textContent = '0 × 0';
      head.append(title, size);
      const grid = document.createElement('div'); grid.className = 'edit-picker-grid'; grid.style.gridTemplateColumns = 'repeat(' + SIZE + ', 22px)';
      const cells = [];
      for (let r = 1; r <= SIZE; r++) for (let c = 1; c <= SIZE; c++) {
        const cell = document.createElement('button'); cell.type = 'button'; cell.className = 'edit-picker-cell'; cell.dataset.r = r; cell.dataset.c = c; cell.setAttribute('aria-label', r + ' × ' + c);
        cell.addEventListener('mousedown', e => e.preventDefault());
        cell.addEventListener('mouseenter', () => paint(r, c));
        cell.addEventListener('click', () => { closeMenu(); insertTable(r, c); requestAnimationFrame(refresh); });
        cells.push(cell); grid.append(cell);
      }
      function paint(r, c) { size.textContent = r + ' × ' + c; for (const cell of cells) cell.classList.toggle('on', +cell.dataset.r <= r && +cell.dataset.c <= c); }
      picker.append(head, grid); document.body.append(picker);
      const box = anchorItem.getBoundingClientRect();
      const left = box.right + 6 + picker.offsetWidth > innerWidth - 8 ? box.left - picker.offsetWidth - 6 : box.right + 6;
      picker.style.left = Math.max(8, left) + 'px'; picker.style.top = Math.max(8, Math.min(box.top - 6, innerHeight - picker.offsetHeight - 8)) + 'px';
    }
    function closeMenu() { closePicker(); if (menu) { menu.remove(); menu = null; } }
    function openMenu(anchor, items) {
      const same = menu && menu.anchor === anchor; closeMenu(); if (same) return;
      menu = document.createElement('div'); menu.className = 'edit-menu'; menu.setAttribute('role', 'menu'); menu.anchor = anchor;
      for (const [label, action, kind, iconName, glyph] of items) {
        const item = document.createElement('button'); item.type = 'button'; item.setAttribute('role', 'menuitem'); item.dataset.kind = kind;
        item.innerHTML = (glyph ? '<span class="edit-glyph" aria-hidden="true">' + glyph + '</span>' : iconName ? icon(iconName) : '') + '<span></span>'; item.lastChild.textContent = label;
        item.addEventListener('mousedown', e => e.preventDefault());
        item.addEventListener('click', () => { closeMenu(); action(); requestAnimationFrame(refresh); });
        if (kind === 'table') { item.classList.add('has-sub'); item.addEventListener('mouseenter', () => showPicker(item)); }
        else item.addEventListener('mouseenter', closePicker);
        menu.append(item);
      }
      document.body.append(menu); fitIcons(menu);
      const box = anchor.getBoundingClientRect(); menu.style.left = Math.max(8, Math.min(box.left, innerWidth - menu.offsetWidth - 8)) + 'px'; menu.style.top = (box.bottom + 4) + 'px';
    }
    document.addEventListener('mousedown', e => { if (menu && !menu.contains(e.target) && !(picker && picker.contains(e.target)) && !(menu.anchor && menu.anchor.contains(e.target))) closeMenu(); }, true);
    const insertItems = () => [
      [t('Table', '表格'), insertTable, 'table', 'table'],
      [t('Code block', '代码块'), insertCodeBlock, 'codeblock', 'codeblock'],
      [t('Image…', '图片…'), insertImage, 'image', 'image'],
      [t('Diagram', '流程图'), insertDiagram, 'diagram', 'diagram'],
      [t('Formula', '公式'), insertMath, 'formula', 'formula'],
      [t('Note', '提示块'), insertNote, 'note', 'note'],
      [t('Divider', '分隔线'), () => run('insertHorizontalRule'), 'rule', 'rule']];
    const headingName = n => [t('Heading 1', '一级标题'), t('Heading 2', '二级标题'), t('Heading 3', '三级标题'), t('Heading 4', '四级标题'), t('Heading 5', '五级标题'), t('Heading 6', '六级标题')][n - 1];
    const styleItems = () => [[t('Body', '正文'), () => run('formatBlock', 'p'), 'p', null, 'T'], ...[1, 2, 3, 4, 5, 6].map(n => [headingName(n), () => { if (!inside('h' + n)) run('formatBlock', 'h' + n); }, 'h' + n, null, 'H<sub>' + n + '</sub>'])];
    // type: icon = 单个图标；menu = 带文字和下拉箭头
    const buttons = [
      { type: 'menu', icon: 'plus', label: () => t('Insert', '插入'), title: t('Insert', '插入'), items: insertItems, kind: 'insert' },
      '|',
      { icon: 'undo', title: t('Undo (⌘Z)', '撤销 (⌘Z)'), action: () => { content.focus(); document.execCommand('undo'); }, kind: 'undo' },
      { icon: 'redo', title: t('Redo (⇧⌘Z)', '重做 (⇧⌘Z)'), action: () => { content.focus(); document.execCommand('redo'); }, kind: 'redo' },
      { icon: 'eraser', title: t('Clear formatting', '清除格式'), action: clearFormat, kind: 'clear' },
      '|',
      { type: 'menu', label: () => { for (let n = 1; n <= 6; n++) if (inside('h' + n)) return headingName(n); return t('Body', '正文'); }, title: t('Text style', '文字样式'), items: styleItems, kind: 'style' },
      '|',
      { icon: 'bold', title: t('Bold (⌘B)', '加粗 (⌘B)'), action: () => run('bold'), kind: 'bold' },
      { icon: 'italic', title: t('Italic (⌘I)', '斜体 (⌘I)'), action: () => run('italic'), kind: 'italic' },
      { icon: 'strike', title: t('Strikethrough', '删除线'), action: () => run('strikeThrough'), kind: 'strike' },
      { icon: 'code', title: t('Code', '代码'), action: toggleCode, kind: 'code' },
      '|',
      { icon: 'ul', title: t('Bulleted list', '无序列表'), action: () => run('insertUnorderedList'), kind: 'ul' },
      { icon: 'ol', title: t('Numbered list', '有序列表'), action: () => run('insertOrderedList'), kind: 'ol' },
      { icon: 'task', title: t('Task list', '任务列表'), action: addTask, kind: 'task' },
      { icon: 'outdent', title: t('Decrease indent (lists and quotes)', '减少缩进（列表与引用）'), action: indentLess, kind: 'outdent' },
      { icon: 'indent', title: t('Increase indent', '增加缩进'), action: indentMore, kind: 'indent' },
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
      const button = document.createElement('button'); button.type = 'button'; button.dataset.tip = spec.title; button.dataset.kind = spec.kind;
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
      bar.append(done); fitIcons(bar);
    }
    function refresh() {
      if (bar.querySelector('input') || bar.hidden) return;
      if (!bar.firstChild) build();
      fitIcons(bar);
      const enabled = name => { try { return document.queryCommandEnabled(name); } catch (e) { return true; } };
      const active = { bold: !!inside('strong, b'), italic: !!inside('em, i'), strike: !!inside('s, del, strike'),
        code: !!inside('code'), link: !!inside('a'), ul: !!inside('ul'), ol: !!inside('ol'), quote: !!inside('blockquote'), task: !!inside('li[data-task]') };
      const off = blocked();
      for (const button of bar.querySelectorAll('button')) {
        const kind = button.dataset.kind;
        button.classList.toggle('on', !!active[kind]);
        if (button.labelFn) button.labelFn();
        if (kind === 'done') continue;
        button.disabled = off || (kind === 'undo' && !enabled('undo')) || (kind === 'redo' && !enabled('redo')) || (kind === 'outdent' && !canOutdent());
      }
      const group = bar.querySelector('.edit-table-group'); if (group) group.hidden = !inside('table');
    }
    function show() {
      if (content.classList.contains('hidden')) return;
      editing = true; document.body.classList.add('is-editing');
      clearTimeout(leaveTimer); bar.classList.remove('leaving');
      if (bar.hidden) { bar.hidden = false; if (!bar.firstChild) build(); }
      refresh();
    }
    let leaveTimer = 0;
    function hide() {
      closeMenu(); hideTip(); editing = false; document.body.classList.remove('is-editing');
      if (bar.hidden) return;
      const calm = !(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches);
      if (!calm) { bar.hidden = true; bar.textContent = ''; return; }
      bar.classList.add('leaving');
      clearTimeout(leaveTimer);
      leaveTimer = setTimeout(() => { if (bar.classList.contains('leaving')) { bar.hidden = true; bar.textContent = ''; bar.classList.remove('leaving'); } }, 190);
    }
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

    // ----- 渲染模式下的格式快捷键：⌘B 加粗、⌘I 斜体、⌘K 链接 -----
    content.addEventListener('keydown', e => {
      if (!e.metaKey || e.ctrlKey || e.altKey || e.shiftKey || e.isComposing) return;
      const key = e.key.toLowerCase();
      if (!['b', 'i', 'k'].includes(key) || content.classList.contains('hidden') || blocked()) return;
      e.preventDefault(); e.stopPropagation();
      if (!editing) show();
      if (key === 'b') run('bold'); else if (key === 'i') run('italic'); else linkEditor();
      requestAnimationFrame(refresh);
    }, true);
    // ----- 表格里的键盘：Enter / Tab 在单元格间移动，不会把表格拆坏 -----
    function stepCell(forward, vertical) {
      const info = cellInfo(); if (!info) return;
      const rows = [...info.table.rows], at = info.rowIndex, col = info.index;
      let row = at, c = col;
      if (vertical) row = forward ? at + 1 : at - 1;
      else if (forward) { c = col + 1; if (c >= info.row.cells.length) { c = 0; row = at + 1; } }
      else { c = col - 1; if (c < 0) { row = at - 1; c = info.row.cells.length - 1; } }
      if (row < 0) return;
      if (row >= rows.length) {
        rewrite(info, copy => { const fresh = document.createElement('tr'); for (let i = 0; i < info.row.cells.length; i++) fresh.append(blankCell(false)); (copy.tBodies[0] || copy.createTBody()).append(fresh); }, row, c);
        return;
      }
      placeCaret(rows[row].cells[Math.min(c, rows[row].cells.length - 1)]);
    }
    content.addEventListener('keydown', e => {
      if (e.isComposing || e.metaKey || e.ctrlKey || e.altKey || !cellInfo()) return;
      if (e.key === 'Enter') { e.preventDefault(); if (!e.shiftKey) stepCell(true, true); }
      else if (e.key === 'Tab') { e.preventDefault(); stepCell(!e.shiftKey, false); }
      else if (e.key === 'Backspace' || e.key === 'Delete') {
        const s = getSelection(); if (!s.isCollapsed || !s.rangeCount) return;
        const cell = cellInfo().cell, r = s.getRangeAt(0), probe = document.createRange(); probe.selectNodeContents(cell);
        if (e.key === 'Backspace') { probe.setEnd(r.startContainer, r.startOffset); if (!probe.toString().length && !probe.cloneContents().querySelector('img')) e.preventDefault(); }
        else { probe.setStart(r.endContainer, r.endOffset); if (!probe.toString().length) e.preventDefault(); }
      }
    }, true);
    // ----- 工具栏提示：悬停约 0.15 秒就出现 -----
    let tip = null, tipTimer = 0;
    function hideTip() { clearTimeout(tipTimer); if (tip) { tip.remove(); tip = null; } }
    function tipFor(button) {
      const text = button.dataset.tip; if (!text) return;
      hideTip();
      tipTimer = setTimeout(() => {
        tip = document.createElement('div'); tip.className = 'edit-tip'; tip.textContent = text; document.body.append(tip);
        const box = button.getBoundingClientRect();
        tip.style.left = Math.max(6, Math.min(box.left + box.width / 2 - tip.offsetWidth / 2, innerWidth - tip.offsetWidth - 6)) + 'px';
        tip.style.top = (box.bottom + 6) + 'px';
      }, 150);
    }
    bar.addEventListener('mouseover', e => { const b = e.target.closest('button'); if (b && bar.contains(b)) tipFor(b); });
    bar.addEventListener('mouseout', e => { if (e.target.closest('button')) hideTip(); });
    bar.addEventListener('mousedown', hideTip);
    window.FormatToolbarKit = { icon, fitIcons, CARET, openMenu, closeMenu, addButton };
    return { refresh, bar, safeHref, setPinned, togglePinned, isEditing: () => editing, isPinned: () => pinned, leave };
  }
  return { create, safeHref };
})();
document.addEventListener('DOMContentLoaded', () => { window.formatToolbar = FormatToolbar.create({ setPinned: v => { try { Bridge.callSafe('set_settings', { format_bar: v }); } catch (e) {} } }); });
