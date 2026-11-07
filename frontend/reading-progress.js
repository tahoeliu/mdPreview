/* 长文阅读辅助：只读覆盖层（顶部细进度线 + 右下角剩余时间），不改动文档 DOM，不参与导出。
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

  // 每个标题到下一个同级或更高级标题之间的阅读分钟数（取整），用于大纲里的"这一节要读多久"。
  function sectionMinutes(headings) {
    const sizes = headings.map(h => {
      let text = '', node = h.nextElementSibling;
      const level = Number(h.tagName[1]);
      while (node && !(/^H[1-6]$/.test(node.tagName) && Number(node.tagName[1]) <= level)) {
        if (!/^H[1-6]$/.test(node.tagName)) text += node.textContent + ' ';
        node = node.nextElementSibling;
      }
      const cjk = (text.match(CJK) || []).length;
      return cjk / CJK_PER_MIN + (text.replace(CJK, ' ').match(WORD) || []).length / WORDS_PER_MIN;
    });
    return sizes.map(m => Math.round(m));
  }

  function label(minutes) {
    const m = Math.max(0, Math.round(minutes));
    return m < 1 ? null : m;
  }

  function create(deps = {}) {
    const scroller = deps.scroller || document.querySelector('.scroll-wrap');
    const content = deps.content || document.getElementById('content');
    const page = deps.page || document.getElementById('page');
    const t = deps.t || ((en, zh) => (window.I18n && I18n.t ? I18n.t(en, zh) : en));
    if (!scroller || !content || !page) return null;

    const bar = document.createElement('div'); bar.className = 'read-progress'; bar.setAttribute('aria-hidden', 'true');
    const fill = document.createElement('div'); bar.append(fill);
    const hud = document.createElement('div'); hud.className = 'read-hud'; hud.setAttribute('aria-hidden', 'true');
    const end = document.createElement('div'); end.className = 'read-end'; end.setAttribute('aria-hidden', 'true'); end.hidden = true;
    document.body.append(bar, hud); page.append(end);

    let total = 0, measured = -1, hideTimer = 0, frame = 0;

    function isLong() {
      return !content.classList.contains('hidden') && content.isConnected &&
        scroller.scrollHeight > scroller.clientHeight * MIN_SCREENS &&
        !document.documentElement.hasAttribute('data-output');
    }
    function measure() {
      const size = content.textContent.length;
      if (size === measured) return;
      measured = size; total = estimateMinutes(content);
    }
    function textFor(progress) {
      const left = total * (1 - progress), n = label(left);
      const pct = Math.round(progress * 100) + '%';
      return (n === null ? t('Almost done', '快读完了') : t('{n} min left', '还剩约 {n} 分钟').replace('{n}', n)) + ' · ' + pct;
    }
    function update(reveal) {
      frame = 0;
      if (!isLong()) { bar.classList.remove('on'); hud.classList.remove('on'); end.hidden = true; return; }
      measure();
      const range = scroller.scrollHeight - scroller.clientHeight;
      const progress = range > 0 ? Math.min(1, Math.max(0, scroller.scrollTop / range)) : 0;
      fill.style.transform = 'scaleX(' + progress.toFixed(4) + ')';
      bar.classList.add('on');
      const total1 = label(total);
      end.hidden = false;
      end.textContent = total1 ? t('End · about {n} min read', '全文完 · 约 {n} 分钟').replace('{n}', total1) : t('End', '全文完');
      if (progress >= 0.995) { hud.classList.remove('on'); return; }
      hud.textContent = scroller.scrollTop < 8 && reveal === 'open'
        ? t('About {n} min read', '约 {n} 分钟读完').replace('{n}', label(total) || 1)
        : textFor(progress);
      hud.classList.add('on');
      clearTimeout(hideTimer);
      hideTimer = setTimeout(() => hud.classList.remove('on'), reveal === 'open' ? 3500 : 1800);
    }
    function schedule(reveal) { if (!frame) frame = requestAnimationFrame(() => update(reveal)); }

    scroller.addEventListener('scroll', () => schedule('scroll'), { passive: true });
    new MutationObserver(() => { measured = -1; schedule('open'); }).observe(content, { childList: true });
    window.addEventListener('resize', () => schedule('scroll'));
    schedule('open');
    return { update, measure, estimateMinutes, bar, hud, end };
  }

  return { create, estimateMinutes, sectionMinutes };
})();
document.addEventListener('DOMContentLoaded', () => { window.readingProgress = ReadingProgress.create(); });
