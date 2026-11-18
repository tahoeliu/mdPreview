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
 const ICONS={
  open:'<path d="M3.5 7.6a2 2 0 0 1 2-2h3.7l2 2.2h7.3a2 2 0 0 1 2 2v7.6a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
  paste:'<rect x="6" y="5" width="12" height="15.5" rx="2"/><path d="M9.5 5v-.8a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1V5M9.2 10.6h5.6M9.2 14.2h5.6"/>'
 };
 async function attempt(run){
  try{const result=await run();if(result&&result.success===false&&!result.cancelled)throw new Error('action-failed');}
  catch(error){showStatus(t('Action failed','操作失败'),true);}
 }
 function tile(kind,label,run){
  const button=document.createElement('button');button.type='button';button.className='welcome-tile';button.dataset.kind=kind;
  button.innerHTML='<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+ICONS[kind]+'</svg><span></span>';
  button.lastChild.textContent=label;
  button.addEventListener('click',()=>void attempt(run));
  return button;
 }
 const recentRequests=new WeakMap();
 async function refresh(overlay){
  const list=overlay.querySelector('.welcome-recents');
  if(!Bridge.ready()||!window.pywebview.api.get_recent_files)return;
  const request=Bridge.call('get_recent_files');
  recentRequests.set(list,request);
  let files;
  try{files=await request;}catch(error){files=[];}
  if(overlay.id!=='welcomeOverlay'||recentRequests.get(list)!==request)return;
  const items=(Array.isArray(files)?files:[]).filter(file=>file&&typeof file.name==='string'&&typeof file.path==='string').slice(0,3);
  const paths=items.map(file=>file.path);
  if(JSON.stringify(paths)===list.dataset.paths)return;
  list.dataset.paths=JSON.stringify(paths);
  list.hidden=!items.length;
  const heading=document.createElement('div');heading.className='welcome-recents-label';heading.textContent=t('Recent Documents','最近文档');
  const rows=document.createElement('ul');
  for(const file of items){
   const row=document.createElement('li');
   const button=document.createElement('button');button.type='button';button.title=file.path;
   const name=document.createElement('span');name.textContent=file.name;
   const folder=document.createElement('span');folder.className='welcome-recent-folder';folder.textContent=file.folder||'';
   button.append(name,folder);
   button.addEventListener('click',()=>void attempt(()=>Bridge.call('open_recent_file',file.path)));
   row.append(button);rows.append(row);
  }
  list.replaceChildren(heading,rows);
 }
 function build(overlay,recover){
  const title=document.createElement('div');title.className='welcome-title';title.textContent='mdPreview';
  const hint=document.createElement('div');hint.className='welcome-hint';hint.textContent=t('Or start typing.','也可直接输入。');
  const actions=document.createElement('div');actions.className='welcome-actions';
  actions.append(tile('open',t('Open File…','打开文件…'),()=>Bridge.call('open_file_dialog')),tile('paste',t('Paste to Preview','粘贴查看'),()=>pasteClipboardAndRead()));
  const recents=document.createElement('section');recents.className='welcome-recents';recents.hidden=true;
  const recovery=document.createElement('button');recovery.type='button';recovery.className='welcome-recovery';recovery.hidden=true;
  recovery.textContent=t('Recover documents','恢复文档');recovery.addEventListener('click',recover);
  overlay.append(title,actions,hint,recents,recovery);
  decorate(overlay);void refresh(overlay);
 }
 async function initialize(){if(!Bridge.ready()||!window.pywebview.api.get_onboarding)return;
  try{const state=await Bridge.call('get_onboarding');first=state.first;const overlay=document.getElementById('welcomeOverlay');if(overlay)decorate(overlay);
   if(state.updated){let button=document.getElementById('releaseNotesNotice');if(!button){button=document.createElement('button');button.id='releaseNotesNotice';button.className='release-notes-notice';button.addEventListener('click',notes);document.body.append(button);}button.textContent=t('Updated to','已更新到')+' '+state.version+' · '+t('See changes','查看新功能');clearTimeout(button._hideTimer);button.classList.remove('is-leaving');button._hideTimer=setTimeout(()=>{acknowledge().catch(()=>{});button.classList.add('is-leaving');setTimeout(()=>button.remove(),400);},10000);}
   else if(!first)await acknowledge();
  }catch(error){showStatus(t('Could not load welcome state','无法加载欢迎状态'),true);}
 }
 async function diagnostics(){try{const result=await Bridge.call('export_diagnostics');if(!result.success&&!result.cancelled)throw new Error('export-failed');}catch(error){showStatus(t('Diagnostics export failed','诊断导出失败'),true);}}
 return {initialize,decorate,build,refresh,example,shortcuts,notes,diagnostics};
})();
