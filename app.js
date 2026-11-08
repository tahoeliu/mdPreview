const documentSession = new DocumentSession();
let appSettings={remote_images:'ask',auto_update:true,auto_reload:true,font_size:16,page_width:720,restore_session:false,language:'system',format_bar:false,reading_font:'sans'};
let saveInFlight = null;
let syncInFlight = null;
let syncRetryCount = 0;
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
  let highlightRaf = null;      // pending rAF for the source highlight layer
  let _highlightHeavy = false; // true once a sync pass takes >24ms (big docs)
  let lastPushedHash = '';
  let lastRenderedHash = '';
  // Set by prepareForClose() when the window is closing: stops all timers and
  // pending JS->Python bridge traffic so teardown never deadlocks.
  let closing = false;
  let keepAliveTimer = null;
  let closePromptVisible = false;
  let isZh = false;
  let renderJobId = 0;
  let deferredRenderTimer = null;
  // Centralized tuning knobs (kept together so they are easy to find/adjust).
  const TOC_AUTO_HIDE_WIDTH = 800;   // below this window width the TOC auto-hides
  const TOC_WIDTH = 200;
  // MacBook Air 13-inch default scaled full-screen width in CSS pixels.
  // Up to this width, keep the reading page centered in the area to the right
  // of the TOC. Past this width, hold the left-side spacing steady until the
  // full-window center catches up, then switch to full-window centering.
  const TOC_RIGHT_PANE_CENTER_MAX_WIDTH = 1470;
  const FONT_MIN = 12;
  const FONT_MAX = 24;
  const FONT_STEP = 1;
  const PYTHON_SYNC_DEBOUNCE_MS = 1800;  // debounce for pushing content to Python
  const STATUS_HIDE_MS = 8000;           // error status auto-hide delay

  // Bilingual helper: returns the Chinese string when the app UI is in
  // Chinese (isZh is set from the backend's locale detection), English otherwise.
  function t(en, zh) {
    return I18n.t(en, zh);
  }

  if (typeof marked !== 'undefined') marked.setOptions({ breaks: true, gfm: true });

  // Make native Enter create <p> paragraphs (not <div>s) in the rendered
  // contenteditable. WebKit's <div> paragraph junk otherwise corrupts the
  // markdown round trip (turndown treats bare <div>s as inline content).
  try { document.execCommand('defaultParagraphSeparator', false, 'p'); } catch (err) {}

  const _jsT0 = performance.now();  // cold-start profiling

  // These are loaded on-demand to speed up cold start by ~300-500ms.
  let _turndownLoaded = false;
  let _mermaidLoaded = false;
  let _mermaidLoadingPromise = null;

  // A heading such as "## Mermaid" gets id="mermaid", and browsers expose
  // elements with an id as window.mermaid. Treat DOM nodes as "not loaded".
  function libraryReady(name) {
    const value = window[name];
    return value !== undefined && value !== null &&
      !(value instanceof Element) && !(value instanceof HTMLCollection);
  }

  function ensureLib(src, globalName) {
    // Load a vendored library on demand; resolves when its global is present.
    if (libraryReady(globalName)) return Promise.resolve();
    return _loadScript(src).then(() => {
      if (!libraryReady(globalName)) {
        throw new Error(globalName + ' failed to load');
      }
    });
  }

  const libraryLoads = new Map();
  function _loadScript(src) {
    if (libraryLoads.has(src)) return libraryLoads.get(src);
    const task = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = src;
      script.onload = () => resolve();
      script.onerror = () => { script.remove(); reject(new Error('Failed to load ' + src)); };
      document.head.appendChild(script);
    }).catch((error) => { libraryLoads.delete(src); throw error; });
    libraryLoads.set(src, task);
    return task;
  }


