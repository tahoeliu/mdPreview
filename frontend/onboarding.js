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
  for(const [label,run] of [[t('Open File…','打开文件…'),()=>Bridge.call('open_file_dialog')],[t('Paste from Clipboard','从剪贴板粘贴'),async()=>{await pasteClipboardAndRead();return {success:true};}],[t('Open Example','打开示例文档'),example],[t('Set as default for .md','设为 .md 默认打开方式'),()=>Bridge.call('set_as_default_for_md')]]){
   const button=document.createElement('button');button.textContent=label;button.addEventListener('click',async event=>{event.stopPropagation();try{const result=await run();if(result?.success===false)throw new Error('action-failed');await acknowledge();actions.remove();}catch(error){showStatus(t('Action failed','操作失败'),true);}});actions.append(button);
  }overlay.append(actions);
 }
 async function initialize(){if(!Bridge.ready()||!window.pywebview.api.get_onboarding)return;
  try{const state=await Bridge.call('get_onboarding');first=state.first;const overlay=document.getElementById('welcomeOverlay');if(overlay)decorate(overlay);
   if(state.updated){let button=document.getElementById('releaseNotesNotice');if(!button){button=document.createElement('button');button.id='releaseNotesNotice';button.className='release-notes-notice';button.addEventListener('click',notes);document.body.append(button);}button.textContent=t('Updated to','已更新到')+' '+state.version+' · '+t('See changes','查看新功能');}
   else if(!first)await acknowledge();
  }catch(error){showStatus(t('Could not load welcome state','无法加载欢迎状态'),true);}
 }
 async function diagnostics(){try{const result=await Bridge.call('export_diagnostics');if(!result.success&&!result.cancelled)throw new Error('export-failed');}catch(error){showStatus(t('Diagnostics export failed','诊断导出失败'),true);}}
 return {initialize,decorate,example,shortcuts,notes,diagnostics};
})();
