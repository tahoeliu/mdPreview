/* 直接构建 OOXML，不使用 HTML altChunk。 */
window.buildDocxFromMarkdown = async function(markdown, ctx) {
  await ensureLib('vendor/docx.umd.js','docx');
  const D=window.docx, tokens=MarkdownPipeline.lex(markdown.replace(/^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/,''));
  const font={ascii:'Calibri',hAnsi:'Calibri',eastAsia:'PingFang SC'};
  const size={small:21,normal:22,large:24}[ctx.options.font] || 22;
  // Word 的脚注与引用一一对应：同一定义被多次引用时，每次引用生成独立脚注（内容相同），
  // 与 Pandoc、LibreOffice 的做法一致，避免出现两个 footnoteReference 指向同一 id 的非常规文件。
  const notes={}, references=[]; let nextNoteId=1, insideNote=false;
  const collect=items=>{for(const t of items||[]){if(t.type==='footnote'&&!notes[t.label]){notes[t.label]=t;} if(t.type==='footnotes')collect(t.rawItems);if(t.tokens)collect(t.tokens);if(t.items)collect(t.items);}};
  collect(tokens);
  const run=(text,style={})=>new D.TextRun({text,font,size,...style});
  const paragraph=(children,opts={})=>new D.Paragraph({children,spacing:{after:120,line:312},...opts});
  const rendered=[...ctx.root.querySelectorAll('.math-inline,.math-block,.mermaid-diagram')];
  async function graphic(token,math=false) {
    const el=rendered.find(e=>math ? (e.dataset.tex===token.text || e.dataset.raw===token.raw.trimEnd()) : e.dataset.source?.trim()===token.text.trim());
    if(!el)throw new Error('rendered-diagram-missing');
    const value=await OutputRaster.node(el,605);
    const scale=token.type==='inlineMath'?Math.min(1,(size/2*96/72*1.3)/value.height):1;
    return new D.ImageRun({type:'png',data:value.data,transformation:{width:Math.max(1,Math.round(value.width*scale)),height:Math.max(1,Math.round(value.height*scale))}});
  }
  async function inline(items,style={}) {
    const result=[];
    for(const t of items||[]) {
      if(['strong','em','del'].includes(t.type)){result.push(...await inline(t.tokens,{...style,...{strong:{bold:true},em:{italics:true},del:{strike:true}}[t.type]}));continue;}
      if(t.type==='link') {if(MarkdownPipeline.safeURL(t.href))result.push(new D.ExternalHyperlink({link:t.href,children:await inline(t.tokens,style)}));else result.push(run(t.text,style));continue;}
      if(t.type==='image') {
        if(/^(?:https?:|\/\/)/i.test(t.href)){
          const image=[...ctx.root.querySelectorAll('img[data-remote-src]')].find(el=>el.dataset.remoteSrc===t.href);
          if(!image?.hasAttribute('src')){result.push(run('[远程图片: '+t.text+']',style));continue;}
          const canvas=document.createElement('canvas');const width=image.naturalWidth,height=image.naturalHeight;
          if(!width||!height||width*height>120000000)throw new Error('remote-image-unavailable');
          canvas.width=width;canvas.height=height;canvas.getContext('2d').drawImage(image,0,0);
          const pic=await OutputRaster.image(canvas.toDataURL('image/png'));
          result.push(new D.ImageRun({type:'png',data:pic.data,transformation:{width:pic.width,height:pic.height}}));continue;
        }
        const response=/^data:image\//i.test(t.href)?{success:true,data:t.href}:await Bridge.call('read_image_for_export',t.href,ctx.documentId);
        if(!response.success)throw new Error('image-export-failed');
        const pic=await OutputRaster.image(response.data);
        let type=(pic.data.match(/^data:image\/(png|jpeg|gif|bmp)/i)||[])[1];
        if(!type)throw new Error('unsupported-docx-image');
        if(type==='jpeg')type='jpg';
        result.push(new D.ImageRun({type,data:pic.data,transformation:{width:pic.width,height:pic.height}}));continue;
      }
      if(t.type==='inlineMath'){result.push(await graphic(t,true));continue;}
      if(t.type==='footnoteRef'){
        // 脚注内部再出现的引用，Word 不支持嵌套，按原文输出。
        if(notes[t.label]&&!insideNote){const id=nextNoteId++;references.push([id,t.label]);result.push(new D.FootnoteReferenceRun(id));}
        else result.push(run(t.raw,style));
        continue;
      }
      if(t.type==='br'){result.push(new D.TextRun({break:1}));continue;}
      if(t.type==='codespan'){result.push(run(t.text,{...style,font:'Menlo',shading:{fill:'F5F5F7'}}));continue;}
      if(t.tokens){result.push(...await inline(t.tokens,style));continue;}
      if(t.type==='html'){const el=document.createElement('div');el.innerHTML=MarkdownPipeline.cleanHTML(t.text);result.push(run(el.textContent,style));continue;}
      const text=document.createElement('textarea');text.innerHTML=t.text || t.raw || '';result.push(run(text.value,style));
    }
    return result;
  }
  function codeLines(token) {
    const code=[...ctx.root.querySelectorAll('pre code')].find(el=>el.textContent.replace(/\n$/,'')===token.text.replace(/\n$/,''));
    const lines=[[]];
    const append=(text,color)=>text.split('\n').forEach((part,index)=>{
      if(index)lines.push([]);
      if(part)lines[lines.length-1].push(run(part,{font:'Menlo',size:18,...(color?{color}:{})}));
    });
    const visit=node=>{
      if(node.nodeType===3){
        const rgb=getComputedStyle(node.parentElement).color.match(/^rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)$/);
        append(node.textContent,rgb?rgb.slice(1).map(n=>Number(n).toString(16).padStart(2,'0')).join(''):undefined);
      }else for(const child of node.childNodes)visit(child);
    };
    if(code){visit(code);if(code.textContent.endsWith('\n'))lines.pop();}else append(token.text);
    return lines.map(children=>paragraph(children,{spacing:{after:0,line:240}}));
  }
  const numbering=[];let listSerial=0;
  async function blocks(items,depth=0,extra={}) {
    const result=[];
    for(const t of items||[]) {
      if(['space','footnote','footnotes','def'].includes(t.type))continue;
      if(t.type==='heading'){result.push(paragraph(await inline(t.tokens),{...extra,heading:D.HeadingLevel['HEADING_'+t.depth]}));continue;}
      if(t.type==='paragraph'||t.type==='text'){result.push(paragraph(await inline(t.tokens||[{type:'text',text:t.text}]),extra));continue;}
      if(t.type==='alert'){result.push(paragraph([run(t.kind,{bold:true})]),...await blocks(t.tokens,depth,extra));continue;}
      if(t.type==='blockquote'){result.push(...await blocks(t.tokens,depth,{...extra,indent:{left:360},border:{left:{color:'BBBBBB',style:D.BorderStyle.SINGLE,size:12,space:8}}}));continue;}
      if(t.type==='list') {
        const reference='list-'+listSerial++;
        numbering.push({reference,levels:Array.from({length:4},(_,level)=>({level,format:t.ordered?D.LevelFormat.DECIMAL:D.LevelFormat.BULLET,text:t.ordered?'%'+(level+1)+'.':'•',start:t.start||1,alignment:D.AlignmentType.LEFT,style:{paragraph:{indent:{left:360*(level+1),hanging:180}}}}))});
        for(const item of t.items){
          const content=item.tokens.filter(x=>x.type!=='space');
          const first=content[0];
          const hasLead=first&&['text','paragraph','heading'].includes(first.type);
          const lead=hasLead?await inline(first.tokens||[{type:'text',text:first.text}]):[];
          result.push(paragraph([...(item.task?[run(item.checked?'\u2611 ':'\u2610 ')]:[]),...lead],{...extra,numbering:{reference,level:Math.min(depth,3)}}));
          result.push(...await blocks(content.slice(hasLead?1:0),depth+1,{...extra,indent:{left:360*(Math.min(depth,3)+1)}}));
        }continue;
      }
      if(t.type==='code') {
        if(t.lang?.split(/\s/)[0]==='mermaid'){result.push(paragraph([await graphic(t)]));continue;}
        const lines=codeLines(t);
        result.push(new D.Table({width:{size:100,type:D.WidthType.PERCENTAGE},rows:[new D.TableRow({children:[new D.TableCell({shading:{fill:'F5F5F7'},children:lines})]})]}));continue;
      }
      if(t.type==='blockMath'){result.push(paragraph([await graphic(t,true)]));continue;}
      if(t.type==='table') {
        const row=async(cells,header)=>new D.TableRow({tableHeader:header,children:await Promise.all(cells.map(async(cell,i)=>new D.TableCell({children:[paragraph(await inline(cell.tokens),{alignment:{left:D.AlignmentType.LEFT,center:D.AlignmentType.CENTER,right:D.AlignmentType.RIGHT}[t.align[i]]||D.AlignmentType.LEFT})]})))});
        result.push(new D.Table({width:{size:100,type:D.WidthType.PERCENTAGE},rows:[await row(t.header,true),...await Promise.all(t.rows.map(c=>row(c,false)))]}));continue;
      }
      if(t.type==='hr'){result.push(paragraph([],{border:{bottom:{color:'BBBBBB',style:D.BorderStyle.SINGLE,size:6}}}));continue;}
      if(t.type==='html'){const el=document.createElement('div');el.innerHTML=MarkdownPipeline.cleanHTML(t.text);result.push(paragraph([run(el.textContent)]));continue;}
      throw new Error('unsupported-docx-token:'+t.type);
    }
    return result;
  }
  const children=await blocks(tokens), footnotes={};
  insideNote=true;
  for(const [id,label] of references)footnotes[id]={children:await blocks(notes[label].content)};
  insideNote=false;
  const doc=new D.Document({title:ctx.title,creator:'mdPreview',styles:{default:{document:{run:{font,size},paragraph:{spacing:{after:120,line:312}}}}},numbering:{config:numbering},footnotes,sections:[{children}]});
  return D.Packer.toBase64String(doc);
};
