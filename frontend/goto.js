/* 跳转到标题（⌘J）：长文档里按名称快速定位；只读，不改文档。 */
window.GoToHeading = (() => {
  function match(query, text) {
    const q = query.trim().toLowerCase(), s = text.toLowerCase();
    if (!q) return 1;
    const at = s.indexOf(q);
    if (at >= 0) return 1000 - at;          // 子串优先，越靠前越好
    let i = 0;                              // 否则按字符顺序的模糊匹配
    for (const ch of s) if (ch === q[i] && ++i === q.length) return 1;
    return 0;
  }
  function rank(items, query) {
    return items.map((item, order) => ({ item, order, score: match(query, item.text) }))
      .filter(x => x.score > 0)
      .sort((a, b) => b.score - a.score || a.order - b.order).map(x => x.item);
  }
  function headings(root) {
    return [...root.querySelectorAll('h1,h2,h3,h4,h5,h6')]
      .map(el => ({ el, level: Number(el.tagName[1]), text: el.textContent.trim() })).filter(x => x.text);
  }
  function open() {
    const content = document.getElementById('content');
    const T = (en, zh) => (window.I18n && I18n.t ? I18n.t(en, zh) : en);
    if (!content || content.classList.contains('hidden')) { showStatus(T('Switch to preview to jump to a heading', '请先切换到预览再跳转标题')); return; }
    const all = headings(content);
    if (!all.length) { showStatus(T('This document has no headings', '此文档没有标题')); return; }
    close();
    const overlay = document.createElement('div'); overlay.className = 'goto-overlay'; overlay.id = 'gotoOverlay';
    const box = document.createElement('div'); box.className = 'goto-box'; box.setAttribute('role', 'dialog'); box.setAttribute('aria-label', T('Go to heading', '跳转到标题'));
    const input = document.createElement('input'); input.type = 'text'; input.placeholder = T('Go to heading…', '跳转到标题…'); input.setAttribute('aria-label', input.placeholder);
    const list = document.createElement('ul'); list.setAttribute('role', 'listbox');
    box.append(input, list); overlay.append(box); document.body.append(overlay);
    let shown = [], active = 0;
    function render() {
      shown = rank(all, input.value).slice(0, 80); active = Math.min(active, Math.max(0, shown.length - 1));
      list.textContent = '';
      for (const [index, item] of shown.entries()) {
        const li = document.createElement('li'); li.setAttribute('role', 'option'); li.style.paddingLeft = (12 + (item.level - 1) * 14) + 'px';
        li.textContent = item.text; if (index === active) li.className = 'active';
        li.addEventListener('mousedown', e => { e.preventDefault(); go(item); });
        list.append(li);
      }
      if (!shown.length) { const li = document.createElement('li'); li.className = 'empty'; li.textContent = T('No matching heading', '没有匹配的标题'); list.append(li); }
      list.querySelector('.active')?.scrollIntoView({ block: 'nearest' });
    }
    function go(item) {
      close();
      const wrap = document.querySelector('.scroll-wrap');
      if (wrap) wrap.scrollTo({ top: Math.max(0, item.el.getBoundingClientRect().top - wrap.getBoundingClientRect().top + wrap.scrollTop - 20), behavior: 'auto' });
      else item.el.scrollIntoView({ block: 'start' });
    }
    input.addEventListener('input', () => { active = 0; render(); });
    input.addEventListener('keydown', e => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
      else if (e.key === 'ArrowDown') { e.preventDefault(); active = Math.min(shown.length - 1, active + 1); render(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); active = Math.max(0, active - 1); render(); }
      else if (e.key === 'Enter') { e.preventDefault(); if (shown[active]) go(shown[active]); }
    });
    input.addEventListener('blur', () => setTimeout(close, 120));
    overlay.addEventListener('mousedown', e => { if (e.target === overlay) close(); });
    render(); input.focus();
  }
  function close() { document.getElementById('gotoOverlay')?.remove(); }
  return { open, close, rank, match, headings };
})();
window.openGoToHeading = () => GoToHeading.open();
