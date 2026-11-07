// 剪贴板转换、质量提示与光标插入：由入口显式注入依赖。
window.MarkdownPaste = {
  create(deps) {
    const {
      document, window, DOMParser, NodeFilter, setTimeout, clearTimeout, t, setModal, showStatus, 
      ensureTurndown, insertMarkdownSnippet, sanitizeHtmlString, escHtml, balanceTableColumns, 
      rewriteRelativeImages, markRenderedContentEdited, state,
    } = deps;
    function normalizeWhitespace(s) {
      return String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
    }

    function showPasteHint() {
      const bubble = document.getElementById('editHintBubble');
      if (!bubble) return;
      const sizeBubble = document.getElementById('sizeHintBubble');
      if (sizeBubble) sizeBubble.classList.remove('visible');
      clearTimeout(state.sizeHintTimer);
      // Each key (⌘ / ⇧ / V) gets its own keycap frame.
      bubble.innerHTML = '<span class="edit-hint-keys">' +
        '<span class="edit-hint-key">⌘</span><span class="edit-hint-key">⇧</span><span class="edit-hint-key">V</span>' +
        '</span><span>' + t('to paste as Markdown', '粘贴为 Markdown') + '</span>';
      bubble.classList.add('visible');
      clearTimeout(state.editHintTimer);
      // Longer dwell than the edit hint so the reminder is not missed.
      state.editHintTimer = setTimeout(() => bubble.classList.remove('visible'), 4000);
    }

    // Preview-mode feedback: after a rich paste is converted to Markdown, show a
    // short confirmation bubble so the user knows the conversion happened.
    function showPastedAsMarkdownHint() {
      const bubble = document.getElementById('editHintBubble');
      if (!bubble) return;
      const sizeBubble = document.getElementById('sizeHintBubble');
      if (sizeBubble) sizeBubble.classList.remove('visible');
      clearTimeout(state.sizeHintTimer);
      bubble.innerHTML = '<span>' + t('Pasted as Markdown', '已粘贴为 Markdown') + '</span>';
      bubble.classList.add('visible');
      clearTimeout(state.editHintTimer);
      state.editHintTimer = setTimeout(() => bubble.classList.remove('visible'), 2000);
    }

    function readClipboardBest() {
      if (deps.Bridge.ready()) {
        return deps.Bridge.callSafe('read_clipboard');
      }
      return Promise.resolve({ format: 'none', content: '', plain: '' });
    }

    function stripHtmlToText(html) {
      if (!html || !html.trim()) return '';
      try {
        const doc = new DOMParser().parseFromString(html, 'text/html');
        return normalizeWhitespace((doc.body && doc.body.textContent) || '');
      } catch (e) {
        return normalizeWhitespace(String(html).replace(/<[^>]*>/g, ' '));
      }
    }

    function hasMarkdownSyntax(text) {
      const s = String(text || '').trim();
      if (!s) return false;
      return /(^|\n)\s{0,3}(#{1,6}\s+|([-*+]\s+)|\d+[.)]\s+|>\s+|(```+|~~~+)|[-*_]{3,}\s*$)/.test(s) ||
        /!\[[^\]]*\]\([^)]*\)|\[[^\]]+\]\([^)]*\)|`[^`]+`|\*\*[^*]+\*\*|__[^_]+__|~~[^~]+~~/.test(s) ||
        /(^|\n)\s*\|.+\|\s*(\n|$)/.test(s);
    }

    function elementHasMarkdownStyle(el) {
      const style = ((el && el.getAttribute && el.getAttribute('style')) || '').toLowerCase();
      if (!style || !normalizeWhitespace(el.textContent || '')) return false;
      return /font-weight\s*:\s*(bold|[6-9]00)\b/.test(style) ||
        /font-style\s*:\s*italic\b/.test(style) ||
        /text-decoration[^;]*(line-through|underline)/.test(style);
    }

    function htmlHasMarkdownConvertibleFormatting(html, plain) {
      if (!html || !html.trim()) return false;
      let doc;
      try {
        doc = new DOMParser().parseFromString(html, 'text/html');
      } catch (e) {
        return false;
      }
      const body = doc.body;
      if (!body || !normalizeWhitespace(body.textContent || '')) return false;

      // These tags produce meaningful Markdown syntax after conversion. Plain
      // text wrappers such as <p>, <div>, <span>, <br>, and style-only layout
      // markup are intentionally ignored to avoid reminders for normal text.
      if (body.querySelector('table, ul, ol, li, blockquote, pre, code, h1, h2, h3, h4, h5, h6, strong, b, em, i, s, del, hr')) return true;

      const link = body.querySelector('a[href]');
      if (link) {
        const href = normalizeWhitespace(link.getAttribute('href') || '');
        const text = normalizeWhitespace(link.textContent || '');
        if (href && text && href !== text) return true;
      }

      return Array.from(body.querySelectorAll('[style]')).some(elementHasMarkdownStyle);
    }

    function shouldShowSourcePasteHint(clip) {
      if (!clip) return false;
      if (clip.format === 'html') return htmlHasMarkdownConvertibleFormatting(clip.content, clip.plain);
      if (clip.format === 'markdown') return hasMarkdownSyntax(clip.content || clip.plain || '');
      return false;
    }

    function unwrapElement(el) {
      if (!el || !el.parentNode) return;
      const frag = el.ownerDocument.createDocumentFragment();
      while (el.firstChild) frag.appendChild(el.firstChild);
      el.parentNode.replaceChild(frag, el);
    }

    // Strip Office/Word cruft, unsupported elements (images, math, media) and
    // normalize code blocks before handing the HTML to turndown.
    function normalizePastedHtml(html) {
      if (!html || !html.trim()) return '';
      const doc = new DOMParser().parseFromString(html, 'text/html');
      // Remove comments (Word conditional comments, Safari StartFragment markers).
      const commentWalker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_COMMENT, null, false);
      const comments = [];
      let cnode;
      while ((cnode = commentWalker.nextNode())) comments.push(cnode);
      comments.forEach(c => c.parentNode && c.parentNode.removeChild(c));
      // Remove media/interactive/unsupported elements outright.
      doc.querySelectorAll('script, style, link, meta, title, head, iframe, object, embed, video, audio, canvas, svg, form, button, input, select, textarea, math, .katex, [class*="MathJax"], [class*="katex"]').forEach(el => {
        if (el.parentNode) el.parentNode.removeChild(el);
      });
      // Word/Outlook namespaced tags (o:p, v:*, w:*, m:*) and mso cruft: unwrap,
      // keeping their text content.
      doc.querySelectorAll('*').forEach(el => {
        const tag = (el.tagName || '').toLowerCase();
        const cls = (el.getAttribute && (el.getAttribute('class') || '')) || '';
        const name = (el.getAttribute && (el.getAttribute('name') || '')) || '';
        if (/^(o|v|w|l|m):/.test(tag) || /mso/i.test(cls) || /^_?mso/i.test(name)) unwrapElement(el);
      });
      // Drop all images (unsupported in v1).
      doc.querySelectorAll('img').forEach(el => {
        if (el.parentNode) el.parentNode.removeChild(el);
      });
      // Code blocks: ChatGPT/Claude wrap each line in spans/divs — reduce any
      // <pre> to <pre><code>textContent</code></pre> so turndown emits a fence.
      // textContent alone loses line breaks between block children (a <div> per
      // line yields no whitespace), so rebuild the text with explicit newlines
      // at every block boundary and <br>.
      doc.querySelectorAll('pre').forEach(pre => {
        const lines = [];
        let current = '';
        const collect = (node) => {
          for (const child of node.childNodes) {
            if (child.nodeType === 3) {
              current += child.textContent;
            } else if (child.nodeType === 1) {
              const tag = child.tagName.toLowerCase();
              if (tag === 'br') { lines.push(current); current = ''; }
              else if (tag === 'div' || tag === 'p' || tag === 'tr' || tag === 'table' || tag === 'pre') {
                collect(child);
                lines.push(current);
                current = '';
              } else {
                collect(child);
              }
            }
          }
        };
        collect(pre);
        if (current) lines.push(current);
        const text = lines.join('\n');
        pre.innerHTML = '';
        const code = doc.createElement('code');
        code.textContent = text;
        pre.appendChild(code);
      });
      // Unwrap pointless font/span wrappers (keep their content).
      doc.querySelectorAll('font, span').forEach(el => unwrapElement(el));
      // Remove empty paragraphs.
      doc.querySelectorAll('p').forEach(p => {
        if (!p.textContent || !p.textContent.trim()) p.parentNode && p.parentNode.removeChild(p);
      });
      return doc.body.innerHTML;
    }

    // Heuristic quality gate: warn when the source converts poorly (Office
    // HTML, images, math) or the conversion lost almost everything.
    function checkPasteQuality(html, md) {
      if (!html) return null;
      if (/<img\b/i.test(html) || /cid:/i.test(html)) return 'image';
      if (/mso-|<!--\[if|<\/(o|v|w|m):[a-z]/i.test(html)) return 'office';
      if (/katex|MathJax|class="[^"]*math/i.test(html)) return 'math';
      const textLen = html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim().length;
      if (textLen > 20 && (md || '').trim().length < 2) return 'lost';
      return null;
    }

    function showPasteQualityWarning() {
      setModal(
        t('Paste as Markdown', '粘贴为 Markdown'),
        '<p style="margin:0 0 8px;">' + t('The source formatting is messy and the conversion may be inaccurate.', '来源格式混乱，转换可能出错。') + '</p>' +
        '<p style="margin:0;color:#888;font-size:12px;">' + t('Content was still inserted; check it in the Source view.', '内容已插入，请在源码视图检查效果。') + '</p>'
      );
    }

    function blockifyForInsert(md) {
      const s = String(md || '').trim();
      if (!s) return '';
      return s.indexOf('\n') !== -1 ? '\n' + s + '\n' : s;
    }

    function insertMdAtSourceCaret(md) {
      insertMarkdownSnippet(blockifyForInsert(md));
    }

    // Map a caret inside the rendered view back to an offset in the markdown
    // source using a whitespace-normalized text anchor (the containing block's
    // text) plus occurrence counting so repeated paragraphs still resolve.
    // Returns -1 when no anchor matches (caller appends at the end).
    function mapRenderedCaretToSourceOffset(md, content, caretNode, caretOffset) {
      let node = caretNode;
      let blockEl = null;
      if (node) {
        if (node.nodeType === 3) node = node.parentElement;
        if (node && node.nodeType === 1) {
          blockEl = node.closest('p, h1, h2, h3, h4, h5, h6, li, pre, blockquote, td, th, div');
        }
      }
      let anchor = '';
      let nth = 0;
      if (blockEl) {
        const full = normalizeWhitespace(blockEl.textContent);
        if (full.length >= 2) {
          anchor = full.slice(0, 120);
          const blocks = content.querySelectorAll('p, h1, h2, h3, h4, h5, h6, li, pre, blockquote, td, th, div');
          let count = 0;
          for (const b of blocks) {
            if (b === blockEl) break;
            if (normalizeWhitespace(b.textContent) === full) count++;
          }
          nth = count;
        }
      }
      if (!anchor && caretNode && caretNode.nodeType === 3) {
        anchor = normalizeWhitespace(caretNode.textContent).slice(0, 120);
        nth = 0;
      }
      if (anchor && anchor.length >= 2) {
        const pos = findNthOccurrenceSourceOffset(md, anchor, nth);
        if (pos >= 0) return pos;
      }
      // Fallback: no text anchor matched (empty paragraph, empty line, caret on
      // a non-text element). Use the block element's ordinal position among
      // rendered blocks to approximate the source offset.
      if (blockEl) {
        const pos2 = estimateSourceOffsetByBlockOrder(md, content, blockEl, caretOffset);
        if (pos2 >= 0) return pos2;
      }
      return -1;
    }

    // Estimate a source offset by counting which rendered block the caret is in.
    // Each rendered block roughly corresponds to a paragraph/block in markdown
    // separated by blank lines, so we walk the block list, find our block's
    // index, then scan the source for the same number of block separators.
    function estimateSourceOffsetByBlockOrder(md, content, targetBlock, caretOffset) {
      const blocks = Array.from(content.querySelectorAll('p, h1, h2, h3, h4, h5, h6, li, pre, blockquote, td, th, div'));
      let blockIdx = -1;
      for (let i = 0; i < blocks.length; i++) {
        if (blocks[i] === targetBlock) { blockIdx = i; break; }
      }
      if (blockIdx < 0) return -1;
      // If the block has text, try to use the text of the *previous* block with
      // text as an anchor — that's more reliable than counting.
      for (let j = blockIdx - 1; j >= 0; j--) {
        const prevText = normalizeWhitespace(blocks[j].textContent);
        if (prevText.length >= 2) {
          const pos = findNthOccurrenceSourceOffset(md, prevText.slice(0, 120), 0);
          if (pos >= 0) {
            // Position after the previous block's text, past any trailing
            // whitespace/newlines, landing at the start of the next block.
            let p = pos;
            // Skip forward past the matched text and any whitespace to the
            // start of the next line/block.
            while (p < md.length && md[p] !== '\n') p++;
            while (p < md.length && /\s/.test(md[p])) p++;
            return p;
          }
        }
      }
      // No previous block with text: caret is in/near the first block.
      // Find the start of the first non-empty line in the source.
      let p0 = 0;
      while (p0 < md.length && /\s/.test(md[p0])) p0++;
      return p0;
    }

    function findNthOccurrenceSourceOffset(md, needle, nth) {
      const norm = [];
      const orig = [];
      for (let k = 0; k < md.length; k++) {
        const ch = md[k];
        if (/\s/.test(ch)) {
          if (norm.length && norm[norm.length - 1] !== ' ') { norm.push(' '); orig.push(k); }
        } else {
          norm.push(ch); orig.push(k);
        }
      }
      const nstr = norm.join('');
      let from = 0;
      let occ = 0;
      let idx = nstr.indexOf(needle, from);
      while (idx !== -1) {
        if (occ === nth) {
          const endIdx = idx + needle.length - 1;
          return (endIdx < orig.length) ? orig[endIdx] + 1 : -1;
        }
        occ++;
        from = idx + 1;
        idx = nstr.indexOf(needle, from);
      }
      return -1;
    }

    function firstMeaningfulLine(md) {
      const lines = String(md || '').split('\n');
      for (const line of lines) {
        const text = line
          .replace(/^(#{1,6}\s+|\s*[-*+]\s+|\s*\d+\.\s+|\s*>\s+|```+|~~~+|\*\*+|__+|[*_])/, '')
          .trim();
        if (text) return text.slice(0, 40);
      }
      return '';
    }

    function placeCaretNearRenderedText(content, anchorText) {
      const sel = window.getSelection();
      if (!anchorText) {
        sel.removeAllRanges();
        return;
      }
      const walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT, null, false);
      let node;
      while ((node = walker.nextNode())) {
        const idx = node.textContent.indexOf(anchorText);
        if (idx >= 0) {
          const range = document.createRange();
          range.setStart(node, idx);
          range.collapse(true);
          sel.removeAllRanges();
          sel.addRange(range);
          return;
        }
      }
      const range = document.createRange();
      range.selectNodeContents(content);
      range.collapse(false);
      sel.removeAllRanges();
      sel.addRange(range);
    }

    // Preview mode: paste converted markdown as RENDERED HTML directly into the
    // contenteditable, instead of rewriting the source and re-rendering the whole
    // document. Two problems with the old full re-render approach:
    //   1. Any paste path that fell through to the native insertion dropped the
    //      raw markdown (visible "#" etc.) into the rendered view.
    //   2. Replacing innerHTML programmatically clears/breaks the browser's
    //      native undo stack, so Cmd+Z could never undo a paste.
    // Using execCommand('insertHTML') keeps the paste inside the browser's own
    // undo stack (Cmd+Z works) and shows WYSIWYG content (no raw markdown).
    // savedSel is a { node, offset } snapshot taken synchronously at paste time,
    // so async clipboard reads cannot lose the caret.
    function pasteMdIntoRendered(md, savedSel) {
      const content = document.getElementById('content');
      if (!content) return;
      const s = String(md || '').trim();
      if (!s) return;
      restoreRenderedSelection(savedSel);
      let html;
      try {
        html = deps.MarkdownPipeline.parse(s);
      } catch (err) {
        html = escHtml(s);
      }
      // marked emits newline text nodes between block elements; turndown would
      // later write those back as stray blank lines / spaces, so strip pure
      // whitespace text nodes outside <pre>/<code> before inserting.
      html = compactRenderedHtml(html);
      html = sanitizeHtmlString(html);
      // A single-paragraph paste stays inline so pasting in the middle of a
      // paragraph does not split it into separate blocks.
      const singleP = html.match(/^<p>([\s\S]*)<\/p>\s*$/);
      if (singleP) html = singleP[1].replace(/\n/g, '<br>');
      let ok = false;
      try {
        content.focus({ preventScroll: true });
        ok = document.execCommand('insertHTML', false, html);
      } catch (err) {
        ok = false;
      }
      if (!ok) {
        // Fallback: manual Range insertion (content stays correct; native undo
        // for this paste is lost, but WKWebView supports insertHTML so this is
        // only a safety net).
        const sel = window.getSelection();
        if (sel && sel.rangeCount) {
          const range = sel.getRangeAt(0);
          const frag = range.createContextualFragment(html);
          range.deleteContents();
          range.insertNode(frag);
          range.collapse(false);
          sel.removeAllRanges();
          sel.addRange(range);
        }
      }
      balanceTableColumns(content);
      rewriteRelativeImages(content);
      markRenderedContentEdited();
    }

    function compactRenderedHtml(html) {
      try {
        const tmp = document.createElement('div');
        tmp.innerHTML = sanitizeHtmlString(html);
        const toRemove = [];
        const walker = document.createTreeWalker(tmp, NodeFilter.SHOW_TEXT, null, false);
        while (walker.nextNode()) {
          const n = walker.currentNode;
          if (n.textContent.trim()) continue;
          if (n.parentNode && n.parentNode.closest && n.parentNode.closest('pre, code, table')) continue;
          toRemove.push(n);
        }
        toRemove.forEach((n) => n.parentNode && n.parentNode.removeChild(n));
        return tmp.innerHTML;
      } catch (e) {
        return html;
      }
    }

    function restoreRenderedSelection(savedSel) {
      if (!savedSel) return;
      const sel = window.getSelection();
      if (!sel) return;
      const node = savedSel.node;
      if (!node || !node.parentNode) return;
      try {
        const range = document.createRange();
        range.setStart(node, savedSel.offset);
        range.collapse(true);
        sel.removeAllRanges();
        sel.addRange(range);
      } catch (e) {}
    }

    // Entry point for the "Paste as Markdown" menu item, Cmd+Shift+V, and
    // preview-mode Cmd+V. Reads the best clipboard flavor, converts, inserts.
    // Guard against double-dispatch: Cmd+V fires the DOM paste event AND a
    // beforeinput with inputType "insertFromPaste" (menu-driven paste only fires
    // the latter). Both call pasteAsMarkdown; a short time window collapses them
    // into one while still allowing genuinely separate pastes.
    let pasteLastTs = 0;
    async function pasteAsMarkdown() {
      const now = Date.now();
      if (state.closing || now - pasteLastTs < 50) return;
      pasteLastTs = now;
      // Snapshot the current selection synchronously *before* any async call.
      // pasteAsMarkdown is async (reads clipboard via the pywebbridge); during
      // those awaits the browser can clear/alter the DOM selection, which makes
      // mapRenderedCaretToSourceOffset fail and paste at end-of-document.
      const sel = window.getSelection();
      let savedSel = null;
      if (sel && sel.rangeCount > 0) {
        const range = sel.getRangeAt(0);
        savedSel = { node: range.startContainer, offset: range.startOffset };
      }
      await ensureTurndown();
      let clip = null;
      try {
        clip = await readClipboardBest();
      } catch (e) {
        clip = null;
      }
      if (!clip || clip.format === 'none') {
        showStatus(t('Clipboard is empty or unreadable', '剪贴板为空或无法读取'), true);
        return;
      }
      let md;
      let quality = null;
      if (clip.format === 'markdown') {
        md = clip.content;
      } else if (clip.format === 'html') {
        const cleaned = normalizePastedHtml(clip.content);
        md = deps.turndownService ? deps.turndownService.turndown(cleaned) : cleaned;
        quality = checkPasteQuality(clip.content, md);
      } else {
        md = clip.content;
      }
      if (!md || !md.trim()) {
        showStatus(t('Nothing to paste', '没有可粘贴的内容'), true);
        return;
      }
      if (quality) showPasteQualityWarning();
      if (state.isSource) {
        insertMdAtSourceCaret(md);
      } else {
        pasteMdIntoRendered(md, savedSel);
        // Preview mode: confirm the conversion happened for rich pastes.
        if (clip.format === 'html' || clip.format === 'markdown') showPastedAsMarkdownHint();
      }
    }


    return {
      normalizeWhitespace, showPasteHint, showPastedAsMarkdownHint, readClipboardBest, stripHtmlToText, 
      hasMarkdownSyntax, elementHasMarkdownStyle, htmlHasMarkdownConvertibleFormatting, 
      shouldShowSourcePasteHint, unwrapElement, normalizePastedHtml, checkPasteQuality, 
      showPasteQualityWarning, blockifyForInsert, insertMdAtSourceCaret, mapRenderedCaretToSourceOffset, 
      estimateSourceOffsetByBlockOrder, findNthOccurrenceSourceOffset, firstMeaningfulLine, 
      placeCaretNearRenderedText, pasteMdIntoRendered, compactRenderedHtml, restoreRenderedSelection, 
      pasteAsMarkdown,
    };
  }
};
