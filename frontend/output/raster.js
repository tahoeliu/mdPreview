/* Word 和富文本共享的本地 SVG/公式栅格化；不静默丢弃图片。 */
window.OutputRaster = (() => {
  async function image(data, maxWidth=605) {
    if(!/^data:image\/(?:png|jpeg|gif|webp|avif|bmp);base64,[a-z0-9+/=]+$/i.test(data))throw new Error('unsupported-raster-source');
    const img = new Image(); img.src=data; await img.decode();
    if(!img.naturalWidth||!img.naturalHeight)throw new Error('invalid-image-size');
    const ratio=Math.min(1,maxWidth/img.naturalWidth);
    const width=Math.max(1,Math.round(img.naturalWidth*ratio)),height=Math.max(1,Math.round(img.naturalHeight*ratio));
    if(!/^data:image\/(?:png|jpeg|gif|bmp);/i.test(data)){
      if(width*height*4>120000000)throw new Error('image-too-large');
      const canvas=document.createElement('canvas');canvas.width=width*2;canvas.height=height*2;
      const context=canvas.getContext('2d');if(!context)throw new Error('canvas-unavailable');
      context.drawImage(img,0,0,canvas.width,canvas.height);data=canvas.toDataURL('image/png');
    }
    return {data,width,height};
  }
  async function node(el, maxWidth=605) {
    const rect=el.getBoundingClientRect();
    const width=Math.max(1,Math.ceil(rect.width)), height=Math.max(1,Math.ceil(rect.height));
    if(width*height*4>120000000)throw new Error('diagram-too-large');
    const svg=el.matches('svg') ? el : el.querySelector('svg');
    let source;
    if(el.matches('.mermaid-diagram') && svg) {
      const clone=svg.cloneNode(true);clone.setAttribute('width',width);clone.setAttribute('height',height);
      source=new XMLSerializer().serializeToString(clone);
    } else {
      const clone=el.cloneNode(true),computed=getComputedStyle(el);
      clone.style.cssText='margin:0;color:#111;background:white;';
      clone.style.fontSize=computed.fontSize;clone.style.fontFamily=computed.fontFamily;clone.style.lineHeight=computed.lineHeight;
      clone.querySelectorAll('.katex-display').forEach(node=>{node.style.margin='0';});
      const css=await MathRenderer.exportCSS(el);
      const container=document.createElementNS('http://www.w3.org/1999/xhtml','div');
      const style=document.createElementNS('http://www.w3.org/1999/xhtml','style');style.textContent=css;
      container.append(style,clone);
      source='<svg xmlns="http://www.w3.org/2000/svg" width="'+width+'" height="'+height+'"><foreignObject width="100%" height="100%">'+new XMLSerializer().serializeToString(container)+'</foreignObject></svg>';
    }
    const input=new Image();input.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(source);await input.decode();
    const canvas=document.createElement('canvas');canvas.width=width*2;canvas.height=height*2;
    const ctx=canvas.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(input,0,0,canvas.width,canvas.height);
    const ratio=Math.min(1,maxWidth/width);
    return {data:canvas.toDataURL('image/png'),width:Math.round(width*ratio),height:Math.round(height*ratio)};
  }
  return {image,node};
})();
