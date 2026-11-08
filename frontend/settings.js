/* 所有设置通过校验桥接保存；默认不启动任何网络请求。 */
window.openSettings=async function(){
  try{
    const values=await Bridge.call('get_settings'),output=await Bridge.call('get_output_settings');
    setModal(t('Settings','设置'),'','');const body=document.getElementById('modalBody');
    const modalVersion=body.dataset.version;
    const controls=[];
    let card=null;function group(title){const heading=document.createElement('h3');heading.className='set-title';heading.textContent=title;body.append(heading);card=document.createElement('div');card.className='set-card';body.append(card);}
    function field(key,label,value,choices,section='settings'){
      const row=document.createElement('label');row.className='set-row';const name=document.createElement('span');name.className='set-label';name.textContent=label;row.append(name);
      const input=document.createElement(choices?'select':'input');
      if(choices){for(const [v,title] of choices){const option=document.createElement('option');option.value=v;option.textContent=title;input.append(option);}if(typeof value==='number'){const nearest=choices.map(([v])=>Number(v)).reduce((a,b)=>Math.abs(b-value)<Math.abs(a-value)?b:a);input.value=String(nearest);}else input.value=value;}
      else if(typeof value==='boolean'){input.type='checkbox';input.checked=value;}
      else {input.type='number';input.value=value;input.min=key==='font_size'?12:360;input.max=key==='font_size'?24:2016;}
      row.append(input);(card||body).append(row);controls.push({key,input,section,value});
    }
    group(t('General','通用'));field('language',t('Interface language','界面语言'),values.language,[['system',t('System','跟随系统')],['en','English'],['zh-Hans',t('Simplified Chinese','简体中文')],['zh-Hant','繁體中文'],['ja','日本語'],['ko','한국어'],['de','Deutsch'],['fr','Français'],['es','Español']]);
    field('appearance',t('Appearance','外观'),values.appearance,[['system',t('System','跟随系统')],['light',t('Light','浅色')],['dark',t('Dark','深色')]]);
    field('restore_session',t('Restore documents at startup','启动时恢复文档'),values.restore_session);field('auto_update',t('Check for updates automatically (GitHub)','自动检查更新（访问 GitHub）'),values.auto_update);
    group(t('Reading','阅读'));field('reading_font',t('Reading font','阅读字体'),values.reading_font,[['sans',t('Sans-serif','无衬线')],['serif',t('Serif','衬线')]]);field('font_size',t('Text size','文字大小'),values.font_size,[[14,t('Small','小')],[16,t('Standard','标准')],[18,t('Large','大')],[20,t('Extra large','特大')]]);field('page_width',t('Reading width','阅读宽度'),values.page_width,[[600,t('Narrow','窄')],[720,t('Standard','标准')],[860,t('Wide','宽')],[1000,t('Extra wide','特宽')]]);field('remote_images',t('Remote images','远程图片'),values.remote_images,[['ask',t('Ask','询问')],['always',t('Always','总是')],['never',t('Never','从不')]]);field('auto_reload',t('Reload external changes','外部修改自动刷新'),values.auto_reload);
    group(t('Export','导出'));
    const labels={paper:t('Paper','纸张'),margins:t('Margins','边距'),font:t('Font size','字号'),pdf_layout:t('PDF layout','PDF布局'),png_width:t('PNG width','PNG宽度'),page_numbers:t('Page numbers','页码'),show_urls:t('Show links','显示链接'),hide_frontmatter:t('Hide metadata','隐藏元数据'),h1_new_page:t('Start heading 1 on new page','一级标题另页')};
    const choices={paper:['auto','a4','letter'],margins:['narrow','normal','wide'],font:['small','normal','large'],pdf_layout:['paged','continuous'],png_width:['original','mobile']};
    const choiceNames={auto:t('Auto','自动'),a4:'A4',letter:'Letter',narrow:t('Narrow','窄'),normal:t('Normal','标准'),wide:t('Wide','宽'),small:t('Small','小'),large:t('Large','大'),paged:t('Paged','分页'),continuous:t('Continuous long page','连续长页'),original:t('Current width','当前宽度'),mobile:t('Phone-sized','手机尺寸')};
    for(const key of Object.keys(labels))field(key,labels[key],output[key],choices[key]?.map(v=>[v,choiceNames[v]||v]),'output');
    group(t('Privacy','隐私'));const privacy=document.createElement('p');privacy.className='set-note';privacy.textContent=t('Offline by default. GitHub is contacted only for enabled update checks; remote images require permission. Preview/source: ⌘E.','默认离线。仅主动检查更新或开启自动更新时访问 GitHub；远程图片仅在你允许后加载。预览/源码切换：⌘E。');card.remove();body.append(privacy);
    group(t('About','关于'));card.remove();const info=await Bridge.call('get_export_css');if(body.dataset.version!==modalVersion||!document.getElementById('modalOverlay').classList.contains('visible'))return;const about=document.createElement('p');about.className='set-note';about.textContent='mdPreview '+info.version;body.append(about);const links=document.createElement('div');links.className='set-links';body.append(links);
    for(const [label,action] of [['GitHub',()=>Bridge.callSafe('open_external_link','https://github.com/tahoeliu/mdPreview')],[t('Credits','致谢'),async()=>{const text=await Bridge.call('get_credits');setModal(t('Credits','致谢'),'','');const pre=document.createElement('pre');pre.style.whiteSpace='pre-wrap';pre.textContent=text;document.getElementById('modalBody').append(pre);}],[t('Export Diagnostics','导出诊断信息'),async()=>{const result=await Bridge.call('export_diagnostics');if(!result.success&&!result.cancelled)showStatus(t('Diagnostics export failed','诊断导出失败'),true);}]]){const button=document.createElement('button');button.textContent=label;button.className='modal-button secondary';button.addEventListener('click',action);links.append(button);}
    const save=document.createElement('button');save.textContent=t('Save','保存');save.addEventListener('click',async()=>{
      const patch={},exportPatch={};for(const {key,input,section,value} of controls){const v=typeof value==='boolean'?input.checked:typeof value==='number'?Number(input.value):input.value;(section==='output'?exportPatch:patch)[key]=v;}
      try{const result=await Bridge.call('set_settings',patch);if(!result.success)throw new Error('settings-failed');const exported=await Bridge.call('set_output_settings',exportPatch);if(!exported.success)throw new Error('output-settings-failed');appSettings=result.settings;contentFontSize=appSettings.font_size;applyFontSize();applyReadingFont();pageWidthPct=normalizePageWidthPct(appSettings.page_width/BASE_WIDTH*100);applyPageWidth();isZh=appSettings.language==='system'?isZh:appSettings.language.startsWith('zh');await I18n.load();applyStaticUiLanguage();closeModal();showStatus(t('Saved. Restart to update all menus and windows.','已保存。重启后所有菜单和窗口生效。'));await renderMarkdown(getCurrentMarkdown(),document.getElementById('content'));}catch(error){showStatus(t('Could not save settings','设置保存失败'),true);}
    });save.className='modal-close';const actions=document.getElementById('modalActions');actions.querySelector('.modal-close')?.classList.add('modal-button','secondary');actions.append(save);
    controls[0]?.input.focus();
  }catch(error){showStatus(t('Could not load settings','无法加载设置'),true);}
};
