// 文档渲染调度、DOM装饰与光标落点：由入口显式注入依赖。
window.MarkdownRendering = {
  create(deps) {
    const {
      document, window, Node, clearTimeout, t, preprocessMarkdownExtensions, renderFrontmatter, 
      renderMathPlaceholders, renderFootnotes, applyHeadingAnchors, highlightRenderedCodeBlocks, 
      balanceTableColumns, buildToc, hasRenderableMermaid, renderMermaidDiagrams, state,
    } = deps;
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
        fmDiv.innerHTML = '<button class="frontmatter-toggle">' + t('Collapse', '折叠') + '</button>' + renderFrontmatter(frontmatter);
        fragment.appendChild(fmDiv);
      }

      const bodyDiv = document.createElement('div');
      const html = deps.RenderPerformance.sync('parse',()=>deps.MarkdownPipeline.parse(body));
      deps.RenderPerformance.sync('dom',()=>{bodyDiv.innerHTML = html;});
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
      deps.RenderPerformance.sync('highlight',()=>highlightRenderedCodeBlocks(container));
      protectComplexBlocks(container);
      balanceTableColumns(container);
      ensureBlockCaretLandingZones(container, content);
      state.lastRenderedHash = content;
    }

    function ensureBlockCaretLandingZones(container, source) {
      container.querySelectorAll('.render-caret-spacer').forEach((node) => node.remove());
      const blockSelector = '.table-wrap, table, pre, blockquote, ul, ol, .mermaid-diagram, .math-block, .frontmatter';
      const blocks = Array.from(container.querySelectorAll(blockSelector));
      for (const block of blocks) {
        if (!block.parentNode || block.closest('.table-wrap table')) continue;
        let next = block.nextSibling;
        while (next && next.nodeType === Node.TEXT_NODE && !next.textContent.trim()) next = next.nextSibling;
        const hasEditableLanding = next && next.nodeType === Node.ELEMENT_NODE && !next.matches(blockSelector);
        if (hasEditableLanding) continue;
        block.parentNode.insertBefore(createRenderCaretSpacer(), block.nextSibling);
      }
      if (/\n\s*$/.test(String(source || ''))) {
        const last = container.lastElementChild;
        if (!last || !last.classList.contains('render-caret-spacer')) container.appendChild(createRenderCaretSpacer());
      }
    }

    function createRenderCaretSpacer() {
      const p = document.createElement('p');
      p.className = 'render-caret-spacer';
      p.setAttribute('data-render-only', 'true');
      p.innerHTML = '<br>';
      return p;
    }

    function placeCaretInRenderSpacer(spacer) {
      if (!spacer) return false;
      const sel = window.getSelection();
      if (!sel) return false;
      const range = document.createRange();
      range.selectNodeContents(spacer);
      range.collapse(false);
      sel.removeAllRanges();
      sel.addRange(range);
      const content = document.getElementById('content');
      try { content.focus({ preventScroll: true }); } catch (e) { content.focus(); }
      return true;
    }

    function placeCaretAtSafeRenderedLanding(content) {
      const spacers = content ? content.querySelectorAll('.render-caret-spacer') : [];
      if (spacers && spacers.length && placeCaretInRenderSpacer(spacers[spacers.length - 1])) return true;
      const sel = window.getSelection();
      if (!sel || !content) return false;
      const range = document.createRange();
      range.selectNodeContents(content);
      range.collapse(false);
      sel.removeAllRanges();
      sel.addRange(range);
      try { content.focus({ preventScroll: true }); } catch (e) { content.focus(); }
      return true;
    }

    function documentLanguage(text) {
      const front = String(text).match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/);
      const declared = front && front[1].match(/^lang:\s*["']?([a-zA-Z]{2,8}(?:-[a-zA-Z0-9]{1,8})*)["']?\s*$/m);
      return declared ? declared[1] : ((String(text).match(/[㐀-鿿]/g) || []).length / Math.max(1,text.length) > 0.1 ? 'zh-CN' : 'en');
    }

    async function renderMarkdown(content, container) {
      document.documentElement.lang = documentLanguage(content);
      const jobId = ++state.renderJobId;
      clearTimeout(state.deferredRenderTimer);
      // A complete token stream is required for fences, references and footnotes.
      // No delayed full-document replacement is allowed to overwrite user input.
      deps.LazyRender.reset();
      const endRender = deps.RenderPerformance.start('render');
      deps.RenderPerformance.sync('parse-dom',()=>appendParsedMarkdown(content, container, { keepExisting: false }));
      deps.RenderPerformance.sync('finalize',()=>finalizeRenderedMarkdown(container, content));
      deps.RenderPerformance.sync('toc',()=>buildToc(container));
      deps.RenderPerformance.sync('reading',()=>deps.ReadingFeatures.decorate(container,content));
      await deps.MathRenderer.renderMath(container,{eager:false});
      endRender();
      if (jobId !== state.renderJobId || state.closing) return;
      if (hasRenderableMermaid(container)) {
        await deps.LazyRender.observe(container.querySelectorAll('code.language-mermaid'),node=>deps.RenderPerformance.async('mermaid',()=>renderMermaidDiagrams(node)));
        if (jobId !== state.renderJobId || state.closing) return;
        protectComplexBlocks(container);
        balanceTableColumns(container);
      }
    }

    function toggleFrontmatter(btn) {
      const box = btn.closest('.frontmatter');
      if (!box) return;
      const collapsed = box.classList.toggle('collapsed');
      btn.textContent = collapsed ? t('Expand', '展开') : t('Collapse', '折叠');
    }

    function rewriteRelativeImages(container) {
      if (!state.filePath || state.filePath === 'Untitled.md') return;
      const base = state.filePath.split('/').slice(0, -1).join('/');
      container.querySelectorAll('img[src]').forEach((img) => {
        const src = img.getAttribute('src') || '';
        if (/^(https?:|file:|data:|\/)/i.test(src)) return;
        img.src = 'file://' + base + '/' + src.replace(/^\.\//, '');
        img.setAttribute('data-original-src', src);
      });
    }


    function protectComplexBlocks(container) {
      container.querySelectorAll('.frontmatter, .mermaid-diagram').forEach((node) => {
        node.setAttribute('contenteditable', 'false');
      });
      container.querySelectorAll('div, section, article').forEach((node) => {
        if (node.querySelector('.frontmatter, .mermaid-diagram')) return;
        const hasMarkdownClass = node.classList.contains('frontmatter') || node.classList.contains('mermaid-diagram');
        if (hasMarkdownClass) node.setAttribute('contenteditable', 'false');
      });
    }


    return {
      appendParsedMarkdown, finalizeRenderedMarkdown, ensureBlockCaretLandingZones, createRenderCaretSpacer, 
      placeCaretInRenderSpacer, placeCaretAtSafeRenderedLanding, documentLanguage, renderMarkdown, 
      toggleFrontmatter, rewriteRelativeImages, protectComplexBlocks,
    };
  }
};
