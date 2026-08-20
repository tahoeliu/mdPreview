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
  const FIRST_SCREEN_MARKDOWN_CHARS = 18000;
  // Centralized tuning knobs (kept together so they are easy to find/adjust).
  const TOC_AUTO_HIDE_WIDTH = 800;   // below this window width the TOC auto-hides
  const FONT_MIN = 12;
  const FONT_MAX = 24;
  const FONT_STEP = 1;
  const PYTHON_SYNC_DEBOUNCE_MS = 1800;  // debounce for pushing content to Python
  const STATUS_HIDE_MS = 8000;           // error status auto-hide delay

  // Bilingual helper: returns the Chinese string when the app UI is in
  // Chinese (isZh is set from the backend's locale detection), English otherwise.
  function t(en, zh) {
    return isZh ? zh : en;
  }

  if (typeof marked !== 'undefined') marked.setOptions({ breaks: true, gfm: true });

  const _jsT0 = performance.now();  // cold-start profiling

  // These are loaded on-demand to speed up cold start by ~300-500ms.
  let _turndownLoaded = false;
  let _mermaidLoaded = false;
  let _mermaidLoadingPromise = null;

  function ensureLib(src, globalName) {
    // Load a vendored library on demand; resolves when its global is present.
    if (window[globalName] !== undefined) return Promise.resolve();
    return _loadScript(src).then(() => {
      if (window[globalName] === undefined) {
        throw new Error(globalName + ' failed to load');
      }
    });
  }

  function _loadScript(src) {
    return new Promise((resolve, reject) => {
      const existing = document.querySelector('script[src="' + src + '"]');
      if (existing) { resolve(); return; }
      const s = document.createElement('script');
      s.src = src;
      s.onload = () => resolve();
      s.onerror = () => reject(new Error('Failed to load ' + src));
      document.head.appendChild(s);
    });
  }

  function _initTurndown() {
    if (turndownService || typeof TurndownService === 'undefined') return;
    turndownService = new TurndownService({ headingStyle: 'atx', codeBlockStyle: 'fenced', bulletListMarker: '-', emDelimiter: '*', strongDelimiter: '**' });
    turndownService.addRule('frontmatter', {
      filter: function (node) {
        return node.classList && node.classList.contains('frontmatter');
      },
      replacement: function (content, node) {
        const raw = node.getAttribute('data-raw');
        return (raw || node.textContent) + '\n\n';
      }
    });
    turndownService.addRule('mermaid', {
      filter: function (node) {
        return node.classList && node.classList.contains('mermaid-diagram');
      },
      replacement: function (content, node) {
        const source = node.getAttribute('data-source') || '';
        return source ? '```mermaid\n' + source.trim() + '\n```' : '';
      }
    });
    turndownService.addRule('listItem', {
      filter: 'li',
      replacement: function (content, node, options) {
        // Same shape as the bundled turndown listItem rule, but with a single
        // space after the marker ("- item" / "1. item") instead of the
        // hardcoded 3-space padding, so pasted lists match the app's style.
        content = content
          .replace(/^\n+/, '')
          .replace(/\n+$/, '\n')
          .replace(/\n/gm, '\n    ');
        var parent = node.parentNode;
        var prefix;
        if (parent && parent.nodeName === 'OL') {
          var start = parent.getAttribute('start');
          var index = Array.prototype.indexOf.call(parent.children, node);
          prefix = (start ? Number(start) + index : index + 1) + '. ';
        } else {
          prefix = options.bulletListMarker + ' ';
        }
        return prefix + content + (node.nextSibling && !/\n$/.test(content) ? '\n' : '');
      }
    });
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
        function escPipe(s) {
          return (s || '').trim().replace(/\|/g, '\\|').replace(/\n/g, ' ');
        }
        var lines = [];
        var headerCells = [];
        for (var c = 0; c < colCount; c++) {
          headerCells.push(escPipe((rows[0].cells[c] || {}).textContent || ''));
        }
        lines.push('| ' + headerCells.join(' | ') + ' |');
        var sepCells = [];
        for (var c2 = 0; c2 < colCount; c2++) {
          var cell = rows[0].cells[c2];
          var align = cell ? (cell.getAttribute('align') || cell.style.textAlign || '') : '';
          if (align === 'center') sepCells.push(':---:');
          else if (align === 'right') sepCells.push('---:');
          else sepCells.push('---');
        }
        lines.push('| ' + sepCells.join(' | ') + ' |');
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

  function ensureTurndown() {
    if (_turndownLoaded) return Promise.resolve();
    if (typeof TurndownService !== 'undefined') { _initTurndown(); _turndownLoaded = true; return Promise.resolve(); }
    return _loadScript('turndown.js').then(() => { _initTurndown(); _turndownLoaded = true; });
  }

  function getMermaidTheme() {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'default';
  }
  function initMermaid() {
    if (typeof mermaid === 'undefined') return;
    mermaid.initialize({
      startOnLoad: false,
      theme: getMermaidTheme(),
      securityLevel: 'strict',
      flowchart: { useMaxWidth: true, htmlLabels: true },
      sequence: { useMaxWidth: true },
    });
  }
  function ensureMermaid() {
    if (_mermaidLoaded) return Promise.resolve();
    if (_mermaidLoadingPromise) return _mermaidLoadingPromise;
    if (typeof mermaid !== 'undefined') { initMermaid(); _mermaidLoaded = true; return Promise.resolve(); }
    _mermaidLoadingPromise = _loadScript('mermaid.min.js').then(() => { initMermaid(); _mermaidLoaded = true; _mermaidLoadingPromise = null; });
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

  function sanitizeMermaidSvg(svg) {
    // Belt-and-braces: even with mermaid's strict security level, strip any
    // script elements and event/javascript: attributes before inserting SVG.
    try {
      const doc = new DOMParser().parseFromString(svg, 'image/svg+xml');
      const root = doc.documentElement;
      const els = Array.from(root.getElementsByTagName('*'));
      for (const el of els) {
        if (el.tagName.toLowerCase() === 'script') {
          el.remove();
          continue;
        }
        for (const attr of Array.from(el.attributes)) {
          const name = attr.name.toLowerCase();
          const value = (attr.value || '').trim().toLowerCase();
          if (name.startsWith('on') ||
              ((name === 'href' || name === 'xlink:href') && value.startsWith('javascript:'))) {
            el.removeAttribute(attr.name);
          }
        }
      }
      return new XMLSerializer().serializeToString(root);
    } catch (e) {
      return svg;
    }
  }

  async function renderMermaidDiagrams(root) {
    const codeBlocks = root.querySelectorAll('code.language-mermaid');
    if (codeBlocks.length === 0) return;
    await ensureMermaid();
    if (typeof mermaid === 'undefined') return;
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
        wrapper.innerHTML = sanitizeMermaidSvg(svg);
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

  function splitMarkdownForFirstScreen(markdown) {
    if (!markdown || markdown.length <= FIRST_SCREEN_MARKDOWN_CHARS) {
      return { first: markdown || '', rest: '', staged: false };
    }
    let cut = markdown.lastIndexOf('\n\n', FIRST_SCREEN_MARKDOWN_CHARS);
    if (cut < FIRST_SCREEN_MARKDOWN_CHARS * 0.55) cut = markdown.lastIndexOf('\n#', FIRST_SCREEN_MARKDOWN_CHARS);
    if (cut < FIRST_SCREEN_MARKDOWN_CHARS * 0.55) cut = markdown.lastIndexOf('\n', FIRST_SCREEN_MARKDOWN_CHARS);
    if (cut < FIRST_SCREEN_MARKDOWN_CHARS * 0.55) cut = FIRST_SCREEN_MARKDOWN_CHARS;
    return { first: markdown.slice(0, cut), rest: markdown.slice(cut), staged: true };
  }

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
  function sanitizeHtmlString(html) {
    const blockedTags = 'script|iframe|object|embed|link|meta|base|style|svg|math|video|audio|source|track|frame|frameset|applet|param|noscript|form';
    const tagRe = new RegExp('<(?:' + blockedTags + ')\\b[^>]*>[\\s\\S]*?<\\/\\s*(?:' + blockedTags + ')\\s*>|<(?:' + blockedTags + ')\\b[^>]*\\/?>', 'gi');
    const onAttrRe = /\s+on[a-z]+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi;
    const dangerousUrl = '(?:javascript:|vbscript:|data:(?!image\\/)|file:)';
    const hrefRe = new RegExp('(href|poster)\\s*=\\s*(?:"|\')?\\s*' + dangerousUrl + '[^\\s"\'>]*', 'gi');
    const srcRe = new RegExp('\\ssrc\\s*=\\s*(?:"|\')?\\s*' + dangerousUrl + '[^\\s"\'>]*', 'gi');
    // style="background:url(javascript:...)" is inert in modern browsers but we
    // still strip it for defense in depth.
    const styleRe = /\sstyle\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi;
    return (html || '')
      .replace(tagRe, '')
      .replace(onAttrRe, '')
      .replace(hrefRe, '$1="#"')
      .replace(srcRe, '')
      .replace(styleRe, (m) => /url\s*\(\s*['"]?\s*(?:javascript|vbscript|data:text\/html)/i.test(m) ? '' : m);
  }

  function sanitizeRenderedDOM(root) {
    try {
      root.querySelectorAll('script,iframe,object,embed,link,meta,base,style,svg,math,video,audio,source,track,frame,frameset,applet,param,noscript,form').forEach((el) => el.remove());
      root.querySelectorAll('*').forEach((el) => {
        for (const attr of Array.from(el.attributes || [])) {
          const name = attr.name.toLowerCase();
          if (name.startsWith('on')) { el.removeAttribute(attr.name); continue; }
          if (name === 'href' || name === 'src' || name === 'xlink:href' || name === 'poster') {
            if (/^\s*(?:javascript:|vbscript:|data:(?!image\/)|file:)/i.test((attr.value || '').trim())) {
              el.removeAttribute(attr.name);
            }
          }
        }
      });
    } catch (e) {
      // Sanitizer must never break rendering.
    }
  }

  const CODE_HIGHLIGHT_MAX_CHARS = 350000;
  const CODE_LANGUAGE_ALIASES = {
    json: 'json',
    js: 'javascript', javascript: 'javascript', jsx: 'javascript',
    ts: 'typescript', typescript: 'typescript', tsx: 'typescript',
    py: 'python', python: 'python',
    bash: 'shell', sh: 'shell', shell: 'shell', zsh: 'shell', console: 'shell', terminal: 'shell',
    yaml: 'yaml', yml: 'yaml',
    html: 'html', xml: 'html', svg: 'html',
    css: 'css', scss: 'css', less: 'css',
    sql: 'sql'
  };
  const JS_TS_KEYWORDS = new Set('as async await break case catch class const constructor continue debugger default delete do else export extends finally for from function get if import in instanceof let new of return set static super switch this throw try typeof var void while with yield interface type enum implements private protected public readonly abstract declare namespace module satisfies'.split(' '));
  const PY_KEYWORDS = new Set('and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield'.split(' '));
  const SHELL_COMMANDS = new Set('alias awk brew cat cd chmod chown cp curl docker echo env export find git grep head jq kill less ls make mkdir mv npm npx open pnpm python python3 rm rsync sed source ssh sudo tail tar test touch unzip yarn zip'.split(' '));
  const SQL_KEYWORDS = new Set('add alter and as asc between by case column create database delete desc distinct drop else exists from group having in inner insert into is join left like limit not null on or order outer primary right select set table then union update values view when where'.split(' '));
  const CSS_AT_RULES = new Set('charset container font-face import keyframes layer media namespace page property scope supports'.split(' '));

  function spanTok(kind, value) {
    return '<span class="tok tok-' + kind + '">' + escHtml(value) + '</span>';
  }

  function normalizeCodeLanguage(code) {
    const classes = Array.from(code.classList || []);
    for (const cls of classes) {
      const match = cls.match(/^(?:language|lang)-(.+)$/i);
      if (match) {
        const raw = match[1].toLowerCase().replace(/[^a-z0-9+#.-]/g, '');
        return CODE_LANGUAGE_ALIASES[raw] || raw;
      }
    }
    return '';
  }

  function readQuoted(text, start) {
    const quote = text[start];
    let i = start + 1;
    while (i < text.length) {
      if (text[i] === '\\') { i += 2; continue; }
      if (text[i] === quote) { i++; break; }
      i++;
    }
    return i;
  }

  function highlightJsonCode(text) {
    let out = '';
    let i = 0;
    while (i < text.length) {
      const ch = text[i];
      if (ch === '"') {
        const end = readQuoted(text, i);
        const raw = text.slice(i, end);
        let j = end;
        while (j < text.length && /\s/.test(text[j])) j++;
        out += spanTok(text[j] === ':' ? 'key' : 'string', raw);
        i = end;
        continue;
      }
      const num = text.slice(i).match(/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/);
      if (num) { out += spanTok('number', num[0]); i += num[0].length; continue; }
      const lit = text.slice(i).match(/^(?:true|false|null)\b/);
      if (lit) { out += spanTok(lit[0] === 'null' ? 'null' : 'literal', lit[0]); i += lit[0].length; continue; }
      if (/^[{}[\],:]$/.test(ch)) out += spanTok('punct', ch);
      else out += escHtml(ch);
      i++;
    }
    return out;
  }

  function highlightCStyleCode(text, keywords, options = {}) {
    let out = '';
    let i = 0;
    while (i < text.length) {
      const ch = text[i];
      const next = text[i + 1];
      if (ch === '/' && next === '/') {
        const end = text.indexOf('\n', i);
        const stop = end < 0 ? text.length : end;
        out += spanTok('comment', text.slice(i, stop));
        i = stop;
        continue;
      }
      if (ch === '/' && next === '*') {
        const end = text.indexOf('*/', i + 2);
        const stop = end < 0 ? text.length : end + 2;
        out += spanTok('comment', text.slice(i, stop));
        i = stop;
        continue;
      }
      if (ch === '"' || ch === "'" || ch === '`') {
        const end = readQuoted(text, i);
        out += spanTok('string', text.slice(i, end));
        i = end;
        continue;
      }
      const num = text.slice(i).match(/^(?:0x[\da-fA-F]+|\d+(?:\.\d+)?)(?:[eE][+-]?\d+)?\b/);
      if (num) { out += spanTok('number', num[0]); i += num[0].length; continue; }
      const word = text.slice(i).match(/^[A-Za-z_$][\w$]*/);
      if (word) {
        const value = word[0];
        if (keywords.has(value)) out += spanTok('keyword', value);
        else if (/^(?:true|false|null|undefined|NaN|Infinity)$/.test(value)) out += spanTok(value === 'null' ? 'null' : 'literal', value);
        else if (options.typescript && /^[A-Z][\w$]*$/.test(value)) out += spanTok('type', value);
        else out += escHtml(value);
        i += value.length;
        continue;
      }
      if (/^[{}[\]().,;:?]$/.test(ch)) out += spanTok('punct', ch);
      else out += escHtml(ch);
      i++;
    }
    return out;
  }

  function highlightPythonCode(text) {
    let out = '';
    let i = 0;
    while (i < text.length) {
      const ch = text[i];
      if (ch === '#') {
        const end = text.indexOf('\n', i);
        const stop = end < 0 ? text.length : end;
        out += spanTok('comment', text.slice(i, stop));
        i = stop;
        continue;
      }
      if ((ch === '"' || ch === "'") && text.slice(i, i + 3) === ch + ch + ch) {
        const end = text.indexOf(ch + ch + ch, i + 3);
        const stop = end < 0 ? text.length : end + 3;
        out += spanTok('string', text.slice(i, stop));
        i = stop;
        continue;
      }
      if (ch === '"' || ch === "'") {
        const end = readQuoted(text, i);
        out += spanTok('string', text.slice(i, end));
        i = end;
        continue;
      }
      if (ch === '@') {
        const deco = text.slice(i).match(/^@[A-Za-z_][\w.]*/);
        if (deco) { out += spanTok('decorator', deco[0]); i += deco[0].length; continue; }
      }
      const num = text.slice(i).match(/^(?:0x[\da-fA-F]+|\d+(?:\.\d+)?)(?:[eE][+-]?\d+)?\b/);
      if (num) { out += spanTok('number', num[0]); i += num[0].length; continue; }
      const word = text.slice(i).match(/^[A-Za-z_][\w]*/);
      if (word) {
        const value = word[0];
        if (PY_KEYWORDS.has(value)) out += spanTok('keyword', value);
        else if (/^(?:True|False|None)$/.test(value)) out += spanTok(value === 'None' ? 'null' : 'literal', value);
        else out += escHtml(value);
        i += value.length;
        continue;
      }
      if (/^[{}[\]().,:]$/.test(ch)) out += spanTok('punct', ch);
      else out += escHtml(ch);
      i++;
    }
    return out;
  }

  function highlightShellCode(text) {
    let out = '';
    let i = 0;
    let atCommandStart = true;
    while (i < text.length) {
      const ch = text[i];
      if (ch === '\n') { out += '\n'; i++; atCommandStart = true; continue; }
      if (ch === '#') {
        const end = text.indexOf('\n', i);
        const stop = end < 0 ? text.length : end;
        out += spanTok('comment', text.slice(i, stop));
        i = stop;
        continue;
      }
      if ((ch === '$' || ch === '#') && atCommandStart) { out += spanTok('prompt', ch); i++; continue; }
      if (ch === '"' || ch === "'") {
        const end = readQuoted(text, i);
        out += spanTok('string', text.slice(i, end));
        i = end;
        atCommandStart = false;
        continue;
      }
      const variable = text.slice(i).match(/^\$\{?[A-Za-z_][\w]*\}?/);
      if (variable) { out += spanTok('variable', variable[0]); i += variable[0].length; atCommandStart = false; continue; }
      const flag = text.slice(i).match(/^--?[A-Za-z0-9][\w-]*/);
      if (flag) { out += spanTok('flag', flag[0]); i += flag[0].length; atCommandStart = false; continue; }
      const word = text.slice(i).match(/^[A-Za-z_][\w.-]*/);
      if (word) {
        const value = word[0];
        out += SHELL_COMMANDS.has(value) ? spanTok('command', value) : escHtml(value);
        i += value.length;
        atCommandStart = false;
        continue;
      }
      out += escHtml(ch);
      if (!/\s/.test(ch)) atCommandStart = false;
      i++;
    }
    return out;
  }

  function highlightYamlValue(value) {
    const leading = (value.match(/^\s*/) || [''])[0];
    const body = value.slice(leading.length);
    if (/^#/.test(body)) return escHtml(leading) + spanTok('comment', body);
    if (/^(?:"(?:\\.|[^"])*"|'(?:\\.|[^'])*')/.test(body)) {
      const end = readQuoted(body, 0);
      return escHtml(leading) + spanTok('string', body.slice(0, end)) + escHtml(body.slice(end));
    }
    const literal = body.match(/^(?:true|false|null|yes|no|on|off)\b/i);
    if (literal) return escHtml(leading) + spanTok('literal', literal[0]) + escHtml(body.slice(literal[0].length));
    const number = body.match(/^-?\d+(?:\.\d+)?\b/);
    if (number) return escHtml(leading) + spanTok('number', number[0]) + escHtml(body.slice(number[0].length));
    return escHtml(value);
  }

  function highlightYamlCode(text) {
    return text.split('\n').map((line) => {
      const commentOnly = line.match(/^(\s*)(#.*)$/);
      if (commentOnly) return escHtml(commentOnly[1]) + spanTok('comment', commentOnly[2]);
      const kv = line.match(/^(\s*)(-\s+)?([A-Za-z0-9_.-]+)(\s*:)(.*)$/);
      if (kv) {
        return escHtml(kv[1]) + escHtml(kv[2] || '') + spanTok('key', kv[3]) + spanTok('punct', kv[4]) + highlightYamlValue(kv[5]);
      }
      return escHtml(line);
    }).join('\n');
  }

  function highlightHtmlTag(tag) {
    let out = '';
    let i = 0;
    if (tag.startsWith('</')) { out += spanTok('punct', '</'); i = 2; }
    else if (tag.startsWith('<')) { out += spanTok('punct', '<'); i = 1; }
    while (i < tag.length) {
      if (tag[i] === '>') { out += spanTok('punct', '>'); i++; continue; }
      if (tag[i] === '/' && tag[i + 1] === '>') { out += spanTok('punct', '/>'); i += 2; continue; }
      if (/\s/.test(tag[i])) { out += escHtml(tag[i]); i++; continue; }
      if (tag[i] === '=') { out += spanTok('punct', '='); i++; continue; }
      if (tag[i] === '"' || tag[i] === "'") {
        const end = readQuoted(tag, i);
        out += spanTok('string', tag.slice(i, end));
        i = end;
        continue;
      }
      const name = tag.slice(i).match(/^[A-Za-z_:][-\w:.]*/);
      if (name) {
        const prev = tag.slice(0, i).trim();
        const next = tag.slice(i + name[0].length).match(/^\s*=/);
        out += (!prev || prev === '<' || prev === '</') ? spanTok('tag', name[0]) : (next ? spanTok('attr', name[0]) : escHtml(name[0]));
        i += name[0].length;
        continue;
      }
      out += escHtml(tag[i]);
      i++;
    }
    return out;
  }

  function highlightHtmlCode(text) {
    let out = '';
    let i = 0;
    while (i < text.length) {
      if (text.startsWith('<!--', i)) {
        const end = text.indexOf('-->', i + 4);
        const stop = end < 0 ? text.length : end + 3;
        out += spanTok('comment', text.slice(i, stop));
        i = stop;
        continue;
      }
      if (text[i] === '<') {
        const end = text.indexOf('>', i + 1);
        if (end < 0) { out += escHtml(text.slice(i)); break; }
        out += highlightHtmlTag(text.slice(i, end + 1));
        i = end + 1;
        continue;
      }
      out += escHtml(text[i]);
      i++;
    }
    return out;
  }

  function highlightCssCode(text) {
    let out = '';
    let i = 0;
    while (i < text.length) {
      if (text[i] === '/' && text[i + 1] === '*') {
        const end = text.indexOf('*/', i + 2);
        const stop = end < 0 ? text.length : end + 2;
        out += spanTok('comment', text.slice(i, stop));
        i = stop;
        continue;
      }
      if (text[i] === '"' || text[i] === "'") {
        const end = readQuoted(text, i);
        out += spanTok('string', text.slice(i, end));
        i = end;
        continue;
      }
      const color = text.slice(i).match(/^#[\da-fA-F]{3,8}\b/);
      if (color) { out += spanTok('color', color[0]); i += color[0].length; continue; }
      const number = text.slice(i).match(/^-?\d+(?:\.\d+)?(?:px|em|rem|vh|vw|%|s|ms|deg)?\b/);
      if (number) { out += spanTok('number', number[0]); i += number[0].length; continue; }
      const prop = text.slice(i).match(/^[-A-Za-z]+(?=\s*:)/);
      if (prop) { out += spanTok('property', prop[0]); i += prop[0].length; continue; }
      const at = text.slice(i).match(/^@([A-Za-z-]+)/);
      if (at && CSS_AT_RULES.has(at[1])) { out += spanTok('keyword', at[0]); i += at[0].length; continue; }
      if (/^[{}():;,]$/.test(text[i])) out += spanTok('punct', text[i]);
      else out += escHtml(text[i]);
      i++;
    }
    return out;
  }

  function highlightSqlCode(text) {
    let out = '';
    let i = 0;
    while (i < text.length) {
      if (text[i] === '-' && text[i + 1] === '-') {
        const end = text.indexOf('\n', i);
        const stop = end < 0 ? text.length : end;
        out += spanTok('comment', text.slice(i, stop));
        i = stop;
        continue;
      }
      if (text[i] === '/' && text[i + 1] === '*') {
        const end = text.indexOf('*/', i + 2);
        const stop = end < 0 ? text.length : end + 2;
        out += spanTok('comment', text.slice(i, stop));
        i = stop;
        continue;
      }
      if (text[i] === '"' || text[i] === "'") {
        const end = readQuoted(text, i);
        out += spanTok('string', text.slice(i, end));
        i = end;
        continue;
      }
      const num = text.slice(i).match(/^\d+(?:\.\d+)?\b/);
      if (num) { out += spanTok('number', num[0]); i += num[0].length; continue; }
      const word = text.slice(i).match(/^[A-Za-z_][\w$]*/);
      if (word) {
        const value = word[0];
        out += SQL_KEYWORDS.has(value.toLowerCase()) ? spanTok('keyword', value) : escHtml(value);
        i += value.length;
        continue;
      }
      if (/^[(),.;*=<>+-]$/.test(text[i])) out += spanTok('punct', text[i]);
      else out += escHtml(text[i]);
      i++;
    }
    return out;
  }

  function highlightGenericCode(text) {
    return highlightCStyleCode(text, new Set(), {});
  }

  function highlightCodeByLanguage(text, language) {
    if (language === 'json') return highlightJsonCode(text);
    if (language === 'javascript') return highlightCStyleCode(text, JS_TS_KEYWORDS, {});
    if (language === 'typescript') return highlightCStyleCode(text, JS_TS_KEYWORDS, { typescript: true });
    if (language === 'python') return highlightPythonCode(text);
    if (language === 'shell') return highlightShellCode(text);
    if (language === 'yaml') return highlightYamlCode(text);
    if (language === 'html') return highlightHtmlCode(text);
    if (language === 'css') return highlightCssCode(text);
    if (language === 'sql') return highlightSqlCode(text);
    return highlightGenericCode(text);
  }

  function highlightRenderedCodeBlocks(container) {
    if (!container || !container.querySelectorAll) return;
    container.querySelectorAll('pre code').forEach((code) => {
      if (code.dataset.syntaxHighlighted === 'true') return;
      const language = normalizeCodeLanguage(code);
      if (language === 'mermaid') return;
      const source = code.textContent || '';
      code.dataset.syntaxHighlighted = 'true';
      code.classList.add('syntax-highlighted');
      if (language) code.classList.add('syntax-lang-' + language);
      if (source.length > CODE_HIGHLIGHT_MAX_CHARS) {
        code.classList.add('syntax-highlight-skipped');
        return;
      }
      code.innerHTML = highlightCodeByLanguage(source, language);
    });
  }

  function appendParsedMarkdown(markdown, container, options = {}) {
    const keepExisting = !!options.keepExisting;
    let frontmatter = '';
    let body = markdown || '';
    const fmMatch = body.match(/^\s*---\r?\n([\s\S]*?)\r?\n(?:---|\.\.\.)\r?\n?/);
    if (fmMatch) {
      frontmatter = fmMatch[1];
      body = body.substring(fmMatch[0].length);
    }

    const extensions = preprocessMarkdownExtensions(body);
    body = extensions.body;
    const fragment = document.createDocumentFragment();

    if (frontmatter) {
      const fmDiv = document.createElement('div');
      fmDiv.className = 'frontmatter';
      fmDiv.setAttribute('contenteditable', 'false');
      fmDiv.setAttribute('data-frontmatter', 'true');
      fmDiv.setAttribute('data-raw', '---\n' + frontmatter + '\n---');
      fmDiv.innerHTML = '<button class="frontmatter-toggle" onclick="toggleFrontmatter(this)">' + t('Collapse', '折叠') + '</button>' + renderFrontmatter(frontmatter);
      fragment.appendChild(fmDiv);
    }

    const bodyDiv = document.createElement('div');
    bodyDiv.innerHTML = sanitizeHtmlString(marked.parse(body));
    sanitizeRenderedDOM(bodyDiv);
    while (bodyDiv.firstChild) fragment.appendChild(bodyDiv.firstChild);

    const work = document.createElement('div');
    work.appendChild(fragment);
    renderMathPlaceholders(work, extensions.mathBlocks);
    renderFootnotes(work, extensions.footnotes);

    if (!keepExisting) container.innerHTML = '';
    while (work.firstChild) container.appendChild(work.firstChild);
  }

  function finalizeRenderedMarkdown(container, content) {
    applyHeadingAnchors(container);
    rewriteRelativeImages(container);
    const tables = container.querySelectorAll('table:not(.table-wrap table)');
    for (const table of tables) {
      if (table.parentElement && table.parentElement.classList.contains('table-wrap')) continue;
      const wrap = document.createElement('div');
      wrap.className = 'table-wrap';
      table.parentNode.insertBefore(wrap, table);
      wrap.appendChild(table);
    }
    highlightRenderedCodeBlocks(container);
    protectComplexBlocks(container);
    balanceTableColumns(container);
    lastRenderedHash = contentHash(content);
  }

  function scheduleDeferredEnhancements(container, content, jobId) {
    clearTimeout(deferredRenderTimer);
    deferredRenderTimer = setTimeout(async () => {
      if (jobId !== renderJobId || closing) return;
      buildToc(container);
      if (hasRenderableMermaid(container)) {
        await renderMermaidDiagrams(container);
        if (jobId !== renderJobId || closing) return;
        protectComplexBlocks(container);
        balanceTableColumns(container);
        requestAnimationFrame(() => { if (!isSource) updateScrollSpy(); });
      }
    }, 80);
  }

  async function renderMarkdown(content, container) {
    const jobId = ++renderJobId;
    clearTimeout(deferredRenderTimer);
    const split = splitMarkdownForFirstScreen(content);
    appendParsedMarkdown(split.first, container, { keepExisting: false });
    finalizeRenderedMarkdown(container, content);
    scheduleDeferredEnhancements(container, content, jobId);

    if (split.staged) {
      requestAnimationFrame(() => {
        setTimeout(() => {
          if (jobId !== renderJobId || closing) return;
          // Re-render the full document in the deferred pass instead of
          // appending only the tail. Markdown constructs can legally span the
          // split boundary (fences, reference links, definitions), so the final
          // DOM must come from a complete parse even though the first paint is
          // intentionally partial.
          appendParsedMarkdown(content, container, { keepExisting: false });
          finalizeRenderedMarkdown(container, content);
          scheduleDeferredEnhancements(container, content, jobId);
        }, 0);
      });
    }
  }

  function toggleFrontmatter(btn) {
    const box = btn.closest('.frontmatter');
    if (!box) return;
    const collapsed = box.classList.toggle('collapsed');
    btn.textContent = collapsed ? t('Expand', '展开') : t('Collapse', '折叠');
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
    if (!isSource) scheduleScrollSpy();
  }

  function buildToc(container) {
    const toc = document.getElementById('tocSidebar');
    const toggle = document.getElementById('tocToggle');
    const headings = Array.from(container.querySelectorAll('h1, h2, h3, h4, h5, h6'));
    tocHasContent = headings.length >= 2;
    if (toggle) toggle.style.display = tocHasContent ? '' : 'none';
    toc.innerHTML = headings.map((h) => {
      const level = h.tagName.slice(1);
      return `<a class="toc-level-${level}" href="#${encodeURIComponent(h.id)}" data-target="${h.id}">${escHtml(h.textContent)}</a>`;
    }).join('');
    applyTocVisibility();
    setupScrollSpy(headings);
    // Re-sync the highlight once layout settles (e.g. after mermaid reflow).
    requestAnimationFrame(() => { if (!isSource) updateScrollSpy(); });
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
    if (isSource) return; // source mode maintains its own highlight
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
    links.forEach(a => {
      a.classList.toggle('toc-active', a.getAttribute('data-target') === currentId);
    });
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
    if (isSource) scheduleSourceTocHighlight();
    else scheduleScrollSpy();
  }

  function toggleToc() {
    const toc = document.getElementById('tocSidebar');
    tocManualOverride = toc.classList.contains('hidden');
    setTocVisible(tocManualOverride);
  }

  function protectComplexBlocks(container) {
    container.querySelectorAll('pre, .frontmatter, .mermaid-diagram').forEach((node) => {
      node.setAttribute('contenteditable', 'false');
    });
    container.querySelectorAll('div, section, article').forEach((node) => {
      if (node.querySelector('.frontmatter, .mermaid-diagram')) return;
      const hasMarkdownClass = node.classList.contains('frontmatter') || node.classList.contains('mermaid-diagram');
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

    // In source mode, scroll the textarea to the heading line instead of
    // looking for a DOM element (which only exists in rendered mode).
    if (isSource) {
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
    markExplicitTocTarget(id);
    scrollToTocTarget(id);
    // Reflect the jump in the URL; harmless if the engine refuses on file://.
    try {
      if (history && history.replaceState) history.replaceState(null, '', '#' + encodeURIComponent(target.id));
    } catch (e) {}
    return true;
  }

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
      const m = line.match(/^(\s*)([^:]+?)(\s*:\s*)(.*)$/);
      if (m && m[2].indexOf('#') !== 0) {
        const indent = m[1];
        const key = m[2];
        const val = m[4];
        const bm = val.match(/^([>|])([-+]?)\s*$/);
        if (bm) {
          const style = bm[1];      // '>' folded, '|' literal
          const chomp = bm[2] || ''; // '' clip, '-' strip, '+' keep
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
      text = lines.join('\n');
    }
    // Chomping: '-' strip trailing newlines, '+' keep all, default clip to one
    if (chomp === '-') return text.replace(/\n+$/, '');
    if (chomp === '+') return text;
    return text.replace(/\n+$/, '') + '\n';
  }

  function highlightInlineMarkdown(line) {
    let h = escHtml(line);
    h = h.replace(/^(#{1,6})(\s)/, '<span class="syn-heading">$1</span>$2');
    h = h.replace(/(\*\*|__)(.+?)\1/g, '<span class="syn-bold">$1</span>$2<span class="syn-bold">$1</span>');
    h = h.replace(/(^|[^\*])(\*)([^\s\*][^\*]*?)\*(?!\*)/g, '$1<span class="syn-italic">$2</span>$3<span class="syn-italic">$2</span>');
    h = h.replace(/(~~)([^~]+?)(~~)/g, '<span class="syn-strike">$1</span>$2<span class="syn-strike">$1</span>');
    h = h.replace(/`([^`]+)`/g, '<span class="syn-code">`</span>$1<span class="syn-code">`</span>');
    // Image marker "!" gets its own color; the [alt](url) is colored by the
    // link rule that follows.
    h = h.replace(/!\[/g, '<span class="syn-image">!</span>[');
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
        // Color the fence markers AND the language tag (e.g. "text" in
        // ```text) so every part of the fence line is highlighted.
        const highlighted = escHtml(line).replace(/^(```+|~~~+)([^\s`]*)/, '<span class="syn-codeblock">$1</span><span class="syn-lang">$2</span>');
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
        // Code content inside a fence: give it a code color so a fenced block
        // is visibly distinct from body text in the source view.
        out.push('<span class="syn-codeblock">' + escHtml(line) + '</span>');
        continue;
      }
      out.push(highlightInlineMarkdown(line));
    }
    return out.join('\n');
  }

  // Cached text and per-logical-line start offsets of the highlight layer;
  // the source-mode geometry code uses them to locate a line inside the <pre>
  // (whose rendered text is HTML-escaped, so character offsets differ from
  // the textarea's value).
  let _sourceLayerText = '';
  let _sourceLineStarts = null;

  function syncHighlight() {
    const t0 = performance.now();
    const layer = document.getElementById('highlightLayer');
    layer.innerHTML = highlightMarkdown(document.getElementById('textarea').value) + '\n';
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
    if (window.pywebview && window.pywebview.api) window.pywebview.api.save_page_width(BASE_WIDTH * pageWidthPct / 100);
  }
  function resetPageWidth() {
    pageWidthPct = 100;
    applyPageWidth();
    showSizeHint('width');
    if (window.pywebview && window.pywebview.api) window.pywebview.api.save_page_width(BASE_WIDTH);
    showStatus(t('Width reset', '宽度已重置'));
  }
  // ── Font size (View menu: ⌘= / ⌘-) ──
  // Adjusts the content font size (±1px) for BOTH the source editor and the
  // rendered markdown, so every visible text element scales together (headings
  // keep their relative ratios via the --content-font-size CSS variable).
  // In-memory only (not persisted), clamped to a sane range.
  let contentFontSize = 16;
  function applyFontSize() {
    document.documentElement.style.setProperty('--content-font-size', contentFontSize + 'px');
  }
  function zoomIn() {
    contentFontSize = Math.min(FONT_MAX, contentFontSize + FONT_STEP);
    applyFontSize();
    showSizeHint('font');
  }
  function zoomOut() {
    contentFontSize = Math.max(FONT_MIN, contentFontSize - FONT_STEP);
    applyFontSize();
    showSizeHint('font');
  }
  function openFile() {
    if (window.pywebview && window.pywebview.api) window.pywebview.api.open_file_dialog();
  }
  async function closeWindow() {
    if (isDirty) {
      promptBeforeClose();
      return;
    }
    if (window.pywebview && window.pywebview.api) window.pywebview.api.close_window();
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
    // Programmatic value assignment fires no input event, so dismiss the
    // empty-document welcome overlay explicitly (e.g. after ⌘⇧V paste).
    updateEmptyState();
  }
  function handleImageDrop(e) {
    e.preventDefault();
    const files = Array.from(e.dataTransfer.files || []).filter(f => /^image\//.test(f.type));
    if (!files.length) return;
    const snippets = files.map(f => `![${f.name}](${f.path || f.name})`).join('\n');
    insertMarkdownSnippet('\n' + snippets + '\n');
    // Switch back to rendered view so the user sees the image immediately
    // (renderMarkdown already rebuilds the TOC and scroll-spy).
    if (isSource) {
      isSource = false;
      renderMarkdown(getCurrentMarkdown(), document.getElementById('content')).then(() => {
        updateView();
      });
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
  function normalizeWhitespace(s) {
    return String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
  }

  function showPasteHint() {
    const bubble = document.getElementById('editHintBubble');
    if (!bubble) return;
    const sizeBubble = document.getElementById('sizeHintBubble');
    if (sizeBubble) sizeBubble.classList.remove('visible');
    clearTimeout(sizeHintTimer);
    // Each key (⌘ / ⇧ / V) gets its own keycap frame.
    bubble.innerHTML = '<span class="edit-hint-keys">' +
      '<span class="edit-hint-key">⌘</span><span class="edit-hint-key">⇧</span><span class="edit-hint-key">V</span>' +
      '</span><span>' + t('to paste as Markdown', '粘贴为 Markdown') + '</span>';
    bubble.classList.add('visible');
    clearTimeout(editHintTimer);
    // Longer dwell than the edit hint so the reminder is not missed.
    editHintTimer = setTimeout(() => bubble.classList.remove('visible'), 4000);
  }

  // Preview-mode feedback: after a rich paste is converted to Markdown, show a
  // short confirmation bubble so the user knows the conversion happened.
  function showPastedAsMarkdownHint() {
    const bubble = document.getElementById('editHintBubble');
    if (!bubble) return;
    const sizeBubble = document.getElementById('sizeHintBubble');
    if (sizeBubble) sizeBubble.classList.remove('visible');
    clearTimeout(sizeHintTimer);
    bubble.innerHTML = '<span>' + t('Pasted as Markdown', '已粘贴为 Markdown') + '</span>';
    bubble.classList.add('visible');
    clearTimeout(editHintTimer);
    editHintTimer = setTimeout(() => bubble.classList.remove('visible'), 2000);
  }

  function readClipboardBest() {
    if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.read_clipboard === 'function') {
      return window.pywebview.api.read_clipboard();
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
    if (!anchor || anchor.length < 2) return -1;
    return findNthOccurrenceSourceOffset(md, anchor, nth);
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

  // Preview mode: insert converted markdown into the source at the position
  // matching the rendered caret, then re-render and restore the caret.
  async function insertMdInPreview(pastedMd) {
    const content = document.getElementById('content');
    const textarea = document.getElementById('textarea');
    const sel = window.getSelection();
    const caretNode = sel && sel.rangeCount ? sel.getRangeAt(0).startContainer : null;
    const caretOffset = sel && sel.rangeCount ? sel.getRangeAt(0).startOffset : 0;
    // Use the real current source: if the user edited the rendered view,
    // textarea.value is stale (getCurrentMarkdown round-trips via turndown).
    const src = getCurrentMarkdown();
    let pos = mapRenderedCaretToSourceOffset(src, content, caretNode, caretOffset);
    if (pos < 0) pos = src.length;
    const s = String(pastedMd || '').trim();
    if (!s) return;
    const block = s.indexOf('\n') !== -1 ? '\n\n' + s + '\n\n' : s;
    textarea.value = src.slice(0, pos) + block + src.slice(pos);
    const caretSource = pos + block.length;
    textarea.setSelectionRange(caretSource, caretSource);
    await renderMarkdown(textarea.value, content);
    renderedDirty = false;
    setDirty(true);
    syncHighlight();
    schedulePythonSync(700);
    placeCaretNearRenderedText(content, firstMeaningfulLine(s));
    try { content.focus({ preventScroll: true }); } catch (e) { content.focus(); }
  }

  // Entry point for the "Paste as Markdown" menu item, Cmd+Shift+V, and
  // preview-mode Cmd+V. Reads the best clipboard flavor, converts, inserts.
  async function pasteAsMarkdown() {
    if (closing) return;
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
      md = turndownService ? turndownService.turndown(cleaned) : cleaned;
      quality = checkPasteQuality(clip.content, md);
    } else {
      md = clip.content;
    }
    if (!md || !md.trim()) {
      showStatus(t('Nothing to paste', '没有可粘贴的内容'), true);
      return;
    }
    if (quality) showPasteQualityWarning();
    if (isSource) {
      insertMdAtSourceCaret(md);
    } else {
      await insertMdInPreview(md);
      // Preview mode: confirm the conversion happened for rich pastes.
      if (clip.format === 'html' || clip.format === 'markdown') showPastedAsMarkdownHint();
    }
  }

  function currentDocTitle() {
    return filePath && filePath !== 'Untitled.md' ? filePath.split('/').pop().replace(/\.[^.]+$/, '') : 'Untitled';
  }

  function buildHtml() {
    const title = currentDocTitle();
    const clone = document.getElementById('content').cloneNode(true);
    clone.querySelectorAll('.frontmatter-toggle, .colgroup, colgroup').forEach(el => el.remove());
    clone.querySelectorAll('*').forEach(el => {
      el.removeAttribute('contenteditable');
      el.removeAttribute('spellcheck');
      Array.from(el.attributes).forEach(attr => {
        if (attr.name.startsWith('data-')) el.removeAttribute(attr.name);
      });
    });
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
    return html;
  }

  // Word (.docx) via html-docx-js 0.3.1: its API is asBlob(html, opts) which
  // returns a Blob; we read it back as a base64 data URL for the native write.
  async function buildDocx() {
    try {
      if (typeof htmlDocx === 'undefined') {
        showStatus(t('Word export is not ready yet', 'Word 导出功能尚未就绪'), true);
        return null;
      }
      const html = buildHtml();
      const blob = htmlDocx.asBlob(html, {
        margins: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
      });
      return await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(reader.error || new Error('FileReader failed'));
        reader.readAsDataURL(blob);
      });
    } catch (err) {
      showStatus(t('Word export failed: ', 'Word 导出失败：') + (err && err.message ? err.message : err), true);
      return null;
    }
  }

  // html2canvas 1.4.1 cannot parse modern CSS color() functions (e.g.
  // `color(display-p3 ...)` produced when a CSS variable expands into a color
  // value). Before rendering we normalize every color property in the clone
  // back to rgb/rgba so export never fails on it.
  function convertColorFunction(v) {
    const m = v.match(/color\(\s*([a-z0-9-]+)\s+([\d.]+%?)\s+([\d.]+%?)\s+([\d.]+%?)(?:\s*\/\s*([\d.]+%?))?\s*\)/);
    if (!m) return '#000000';
    const toFrac = (s) => s.endsWith('%') ? parseFloat(s) / 100 : parseFloat(s);
    const r = Math.max(0, Math.min(255, Math.round(toFrac(m[2]) * 255)));
    const g = Math.max(0, Math.min(255, Math.round(toFrac(m[3]) * 255)));
    const b = Math.max(0, Math.min(255, Math.round(toFrac(m[4]) * 255)));
    const a = m[5] !== undefined ? toFrac(m[5]) : 1;
    return a >= 1 ? 'rgb(' + r + ',' + g + ',' + b + ')' : 'rgba(' + r + ',' + g + ',' + b + ',' + a + ')';
  }

  function sanitizeCloneColors(doc) {
    const props = [
      'color', 'backgroundColor', 'borderTopColor', 'borderRightColor',
      'borderBottomColor', 'borderLeftColor', 'borderBlockStartColor',
      'borderBlockEndColor', 'borderInlineStartColor', 'borderInlineEndColor',
      'outlineColor', 'textDecorationColor', 'caretColor', 'columnRuleColor',
      'textEmphasisColor', 'WebkitTextFillColor', 'WebkitTextStrokeColor',
      'boxShadow', 'textShadow',
    ];
    doc.querySelectorAll('*').forEach(el => {
      const cs = getComputedStyle(el);
      for (const p of props) {
        const v = cs.getPropertyValue(p);
        if (v && v.indexOf('color(') >= 0) {
          el.style.setProperty(p, convertColorFunction(v));
        }
      }
    });
  }

  // PNG long image via html2canvas: render the whole content area to a bitmap.
  async function buildPng() {
    try {
      if (typeof html2canvas === 'undefined') {
        showStatus(t('PNG export is not ready yet', 'PNG 导出功能尚未就绪'), true);
        return null;
      }
      const contentEl = document.getElementById('content');
      if (!contentEl) return null;
      showStatus(t('Rendering image…', '正在渲染图片…'));
      const canvas = await html2canvas(contentEl, {
        backgroundColor: '#ffffff',
        scale: 2,
        useCORS: true,
        logging: false,
        onclone: sanitizeCloneColors,
      });
      return canvas.toDataURL('image/png');
    } catch (err) {
      showStatus(t('PNG export failed: ', 'PNG 导出失败：') + (err && err.message ? err.message : err), true);
      return null;
    }
  }

  // ── Export As (File menu): one native panel with a format popup ──
  async function exportAs() {
    if (!window.pywebview || !window.pywebview.api) {
      showStatus(t('Export is not ready yet', '导出功能尚未就绪'), true);
      return;
    }
    try {
      const res = await window.pywebview.api.export_as_choose(currentDocTitle() + '.md');
      if (!res || !res.success) return;
      const writeRes = await exportAsWrite(res.path, res.format);
      if (writeRes && writeRes.success) {
        showStatus(t('Exported', '已导出'));
      } else {
        showStatus(t('Export failed: ', '导出失败：') + ((writeRes && writeRes.error) || ''), true);
      }
    } catch (err) {
      showStatus(t('Export failed: ', '导出失败：') + (err && err.message ? err.message : err), true);
    }
  }

  // Build the payload for a chosen export format and write it through the
  // native bridge. Shared by Export As and Save As (non-Markdown formats).
  // PDF/PNG capture the rendered DOM: in Source mode the textarea is only
  // viewport-tall and #content is hidden, so a capture would yield just the
  // visible area (or an empty image). We temporarily switch to Preview and
  // restore the UI after the write completes.
  async function exportAsWrite(path, format) {
    const needPreview = isSource && (format === 'pdf' || format === 'png');
    if (needPreview) await showPreviewForCapture();
    // PDFs must not contain the fixed-position TOC sidebar. Hide it (and drop
    // the has-toc layout class so the page goes back to full-width centering)
    // for the duration of the write, then restore.
    const toc = document.querySelector('.toc-sidebar');
    const hideToc = format === 'pdf' && !!toc;
    const tocPrevDisplay = hideToc ? toc.style.display : null;
    const wasHasToc = hideToc && document.body.classList.contains('has-toc');
    if (hideToc) {
      toc.style.display = 'none';
      document.body.classList.remove('has-toc');
    }
    // WKWebView only paints what the document actually contains: body is
    // height:100vh with the scrolling happening inside .scroll-wrap, so
    // createPDF would capture just one viewport (the rest of the PDF comes
    // out blank). Temporarily un-clamp the document to its full content
    // height for the duration of the write, then restore the layout.
    const savedLayout = [];
    const stash = (el, p) => savedLayout.push([el, p, el.style.getPropertyValue(p)]);
    const body = document.body;
    const sw = document.querySelector('.scroll-wrap');
    if (format === 'pdf') {
      stash(body, 'height');
      stash(body, 'overflow');
      if (sw) { stash(sw, 'position'); stash(sw, 'height'); stash(sw, 'overflow'); }
      body.style.height = 'auto';
      body.style.overflow = 'visible';
      if (sw) {
        sw.style.position = 'static';
        sw.style.height = 'auto';
        sw.style.overflow = 'visible';
      }
      void body.offsetHeight;  // force reflow before measuring
    }
    try {
      let content = '';
      if (format === 'md' || format === 'txt') content = getCurrentMarkdown();
      else if (format === 'html') content = buildHtml();
      else if (format === 'docx') {
        await ensureLib('html-docx-js.js', 'htmlDocx');
        content = await buildDocx();
      } else if (format === 'png') {
        await ensureLib('html2canvas.min.js', 'html2canvas');
        content = await buildPng();
      }
      if (content === null) return { success: false, error: 'conversion-failed' };
      let pageSize = null;
      if (format === 'pdf') {
        // createPDF defaults to the visible viewport; pass the full document
        // size so everything is captured. +100px keeps the last line off the
        // page edge. `breaks` lists the top edge of every block element so the
        // A4 slicing lands on element boundaries instead of mid-line.
        pageSize = {
          width: Math.max(document.body.scrollWidth, window.innerWidth),
          height: document.body.scrollHeight + 100,
        };
      }
      return await window.pywebview.api.export_as_write(path, format, content, pageSize);
    } finally {
      savedLayout.forEach(([el, p, v]) => {
        if (v) el.style.setProperty(p, v);
        else el.style.removeProperty(p);
      });
      if (hideToc) {
        toc.style.display = tocPrevDisplay;
        if (wasHasToc) document.body.classList.add('has-toc');
      }
      if (needPreview) restoreSourceMode();
    }
  }

  // Temporarily render the Preview DOM for a capture while staying logically
  // in Source mode; restoreSourceMode() puts the UI back afterwards.
  async function showPreviewForCapture() {
    const content = document.getElementById('content');
    const source = document.getElementById('source');
    const page = document.getElementById('page');
    const textarea = document.getElementById('textarea');
    const md = textarea ? textarea.value : '';
    if (contentHash(md) !== lastRenderedHash) {
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
  function printDocument() { window.print(); }

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

  function setModal(title, bodyHtml, actionsHtml) {
    const header = document.getElementById('modalHeader');
    const body = document.getElementById('modalBody');
    const actions = document.getElementById('modalActions');
    if (header) header.textContent = title;
    if (body) body.innerHTML = bodyHtml;
    if (actions) actions.innerHTML = actionsHtml || '<button class="modal-close" onclick="closeModal()">' + t('Close', '关闭') + '</button>';
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
    if (img) {
      e.preventDefault();
      document.getElementById('imageLightboxImg').src = img.src;
      document.getElementById('imageLightbox').classList.add('visible');
      return;
    }
    // Non-editable rendered content (frontmatter, code blocks, math, Mermaid,
    // protected blocks, ...): show a transient hint pointing the user to the
    // Source view instead of silently doing nothing.
    // NOTE: do NOT exclude [contenteditable="true"] here — closest() walks up
    // to #content (which IS contenteditable="true") and would always match,
    // silently disabling the hint. Editable-vs-not is decided by
    // findNonEditableAncestor() below.
    if (!isSource && !e.target.closest('button, a, input, select, label, [role="button"]')) {
      if (getTableInteractionTarget(e)) {
        showTableEditHint();
        return;
      }
      const ne = findNonEditableAncestor(e.target);
      if (ne) showEditHint(ne);
    }
  });
  document.getElementById('content').addEventListener('beforeinput', (e) => {
    if (!isSource && getTableInteractionTarget(e)) showTableEditHint();
  });
  document.getElementById('content').addEventListener('input', (e) => {
    if (!isSource && getTableInteractionTarget(e)) showTableEditHint();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeModal();
  });
  function escHtml(s) {
    if (!s) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

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
    try {
      if (window.pywebview && window.pywebview.api && window.pywebview.api.startup_ready) {
        window.pywebview.api.startup_ready(Math.round(performance.now() - _jsT0));
      }
    } catch (e) {}
    
    if (pageWidth) {
      pageWidthPct = normalizePageWidthPct(pageWidth / BASE_WIDTH * 100);
      applyPageWidth();
    }
    if (zh !== undefined) {
      isZh = zh;
      applyStaticUiLanguage();
    }
    await renderMarkdown(content, document.getElementById('content'));
    document.getElementById('textarea').value = content;
    syncHighlight();
    lastPushedHash = contentHash(content);
    isDirty = false;
    renderedDirty = false;
    if (window.pywebview && window.pywebview.api) window.pywebview.api.set_dirty(false);
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
    if (draftRecovered) showDraftRecoveredBanner();
    // Preload turndown.js in background (non-blocking) so it's ready
    // when the user first toggles to source mode.
    ensureTurndown();
    if (containsMermaidFence(content)) {
      ensureMermaid();
    }
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
      if (window.pywebview && window.pywebview.api) {
        window.pywebview.api.get_initial_content().then((data) => loadContent(data.path, data.content, data.pageWidth, data.draftRecovered, data.isZh));
      }
      remove();
    });
    dismiss.addEventListener('click', (e) => { e.preventDefault(); remove(); });
    setTimeout(remove, STATUS_HIDE_MS);
  }

  function reloadContent() {
    if (window.pywebview && window.pywebview.api) {
      window.pywebview.api.get_initial_content().then((data) => loadContent(data.path, data.content, data.pageWidth, data.draftRecovered, data.isZh));
    }
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
      a.classList.toggle('toc-active', a.getAttribute('data-target') === headingId);
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
  function collectMarkdownHeadingSlugs(md) {
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
    if (!layer || !wrap || !_sourceLineStarts) return null;
    const start = _sourceLineStarts[line];
    if (start === undefined) return null;
    const nl = _sourceLayerText.indexOf('\n', start);
    const end = nl === -1 ? _sourceLayerText.length : nl;
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
    for (const s of headings) {
      const t = sourceLineTop(s.line);
      if (t === null) continue;
      if (t <= limit) active = s.slug;
      else break;
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
    if (!isSource) return;
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
    if (!isSource) return;
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

  async function toggleView() {
    if (!isSource) {
      // rendered → source: capture cursor, convert, position
      const content = document.getElementById('content');
      const textarea = document.getElementById('textarea');
      if (renderedDirty) {
        // Only round-trip the DOM when the user actually edited the rendered view.
        await ensureTurndown();
        const html = content.innerHTML;
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
      if (contentHash(md) !== lastRenderedHash) {
        await renderMarkdown(md, document.getElementById('content'));
      }
      renderedDirty = false;
      isSource = false;
      updateView();
      syncPositionToRendered(headingId);
    }
  }

  function updateView() {
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
    showModeIndicator();
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
        const tips = isZh
          ? '拖拽 <strong>.md</strong> 文件到此处，或双击打开'
          : 'or double click a <strong>.md</strong> file to open';
        const toggleTip = isZh
          ? '<kbd>⌘</kbd><kbd>E</kbd> 预览'
          : '<kbd>⌘</kbd><kbd>E</kbd> to preview';
        const pasteTip = isZh
          ? '<kbd>⌘</kbd><kbd>⇧</kbd><kbd>V</kbd> 粘贴为 Markdown'
          : '<kbd>⌘</kbd><kbd>⇧</kbd><kbd>V</kbd> to paste as Markdown';
        const title = isZh ? '开始书写' : 'Start writing';
        overlay.innerHTML = '<div class="welcome-icon">&#9998;</div>' +
          '<div class="welcome-title">' + title + '</div>' +
          '<div class="welcome-tip">' + tips + '</div>' +
          '<div class="welcome-tip">' + toggleTip + '</div>' +
          '<div class="welcome-tip">' + pasteTip + '</div>';
        content.parentNode.appendChild(overlay);
        overlay.addEventListener('click', () => {
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

  function forceCloseWindow(discard = false) {
    closePromptVisible = false;
    if (window.pywebview && window.pywebview.api) {
      window.pywebview.api.force_close_window(!!discard);
    }
  }

  // Called by Python when the user closes the last document window but is not
  // quitting the app. Instead of terminating, the window becomes a blank Untitled
  // document so the app stays alive and Finder double-click / Dock reopen keep
  // working without a cold start.
  function convertToBlankDocument() {
    filePath = null;
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
    if (window.pywebview && window.pywebview.api) {
      window.pywebview.api.reset_to_untitled();
    }
  }

  function promptBeforeClose(force = false) {
    if (!force && !isDirty) {
      forceCloseWindow();
      return;
    }
    if (closePromptVisible) return;
    closePromptVisible = true;
    // Native TextEdit-style dialog (keep question + name/location + red
    // Delete / gray Cancel / blue Save) shown from the Python side. The
    // in-page modal below is only a fallback for non-Cocoa environments.
    if (window.pywebview && window.pywebview.api && window.pywebview.api.native_save_prompt) {
      window.pywebview.api.native_save_prompt()
        .then(async (res) => {
          closePromptVisible = false;
          if (!res || !res.action) return;
          if (res.action === 'save') {
            if (res.path && res.path !== filePath) filePath = res.path;
            const result = await saveFile(false, null, { closeOnSuccess: true });
            if (result && result.saved) {
              await forceCloseWindow();
            } else {
              closePromptVisible = false;
            }
          } else if (res.action === 'delete') {
            await forceCloseWindow(true);
          }
          // cancel: keep the window open and do nothing
        })
        .catch(() => { closePromptVisible = false; });
      return;
    }
    const name = filePath && filePath !== 'Untitled.md' ? filePath.split('/').pop() : 'Untitled.md';
    const bodyHtml = '<p>' + t('Do you want to save the changes you made to', '是否保存对') + ' <strong>' + escHtml(name) + '</strong> ' + t('?', '所做的更改？') + '</p>' +
      '<p style="color:#666;margin-bottom:0;">' + t('Your changes will be lost if you do not save them.', '若不保存，更改将丢失。') + '</p>';
    const actionsHtml = '<button class="modal-button secondary" id="closeCancel">' + t('Cancel', '取消') + '</button>' +
      '<button class="modal-button danger" id="closeDiscard">' + t("Don't Save", '不保存') + '</button>' +
      '<button class="modal-button" id="closeSave">' + t('Save', '保存') + '</button>';
    setModal(t('Save Changes?', '保存更改？'), bodyHtml, actionsHtml);
    document.getElementById('closeCancel').addEventListener('click', () => {
      closePromptVisible = false;
      closeModal();
    });
    document.getElementById('closeDiscard').addEventListener('click', async () => {
      closeModal();
      await forceCloseWindow(true);
    });
    document.getElementById('closeSave').addEventListener('click', async () => {
      closeModal();
      closePromptVisible = false;
      const result = await saveFile(false, null, { closeOnSuccess: true });
      if (result && result.saved) await forceCloseWindow();
    });
  }

  function showSaveConflictDialog(path, markdown, options = {}) {
    const finishOverwrite = async () => {
      const result = await saveFile(true, markdown);
      if (options.closeOnSuccess && result && result.saved) await forceCloseWindow();
    };
    const finishSaveAs = async () => {
      const result = await saveAsFile(markdown);
      if (options.closeOnSuccess && result && result.saved) await forceCloseWindow();
    };
    const finishCancel = () => {
      showStatus(t('Save cancelled', '已取消保存'));
      if (options.closeOnCancel) promptBeforeClose();
    };
    // Native macOS sheet (Save Current / Save As / Cancel); the HTML modal
    // below stays as a fallback for non-Cocoa environments.
    if (window.pywebview && window.pywebview.api && window.pywebview.api.native_conflict_prompt) {
      window.pywebview.api.native_conflict_prompt(path)
        .then((res) => {
          if (!res || !res.action) return finishCancel();
          if (res.action === 'overwrite') return finishOverwrite();
          if (res.action === 'save_as') return finishSaveAs();
          return finishCancel();
        })
        .catch(() => finishCancel());
      return;
    }
    const name = path ? path.split('/').pop() : t('this file', '此文件');
    const bodyHtml = '<p>' + t('The file', '文件') + ' <strong>' + escHtml(name) + '</strong> ' + t('has changed on disk since it was opened or last saved.', '自打开或上次保存以来已在磁盘上发生变化。') + '</p>' +
      '<p>' + t('Choose how to continue:', '请选择如何继续：') + '</p>' +
      '<ul style="margin:8px 0 0 18px;padding:0;color:#555;line-height:1.5;">' +
      '<li><strong>' + t('Save As', '另存为') + '</strong> ' + t('keeps the changed file untouched and saves this document to a new path.', '保持磁盘文件不变，将本文档保存到新路径。') + '</li>' +
      '<li><strong>' + t('Save Current', '保存当前') + '</strong> ' + t('overwrites the file on disk with the content in this window.', '用当前窗口内容覆盖磁盘文件。') + '</li>' +
      '<li><strong>' + t('Cancel', '取消') + '</strong> ' + t('stops saving.', '停止保存。') + '</li>' +
      '</ul>';
    const actionsHtml = '<button class="modal-button secondary" id="conflictCancel">' + t('Cancel', '取消') + '</button>' +
      '<button class="modal-button" id="conflictSaveAs">' + t('Save As...', '另存为…') + '</button>' +
      '<button class="modal-button danger" id="conflictOverwrite">' + t('Save Current', '保存当前') + '</button>';
    setModal(t('Save Conflict', '保存冲突'), bodyHtml, actionsHtml);
    document.getElementById('conflictCancel').addEventListener('click', () => {
      closeModal();
      finishCancel();
    });
    document.getElementById('conflictSaveAs').addEventListener('click', () => {
      closeModal();
      finishSaveAs();
    });
    document.getElementById('conflictOverwrite').addEventListener('click', () => {
      closeModal();
      finishOverwrite();
    });
  }

  async function saveFile(force = false, suppliedMarkdown = null, options = {}) {
    if (!window.pywebview || !window.pywebview.api) {
      showStatus(t('Save is not ready yet', '保存功能尚未就绪'), true);
      return { saved: false, error: 'not-ready' };
    }
    const markdown = suppliedMarkdown !== null ? suppliedMarkdown : getCurrentMarkdown();
    if (!filePath || filePath === 'Untitled.md') {
      return await saveAsFile(markdown);
    }
    try {
      const result = await window.pywebview.api.save_file(filePath, markdown, !!force);
      if (result.success) {
        markSaved(markdown);
        showStatus(force ? t('Saved current version', '已保存当前版本') : t('Saved', '已保存'));
        return { saved: true };
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
    }
  }

  async function saveAsFile(suppliedMarkdown = null) {
    if (!window.pywebview || !window.pywebview.api) {
      showStatus(t('Save is not ready yet', '保存功能尚未就绪'), true);
      return { saved: false, error: 'not-ready' };
    }
    const markdown = suppliedMarkdown !== null ? suppliedMarkdown : getCurrentMarkdown();
    try {
      const result = await window.pywebview.api.save_as_choose(currentDocTitle() + '.md');
      if (result && result.success) {
        const { path, format } = result;
        if (format === 'md') {
          filePath = path;
          markSaved(markdown);
          showStatus(t('Saved', '已保存'));
          return { saved: true };
        }
        // Saved as another format: export only, keep the working file untouched.
        const writeRes = await exportAsWrite(path, format);
        if (writeRes && writeRes.success) {
          showStatus(t('Saved', '已保存'));
          return { saved: true, exported: true, path };
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
  function showStatus(text, isError = false) {
    const el = document.getElementById('status');
    el.textContent = text;
    el.classList.toggle('error', !!isError);
    el.classList.add('visible');
    clearTimeout(statusTimer);
    statusTimer = setTimeout(() => el.classList.remove('visible'), isError ? 5000 : 1500);
  }

  // ── Non-editable content hint bubble ──
  // The rendered view is contenteditable, but some blocks are marked
  // contenteditable="false" (frontmatter, fenced code blocks, math, Mermaid
  // diagrams, protected blocks). Clicking one of those does nothing visually,
  // so show a short-lived translucent bubble suggesting the Source view.
  let editHintTimer = null;
  let sizeHintTimer = null;

  function showSizeHint(kind) {
    const bubble = document.getElementById('sizeHintBubble');
    if (!bubble) return;
    const editBubble = document.getElementById('editHintBubble');
    if (editBubble) editBubble.classList.remove('visible');
    clearTimeout(editHintTimer);
    let text;
    if (kind === 'width') {
      text = t('Width', '宽度') + ' ' + pageWidthPct + '%';
    } else {
      text = t('Font', '字号') + ' ' + contentFontSize + 'px';
    }
    bubble.textContent = text;
    bubble.classList.add('visible');
    clearTimeout(sizeHintTimer);
    sizeHintTimer = setTimeout(() => bubble.classList.remove('visible'), 1000);
  }

  function findNonEditableAncestor(target) {
    const contentEl = document.getElementById('content');
    let el = target && target.nodeType === 1 ? target : (target ? target.parentNode : null);
    while (el && el !== contentEl && el !== document.body) {
      if (el.getAttribute && el.getAttribute('contenteditable') === 'false') return el;
      el = el.parentNode;
    }
    return null;
  }

  function getTableInteractionTarget(event) {
    const contentEl = document.getElementById('content');
    const fromTarget = event && event.target && event.target.closest ? event.target.closest('table') : null;
    if (fromTarget && contentEl && contentEl.contains(fromTarget)) return fromTarget;
    const selection = window.getSelection ? window.getSelection() : null;
    if (!selection || selection.rangeCount === 0) return null;
    const node = selection.anchorNode;
    const el = node && node.nodeType === 1 ? node : (node ? node.parentNode : null);
    const fromSelection = el && el.closest ? el.closest('table') : null;
    return fromSelection && contentEl && contentEl.contains(fromSelection) ? fromSelection : null;
  }

  function showEditHint(anchor) {
    const bubble = document.getElementById('editHintBubble');
    if (!bubble) return;
    const sizeBubble = document.getElementById('sizeHintBubble');
    if (sizeBubble) sizeBubble.classList.remove('visible');
    clearTimeout(sizeHintTimer);
    // ⌘E-first copy: the shortcut is the anchor, the verb follows. Kept as
    // constant strings (no user input) so innerHTML is safe.
    bubble.innerHTML = '<span class="edit-hint-key">⌘E</span><span>' + t('to edit in Source', '使用源码模式编辑') + '</span>';
    bubble.classList.add('visible');
    clearTimeout(editHintTimer);
    editHintTimer = setTimeout(() => bubble.classList.remove('visible'), 1600);
  }

  function showTableEditHint() {
    const bubble = document.getElementById('editHintBubble');
    if (!bubble) return;
    const sizeBubble = document.getElementById('sizeHintBubble');
    if (sizeBubble) sizeBubble.classList.remove('visible');
    clearTimeout(sizeHintTimer);
    bubble.innerHTML = '<span class="edit-hint-copy">Switch to Source mode</span>' +
      '<span class="edit-hint-keys"><span class="edit-hint-key">⌘</span><span class="edit-hint-key">E</span></span>' +
      '<span class="edit-hint-copy">to keep your table formatting intact</span>';
    bubble.classList.add('visible');
    clearTimeout(editHintTimer);
    editHintTimer = setTimeout(() => bubble.classList.remove('visible'), 1800);
  }

  // Apply bilingual text to static UI elements declared in index.html.
  // Called whenever isZh is (re)set, i.e. after each loadContent().
  function applyStaticUiLanguage() {
    const findInput = document.getElementById('findInput');
    if (findInput) findInput.placeholder = t('Find', '查找');
    const findPrev = document.getElementById('findPrev');
    if (findPrev) findPrev.title = t('Previous (Shift+Cmd+G)', '上一个 (Shift+Cmd+G)');
    const findNext = document.getElementById('findNext');
    if (findNext) findNext.title = t('Next (Cmd+G)', '下一个 (Cmd+G)');
    const findClose = document.getElementById('findClose');
    if (findClose) findClose.title = t('Close (Esc)', '关闭 (Esc)');
    const tocToggle = document.getElementById('tocToggle');
    if (tocToggle) {
      const label = t('Show outline', '显示大纲');
      tocToggle.title = label;
      tocToggle.setAttribute('aria-label', label);
    }
      const ub = document.getElementById('updateBubble');
    if (ub) {
      const txt = ub.querySelector('.update-bubble-text');
      if (txt && !ub.classList.contains('installing') && !ub.classList.contains('downloading')) {
        txt.textContent = t('Update available, click to install...', '有新版本可用，点击安装…');
      }
      const closeBtn = ub.querySelector('.update-bubble-close');
      if (closeBtn) {
        const dismiss = t('Dismiss', '忽略');
        closeBtn.title = dismiss;
        closeBtn.setAttribute('aria-label', dismiss);
      }
    }
  }

  let _updateBubbleDismissed = false;

  function setUpdateBubbleText(text) {
    const el = document.getElementById('updateBubble');
    const txt = el ? el.querySelector('.update-bubble-text') : null;
    if (txt) txt.textContent = text;
  }

  function setUpdateProgress(percent) {
    const bar = document.getElementById('updateProgressBar');
    if (bar) bar.style.width = Math.max(0, Math.min(100, percent || 0)) + '%';
  }

  function showUpdateBubble() {
    if (_updateBubbleDismissed) return;
    const el = document.getElementById('updateBubble');
    if (el) {
      el.classList.remove('downloading');
      el.classList.add('visible');
      setUpdateProgress(0);
      setUpdateBubbleText(t('Update available, click to install...', '有新版本可用，点击安装…'));
    }
  }

  function showUpdateDownloadProgress(percent) {
    _updateBubbleDismissed = false;
    const el = document.getElementById('updateBubble');
    const p = Math.max(0, Math.min(100, Math.round(percent || 0)));
    if (el) {
      el.classList.remove('installing');
      el.classList.add('visible', 'downloading');
      setUpdateProgress(p);
      setUpdateBubbleText(t('Downloading update... ', '正在下载更新… ') + p + '%');
    }
  }

  function showUpdateDownloadFailed(message) {
    const el = document.getElementById('updateBubble');
    if (el) {
      el.classList.remove('downloading', 'installing');
      el.classList.add('visible');
      setUpdateProgress(0);
      setUpdateBubbleText(t('Download failed. Check your connection.', '下载失败，请检查网络。'));
    }
    showStatus(t('Update download failed: ', '更新下载失败：') + (message || t('unknown', '未知')), true);
  }

  function showManualInstallGuide(dmgPath, message) {
    const hint = dmgPath
      ? t(' Open the DMG and drag mdPreview to Applications: ', ' 请打开 DMG，并将 mdPreview 拖到 Applications：') + dmgPath
      : t(' Please download the DMG manually and drag mdPreview to Applications.', ' 请手动下载 DMG，并将 mdPreview 拖到 Applications。');
    showStatus((message || t('Update failed.', '更新失败。')) + hint, true);
  }

  function dismissUpdateBubble(event) {
    if (event) event.stopPropagation();
    _updateBubbleDismissed = true;
    const el = document.getElementById('updateBubble');
    if (el) el.classList.remove('visible');
  }

  function installUpdate() {
    const el = document.getElementById('updateBubble');
    if (el && (el.classList.contains('installing') || el.classList.contains('downloading'))) return;
    if (el) {
      setUpdateBubbleText(t('Installing...', '正在安装…'));
      el.classList.remove('downloading');
      el.classList.add('installing');
    }
    showStatus(t('Installing update...', '正在安装更新…'));
    if (window.pywebview && window.pywebview.api) {
      window.pywebview.api.perform_auto_install().then(function(result) {
        if (result && result.success) {
          showStatus(t('Update installed. Restarting...', '更新已安装，正在重启…'));
        } else {
          const error = result ? result.error : t('unknown', '未知');
          if (result && result.manual_install) {
            showManualInstallGuide(result.manual_dmg_path || '', t('Automatic install failed.', '自动安装失败。'));
          } else {
            showStatus(t('Update failed: ', '更新失败：') + error, true);
          }
          if (el) {
            setUpdateBubbleText(t('Update available, click to install...', '有新版本可用，点击安装…'));
            el.classList.remove('installing');
          }
        }
      }).catch(function(err) {
        showStatus(t('Update failed: ', '更新失败：') + err, true);
        if (el) {
          setUpdateBubbleText(t('Update available, click to install...', '有新版本可用，点击安装…'));
          el.classList.remove('installing');
        }
      });
    }
  }

  let findState = { query: '', matches: [], currentIdx: -1, scrollTop: 0 };

  function openFindBar() {
    const bar = document.getElementById('findBar');
    const input = document.getElementById('findInput');
    bar.classList.add('visible');
    // Push content down so the bar doesn't overlap
    document.querySelector('.scroll-wrap').style.top = '40px';
    input.focus();
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
    const lines = textarea.value.substring(0, start).split('\n').length; // 1-based
    // Scroll first (leaving ~100px of context above), then select and focus:
    // focusing reveals the caret, and a pre-scrolled caret doesn't fight it.
    scrollTextareaToLine(lines - 1, 100);
    textarea.setSelectionRange(start, end);
    try { textarea.focus({ preventScroll: true }); } catch (e) { textarea.focus(); }
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
    if (cmd && e.key === '0') { e.preventDefault(); resetPageWidth(); }
    // Zoom: ⌘= / ⌘- (View menu). WebKit may not forward ⌘= to JS when the
    // menu item handles it, so this is a JS-level fallback as well.
    if (cmd && e.key === '=') { e.preventDefault(); zoomIn(); }
    if (cmd && e.key === '-') { e.preventDefault(); zoomOut(); }
    // Width: ⌘. / ⌘, (moved off ⌘= / ⌘- which are now Zoom).
    if (cmd && e.key === '.') { e.preventDefault(); adjustPageWidth(10); }
    if (cmd && e.key === ',') { e.preventDefault(); adjustPageWidth(-10); }
    if (cmd && e.key === 'e') { e.preventDefault(); toggleView(); }
    if (cmd && e.key === 'f') { e.preventDefault(); openFindBar(); }
    if (cmd && e.key === 'g') { e.preventDefault(); e.shiftKey ? findPrev() : findNext(); }
    // Paste as Markdown: normally the native Edit menu item (Cmd+Shift+V)
    // consumes this first; this is a JS-level fallback for before menus are
    // set up or if the menu item is unavailable.
    if (cmd && e.shiftKey && e.key === 'v') { e.preventDefault(); pasteAsMarkdown(); return; }
  });

  function isBlockedHref(href) {
    return !href || /^\s*(javascript:|data:)/i.test(href);
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
    if (highlightRaf !== null) { cancelAnimationFrame(highlightRaf); highlightRaf = null; }
    clearTimeout(statusTimer);
    clearTimeout(deferredRenderTimer);
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

  document.getElementById('content').addEventListener('input', () => { renderedDirty = true; setDirty(true); schedulePythonSync(PYTHON_SYNC_DEBOUNCE_MS); dismissWelcomeOverlay(); });
  document.getElementById('textarea').addEventListener('input', () => { setDirty(true); scheduleHighlightSync(); schedulePythonSync(700); updateEmptyState(); });
  const scrollWrapEl = document.querySelector('.scroll-wrap');
  if (scrollWrapEl) scrollWrapEl.addEventListener('scroll', scheduleTocSync, { passive: true });
  const sourceTextarea = document.getElementById('textarea');
  sourceTextarea.addEventListener('click', scheduleSourceTocHighlight);
  sourceTextarea.addEventListener('keyup', scheduleSourceTocHighlight);
  sourceTextarea.addEventListener('input', scheduleSourceTocHighlight);
  document.addEventListener('dragover', (e) => e.preventDefault());
  document.addEventListener('drop', handleImageDrop);
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
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.read_clipboard === 'function') {
        window.pywebview.api.read_clipboard().then(function (clip) {
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
    window.pywebview.api.get_initial_content().then((data) => loadContent(data.path, data.content, data.pageWidth, data.draftRecovered, data.isZh));
  });
