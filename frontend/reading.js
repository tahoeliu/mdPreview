/* 阅读交互：任务只定位 lexer 识别的列表项，不扫描代码块中的标记。 */
window.ReadingFeatures = (() => {
  let allowedDocument=null;
  function tasks(markdown) {
    const found=[];
    // lexer 的 item.text / quote.text 去掉了前缀；将字符映射回 raw 的绝对位置。
    function mapText(text,raw,map){
      const result=[];let cursor=0;
      for(const [index,line] of text.split('\n').entries()){
        if(index){result.push(map[cursor-1]);}
        const end=raw.indexOf('\n',cursor),stop=end<0?raw.length:end;
        const at=raw.slice(cursor,stop).lastIndexOf(line);if(at<0)return null;
        for(let i=0;i<line.length;i++)result.push(map[cursor+at+i]);
        cursor=stop+1;
      }return result;
    }
    function visit(tokens,source,map){
      let cursor=0;
      for(const token of tokens||[]){
        if(!token.raw)continue;
        const offset=source.indexOf(token.raw,cursor);if(offset<0)continue;cursor=offset+token.raw.length;
        const tokenMap=map.slice(offset,cursor);
        if(token.type==='list'){
          let itemCursor=0;
          for(const item of token.items){
            const local=token.raw.indexOf(item.raw,itemCursor);if(local<0)continue;itemCursor=local+item.raw.length;
            const itemMap=tokenMap.slice(local,itemCursor),marker=/^[ \t]*(?:[-+*]|\d+[.)])[ \t]+\[([ xX])\]/.exec(item.raw);
            if(item.task&&marker)found.push({offset:itemMap[marker[0].lastIndexOf('[')+1],checked:!!item.checked});
            const mapped=mapText(item.text,item.raw,itemMap);if(mapped)visit(item.tokens,item.text,mapped);
          }
        }else if(token.type==='blockquote'&&!/^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]/.test(token.text)){
          const mapped=mapText(token.text,token.raw,tokenMap);if(mapped)visit(token.tokens,token.text,mapped);
        }
      }
    }
    // 没有任务列表标记就不必再对整篇文档做一次 lexer 与逐字符位置映射（大文档下代价很高）。
    if(!/^[ \t>]*(?:[-+*]|\d+[.)])[ \t]+\[[ xX]\]/m.test(markdown))return found;
    const front=/^\s*---\r?\n[\s\S]*?\r?\n(?:---|\.\.\.)\r?\n?/.exec(markdown),offset=front?front[0].length:0;
    const body=markdown.slice(offset);
    visit(MarkdownPipeline.lex(body),body,Array.from({length:body.length},(_,i)=>i+offset));return found.sort((a,b)=>a.offset-b.offset);
  }
  function decorate(root,markdown){
    for(const pre of root.querySelectorAll('pre')){
      if(pre.querySelector('.code-copy-btn'))continue;
      const button=document.createElement('button');button.type='button';button.className='code-copy-btn';button.contentEditable='false';
      const icon=d=>'<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+d+'</svg>';
      const copyIcon=icon('<rect x="9" y="9" width="11" height="11" rx="2.5"/><path d="M5 15V6.5A2.5 2.5 0 0 1 7.5 4H15"/>'),doneIcon=icon('<path d="M5 12.5l4.5 4.5L19 7.5"/>');
      button.innerHTML=copyIcon;button.title=t('Copy code','复制代码');button.setAttribute('aria-label',t('Copy code','复制代码'));
      button.addEventListener('click',async e=>{e.preventDefault();e.stopPropagation();if(await copyTextToClipboard(pre.querySelector('code')?.textContent||'')){button.innerHTML=doneIcon;button.classList.add('done');button.title=t('Copied','已复制');setTimeout(()=>{button.innerHTML=copyIcon;button.classList.remove('done');button.title=t('Copy code','复制代码');},1500);}});pre.append(button);
    }
    if(window.Folding)Folding.decorate(root);
    const positions=tasks(markdown);let index=0;
    if(root.querySelectorAll('li[data-task]:not(.markdown-alert li):not(.footnotes li)').length!==positions.length){remoteBar(root);return;}
    for(const li of root.querySelectorAll('li[data-task]')){
      if(li.closest('.markdown-alert,.footnotes'))continue;
      const target=li.firstElementChild?.tagName==='P'?li.firstElementChild:li;
      const text=[...target.childNodes].find(n=>n.nodeType===3&&/^\[[ xX]\]\s/.test(n.textContent));
      if(!text)continue;
      const task=positions[index++];if(!task)continue;
      text.textContent=text.textContent.replace(/^\[[ xX]\]\s*/,'');
      const button=document.createElement('button');button.className='task-toggle';button.contentEditable='false';button.setAttribute('role','checkbox');button.setAttribute('aria-label',t('Toggle task','切换任务状态'));button.setAttribute('aria-checked',String(task.checked));button.textContent=task.checked?'\u2611':'\u2610';button.dataset.taskMarker=task.checked?'[x] ':'[ ] ';
      button.addEventListener('click',async e=>{e.preventDefault();e.stopPropagation();if(outputBusy||closing)return;
        const current=getCurrentMarkdown();
        if(current!==markdown){await renderMarkdown(current,root);showStatus(t('Content changed. Toggle again.','内容已更新，请再次勾选'));return;}
        const fresh=task;
        const next=current.slice(0,fresh.offset)+(fresh.checked?' ':'x')+current.slice(fresh.offset+1);
        document.getElementById('textarea').value=next;renderedDirty=false;setDirty(true);syncHighlight();await renderMarkdown(next,root);pushContentToPython(true);
      });text.before(button);
    }
    remoteBar(root);
  }
  function reset(){allowedDocument=null;}
  function loadRemote(root){
    for(const img of root.querySelectorAll('img[data-remote-src],img[data-remote-srcset],source[data-remote-srcset]')){
      const src=img.dataset.remoteSrc;
      if(src&&/^(?:https?:|\/\/)/i.test(src)&&MarkdownPipeline.safeURL(src.startsWith('//')?'https:'+src:src,true))img.setAttribute('src',src.startsWith('//')?'https:'+src:src);
      const candidates=(img.dataset.remoteSrcset||'').split(',').map(value=>value.trim()).filter(Boolean);
      if(candidates.length&&candidates.every(value=>/^(?:https?:\/\/|\/\/)[^\s,]+(?:\s+(?:\d+(?:\.\d+)?x|\d+w))?$/.test(value)))img.setAttribute('srcset',candidates.map(value=>value.startsWith('//')?'https:'+value:value).join(', '));
    }
    root.querySelector('.remote-image-bar')?.remove();
  }
  function remoteBar(root){
    const images=root.querySelectorAll('img[data-remote-src],img[data-remote-srcset]');if(!images.length)return;
    if(appSettings.remote_images==='always'||allowedDocument===documentSession.id){loadRemote(root);return;}
    if(appSettings.remote_images==='never')return;
    const bar=document.createElement('div');bar.className='remote-image-bar';bar.contentEditable='false';bar.textContent=t('Remote images: {count}. Loading reveals this visit to the remote server.','远程图片：{count} 张。加载后对方服务器会知道此次访问。').replace('{count}',images.length);
    for(const [title,always] of [[t('Load','加载'),false],[t('Always load','总是加载'),true]]){const button=document.createElement('button');button.textContent=title;button.addEventListener('click',async()=>{if(always){const result=await Bridge.call('set_settings',{remote_images:'always'});if(!result.success)return;appSettings=result.settings;}allowedDocument=documentSession.id;loadRemote(root);});bar.append(button);}root.prepend(bar);
  }
  async function beforeOutput(kind){
    if(kind==='html'||appSettings.remote_images==='never')return;
    const root=document.getElementById('content');
    if((root.querySelector('img[data-remote-src]:not([src])')||root.querySelector('img[data-remote-srcset]:not([srcset])'))&&window.confirm(t('Load remote images for output? The remote server will learn about this visit.','输出包含未加载的远程图片。是否加载？对方服务器将获知此次访问。'))){allowedDocument=documentSession.id;loadRemote(root);}
  }
  return {tasks,decorate,reset,beforeOutput};
})();
