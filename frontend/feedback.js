// 状态提示、编辑提示与界面本地化：由入口显式注入依赖。
window.EditorFeedback = {
  create(deps) {
    const {
      document, window, setTimeout, clearTimeout, t, normalizeCodeLanguage, state,
    } = deps;
    function showStatus(text, isError = false) {
      const el = document.getElementById('status');
      el.textContent = text;
      el.classList.toggle('error', !!isError);
      el.classList.add('visible');
      clearTimeout(state.statusTimer);
      state.statusTimer = setTimeout(() => el.classList.remove('visible'), isError ? 5000 : 1500);
    }

    // ── Non-editable content hint bubble ──
    // The rendered view is contenteditable, but some blocks are marked
    // contenteditable="false" (frontmatter, fenced code blocks, math, Mermaid
    // diagrams, protected blocks). Clicking one of those does nothing visually,
    // so show a short-lived translucent bubble suggesting the Source view.

    function showSizeHint(kind) {
      const bubble = document.getElementById('sizeHintBubble');
      if (!bubble) return;
      const editBubble = document.getElementById('editHintBubble');
      if (editBubble) editBubble.classList.remove('visible');
      clearTimeout(state.editHintTimer);
      let text;
      if (kind === 'width') {
        text = t('Width', '宽度') + ' ' + state.pageWidthPct + '%';
      } else {
        text = t('Font', '字号') + ' ' + state.contentFontSize + 'px';
      }
      bubble.textContent = text;
      bubble.classList.add('visible');
      clearTimeout(state.sizeHintTimer);
      state.sizeHintTimer = setTimeout(() => bubble.classList.remove('visible'), 1000);
    }

    function findNonEditableAncestor(target) {
      const contentEl = document.getElementById('content');
      let el = target && target.nodeType === 1 ? target : (target ? target.parentNode : null);
      if (el && el.isContentEditable) return null; // an editable island (e.g. front matter text) inside a locked block
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

    function getCodeBlockInteractionTarget(event) {
      const contentEl = document.getElementById('content');
      function editableCodeBlockFrom(el) {
        const pre = el && el.closest ? el.closest('pre') : null;
        if (!pre || !contentEl || !contentEl.contains(pre) || pre.classList.contains('frontmatter-body')) return null;
        const code = pre.querySelector('code');
        if (code && normalizeCodeLanguage(code) === 'mermaid') return null;
        return pre;
      }
      const targetEl = event && event.target && event.target.nodeType === 1 ? event.target : (event && event.target ? event.target.parentNode : null);
      const fromTarget = editableCodeBlockFrom(targetEl);
      if (fromTarget) return fromTarget;
      const selection = window.getSelection ? window.getSelection() : null;
      if (!selection || selection.rangeCount === 0) return null;
      const node = selection.anchorNode;
      const el = node && node.nodeType === 1 ? node : (node ? node.parentNode : null);
      return editableCodeBlockFrom(el);
    }

    function getEditableComplexInteractionTarget(event) {
      return getTableInteractionTarget(event) || getCodeBlockInteractionTarget(event);
    }

    function showEditHint(anchor) {
      const bubble = document.getElementById('editHintBubble');
      if (!bubble) return;
      const sizeBubble = document.getElementById('sizeHintBubble');
      if (sizeBubble) sizeBubble.classList.remove('visible');
      clearTimeout(state.sizeHintTimer);
      // ⌘E-first copy: the shortcut is the anchor, the verb follows. Kept as
      // constant strings (no user input) so innerHTML is safe.
      bubble.innerHTML = '<span class="edit-hint-key">⌘E</span><span>' + t('to edit in Source', '使用源码模式编辑') + '</span>';
      bubble.classList.add('visible');
      clearTimeout(state.editHintTimer);
      state.editHintTimer = setTimeout(() => bubble.classList.remove('visible'), 1600);
    }

    function showTableEditHint() {
      const bubble = document.getElementById('editHintBubble');
      if (!bubble) return;
      const sizeBubble = document.getElementById('sizeHintBubble');
      if (sizeBubble) sizeBubble.classList.remove('visible');
      clearTimeout(state.sizeHintTimer);
      bubble.innerHTML = '<span class="edit-hint-copy">Switch to Source mode</span>' +
        '<span class="edit-hint-keys"><span class="edit-hint-key">⌘</span><span class="edit-hint-key">E</span></span>' +
        '<span class="edit-hint-copy">to keep your formatting intact</span>';
      bubble.classList.add('visible');
      clearTimeout(state.editHintTimer);
      state.editHintTimer = setTimeout(() => bubble.classList.remove('visible'), 1800);
    }

    // Apply bilingual text to static UI elements declared in index.html.
    // Called whenever isZh is (re)set, i.e. after each loadContent().
    function applyStaticUiLanguage() {
      const findInput = document.getElementById('findInput');
      if (findInput) { findInput.placeholder = t('Find', '查找'); findInput.setAttribute('aria-label',t('Find', '查找')); }
      document.getElementById('findCount').setAttribute('role','status');
      document.getElementById('tocSidebar').setAttribute('aria-label',t('Document outline','文档目录'));
      document.getElementById('content').setAttribute('aria-label',t('Markdown document','Markdown 文档'));
      document.getElementById('textarea').setAttribute('aria-label',t('Markdown source','Markdown 源码'));
      const replaceInput=document.getElementById('replaceInput');
      if(replaceInput){replaceInput.placeholder=t('Replace with','替换为');replaceInput.setAttribute('aria-label',replaceInput.placeholder);}
      document.querySelectorAll('.replace-action').forEach(button=>{button.textContent=button.dataset.replaceAll==='true'?t('Replace all','全部替换'):t('Replace','替换');});
      const findPrev = document.getElementById('findPrev');
      if (findPrev) findPrev.title = t('Previous (Shift+Cmd+G)', '上一个 (Shift+Cmd+G)');
      const findNext = document.getElementById('findNext');
      if (findNext) findNext.title = t('Next (Cmd+G)', '下一个 (Cmd+G)');
      const findClose = document.getElementById('findClose');
      if (findClose) findClose.title = t('Close (Esc)', '关闭 (Esc)');
      [findPrev,findNext,findClose].forEach(button=>{if(button)button.setAttribute('aria-label',button.title);});
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


    return {
      showStatus, showSizeHint, findNonEditableAncestor, getTableInteractionTarget, 
      getCodeBlockInteractionTarget, getEditableComplexInteractionTarget, showEditHint, showTableEditHint, 
      applyStaticUiLanguage,
    };
  }
};
