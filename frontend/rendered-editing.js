// 预览编辑块边界、引用换行及回写规范化：由入口显式注入依赖。
window.RenderedEditing = {
  create(deps) {
    const {
      document, window, Node, NodeFilter, Range, setDirty, schedulePythonSync, dismissWelcomeOverlay, 
      sanitizeHtmlString, state,
    } = deps;
    const RENDER_BLOCK_SELECTOR = 'p, h1, h2, h3, h4, h5, h6, li, blockquote';

    function isBlankRenderParagraph(el) {
      return !!(el && el.tagName === 'P' && !el.textContent.trim() && !el.querySelector('img, pre, table, .mermaid-diagram, .math-block'));
    }

    function lastTextNodeIn(el) {
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null, false);
      let last = null;
      while (walker.nextNode()) last = walker.currentNode;
      return last;
    }

    function placeCaretInRenderedBlock(el, atEnd) {
      const sel = window.getSelection();
      if (!sel || !el) return;
      const r = document.createRange();
      r.selectNodeContents(el);
      r.collapse(!atEnd);
      sel.removeAllRanges();
      sel.addRange(r);
    }

    function markRenderedContentEdited() {
      state.renderedDirty = true;
      setDirty(true);
      schedulePythonSync(deps.PYTHON_SYNC_DEBOUNCE_MS);
      dismissWelcomeOverlay();
    }

    function handleRenderedBlockEdgeDelete(e) {
      const content = document.getElementById('content');
      if (!content || !content.contains(e.target)) return;
      if (e.isComposing) return;
      const sel = window.getSelection();
      if (!sel || !sel.rangeCount || !sel.isCollapsed) return;
      const range = sel.getRangeAt(0);
      let blockEl = null;
      const node = range.startContainer;
      if (node.nodeType === Node.TEXT_NODE) blockEl = node.parentElement ? node.parentElement.closest(RENDER_BLOCK_SELECTOR) : null;
      else if (node.nodeType === Node.ELEMENT_NODE) blockEl = node.closest(RENDER_BLOCK_SELECTOR);
      if (!blockEl) return;
      const blockRange = document.createRange();
      blockRange.selectNodeContents(blockEl);
      if (e.key === 'Backspace') {
        const startRange = blockRange.cloneRange();
        startRange.collapse(true);
        if (range.compareBoundaryPoints(Range.START_TO_START, startRange) !== 0) return;
        e.preventDefault();
        mergeRenderedBlockWithPrevious(blockEl);
      } else {
        const endRange = blockRange.cloneRange();
        endRange.collapse(false);
        if (range.compareBoundaryPoints(Range.START_TO_START, endRange) !== 0) return;
        e.preventDefault();
        mergeRenderedBlockWithNext(blockEl);
      }
    }

    function mergeRenderedBlockWithPrevious(blockEl) {
      const prev = blockEl.previousElementSibling;
      if (!prev) return;
      // Backspace inside an empty paragraph deletes that blank paragraph.
      if (isBlankRenderParagraph(blockEl)) {
        blockEl.parentNode.removeChild(blockEl);
        markRenderedContentEdited();
        if (prev && prev.matches(RENDER_BLOCK_SELECTOR)) placeCaretInRenderedBlock(prev, true);
        return;
      }
      // Deleting a blank paragraph between two blocks removes the blank line.
      if (isBlankRenderParagraph(prev)) {
        prev.parentNode.removeChild(prev);
        markRenderedContentEdited();
        placeCaretInRenderedBlock(blockEl, false);
        return;
      }
      if (!prev.matches(RENDER_BLOCK_SELECTOR)) return; // tables/pre/mermaid are not merged
      const origLastText = lastTextNodeIn(prev);
      const frag = document.createDocumentFragment();
      while (blockEl.firstChild) frag.appendChild(blockEl.firstChild);
      prev.appendChild(frag);
      blockEl.parentNode.removeChild(blockEl);
      markRenderedContentEdited();
      const sel = window.getSelection();
      if (sel) {
        const r = document.createRange();
        if (origLastText) { r.setStart(origLastText, origLastText.length); r.collapse(true); }
        else { r.selectNodeContents(prev); r.collapse(false); }
        sel.removeAllRanges();
        sel.addRange(r);
      }
    }

    function mergeRenderedBlockWithNext(blockEl) {
      let next = blockEl.nextElementSibling;
      if (!next) return;
      if (isBlankRenderParagraph(blockEl)) {
        blockEl.parentNode.removeChild(blockEl);
        markRenderedContentEdited();
        if (next && next.matches(RENDER_BLOCK_SELECTOR)) placeCaretInRenderedBlock(next, false);
        return;
      }
      if (isBlankRenderParagraph(next)) {
        next.parentNode.removeChild(next);
        markRenderedContentEdited();
        placeCaretInRenderedBlock(blockEl, true);
        return;
      }
      if (!next.matches(RENDER_BLOCK_SELECTOR)) return;
      const origLastText = lastTextNodeIn(blockEl);
      const frag = document.createDocumentFragment();
      while (next.firstChild) frag.appendChild(next.firstChild);
      blockEl.appendChild(frag);
      next.parentNode.removeChild(next);
      markRenderedContentEdited();
      const sel = window.getSelection();
      if (sel) {
        const r = document.createRange();
        if (origLastText) { r.setStart(origLastText, origLastText.length); r.collapse(true); }
        else { r.selectNodeContents(blockEl); r.collapse(false); }
        sel.removeAllRanges();
        sel.addRange(r);
      }
    }

    // Rendered view: Enter inside a blockquote. Taken over from the browser
    // because WKWebView's native Enter inserts <div>/<p> junk inside the quote
    // (and on an empty quote line a NESTED blockquote). Those junk nodes then
    // round-trip through turndown as stray "> " blank lines: the preview grows
    // blank lines the source never had, and the source gains "> " lines the
    // user never typed. Standard editor behavior implemented here:
    //   - Enter on a non-empty quote line      -> new empty line inside the quote
    //   - Enter on the last (empty) quote line -> leave the quote: the empty
    //     line is removed and a new <p> is inserted after the blockquote
    // Content after the caret moves into the new line (native split semantics).
    // Note: like the merge helpers above, the manual DOM edit replaces the
    // native undo entry for this keystroke.
    function handleRenderedEnter(e) {
      const content = document.getElementById('content');
      if (!content || !content.contains(e.target)) return;
      if (e.isComposing || e.keyCode === 229) return;
      const sel = window.getSelection();
      if (!sel || !sel.rangeCount) return;
      const range = sel.getRangeAt(0);
      if (!range.collapsed) return; // selection replacement stays native
      const startNode = range.startContainer;
      const startEl = startNode.nodeType === Node.ELEMENT_NODE ? startNode : startNode.parentElement;
      if (!startEl) return;
      if (startEl.closest('pre, code, table, .mermaid-diagram, .math-block, .frontmatter')) return;
      const quote = startEl.closest('blockquote');
      if (!quote || !content.contains(quote)) return;
      // The line block the caret sits in (innermost block inside the quote).
      let line = startEl.closest('p, h1, h2, h3, h4, h5, h6, li, div');
      if (line && (!quote.contains(line) || line === quote)) return; // bare text in quote: stay native
      if (!line) return;
      e.preventDefault();
      // Extract the content after the caret: it moves into the new line.
      const tail = range.cloneRange();
      tail.setEnd(line, line.childNodes.length);
      const frag = tail.extractContents();
      const isBlankLine = !line.textContent.trim() && !line.querySelector('img');
      if (isBlankLine && !line.nextElementSibling) {
        // Leave the quote: drop this empty trailing line, then insert a fresh
        // paragraph after the blockquote. If the quote has no content left,
        // remove it entirely.
        const quoteParent = quote.parentNode;
        const quoteRef = quote.nextSibling;
        line.parentNode.removeChild(line);
        if (!quote.textContent.trim() && !quote.querySelector('img')) quoteParent.removeChild(quote);
        const p = document.createElement('p');
        p.appendChild(document.createElement('br'));
        quoteParent.insertBefore(p, quoteRef);
        placeCaretInRenderedBlock(p, false);
        markRenderedContentEdited();
        return;
      }
      // Continuation: a new line inside the quote, carrying the tail content.
      const tag = line.tagName === 'DIV' ? 'P' : line.tagName;
      const newLine = document.createElement(tag);
      if (frag.hasChildNodes()) newLine.appendChild(frag);
      else newLine.appendChild(document.createElement('br'));
      line.parentNode.insertBefore(newLine, line.nextSibling);
      placeCaretInRenderedBlock(newLine, false);
      markRenderedContentEdited();
    }

    // Prepares the rendered DOM for markdown conversion (turndown), fixing two
    // WebKit editing artifacts that would otherwise corrupt the round trip:
    //   1. Empty <p>/<div> line blocks (only a <br>) at the END of a blockquote
    //      get written back as stray "> " blank lines in the source — and those
    //      lines then re-render as even more blank quote lines in the preview.
    //      Trailing empty quote lines carry no information, so they are dropped.
    //      Empty lines in the MIDDLE of a quote are preserved ("> " separator).
    //   2. Paragraph-like <div>s inside a blockquote are inline content for
    //      turndown, which merges quote lines together; they become <p> first.
    //      Known wrapper divs (.table-wrap, .mermaid-diagram, ...) are excluded.
    // Also strips trailing <br> inside quote lines (WebKit keeps a placeholder
    // <br> after typing into an empty line).
    // Operates on a detached clone; the live preview DOM is never touched.
    function normalizeRenderedHtmlForTurndown(html) {
      try {
        const tmp = document.createElement('div');
        // Task checkboxes are buttons, which the sanitizer removes: turn them into marker spans first so "- [x]" survives edits.
        const pre = document.createElement('div'); pre.innerHTML = html;
        pre.querySelectorAll('.task-toggle').forEach((box) => {
          const mark = document.createElement('span'); mark.className = 'task-marker'; mark.textContent = 'x'; mark.setAttribute('data-task-marker', box.dataset.taskMarker || ''); box.replaceWith(mark);
        });
        // The sanitizer drops attribute values that contain "-->" (every Mermaid arrow), so raw sources travel base64-encoded.
        const RAW = ['data-source', 'data-raw', 'data-image-raw', 'data-resource-raw'];
        const encode = text => btoa(unescape(encodeURIComponent(text)));
        const decode = text => decodeURIComponent(escape(atob(text)));
        pre.querySelectorAll(RAW.map(n => '[' + n + ']').join(',')).forEach((el) => {
          for (const name of RAW) if (el.hasAttribute(name)) { el.setAttribute('data-mdp-b64-' + name.slice(5), encode(el.getAttribute(name))); el.removeAttribute(name); }
        });
        pre.querySelectorAll('.mermaid-diagram').forEach((el) => { el.textContent = 'x'; });   // the drawn SVG is output only; its labels must not leak into the text
        tmp.innerHTML = sanitizeHtmlString(pre.innerHTML);
        tmp.querySelectorAll('*').forEach((el) => {
          if (el.classList.contains('mermaid-diagram') && !el.textContent.trim()) el.textContent = 'x';   // empty elements are skipped by the converter
          for (const name of RAW) { const key = 'data-mdp-b64-' + name.slice(5); if (el.hasAttribute(key)) { try { el.setAttribute(name, decode(el.getAttribute(key))); } catch (e) {} el.removeAttribute(key); } }
        });
        tmp.querySelectorAll('blockquote').forEach((quote) => {
          // Nested quotes may already have been removed together with their
          // ancestor (forEach iterates a static snapshot) — guard each removal.
          quote.querySelectorAll('blockquote').forEach((nested) => {
            if (!nested.parentNode) return;
            if (!nested.textContent.trim() && !nested.querySelector('img')) nested.parentNode.removeChild(nested);
          });
          if (!quote.parentNode) return; // removed with an ancestor quote
          let child = quote.lastElementChild;
          while (child) {
            const prev = child.previousElementSibling;
            const isLineBlock = child.tagName === 'P' || child.tagName === 'DIV';
            const isEmptyLine = isLineBlock && !child.textContent.trim() &&
              !child.querySelector('img') && !child.querySelector('table, pre, ul, ol');
            if (isEmptyLine) child.parentNode.removeChild(child);
            else break;
            child = prev;
          }
          if (!quote.parentNode) return;
          if (!quote.textContent.trim() && !quote.querySelector('img')) {
            quote.parentNode.removeChild(quote);
            return;
          }
        });
        // Strip trailing <br> from every line block: WebKit keeps a placeholder
        // <br> after typing into an empty line, and a <br> at the very end of a
        // block never carries meaning — but it round-trips as a "  " (trailing
        // spaces) junk line in the markdown source.
        tmp.querySelectorAll('p, div').forEach((line) => {
          if (!line.parentNode) return;
          if (line.closest('.table-wrap, .mermaid-diagram, .math-block, .frontmatter')) return;
          while (line.lastElementChild && line.lastElementChild.tagName === 'BR') {
            line.removeChild(line.lastElementChild);
          }
        });
        // Paragraph-like <div>s inside a blockquote are inline content for
        // turndown, which merges quote lines together; they become <p> first.
        tmp.querySelectorAll('blockquote div').forEach((d) => {
          if (!d.parentNode) return;
          if (d.closest('.table-wrap, .mermaid-diagram, .math-block, .frontmatter')) return;
          if (d.querySelector('p, div, ul, ol, table, pre, blockquote, h1, h2, h3, h4, h5, h6, img, .mermaid-diagram, .math-block')) return;
          const p = document.createElement('p');
          while (d.firstChild) p.appendChild(d.firstChild);
          d.parentNode.replaceChild(p, d);
        });
        return tmp.innerHTML;
      } catch (err) {
        return html;
      }
    }


    return {
      isBlankRenderParagraph, lastTextNodeIn, placeCaretInRenderedBlock, markRenderedContentEdited, 
      handleRenderedBlockEdgeDelete, mergeRenderedBlockWithPrevious, mergeRenderedBlockWithNext, 
      handleRenderedEnter, normalizeRenderedHtmlForTurndown,
    };
  }
};
