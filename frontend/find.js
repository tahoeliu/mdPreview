// 文档查找与匹配定位：由入口显式注入依赖。
window.DocumentFind = {
  create(deps) {
    const {
      document, window, scrollTextareaToLine, findRangeBetween, state,
    } = deps;
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
      if (state.isSource) document.getElementById('textarea').focus();
      else document.getElementById('content').focus();
    }

    function getSearchableText() {
      if (state.isSource) return document.getElementById('textarea');
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

      if (state.isSource) {
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
      if (state.isSource) {
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
      if (state.isSource) {
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


    return {
      openFindBar, closeFindBar, getSearchableText, doFind, findInTextarea, scrollToTextareaMatch, 
      clearFindHighlights, findInContentEditable, highlightCurrentMatch, findNext, findPrev, updateFindButtons,
    };
  }
};
