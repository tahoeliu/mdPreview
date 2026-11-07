/* 在浅色原布局中读取样式，选区边界的祖先样式也保留。 */
window.buildRichText = async function(root, selectionRange) {
  const holder=document.createElement('div');holder.className='markdown';holder.style.cssText='position:absolute;left:-100000px;top:0;width:'+root.getBoundingClientRect().width+'px;visibility:hidden';
  let wrapper=holder;
  if(selectionRange) {
    selectionRange=selectionRange.cloneRange();
    // 公式和图表不可编辑；部分选中时复制完整节点，避免截断渲染结构。
    const atomic=node=>(node.nodeType===1?node:node.parentElement)?.closest('.math-inline,.math-block,.mermaid-diagram');
    const start=atomic(selectionRange.startContainer),end=atomic(selectionRange.endContainer);
    if(start&&root.contains(start))selectionRange.setStartBefore(start);
    if(end&&root.contains(end))selectionRange.setEndAfter(end);
    let ancestor=selectionRange.commonAncestorContainer;
    if(ancestor.nodeType!==1)ancestor=ancestor.parentElement;
    const chain=[];while(ancestor&&ancestor!==root){chain.unshift(ancestor);ancestor=ancestor.parentElement;}
    for(const source of chain){const copy=source.cloneNode(false);wrapper.append(copy);wrapper=copy;}
    wrapper.append(selectionRange.cloneContents());
  }else holder.innerHTML=root.innerHTML;
  root.append(holder);
  try {
    const plain=toPlainText(holder);
    holder.querySelectorAll('.task-toggle').forEach(el=>el.replaceWith(document.createTextNode(el.dataset.taskMarker||'')));
    holder.querySelectorAll('.remote-image-bar,.code-copy-btn').forEach(el=>el.remove());
    for(const el of [...holder.querySelectorAll('.mermaid-diagram,.math-inline,.math-block')]) {
      const pic=await OutputRaster.node(el);const image=document.createElement('img');image.src=pic.data;image.width=pic.width;image.height=pic.height;image.alt=el.dataset.tex||'图表';el.replaceWith(image);
    }
    for(const image of holder.querySelectorAll('img[data-original-src]')){
      const response=await Bridge.call('read_image_for_export',image.dataset.originalSrc,documentSession.id);
      if(!response.success)throw new Error('clipboard-image-failed');image.src=response.data;
    }
    const properties=['color','background-color','font-size','font-weight','font-style','font-family','line-height','text-decoration','border-collapse','text-align','white-space','list-style-type','vertical-align'];
    for(const side of ['top','right','bottom','left']){properties.push('margin-'+side,'padding-'+side);for(const key of ['width','style','color'])properties.push('border-'+side+'-'+key);}
    const records=[...holder.querySelectorAll('*')].map(el=>{const cs=getComputedStyle(el),parent=getComputedStyle(el.parentElement);return [el,properties.filter(p=>cs.getPropertyValue(p)!==parent.getPropertyValue(p)).map(p=>[p,cs.getPropertyValue(p)])];});
    // 复制根继承值，避免粘贴目标的默认字体/颜色覆盖选区。
    const rootStyle=getComputedStyle(root);
    const body=document.createElement('div');for(const p of properties)body.style.setProperty(p,rootStyle.getPropertyValue(p));
    for(const [el,styles] of records){el.removeAttribute('style');for(const [p,v] of styles)if(!/url\s*\(/i.test(v))el.style.setProperty(p,v);for(const attr of [...el.attributes])if(/^(?:class|id|contenteditable|spellcheck)$/.test(attr.name)||attr.name.startsWith('data-')||attr.name.startsWith('on'))el.removeAttribute(attr.name);}
    holder.querySelectorAll('button,script,style,.code-copy-btn').forEach(el=>el.remove());
    body.innerHTML=holder.innerHTML;
    return {html:body.outerHTML,plain};
  }finally{holder.remove();}
};
