/* 从渲染树提取可读纯文本，不反向输出 Markdown 标记。 */
window.toPlainText = function(rootEl) {
  const codeBlocks = [];
  const walk = (node, depth = 0) => {
    if (node.nodeType === 3) return node.textContent;
    if (node.nodeType !== 1) return '';
    const tag = node.tagName;
    if(node.matches('.task-toggle'))return node.dataset.taskMarker||'';
    if (node.matches('script,style,button,input,.remote-image-bar,.code-lang-label,.frontmatter-toggle,.footnote-backref,.markdown-definitions')) return '';
    if (node.matches('.mermaid-diagram')) return '\n\n[图表]\n\n';
    if (node.matches('.math-inline,.math-block')) {
      const tex = node.getAttribute('data-tex') ?? node.textContent;
      return node.matches('.math-block') ? '\n\n'+tex+'\n\n' : tex;
    }
    if (tag === 'IMG') return '[图片: ' + (node.getAttribute('alt') || '') + ']';
    if (tag === 'BR') return '\n';
    if (tag === 'PRE') {
      const index = codeBlocks.push((node.querySelector('code') || node).textContent.replace(/\n$/,''))-1;
      return '\n\n\u0000code'+index+'\u0000\n\n';
    }
    if (tag === 'UL' || tag === 'OL') {
      const start = Number(node.getAttribute('start') || 1);
      return '\n' + [...node.children].filter(el => el.tagName === 'LI').map((li,index) => {
        const checkbox = li.querySelector(':scope > input[type="checkbox"],:scope > p > input[type="checkbox"]');
        const prefix = checkbox ? (checkbox.checked ? '[x] ' : '[ ] ') : tag === 'OL' ? (start+index)+'. ' : '• ';
        const parts = [...li.childNodes];
        const text = parts.filter(el => !['UL','OL'].includes(el.tagName)).map(el => walk(el,depth+1)).join('').trim();
        const nested = parts.filter(el => ['UL','OL'].includes(el.tagName)).map(el => walk(el,depth+1)).join('');
        return '  '.repeat(depth)+(/^\[[ xX]\]\s/.test(text) ? '' : prefix)+text.replace(/^(\[[ xX]\])\s+/, '$1 ')+'\n'+nested;
      }).join('') + '\n';
    }
    if (tag === 'TR') return [...node.children].map(el=>walk(el,depth).trim()).join('\t')+'\n';
    const text = [...node.childNodes].map(el=>walk(el,depth)).join('');
    if (tag === 'A') {
      const url=node.getAttribute('href') || '';
      return !url || url.startsWith('#') || text.trim()===url ? text : text+' ('+url+')';
    }
    return /^(H[1-6]|P|BLOCKQUOTE|TABLE|SECTION|DIV)$/.test(tag) ? '\n\n'+text+'\n\n' : text;
  };
  return walk(rootEl).replace(/\n{3,}/g,'\n\n').trim().replace(/\u0000code(\d+)\u0000/g, (_, index) => codeBlocks[Number(index)])+'\n';
};
