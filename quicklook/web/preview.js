/* Finder 空格预览的渲染入口：与主应用使用同一条净化管线，不联网，不渲染 Mermaid。 */
window.renderMarkdownPreview = function (text) {
  const container = document.getElementById('content');
  const front = /^\s*---\r?\n([\s\S]*?)\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|$)/.exec(text);
  const body = front ? text.slice(front[0].length) : text;
  container.textContent = '';
  if (front) {
    const block = document.createElement('pre');
    block.className = 'frontmatter';
    block.textContent = front[1];
    container.appendChild(block);
  }
  const holder = document.createElement('div');
  holder.innerHTML = MarkdownPipeline.parse(body);
  container.appendChild(holder);
  // 预览里没有网络：把不是 data: 的图片换成带 alt 文字的占位，避免满屏破图。
  let blocked = 0;
  for (const image of container.querySelectorAll('img')) {
    const source = image.getAttribute('src') || '';
    if (/^data:image\//i.test(source)) continue;
    const placeholder = document.createElement('span');
    placeholder.className = 'blocked-image';
    placeholder.textContent = image.getAttribute('alt') || '[image]';
    image.replaceWith(placeholder);
    blocked++;
  }
  // 链接保留外观，但预览里不能跳转。
  for (const link of container.querySelectorAll('a[href]')) link.setAttribute('role', 'link');
  let formulas = 0;
  if (window.katex) {
    for (const node of container.querySelectorAll('.math-inline, .math-block')) {
      try {
        const html = katex.renderToString(node.textContent, { displayMode: node.classList.contains('math-block'), throwOnError: false, output: 'htmlAndMathml', trust: false, strict: 'ignore' });
        node.innerHTML = MarkdownPipeline.cleanMath(html);
        node.setAttribute('data-rendered', '1');
        formulas++;
      } catch (error) { /* 保留源码样式 */ }
    }
  }
  return {
    elements: container.querySelectorAll('*').length,
    headings: container.querySelectorAll('h1,h2,h3,h4,h5,h6').length,
    formulas: formulas,
    blocked_images: blocked,
  };
};
