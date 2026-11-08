// 目录布局、滚动跟踪与双视图定位：由入口显式注入依赖。
window.DocumentOutline = {
  create(deps) {
    const {
      document, window, Node, NodeFilter, history, getComputedStyle, requestAnimationFrame, escHtml, t, 
      getPageWidth, placeCaretAtSafeRenderedLanding, state,
    } = deps;
    function syncTocToggle(hidden) {
      const toggle = document.getElementById('tocToggle');
      if (!toggle) return;
      toggle.classList.toggle('collapsed', hidden);
      toggle.setAttribute('aria-expanded', hidden ? 'false' : 'true');
      toggle.setAttribute('aria-label', hidden ? t('Show outline', '显示大纲') : t('Hide outline', '隐藏大纲'));
      toggle.setAttribute('title', hidden ? t('Show outline', '显示大纲') : t('Hide outline', '隐藏大纲'));
    }


    function isTocAutoHideWidth() {
      return window.innerWidth < deps.TOC_AUTO_HIDE_WIDTH;
    }

    function shouldAutoShowToc() {
      return state.tocHasContent && !isTocAutoHideWidth();
    }

    // 目录宽度随标题长度与窗口宽度自适应：最长标题决定理想宽度，夹在 188–300px 且不超过窗口的 28%。
    let tocMeasure = null;
    function computeTocWidth(entries) {
      const base = deps.TOC_WIDTH || 200;
      if (!entries || !entries.length || /jsdom/i.test(navigator.userAgent)) return base;
      try {
        tocMeasure = tocMeasure || document.createElement('canvas').getContext('2d');
        const style = getComputedStyle(document.getElementById('tocSidebar'));
        tocMeasure.font = '600 ' + style.fontSize + ' ' + style.fontFamily;
        let widest = 0;
        for (const { text, indent } of entries) widest = Math.max(widest, tocMeasure.measureText(text).width + indent);
        const ideal = Math.ceil(widest + 16 + 12);
        return Math.round(Math.max(188, Math.min(ideal, 300, window.innerWidth * 0.28)));
      } catch (e) { return base; }
    }
    function tocWidthNow() { return computeTocWidth(state.tocEntries); }

    function updateTocAwarePageLayout() {
      const page = document.getElementById('page');
      if (!page) return;

      if (!document.body.classList.contains('has-toc')) {
        page.style.removeProperty('--toc-aware-page-left');
        page.style.removeProperty('--toc-aware-page-width');
        return;
      }

      const tw = tocWidthNow();
      const windowWidth = window.innerWidth;
      document.getElementById('tocSidebar').style.width = tw + 'px';
      const pageWidth = getPageWidth();
      const compressedWidth = Math.max(0, windowWidth - tw);
      let targetWidth = Math.min(pageWidth, compressedWidth);
      let targetLeft = tw;

      if (windowWidth > tw + pageWidth) {
        targetWidth = pageWidth;
        const rightPaneCenterMaxWidth = Math.max(deps.TOC_RIGHT_PANE_CENTER_MAX_WIDTH, tw * 2 + pageWidth);
        const rightPaneCenteredLeft = tw + (Math.min(windowWidth, rightPaneCenterMaxWidth) - tw - pageWidth) / 2;
        const fullWindowCenteredLeft = (windowWidth - pageWidth) / 2;
        targetLeft = windowWidth <= rightPaneCenterMaxWidth + tw
          ? rightPaneCenteredLeft
          : fullWindowCenteredLeft;
      }

      page.style.setProperty('--toc-aware-page-left', Math.round(targetLeft) + 'px');
      page.style.setProperty('--toc-aware-page-width', Math.round(targetWidth) + 'px');
    }

    function setTocVisible(visible) {
      const toc = document.getElementById('tocSidebar');
      const show = !!visible && state.tocHasContent;
      toc.classList.toggle('hidden', !show);
      document.body.classList.toggle('has-toc', show);
      syncTocToggle(!show);
      updateTocAwarePageLayout();
    }

    function applyTocVisibility() {
      if (isTocAutoHideWidth() && state.tocManualOverride !== true) {
        setTocVisible(false);
        return;
      }
      setTocVisible(state.tocManualOverride === null ? shouldAutoShowToc() : state.tocManualOverride);
    }

    function handleTocResize() {
      if (isTocAutoHideWidth()) {
        state.tocManualOverride = null;
        setTocVisible(false);
        return;
      }
      applyTocVisibility();
      updateTocAwarePageLayout();
      if (!state.isSource) scheduleScrollSpy();
    }

    function buildToc(container) {
      const toc = document.getElementById('tocSidebar');
      const toggle = document.getElementById('tocToggle');
      const headings = Array.from(container.querySelectorAll('h1, h2, h3, h4, h5, h6'));
      const visibleHeadingLevels = Array.from(new Set(headings
        .map(h => parseInt(h.tagName.slice(1), 10))
        .filter(level => Number.isFinite(level))))
        .sort((a, b) => a - b);
      state.tocHasContent = headings.length >= 2;
      if (toggle) toggle.style.display = state.tocHasContent ? '' : 'none';
      state.tocEntries = headings.map(h => ({ text: h.textContent.trim(), indent: Math.max(0, visibleHeadingLevels.indexOf(parseInt(h.tagName.slice(1), 10))) * 12 }));
      toc.innerHTML = '<ul>' + headings.map((h, index) => {
        const level = parseInt(h.tagName.slice(1), 10);
        const relativeIndent = Math.max(0, visibleHeadingLevels.indexOf(level)) * 12;
        return `<li><a class="toc-level-${level}" style="padding-left: ${relativeIndent}px;" href="#${encodeURIComponent(h.id)}" data-target="${escHtml(h.id)}">${escHtml(h.textContent)}</a></li>`;
      }).join('') + '</ul>';
      applyTocVisibility();
      setupScrollSpy(headings);
      // Re-sync the highlight once layout settles (e.g. after mermaid reflow).
      requestAnimationFrame(() => { if (!state.isSource) updateScrollSpy(); });
    }

    // ── Scroll-spy: keep the TOC highlight in sync with the rendered view ──
    // Deterministic geometric spy: the "current" heading is the last heading
    // whose top has scrolled to/above a small band near the top of the
    // viewport. This replaces the previous IntersectionObserver-based spy,
    // whose result depended on WHEN the browser delivered intersection
    // callbacks (throttled/coalesced differently in WKWebView vs Blink) and on
    // the exact landing geometry of the scroll, so it could disagree with the
    // entry the user actually clicked. An explicitly-clicked TOC target
    // (explicitTocTarget) temporarily wins over the spy until the user scrolls.
    let scrollSpyRaf = null;
    function setupScrollSpy(headings) {
      if (!headings || headings.length === 0) return;
      updateScrollSpy();
    }

    function updateScrollSpy() {
      if (state.isSource) return; // source mode maintains its own highlight
      if (explicitTocTarget) return; // a click is in flight; don't clobber it
      const content = document.getElementById('content');
      const toc = document.getElementById('tocSidebar');
      if (!content || !toc) return;
      const headings = Array.from(content.querySelectorAll('h1, h2, h3, h4, h5, h6'));
      const links = toc.querySelectorAll('a');
      if (headings.length === 0 || links.length === 0) return;
      const scrollY = document.querySelector('.scroll-wrap').scrollTop;
      let currentId = null;
      for (const h of headings) {
        if (h.offsetTop - TOC_SPY_BAND <= scrollY) currentId = h.id;
        else break;
      }
      if (!currentId) currentId = headings[0].id;
      setTocActive(currentId);
      ensureTocActiveVisible();
    }

    function scheduleScrollSpy() {
      if (scrollSpyRaf) return;
      scrollSpyRaf = requestAnimationFrame(() => { scrollSpyRaf = null; updateScrollSpy(); });
    }

    // Mode-aware scroll handler: as soon as the user scrolls (i.e. the wrap
    // moves away from the position our own code last set programmatically),
    // the explicitly-clicked target expires and the spy takes over again.
    function scheduleTocSync() {
      const wrap = document.querySelector('.scroll-wrap');
      if (explicitTocTarget && wrap && Math.abs(wrap.scrollTop - lastProgrammaticScrollTop) > 2) {
        explicitTocTarget = null;
      }
      if (state.isSource) scheduleSourceTocHighlight();
      else scheduleScrollSpy();
    }

    function toggleToc() {
      const toc = document.getElementById('tocSidebar');
      state.tocManualOverride = toc.classList.contains('hidden');
      setTocVisible(state.tocManualOverride);
    }


    function slugifyHeading(text) {
      return (text || '')
        .trim()
        .toLowerCase()
        .replace(/[\s\u00A0]+/g, '-')
        .replace(/[^\w\-\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]/g, '')
        .replace(/-+/g, '-')
        .replace(/^-|-$/g, '') || 'heading';
    }

    function applyHeadingAnchors(container) {
      const used = new Map();
      container.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach((heading) => {
        let id = heading.getAttribute('id') || slugifyHeading(heading.textContent);
        const count = used.get(id) || 0;
        used.set(id, count + 1);
        if (count > 0) id = id + '-' + count;
        heading.setAttribute('id', id);
      });
    }

    function scrollToHash(hash) {
      if (!hash || hash === '#') return false;
      const raw = hash.slice(1);
      let id = raw;
      try { id = decodeURIComponent(raw); } catch (e) {}

      // In source mode, scroll the textarea to the heading line instead of
      // looking for a DOM element (which only exists in rendered mode).
      if (state.isSource) {
        const textarea = document.getElementById('textarea');
        const md = textarea.value;
        const line = findHeadingLineInMarkdown(md, id);
        if (line >= 0) {
          let pos = 0;
          const lines = md.split('\n');
          for (let i = 0; i < line; i++) {
            pos += lines[i].length + 1;
          }
          textarea.setSelectionRange(pos, pos);
          // Scroll first, then focus with preventScroll: focusing a textarea
          // reveals the caret and may scroll its scrollport, which would fight
          // the explicit scroll (and WKWebView can do so asynchronously).
          scrollTextareaToLine(line);
          try { textarea.focus({ preventScroll: true }); } catch (e) { textarea.focus(); }
          markExplicitTocTarget(id);
          return true;
        }
        return false;
      }

      const target = document.getElementById(id) || document.getElementById(raw);
      if (!target) return false;
      // Highlight the clicked entry immediately (explicit user intent) instead
      // of relying on the scroll-spy to observe where the scroll landed, and
      // scroll with the same measured math used elsewhere (a plain
      // scrollIntoView leaves the final geometry up to the engine).
      if (window.Folding) Folding.reveal(target);
      markExplicitTocTarget(id);
      scrollToTocTarget(id);
      // Reflect the jump in the URL; harmless if the engine refuses on file://.
      try {
        if (history && history.replaceState) history.replaceState(null, '', '#' + encodeURIComponent(target.id));
      } catch (e) {}
      return true;
    }


    // ── TOC-based position sync ──
    // When toggling between source and rendered modes, instead of trying to
    // map the exact cursor position (which is fragile), we use the currently
    // active TOC entry as the anchor point and scroll to that heading.

    function getActiveTocTarget() {
      const toc = document.getElementById('tocSidebar');
      if (!toc) return null;
      const active = toc.querySelector('a.toc-active');
      return active ? active.getAttribute('data-target') : null;
    }

    // The heading is "current" when its top is at/above this band below the
    // viewport top. Used by both the rendered-mode scroll-spy and the
    // source-mode reference line so the two modes agree on the active heading.
    const TOC_SPY_BAND = 80;

    // The heading the user explicitly clicked (or that a mode switch scrolled
    // to). While set, the scroll-spy keeps its hands off the highlight, so the
    // entry the user chose stays highlighted even when the landing geometry
    // disagrees (e.g. a heading near the document end that cannot reach the
    // top of the viewport). Cleared as soon as the user scrolls.
    let explicitTocTarget = null;
    // The scrollTop our own code last set programmatically; used by
    // scheduleTocSync() to tell programmatic scrolls from user-initiated ones.
    let lastProgrammaticScrollTop = -1;

    function setTocActive(headingId) {
      const toc = document.getElementById('tocSidebar');
      if (!toc) return;
      toc.querySelectorAll('a').forEach((a) => {
        const active = a.getAttribute('data-target') === headingId;
        a.classList.toggle('toc-active', active);
        if (active) a.setAttribute('aria-current', 'true');
        else a.removeAttribute('aria-current');
      });
    }

    function markExplicitTocTarget(headingId) {
      explicitTocTarget = headingId || null;
      if (explicitTocTarget) setTocActive(headingId);
    }

    // Place the caret at the very start of a rendered heading. Used before
    // focusing the contenteditable so the browser's reveal-caret scroll points
    // at the heading instead of the document start.
    function placeCaretAtHeading(headingId) {
      if (!headingId) return;
      const h = document.getElementById(headingId);
      if (!h) return;
      const sel = window.getSelection();
      if (!sel) return;
      const range = document.createRange();
      const node = h.firstChild && h.firstChild.nodeType === Node.TEXT_NODE ? h.firstChild : h;
      range.setStart(node, 0);
      range.collapse(true);
      sel.removeAllRanges();
      sel.addRange(range);
    }

    // Collect every heading line in a markdown source together with its slug,
    // applying the SAME duplicate-suffix rule as applyHeadingAnchors() uses for
    // the rendered DOM ("foo", "foo-1", "foo-2"). Without this, the source-side
    // lookup produced the plain slug for repeated headings while the rendered
    // heading had a -N suffix, so TOC clicks and highlight sync missed (or hit
    // the wrong copy of) duplicate headings. Fence-aware: heading-looking lines
    // inside ``` fenced code blocks are ignored.
    let cachedHeadingText = null;
    let cachedHeadings = [];
    function collectMarkdownHeadingSlugs(md) {
      if (md === cachedHeadingText) return cachedHeadings;
      const slugs = [];
      const used = new Map();
      const lines = md.split('\n');
      let inFence = false;
      let fenceMarker = '';
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const fm = line.match(/^[ \t]*(`{3,}|~{3,})/);
        if (fm) {
          if (!inFence) { inFence = true; fenceMarker = fm[1][0]; }
          else if (fm[1][0] === fenceMarker) { inFence = false; }
          continue;
        }
        if (inFence) continue;
        const m = line.match(/^(#{1,6})\s+(.+)$/);
        if (!m) continue;
        let slug = slugifyHeading(m[2].trim().replace(/\s+#+\s*$/, ''));
        const count = used.get(slug) || 0;
        used.set(slug, count + 1);
        if (count > 0) slug = slug + '-' + count;
        slugs.push({ line: i, slug });
      }
      cachedHeadingText = md;
      cachedHeadings = slugs;
      return slugs;
    }

    function findHeadingLineInMarkdown(md, headingId) {
      if (!headingId) return -1;
      const found = collectMarkdownHeadingSlugs(md).find((s) => s.slug === headingId);
      return found ? found.line : -1;
    }

    // ── Source-mode geometry ──
    // All source-mode positioning is based on the browser's ACTUAL rendered
    // geometry of the highlight layer (Range.getClientRects), never on
    // line-number × line-height math. The math is invalid for two reasons:
    //  1. The rendered line pitch can differ from CSS line-height (native
    //     text rendering / sub-pixel rounding), an error that accumulates
    //     linearly with depth.
    //  2. Long lines WRAP under white-space:pre-wrap, so a logical line is
    //     several visual lines tall; a "top = lineN × pitch" formula lands
    //     below the real heading (this is why the caret was correct — the
    //     browser placed it at the true geometry — but the content was not at
    //     the top of the viewport).

    // Top (in the scroll-wrap's content coordinates) of the given logical line
    // of the highlight layer — i.e. the scrollTop that puts that line at the
    // very top of the viewport. Empty lines return null.
    function sourceLineTop(line) {
      const layer = document.getElementById('highlightLayer');
      const wrap = document.querySelector('.scroll-wrap');
      if (!layer || !wrap || !state._sourceLineStarts) return null;
      const start = state._sourceLineStarts[line];
      if (start === undefined) return null;
      const nl = state._sourceLayerText.indexOf('\n', start);
      const end = nl === -1 ? state._sourceLayerText.length : nl;
      if (end === start) return null; // empty line
      const range = findRangeBetween(layer, start, end);
      if (!range) return null;
      const rects = range.getClientRects();
      if (!rects || !rects.length) return null;
      const wrapRect = wrap.getBoundingClientRect();
      return rects[0].top - wrapRect.top + wrap.scrollTop;
    }

    // Scroll the source view so that the given logical line sits `offset`
    // pixels below the top of the viewport, using its measured real position.
    function scrollTextareaToLine(line, offset = 12) {
      if (line < 0) return;
      const wrap = document.querySelector('.scroll-wrap');
      const top = sourceLineTop(line);
      if (top === null) return;
      wrap.scrollTo({ top: Math.max(0, top - offset), behavior: 'auto' });
      lastProgrammaticScrollTop = wrap.scrollTop;
    }

    function scrollToTocTarget(headingId) {
      if (!headingId) return;
      const target = document.getElementById(headingId);
      if (!target) return;
      const wrap = document.querySelector('.scroll-wrap');
      if (wrap) {
        // Scroll the wrap directly so the heading lands near the top — more
        // reliable than scrollIntoView inside the embedded WebView.
        const top = target.getBoundingClientRect().top - wrap.getBoundingClientRect().top + wrap.scrollTop - 20;
        wrap.scrollTo({ top: Math.max(0, top), behavior: 'auto' });
        lastProgrammaticScrollTop = wrap.scrollTop;
      } else {
        target.scrollIntoView({ behavior: 'auto', block: 'start' });
      }
    }

    function syncPositionToSource() {
      const textarea = document.getElementById('textarea');
      const md = textarea.value;
      const headingId = getActiveTocTarget();
      const line = findHeadingLineInMarkdown(md, headingId);
      if (line >= 0) {
        const lines = md.split('\n');
        let pos = 0;
        for (let i = 0; i < line; i++) {
          pos += lines[i].length + 1;
        }
        textarea.setSelectionRange(pos, pos);
        scrollTextareaToLine(line);
      }
      try { textarea.focus({ preventScroll: true }); } catch (e) { textarea.focus(); }
      updateSourceTocHighlight();
    }

    // Called after switching to rendered mode: scroll the rendered content to
    // the heading that was active in the TOC. The heading id is captured by the
    // caller BEFORE re-rendering, because renderMarkdown() -> buildToc() rebuilds
    // the TOC and clears the active class.
    function syncPositionToRendered(headingId) {
      const content = document.getElementById('content');
      if (headingId === undefined) headingId = getActiveTocTarget();
      if (!headingId) {
        placeCaretAtSafeRenderedLanding(content);
        return;
      }
      scrollToTocTarget(headingId);
      // Place the caret at the target heading BEFORE focusing: focusing a
      // contenteditable reveals the caret and scrolls it into view, and with
      // no caret at the target the browser scrolls back to the document start
      // (observed in both WKWebView and Blink).
      placeCaretAtHeading(headingId);
      try { content.focus({ preventScroll: true }); } catch (e) { content.focus(); }
      // Focus can trigger an async reveal-caret scroll; run the final
      // positioning after it so the heading always ends up at the top.
      scrollToTocTarget(headingId);
      markExplicitTocTarget(headingId);
      ensureTocActiveVisible();
    }

    // ── TOC active-state tracking & auto-reveal ──
    // In source mode the rendered headings don't exist, so the TOC highlight is
    // derived from the markdown itself: the most recent heading whose REAL
    // rendered position (measured from the highlight layer) is at/above the top
    // band of the viewport. In both modes the TOC sidebar auto-scrolls to keep
    // the active entry visible, but only when that entry has scrolled outside
    // the TOC's visible range.

    // The slug of the heading that defines "where the user is" in source mode:
    // the heading under the caret when the caret is inside the visible viewport
    // (so moving the caret tracks the outline), otherwise the last heading
    // whose measured top is within TOC_SPY_BAND of the viewport top. Both
    // cases use the highlight layer's real rendered geometry, never line math.
    function sourceActiveHeadingSlug() {
      const textarea = document.getElementById('textarea');
      const wrap = document.querySelector('.scroll-wrap');
      if (!textarea || !wrap) return null;
      const headings = collectMarkdownHeadingSlugs(textarea.value);
      if (headings.length === 0) return null;
      const lastHeadingAtOrAbove = (refLine) => {
        let active = null;
        for (const s of headings) {
          if (s.line > refLine) break;
          active = s.slug;
        }
        return active;
      };
      // Caret inside the visible viewport → follow the caret's heading.
      if (document.activeElement === textarea) {
        const pos = textarea.selectionStart;
        const cursorLine = (textarea.value.slice(0, pos).match(/\n/g) || []).length;
        const cursorTop = sourceLineTop(cursorLine);
        if (cursorTop !== null && cursorTop >= wrap.scrollTop && cursorTop <= wrap.scrollTop + wrap.clientHeight) {
          return lastHeadingAtOrAbove(cursorLine);
        }
      }
      // Otherwise the last heading at/above the top band of the viewport.
      const limit = wrap.scrollTop + TOC_SPY_BAND;
      let active = null;
      let low = 0, high = headings.length - 1;
      while (low <= high) {
        const middle = (low + high) >> 1;
        const top = sourceLineTop(headings[middle].line);
        if (top !== null && top <= limit) { active = headings[middle].slug; low = middle + 1; }
        else high = middle - 1;
      }
      return active;
    }

    // Scroll the TOC panel so the active entry is visible — only when it has
    // scrolled outside the TOC's visible range (up or down).
    function ensureTocActiveVisible() {
      const toc = document.getElementById('tocSidebar');
      if (!toc || toc.classList.contains('hidden')) return;
      const active = toc.querySelector('a.toc-active');
      if (!active) return;
      const tocTop = toc.getBoundingClientRect().top;
      const style = getComputedStyle(toc);
      const padTop = parseFloat(style.paddingTop) || 0;
      const padBottom = parseFloat(style.paddingBottom) || 0;
      const viewTop = tocTop + padTop;
      const viewBottom = tocTop + toc.clientHeight - padBottom;
      const actTop = active.getBoundingClientRect().top;
      const actBottom = active.getBoundingClientRect().bottom;
      if (actTop >= viewTop && actBottom <= viewBottom) return;
      if (actTop < viewTop) {
        toc.scrollTo({ top: Math.max(0, toc.scrollTop - (viewTop - actTop) - 4), behavior: 'smooth' });
      } else {
        toc.scrollTo({ top: toc.scrollTop + (actBottom - viewBottom) + 4, behavior: 'smooth' });
      }
    }

    function updateSourceTocHighlight() {
      if (!state.isSource) return;
      if (explicitTocTarget) return; // a click is in flight; don't clobber it
      const toc = document.getElementById('tocSidebar');
      if (!toc) return;
      const slug = sourceActiveHeadingSlug();
      let found = false;
      toc.querySelectorAll('a').forEach(a => {
        const on = slug !== null && a.getAttribute('data-target') === slug;
        a.classList.toggle('toc-active', on);
        if (on) found = true;
      });
      if (found) ensureTocActiveVisible();
    }

    // Fallback: derive the target heading directly from the current source
    // position, independent of TOC highlight state.
    function getSourceActiveHeading() {
      return sourceActiveHeadingSlug();
    }

    let sourceTocHighlightRaf = null;
    function scheduleSourceTocHighlight() {
      if (!state.isSource) return;
      if (sourceTocHighlightRaf) return;
      sourceTocHighlightRaf = requestAnimationFrame(() => {
        sourceTocHighlightRaf = null;
        updateSourceTocHighlight();
      });
    }

    function findRangeBetween(root, startOff, endOff) {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
      let current = 0;
      let sn = null, so = 0, en = null, eo = 0;
      let node;
      while (node = walker.nextNode()) {
        const len = node.textContent.length;
        if (!sn && current + len >= startOff) { sn = node; so = Math.min(startOff - current, len); }
        if (current + len >= endOff) { en = node; eo = Math.min(endOff - current, len); break; }
        current += len;
      }
      if (!sn) return null;
      const range = document.createRange();
      range.setStart(sn, so);
      range.setEnd(en || sn, en ? eo : so);
      return range;
    }


    return {
      syncTocToggle, isTocAutoHideWidth, shouldAutoShowToc, updateTocAwarePageLayout, setTocVisible, 
      applyTocVisibility, handleTocResize, buildToc, setupScrollSpy, updateScrollSpy, scheduleScrollSpy, 
      scheduleTocSync, toggleToc, slugifyHeading, applyHeadingAnchors, scrollToHash, getActiveTocTarget, 
      setTocActive, markExplicitTocTarget, placeCaretAtHeading, collectMarkdownHeadingSlugs, 
      findHeadingLineInMarkdown, sourceLineTop, scrollTextareaToLine, scrollToTocTarget, syncPositionToSource, 
      syncPositionToRendered, sourceActiveHeadingSlug, ensureTocActiveVisible, updateSourceTocHighlight, 
      getSourceActiveHeading, scheduleSourceTocHighlight, findRangeBetween,
    };
  }
};