var {
  _initTurndown, ensureTurndown,
} = MarkdownConversion.create({
  _loadScript: (...args) => _loadScript(...args),
  state: {
    get turndownService() { return turndownService; },
    set turndownService(value) { turndownService = value; },
    get _turndownLoaded() { return _turndownLoaded; },
    set _turndownLoaded(value) { _turndownLoaded = value; },
  },
  get TurndownService() { return typeof TurndownService === 'undefined' ? undefined : TurndownService; }
});
  function getMermaidTheme() {
    if (document.documentElement.hasAttribute('data-output')) return 'default';
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'default';
  }
  function initMermaid() {
    if (!libraryReady('mermaid')) return;
    mermaid.initialize({
      startOnLoad: false,
      theme: getMermaidTheme(),
      securityLevel: 'strict',
      secure: ['securityLevel','htmlLabels','flowchart','themeCSS','startOnLoad'],
      suppressErrorRendering: true,
      // Native SVG labels survive strict sanitization and stay sharp in the viewer.
      htmlLabels: false,
      flowchart: { useMaxWidth: true, htmlLabels: false },
      sequence: { useMaxWidth: true },
    });
  }
  function ensureMermaid() {
    if (_mermaidLoaded) return Promise.resolve();
    if (_mermaidLoadingPromise) return _mermaidLoadingPromise;
    if (libraryReady('mermaid')) { initMermaid(); _mermaidLoaded = true; return Promise.resolve(); }
    _mermaidLoadingPromise = _loadScript('vendor/mermaid.min.js').then(() => { initMermaid(); _mermaidLoaded = true; }).finally(() => { _mermaidLoadingPromise = null; });
    return _mermaidLoadingPromise;
  }
  initMermaid();
  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      if (_mermaidLoaded) {
        initMermaid();
        mermaidSvgCache.clear();
        renderMermaidDiagrams(document.getElementById('content'));
      }
    });
  }

  function sanitizeMermaidSvg(svg) { return MarkdownPipeline.cleanSVG(svg); }

  function assertMermaidSafe(source) {
    // 保守限定旧式无资源语法；拒绝所有扩展属性、HTML、实体/转义及配置指令。
    // 不尝试用URL正则理解Mermaid/YAML：未知语法安全失败，避免render内部先请求。
    const text = String(source).normalize('NFKC');
    if (text.trimStart().startsWith('---') || text.includes('%%{') || text.replace(/\s/g,'').toLowerCase().includes('url(') ||
        [...text].some(char => ['@','<','&','\\','!'].includes(char)))
      throw new Error('Mermaid 外部资源或扩展语法已禁用 (blocked)');
  }

  async function renderSafeMermaid(id, source) {
    assertMermaidSafe(source);
    if (mermaid.mermaidAPI?.getDiagramFromText) {
      const diagram = await mermaid.mermaidAPI.getDiagramFromText(source);
      const vertices = diagram.db?.getVertices?.();
      for (const vertex of vertices instanceof Map ? vertices.values() : Object.values(vertices || {})) {
        if (vertex.img || vertex.image || vertex.icon) throw new Error('Mermaid 图片节点已禁用 (blocked)');
      }
    }
    return mermaid.render(id, source);
  }

  async function renderMermaidDiagrams(root) {
    const codeBlocks = root.matches?.('code.language-mermaid') ? [root] : root.querySelectorAll('code.language-mermaid');
    const generation = renderJobId;
    if (codeBlocks.length === 0) return;
    try { await ensureMermaid(); } catch (error) { showStatus(error.message, true); return; }
    if (!libraryReady('mermaid')) return;
    for (const code of codeBlocks) {
      if (generation !== renderJobId || closing || !code.isConnected) return;
      const pre = code.parentElement;
      if (!pre || pre.nodeName !== 'PRE') continue;
      const source = code.textContent;
      if (!source.trim()) continue;
      try {
        let svg = mermaidSvgCache.get(source);
        if (!svg) {
          const id = 'mermaid-' + Math.random().toString(36).slice(2, 9);
          const rendered = await renderSafeMermaid(id, source);
          svg = rendered.svg;
          if (mermaidSvgCache.size >= 32) mermaidSvgCache.delete(mermaidSvgCache.keys().next().value);
          mermaidSvgCache.set(source, svg);
        }
        if (generation !== renderJobId || closing || !pre.isConnected) return;
        const wrapper = document.createElement('div');
        wrapper.className = 'mermaid-diagram';
        wrapper.setAttribute('data-source', source);
        wrapper.setAttribute('contenteditable', 'false');
        wrapper.innerHTML = sanitizeMermaidSvg(svg);
        if (pre.parentNode && !closing) pre.parentNode.replaceChild(wrapper, pre);
      } catch (e) {
        const error = document.createElement('div');
        error.className = 'mermaid-error';
        error.setAttribute('contenteditable', 'false');
        error.setAttribute('data-raw', '```mermaid\n' + source + '\n```');
        error.textContent = 'Mermaid render error: ' + (e && e.message ? e.message : e);
        if (pre.parentNode && !closing) pre.parentNode.replaceChild(error, pre);
      }
    }
  }

  // Extensions now run in the lexer, so code and HTML attributes are never scanned as prose.
  function preprocessMarkdownExtensions(markdown) { return { body: markdown, footnotes: [], mathBlocks: [] }; }
  function renderMathPlaceholders() {}
  function renderFootnotes() {}

  function containsMermaidFence(markdown) {
    return /(^|\n)\s*(```+|~~~+)\s*mermaid(?:\s|$)/i.test(markdown || '');
  }

  function hasRenderableMermaid(root) {
    return !!(root && root.querySelector && root.querySelector('code.language-mermaid'));
  }

  // ── Render-time HTML sanitizer (stored-XSS defense) ────────────────────────
  // Markdown may contain raw HTML and marked() passes it through verbatim. A
  // hostile document could otherwise inject event handlers (<img onerror>),
  // active elements (<iframe>/<embed>/<link>), or javascript: URLs that run in
  // the WKWebView and reach the Python bridge (save_file, open_external_link,
  // perform_auto_install, ...). That is a P0 stored-XSS vector for an app that
  // opens untrusted files, so rendered HTML is sanitized TWICE:
  //   1. string-level BEFORE innerHTML (otherwise <img onerror> already fires
  //      while the parser sets innerHTML and no DOM pass can undo it);
  //   2. DOM-level AFTER parsing (defense in depth for parser-normalized forms).
  function sanitizeHtmlString(html) { return MarkdownPipeline.cleanHTML(html); }
  function sanitizeRenderedDOM(root) { root.innerHTML = MarkdownPipeline.cleanHTML(root.innerHTML); }


var {
  spanTok, normalizeCodeLanguage, readQuoted, highlightJsonCode, highlightCStyleCode, highlightPythonCode, 
  highlightShellCode, highlightYamlValue, highlightYamlCode, highlightHtmlTag, highlightHtmlCode, 
  highlightCssCode, highlightSqlCode, highlightGenericCode, highlightCodeByLanguage, 
  highlightRenderedCodeBlocks, renderFrontmatter, resolveBlockScalar, highlightInlineMarkdown, 
  highlightMarkdown,
} = SyntaxHighlight.create({
  document,
  escHtml: (...args) => escHtml(...args)
});

var {
  appendParsedMarkdown, finalizeRenderedMarkdown, ensureBlockCaretLandingZones, createRenderCaretSpacer, 
  placeCaretInRenderSpacer, placeCaretAtSafeRenderedLanding, documentLanguage, renderMarkdown, 
  toggleFrontmatter, rewriteRelativeImages, protectComplexBlocks,
} = MarkdownRendering.create({
  document,
  window,
  Node,
  clearTimeout,
  t: (...args) => t(...args),
  preprocessMarkdownExtensions: (...args) => preprocessMarkdownExtensions(...args),
  renderFrontmatter: (...args) => renderFrontmatter(...args),
  renderMathPlaceholders: (...args) => renderMathPlaceholders(...args),
  renderFootnotes: (...args) => renderFootnotes(...args),
  applyHeadingAnchors: (...args) => applyHeadingAnchors(...args),
  highlightRenderedCodeBlocks: (...args) => highlightRenderedCodeBlocks(...args),
  balanceTableColumns: (...args) => balanceTableColumns(...args),
  buildToc: (...args) => buildToc(...args),
  hasRenderableMermaid: (...args) => hasRenderableMermaid(...args),
  renderMermaidDiagrams: (...args) => renderMermaidDiagrams(...args),
  state: {
    get lastRenderedHash() { return lastRenderedHash; },
    set lastRenderedHash(value) { lastRenderedHash = value; },
    get renderJobId() { return renderJobId; },
    set renderJobId(value) { renderJobId = value; },
    get deferredRenderTimer() { return deferredRenderTimer; },
    set deferredRenderTimer(value) { deferredRenderTimer = value; },
    get closing() { return closing; },
    set closing(value) { closing = value; },
    get filePath() { return filePath; },
    set filePath(value) { filePath = value; },
  },
  get RenderPerformance() { return typeof RenderPerformance === 'undefined' ? undefined : RenderPerformance; },
  get MarkdownPipeline() { return typeof MarkdownPipeline === 'undefined' ? undefined : MarkdownPipeline; },
  get LazyRender() { return typeof LazyRender === 'undefined' ? undefined : LazyRender; },
  get ReadingFeatures() { return typeof ReadingFeatures === 'undefined' ? undefined : ReadingFeatures; },
  get MathRenderer() { return typeof MathRenderer === 'undefined' ? undefined : MathRenderer; }
});
  let tocHasContent = false;
  let tocManualOverride = null;

var {
  syncTocToggle, isTocAutoHideWidth, shouldAutoShowToc, updateTocAwarePageLayout, setTocVisible, 
  applyTocVisibility, handleTocResize, buildToc, setupScrollSpy, updateScrollSpy, scheduleScrollSpy, 
  scheduleTocSync, toggleToc, slugifyHeading, applyHeadingAnchors, scrollToHash, getActiveTocTarget, 
  setTocActive, markExplicitTocTarget, placeCaretAtHeading, collectMarkdownHeadingSlugs, 
  findHeadingLineInMarkdown, sourceLineTop, scrollTextareaToLine, scrollToTocTarget, syncPositionToSource, 
  syncPositionToRendered, sourceActiveHeadingSlug, ensureTocActiveVisible, updateSourceTocHighlight, 
  getSourceActiveHeading, scheduleSourceTocHighlight, findRangeBetween,
} = DocumentOutline.create({
  document,
  window,
  Node,
  NodeFilter,
  history,
  getComputedStyle,
  requestAnimationFrame,
  escHtml: (...args) => escHtml(...args),
  t: (...args) => t(...args),
  getPageWidth: (...args) => getPageWidth(...args),
  placeCaretAtSafeRenderedLanding: (...args) => placeCaretAtSafeRenderedLanding(...args),
  state: {
    get isSource() { return isSource; },
    set isSource(value) { isSource = value; },
    get tocHasContent() { return tocHasContent; },
    set tocHasContent(value) { tocHasContent = value; },
    get tocManualOverride() { return tocManualOverride; },
    set tocManualOverride(value) { tocManualOverride = value; },
    get _sourceLayerText() { return _sourceLayerText; },
    set _sourceLayerText(value) { _sourceLayerText = value; },
    get _sourceLineStarts() { return _sourceLineStarts; },
    set _sourceLineStarts(value) { _sourceLineStarts = value; },
  },
  get TOC_AUTO_HIDE_WIDTH() { return typeof TOC_AUTO_HIDE_WIDTH === 'undefined' ? undefined : TOC_AUTO_HIDE_WIDTH; },
  get TOC_WIDTH() { return typeof TOC_WIDTH === 'undefined' ? undefined : TOC_WIDTH; },
  get TOC_RIGHT_PANE_CENTER_MAX_WIDTH() { return typeof TOC_RIGHT_PANE_CENTER_MAX_WIDTH === 'undefined' ? undefined : TOC_RIGHT_PANE_CENTER_MAX_WIDTH; }
});
  // Cached text and per-logical-line start offsets of the highlight layer;
  // the source-mode geometry code uses them to locate a line inside the <pre>
  // (whose rendered text is HTML-escaped, so character offsets differ from
  // the textarea's value).
  let _sourceLayerText = '';
  let _sourceLineStarts = null;

  function syncHighlight() {
    const t0 = performance.now();
    const layer = document.getElementById('highlightLayer');
    const sourceText = document.getElementById('textarea').value;
    layer.innerHTML = (sourceText.length > 500000 ? escHtml(sourceText) : highlightMarkdown(sourceText)) + '\n';
    _sourceLayerText = layer.textContent;
    const starts = [0];
    for (let i = 0; i < _sourceLayerText.length; i++) {
      if (_sourceLayerText[i] === '\n') starts.push(i + 1);
    }
    _sourceLineStarts = starts;
    // Adaptive sync strategy: light documents re-highlight on the next frame so
    // fast typing never shows transparent text (the textarea's own text is
    // transparent; the highlight layer below provides the visible colors). Heavy
    // documents fall back to debouncing so keystrokes never block on a long pass.
    _highlightHeavy = (performance.now() - t0) > 24;
  }

  function scheduleHighlightSync() {
    clearTimeout(highlightTimer);
    if (_highlightHeavy) {
      highlightTimer = setTimeout(syncHighlight, 120);
      return;
    }
    if (highlightRaf === null) {
      highlightRaf = requestAnimationFrame(() => {
        highlightRaf = null;
        syncHighlight();
      });
    }
  }

  // Page width is expressed as a percentage of the base reading-column width.
  // 100% = the default column (720px); each step is ±10% (⌘. / ⌘,), clamped to
  // 50%–280%. The px value stored/used by CSS is derived from this percentage.
  const BASE_WIDTH = 720;
  const WIDTH_STEP = 10;
  const WIDTH_MIN = 50;   // 50%  → 360px
  const WIDTH_MAX = 280;  // 280% → 2016px
  let pageWidthPct = 100;

  function setPageWidth(px) {
    const page = document.getElementById('page');
    page.style.setProperty('--page-width', Math.round(px) + 'px');
  }
  function applyPageWidth() {
    setPageWidth(BASE_WIDTH * pageWidthPct / 100);
    updateTocAwarePageLayout();
  }
  function getPageWidth() {
    const page = document.getElementById('page');
    return parseInt(getComputedStyle(page).getPropertyValue('--page-width').trim()) || 720;
  }
  function normalizePageWidthPct(value) {
    return Math.max(WIDTH_MIN, Math.min(WIDTH_MAX, Math.round(value / WIDTH_STEP) * WIDTH_STEP));
  }
  function adjustPageWidth(deltaPct) {
    pageWidthPct = normalizePageWidthPct(pageWidthPct + deltaPct);
    applyPageWidth();
    showSizeHint('width');
    if (Bridge.ready()) Bridge.callSafe('save_page_width', BASE_WIDTH * pageWidthPct / 100);
  }
  function resetPageWidth() {
    pageWidthPct = 100;
    applyPageWidth();
    showSizeHint('width');
    if (Bridge.ready()) Bridge.callSafe('save_page_width', BASE_WIDTH);
    showStatus(t('Width reset', '宽度已重置'));
  }
  // ── Font size (View menu: ⌘= / ⌘-) ──
  // Adjusts the content font size (±1px) for BOTH the source editor and the
  // rendered markdown, so every visible text element scales together (headings
  // keep their relative ratios via the --content-font-size CSS variable).
  // In-memory only (not persisted), clamped to a sane range.
  let contentFontSize = 16;
  function applyReadingFont() { document.documentElement.setAttribute('data-reading-font', appSettings.reading_font === 'serif' ? 'serif' : 'sans'); }
  window.toggleFormatBar = function () { if (window.formatToolbar) window.formatToolbar.togglePinned(); };
  function applyFontSize() {
    document.documentElement.style.setProperty('--content-font-size', contentFontSize + 'px');
  }
  function resetFontSize(){contentFontSize=16;applyFontSize();Bridge.callSafe('save_font_size',contentFontSize);}
  function zoomIn() {
    if (imageViewer.active) { imageViewer.zoomIn(); return; }
    contentFontSize = Math.min(FONT_MAX, contentFontSize + FONT_STEP);
    applyFontSize();
    showSizeHint('font');
    Bridge.callSafe('save_font_size',contentFontSize);
  }
  function zoomOut() {
    if (imageViewer.active) { imageViewer.zoomOut(); return; }
    contentFontSize = Math.max(FONT_MIN, contentFontSize - FONT_STEP);
    applyFontSize();
    showSizeHint('font');
    Bridge.callSafe('save_font_size',contentFontSize);
  }
  function openFile() {
    if (Bridge.ready()) Bridge.callSafe('open_file_dialog');
  }
  async function closeWindow() {
    if (isDirty) {
      promptBeforeClose();
      return;
    }
    if (Bridge.ready()) Bridge.callSafe('close_window');
  }
  function insertMarkdownSnippet(snippet) {
    const textarea = document.getElementById('textarea');
    if (!isSource) {
      textarea.value = getCurrentMarkdown();
      isSource = true;
      updateView();
    }
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    EditorFeatures.replace(textarea,start,end,snippet,[start+snippet.length,start+snippet.length]);
    setDirty(true);
    syncHighlight();
    pushContentToPython(true);
    // Programmatic value assignment fires no input event, so dismiss the
    // empty-document welcome overlay explicitly (e.g. after ⌘⇧V paste).
    updateEmptyState();
  }
  async function handleDrop(e) {
    e.preventDefault();
    for(const file of Array.from(e.dataTransfer.files||[])){
      try{
        if(/\.(md|markdown|mdown|mkd|mkdown|txt)$/i.test(file.name)){
          if(!file.path){showStatus(t('No file path provided. Use the Open File menu.','浏览器未提供文件路径，请使用打开文件菜单'),true);continue;}
          const result=await Bridge.call('open_linked_document',file.path,'',false);if(!result.success)showStatus(t('Could not open dropped document','无法打开拖入的文档'),true);
        }else if(file.type.startsWith('image/'))await EditorFeatures.image(file);
      }catch(error){showStatus(t('Drop failed','拖入文件失败'),true);}
    }
  }
  // ── Paste as Markdown ──
  // The pasteboard carries several flavors of the same copy at once; we pick
  // the best one (text/markdown > HTML > plain text) and convert HTML to
  // Markdown via turndown. Images are unsupported in v1 (dropped) and
  // Office/Word HTML is not optimized for, so messy sources get a warning.
  // Behavior by mode:
  //   source  : Cmd+V stays native plain-text paste; if the clipboard is
  //             rich, a bubble reminds the user to press Cmd+Shift+V.
  //   preview : Cmd+V / Cmd+Shift+V / menu all convert to Markdown and insert
  //             into the source, then re-render.

var {
  normalizeWhitespace, showPasteHint, showPastedAsMarkdownHint, readClipboardBest, stripHtmlToText, 
  hasMarkdownSyntax, elementHasMarkdownStyle, htmlHasMarkdownConvertibleFormatting, shouldShowSourcePasteHint, 
  unwrapElement, normalizePastedHtml, checkPasteQuality, showPasteQualityWarning, blockifyForInsert, 
  insertMdAtSourceCaret, mapRenderedCaretToSourceOffset, estimateSourceOffsetByBlockOrder, 
  findNthOccurrenceSourceOffset, firstMeaningfulLine, placeCaretNearRenderedText, pasteMdIntoRendered, 
  compactRenderedHtml, restoreRenderedSelection, pasteAsMarkdown,
} = MarkdownPaste.create({
  document,
  window,
  DOMParser,
  NodeFilter,
  setTimeout,
  clearTimeout,
  t: (...args) => t(...args),
  setModal: (...args) => setModal(...args),
  showStatus: (...args) => showStatus(...args),
  ensureTurndown: (...args) => ensureTurndown(...args),
  insertMarkdownSnippet: (...args) => insertMarkdownSnippet(...args),
  sanitizeHtmlString: (...args) => sanitizeHtmlString(...args),
  escHtml: (...args) => escHtml(...args),
  balanceTableColumns: (...args) => balanceTableColumns(...args),
  rewriteRelativeImages: (...args) => rewriteRelativeImages(...args),
  markRenderedContentEdited: (...args) => markRenderedContentEdited(...args),
  state: {
    get isSource() { return isSource; },
    set isSource(value) { isSource = value; },
    get closing() { return closing; },
    set closing(value) { closing = value; },
    get editHintTimer() { return editHintTimer; },
    set editHintTimer(value) { editHintTimer = value; },
    get sizeHintTimer() { return sizeHintTimer; },
    set sizeHintTimer(value) { sizeHintTimer = value; },
  },
  get Bridge() { return Bridge; },
  get turndownService() { return turndownService; },
  get MarkdownPipeline() { return MarkdownPipeline; }
});
  let outputBusy = false;

var {
  currentDocTitle, buildHtml, buildDocx, exportAs, exportAsWrite, printDocument, copyAsRichText, 
  copyAsMarkdown,
} = DocumentOutput.create({
  document,
  window,
  FileReader,
  t: (...args) => t(...args),
  showStatus: (...args) => showStatus(...args),
  documentLanguage: (...args) => documentLanguage(...args),
  getCurrentMarkdown: (...args) => getCurrentMarkdown(...args),
  escHtml: (...args) => escHtml(...args),
  ensureTurndown: (...args) => ensureTurndown(...args),
  ensureLib: (...args) => ensureLib(...args),
  toPlainText: (...args) => toPlainText(...args),
  buildDocxFromMarkdown: (...args) => buildDocxFromMarkdown(...args),
  buildRichText: (...args) => buildRichText(...args),
  copyTextToClipboard: (...args) => copyTextToClipboard(...args),
  state: {
    get filePath() { return filePath; },
    set filePath(value) { filePath = value; },
    get outputBusy() { return outputBusy; },
    set outputBusy(value) { outputBusy = value; },
    get closing() { return closing; },
    set closing(value) { closing = value; },
    get isSource() { return isSource; },
    set isSource(value) { isSource = value; },
  },
  get Bridge() { return typeof Bridge === 'undefined' ? undefined : Bridge; },
  get MathRenderer() { return typeof MathRenderer === 'undefined' ? undefined : MathRenderer; },
  get MarkdownPipeline() { return typeof MarkdownPipeline === 'undefined' ? undefined : MarkdownPipeline; },
  get OutputPrep() { return typeof OutputPrep === 'undefined' ? undefined : OutputPrep; },
  get documentSession() { return typeof documentSession === 'undefined' ? undefined : documentSession; },
  get turndownService() { return typeof turndownService === 'undefined' ? undefined : turndownService; }
});
  OutputPrep.configure({
    isSource: () => isSource,
    showPreview: showPreviewForCapture,
    restoreSource: restoreSourceMode,
    resetTheme: () => { mermaidSvgCache.clear(); initMermaid(); },
    renderLight: async () => {
      await LazyRender.flush();
      await renderMermaidDiagrams(document.getElementById('content'));
      await MathRenderer.renderMath(document.getElementById('content'), {eager:true});
      const diagrams = [...document.querySelectorAll('.mermaid-diagram[data-source]')];
      if (!diagrams.length) return;
      await ensureMermaid();
      mermaidSvgCache.clear(); initMermaid();
      for (const el of diagrams) {
        const result = await renderSafeMermaid('output-' + Math.random().toString(36).slice(2), el.dataset.source);
        el.innerHTML = sanitizeMermaidSvg(result.svg);
      }
    }
  });

  // Temporarily render the Preview DOM for a capture while staying logically
  // in Source mode; restoreSourceMode() puts the UI back afterwards.
  async function showPreviewForCapture() {
    const content = document.getElementById('content');
    const source = document.getElementById('source');
    const page = document.getElementById('page');
    const textarea = document.getElementById('textarea');
    const md = textarea ? textarea.value : '';
    if (md !== lastRenderedHash) {
      await renderMarkdown(md, content);
    }
    renderedDirty = false;
    content.classList.remove('hidden');
    source.classList.remove('visible');
    page.classList.remove('full-width');
    isSource = false;
    updateEmptyState();
    await new Promise(res => requestAnimationFrame(res));
  }

  function restoreSourceMode() {
    const content = document.getElementById('content');
    const source = document.getElementById('source');
    const page = document.getElementById('page');
    content.classList.add('hidden');
    source.classList.add('visible');
    page.classList.remove('full-width');
    isSource = true;
    updateEmptyState();
    syncPositionToSource();
  }
  document.addEventListener('keydown',event=>{if(event.metaKey&&event.key.toLowerCase()==='c'&&(event.shiftKey||event.altKey)){event.preventDefault();if(event.shiftKey)copyAsRichText();else copyAsMarkdown();}});

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

  let modalPreviousFocus = null;
  function setModal(title, bodyHtml, actionsHtml) {
    imageViewer.close();
    if (!document.getElementById('modalOverlay').classList.contains('visible')) modalPreviousFocus = document.activeElement;
    const header = document.getElementById('modalHeader');
    const body = document.getElementById('modalBody');
    const actions = document.getElementById('modalActions');
    if (header) header.textContent = title;
    if (body) { body.dataset.version=String(Number(body.dataset.version||0)+1);body.innerHTML = bodyHtml; }
    if (actions) actions.innerHTML = actionsHtml || '<button class="modal-close">' + t('Close', '关闭') + '</button>';
    document.getElementById('modalOverlay').classList.add('visible');
    const firstControl = document.querySelector('#modalOverlay button, #modalOverlay a[href], #modalOverlay input, #modalOverlay select, #modalOverlay textarea');
    if (firstControl) firstControl.focus();
  }

  function closeModal() {
    document.getElementById('modalOverlay').classList.remove('visible');
    closePromptVisible = false;
    if (modalPreviousFocus && modalPreviousFocus.isConnected) modalPreviousFocus.focus();
  }
  document.getElementById('updateBubble').addEventListener('click',event=>{if(!event.target.closest('.update-bubble-close'))installUpdate();});
  document.querySelector('.update-bubble-body').setAttribute('role','button');
  document.querySelector('.update-bubble-body').tabIndex=0;
  document.querySelector('.update-bubble-body').addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();installUpdate();}else if(event.key==='Escape'){dismissUpdateBubble(event);document.getElementById(isSource?'textarea':'content').focus();}});
  document.querySelector('.update-bubble-close').addEventListener('click',event=>dismissUpdateBubble(event));
  document.getElementById('content').addEventListener('click',event=>{const button=event.target.closest('.frontmatter-toggle');if(button){event.preventDefault();toggleFrontmatter(button);}});
  document.getElementById('modalOverlay').addEventListener('click',event=>{if(event.target.closest('.modal-close'))closeModal();});
  document.getElementById('modalOverlay').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeModal();
  });
  const imageViewer = createImageViewer({
    root: document.getElementById('imageLightbox'),
    content: document.getElementById('content'),
    enabled: () => !isSource && !closing && !closePromptVisible,
    translate: t,
    cleanSVG: sanitizeMermaidSvg,
    onError: message => showStatus(message, true),
  });
  document.getElementById('content').addEventListener('click', (e) => {
    // Non-editable rendered content (frontmatter, math, Mermaid, protected
    // blocks, ...): show a transient hint pointing the user to the Source view
    // instead of silently doing nothing. Editable complex content such as
    // tables and fenced code blocks reuse the same formatting-safety hint.
    // NOTE: do NOT exclude [contenteditable="true"] here — closest() walks up
    // to #content (which IS contenteditable="true") and would always match,
    // silently disabling the hint. Editable-vs-not is decided by
    // findNonEditableAncestor() below.
    if (!isSource && e.target.closest && e.target.closest('.render-caret-spacer')) {
      placeCaretInRenderSpacer(e.target.closest('.render-caret-spacer'));
      return;
    }
    if (!isSource && !e.target.closest('button, a, input, select, label, [role="button"]')) {
      if (getEditableComplexInteractionTarget(e)) {
        showTableEditHint();
        return;
      }
      const ne = findNonEditableAncestor(e.target);
      if (ne) showEditHint(ne);
    }
  });
  document.getElementById('content').addEventListener('beforeinput', (e) => {
    if (isSource) return;
    if (getEditableComplexInteractionTarget(e)) showTableEditHint();
    // Intercept pastes that arrive through the native Edit-menu path (which
    // does not always fire a DOM paste event) so raw markdown never lands in
    // the rendered view. The in-flight flag collapses this with the paste
    // event handler when both fire for the same Cmd+V.
    if (e.inputType === 'insertFromPaste') {
      e.preventDefault();
      pasteAsMarkdown();
    }
  });
  document.getElementById('content').addEventListener('input', (e) => {
    if (!isSource && getEditableComplexInteractionTarget(e)) showTableEditHint();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeModal();
    // Rendered view: Enter inside a blockquote is taken over (see
    // handleRenderedEnter). WKWebView's native behavior inserts <div>/<p>
    // junk — and on an empty quote line a nested blockquote — which corrupts
    // the markdown round trip (stray "> " blank lines in the source).
    if (!isSource && e.key === 'Enter' && !e.metaKey && !e.ctrlKey && !e.altKey && !e.shiftKey) {
      handleRenderedEnter(e);
    }
    // Rendered view: Backspace/Delete on a block edge should merge adjacent
    // blocks (which is how a blank line between markdown paragraphs is
    // removed). WKWebView/Safari only moves the caret there, so without this
    // the deletion appears to do nothing and the blank line comes back after
    // Cmd+E. Only plain key presses (no Cmd/Ctrl/Alt/Shift) are intercepted;
    // ordinary character deletion inside a block stays native.
    if (!isSource && (e.key === 'Backspace' || e.key === 'Delete') && !e.metaKey && !e.ctrlKey && !e.altKey && !e.shiftKey) {
      handleRenderedBlockEdgeDelete(e);
    }
  });


var {
  isBlankRenderParagraph, lastTextNodeIn, placeCaretInRenderedBlock, markRenderedContentEdited, 
  handleRenderedBlockEdgeDelete, mergeRenderedBlockWithPrevious, mergeRenderedBlockWithNext, 
  handleRenderedEnter, normalizeRenderedHtmlForTurndown,
} = RenderedEditing.create({
  document,
  window,
  Node,
  NodeFilter,
  Range,
  setDirty: (...args) => setDirty(...args),
  schedulePythonSync: (...args) => schedulePythonSync(...args),
  dismissWelcomeOverlay: (...args) => dismissWelcomeOverlay(...args),
  sanitizeHtmlString: (...args) => sanitizeHtmlString(...args),
  state: {
    get renderedDirty() { return renderedDirty; },
    set renderedDirty(value) { renderedDirty = value; },
  },
  get PYTHON_SYNC_DEBOUNCE_MS() { return typeof PYTHON_SYNC_DEBOUNCE_MS === 'undefined' ? undefined : PYTHON_SYNC_DEBOUNCE_MS; }
});
  function escHtml(s) {
    if (!s) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }


var {
  balanceTableColumns, setColumnEdge, clearColumnEdges, getResizeColumnFromEvent, enableTableResize, 
  startColDrag,
} = TableLayout.create({
  document,
  getComputedStyle
});
  async function loadContent(path, content, pageWidth, draftRecovered, zh, meta = {}) {
    imageViewer.close(false);
    clearTimeout(readingTimer);
    clearTimeout(pythonSyncTimer);
    documentSession.reset({ ...meta, draftRecovered: !!draftRecovered });
    closing = false;
    lastPushedHash = content;
    mermaidSvgCache.clear();
    filePath = path;
    ReadingFeatures.reset();
    appSettings={...appSettings,...(meta.settings||{})};
    if(window.formatToolbar)window.formatToolbar.setPinned(!!appSettings.format_bar,false);
    applyReadingFont();
    I18n.configure(meta.i18n||{locale:appSettings.language==='system'?(zh?'zh-Hans':'en'):appSettings.language,messages:{}});
    contentFontSize=meta.fontSize||appSettings.font_size;applyFontSize();
    if(appSettings.language!=='system')zh=appSettings.language.startsWith('zh');
    document.getElementById('textarea').value = content;
    const loadEpoch = documentSession.epoch;
    const loadRevision = documentSession.revision;
    isSource = (!path || path === 'Untitled.md');
    document.getElementById('textarea').readOnly = true;
    document.getElementById('content').setAttribute('contenteditable', 'false');
    document.getElementById('content').setAttribute('aria-busy', 'true');
    if (pageWidth) {
      pageWidthPct = normalizePageWidthPct(pageWidth / BASE_WIDTH * 100);
      applyPageWidth();
    }
    if (zh !== undefined) {
      isZh = zh;
      applyStaticUiLanguage();
    }
    await renderMarkdown(content, document.getElementById('content'));
    if (loadEpoch !== documentSession.epoch) return;
    syncHighlight();
    isDirty = !!draftRecovered || documentSession.revision > loadRevision;
    renderedDirty = !isSource && documentSession.revision > loadRevision;
    document.getElementById('content').setAttribute('aria-busy', 'false');
    if (Bridge.ready()) Bridge.callSafe('set_dirty', isDirty, documentSession.revision, documentSession.id);
    // Opening an EXISTING document (double-click, Cmd+O, Finder, reopen) shows
    // the rendered Preview by default. Only a brand-new blank document (path
    // still 'Untitled.md') starts in Source mode so the user can type right in.
    isSource = (!path || path === 'Untitled.md');
    updateView();
    // A brand-new blank document gets the caret automatically placed in the
    // source area — no click needed. The hint stays until typing begins.
    if (isSource) {
      const ta = document.getElementById('textarea');
      if (ta) {
        ta.focus();
        ta.setSelectionRange(0, 0);
      }
    }
    deletedOnDisk=false;
    if(meta.hash)scrollToHash('#'+meta.hash);else restoreReading(meta.readingPosition);
    if (meta.readError) {
      document.getElementById('textarea').readOnly = true;
      document.getElementById('content').setAttribute('contenteditable', 'false');
      showStatus(t('Could not read the file: ', '无法读取文件：') + meta.readError, true);
    } else {
      document.getElementById('textarea').readOnly = false;
      document.getElementById('content').setAttribute('contenteditable', 'true');
    }
    if (draftRecovered) showDraftRecoveredBanner();
    if (meta.externalConflict) showStatus(t('The original file changed after this draft. Saving will ask how to resolve it.', '原文件在草稿之后发生变化，保存时将询问如何处理。'), true);
    if (Bridge.ready()) Bridge.callSafe('startup_ready', Math.round(performance.now() - _jsT0));
    // Preload turndown.js in background (non-blocking) so it's ready
    // when the user first toggles to source mode.
    Onboarding.initialize();
    // 转换器仅在首次编辑、粘贴或回写时加载。
    if (meta.recoverableDrafts && meta.recoverableDrafts.length && !draftRecovered && isSource) showRecoveryManager(meta.recoverableDrafts);
  }

  function showDraftRecoveredBanner() {
    const banner = document.createElement('div');
    banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:950;background:#fff3cd;border-bottom:1px solid #ffc107;color:#856404;padding:8px 16px;font-size:13px;display:flex;align-items:center;gap:12px;justify-content:center;';
    const msg = t('Unsaved changes from a previous session have been restored.','已恢复上次未保存的修改。');
    const discardText = t('Discard','放弃');
    const dismissText = t('Dismiss','忽略');
    banner.innerHTML = '<span>' + msg + '</span>' +
      '<a href="#" id="draftDiscard" style="color:#856404;font-weight:600;text-decoration:underline;">' + discardText + '</a>' +
      '<a href="#" id="draftDismiss" style="color:#856404;text-decoration:underline;">' + dismissText + '</a>';
    document.body.appendChild(banner);
    const discard = document.getElementById('draftDiscard');
    const dismiss = document.getElementById('draftDismiss');
    const remove = () => { const focused=banner.contains(document.activeElement);if (banner.parentNode) banner.parentNode.removeChild(banner);if(focused)document.getElementById(isSource?'textarea':'content').focus(); };
    banner.setAttribute('role','status');
    banner.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();remove();}});
    discard.addEventListener('click', async (e) => {
      e.preventDefault();
      if (Bridge.ready()) await Bridge.call('discard_draft');
      if (Bridge.ready()) {
        Bridge.call('get_initial_content').then((data) => data.headless ? runHeadlessExport(data) : loadContent(data.path, data.content, data.pageWidth, data.draftRecovered, data.isZh, data));
      }
      remove();
    });
    dismiss.addEventListener('click', (e) => { e.preventDefault(); remove(); });
    setTimeout(remove, STATUS_HIDE_MS);
  }

  let readingTimer=null,deletedOnDisk=false;
  function readingPosition(){const sw=document.querySelector('.scroll-wrap');return {ratio:sw.scrollTop/Math.max(1,sw.scrollHeight-sw.clientHeight),headingId:getActiveTocTarget()||''};}
  function restoreReading(position){if(!position)return;if(position.headingId&&document.getElementById(position.headingId))scrollToHash('#'+position.headingId);else{const sw=document.querySelector('.scroll-wrap');sw.scrollTop=(position.ratio||0)*Math.max(0,sw.scrollHeight-sw.clientHeight);}}
  document.querySelector('.scroll-wrap').addEventListener('scroll',()=>{clearTimeout(readingTimer);if(closing)return;const id=documentSession.id;readingTimer=setTimeout(()=>{if(!closing&&id===documentSession.id)Bridge.callSafe('save_reading_position',readingPosition(),id);},500);},{passive:true});
  let reloadRequest=0;
  async function reloadFromDisk(){
    if(isDirty||closing||outputBusy)return false;
    const request=++reloadRequest;
    const id=documentSession.id,revision=documentSession.revision,position=readingPosition();
    const current=()=>request===reloadRequest&&id===documentSession.id&&revision===documentSession.revision&&!isDirty&&!closing;
    const conflict=()=>showStatus(isZh?'同步冲突：未确认磁盘版本，请重试刷新或另存为。':'Disk sync conflict: retry reload or use Save As.',true);
    try {
      const result=await Bridge.call('reload_from_disk',id,revision);
      if(!current())return false;
      if(!result.success){conflict();return false;}
      document.getElementById('textarea').value=result.content;renderedDirty=false;lastPushedHash=result.content;
      await renderMarkdown(result.content,document.getElementById('content'));
      if(!current())return false;
      const acknowledged=await Bridge.call('ack_reload_from_disk',result.candidateId,id,revision);
      if(!current())return false;
      if(!acknowledged?.success){conflict();return false;}
      syncHighlight();restoreReading(position);showStatus(t('File updated externally','文件已在外部更新'));return true;
    } catch(error) {
      if(current())conflict();
      return false;
    }
  }
  async function handleExternalChange(id,deleted){
    if(id!==documentSession.id||closing)return;
    deletedOnDisk=deleted;
    if(deleted){showStatus(t('File deleted or renamed. Use Save As.','文件已删除或重命名，保存将使用另存为'),true);return;}
    if(isDirty){showStatus(t('Disk file changed. Keep your changes with Save As.','磁盘文件已变化；保留当前修改，请另存为'),true);const choice=await Bridge.call('native_conflict_prompt',filePath);if(choice?.action==='save_as'||choice==='save_as')await saveAsFile();else if(choice?.action==='overwrite')await saveFile(true);return;}
    if(appSettings.auto_reload)await reloadFromDisk();else showStatus(t('File updated externally; automatic reload is off.','文件已在外部更新，自动刷新已关闭'),true);
  }
  function reloadContent() {
    if (Bridge.ready()) {
      Bridge.call('get_initial_content').then((data) => data.headless ? runHeadlessExport(data) : loadContent(data.path, data.content, data.pageWidth, data.draftRecovered, data.isZh, data));
    }
  }

  let _flashModeNext = false;
  async function toggleView() {
    imageViewer.close();
    _flashModeNext = true;
    if (!isSource) {
      // rendered → source: capture cursor, convert, position
      const content = document.getElementById('content');
      const textarea = document.getElementById('textarea');
      if (renderedDirty) {
        // Only round-trip the DOM when the user actually edited the rendered view.
        await ensureTurndown();
        // Normalize WebKit editing junk (empty trailing quote lines, quote
        // <div>s) before converting, so the source stays clean.
        const html = normalizeRenderedHtmlForTurndown(content.innerHTML);
        textarea.value = turndownService ? turndownService.turndown(html) : html;
      }
      // Otherwise the textarea already holds the pristine markdown.
      syncHighlight();
      isSource = true;
      updateView();
      syncPositionToSource();
    } else {
      // source → rendered: re-render if needed, then scroll to TOC position.
      // Capture the active TOC target BEFORE re-rendering: renderMarkdown()
      // → buildToc() rebuilds the TOC and clears the active class. Falls
      // back to deriving the target from the current source position so
      // reverse positioning works even when no TOC entry is highlighted.
      const headingId = getActiveTocTarget() || getSourceActiveHeading();
      const md = document.getElementById('textarea').value;
      if (md !== lastRenderedHash) {
        await renderMarkdown(md, document.getElementById('content'));
      }
      renderedDirty = false;
      isSource = false;
      updateView();
      syncPositionToRendered(headingId);
    }
  }

  function updateView() {
    document.querySelectorAll('#replaceInput,.replace-action').forEach(el=>el.hidden=!isSource);
    const content = document.getElementById('content');
    const source = document.getElementById('source');
    const page = document.getElementById('page');
    page.classList.remove('full-width');
    if (isSource) {
      content.classList.add('hidden');
      source.classList.add('visible');
    } else {
      content.classList.remove('hidden');
      source.classList.remove('visible');
    }
    updateEmptyState();
    if (_flashModeNext) { _flashModeNext = false; showModeIndicator(); }
  }

  let _modeIndicatorTimer = null;
  function showModeIndicator() {
    const el = document.getElementById('modeIndicator');
    if (!el) return;
    el.textContent = isSource ? 'mdSource' : 'mdPreview';
    el.classList.add('visible');
    if (_modeIndicatorTimer) clearTimeout(_modeIndicatorTimer);
    _modeIndicatorTimer = setTimeout(() => { el.classList.remove('visible'); }, 2000);
  }

  function updateEmptyState() {
    const content = document.getElementById('content');
    const textarea = document.getElementById('textarea');
    // The welcome hint shows only in SOURCE mode on a truly empty document
    // (the textarea is the source of truth while in source mode). In Preview
    // mode we never show the hint — only the normally rendered content.
    const isEmpty = isSource && (textarea ? textarea.value.trim() === '' : false);
    if (isEmpty) {
      // Build a non-editable overlay that sits on top of the empty source area.
      // The textarea itself stays empty so the cursor lands at position 0.
      let overlay = document.getElementById('welcomeOverlay');
      if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'welcomeOverlay';
        overlay.className = 'welcome-overlay';
        const tips = t('Drop a .md file here or double-click it to open','拖拽 .md 文件到此处，或双击打开');
        const toggleTip = '<kbd>⌘</kbd><kbd>E</kbd> '+t('Preview','预览');
        const pasteTip = '<kbd>⌘</kbd><kbd>⇧</kbd><kbd>V</kbd> '+t('Paste as Markdown','粘贴为 Markdown');
        const title = t('Start writing','开始书写');
        overlay.innerHTML = '<div class="welcome-icon">&#9998;</div>' +
          '<div class="welcome-title">' + title + '</div>' +
          '<div class="welcome-tip">' + tips + '</div>' +
          '<div class="welcome-tip">' + toggleTip + '</div>' +
          '<div class="welcome-tip">' + pasteTip + '</div>';
        content.parentNode.appendChild(overlay);
        Onboarding.decorate(overlay);
        overlay.addEventListener('click', (event) => {
          if(event.target.closest('button,a'))return;
          // Focus the editor without dismissing the hint — it stays visible
          // until the user actually starts typing (input hides it), so a
          // newly created document always has the caret ready in the source
          // area with the hint still explaining what to do.
          const ta = document.getElementById('textarea');
          if (isSource && ta) {
            ta.focus();
          } else {
            content.focus();
            const range = document.createRange();
            range.selectNodeContents(content);
            range.collapse(true);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
          }
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

  function getCurrentMarkdown() {
    if (isSource) return document.getElementById('textarea').value;
    if (!renderedDirty) return document.getElementById('textarea').value;
    const html = normalizeRenderedHtmlForTurndown(document.getElementById('content').innerHTML);
    if (!turndownService) throw new Error(t('Markdown converter is not ready. Please retry.', 'Markdown 转换器尚未就绪，请重试。'));
    return turndownService.turndown(html);
  }

  function markSaved(markdown, snapshot = documentSession.snapshot(markdown)) {
    if (!documentSession.isCurrent(snapshot)) return false;
    const clean = documentSession.saved(snapshot);
    if (clean) {
      isDirty = false;
      renderedDirty = false;
      document.getElementById('textarea').value = markdown;
      lastPushedHash = markdown;
      documentSession.ackRevision = snapshot.revision;
      syncHighlight();
    } else {
      isDirty = true;
      schedulePythonSync(0);
    }
    if (Bridge.ready()) Bridge.callSafe('set_dirty', !clean, documentSession.revision, documentSession.id);
    return clean;
  }

  function forceCloseWindow(discard = false) {
    closePromptVisible = false;
    if (Bridge.ready()) {
      return Bridge.call('force_close_window', !!discard);
    }
  }

  // Called by Python when the user closes the last document window but is not
  // quitting the app. Instead of terminating, the window becomes a blank Untitled
  // document so the app stays alive and Finder double-click / Dock reopen keep
  // working without a cold start.
  function convertToBlankDocument() {
    filePath = null;
    documentSession.reset();
    closing = false;
    renderJobId += 1;
    clearTimeout(pythonSyncTimer);
    mermaidSvgCache.clear();
    markSaved('');
    document.getElementById('content').innerHTML = '';
    // Reset the outline too, otherwise the previous document's TOC lingers on
    // the blank Untitled window (visible when reopened from the Dock).
    tocHasContent = false;
    tocManualOverride = null;
    const toc = document.getElementById('tocSidebar');
    if (toc) toc.innerHTML = '';
    const toggle = document.getElementById('tocToggle');
    if (toggle) toggle.style.display = 'none';
    setTocVisible(false);
    // Blank documents default to Source mode (with the empty-document hint),
    // matching the default mode of freshly opened documents.
    isSource = true;
    updateView();
    // Put the caret in the source area immediately; the hint disappears only
    // once the user starts typing.
    const ta = document.getElementById('textarea');
    if (ta) {
      ta.focus();
      ta.setSelectionRange(0, 0);
    }
    if (Bridge.ready()) {
      return Bridge.call('reset_to_untitled').then(() => reloadContent());
    }
  }


var {
  promptBeforeClose, showSaveConflictDialog,
} = SaveDialogs.create({
  document,
  t: (...args) => t(...args),
  escHtml: (...args) => escHtml(...args),
  ensureTurndown: (...args) => ensureTurndown(...args),
  pushContentToPython: (...args) => pushContentToPython(...args),
  forceCloseWindow: (...args) => forceCloseWindow(...args),
  saveFile: (...args) => saveFile(...args),
  saveAsFile: (...args) => saveAsFile(...args),
  setModal: (...args) => setModal(...args),
  closeModal: (...args) => closeModal(...args),
  showStatus: (...args) => showStatus(...args),
  state: {
    get isDirty() { return isDirty; },
    set isDirty(value) { isDirty = value; },
    get filePath() { return filePath; },
    set filePath(value) { filePath = value; },
    get closePromptVisible() { return closePromptVisible; },
    set closePromptVisible(value) { closePromptVisible = value; },
  },
  get Bridge() { return typeof Bridge === 'undefined' ? undefined : Bridge; }
});
  async function saveFile(force = false, suppliedMarkdown = null, options = {}) {
    if(deletedOnDisk)return saveAsFile();
    if (!Bridge.ready()) {
      showStatus(t('Save is not ready yet', '保存功能尚未就绪'), true);
      return { saved: false, error: 'not-ready' };
    }
    if (saveInFlight) { await saveInFlight; return saveFile(force, null, options); }
    await ensureTurndown();
    const markdown = suppliedMarkdown !== null ? suppliedMarkdown : getCurrentMarkdown();
    const snapshot = documentSession.snapshot(markdown);
    if (!filePath || filePath === 'Untitled.md') {
      return await saveAsFile(markdown);
    }
    try {
      saveInFlight = Bridge.call('save_file', filePath, markdown, !!force, snapshot.revision, snapshot.id);
      const result = await saveInFlight;
      if (!documentSession.isCurrent(snapshot)) return { saved: false, stale: true };
      if (result.success) {
        const clean = markSaved(markdown, snapshot);
        showStatus(force ? t('Saved current version', '已保存当前版本') : t('Saved', '已保存'));
        return { saved: clean, snapshotSaved: true };
      } else if (result.deleted) {
        deletedOnDisk=true;return await saveAsFile(markdown);
      } else if (result.conflict) {
        showSaveConflictDialog(result.path || filePath, markdown, options);
        return { saved: false, conflict: true };
      } else {
        showStatus(result.error ? t('Save failed: ', '保存失败：') + result.error : t('Save failed', '保存失败'), true);
        return { saved: false, error: result.error || 'save-failed' };
      }
    } catch (err) {
      showStatus(t('Save failed: ', '保存失败：') + (err && err.message ? err.message : err), true);
      return { saved: false, error: err };
    } finally { saveInFlight = null; }
  }

  async function saveAsFile(suppliedMarkdown = null) {
    if (!Bridge.ready()) {
      showStatus(t('Save is not ready yet', '保存功能尚未就绪'), true);
      return { saved: false, error: 'not-ready' };
    }
    await ensureTurndown();
    const identity = documentSession.id;
    try {
      const result = await Bridge.call('save_as_choose', currentDocTitle() + '.md');
      if (result && result.success) {
        if (identity !== documentSession.id) return { saved: false, stale: true };
        const markdown = getCurrentMarkdown();
        const snapshot = documentSession.snapshot(markdown);
        const { path, format } = result;
        if (format === 'md') {
          const saveRes = await Bridge.call('save_file', path, markdown, true, snapshot.revision, snapshot.id);
          if (saveRes && saveRes.success) {
            if (!documentSession.isCurrent(snapshot)) return { saved: false, stale: true };
            filePath = path;
            deletedOnDisk=false;
            const clean = markSaved(markdown, snapshot);
            showStatus(t('Saved', '已保存'));
            return { saved: clean, snapshotSaved: true, path };
          }
          showStatus(t('Save failed: ', '保存失败：') + ((saveRes && saveRes.error) || ''), true);
          return { saved: false, error: (saveRes && saveRes.error) || 'save-failed' };
        }
        // Saved as another format: export only, keep the working file untouched.
        const writeRes = await exportAsWrite(path, format);
        if (writeRes && writeRes.success) {
          showStatus(t('Saved', '已保存'));
          return { saved: false, exported: true, path };
        }
        showStatus(t('Save failed: ', '保存失败：') + ((writeRes && writeRes.error) || ''), true);
        return { saved: false, error: (writeRes && writeRes.error) || 'save-failed' };
      } else if (result && !result.cancelled) {
        showStatus(result.error ? t('Save failed: ', '保存失败：') + result.error : t('Save failed', '保存失败'), true);
        return { saved: false, error: result.error || 'save-failed' };
      }
      return { saved: false, cancelled: true };
    } catch (err) {
      showStatus(t('Save failed: ', '保存失败：') + (err && err.message ? err.message : err), true);
      return { saved: false, error: err };
    }
  }

  let statusTimer = null;
  let editHintTimer = null;
  let sizeHintTimer = null;

var {
  showStatus, showSizeHint, findNonEditableAncestor, getTableInteractionTarget, getCodeBlockInteractionTarget, 
  getEditableComplexInteractionTarget, showEditHint, showTableEditHint, applyStaticUiLanguage,
} = EditorFeedback.create({
  document,
  window,
  setTimeout,
  clearTimeout,
  t: (...args) => t(...args),
  normalizeCodeLanguage: (...args) => normalizeCodeLanguage(...args),
  state: {
    get statusTimer() { return statusTimer; },
    set statusTimer(value) { statusTimer = value; },
    get editHintTimer() { return editHintTimer; },
    set editHintTimer(value) { editHintTimer = value; },
    get sizeHintTimer() { return sizeHintTimer; },
    set sizeHintTimer(value) { sizeHintTimer = value; },
    get pageWidthPct() { return pageWidthPct; },
    set pageWidthPct(value) { pageWidthPct = value; },
    get contentFontSize() { return contentFontSize; },
    set contentFontSize(value) { contentFontSize = value; },
  }
});

var {
  setUpdateBubbleText, setUpdateProgress, showUpdateBubble, showUpdateDownloadProgress, 
  showUpdateDownloadFailed, showManualInstallGuide, dismissUpdateBubble, installUpdate,
} = UpdateFeedback.create({
  document,
  t: (...args) => t(...args),
  showStatus: (...args) => showStatus(...args),
  pushContentToPython: (...args) => pushContentToPython(...args),
  state: {
    get isDirty() { return isDirty; },
    set isDirty(value) { isDirty = value; },
  },
  get Bridge() { return Bridge; }
});

var {
  openFindBar, closeFindBar, getSearchableText, doFind, findInTextarea, scrollToTextareaMatch, 
  clearFindHighlights, findInContentEditable, highlightCurrentMatch, findNext, findPrev, updateFindButtons,
} = DocumentFind.create({
  document,
  window,
  scrollTextareaToLine: (...args) => scrollTextareaToLine(...args),
  findRangeBetween: (...args) => findRangeBetween(...args),
  state: {
    get isSource() { return isSource; },
    set isSource(value) { isSource = value; },
  }
});
  document.getElementById('findInput').addEventListener('input', () => { doFind(); });
  document.getElementById('findInput').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); e.shiftKey ? findPrev() : findNext(); }
    if (e.key === 'Escape') { e.preventDefault(); closeFindBar(); }
  });
  document.getElementById('tocToggle').addEventListener('click', toggleToc);
  document.getElementById('findNext').addEventListener('click', findNext);
  document.getElementById('findPrev').addEventListener('click', findPrev);
  document.getElementById('findClose').addEventListener('click', closeFindBar);

  document.addEventListener('keydown', (e) => {
    const cmd = e.metaKey;
    if (cmd && e.key === 's') { e.preventDefault(); e.shiftKey ? saveAsFile() : saveFile(); }
    if (cmd && e.altKey && e.key === 'o') { e.preventDefault(); toggleToc(); return; }
    if (cmd && e.key === 'o') { e.preventDefault(); openFile(); }
    if (cmd && e.key === 'w') { e.preventDefault(); closeWindow(); }
    if (cmd && e.key === '0') { e.preventDefault(); e.altKey?resetPageWidth():resetFontSize(); }
    // Zoom: ⌘= / ⌘- (View menu). WebKit may not forward ⌘= to JS when the
    // menu item handles it, so this is a JS-level fallback as well.
    if (cmd && e.key === '=') { e.preventDefault(); e.altKey?adjustPageWidth(10):zoomIn(); }
    if (cmd && e.key === '-') { e.preventDefault(); e.altKey?adjustPageWidth(-10):zoomOut(); }
    // Width: ⌘. / ⌘, (moved off ⌘= / ⌘- which are now Zoom).
    if (cmd && e.key === ',') { e.preventDefault(); openSettings(); }
    if (cmd && e.key === 'e') { e.preventDefault(); toggleView(); }
    if (cmd && e.key === 'f') { e.preventDefault(); openFindBar(); }
    if (cmd && e.key === 'g') { e.preventDefault(); e.shiftKey ? findPrev() : findNext(); }
    // Paste as Markdown: normally the native Edit menu item (Cmd+Shift+V)
    // consumes this first; this is a JS-level fallback for before menus are
    // set up or if the menu item is unavailable.
    if (cmd && e.shiftKey && e.key === 'v') { e.preventDefault(); pasteAsMarkdown(); return; }
  });

  function isBlockedHref(href) {
    return !href || !MarkdownPipeline.safeURL(href);
  }

  function isExternalHref(href) {
    return /^[a-z][a-z0-9+.-]*:/i.test(href) || href.startsWith('//');
  }

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
      if (Bridge.ready()) Bridge.callSafe('open_external_link', href);
      return;
    }
    e.preventDefault();
    try {
      const split=href.indexOf('#'),path=decodeURIComponent(split<0?href:href.slice(0,split)),hash=split<0?'':decodeURIComponent(href.slice(split+1));
      if(!filePath||filePath==='Untitled.md'){showStatus(t('Save the document before opening relative links','请先保存文档再打开相对链接'),true);return;}
      const base=new URL('file://'+filePath.split('/').map(encodeURIComponent).join('/'));const absolute=decodeURIComponent(new URL(path.split('/').map(encodeURIComponent).join('/'),base).pathname);
      Bridge.call('open_linked_document',absolute,hash,e.metaKey).then(result=>{if(!result.success&&!result.cancelled)showStatus(result.error==='dirty-document'?t('Save your changes first','请先保存当前修改'):t('Linked file missing or unavailable','找不到链接的文件或无法打开'),true);}).catch(()=>showStatus(t('Could not open link','无法打开链接'),true));
    }catch(error){showStatus(t('Invalid link','链接格式无效'),true);}
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
    imageViewer.close(false);
    closing = true;
    LazyRender.reset();
    clearTimeout(readingTimer);
    clearTimeout(pythonSyncTimer);
    clearTimeout(highlightTimer);
    if (highlightRaf !== null) { cancelAnimationFrame(highlightRaf); highlightRaf = null; }
    clearTimeout(statusTimer);
    clearTimeout(deferredRenderTimer);
    if (keepAliveTimer) { clearInterval(keepAliveTimer); keepAliveTimer = null; }
  }

  let pythonSyncTimer = null;

  async function pushContentToPython(force = false) {
    if (closing || !Bridge.ready()) return false;
    if (!force && !isDirty) return true;
    if (syncInFlight) { await syncInFlight; return pushContentToPython(force); }
    if (renderedDirty) await ensureTurndown();
    const markdown = getCurrentMarkdown();
    const snapshot = documentSession.snapshot(markdown);
    if (!force && markdown === lastPushedHash && snapshot.revision <= documentSession.ackRevision) return true;
    syncInFlight = Promise.resolve(Bridge.call('store_content', markdown, snapshot.revision, snapshot.id));
    try {
      const result = await syncInFlight;
      if (result === false || (result && result.success === false)) throw new Error((result && result.error) || 'Draft sync rejected');
      if (documentSession.isCurrent(snapshot)) {
        lastPushedHash = markdown;
        documentSession.ackRevision = snapshot.revision;
        syncRetryCount = 0;
      }
      return true;
    } catch (error) {
      if (documentSession.isCurrent(snapshot) && !closing) {
        showStatus(t('Draft could not be saved. Keep this window open and retry saving.', '草稿保存失败，请保留窗口并重试保存。'), true);
        if (syncRetryCount++ < 3) schedulePythonSync(Math.min(8000, 500 * 2 ** syncRetryCount));
      }
      return false;
    } finally { syncInFlight = null; }
  }

  function schedulePythonSync(delay = 900) {
    if (closing) return;
    clearTimeout(pythonSyncTimer);
    pythonSyncTimer = setTimeout(() => pushContentToPython(false), delay);
  }

  function setDirty(dirty) {
    if (dirty) documentSession.edit();
    isDirty = !!dirty;
    if (Bridge.ready()) Bridge.callSafe('set_dirty', dirty, documentSession.revision, documentSession.id);
  }

  document.getElementById('content').addEventListener('input', () => { renderedDirty = true; setDirty(true); schedulePythonSync(PYTHON_SYNC_DEBOUNCE_MS); dismissWelcomeOverlay(); });
  document.getElementById('textarea').addEventListener('input', () => { setDirty(true); scheduleHighlightSync(); schedulePythonSync(700); updateEmptyState(); });
  const scrollWrapEl = document.querySelector('.scroll-wrap');
  if (scrollWrapEl) scrollWrapEl.addEventListener('scroll', scheduleTocSync, { passive: true });
  const sourceTextarea = document.getElementById('textarea');
  sourceTextarea.addEventListener('click', scheduleSourceTocHighlight);
  sourceTextarea.addEventListener('keyup', scheduleSourceTocHighlight);
  sourceTextarea.addEventListener('input', scheduleSourceTocHighlight);
  document.addEventListener('dragover', (e) => e.preventDefault());
  EditorFeatures.install();
  document.addEventListener('drop', handleDrop);
  // Paste interception:
  //   source  : keep native plain-text paste; if the clipboard is rich, show
  //             the Cmd+Shift+V reminder bubble.
  //   preview : always convert to Markdown (Cmd+V / menu Paste).
  // Only intercept when the editor itself is the target (not the find input).
  document.addEventListener('paste', (e) => {
    if (closing) return;
    const ta = document.getElementById('textarea');
    const content = document.getElementById('content');
    const target = e.target;
    const inSourceEditor = ta && target === ta;
    const inPreviewEditor = content && target && target.nodeType === 1 && content.contains(target);
    if (!inSourceEditor && !inPreviewEditor) return;
    if (isSource) {
      if (Bridge.ready()) {
        Bridge.callSafe('read_clipboard').then(function (clip) {
          if (shouldShowSourcePasteHint(clip)) showPasteHint();
        }).catch(function () {});
      }
    } else {
      e.preventDefault();
      pasteAsMarkdown();
    }
  });
  window.addEventListener('resize', handleTocResize);
  keepAliveTimer = setInterval(() => { if (!closing && isSource) pushContentToPython(false); }, 5000);

  window.addEventListener('pywebviewready', () => {
    Bridge.call('get_initial_content').then((data) => data.headless ? runHeadlessExport(data) : loadContent(data.path, data.content, data.pageWidth, data.draftRecovered, data.isZh, data));
  });

  function showRecoveryManager(drafts) {
    const body = '<p>' + t('Unsaved documents are available to recover.', '发现可恢复的未保存文档。') + '</p>' +
      drafts.map((draft, index) => '<button class="modal-button secondary recover-draft" data-index="' + index + '">' + escHtml(draft.preview || t('Untitled document', '未命名文档')) + '</button>').join('');
    setModal(t('Recover documents', '恢复文档'), body);
    document.querySelectorAll('.recover-draft').forEach(button => button.addEventListener('click', async () => {
      const result = await Bridge.call('recover_untitled', drafts[Number(button.dataset.index)].documentId);
      if (!result.success) return showStatus(result.error, true);
      closeModal();
      const data = result.data;
      await loadContent(data.path, data.content, data.pageWidth, true, data.isZh, data);
    }));
  }

  async function confirmQuitDocument() {
    try {
      await ensureTurndown();
      if (!isDirty) return Bridge.call('finish_quit_document', true, documentSession.id);
      const flushed = await pushContentToPython(true);
      const result = await Bridge.call('native_save_prompt');
      if (!result || result.action === 'cancel') return Bridge.call('finish_quit_document', false, documentSession.id);
      if (result.action === 'delete') {
        await Bridge.call('discard_draft');
        isDirty = false;
      } else if (result.action === 'save') {
        if (result.path) filePath = result.path;
        const saved = await saveFile();
        if (!saved.saved || isDirty) return Bridge.call('finish_quit_document', false, documentSession.id);
      } else return Bridge.call('finish_quit_document', false, documentSession.id);
      return Bridge.call('finish_quit_document', !isDirty, documentSession.id);
    } catch (error) {
      showStatus(error.message, true);
      return Bridge.call('finish_quit_document', false, documentSession.id);
    }
  }

  function setQuitFrozen(frozen) {
    document.getElementById('textarea').readOnly = !!frozen;
    document.getElementById('content').setAttribute('contenteditable', frozen ? 'false' : 'true');
  }

  document.getElementById('modalOverlay').addEventListener('keydown', (event) => {
    if (event.key === 'Escape') { event.preventDefault(); closeModal(); return; }
    if (event.key !== 'Tab') return;
    const controls = [...event.currentTarget.querySelectorAll('button, a[href], input, select, textarea')].filter(node => !node.disabled);
    if (!controls.length) return;
    const first = controls[0], last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });


// "New from Clipboard": paste into the blank document, then show it rendered
// (a blank document starts in source mode, but the goal here is reading).
window.pasteClipboardAndRead = async function () {
  await Promise.resolve(pasteAsMarkdown());
  await new Promise(resolve => setTimeout(resolve, 150));
  if (isSource && getCurrentMarkdown().trim()) await toggleView();
};
