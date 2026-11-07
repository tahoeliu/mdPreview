// Turndown延迟初始化与保真回写规则：由入口显式注入依赖。
window.MarkdownConversion = {
  create(deps) {
    const {
      _loadScript, state,
    } = deps;
    function _initTurndown() {
      if (state.turndownService || typeof deps.TurndownService === 'undefined') return;
      state.turndownService = new deps.TurndownService({ headingStyle: 'atx', codeBlockStyle: 'fenced', bulletListMarker: '-', emDelimiter: '*', strongDelimiter: '**' });
      state.turndownService.remove(node=>node.matches?.('.code-copy-btn,.remote-image-bar'));
      state.turndownService.addRule('taskToggle',{filter:node=>node.matches?.('.task-toggle'),replacement:(_,node)=>node.dataset.taskMarker||''});
      state.turndownService.addRule('frontmatter', {
        filter: function (node) {
          return node.classList && node.classList.contains('frontmatter');
        },
        replacement: function (content, node) {
          const raw = node.getAttribute('data-raw');
          return (raw || node.textContent) + '\n\n';
        }
      });
      state.turndownService.addRule('mermaid', {
        filter: function (node) {
          return node.classList && node.classList.contains('mermaid-diagram');
        },
        replacement: function (content, node) {
          const source = node.getAttribute('data-source') || '';
          return source ? '```mermaid\n' + source.trim() + '\n```' : '';
        }
      });
      state.turndownService.addRule('preservedExtension', {
        filter: (node) => node.hasAttribute && node.hasAttribute('data-raw') && !node.classList.contains('frontmatter'),
        replacement: (content, node) => {
          const raw = node.getAttribute('data-raw') || '';
          return node.classList.contains('math-block') || node.classList.contains('footnotes') || node.classList.contains('markdown-definitions') || node.classList.contains('markdown-alert') ? '\n\n' + raw + '\n\n' : raw;
        }
      });
      state.turndownService.addRule('blockedResource', {
        filter: node => node.hasAttribute && node.hasAttribute('data-resource-raw'),
        replacement: (content,node) => node.getAttribute('data-resource-raw')
      });
      state.turndownService.addRule('relativeImage', {
        filter: 'img',
        replacement: (content, node) => {
          if(node.hasAttribute('data-image-raw'))return node.getAttribute('data-image-raw');
          const src = node.getAttribute('data-remote-src') || node.getAttribute('data-original-src') || node.getAttribute('src') || '';
          const alt = (node.getAttribute('alt') || '').replace(/\]/g, '\\]');
          return src ? '![' + alt + '](' + src.replace(/\)/g, '\\)') + ')' : '';
        }
      });
      state.turndownService.addRule('listItem', {
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
      state.turndownService.addRule('renderCaretSpacer', {
        filter: function (node) {
          return node.nodeType === 1 && node.classList && node.classList.contains('render-caret-spacer');
        },
        replacement: function (content, node) {
          const text = (content || node.textContent || '').trim();
          return text ? '\n\n' + text + '\n\n' : '';
        }
      });
      state.turndownService.addRule('table', {
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
            headerCells.push(escPipe(rows[0].cells[c] ? state.turndownService.turndown(rows[0].cells[c].innerHTML) : ''));
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
              cells.push(escPipe(rows[r2].cells[c3] ? state.turndownService.turndown(rows[r2].cells[c3].innerHTML) : ''));
            }
            lines.push('| ' + cells.join(' | ') + ' |');
          }
          return '\n\n' + lines.join('\n') + '\n\n';
        }
      });
    }

    function ensureTurndown() {
      if (state._turndownLoaded) return Promise.resolve();
      if (typeof deps.TurndownService !== 'undefined') { _initTurndown(); state._turndownLoaded = true; return Promise.resolve(); }
      return _loadScript('vendor/turndown.js').then(() => { _initTurndown(); state._turndownLoaded = true; });
    }


    return {
      _initTurndown, ensureTurndown,
    };
  }
};
