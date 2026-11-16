window.Onboarding=(()=>{
 let first=false;
 async function acknowledge(){await Bridge.call('acknowledge_onboarding');first=false;}
 async function example(){try{
  const markdown=await Bridge.call('get_example');
  setModal(t('Open Example','打开示例文档'),'','');
  const article=document.createElement('article');article.className='markdown';article.lang=I18n.locale;article.contentEditable='false';
  article.innerHTML=MarkdownPipeline.parse(markdown.replace(/^---\n[\s\S]*?\n---\n/,''));document.getElementById('modalBody').append(article);
  await MathRenderer.renderMath(article,{eager:true});await renderMermaidDiagrams(article);
  document.querySelector('#modalActions button')?.focus();
  await acknowledge();
 }catch(error){showStatus(t('Could not open example','无法打开示例'),true);}}
 async function shortcuts(){try{
  const definitions=await Bridge.call('get_shortcuts');setModal(t('Keyboard Shortcuts','快捷键一览'),'','');
  const table=document.createElement('table');const symbols={command:'⌘',option:'⌥',shift:'⇧',control:'⌃'};
  for(const item of definitions){const row=table.insertRow();row.insertCell().textContent=t(item.en,item.zh);row.insertCell().textContent=item.modifiers.map(x=>symbols[x]).join('')+item.key.toUpperCase();}
  document.getElementById('modalBody').append(table);
 }catch(error){showStatus(t('Could not load shortcuts','无法加载快捷键'),true);}}
 async function notes(){try{const data=await Bridge.call('get_release_notes');setModal(t('Release Notes','更新说明')+' '+data.version,'','');
  const article=document.createElement('article');article.className='markdown';article.innerHTML=data.available?MarkdownPipeline.parse(data.content):'';
  if(!data.available)article.textContent=t('No bundled notes for this version.','此版本没有内置更新说明。');document.getElementById('modalBody').append(article);await acknowledge();document.getElementById('releaseNotesNotice')?.remove();
 }catch(error){showStatus(t('Could not load release notes','无法加载更新说明'),true);}}
 function decorate(overlay){if(!first||overlay.querySelector('[data-onboarding]'))return;
  const actions=document.createElement('div');actions.dataset.onboarding='true';
  for(const [label,run] of [[t('Open Example','打开示例文档'),example],[t('Set as default for .md','设为 .md 默认打开方式'),()=>Bridge.call('set_as_default_for_md')]]){
   const button=document.createElement('button');button.textContent=label;button.addEventListener('click',async event=>{event.stopPropagation();try{const result=await run();if(result?.success===false)throw new Error('action-failed');await acknowledge();actions.remove();}catch(error){showStatus(t('Action failed','操作失败'),true);}});actions.append(button);
  }const row=overlay.querySelector('.welcome-actions');if(row)row.after(actions);else overlay.append(actions);
 }
 // The start screen on an empty document: a title and three entry points (open, recent, paste).
 const ICONS={open:'<path d="M3.5 7.6a2 2 0 0 1 2-2h3.7l2 2.2h7.3a2 2 0 0 1 2 2v7.6a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
  recent:'<circle cx="12" cy="12" r="8.5"/><path d="M12 7.4V12l3.1 2"/>',
  paste:'<rect x="6" y="5" width="12" height="15.5" rx="2"/><path d="M9.5 5v-.8a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1V5M9.2 10.6h5.6M9.2 14.2h5.6"/>'};
 async function attempt(run){try{const result=await run();if(result&&result.success===false&&!result.cancelled)throw new Error('action-failed');}catch(error){showStatus(t('Action failed','操作失败'),true);}}
 function tile(kind,label,run){const button=document.createElement('button');button.type='button';button.className='welcome-tile';button.dataset.kind=kind;
  button.innerHTML='<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+ICONS[kind]+'</svg><span></span>';
  button.lastChild.textContent=label;button.addEventListener('click',event=>{event.stopPropagation();attempt(run);});return button;}
 function closeRecent(){const menu=document.querySelector('.welcome-menu');if(!menu)return;menu.remove();document.querySelector('.welcome-tile[data-kind="recent"]')?.setAttribute('aria-expanded','false');
  document.removeEventListener('click',closeRecent);window.removeEventListener('keydown',recentKey,true);}
 function recentKey(event){if(event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();closeRecent();document.querySelector('.welcome-tile[data-kind="recent"]')?.focus();}}
 function openRecent(button,files){if(document.querySelector('.welcome-menu')){closeRecent();return;}
  const menu=document.createElement('div');menu.className='welcome-menu';menu.setAttribute('role','menu');
  for(const file of files){const item=document.createElement('button');item.type='button';item.setAttribute('role','menuitem');item.title=file.path;
   const name=document.createElement('span');name.className='welcome-menu-name';name.textContent=file.name;const folder=document.createElement('span');folder.className='welcome-menu-folder';folder.textContent=file.folder||'';item.append(name,folder);
   item.addEventListener('click',event=>{event.stopPropagation();closeRecent();attempt(()=>Bridge.call('open_recent_file',file.path));});menu.append(item);}
  button.after(menu);button.setAttribute('aria-expanded','true');menu.firstChild.focus();
  document.addEventListener('click',closeRecent);window.addEventListener('keydown',recentKey,true);}
 let recentFiles=[];
 async function recent(button){if(!button||!Bridge.ready()||!window.pywebview.api.get_recent_files)return;
  let files=[];try{files=await Bridge.call('get_recent_files');}catch(error){files=[];}
  recentFiles=Array.isArray(files)?files.filter(file=>file&&typeof file.name==='string'&&typeof file.path==='string'):[];
  if(!button.isConnected)return;button.disabled=!recentFiles.length;button.setAttribute('aria-haspopup','menu');button.setAttribute('aria-expanded','false');
  if(!button.dataset.bound){button.dataset.bound='true';button.addEventListener('click',event=>{event.stopPropagation();if(recentFiles.length)openRecent(button,recentFiles);});}}
 function refresh(overlay){closeRecent();recent(overlay.querySelector('.welcome-tile[data-kind="recent"]'));}
 function build(overlay){const title=document.createElement('div');title.className='welcome-title';title.textContent=t('Start writing','开始书写');
  const hint=document.createElement('div');hint.className='welcome-hint';hint.textContent=t('Just type, or open something.','直接输入，或打开一份文档。');
  const actions=document.createElement('div');actions.className='welcome-actions';
  const recentTile=tile('recent',t('Open Recent','打开最近'),async()=>{});recentTile.disabled=true;
  const slot=document.createElement('div');slot.className='welcome-slot';slot.append(recentTile);
  actions.append(tile('open',t('Open File…','打开文件…'),()=>Bridge.call('open_file_dialog')),slot,tile('paste',t('Paste','粘贴'),async()=>{await pasteClipboardAndRead();}));
  overlay.append(title,hint,actions);decorate(overlay);recent(recentTile);}
 async function initialize(){if(!Bridge.ready()||!window.pywebview.api.get_onboarding)return;
  try{const state=await Bridge.call('get_onboarding');first=state.first;const overlay=document.getElementById('welcomeOverlay');if(overlay)decorate(overlay);
   if(state.updated){let button=document.getElementById('releaseNotesNotice');if(!button){button=document.createElement('button');button.id='releaseNotesNotice';button.className='release-notes-notice';button.addEventListener('click',notes);document.body.append(button);}button.textContent=t('Updated to','已更新到')+' '+state.version+' · '+t('See changes','查看新功能');clearTimeout(button._hideTimer);button.classList.remove('is-leaving');button._hideTimer=setTimeout(()=>{acknowledge().catch(()=>{});button.classList.add('is-leaving');setTimeout(()=>button.remove(),400);},10000);}
   else if(!first)await acknowledge();
  }catch(error){showStatus(t('Could not load welcome state','无法加载欢迎状态'),true);}
 }
 async function diagnostics(){try{const result=await Bridge.call('export_diagnostics');if(!result.success&&!result.cancelled)throw new Error('export-failed');}catch(error){showStatus(t('Diagnostics export failed','诊断导出失败'),true);}}
 return {initialize,decorate,build,refresh,example,shortcuts,notes,diagnostics};
})();
