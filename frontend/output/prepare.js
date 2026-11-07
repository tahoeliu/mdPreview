/* 输出生命周期：保存界面状态，失败时也按逆序恢复。 */
window.OutputPrep = (() => {
  let hooks, busy = false;
  return {
    configure(value) { hooks = value; },
    async prepare(kind, opts = {}) {
      if (busy) throw new Error('output-busy');
      busy = true;
      const undo = [], root = document.documentElement;
      let restored = false;
      const restore = () => {
        if (restored) return;
        restored = true;
        try { for (const fn of undo.reverse()) fn(); } finally { busy = false; }
      };
      const style = (el, key, value) => {
        if (!el) return;
        const old = el.style.getPropertyValue(key), priority = el.style.getPropertyPriority(key);
        undo.push(() => old ? el.style.setProperty(key, old, priority) : el.style.removeProperty(key));
        el.style.setProperty(key, value, 'important');
      };
      const cls = (el, name, present) => {
        const previous = el.classList.contains(name);
        undo.push(() => el.classList.toggle(name, previous));
        el.classList.toggle(name, present);
      };
      try {
        const sw = document.querySelector('.scroll-wrap');
        const scroll = sw ? [sw.scrollLeft, sw.scrollTop] : null;
        if (scroll) undo.push(() => sw.scrollTo(...scroll));
        if (hooks.isSource()) { undo.push(hooks.restoreSource); await hooks.showPreview(); }
        await ReadingFeatures.beforeOutput(kind);
        const old = root.getAttribute('data-output');
        undo.push(() => { if (old === null) root.removeAttribute('data-output'); else root.setAttribute('data-output', old); hooks.resetTheme(); });
        root.dataset.output = kind;
        const diagrams = [...document.querySelectorAll('.mermaid-diagram')].map(el => [el, el.innerHTML]);
        undo.push(() => diagrams.forEach(([el, html]) => { el.innerHTML = html; }));
        await hooks.renderLight();
        cls(document.body, 'has-toc', false);
        for (const el of document.body.children) {
          if (el !== sw && !['SCRIPT', 'STYLE', 'LINK'].includes(el.tagName)) style(el, 'display', 'none');
        }
        document.querySelectorAll('.toc-sidebar').forEach(el => style(el, 'display', 'none'));
        for (const [key, name] of [['show_urls','print-show-urls'],['hide_frontmatter','print-hide-frontmatter'],['h1_new_page','print-h1-new-page']]) cls(root,name,!!opts[key]);
        document.querySelectorAll('.markdown pre').forEach(el => cls(el,'print-short',el.textContent.replace(/\n$/,'').split('\n').length <= 25));
        style(root,'--print-font-size',{small:'9.5pt',normal:'10.75pt',large:'12pt'}[opts.font] || '10.75pt');
        if (['pdf','png'].includes(kind)) {
          style(document.body,'height','auto'); style(document.body,'overflow','visible');
          style(sw,'position','static'); style(sw,'height','auto'); style(sw,'overflow','visible');
        }
        if (kind === 'png' && opts.png_width === 'mobile') {
          const page = document.querySelector('.page');
          style(page,'width','540px'); style(page,'max-width','540px'); style(page,'box-sizing','border-box');
        }
        await Promise.all([...document.images].map(image => image.decode ? image.decode().catch(() => {}) : Promise.resolve()));
        if (document.fonts) await document.fonts.ready;
        await new Promise(resolve => {
          let frame, done = false;
          const finish = () => { if (done) return; done = true; clearTimeout(timer); cancelAnimationFrame(frame); void document.body.offsetHeight; resolve(); };
          // 被遮挡的 WKWebView 可能暂停动画帧；布局就绪不应无限阻塞原生输出。
          const timer = setTimeout(finish, 500);
          frame = requestAnimationFrame(() => { frame = requestAnimationFrame(finish); });
        });
        return restore;
      } catch (error) { restore(); throw error; }
    }
  };
})();
