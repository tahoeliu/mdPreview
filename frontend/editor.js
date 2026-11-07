/* 源码编辑统一走 insertText，让原生撤销栈记录每次替换。 */
window.EditorFeatures=(()=>{
  function replace(ta,start,end,text,selection){ta.focus();ta.setSelectionRange(start,end);if(!document.execCommand('insertText',false,text))throw new Error('undoable-edit-unavailable');if(selection)ta.setSelectionRange(...selection);}
  function key(event){
    const ta=document.getElementById('textarea');if(event.target!==ta||!isSource||event.isComposing)return;
    const value=ta.value,start=ta.selectionStart,end=ta.selectionEnd,selected=value.slice(start,end),cmd=event.metaKey||event.ctrlKey;
    if(cmd&&!event.altKey&&['b','i','k'].includes(event.key.toLowerCase())){
      event.preventDefault();event.stopImmediatePropagation();const k=event.key.toLowerCase(),marker=k==='b'?'**':'*';
      if(k==='k'){if(value.slice(start-1,start)==='['&&value.slice(end,end+3)===']()')replace(ta,start-1,end+3,selected,[start-1,end-1]);else replace(ta,start,end,'['+selected+']()',[start+selected.length+3,start+selected.length+3]);}
      else if(value.slice(start-marker.length,start)===marker&&value.slice(end,end+marker.length)===marker)replace(ta,start-marker.length,end+marker.length,selected,[start-marker.length,end-marker.length]);
      else replace(ta,start,end,marker+selected+marker,[start+marker.length,end+marker.length]);return;
    }
    if(event.key==='Enter'&&!cmd&&!event.altKey){
      const lineStart=value.lastIndexOf('\n',start-1)+1,line=value.slice(lineStart,start),match=/^(\s*)([-*]|\d+\.|>)(\s+)(\[[ xX]\]\s+)?(.*)$/.exec(line);
      if(match&&start===end){event.preventDefault();event.stopImmediatePropagation();if(!match[5].trim())replace(ta,lineStart,start,'');else {const marker=/^\d/.test(match[2])?(parseInt(match[2],10)+1)+'.':match[2];replace(ta,start,end,'\n'+match[1]+marker+match[3]+(match[4]?'[ ] ':''));}}return;
    }
    if(event.key==='Tab'&&!cmd&&!event.altKey){event.preventDefault();event.stopImmediatePropagation();const from=value.lastIndexOf('\n',start-1)+1,to=end>start&&value[end-1]==='\n'?end-1:end;const lines=value.slice(from,to).split('\n');const text=lines.map(line=>event.shiftKey?line.replace(/^ {1,2}/,''):'  '+line).join('\n');replace(ta,from,to,text,[from,from+text.length]);}
  }
  async function image(file){
    if(!filePath||filePath==='Untitled.md'){showStatus(t('Save the document before inserting an image','请先保存文档再插入图片'),true);await saveAsFile();if(!filePath||filePath==='Untitled.md')return;}
    const identity=documentSession.id;
    const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(file);});
    const ext={'image/png':'png','image/jpeg':'jpg','image/gif':'gif','image/webp':'webp'}[file.type];if(!ext)throw new Error('unsupported-image');
    const result=await Bridge.call('save_image_asset',filePath,data,ext,file.name,identity);
    if(identity!==documentSession.id)return;if(!result.success)throw new Error('image-save-failed');
    insertMarkdownSnippet('\n!['+(file.name||'图片').replace(/[\[\]\\]/g,'_')+']('+result.path+')\n');
  }
  function install(){
    document.addEventListener('keydown',key,true);
    document.addEventListener('paste',event=>{
      if(!event.target.closest?.('#textarea,#content')||event.clipboardData?.getData('text/plain'))return;
      const item=[...(event.clipboardData?.items||[])].find(i=>i.kind==='file'&&i.type.startsWith('image/'));if(!item)return;
      event.preventDefault();event.stopImmediatePropagation();image(item.getAsFile()).catch(()=>showStatus(t('Image save failed','图片保存失败'),true));
    },true);
    const bar=document.getElementById('findBar'),input=document.createElement('input');input.hidden=!isSource;input.id='replaceInput';input.placeholder=t('Replace with','替换为');input.setAttribute('aria-label',input.placeholder);bar.append(input);
    for(const all of [false,true]){const button=document.createElement('button');button.textContent=all?t('Replace all','全部替换'):t('Replace','替换');button.dataset.replaceAll=String(all);button.className='replace-action';button.hidden=!isSource;button.addEventListener('click',()=>{
      if(!isSource)return;const ta=document.getElementById('textarea'),needle=document.getElementById('findInput').value;if(!needle)return;
      if(all)replace(ta,0,ta.value.length,ta.value.split(needle).join(input.value));else{const index=ta.value.indexOf(needle,ta.selectionStart);if(index>=0)replace(ta,index,index+needle.length,input.value);}
    });bar.append(button);}
  }
  return {install,image,replace};
})();
