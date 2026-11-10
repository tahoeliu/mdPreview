/* 折叠：点击标题左侧的小箭头收起/展开整节；很长的代码块和表格默认只显示开头，点击展开。
   折叠按钮放在 #content 之外的覆盖层里，折叠状态只是 CSS 类，不会进入 Markdown 或任何导出。 */
window.Folding = (() => {
  const CODE_LINES = 28, CODE_SHOW = 18;
  const t = (en, zh) => (window.I18n && I18n.t ? I18n.t(en, zh) : en);
  const HEADING = /^H[1-6]$/;
  let hoveredHeading = null, content = null, layer = null, folded = new Set(), observer = null, frame = 0;

  function level(h) { return +h.tagName[1]; }
  function hasBody(h) { const n = h.nextElementSibling; return !!n && !(HEADING.test(n.tagName) && level(n) <= level(h)); }
  function ensureLayer() {
    if (layer && layer.isConnected) return layer;
    const page = document.getElementById('page'); if (!page) return null;
    layer = document.createElement('div'); layer.className = 'fold-layer'; page.append(layer);
    return layer;
  }
  // 重新计算哪些块被隐藏
  function apply() {
    if (!content) return;
    let hideBelow = null;
    for (const el of content.children) {
      if (HEADING.test(el.tagName)) {
        const hidden = hideBelow !== null && level(el) > hideBelow;
        el.classList.toggle('fold-hidden', hidden);
        if (!hidden) hideBelow = folded.has(el) ? level(el) : null;
        el.classList.toggle('fold-collapsed', folded.has(el) && !hidden);
      } else el.classList.toggle('fold-hidden', hideBelow !== null);
    }
    place();
  }
  function place() {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      const host = ensureLayer(); if (!host || !content) return;
      host.textContent = '';
      if (content.classList.contains('hidden') || window.innerWidth < 760) return;
      const pr = document.getElementById('page').getBoundingClientRect(), cr = content.getBoundingClientRect();
      for (const h of content.querySelectorAll(':scope > h1, :scope > h2, :scope > h3, :scope > h4')) {
        if (h.classList.contains('fold-hidden') || !hasBody(h)) continue;
        const rect = h.getBoundingClientRect(), line = parseFloat(getComputedStyle(h).lineHeight) || rect.height;
        const button = document.createElement('button'); button.type = 'button'; button.className = 'fold-toggle';
        const isFolded = folded.has(h);
        button.classList.toggle('collapsed', isFolded);
        button.setAttribute('aria-expanded', String(!isFolded));
        button.setAttribute('aria-label', (isFolded ? t('Expand section: {title}', '展开本节：{title}') : t('Collapse section: {title}', '收起本节：{title}')).replace('{title}', h.textContent.trim()));
        button.title = isFolded ? t('Expand section', '展开本节') : t('Collapse section', '收起本节');
        button.style.top = (rect.top - pr.top + (Math.min(line, rect.height) - 16) / 2) + 'px';
        button.style.left = (cr.left - pr.left - 20) + 'px';
        button.addEventListener('click', () => toggle(h));
        button._heading = h;
        if (h === hoveredHeading) button.classList.add('show');
        host.append(button);
      }
    });
  }
  function toggle(h) { if (folded.has(h)) folded.delete(h); else folded.add(h); apply(); }
  function setAll(fold) {
    folded.clear();
    if (fold) for (const h of content.querySelectorAll(':scope > h2, :scope > h3')) if (hasBody(h)) folded.add(h);
    apply();
  }
  // 让 el 可见：展开包含它的所有折叠
  function reveal(el) {
    if (!content || !el || !content.contains(el)) return;
    let top = el; while (top && top.parentElement !== content) top = top.parentElement;
    if (!top) return;
    let changed = false;
    const more = el.closest && el.closest('.is-folded, .has-folded-rows');
    if (more) { expandBlock(more); changed = true; }
    if (top.classList.contains('fold-hidden') || (HEADING.test(top.tagName) && false)) {
      let need = Infinity;
      for (let n = top.previousElementSibling; n; n = n.previousElementSibling) {
        if (HEADING.test(n.tagName) && level(n) < need) { need = level(n); if (folded.delete(n)) changed = true; }
      }
    }
    if (changed) apply();
  }
  // ----- 长代码块 / 长表格 -----
  function expandBlock(block) {
    block.classList.remove('is-folded', 'has-folded-rows');
    block.querySelectorAll('.row-folded').forEach(r => r.classList.remove('row-folded'));
    const anchor = block.closest('.table-wrap') || block; const btn = anchor.nextElementSibling; if (btn && btn.classList.contains('fold-more')) btn.hidden = true;
    place();
  }
  function moreButton(block, count, unit) {
    const button = document.createElement('button'); button.type = 'button'; button.className = 'fold-more'; button.contentEditable = 'false';
    button.textContent = (unit === 'rows' ? t('Show all {n} rows', '显示全部 {n} 行') : t('Show all {n} lines', '显示全部 {n} 行')).replace('{n}', count);
    button.addEventListener('click', e => { e.preventDefault(); e.stopPropagation(); expandBlock(block); });
    (block.closest('.table-wrap') || block).after(button);
  }
  function foldLong(root) {
    for (const pre of root.querySelectorAll(':scope > pre')) {
      const count = (pre.querySelector('code')?.textContent || pre.textContent).replace(/\n$/, '').split('\n').length;
      if (count <= CODE_LINES || pre.nextElementSibling?.classList.contains('fold-more')) continue;
      pre.classList.add('is-folded'); pre.style.setProperty('--fold-lines', CODE_SHOW); moreButton(pre, count, 'lines');
    }
    // Long tables are never folded: every row is always shown and editable.
  }
  function decorate(root) {
    if (!root || root.id !== 'content') return;
    content = root; folded = new Set(); wireHover();
    root.querySelectorAll('.fold-more').forEach(b => b.remove());
    foldLong(root);
    apply();
    if (!observer && window.ResizeObserver) { observer = new ResizeObserver(place); observer.observe(root); window.addEventListener('resize', place); }
  }

  // The small arrow shows only while the pointer is on its heading (or on the arrow itself); collapsed sections keep a faint one so they stay recognisable.
  let hideTimer = 0;
  function showArrowFor(heading) {
    clearTimeout(hideTimer); hoveredHeading = heading;
    for (const b of document.querySelectorAll('.fold-toggle')) b.classList.toggle('show', b._heading === heading);
  }
  function scheduleArrowHide() { clearTimeout(hideTimer); hideTimer = setTimeout(() => { hoveredHeading = null; for (const b of document.querySelectorAll('.fold-toggle.show')) b.classList.remove('show'); }, 250); }
  let hoverWired = false;
  function wireHover() {
    if (hoverWired || !content) return; hoverWired = true;
    content.addEventListener('mouseover', e => { const h = e.target.closest && e.target.closest('h1, h2, h3, h4'); if (h && content.contains(h)) showArrowFor(h); else scheduleArrowHide(); });
    content.addEventListener('mouseleave', scheduleArrowHide);
    document.addEventListener('mouseover', e => { const b = e.target.closest && e.target.closest('.fold-toggle'); if (b) showArrowFor(b._heading); });
  }
  return { decorate, toggle, setAll, reveal, apply, place, isFolded: h => folded.has(h) };
})();
