/* 所有设置通过校验桥接保存；默认不启动任何网络请求。 */
window.openSettings=async function(){
  try{
    const values=await Bridge.call('get_settings'),output=await Bridge.call('get_output_settings');
    setModal(t('Settings','设置'),'','');const body=document.getElementById('modalBody');
    const modalVersion=body.dataset.version;
    const controls=[];
    function group(title){const heading=document.createElement('h3');heading.textContent=title;body.append(heading);}
    function field(key,label,value,choices,section='settings'){
      const row=document.createElement('label');row.style.cssText='display:flex;justify-content:space-between;gap:18px;margin:10px 0';row.append(document.createTextNode(label));
      const input=document.createElement(choices?'select':'input');
      if(choices){for(const [v,title] of choices){const option=document.createElement('option');option.value=v;option.textContent=title;input.append(option);}input.value=value;}
      else if(typeof value==='boolean'){input.type='checkbox';input.checked=value;}
      else {input.type='number';input.value=value;input.min=key==='font_size'?12:360;input.max=key==='font_size'?24:2016;}
      row.append(input);body.append(row);controls.push({key,input,section,value});
    }
    group(t('General','通用'));field('language',t('Interface language','界面语言'),values.language,[['system',t('System','跟随系统')],['en','English'],['zh-Hans',t('Simplified Chinese','简体中文')],['zh-Hant','繁體中文']]);
    field('restore_session',t('Restore documents at startup','启动时恢复文档'),values.restore_session);field('auto_update',t('Check for updates automatically (GitHub)','自动检查更新（访问 GitHub）'),values.auto_update);
    group(t('Reading','阅读'));field('font_size',t('Default font size','默认字号'),values.font_size);field('page_width',t('Default width','默认宽度'),values.page_width);field('remote_images',t('Remote images','远程图片'),values.remote_images,[['ask',t('Ask','询问')],['always',t('Always','总是')],['never',t('Never','从不')]]);field('auto_reload',t('Reload external changes','外部修改自动刷新'),values.auto_reload);
    group(t('Export','导出'));
    const labels={paper:t('Paper','纸张'),margins:t('Margins','边距'),font:t('Font size','字号'),pdf_layout:t('PDF layout','PDF布局'),png_width:t('PNG width','PNG宽度'),page_numbers:t('Page numbers','页码'),show_urls:t('Show links','显示链接'),hide_frontmatter:t('Hide metadata','隐藏元数据'),h1_new_page:t('Start heading 1 on new page','一级标题另页')};
    const choices={paper:['auto','a4','letter'],margins:['narrow','normal','wide'],font:['small','normal','large'],pdf_layout:['paged','continuous'],png_width:['original','mobile']};
    for(const key of Object.keys(labels))field(key,labels[key],output[key],choices[key]?.map(v=>[v,v]),'output');
    group(t('Privacy','隐私'));const privacy=document.createElement('p');privacy.textContent=t('Offline by default. GitHub is contacted only for enabled update checks; remote images require permission. Preview/source: ⌘E.','默认离线。仅主动检查更新或开启自动更新时访问 GitHub；远程图片仅在你允许后加载。预览/源码切换：⌘E。');body.append(privacy);
    group(t('About','关于'));const info=await Bridge.call('get_export_css');if(body.dataset.version!==modalVersion||!document.getElementById('modalOverlay').classList.contains('visible'))return;const about=document.createElement('p');about.textContent='mdPreview '+info.version;body.append(about);
    for(const [label,action] of [['GitHub',()=>Bridge.callSafe('open_external_link','https://github.com/tahoeliu/mdPreview')],[t('Credits','致谢'),async()=>{const text=await Bridge.call('get_credits');setModal(t('Credits','致谢'),'','');const pre=document.createElement('pre');pre.style.whiteSpace='pre-wrap';pre.textContent=text;document.getElementById('modalBody').append(pre);}],[t('Export Diagnostics','导出诊断信息'),async()=>{const result=await Bridge.call('export_diagnostics');if(!result.success&&!result.cancelled)showStatus(t('Diagnostics export failed','诊断导出失败'),true);}]]){const button=document.createElement('button');button.textContent=label;button.addEventListener('click',action);body.append(button);}
    const save=document.createElement('button');save.textContent=t('Save','保存');save.addEventListener('click',async()=>{
      const patch={},exportPatch={};for(const {key,input,section,value} of controls){const v=typeof value==='boolean'?input.checked:typeof value==='number'?Number(input.value):input.value;(section==='output'?exportPatch:patch)[key]=v;}
      try{const result=await Bridge.call('set_settings',patch);if(!result.success)throw new Error('settings-failed');const exported=await Bridge.call('set_output_settings',exportPatch);if(!exported.success)throw new Error('output-settings-failed');appSettings=result.settings;contentFontSize=appSettings.font_size;applyFontSize();pageWidthPct=normalizePageWidthPct(appSettings.page_width/BASE_WIDTH*100);applyPageWidth();isZh=appSettings.language==='system'?isZh:appSettings.language.startsWith('zh');await I18n.load();applyStaticUiLanguage();closeModal();showStatus(t('Saved. Restart to update all menus and windows.','已保存。重启后所有菜单和窗口生效。'));await renderMarkdown(getCurrentMarkdown(),document.getElementById('content'));}catch(error){showStatus(t('Could not save settings','设置保存失败'),true);}
    });document.getElementById('modalActions').prepend(save);
    controls[0]?.input.focus();
  }catch(error){showStatus(t('Could not load settings','无法加载设置'),true);}
};
