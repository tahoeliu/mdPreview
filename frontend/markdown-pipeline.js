/* Token-aware Markdown extensions and fail-closed HTML/SVG boundaries. */
(function () {
  const escape = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const purifier = window.DOMPurify;
  const reservedIds = new Set([...document.querySelectorAll('[id]')].map(element => element.id));
  ['draftDiscard','draftDismiss','welcomeOverlay','closeCancel','closeDiscard','closeSave','conflictCancel','conflictSaveAs','conflictOverwrite'].forEach(id => reservedIds.add(id));
  if (!purifier || !window.marked || !window.markedFootnote) throw new Error('Required offline renderer missing');
  function safeURL(value, image = false, allowFile = false) {
    const normalized = String(value || '').replace(/[\u0000-\u0020\u007f-\u009f]/g, '');
    if (image && /^data:image\/(?:png|jpeg|gif|webp|avif);base64,[a-z0-9+/=]+$/i.test(normalized)) return true;
    if (allowFile && /^file:\/\//i.test(normalized)) return image;
    if (/^[a-z][a-z0-9+.-]*:/i.test(normalized)) return /^(https?:|mailto:|tel:)/i.test(normalized);
    return !normalized.startsWith('//');
  }
  function clean(html, svg = false, allowFile = false) {
    const fragment = purifier.sanitize(String(html || ''), {
      USE_PROFILES: svg ? { svg: true, svgFilters: true, html: true } : { html: true },
      FORBID_TAGS: ['script', 'iframe', 'object', 'embed', 'form', 'input', 'button', 'select', 'textarea', 'link', 'meta', 'base', ...(svg ? [] : ['style'])],
      FORBID_ATTR: ['srcset', 'formaction', ...(svg ? [] : ['style'])],
      ADD_ATTR: ['contenteditable'], RETURN_DOM_FRAGMENT: true,
      ...(allowFile ? { ADD_URI_SAFE_ATTR: ['src'] } : {})
    });
    for (const element of fragment.querySelectorAll('*')) {
      if (reservedIds.has(element.id)) element.removeAttribute('id');
      element.removeAttribute('name');
      for (const attr of Array.from(element.attributes)) {
        if (attr.name.toLowerCase().startsWith('on')) element.removeAttribute(attr.name);
        if (['href', 'src', 'xlink:href', 'poster'].includes(attr.name.toLowerCase()) &&
            !safeURL(attr.value, element.tagName.toLowerCase() === 'img', allowFile)) element.removeAttribute(attr.name);
      }
    }
    const holder = document.createElement('div'); holder.appendChild(fragment);
    return holder.innerHTML;
  }
  const mathExtensions = [
    {
      name: 'blockMath', level: 'block', start: (src) => src.indexOf('$$'),
      tokenizer(src) {
        const match = /^\$\$[ \t]*\n?([\s\S]*?)\$\$(?:[ \t]*\n|$)/.exec(src);
        if (match) return { type: 'blockMath', raw: match[0], text: match[1].trim() };
      },
      renderer(token) { return '<div class="math-block" contenteditable="false" data-raw="' + escape(token.raw.trimEnd()) + '">' + escape(token.text) + '</div>\n'; }
    },
    {
      name: 'inlineMath', level: 'inline', start: (src) => src.indexOf('$'),
      tokenizer(src) {
        const match = /^\$(?!\$|\s)([^$\n]*?\S)\$(?!\d)/.exec(src);
        if (match) return { type: 'inlineMath', raw: match[0], text: match[1] };
      },
      renderer(token) { return '<span class="math-inline" contenteditable="false" data-raw="' + escape(token.raw) + '">' + escape(token.text) + '</span>'; }
    }
  ];
  // Relax only punctuation + an exact ** closer + Han text. Keep the
  // original source and Marked's delimiter balancing, escaping and code/link
  // masking; never insert whitespace into documents or patch vendor code.
  const cjkStrongBoundary = /([\p{P}])\*\*(?!\*)(?=\p{Script=Han})/gu;
  function cjkEmStrong(src, maskedSrc, prevChar) {
    if (!src.startsWith('**') || src[2] === '*') return false;
    // maskedSrc may include already-consumed text. Align it before scanning.
    // * and _ stay punctuation-classified so triple/mixed runs are untouched.
    const aligned = maskedSrc.slice(-src.length);
    const masked = aligned.replace(cjkStrongBoundary, (run, punctuation) =>
      punctuation === '*' || punctuation === '_' ? run : 'a'.repeat(punctuation.length) + run.slice(punctuation.length));
    if (masked === aligned) return false;
    return marked.Tokenizer.prototype.emStrong.call(this, src, masked, prevChar) || false;
  }
  function parse(markdown) {
    const definitions = [];
    // A fresh extension state per document prevents cross-document footnote leakage.
    const parser = new marked.Marked({ breaks: true, gfm: true },
      markedFootnote({ refMarkers: true, keepLabels: true, prefixId: 'fn-' }),
      { tokenizer: { emStrong: cjkEmStrong }, extensions: mathExtensions, walkTokens(token) {
        if (token.type === 'footnote') definitions.push(token.raw.trimEnd());
        if (token.type === 'html') {
          const holder = document.createElement('div'); holder.innerHTML = clean(token.text);
          holder.querySelectorAll('*').forEach(element => {
            ['frontmatter','mermaid-diagram','footnotes','math-inline','math-block','render-caret-spacer','markdown-definitions'].forEach(name => element.classList.remove(name));
            for (const attr of Array.from(element.attributes)) {
              if (attr.name.startsWith('data-') || attr.name === 'contenteditable') element.removeAttribute(attr.name);
            }
          });
          token.text = holder.innerHTML;
        }
      }});
    const html = clean(parser.parse(markdown));
    const root = document.createElement('div'); root.innerHTML = html;
    root.querySelectorAll('sup:has(a[data-fn-ref])').forEach((sup) => {
      const anchor = sup.querySelector('a');
      const label = decodeURIComponent(anchor.getAttribute('href').replace(/^#fn-/, ''));
      sup.setAttribute('data-raw', '[^' + label + ']');
    });
    const section = root.querySelector('.footnotes');
    if (section) { section.setAttribute('data-raw', definitions.join('\n\n')); section.setAttribute('contenteditable', 'false'); }
    else if (definitions.length) {
      const preserved = document.createElement('div'); preserved.className = 'markdown-definitions';
      preserved.hidden = true; preserved.setAttribute('contenteditable','false');
      preserved.setAttribute('data-raw',definitions.join('\n\n'));
      preserved.textContent = definitions.join('\n\n'); root.appendChild(preserved);
    }
    return root.innerHTML;
  }
  window.MarkdownPipeline = { parse, cleanHTML: (html, allowFile = false) => clean(html, false, allowFile), cleanSVG: (svg) => clean(svg, true), cleanExport: (html) => clean(html, true, true), safeURL };
})();
