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
  function clean(html, svg = false, allowFile = false, math = false) {
    // template 内容不激活资源；在任何可加载的 DOM 节点创建前移除远程图片地址。
    const inert = document.createElement('template');
    inert.innerHTML = String(html || '');
    // 不支持的自动加载入口整体替换为惰性文本占位；原HTML仅存于data属性供回写。
    for (const element of inert.content.querySelectorAll('video,audio,source,track,object,embed,iframe,[poster],[background],svg image,svg use')) {
      if (!inert.content.contains(element)) continue;
      const placeholder = document.createElement('span');
      placeholder.setAttribute('data-resource-raw', element.outerHTML);
      placeholder.setAttribute('contenteditable', 'false');
      placeholder.textContent = '[不支持的外部资源已禁用]';
      element.replaceWith(placeholder);
    }
    if (!allowFile) for (const img of inert.content.querySelectorAll('img')) {
      const src=img.getAttribute('src')||'', srcset=img.getAttribute('srcset');
      if (/^(?:https?:|\/\/)/i.test(src.replace(/[\u0000-\u0020\u007f-\u009f]/g,'')) || srcset) {
        if (!img.hasAttribute('data-image-raw') && !img.hasAttribute('data-md-image')) img.setAttribute('data-image-raw',img.outerHTML);
        if (src) img.setAttribute('data-remote-src',src);
        if (srcset) img.setAttribute('data-remote-srcset',srcset);
        img.removeAttribute('src');img.removeAttribute('srcset');
      }
    }
    const fragment = purifier.sanitize(inert.innerHTML, {
      USE_PROFILES: svg ? { svg: true, svgFilters: true, html: true, mathMl: math } : { html: true },
      FORBID_TAGS: ['script', 'iframe', 'object', 'embed', 'form', 'input', 'button', 'select', 'textarea', 'link', 'meta', 'base', ...(svg ? [] : ['style'])],
      FORBID_ATTR: ['srcset', 'poster', 'background', 'formaction', ...(svg ? [] : ['style'])],
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
      name: 'blockMath', level: 'block', start: (src) => src.search(/\$\$|\\\[/),
      tokenizer(src) {
        const match = /^(?:\$\$[ \t]*\n?([\s\S]*?)\$\$|\\\[([\s\S]+?)\\\])(?:[ \t]*\n|$)/.exec(src);
        if (match) match[1] = match[1] === undefined ? match[2] : match[1];
        if (match) return { type: 'blockMath', raw: match[0], text: match[1].trim() };
      },
      renderer(token) { return '<div class="math-block" contenteditable="false" data-raw="' + escape(token.raw.trimEnd()) + '">' + escape(token.text) + '</div>\n'; }
    },
    {
      name: 'inlineMath', level: 'inline', start: (src) => src.search(/\$|\\\(/),
      tokenizer(src) {
        const match = /^(?:\$(?!\$|\s)([^$\n]*?\S)\$(?!\d)|\\\(([^\n]+?)\\\))/.exec(src);
        if (match) match[1] = match[1] === undefined ? match[2] : match[1];
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
  // marked 12 的 walkTokens 在循环里反复 values = values.concat(...)，复杂度是 O(n²)：
  // 800KB 文档仅此一项就要约 17 秒。这里提供语义相同的线性实现：同样的遍历顺序，
  // 且回调之后才按（可能已被回调改写的）token.type 决定如何深入子节点。
  function linearWalkTokens(tokens, callback) {
    const values = [];
    const childTokens = this.defaults && this.defaults.extensions && this.defaults.extensions.childTokens;
    const record = (result) => {
      if (Array.isArray(result)) { for (const item of result) values.push(item); }
      else values.push(result); // 与 Array#concat 一致：非数组（含 undefined）按一个元素追加
    };
    const visit = (list) => {
      for (const token of list) {
        record(callback.call(this, token));
        if (token.type === 'table') {
          for (const cell of token.header) visit(cell.tokens);
          for (const row of token.rows) for (const cell of row) visit(cell.tokens);
        } else if (token.type === 'list') {
          visit(token.items);
        } else if (childTokens && childTokens[token.type]) {
          childTokens[token.type].forEach((name) => visit(token[name].flat(Infinity)));
        } else if (token.tokens) {
          visit(token.tokens);
        }
      }
    };
    visit(tokens);
    return values;
  }
  // marked-footnote 的块级 start 对每个段落扫描整篇剩余文本，大文档下是二次复杂度；
  // 文档里根本没有 [^标签] 语法时就不注册它（结果完全相同，只是省掉这部分开销）。
  const footnoteSyntax = /\[\^[^\]\n]+\]/;
  function createParser(definitions = [], source = '') {
    // A fresh extension state per document prevents cross-document footnote leakage.
    const parser = new marked.Marked({ breaks: true, gfm: true },
      ...(footnoteSyntax.test(source) ? [markedFootnote({ refMarkers: true, keepLabels: true, prefixId: 'fn-' })] : []),
      { renderer: { checkbox(checked) { return checked ? '[x] ' : '[ ] '; },
          listitem(text,task){return '<li'+(task?' data-task="true"':'')+'>'+text+'</li>\n';},
          image(href,title,text){return '<img src="'+escape(href)+'" alt="'+escape(text)+'"'+(title?' title="'+escape(title)+'"':'')+' data-md-image="true">';} },
        tokenizer: { emStrong: cjkEmStrong }, extensions: [...mathExtensions, {
          name:'alert',level:'block',renderer(token){return '<div class="markdown-alert markdown-alert-'+token.kind.toLowerCase()+'" contenteditable="false" data-raw="'+escape(token.raw.trimEnd())+'"><p class="markdown-alert-title"><span aria-hidden="true">!</span> '+token.kind+'</p>'+this.parser.parse(token.tokens)+'</div>';}
        }], walkTokens(token) {
        if(token.type==='blockquote'){
          const match=/^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ \t]*(?:\n|$)/.exec(token.text);
          if(match){token.type='alert';token.kind=match[1];token.tokens=createParser([],token.text).lexer(token.text.slice(match[0].length));}
        }
        if (token.type === 'footnote') definitions.push(token.raw.trimEnd());
        if (token.type === 'html') {
          const original=document.createElement('template');original.innerHTML=token.text;
          original.content.querySelectorAll('*').forEach(el=>{for(const attr of [...el.attributes])if(attr.name.startsWith('data-'))el.removeAttribute(attr.name);});
          const holder = document.createElement('div'); holder.innerHTML = clean(original.innerHTML);
          holder.querySelectorAll('*').forEach(element => {
            ['frontmatter','mermaid-diagram','footnotes','math-inline','math-block','render-caret-spacer','markdown-definitions','markdown-alert','remote-image-bar','task-toggle','code-copy-btn'].forEach(name => element.classList.remove(name));
            for (const attr of Array.from(element.attributes)) {
              if ((attr.name.startsWith('data-') && !['data-remote-src','data-remote-srcset','data-image-raw','data-resource-raw'].includes(attr.name)) || attr.name === 'contenteditable') element.removeAttribute(attr.name);
            }
          });
          token.text = holder.innerHTML;
        }
      }});
    parser.walkTokens = linearWalkTokens;
    return parser;
  }
  function lex(markdown) { return createParser([], markdown).lexer(markdown); }
  function parse(markdown) {
    const definitions = [];
    const parser = createParser(definitions, markdown);
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
  function cleanMath(html) {
    const fragment = purifier.sanitize(String(html), {
      ALLOWED_TAGS: ['span','math','semantics','mrow','mi','mo','mn','msup','msub','msubsup','mfrac','msqrt','mroot','mtable','mtr','mtd','mtext','mspace','annotation','mstyle','mover','munder','munderover','mpadded','mphantom','menclose','svg','path','line','g'],
      ALLOWED_ATTR: ['style','class','aria-hidden','encoding','xmlns','display','mathvariant','stretchy','fence','separator','accent','accentunder','columnalign','columnspacing','rowspacing','width','height','depth','viewBox','preserveAspectRatio','d','fill','stroke','stroke-width','x1','x2','y1','y2'],
      ALLOW_DATA_ATTR: false, RETURN_DOM_FRAGMENT: true
    });
    const properties = /^(?:color|background-color|position|display|top|bottom|left|right|width|height|min-width|font-size|font-family|font-style|font-weight|line-height|vertical-align|text-align|white-space|margin(?:-(?:left|right|top|bottom))?|padding(?:-(?:left|right|top|bottom))?|border(?:-(?:left|right|top|bottom))?(?:-(?:width|style|color))?|transform|transform-origin)$/;
    for (const el of fragment.querySelectorAll('*')) {
      for (const attr of [...el.attributes]) {
        if (/href|src|^on/i.test(attr.name) || /url\s*\(|expression|@import|\\/i.test(attr.value)) el.removeAttribute(attr.name);
      }
      if (el.style) for (const name of Array.from(el.style)) if (!properties.test(name)) el.style.removeProperty(name);
    }
    const holder = document.createElement('div'); holder.append(fragment); return holder.innerHTML;
  }
  window.MarkdownPipeline = { parse, lex, linearWalkTokens, cleanMath, cleanHTML: (html, allowFile = false) => clean(html, false, allowFile), cleanSVG: (svg) => clean(svg, true), cleanExport: (html) => clean(html, true, true, true), safeURL };
})();
