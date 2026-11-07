// 源码和代码块着色：由入口显式注入依赖。
window.SyntaxHighlight = {
  create(deps) {
    const {
      document, escHtml,
    } = deps;
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

        // `text` blocks: keep the source as plain, uncolored text and render no
        // language badge.
        if (language === 'text') {
          code.classList.add('syntax-lang-text');
          return;
        }

        code.classList.add('syntax-highlighted');
        if (language) code.classList.add('syntax-lang-' + language);
        if (source.length > CODE_HIGHLIGHT_MAX_CHARS) {
          code.classList.add('syntax-highlight-skipped');
          return;
        }
        code.innerHTML = highlightCodeByLanguage(source, language);

        // Non-selectable language badge in the top-right corner of the gray
        // background. It must never be captured by a text selection / copy of the
        // code, so it is marked user-select:none and contenteditable=false.
        const pre = code.parentElement;
        if (language && pre && pre.tagName === 'PRE' && !pre.querySelector('.code-lang-label')) {
          const label = document.createElement('span');
          label.className = 'code-lang-label';
          label.textContent = language;
          label.setAttribute('contenteditable', 'false');
          label.setAttribute('aria-hidden', 'true');
          pre.appendChild(label);
        }
      });
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
      // Single-underscore italic (_like this_). Runs after the bold rule so __
      // pairs are already wrapped in spans. The [^\w_] guard keeps intraword
      // underscores (snake_case_words) from matching — matching CommonMark,
      // which does not emphasize inside words with _.
      h = h.replace(/(^|[^\w_])_([^_\s][^_]*?)_(?!\w)/g, '$1<span class="syn-italic">_</span>$2<span class="syn-italic">_</span>');
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


    return {
      spanTok, normalizeCodeLanguage, readQuoted, highlightJsonCode, highlightCStyleCode, highlightPythonCode, 
      highlightShellCode, highlightYamlValue, highlightYamlCode, highlightHtmlTag, highlightHtmlCode, 
      highlightCssCode, highlightSqlCode, highlightGenericCode, highlightCodeByLanguage, 
      highlightRenderedCodeBlocks, renderFrontmatter, resolveBlockScalar, highlightInlineMarkdown, 
      highlightMarkdown,
    };
  }
};
