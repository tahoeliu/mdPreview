/* 长文阅读辅助：只读覆盖层（顶部细进度线和位置标记），不改动文档 DOM，不参与导出。
   原则：安静、可忽略、对短文档完全不出现。 */
window.ReadingProgress = (() => {
  const CJK = /[㐀-鿿豈-﫿぀-ヿ가-힯]/g;
  const WORD = /[A-Za-z0-9À-ɏ]+(?:['’-][A-Za-z0-9À-ɏ]+)*/g;
  const CJK_PER_MIN = 450, WORDS_PER_MIN = 230, MIN_SCREENS = 2.5;

  // 估算阅读分钟数：代码块只按一半计，数学/图表不计。
  function estimateMinutes(root) {
    if (!root) return 0;
    let text = '';
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: (node) => node.parentElement && node.parentElement.closest('.math-block, .math-inline, .mermaid-diagram, svg, .frontmatter, script, style')
        ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT });
    let codeChars = 0;
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (node.parentElement.closest('pre')) codeChars += node.nodeValue.length; else text += node.nodeValue + ' ';
    }
    const cjk = (text.match(CJK) || []).length;
    const words = (text.replace(CJK, ' ').match(WORD) || []).length;
    return cjk / CJK_PER_MIN + words / WORDS_PER_MIN + codeChars / 2 / 900;
  }

  function create(deps = {}) {
    const scroller = deps.scroller || document.querySelector('.scroll-wrap');
    const content = deps.content || document.getElementById('content');
    const page = deps.page || document.getElementById('page');
    const t = deps.t || ((en, zh) => (window.I18n && I18n.t ? I18n.t(en, zh) : en));
    if (!scroller || !content || !page) return null;

    const bar = document.createElement('div'); bar.className = 'read-progress'; bar.setAttribute('aria-hidden', 'true');
    const fill = document.createElement('div'); bar.append(fill);
    const end = document.createElement('div'); end.className = 'read-end'; end.hidden = true;
    const svg = d => '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + d + '</svg>';
    end.innerHTML = '<div class="read-end-mark"><span aria-hidden="true">mdPreview</span></div><div class="read-end-actions"></div>';
    const actions = end.querySelector('.read-end-actions');
    for (const [icon, title, run] of [
      ['<rect x="8" y="8" width="12" height="12" rx="2.5"/><path d="M16 8V6.5A2.5 2.5 0 0 0 13.5 4h-7A2.5 2.5 0 0 0 4 6.5v7A2.5 2.5 0 0 0 6.5 16H8"/>', t('Copy as Markdown', '复制 Markdown 全文'), () => window.copyAsMarkdown && copyAsMarkdown()],
      ['<path d="M7 3h7l5 5v13H7zM14 3v5h5M12 12v5m-2.5-2.5L12 17l2.5-2.5"/>', t('Export…', '导出…'), () => window.exportAs && exportAs()],
      ['<path d="M12 15V3M8 7l4-4 4 4M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7"/>', t('Share…', '共享…'), e => { const r = e.currentTarget.getBoundingClientRect(); try { Bridge.callSafe('share_document', Math.round(r.left + r.width / 2), Math.round(r.top)); } catch (x) {} }],
    ]) {
      const b = document.createElement('button'); b.type = 'button'; b.title = title; b.setAttribute('aria-label', title); b.innerHTML = svg(icon);
      b.addEventListener('click', run); actions.append(b);
    }
    document.body.append(bar); page.append(end);

    // Make the name exactly as wide as the row of buttons under it.
    function fitName() {
      const name = end.querySelector('.read-end-mark span'), row = end.querySelector('.read-end-actions');
      if (!name || !row || end.hidden) return;
      const target = row.getBoundingClientRect().width; if (!target) return;
      name.style.fontSize = '20px';
      const width = name.getBoundingClientRect().width; if (!width) return;
      name.style.fontSize = (20 * target / width).toFixed(2) + 'px';
    }
    let frame = 0;

    function update() {
      frame = 0;
      const preview = !content.classList.contains('hidden') && content.isConnected &&
        !document.documentElement.hasAttribute('data-output');
      end.hidden = !(preview && content.textContent.trim());
      if (!end.hidden) fitName();
      const height = scroller.clientHeight;
      const long = preview && scroller.scrollHeight > height * MIN_SCREENS;
      bar.classList.toggle('on', long);
      if (!long) return;
      const progress = Math.min(1, Math.max(0, scroller.scrollTop / (scroller.scrollHeight - height)));
      fill.style.transform = 'scaleX(' + progress.toFixed(4) + ')';
    }
    function schedule() { if (!frame) frame = requestAnimationFrame(update); }

    // A thin position marker replaces the scrollbar: visible while scrolling and ~2 s after.
    const thumb = document.createElement('div'); thumb.className = 'read-thumb'; document.body.append(thumb);
    let thumbTimer = 0;
    function showThumb() {
      const box = scroller.getBoundingClientRect(), range = scroller.scrollHeight - scroller.clientHeight;
      if (range <= 1 || document.documentElement.hasAttribute('data-output')) { thumb.classList.remove('on'); return; }
      const track = box.height - 16, size = Math.max(32, track * scroller.clientHeight / scroller.scrollHeight);
      thumb.style.height = size.toFixed(1) + 'px';
      thumb.style.top = (box.top + 8 + (track - size) * Math.min(1, Math.max(0, scroller.scrollTop / range))).toFixed(1) + 'px';
      thumb.classList.add('on');
      clearTimeout(thumbTimer);
      thumbTimer = setTimeout(() => thumb.classList.remove('on'), 1800);
    }
    scroller.addEventListener('scroll', showThumb, { passive: true });
    scroller.addEventListener('scroll', schedule, { passive: true });
    new MutationObserver(schedule).observe(content, { childList: true });
    window.addEventListener('resize', schedule);
    schedule();
    return { bar, end, thumb };
  }

  return { create, estimateMinutes };
})();
document.addEventListener('DOMContentLoaded', () => { window.readingProgress = ReadingProgress.create(); });
