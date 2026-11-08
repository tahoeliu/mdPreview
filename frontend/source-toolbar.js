/* 代码（源码）模式的顶部工具栏：默认显示；按钮直接在 Markdown 文本里加减语法，修改走 insertText，⌘Z 可撤销。 */
window.SourceToolbar = (() => {
  let bar = null;
  const t = (en, zh) => (window.I18n && I18n.t ? I18n.t(en, zh) : en);
  const ta = () => document.getElementById('textarea');
  const edit = (start, end, text, selection) => EditorFeatures.replace(ta(), start, end, text, selection);
  const lineBounds = () => {
    const el = ta(), v = el.value;
    const from = v.lastIndexOf('\n', el.selectionStart - 1) + 1;
    let to = v.indexOf('\n', el.selectionEnd); if (to < 0) to = v.length;
    if (el.selectionEnd > el.selectionStart && v[el.selectionEnd - 1] === '\n') to = el.selectionEnd - 1;
    return [from, to];
  };
  function wrap(marker) {
    const el = ta(), v = el.value, s = el.selectionStart, e = el.selectionEnd, picked = v.slice(s, e), n = marker.length;
    if (v.slice(s - n, s) === marker && v.slice(e, e + n) === marker) edit(s - n, e + n, picked, [s - n, e - n]);
    else if (picked) edit(s, e, marker + picked + marker, [s + n, e + n]);
    else edit(s, e, marker + marker, [s + n, s + n]);
  }
  function mapLines(fn) {
    const [from, to] = lineBounds(), lines = ta().value.slice(from, to).split('\n');
    const out = lines.map((line, i) => fn(line, i)).join('\n');
    edit(from, to, out, [from, from + out.length]);
  }
  const LIST = /^(\s*)(?:[-*+]|\d+\.)\s+(?:\[[ xX]\]\s+)?/;
  const strip = line => line.replace(LIST, '$1').replace(/^(\s*)>\s?/, '$1').replace(/^(\s*)#{1,6}\s+/, '$1');
  function heading(n) {
    mapLines(line => { const plain = line.replace(/^(\s*)#{1,6}\s+/, '$1'); return n ? '#'.repeat(n) + ' ' + plain.trimStart() : plain; });
  }
  function bullet(kind) {
    const el = ta(), [from, to] = lineBounds(), lines = el.value.slice(from, to).split('\n');
    const on = lines.every(l => (kind === 'ol' ? /^\s*\d+\.\s/.test(l) : kind === 'task' ? /^\s*[-*+]\s+\[[ xX]\]\s/.test(l) : /^\s*[-*+]\s/.test(l) && !/\[[ xX]\]\s/.test(l)));
    mapLines((line, i) => {
      const plain = strip(line).trimStart(), lead = line.match(/^\s*/)[0];
      if (on) return lead + plain;
      return lead + (kind === 'ol' ? (i + 1) + '. ' : kind === 'task' ? '- [ ] ' : '- ') + plain;
    });
  }
  function quote() {
    const [from, to] = lineBounds(), lines = ta().value.slice(from, to).split('\n');
    const on = lines.every(l => /^\s*>/.test(l));
    mapLines(line => on ? line.replace(/^(\s*)>\s?/, '$1') : '> ' + line);
  }
  const indent = more => mapLines(line => more ? '  ' + line : line.replace(/^( {1,2}|\t)/, ''));
  function link() {
    const el = ta(), s = el.selectionStart, e = el.selectionEnd, picked = el.value.slice(s, e) || t('link text', '链接文字');
    const url = 'https://';
    edit(s, e, '[' + picked + '](' + url + ')', [s + picked.length + 3, s + picked.length + 3 + url.length]);
  }
  function insertBlock(snippet, caret) {
    const el = ta(), v = el.value, at = v.indexOf('\n', el.selectionEnd) < 0 ? v.length : v.indexOf('\n', el.selectionEnd);
    const before = at === 0 || v.slice(0, at).endsWith('\n\n') ? '' : v.slice(0, at).endsWith('\n') ? '\n' : '\n\n';
    const text = before + snippet + '\n';
    const start = at + before.length;
    edit(at, at, text, caret != null ? [start + caret, start + caret] : [at + text.length, at + text.length]);
  }
  const TABLE = '| ' + t('Column', '列') + ' 1 | ' + t('Column', '列') + ' 2 | ' + t('Column', '列') + ' 3 |\n| --- | --- | --- |\n|  |  |  |\n|  |  |  |';
  const insertItems = () => [
    [t('Table', '表格'), () => insertBlock(TABLE), 'table', 'table'],
    [t('Code block', '代码块'), () => { const el = ta(), picked = el.value.slice(el.selectionStart, el.selectionEnd); insertBlock('```\n' + picked + '\n```', 4); }, 'codeblock', 'codeblock'],
    [t('Image…', '图片…'), () => { const p = document.createElement('input'); p.type = 'file'; p.accept = 'image/png,image/jpeg,image/gif,image/webp'; p.addEventListener('change', () => { if (p.files[0]) EditorFeatures.image(p.files[0]).catch(() => showStatus(t('Image save failed', '图片保存失败'), true)); }); p.click(); }, 'image', 'image'],
    [t('Diagram', '流程图'), () => insertBlock('```mermaid\ngraph TD\n  A[Start] --> B[Next step]\n  B --> C[Finish]\n```'), 'diagram', 'diagram'],
    [t('Formula', '公式'), () => insertBlock('$$\nE = mc^2\n$$'), 'formula', 'formula'],
    [t('Note', '提示块'), () => insertBlock('> [!NOTE]\n> ' + t('Write your note here.', '在这里写提示内容。')), 'note', 'note'],
    [t('Divider', '分隔线'), () => insertBlock('---'), 'rule', 'rule'],
  ];
  const headingName = n => [t('Heading 1', '一级标题'), t('Heading 2', '二级标题'), t('Heading 3', '三级标题'), t('Heading 4', '四级标题'), t('Heading 5', '五级标题'), t('Heading 6', '六级标题')][n - 1];
  const styleItems = () => [[t('Body', '正文'), () => heading(0), 'p', null, 'T'], ...[1, 2, 3, 4, 5, 6].map(n => [headingName(n), () => heading(n), 'h' + n, null, 'H<sub>' + n + '</sub>'])];
  const specs = () => [
    { type: 'menu', icon: 'plus', label: () => t('Insert', '插入'), title: t('Insert', '插入'), items: insertItems, kind: 'insert' }, '|',
    { icon: 'undo', title: t('Undo (⌘Z)', '撤销 (⌘Z)'), action: () => { ta().focus(); document.execCommand('undo'); }, kind: 'undo' },
    { icon: 'redo', title: t('Redo (⇧⌘Z)', '重做 (⇧⌘Z)'), action: () => { ta().focus(); document.execCommand('redo'); }, kind: 'redo' }, '|',
    { type: 'menu', label: () => t('Text style', '文字样式'), title: t('Text style', '文字样式'), items: styleItems, kind: 'style' }, '|',
    { icon: 'bold', title: t('Bold (⌘B)', '加粗 (⌘B)'), action: () => wrap('**'), kind: 'bold' },
    { icon: 'italic', title: t('Italic (⌘I)', '斜体 (⌘I)'), action: () => wrap('*'), kind: 'italic' },
    { icon: 'strike', title: t('Strikethrough', '删除线'), action: () => wrap('~~'), kind: 'strike' },
    { icon: 'code', title: t('Code', '代码'), action: () => wrap('`'), kind: 'code' }, '|',
    { icon: 'ul', title: t('Bulleted list', '无序列表'), action: () => bullet('ul'), kind: 'ul' },
    { icon: 'ol', title: t('Numbered list', '有序列表'), action: () => bullet('ol'), kind: 'ol' },
    { icon: 'task', title: t('Task list', '任务列表'), action: () => bullet('task'), kind: 'task' },
    { icon: 'outdent', title: t('Decrease indent', '减少缩进'), action: () => indent(false), kind: 'outdent' },
    { icon: 'indent', title: t('Increase indent', '增加缩进'), action: () => indent(true), kind: 'indent' }, '|',
    { icon: 'link', title: t('Link', '链接'), action: link, kind: 'link' },
    { icon: 'quote', title: t('Quote', '引用'), action: quote, kind: 'quote' },
  ];
  function build() {
    const kit = window.FormatToolbarKit; if (!kit || bar) return;
    bar = document.createElement('div'); bar.className = 'edit-bar source-bar'; bar.setAttribute('role', 'toolbar'); bar.setAttribute('aria-label', t('Format', '格式')); bar.hidden = true;
    document.body.append(bar);
    for (const item of specs()) {
      if (item === '|') { bar.append(Object.assign(document.createElement('span'), { className: 'edit-sep' })); continue; }
      kit.addButton(bar, item);
    }
    const mode = document.createElement('button'); mode.type = 'button'; mode.className = 'edit-mode'; mode.dataset.kind = 'mode'; mode.textContent = t('Preview', '预览'); mode.dataset.tip = t('Switch to Preview (⌘E)', '切换到预览 (⌘E)'); mode.setAttribute('aria-label', mode.dataset.tip);
    mode.addEventListener('click', () => { window.toggleView && toggleView(); });
    bar.append(mode);
    kit.fitIcons(bar);
    // buttons take no focus so the caret and selection stay in the text
    bar.addEventListener('mousedown', e => { if (!e.target.closest('input')) e.preventDefault(); });
  }
  function sync() {
    const kit = window.FormatToolbarKit; if (!kit) return;
    const show = !!(typeof isSource !== 'undefined' && isSource);
    if (show) build();
    if (!bar) return;
    if (show && bar.hidden) { bar.hidden = false; kit.fitIcons(bar); }
    else if (!show && !bar.hidden) { kit.closeMenu(); bar.hidden = true; }
    document.body.classList.toggle('has-source-bar', show);
  }
  return { sync, get bar() { return bar; } };
})();
