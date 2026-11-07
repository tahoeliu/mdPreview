/* KaTeX 输出只经过独立数学白名单；原文始终保留在 data-raw。 */
window.MathRenderer = (() => {
  let loading;
  async function ready() {
    if (!loading) loading = (async () => {
      let css = document.querySelector('link[data-katex]');
      if (!css) {
        css = document.createElement('link'); css.rel = 'stylesheet';
        css.href = 'vendor/katex/katex.min.css'; css.dataset.katex = 'true';
        const loaded = new Promise((resolve,reject) => {
          css.onload=resolve;
          css.onerror=()=>{ css.remove(); reject(new Error('katex-css-load-failed')); };
        });
        document.head.append(css); await loaded;
      }
      await ensureLib('vendor/katex/katex.min.js','katex');
    })().catch(error => { loading = null; throw error; });
    return loading;
  }
  async function renderMath(root, {eager = true} = {}) {
    const selector = '.math-inline:not([data-rendered]),.math-block:not([data-rendered])';
    const nodes = root.matches?.(selector) ? [root] : [...root.querySelectorAll(selector)];
    if (!eager) return LazyRender.observe(nodes, node=>RenderPerformance.async('math',()=>renderMath(node)));
    if (!nodes.length) return;
    const wasConnected = root.isConnected;
    await ready();
    for (const el of nodes) {
      if ((wasConnected && !root.isConnected) || !root.contains(el) || el.dataset.rendered) continue;
      const tex = el.dataset.tex || el.textContent;
      el.dataset.tex = tex;
      const html = katex.renderToString(tex,{displayMode:el.classList.contains('math-block'),throwOnError:false,output:'htmlAndMathml',trust:false,strict:'ignore',maxExpand:1000,maxSize:50});
      el.innerHTML = MarkdownPipeline.cleanMath(html);
      el.dataset.rendered = '1';
      el.classList.add('math-rendered');
      el.classList.toggle('math-error',!!el.querySelector('.katex-error'));
      el.title = el.dataset.raw || tex;
    }
  }
  async function exportCSS(root) {
    if (!root.querySelector('.katex')) return '';
    const families = new Set(['KaTeX_Main']);
    const mounted = root.isConnected;
    const holder = document.createElement('div');
    if (!mounted) { holder.style.cssText='position:absolute;left:-100000px;visibility:hidden'; holder.append(root); document.body.append(holder); }
    try {
      root.querySelectorAll('.katex,.katex *').forEach(el => { if(el.namespaceURI==='http://www.w3.org/1998/Math/MathML')return; (getComputedStyle(el).fontFamily||el.style.fontFamily||'').split(',').forEach(f => { f=f.trim().replace(/["']/g,''); if (/^KaTeX_(?:[A-Za-z]+|Size[1-4])$/.test(f)) families.add(f); }); });
      return await Bridge.call('get_math_export_css',[...families]);
    } finally { if (!mounted) { root.remove(); holder.remove(); } }
  }
  return {renderMath,exportCSS};
})();
