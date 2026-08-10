let isSource = false;
  let isDirty = false;
  let filePath = '';
  let turndownService = null;
  // True when the rendered (contenteditable) view has been edited by the user.
  // When false, Cmd+E switches back to source using the pristine markdown
  // instead of round-tripping the (possibly browser-rewritten) DOM via turndown.
  let renderedDirty = false;
  const mermaidSvgCache = new Map();
  let highlightTimer = null;
  let lastPushedHash = '';
  let lastRenderedHash = '';
  // Set by prepareForClose() when the window is closing: stops all timers and
  // pending JS->Python bridge traffic so teardown never deadlocks.
  let closing = false;
  let keepAliveTimer = null;
  // Locale flag set from Python on init
  let isZh = false;

  if (typeof marked !== 'undefined') marked.setOptions({ breaks: true, gfm: true });
  if (typeof TurndownService !== 'undefined') {
    turndownService = new TurndownService({ headingStyle: 'atx', codeBlockStyle: 'fenced', bulletListMarker: '-', emDelimiter: '*', strongDelimiter: '**' });
    // Preserve YAML frontmatter blocks during HTML→Markdown conversion
    turndownService.addRule('frontmatter', {
      filter: function (node) {
        return node.classList && node.classList.contains('frontmatter');
      },
      replacement: function (content, node) {
        // Round-trip via the stored raw YAML (data-raw) so that block-scalar
        // indicators (>, |, -) are preserved exactly when toggling to source.
        const raw = node.getAttribute('data-raw');
        return (raw || node.textContent) + '\n\n';
      }
    });
    // Preserve mermaid code blocks during HTML→Markdown conversion
    turndownService.addRule('mermaid', {
      filter: function (node) {
        return node.classList && node.classList.contains('mermaid-diagram');
      },
      replacement: function (content, node) {
        const source = node.getAttribute('data-source') || '';
        return source ? '```mermaid\n' + source.trim() + '\n```' : '';
      }
    });

    // Convert HTML tables back to GFM pipe-table syntax
    turndownService.addRule('table', {
      filter: function (node) {
        return node.nodeName === 'TABLE';
      },
      replacement: function (content, node) {
        var rows = node.rows;
        if (!rows || rows.length === 0) return '';

        var colCount = 0;
        for (var r = 0; r < rows.length; r++) {
          colCount = Math.max(colCount, rows[r].cells.length);
        }
        if (colCount === 0) return '';

        // Escape pipe chars in cell text
        function escPipe(s) {
          return (s || '').trim().replace(/\|/g, '\\|').replace(/\n/g, ' ');
        }

        var lines = [];

        // Header row (always first row in GFM tables)
        var headerCells = [];
        for (var c = 0; c < colCount; c++) {
          headerCells.push(escPipe((rows[0].cells[c] || {}).textContent || ''));
        }
        lines.push('| ' + headerCells.join(' | ') + ' |');

        // Separator row with alignment
        var sepCells = [];
        for (var c2 = 0; c2 < colCount; c2++) {
          var cell = rows[0].cells[c2];
          var align = cell ? (cell.getAttribute('align') || cell.style.textAlign || '') : '';
          if (align === 'center') sepCells.push(':---:');
          else if (align === 'right') sepCells.push('---:');
          else sepCells.push('---');
        }
        lines.push('| ' + sepCells.join(' | ') + ' |');

        // Data rows
        for (var r2 = 1; r2 < rows.length; r2++) {
          var cells = [];
          for (var c3 = 0; c3 < colCount; c3++) {
            cells.push(escPipe((rows[r2].cells[c3] || {}).textContent || ''));
          }
          lines.push('| ' + cells.join(' | ') + ' |');
        }

        return '\n\n' + lines.join('\n') + '\n\n';
      }
    });
  }

  // ── Mermaid initialization ──
  function getMermaidTheme() {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'default';
  }
  function initMermaid() {
    if (typeof mermaid === 'undefined') return;
    mermaid.initialize({
      startOnLoad: false,
      theme: getMermaidTheme(),
      securityLevel: 'loose',
      flowchart: { useMaxWidth: true, htmlLabels: true },
      sequence: { useMaxWidth: true },
    });
  }
  initMermaid();
  // Re-init and re-render when system theme changes
  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      initMermaid();
      // Clear cache so diagrams re-render with new theme
      mermaidSvgCache.clear();
      renderMermaidDiagrams(document.getElementById('content'));
    });
  }

  // Render all mermaid code blocks to SVG diagrams
  async function renderMermaidDiagrams(root) {
    if (typeof mermaid === 'undefined') return;
    const codeBlocks = root.querySelectorAll('code.language-mermaid');
    for (const code of codeBlocks) {
      const pre = code.parentElement;
      if (!pre || pre.nodeName !== 'PRE') continue;
      const source = code.textContent;
      if (!source.trim()) continue;
      try {
        let svg = mermaidSvgCache.get(source);
        if (!svg) {
          const id = 'mermaid-' + Math.random().toString(36).slice(2, 9);
          const rendered = await mermaid.render(id, source);
          svg = rendered.svg;
          mermaidSvgCache.set(source, svg);
        }
        const wrapper = document.createElement('div');
        wrapper.className = 'mermaid-diagram';
        wrapper.setAttribute('data-source', source);
        wrapper.setAttribute('contenteditable', 'false');
        wrapper.innerHTML = svg;
        pre.parentNode.replaceChild(wrapper, pre);
      } catch (e) {
        const error = document.createElement('div');
        error.className = 'mermaid-error';
        error.setAttribute('contenteditable', 'false');
        error.textContent = 'Mermaid render error: ' + (e && e.message ? e.message : e);
        pre.parentNode.replaceChild(error, pre);
      }
    }
  }

  function preprocessMarkdownExtensions(markdown) {
    const footnotes = [];
    let body = markdown.replace(/^\[\^([^\]]+)\]:\s*([\s\S]*?)(?=^\[\^[^\]]+\]:|\n{2,}|\s*$)/gm, (match, id, text) => {
      footnotes.push({ id: id.trim(), text: text.trim().replace(/\n\s+/g, ' ') });
      return '';
    });
    const mathBlocks = [];
    body = body.replace(/\$\$\s*([\s\S]*?)\s*\$\$/g, (match, expr) => {
      const token = `@@MATH_BLOCK_${mathBlocks.length}@@`;
      mathBlocks.push(expr.trim());
      return token;
    });
    return { body, footnotes, mathBlocks };
  }

  function renderMathPlaceholders(root, mathBlocks) {
    root.innerHTML = root.innerHTML.replace(/@@MATH_BLOCK_(\d+)@@/g, (match, idx) => {
      return '<span class="math-block" contenteditable="false">' + escHtml(mathBlocks[Number(idx)] || '') + '</span>';
    });
    root.innerHTML = root.innerHTML.replace(/\$([^$\n]+?)\$/g, (match, expr) => {
      return '<span class="math-inline" contenteditable="false">' + escHtml(expr.trim()) + '</span>';
    });
  }

  function renderFootnotes(root, footnotes) {
    if (!footnotes.length) return;
    root.querySelectorAll('sup').forEach((sup) => {
      const text = sup.textContent || '';
      const ref = text.match(/^\[([^\]]+)\]$/);
      if (!ref) return;
      const id = ref[1];
      const slug = slugifyHeading(id);
      sup.className = 'footnote-ref';
      sup.id = `fnref-${slug}`;
      sup.innerHTML = `<a href="#fn-${slug}">[${escHtml(id)}]</a>`;
    });
    const section = document.createElement('section');
    section.className = 'footnotes';
    section.setAttribute('contenteditable', 'false');
    const items = footnotes.map((fn) => {
      const id = slugifyHeading(fn.id);
      return `<li id="fn-${id}">${escHtml(fn.text)} <a class="footnote-backref" href="#fnref-${id}">↩</a></li>`;
    }).join('');
    section.innerHTML = `<ol>${items}</ol>`;
    root.appendChild(section);
  }

  // Render a specific container's markdown and mermaid diagrams
  async function renderMarkdown(content, container) {
    // Extract YAML frontmatter (--- at start, ending with ---) before marked.parse
    // so it doesn't get mangled into <hr> tags
    let frontmatter = '';
    let body = content;
    const fmMatch = content.match(/^\s*---\r?\n([\s\S]*?)\r?\n(?:---|\.\.\.)\r?\n?/);
    if (fmMatch) {
      frontmatter = fmMatch[1];
      body = content.substring(fmMatch[0].length);
    }

    const extensions = preprocessMarkdownExtensions(body);
    body = extensions.body;

    if (frontmatter) {
      const fmDiv = document.createElement('div');
      fmDiv.className = 'frontmatter';
      fmDiv.setAttribute('contenteditable', 'false');
      fmDiv.setAttribute('data-frontmatter', 'true');
      fmDiv.setAttribute('data-raw', '---\n' + frontmatter + '\n---');
      fmDiv.innerHTML = '<button class="frontmatter-toggle" onclick="toggleFrontmatter(this)">Collapse</button>' + renderFrontmatter(frontmatter);
      container.innerHTML = '';
      container.appendChild(fmDiv);
      const bodyDiv = document.createElement('div');
      bodyDiv.innerHTML = marked.parse(body);
      while (bodyDiv.firstChild) {
        container.appendChild(bodyDiv.firstChild);
      }
    } else {
      container.innerHTML = marked.parse(body);
    }
    renderMathPlaceholders(container, extensions.mathBlocks);
    renderFootnotes(container, extensions.footnotes);
    applyHeadingAnchors(container);
    rewriteRelativeImages(container);
    buildToc(container);
    // Wrap tables in .table-wrap for overflow control
    const tables = container.querySelectorAll('table');
    for (const table of tables) {
      const wrap = document.createElement('div');
      wrap.className = 'table-wrap';
      wrap.setAttribute('contenteditable', 'false');
      table.parentNode.insertBefore(wrap, table);
      wrap.appendChild(table);
    }
    await renderMermaidDiagrams(container);
    protectComplexBlocks(container);
    balanceTableColumns(container);
    lastRenderedHash = contentHash(content);
  }

  function toggleFrontmatter(btn) {
    const box = btn.closest('.frontmatter');
    if (!box) return;
    const collapsed = box.classList.toggle('collapsed');
    btn.textContent = collapsed ? 'Expand' : 'Collapse';
  }

  function rewriteRelativeImages(container) {
    if (!filePath || filePath === 'Untitled.md') return;
    const base = filePath.split('/').slice(0, -1).join('/');
    container.querySelectorAll('img[src]').forEach((img) => {
      const src = img.getAttribute('src') || '';
      if (/^(https?:|file:|data:|\/)/i.test(src)) return;
      img.src = 'file://' + base + '/' + src.replace(/^\.\//, '');
      img.setAttribute('data-original-src', src);
    });
  }

  function syncTocToggle(hidden) {
    const toggle = document.getElementById('tocToggle');
    if (!toggle) return;
    toggle.classList.toggle('collapsed', hidden);
    toggle.setAttribute('aria-expanded', hidden ? 'false' : 'true');
    toggle.setAttribute('aria-label', hidden ? 'Show outline' : 'Hide outline');
    toggle.setAttribute('title', hidden ? 'Show outline' : 'Hide outline');
  }

  const TOC_AUTO_HIDE_WIDTH = 800;
  let tocHasContent = false;
  let tocManualOverride = null;

  function isTocAutoHideWidth() {
    return window.innerWidth < TOC_AUTO_HIDE_WIDTH;
  }

  function shouldAutoShowToc() {
    return tocHasContent && !isTocAutoHideWidth();
  }

  function setTocVisible(visible) {
    const toc = document.getElementById('tocSidebar');
    const show = !!visible && tocHasContent;
    toc.classList.toggle('hidden', !show);
    document.body.classList.toggle('has-toc', show);
    syncTocToggle(!show);
  }

  function applyTocVisibility() {
    if (isTocAutoHideWidth() && tocManualOverride !== true) {
      setTocVisible(false);
      return;
    }
    setTocVisible(tocManualOverride === null ? shouldAutoShowToc() : tocManualOverride);
  }

  function handleTocResize() {
    if (isTocAutoHideWidth()) {
      tocManualOverride = null;
      setTocVisible(false);
      return;
    }
    applyTocVisibility();
  }

  function buildToc(container) {
    const toc = document.getElementById('tocSidebar');
    const toggle = document.getElementById('tocToggle');
    const headings = Array.from(container.querySelectorAll('h1, h2, h3, h4, h5, h6'));
    tocHasContent = headings.length >= 2;
    // Hide the toggle button entirely when there are no headings to outline
    if (toggle) toggle.style.display = tocHasContent ? '' : 'none';
    toc.innerHTML = headings.map((h) => {
      const level = h.tagName.slice(1);
      return `<a class="toc-level-${level}" href="#${encodeURIComponent(h.id)}" data-target="${h.id}">${escHtml(h.textContent)}</a>`;
    }).join('');
    applyTocVisibility();
    setupScrollSpy(headings);
  }

  let scrollSpyObserver = null;
  function setupScrollSpy(headings) {
    if (scrollSpyObserver) { scrollSpyObserver.disconnect(); scrollSpyObserver = null; }
    if (!headings || headings.length === 0) return;
    const toc = document.getElementById('tocSidebar');
    const links = toc.querySelectorAll('a');
    if (links.length === 0) return;
    // Use IntersectionObserver to detect which heading is in view
    const visibleIds = new Set();
    scrollSpyObserver = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) visibleIds.add(entry.target.id);
        else visibleIds.delete(entry.target.id);
      });
      // Pick the first visible heading
      let currentId = null;
      if (visibleIds.size > 0) {
        for (const h of headings) { if (visibleIds.has(h.id)) { currentId = h.id; break; } }
      }
      // If none visible, pick the last one we scrolled past
      if (!currentId) {
        const scrollY = document.querySelector('.scroll-wrap').scrollTop;
        for (const h of headings) {
          if (h.offsetTop - 80 <= scrollY) currentId = h.id;
          else break;
        }
      }
      links.forEach(a => {
        a.classList.toggle('toc-active', a.getAttribute('data-target') === currentId);
      });
    }, { root: document.querySelector('.scroll-wrap'), rootMargin: '0px 0px -70% 0px', threshold: 0 });
    headings.forEach(h => scrollSpyObserver.observe(h));
  }

  function toggleToc() {
    const toc = document.getElementById('tocSidebar');
    tocManualOverride = toc.classList.contains('hidden');
    setTocVisible(tocManualOverride);
  }

  function protectComplexBlocks(container) {
    container.querySelectorAll('pre, table, .frontmatter, .mermaid-diagram').forEach((node) => {
      node.setAttribute('contenteditable', 'false');
    });
    container.querySelectorAll('div, section, article').forEach((node) => {
      if (node.querySelector('.frontmatter, .mermaid-diagram')) return;
      const hasMarkdownClass = node.classList.contains('frontmatter') || node.classList.contains('mermaid-diagram') || node.classList.contains('table-wrap');
      if (hasMarkdownClass) node.setAttribute('contenteditable', 'false');
    });
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
    const target = document.getElementById(id) || document.getElementById(raw);
    if (!target) return false;
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    if (history && history.replaceState) history.replaceState(null, '', '#' + encodeURIComponent(target.id));
    return true;
  }

  // ── YAML frontmatter rendering ──
  // Renders frontmatter as plain text (no syntax colors) but resolves
  // block scalar indicators per YAML semantics:
  //   ">"  folded block scalar  → indicator hidden; following indented lines
  //        are one string, ordinary newlines folded into spaces
  //   "|"  literal block scalar → indicator hidden; newlines preserved
  //   "-"  chomping indicator   → trailing newline(s) of the scalar stripped
  //   "+"  chomping indicator   → all trailing newlines kept
  // The original raw frontmatter is kept in data-raw for exact round-trips.
  function renderFrontmatter(text) {
    const lines = text.split('\n');
    const out = [];
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      // key: value
      const m = line.match(/^(\s*)([^:]+?)(\s*:\s*)(.*)$/);
      if (m && m[2].indexOf('#') !== 0) {
        const indent = m[1];
        const key = m[2];
        const val = m[4];
        const bm = val.match(/^([>|])([-+]?)\s*$/);
        if (bm) {
          const style = bm[1];      // '>' folded, '|' literal
          const chomp = bm[2] || ''; // '' clip, '-' strip, '+' keep
          // Collect following more-indented lines as the scalar content.
          const block = [];
          const keyIndentLen = indent.length;
          let baseIndent = null;
          i++;
          while (i < lines.length) {
            const n = lines[i];
            if (n.trim() === '') { block.push(''); i++; continue; }
            const ind = n.match(/^(\s*)/)[1].length;
            if (ind <= keyIndentLen) break;
            if (baseIndent === null) baseIndent = ind;
            block.push(n.slice(baseIndent));
            i++;
          }
          out.push(indent + key + ': ' + resolveBlockScalar(block, style, chomp));
          continue;
        }
        out.push(line);
        i++;
        continue;
      }
      out.push(line);
      i++;
    }
    return escHtml('---\n' + out.join('\n') + '\n---');
  }

  function resolveBlockScalar(lines, style, chomp) {
    let text;
    if (style === '>') {
      // Folded: ordinary newlines become spaces; blank lines become "\n"
      const parts = [];
      for (let k = 0; k < lines.length; k++) {
        const l = lines[k];
        if (l === '') {
          parts.push('\n');
        } else {
          if (parts.length > 0 && parts[parts.length - 1] !== '\n' && !parts[parts.length - 1].endsWith(' ')) {
            parts.push(' ');
          }
          parts.push(l);
        }
      }
      text = parts.join('');
    } else {
      // Literal: newlines preserved as-is
      text = lines.join('\n');
    }
    // Chomping: '-' strip trailing newlines, '+' keep all, default clip to one
    if (chomp === '-') return text.replace(/\n+$/, '');
    if (chomp === '+') return text;
    return text.replace(/\n+$/, '') + '\n';
  }

  // ── Markdown syntax highlighting ──
  function highlightInlineMarkdown(line) {
    let h = escHtml(line);
    h = h.replace(/^(#{1,6})(\s)/, '<span class="syn-heading">$1</span>$2');
    h = h.replace(/(\*\*|__)(.+?)\1/g, '<span class="syn-bold">$1</span>$2<span class="syn-bold">$1</span>');
    h = h.replace(/(^|[^\*])(\*)([^\s\*][^\*]*?)\*(?!\*)/g, '$1<span class="syn-italic">$2</span>$3<span class="syn-italic">$2</span>');
    h = h.replace(/`([^`]+)`/g, '<span class="syn-code">`</span>$1<span class="syn-code">`</span>');
    h = h.replace(/\[([^\]]*)\]\(([^)]*)\)/g, '<span class="syn-link">[</span>$1<span class="syn-link">]</span><span class="syn-link">(</span>$2<span class="syn-link">)</span>');
    h = h.replace(/^(\s*)((?:(?:\* ?){2,}\*)|(?:(?:- ?){2,}-))\s*$/, '$1<span class="syn-hr">$2</span>');
    h = h.replace(/^(\s*)([-*+])(\s)/, '$1<span class="syn-list">$2</span>$3');
    h = h.replace(/^(&gt;)(\s?)/, '<span class="syn-quote">$1</span>$2');
    return h;
  }

  function highlightMarkdown(text) {
    const lines = text.split('\n');
    const out = [];
    let inFence = false;
    let fenceMarker = '';
    let inFrontmatter = false;
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (i === 0 && /^\s*---\s*$/.test(line)) {
        inFrontmatter = true;
        out.push('<span class="syn-codeblock">' + escHtml(line) + '</span>');
        continue;
      }
      if (inFrontmatter) {
        out.push('<span class="syn-codeblock">' + escHtml(line) + '</span>');
        if (/^\s*(---|\.\.\.)\s*$/.test(line)) inFrontmatter = false;
        continue;
      }
      const fence = line.match(/^\s*(```+|~~~+)/);
      if (fence) {
        const marker = fence[1][0];
        const highlighted = escHtml(line).replace(/(```+|~~~+)/, '<span class="syn-codeblock">$1</span>');
        out.push(highlighted);
        if (!inFence) {
          inFence = true;
          fenceMarker = marker;
        } else if (marker === fenceMarker) {
          inFence = false;
          fenceMarker = '';
        }
        continue;
      }
      if (inFence) {
        out.push(escHtml(line));
        continue;
      }
      out.push(highlightInlineMarkdown(line));
    }
    return out.join('\n');
  }

  function syncHighlight() {
    document.getElementById('highlightLayer').innerHTML = highlightMarkdown(document.getElementById('textarea').value) + '\n';
  }

  function scheduleHighlightSync() {
    clearTimeout(highlightTimer);
    highlightTimer = setTimeout(syncHighlight, 120);
  }

  // ── Page width control ──
  function setPageWidth(w) {
    const page = document.getElementById('page');
    page.style.setProperty('--page-width', w + 'px');
  }
  function adjustPageWidth(delta) {
    const page = document.getElementById('page');
    const current = parseInt(getComputedStyle(page).getPropertyValue('--page-width').trim()) || 720;
    let next = current + delta;
    if (next < 360) next = 360;
    if (next > 2000) next = 2000;
    setPageWidth(next);
    // Notify Python to persist
    if (window.pywebview && window.pywebview.api) window.pywebview.api.save_page_width(next);
  }
  function resetPageWidth() {
    setPageWidth(720);
    if (window.pywebview && window.pywebview.api) window.pywebview.api.save_page_width(720);
    showStatus('Width reset');
  }
  function openFile() {
    if (window.pywebview && window.pywebview.api) window.pywebview.api.open_file_dialog();
  }
  function closeWindow() {
    if (window.pywebview && window.pywebview.api) window.pywebview.api.close_window();
  }
  async function showPreferences() {
    // Show an informational modal about the app
    const body = document.getElementById('modalBody');
    let version = '—';
    try {
      if (window.pywebview && window.pywebview.api) {
        const info = await window.pywebview.api.get_app_info();
        if (info && info.version) version = info.version;
      }
    } catch (e) {}
    body.innerHTML =
      '<div class="modal-row"><span class="modal-label">App</span><span class="modal-value">mdPreview</span></div>' +
      '<div class="modal-row"><span class="modal-label">Version</span><span class="modal-value">' + version + '</span></div>' +
      '<div class="modal-row"><span class="modal-label">Shortcuts</span><span class="modal-value" style="font-size:12px;line-height:1.6">' +
      '⌘O Open &nbsp; ⌘S Save &nbsp; ⌘E Toggle Source<br>' +
      '⌘F Find &nbsp; ⌘W Close &nbsp; ⌘+ Zoom In<br>' +
      '⌘− Zoom Out &nbsp; ⌘0 Reset Width<br>' +
      '⌘N New &nbsp; Drag images to insert</span></div>';
    document.getElementById('modalOverlay').classList.add('visible');
    document.querySelector('.modal-header').textContent = 'About mdPreview';
  }
  function insertMarkdownSnippet(snippet) {
    const textarea = document.getElementById('textarea');
    if (!isSource) {
      textarea.value = getCurrentMarkdown();
      isSource = true;
      updateView();
    }
    const start = textarea.selectionStart || textarea.value.length;
    const end = textarea.selectionEnd || start;
    textarea.value = textarea.value.slice(0, start) + snippet + textarea.value.slice(end);
    textarea.setSelectionRange(start + snippet.length, start + snippet.length);
    setDirty(true);
    syncHighlight();
    pushContentToPython(true);
  }
  function handleImageDrop(e) {
    e.preventDefault();
    const files = Array.from(e.dataTransfer.files || []).filter(f => /^image\//.test(f.type));
    if (!files.length) return;
    const snippets = files.map(f => `![${f.name}](${f.path || f.name})`).join('\n');
    insertMarkdownSnippet('\n' + snippets + '\n');
    // Switch back to rendered view so the user sees the image immediately
    if (isSource) {
      isSource = false;
      renderMarkdown(getCurrentMarkdown(), document.getElementById('content')).then(() => {
        updateView();
        buildToc(document.getElementById('content'));
      });
    }
  }
  function exportHTML() {
    const title = filePath && filePath !== 'Untitled.md' ? filePath.split('/').pop().replace(/\.[^.]+$/, '') : 'Untitled';
    // Clone the rendered content and clean up editor-internal attributes
    const clone = document.getElementById('content').cloneNode(true);
    // Remove editor-only elements
    clone.querySelectorAll('.frontmatter-toggle, .colgroup, colgroup').forEach(el => el.remove());
    // Strip contenteditable and data-* attributes from all elements
    clone.querySelectorAll('*').forEach(el => {
      el.removeAttribute('contenteditable');
      el.removeAttribute('spellcheck');
      // Remove data-* attributes
      Array.from(el.attributes).forEach(attr => {
        if (attr.name.startsWith('data-')) el.removeAttribute(attr.name);
      });
    });
    // Get the CSS to inline
    const styles = document.querySelector('link[href*="styles.css"]') ? '<link rel="stylesheet" href="styles.css">' : '';
    const html = '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1.0">\n<title>' + escHtml(title) + '</title>\n' +
      '<style>\n' +
      'body { font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif; max-width: 720px; margin: 40px auto; padding: 0 24px; color: #333; line-height: 1.8; }\n' +
      'h1 { font-size: 30px; font-weight: 700; } h2 { font-size: 23px; font-weight: 600; } h3 { font-size: 18px; font-weight: 600; }\n' +
      'code { font-family: "SF Mono", Menlo, monospace; background: #f5f5f7; padding: 2px 6px; border-radius: 4px; font-size: 14px; }\n' +
      'pre { padding: 14px 18px; background: #f5f5f7; border-radius: 8px; overflow-x: auto; }\n' +
      'pre code { background: none; padding: 0; }\n' +
      'blockquote { border-left: 3px solid #e0e0e0; padding-left: 20px; color: #666; }\n' +
      'table { border-collapse: collapse; width: 100%; } th, td { border: 1px solid #e0e0e0; padding: 8px 14px; } th { background: #f5f5f7; }\n' +
      'img { max-width: 100%; border-radius: 10px; }\n' +
      'a { color: #007aff; }\n' +
      '.math-inline, .math-block { font-family: "SF Mono", Menlo, monospace; background: #f8f8fa; border: 1px solid #ececf0; border-radius: 6px; color: #5a3b8f; }\n' +
      '.math-block { display: block; padding: 12px 14px; overflow-x: auto; text-align: center; }\n' +
      '.frontmatter { font-family: "SF Mono", Menlo, monospace; font-size: 13px; background: #f5f5f7; border-radius: 8px; padding: 14px 18px; white-space: pre-wrap; }\n' +
      '.mermaid-diagram { text-align: center; }\n' +
      '</style>\n</head>\n<body>\n' + clone.innerHTML + '\n</body>\n</html>';
    if (window.pywebview && window.pywebview.api) window.pywebview.api.export_document(title + '.html', html, 'html');
  }
  function exportText() {
    const title = filePath && filePath !== 'Untitled.md' ? filePath.split('/').pop().replace(/\.[^.]+$/, '') : 'Untitled';
    if (window.pywebview && window.pywebview.api) window.pywebview.api.export_document(title + '.txt', getCurrentMarkdown(), 'txt');
  }
  function printDocument() { window.print(); }

  // ── File Properties Modal ──
  async function copyTextToClipboard(text) {
    if (!text || text === '-') return false;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch (e) {}
    try {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.setAttribute('readonly', 'readonly');
      textarea.style.position = 'fixed';
      textarea.style.left = '-9999px';
      textarea.style.top = '0';
      document.body.appendChild(textarea);
      textarea.select();
      const ok = document.execCommand('copy');
      document.body.removeChild(textarea);
      return ok;
    } catch (e) {
      return false;
    }
  }

  async function showFileProperties() {
    if (!window.pywebview || !window.pywebview.api) return;
    const props = await window.pywebview.api.get_file_properties();
    const body = document.getElementById('modalBody');
    const rows = [
      { label: 'Name', value: props.name },
      { label: 'Location', value: props.location || '-', copyable: !!props.location },
      { label: 'Size', value: props.sizeFormatted + ' (' + (props.size || 0) + ' bytes)' },
      { label: 'Encoding', value: props.encoding || '-' },
      { label: 'Modified', value: props.modified || '-' },
      { label: 'Created', value: props.created || '-' },
    ];
    body.innerHTML = rows.map(r => {
      const copyButton = r.copyable ? '<button class="modal-copy" type="button" data-copy="location" title="Copy location">Copy</button>' : '';
      return `<div class="modal-row"><div class="modal-label">${r.label}</div><div class="modal-value">${escHtml(r.value)}</div>${copyButton}</div>`;
    }).join('');
    const copyLocation = body.querySelector('[data-copy="location"]');
    if (copyLocation) {
      copyLocation.addEventListener('click', async () => {
        const ok = await copyTextToClipboard(props.location || '');
        showStatus(ok ? 'Location copied' : 'Copy failed', !ok);
      });
    }
    document.getElementById('modalOverlay').classList.add('visible');
  }
  function closeModal() {
    document.getElementById('modalOverlay').classList.remove('visible');
  }
  document.getElementById('modalOverlay').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeModal();
  });
  document.getElementById('imageLightbox').addEventListener('click', () => {
    document.getElementById('imageLightbox').classList.remove('visible');
  });
  document.getElementById('content').addEventListener('click', (e) => {
    const img = e.target.closest('img');
    if (!img) return;
    e.preventDefault();
    document.getElementById('imageLightboxImg').src = img.src;
    document.getElementById('imageLightbox').classList.add('visible');
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeModal();
  });
  function escHtml(s) {
    if (!s) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // ── Table column balancing + drag-resize ──
  function balanceTableColumns(container) {
    const tables = container.querySelectorAll('table');
    const pageWidth = parseInt(getComputedStyle(document.getElementById('page')).getPropertyValue('--page-width').trim()) || 720;
    const availableWidth = pageWidth - 64;  // padding: 60px 32px → 32+32=64px horizontal

    for (const table of tables) {
      if (table.rows.length === 0) continue;
      const colCount = table.rows[0].cells.length;
      if (colCount === 0) continue;

      const colWidths = new Array(colCount).fill(0);
      for (let r = 0; r < table.rows.length; r++) {
        for (let c = 0; c < Math.min(table.rows[r].cells.length, colCount); c++) {
          const cell = table.rows[r].cells[c];
          const textLen = cell.textContent.replace(/\s+/g, ' ').length;
          const estWidth = Math.max(textLen * 8 + 28, 50);
          colWidths[c] = Math.max(colWidths[c], estWidth);
        }
      }

      let totalDesired = colWidths.reduce((a, b) => a + b, 0);
      const minColWidth = 60;
      const maxColWidth = Math.min(400, availableWidth * 0.6);

      if (totalDesired > availableWidth) {
        const ratio = availableWidth / totalDesired;
        for (let c = 0; c < colCount; c++) colWidths[c] = Math.max(minColWidth, Math.floor(colWidths[c] * ratio));
      } else if (totalDesired < availableWidth) {
        const extra = availableWidth - totalDesired;
        for (let c = 0; c < colCount; c++) colWidths[c] += Math.floor(extra * (colWidths[c] / totalDesired));
      }
      for (let c = 0; c < colCount; c++) colWidths[c] = Math.min(colWidths[c], maxColWidth);

      const currentTotal = colWidths.reduce((a, b) => a + b, 0);
      if (currentTotal < availableWidth) colWidths[colCount - 1] += availableWidth - currentTotal;
      else if (currentTotal > availableWidth) {
        colWidths[colCount - 1] -= currentTotal - availableWidth;
        if (colWidths[colCount - 1] < minColWidth) colWidths[colCount - 1] = minColWidth;
      }

      // Apply widths through a <colgroup> so columns stay independently resizable
      const total = colWidths.reduce((a, b) => a + b, 0);
      let colgroup = table.querySelector('colgroup');
      if (!colgroup) {
        colgroup = document.createElement('colgroup');
        table.insertBefore(colgroup, table.firstChild);
      }
      colgroup.innerHTML = '';
      colWidths.forEach((w) => {
        const col = document.createElement('col');
        col.style.width = (w / total * 100).toFixed(2) + '%';
        colgroup.appendChild(col);
      });

      enableTableResize(table);
    }
  }

  // Allow dragging a column's right border to resize it; the space taken/given
  // is borrowed from the adjacent column so the table width stays constant.
  // Highlight (or clear) every cell in a given column, across all rows.
  function setColumnEdge(table, colIndex, on) {
    for (let r = 0; r < table.rows.length; r++) {
      const cells = table.rows[r].cells;
      if (colIndex >= cells.length) continue;
      const cell = cells[colIndex];
      cell.classList.toggle('col-edge', on);
      cell.style.cursor = on ? 'col-resize' : '';
    }
  }
  function clearColumnEdges(table) {
    const all = table.querySelectorAll('th, td');
    for (const cell of all) {
      cell.classList.remove('col-edge');
      if (cell.style.cursor === 'col-resize') cell.style.cursor = '';
    }
  }

  function getResizeColumnFromEvent(table, e) {
    const EDGE = 6;
    const cell = e.target.closest('th, td');
    if (!cell || !table.contains(cell)) return -1;
    const cells = Array.from(cell.parentElement.cells);
    const i = cells.indexOf(cell);
    if (i < 0 || i >= cells.length - 1) return -1;
    const rect = cell.getBoundingClientRect();
    return e.clientX >= rect.right - EDGE && e.clientX <= rect.right + 2 ? i : -1;
  }

  function enableTableResize(table) {
    if (table.__resizeReady) return;
    table.__resizeReady = true;
    table.addEventListener('mousemove', (e) => {
      if (table.__dragging) return;
      const i = getResizeColumnFromEvent(table, e);
      clearColumnEdges(table);
      if (i >= 0) setColumnEdge(table, i, true);
    });
    table.addEventListener('mouseleave', () => {
      if (!table.__dragging) clearColumnEdges(table);
    });
    table.addEventListener('mousedown', (e) => {
      const i = getResizeColumnFromEvent(table, e);
      if (i < 0) return;
      e.preventDefault();
      startColDrag(table, i, e);
    });
  }

  function startColDrag(table, i, e) {
    const colgroup = table.querySelector('colgroup');
    if (!colgroup) return;
    const cols = Array.from(colgroup.querySelectorAll('col'));
    if (i + 1 >= cols.length) return;

    const headerCells = Array.from(table.rows[0].cells);
    const totalPx = table.getBoundingClientRect().width;
    const widthsPx = headerCells.map((c) => c.getBoundingClientRect().width);
    const startX = e.clientX;
    const minPx = 40;

    table.__dragging = true;
    document.body.style.userSelect = 'none';
    document.body.style.cursor = 'col-resize';

    const onMove = (ev) => {
      const deltaPx = ev.clientX - startX;
      let newCur = widthsPx[i] + deltaPx;
      let newNext = widthsPx[i + 1] - deltaPx;
      if (newCur < minPx) { newNext -= minPx - newCur; newCur = minPx; }
      if (newNext < minPx) { newCur -= minPx - newNext; newNext = minPx; }
      if (newCur < minPx) newCur = minPx;
      if (newNext < minPx) newNext = minPx;
      cols[i].style.width = (newCur / totalPx * 100).toFixed(2) + '%';
      cols[i + 1].style.width = (newNext / totalPx * 100).toFixed(2) + '%';
    };
    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      document.body.style.userSelect = '';
      document.body.style.cursor = '';
      table.__dragging = false;
      Array.from(table.querySelectorAll('th, td')).forEach((c) => { c.classList.remove('col-edge'); c.style.cursor = ''; });
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }
  async function loadContent(path, content, pageWidth, draftRecovered, zh) {
    filePath = path;
    if (pageWidth) setPageWidth(pageWidth);
    if (zh !== undefined) isZh = zh;
    await renderMarkdown(content, document.getElementById('content'));
    document.getElementById('textarea').value = content;
    syncHighlight();
    lastPushedHash = contentHash(content);
    isDirty = false;
    renderedDirty = false;
    if (window.pywebview && window.pywebview.api) window.pywebview.api.set_dirty(false);
    isSource = false;
    updateView();
    if (draftRecovered) showDraftRecoveredBanner();
  }

  function showDraftRecoveredBanner() {
    const banner = document.createElement('div');
    banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:950;background:#fff3cd;border-bottom:1px solid #ffc107;color:#856404;padding:8px 16px;font-size:13px;display:flex;align-items:center;gap:12px;justify-content:center;';
    const msg = isZh
      ? '已恢复上次未保存的修改。'
      : 'Unsaved changes from a previous session have been restored.';
    const discardText = isZh ? '放弃' : 'Discard';
    const dismissText = isZh ? '忽略' : 'Dismiss';
    banner.innerHTML = '<span>' + msg + '</span>' +
      '<a href="#" id="draftDiscard" style="color:#856404;font-weight:600;text-decoration:underline;">' + discardText + '</a>' +
      '<a href="#" id="draftDismiss" style="color:#856404;text-decoration:underline;">' + dismissText + '</a>';
    document.body.appendChild(banner);
    const discard = document.getElementById('draftDiscard');
    const dismiss = document.getElementById('draftDismiss');
    const remove = () => { if (banner.parentNode) banner.parentNode.removeChild(banner); };
    discard.addEventListener('click', (e) => {
      e.preventDefault();
      if (window.pywebview && window.pywebview.api) window.pywebview.api.discard_draft();
      // Reload the original file content
      if (window.pywebview && window.pywebview.api) {
        window.pywebview.api.get_initial_content().then((data) => loadContent(data.path, data.content, data.pageWidth, data.draftRecovered, data.isZh));
      }
      remove();
    });
    dismiss.addEventListener('click', (e) => { e.preventDefault(); remove(); });
    setTimeout(remove, 8000);
  }

  function reloadContent() {
    if (window.pywebview && window.pywebview.api) {
      window.pywebview.api.get_initial_content().then((data) => loadContent(data.path, data.content, data.pageWidth, data.draftRecovered, data.isZh));
    }
  }

  // ── Cursor sync: rendered → source ──
  // Strategy: find the block element (p, h1, li, etc.) containing the cursor,
  // get its text, search for it in markdown, then apply cursor offset within the block.
  function syncToSource() {
    const content = document.getElementById('content');
    const textarea = document.getElementById('textarea');
    const md = textarea.value;
    const sel = window.getSelection();

    if (!sel || sel.rangeCount === 0 || !content.contains(sel.anchorNode)) {
      textarea.setSelectionRange(0, 0);
      textarea.focus();
      return;
    }

    const range = sel.getRangeAt(0);
    const hasSelection = !range.collapsed;

    if (hasSelection) {
      // Selection: find start and end positions separately using block method
      const startPos = findRenderedPosInMarkdown(content, md, range.startContainer, range.startOffset);
      const endPos = findRenderedPosInMarkdown(content, md, range.endContainer, range.endOffset);
      if (startPos >= 0 && endPos >= 0 && endPos >= startPos) {
        textarea.setSelectionRange(startPos, endPos);
      } else if (startPos >= 0) {
        textarea.setSelectionRange(startPos, startPos);
      } else {
        textarea.setSelectionRange(0, 0);
      }
    } else {
      // No selection: find block element containing cursor
      const info = getBlockInfo(content, range);
      if (!info || !info.text) {
        textarea.setSelectionRange(0, 0);
        textarea.focus();
        return;
      }

      // Search for block text in markdown
      const blockPos = findInMarkdown(md, info.text);

      if (blockPos >= 0) {
        // Position cursor at blockPos + offset within block
        // Need to account for markdown syntax at the start of the block
        const afterBlock = md.substring(blockPos);
        const syntaxLen = countLeadingSyntax(afterBlock, info.text);
        const cursorPos = blockPos + syntaxLen + info.offset;
        textarea.setSelectionRange(cursorPos, cursorPos);
      } else {
        // Fallback: search for a snippet around cursor
        const snipStart = Math.max(0, info.offset - 15);
        const snipEnd = Math.min(info.text.length, info.offset + 15);
        const snippet = info.text.substring(snipStart, snipEnd);
        const snipPos = findInMarkdown(md, snippet);
        if (snipPos >= 0) {
          textarea.setSelectionRange(snipPos + (info.offset - snipStart), snipPos + (info.offset - snipStart));
        } else {
          textarea.setSelectionRange(0, 0);
        }
      }
    }

    textarea.focus();
    scrollToTextareaCursor(textarea, md);
  }

  // Find a rendered position's corresponding markdown position
  // Uses block element text + cursor offset within block
  function findRenderedPosInMarkdown(root, md, node, offset) {
    // Find block element containing this node
    let el = node;
    if (el.nodeType === Node.TEXT_NODE) el = el.parentElement;
    const blockTags = 'P,H1,H2,H3,H4,H5,H6,LI,BLOCKQUOTE,PRE,TD,TH,DIV,DD,DT';
    while (el && el !== root) {
      if (el.matches && el.matches(blockTags)) break;
      el = el.parentElement;
    }
    if (!el || el === root) return -1;

    const blockText = el.textContent;
    if (!blockText) return -1;

    // Calculate offset within block's text content
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null, false);
    let cursorInBlock = 0;
    let found = false;
    let tn;
    while (tn = walker.nextNode()) {
      if (tn === node) {
        cursorInBlock += offset;
        found = true;
        break;
      }
      cursorInBlock += tn.textContent.length;
    }
    if (!found) return -1;

    // Search for block text in markdown
    const blockPos = findInMarkdown(md, blockText);
    if (blockPos < 0) return -1;

    // Count leading markdown syntax before block text
    const afterBlock = md.substring(blockPos);
    const syntaxLen = countLeadingSyntax(afterBlock, blockText);

    return blockPos + syntaxLen + cursorInBlock;
  }

  // Get the block element and cursor offset within it
  function getBlockInfo(root, range) {
    let el = range.startContainer;
    if (el.nodeType === Node.TEXT_NODE) el = el.parentElement;

    // Walk up to find block-level element
    const blockTags = 'P,H1,H2,H3,H4,H5,H6,LI,BLOCKQUOTE,PRE,TD,TH,DIV,DD,DT';
    while (el && el !== root) {
      if (el.matches && el.matches(blockTags)) break;
      el = el.parentElement;
    }
    if (!el || el === root) return null;

    // Get text content of the block
    const blockText = el.textContent;
    if (!blockText) return null;

    // Calculate cursor offset within the block's text content
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null, false);
    let offset = 0;
    let found = false;
    let tn;
    while (tn = walker.nextNode()) {
      if (tn === range.startContainer) {
        offset += range.startOffset;
        found = true;
        break;
      }
      offset += tn.textContent.length;
    }

    return { text: blockText, offset: found ? offset : 0, element: el };
  }

  // Count leading markdown syntax characters before the actual text
  function countLeadingSyntax(mdSnippet, targetText) {
    // The md snippet starts with the block text, possibly prefixed by syntax
    // e.g., "# Hello" → targetText is "Hello", syntax is "# " (2 chars)
    // e.g., "- item" → targetText is "item", syntax is "- " (2 chars)
    // e.g., "**bold**" → targetText is "bold", syntax is "**" (2 chars)
    let i = 0;
    while (i < mdSnippet.length && i < mdSnippet.length - targetText.length + 1) {
      // Check if the rest of mdSnippet from position i matches targetText
      const rest = mdSnippet.substring(i);
      if (rest.startsWith(targetText) || textMatches(rest, targetText)) {
        return i;
      }
      i++;
    }
    return 0;
  }

  // Check if two texts match (whitespace-normalized)
  function textMatches(a, b) {
    return a.replace(/\s+/g, ' ').trim().startsWith(b.replace(/\s+/g, ' ').trim());
  }

  // Search for text in markdown, trying exact then normalized match
  function findInMarkdown(md, text) {
    if (!text) return -1;
    // Exact search
    let pos = md.indexOf(text);
    if (pos >= 0) return pos;
    // Normalized: collapse whitespace
    const normText = text.replace(/\s+/g, ' ').trim();
    if (normText.length < 3) return -1;
    // Build normalized md with position map
    const { norm, map } = normalizeForSearch(md);
    let npos = norm.indexOf(normText);
    if (npos < 0) npos = norm.lastIndexOf(normText);
    if (npos >= 0 && npos < map.length) {
      return map[npos];
    }
    return -1;
  }

  function normalizeForSearch(text) {
    let norm = '';
    let map = [];
    for (let i = 0; i < text.length; i++) {
      if (/\s/.test(text[i])) {
        if (norm.length === 0 || norm[norm.length - 1] !== ' ') {
          norm += ' ';
          map.push(i);
        }
      } else {
        norm += text[i];
        map.push(i);
      }
    }
    return { norm, map };
  }

  // ── Cursor sync: source → rendered ──
  // Strategy: get the line text at cursor in textarea, search for it in rendered content
  function syncToRendered() {
    const content = document.getElementById('content');
    const textarea = document.getElementById('textarea');
    const md = textarea.value;
    const cursorPos = textarea.selectionStart;
    const selLen = textarea.selectionEnd - textarea.selectionStart;

    if (cursorPos === 0 && selLen === 0) {
      content.focus();
      return;
    }

    // Get the line text at cursor position in markdown
    const lineStart = md.lastIndexOf('\n', cursorPos - 1) + 1;
    const lineEnd = md.indexOf('\n', cursorPos);
    const lineText = md.substring(lineStart, lineEnd >= 0 ? lineEnd : md.length);
    const cursorInLine = cursorPos - lineStart;

    // Strip markdown syntax from line text to get plain text
    const plainLine = stripMarkdownSyntax(lineText);
    if (!plainLine) {
      content.focus();
      return;
    }

    // Search for plainLine in rendered text content
    const fullText = content.textContent;
    const { norm, map } = normalizeForSearch(fullText);
    const plainNorm = plainLine.replace(/\s+/g, ' ').trim();

    let npos = norm.indexOf(plainNorm);
    if (npos < 0) {
      // Try last occurrence
      npos = norm.lastIndexOf(plainNorm);
    }
    if (npos < 0 && plainNorm.length > 5) {
      // Try shorter
      npos = norm.indexOf(plainNorm.slice(0, Math.floor(plainNorm.length / 2)));
    }

    if (npos < 0) {
      content.focus();
      return;
    }

    // Calculate the rendered text offset
    const renderedOffset = map[npos] + cursorInLine;

    // Find DOM range at this offset
    let range;
    if (selLen > 0) {
      // Selection: find both start and end
      const selEndInLine = cursorInLine + selLen;
      const renderedEnd = map[npos] + selEndInLine;
      range = findRangeBetween(content, renderedOffset, renderedEnd);
    } else {
      range = findRangeAtOffset(content, renderedOffset);
    }

    if (!range) {
      // Fallback: try just the block start
      range = findRangeAtOffset(content, map[npos]);
    }

    if (!range) { content.focus(); return; }

    const newSel = window.getSelection();
    newSel.removeAllRanges();
    newSel.addRange(range);
    content.focus();

    // Scroll into view
    const rect = range.getBoundingClientRect();
    if (rect) {
      const wrap = document.querySelector('.scroll-wrap');
      const wrapRect = wrap.getBoundingClientRect();
      if (rect.top < wrapRect.top + 60 || rect.bottom > wrapRect.bottom) {
        wrap.scrollTo({ top: wrap.scrollTop + rect.top - wrapRect.top - 80, behavior: 'auto' });
      }
    }
  }

  function stripMarkdownSyntax(text) {
    return text
      .replace(/^#{1,6}\s*/, '')
      .replace(/^[-*+]\s+/, '')
      .replace(/^>\s*/, '')
      .replace(/^\d+\.\s+/, '')
      .replace(/^\|/, '')
      .replace(/\*\*(.+?)\*\*/g, '$1')
      .replace(/\*(.+?)\*/g, '$1')
      .replace(/__(.+?)__/g, '$1')
      .replace(/_(.+?)_/g, '$1')
      .replace(/~~(.+?)~~/g, '$1')
      .replace(/`([^`]+)`/g, '$1')
      .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
      .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
      .replace(/\|/g, ' ')
      .trim();
  }

  function scrollToTextareaCursor(textarea, md) {
    const lines = md.substring(0, textarea.selectionStart).split('\n').length;
    document.querySelector('.scroll-wrap').scrollTo({ top: Math.max(0, (lines - 1) * 25 - 100), behavior: 'auto' });
  }

  // Find DOM range at a character offset in contenteditable
  function findRangeAtOffset(root, offset) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
    let current = 0;
    let node;
    while (node = walker.nextNode()) {
      const len = node.textContent.length;
      if (current + len >= offset) {
        const range = document.createRange();
        range.setStart(node, Math.min(offset - current, len));
        range.collapse(true);
        return range;
      }
      current += len;
    }
    return null;
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

  // ── View toggle ──
  async function toggleView() {
    if (!isSource) {
      // rendered → source: capture cursor, convert, position
      const content = document.getElementById('content');
      const textarea = document.getElementById('textarea');
      if (renderedDirty) {
        // Only round-trip the DOM when the user actually edited the rendered view.
        const html = content.innerHTML;
        textarea.value = turndownService ? turndownService.turndown(html) : html;
      }
      // Otherwise the textarea already holds the pristine markdown.
      syncHighlight();
      isSource = true;
      updateView();
      syncToSource();
    } else {
      // source → rendered: capture cursor, convert, position
      const md = document.getElementById('textarea').value;
      if (contentHash(md) !== lastRenderedHash) {
        await renderMarkdown(md, document.getElementById('content'));
      }
      renderedDirty = false;
      isSource = false;
      updateView();
      syncToRendered();
    }
  }

  function updateView() {
    const content = document.getElementById('content');
    const source = document.getElementById('source');
    const hint = document.getElementById('sourceHint');
    const page = document.getElementById('page');
    if (isSource) {
      content.classList.add('hidden');
      source.classList.add('visible');
      hint.classList.add('visible');
      page.classList.add('full-width');
    } else {
      content.classList.remove('hidden');
      source.classList.remove('visible');
      hint.classList.remove('visible');
      page.classList.remove('full-width');
    }
    updateEmptyState();
  }

  function updateEmptyState() {
    const content = document.getElementById('content');
    // Show welcome overlay only when content is truly empty (no text, no child elements)
    const isEmpty = !isSource && content.textContent.trim() === '' && content.children.length === 0;
    if (isEmpty) {
      // Build a non-editable overlay that sits on top of the empty contenteditable.
      // The contenteditable itself stays empty so the cursor lands at position 0.
      let overlay = document.getElementById('welcomeOverlay');
      if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'welcomeOverlay';
        overlay.className = 'welcome-overlay';
        const tips = isZh
          ? '拖拽 <strong>.md</strong> 文件到此处，或双击打开'
          : 'Drag a <strong>.md</strong> file here, or double click to open';
        const toggleTip = isZh
          ? '<kbd>⌘</kbd><kbd>E</kbd> 切换源码 / 预览'
          : '<kbd>⌘</kbd><kbd>E</kbd> to toggle source / preview';
        const title = isZh ? '开始书写' : 'Start writing';
        overlay.innerHTML = '<div class="welcome-icon">&#9998;</div>' +
          '<div class="welcome-title">' + title + '</div>' +
          '<div class="welcome-tip">' + tips + '</div>' +
          '<div class="welcome-tip">' + toggleTip + '</div>';
        content.parentNode.appendChild(overlay);
        // Clicking anywhere on the content area focuses the editor and dismisses overlay
        overlay.addEventListener('click', () => {
          content.focus();
          // Place cursor at the very beginning
          const range = document.createRange();
          range.selectNodeContents(content);
          range.collapse(true);
          const sel = window.getSelection();
          sel.removeAllRanges();
          sel.addRange(range);
          dismissWelcomeOverlay();
        });
      }
    } else {
      dismissWelcomeOverlay();
    }
  }

  function dismissWelcomeOverlay() {
    const overlay = document.getElementById('welcomeOverlay');
    if (overlay) {
      overlay.classList.add('welcome-fadeout');
      setTimeout(() => { if (overlay.parentNode) overlay.parentNode.removeChild(overlay); }, 200);
    }
  }

  // ── Save ──
  function getCurrentMarkdown() {
    if (isSource) return document.getElementById('textarea').value;
    if (!renderedDirty) return document.getElementById('textarea').value;
    const html = document.getElementById('content').innerHTML;
    return turndownService ? turndownService.turndown(html) : html;
  }

  function markSaved(markdown) {
    isDirty = false;
    renderedDirty = false;
    if (window.pywebview && window.pywebview.api) window.pywebview.api.set_dirty(false);
    document.getElementById('textarea').value = markdown;
    lastPushedHash = contentHash(markdown);
    syncHighlight();
  }

  async function saveFile() {
    if (!window.pywebview || !window.pywebview.api) {
      showStatus('Save is not ready yet', true);
      return;
    }
    const markdown = getCurrentMarkdown();
    if (!filePath || filePath === 'Untitled.md') {
      // Untitled document — show Save As dialog
      await saveAsFile();
      return;
    }
    try {
      const result = await window.pywebview.api.save_file(filePath, markdown);
      if (result.success) {
        markSaved(markdown);
        showStatus('Saved');
      } else {
        showStatus(result.error ? 'Save failed: ' + result.error : 'Save failed', true);
      }
    } catch (err) {
      showStatus('Save failed: ' + (err && err.message ? err.message : err), true);
    }
  }

  async function saveAsFile() {
    if (!window.pywebview || !window.pywebview.api) {
      showStatus('Save is not ready yet', true);
      return;
    }
    const markdown = getCurrentMarkdown();
    try {
      const result = await window.pywebview.api.save_as_dialog(markdown);
      if (result.success) {
        filePath = result.path;
        markSaved(markdown);
        showStatus('Saved');
      } else if (!result.cancelled) {
        showStatus(result.error ? 'Save failed: ' + result.error : 'Save failed', true);
      }
    } catch (err) {
      showStatus('Save failed: ' + (err && err.message ? err.message : err), true);
    }
  }

  let statusTimer = null;
  function showStatus(text, isError = false) {
    const el = document.getElementById('status');
    el.textContent = text;
    el.classList.toggle('error', !!isError);
    el.classList.add('visible');
    clearTimeout(statusTimer);
    statusTimer = setTimeout(() => el.classList.remove('visible'), isError ? 5000 : 1500);
  }

  // ── Find ──
  let findState = { query: '', matches: [], currentIdx: -1, scrollTop: 0 };

  function openFindBar() {
    const bar = document.getElementById('findBar');
    const input = document.getElementById('findInput');
    bar.classList.add('visible');
    // Push content down so the bar doesn't overlap
    document.querySelector('.scroll-wrap').style.top = '40px';
    input.focus();
    // Pre-fill with current selection
    const sel = window.getSelection().toString();
    if (sel) { input.value = sel; doFind(); }
    else { input.select(); }
  }

  function closeFindBar() {
    const bar = document.getElementById('findBar');
    bar.classList.remove('visible');
    document.querySelector('.scroll-wrap').style.top = '';
    clearFindHighlights();
    document.getElementById('findCount').textContent = '';
    findState = { query: '', matches: [], currentIdx: -1, scrollTop: 0 };
    // Return focus to editor
    if (isSource) document.getElementById('textarea').focus();
    else document.getElementById('content').focus();
  }

  function getSearchableText() {
    if (isSource) return document.getElementById('textarea');
    return document.getElementById('content');
  }

  function doFind() {
    const query = document.getElementById('findInput').value;
    if (!query) {
      clearFindHighlights();
      document.getElementById('findCount').textContent = '';
      findState = { query: '', matches: [], currentIdx: -1, scrollTop: 0 };
      return;
    }

    if (isSource) {
      findInTextarea(query);
    } else {
      findInContentEditable(query);
    }
  }

  function findInTextarea(query) {
    const textarea = document.getElementById('textarea');
    const text = textarea.value;
    const matches = [];
    const lowerText = text.toLowerCase();
    const lowerQuery = query.toLowerCase();
    let pos = 0;
    while (true) {
      const idx = lowerText.indexOf(lowerQuery, pos);
      if (idx === -1) break;
      matches.push(idx);
      pos = idx + query.length;
    }
    findState.query = query;
    findState.matches = matches;

    const countEl = document.getElementById('findCount');
    if (matches.length === 0) {
      countEl.textContent = '0/0';
      findState.currentIdx = -1;
    } else {
      // Find the match closest to the current cursor
      const cursor = textarea.selectionStart;
      let idx = 0;
      for (let i = 0; i < matches.length; i++) {
        if (matches[i] >= cursor) { idx = i; break; }
        idx = i;
      }
      findState.currentIdx = idx;
      countEl.textContent = (idx + 1) + '/' + matches.length;
      scrollToTextareaMatch(idx);
    }
    updateFindButtons();
  }

  function scrollToTextareaMatch(idx) {
    const textarea = document.getElementById('textarea');
    const start = findState.matches[idx];
    const end = start + findState.query.length;
    textarea.focus();
    textarea.setSelectionRange(start, end);
    // Scroll into view
    const lines = textarea.value.substring(0, start).split('\n').length;
    const lineHeight = 25;
    document.querySelector('.scroll-wrap').scrollTo({ top: Math.max(0, (lines - 1) * lineHeight - 100), behavior: 'auto' });
  }

  function clearFindHighlights() {
    const content = document.getElementById('content');
    const marks = content.querySelectorAll('mark.find-highlight');
    for (const mark of marks) {
      const parent = mark.parentNode;
      parent.replaceChild(document.createTextNode(mark.textContent), mark);
      parent.normalize();
    }
  }

  function findInContentEditable(query) {
    clearFindHighlights();
    const content = document.getElementById('content');
    const matches = [];
    const lowerQuery = query.toLowerCase();
    const text = content.textContent || '';
    const lowerText = text.toLowerCase();
    let pos = 0;
    while (true) {
      const idx = lowerText.indexOf(lowerQuery, pos);
      if (idx === -1) break;
      matches.push(idx);
      pos = idx + query.length;
    }

    findState.query = query;
    findState.matches = matches;

    const countEl = document.getElementById('findCount');
    if (matches.length === 0) {
      countEl.textContent = '0/0';
      findState.currentIdx = -1;
    } else {
      findState.currentIdx = 0;
      countEl.textContent = '1/' + matches.length;
      // Highlight current match
      highlightCurrentMatch();
    }
    updateFindButtons();
  }

  function highlightCurrentMatch() {
    clearFindHighlights();
    const content = document.getElementById('content');
    if (findState.currentIdx < 0 || findState.currentIdx >= findState.matches.length) return;
    const start = findState.matches[findState.currentIdx];
    const range = findRangeBetween(content, start, start + findState.query.length);
    if (!range) return;
    const mark = document.createElement('mark');
    mark.className = 'find-highlight current';
    try {
      range.surroundContents(mark);
    } catch (e) {
      return;
    }
    const rect = mark.getBoundingClientRect();
    const wrap = document.querySelector('.scroll-wrap');
    const wrapRect = wrap.getBoundingClientRect();
    if (rect.top < wrapRect.top + 60 || rect.bottom > wrapRect.bottom) {
      wrap.scrollTo({ top: wrap.scrollTop + rect.top - wrapRect.top - 80, behavior: 'auto' });
    }
  }

  function findNext() {
    if (findState.matches.length === 0) return;
    findState.currentIdx = (findState.currentIdx + 1) % findState.matches.length;
    if (isSource) {
      scrollToTextareaMatch(findState.currentIdx);
    } else {
      highlightCurrentMatch();
    }
    document.getElementById('findCount').textContent = (findState.currentIdx + 1) + '/' + findState.matches.length;
    updateFindButtons();
  }

  function findPrev() {
    if (findState.matches.length === 0) return;
    findState.currentIdx = (findState.currentIdx - 1 + findState.matches.length) % findState.matches.length;
    if (isSource) {
      scrollToTextareaMatch(findState.currentIdx);
    } else {
      highlightCurrentMatch();
    }
    document.getElementById('findCount').textContent = (findState.currentIdx + 1) + '/' + findState.matches.length;
    updateFindButtons();
  }

  function updateFindButtons() {
    const has = findState.matches.length > 0;
    document.getElementById('findNext').disabled = !has;
    document.getElementById('findPrev').disabled = !has;
  }

  // Find bar events
  document.getElementById('findInput').addEventListener('input', () => { doFind(); });
  document.getElementById('findInput').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); e.shiftKey ? findPrev() : findNext(); }
    if (e.key === 'Escape') { e.preventDefault(); closeFindBar(); }
  });
  document.getElementById('tocToggle').addEventListener('click', toggleToc);
  document.getElementById('findNext').addEventListener('click', findNext);
  document.getElementById('findPrev').addEventListener('click', findPrev);
  document.getElementById('findClose').addEventListener('click', closeFindBar);

  // ── Events ──
  document.addEventListener('keydown', (e) => {
    const cmd = e.metaKey;
    if (cmd && e.key === 's') { e.preventDefault(); e.shiftKey ? saveAsFile() : saveFile(); }
    if (cmd && e.altKey && e.key === 'o') { e.preventDefault(); toggleToc(); return; }
    if (cmd && e.key === 'o') { e.preventDefault(); openFile(); }
    if (cmd && e.key === 'w') { e.preventDefault(); closeWindow(); }
    if (cmd && e.key === '0') { e.preventDefault(); resetPageWidth(); }
    if (cmd && e.key === ',') { e.preventDefault(); showPreferences(); }
    if (cmd && e.key === 'e') { e.preventDefault(); toggleView(); }
    if (cmd && e.key === 'i') { e.preventDefault(); showFileProperties(); }
    if (cmd && e.key === 'f') { e.preventDefault(); openFindBar(); }
    if (cmd && e.key === 'g') { e.preventDefault(); e.shiftKey ? findPrev() : findNext(); }
  });

  function isBlockedHref(href) {
    return !href || /^\s*(javascript:|data:)/i.test(href);
  }

  function isExternalHref(href) {
    return /^[a-z][a-z0-9+.-]*:/i.test(href) || href.startsWith('//');
  }

  // Open external links in the default browser and support in-document anchors.
  document.addEventListener('click', (e) => {
    const a = e.target.closest('a[href]');
    if (!a) return;
    const href = (a.getAttribute('href') || '').trim();
    if (isBlockedHref(href)) {
      e.preventDefault();
      return;
    }
    if (href.startsWith('#')) {
      e.preventDefault();
      scrollToHash(href);
      return;
    }
    if (isExternalHref(href)) {
      e.preventDefault();
      if (window.pywebview && window.pywebview.api) window.pywebview.api.open_external_link(href);
      return;
    }
    // Keep relative document links from navigating the editor webview away.
    // Image-relative support is handled during rendering; relative document links can be opened later.
    e.preventDefault();
  });

  function contentHash(text) {
    let hash = 0;
    for (let i = 0; i < text.length; i++) hash = ((hash << 5) - hash + text.charCodeAt(i)) | 0;
    return text.length + ':' + hash;
  }

  // Called by the native side right before the window closes: cancel every
  // timer and stop new JS->Python bridge calls. This prevents a bridge call
  // from being in flight while WKWebView is torn down, which could otherwise
  // leave a non-daemon pywebview thread blocked forever and deadlock the
  // interpreter on exit.
  function prepareForClose() {
    closing = true;
    clearTimeout(pythonSyncTimer);
    clearTimeout(highlightTimer);
    clearTimeout(statusTimer);
    if (keepAliveTimer) { clearInterval(keepAliveTimer); keepAliveTimer = null; }
  }

  let pythonSyncTimer = null;

  function pushContentToPython(force = false) {
    if (closing) return;
    if (!window.pywebview || !window.pywebview.api) return;
    if (!force && !isDirty) return;
    const markdown = getCurrentMarkdown();
    const hash = contentHash(markdown);
    if (!force && hash === lastPushedHash) return;
    lastPushedHash = hash;
    window.pywebview.api.store_content(markdown);
  }

  function schedulePythonSync(delay = 900) {
    if (closing) return;
    clearTimeout(pythonSyncTimer);
    pythonSyncTimer = setTimeout(() => pushContentToPython(false), delay);
  }

  function setDirty(dirty) {
    if (isDirty === dirty) return;
    isDirty = dirty;
    if (window.pywebview && window.pywebview.api) window.pywebview.api.set_dirty(dirty);
  }

  document.getElementById('content').addEventListener('input', () => { renderedDirty = true; setDirty(true); schedulePythonSync(1800); dismissWelcomeOverlay(); });
  document.getElementById('textarea').addEventListener('input', () => { setDirty(true); scheduleHighlightSync(); schedulePythonSync(700); });
  document.addEventListener('dragover', (e) => e.preventDefault());
  document.addEventListener('drop', handleImageDrop);
  window.addEventListener('resize', handleTocResize);
  keepAliveTimer = setInterval(() => { if (!closing && isSource) pushContentToPython(false); }, 5000);

  window.addEventListener('pywebviewready', () => {
    window.pywebview.api.get_initial_content().then((data) => loadContent(data.path, data.content, data.pageWidth, data.draftRecovered, data.isZh));
  });
