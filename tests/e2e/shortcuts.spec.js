const {test,expect}=require('@playwright/test');
test.beforeEach(async({page})=>{
  await page.goto('/');
  await page.waitForFunction(()=>typeof loadContent==='function');
  await page.evaluate(async()=>{
    window.__saved=null;
    const settings={language:'en',appearance:'system',restore_session:false,auto_update:true,format_bar:false,font_size:16,reading_font:'sans',toggle_shortcut:'cmd+e',page_width:720,remote_images:'ask',auto_reload:true};
    window.pywebview={api:{
      get_export_css(){return Promise.resolve({css:'',version:'2.0.0'});},
      get_output_settings(){return Promise.resolve({font:'normal'});},
      get_settings(){return Promise.resolve(settings);},
      set_settings(patch){window.__saved=patch;return Promise.resolve({success:true,settings:{...settings,...patch}});},
      set_output_settings(){return Promise.resolve({success:true});},
      set_dirty(){return Promise.resolve(true);},store_content(){return Promise.resolve({success:true});},startup_ready(){}}};
    await ensureTurndown();
  });
});
test('Preview/Source shortcut is the first row of Settings and can be changed',async({page})=>{
  await page.evaluate(()=>loadContent('/tmp/doc.md','Hello',720,false,false));
  await page.evaluate(()=>openSettings());
  const first=page.locator('#modalBody .set-row').first();
  await expect(first).toContainText('Switch Preview / Source');
  await expect(first.locator('.set-shortcut-btn')).toHaveText('⌘E');
  await first.locator('.set-shortcut-btn').click();
  await page.keyboard.press('Meta+c');                       // already used elsewhere: refused
  await expect(page.locator('.set-shortcut-note')).toBeVisible();
  await page.keyboard.press('Meta+Shift+u');
  await expect(first.locator('.set-shortcut-btn')).toHaveText('⇧⌘U');
  await page.locator('#modalActions .modal-close').last().click();
  await expect.poll(()=>page.evaluate(()=>window.__saved&&window.__saved.toggle_shortcut)).toBe('cmd+shift+u');
});
test('the chosen shortcut switches views and the old one stops working',async({page})=>{
  await page.evaluate(()=>{appSettings.toggle_shortcut='cmd+shift+u';loadContent('/tmp/doc.md','Hello',720,false,false);});
  await page.keyboard.press('Meta+e');
  expect(await page.evaluate(()=>isSource)).toBe(false);
  await page.keyboard.press('Meta+Shift+u');
  await expect.poll(()=>page.evaluate(()=>isSource)).toBe(true);
});
test('the page ends with the mark and copy / share actions, not a read-time line',async({page})=>{
  await page.evaluate(()=>loadContent('/tmp/doc.md','# T\n\nHello',720,false,false));
  const end=page.locator('.read-end');
  await expect(end).toBeVisible();
  await expect(end).toContainText('mdPreview');
  await expect(end).not.toContainText('min read');
  await expect(end.locator('button')).toHaveCount(3);
});
test('outline: colour-only selection, word count at the bottom with three ways to count, smooth jump',async({page})=>{
  const body=Array.from({length:60},(_,i)=>'段落 '+i+' 一些中文和 English words here.\n').join('\n');
  await page.setViewportSize({width:1200,height:700});
  await page.evaluate(b=>loadContent('/tmp/doc.md','# 甲\n\nhello world 你好\n\n## 乙\n\n'+b+'\n## 丙\n\n'+b+'\n## 丁\n\nEnd',720,false,false),body);
  const footer=page.locator('#tocSidebar .toc-count');
  await expect(footer).toBeVisible();
  await expect(footer).toContainText('words');
  const gap=await footer.evaluate(el=>innerHeight-el.getBoundingClientRect().bottom);
  expect(gap).toBeLessThan(24);                                  // pinned to the window's lower edge
  await footer.locator('button').click();
  await expect(page.locator('.count-menu button')).toHaveCount(3);
  await page.locator('.count-menu button').nth(1).click();
  await expect(footer).toContainText('characters');
  await page.click('#tocSidebar a >> nth=2');
  const active=page.locator('#tocSidebar a.toc-active');
  await expect(active).toHaveCount(1);
  const bg=await active.evaluate(el=>getComputedStyle(el).backgroundColor);
  expect(bg).toBe('rgba(0, 0, 0, 0)');
  const early=await page.evaluate(()=>document.querySelector('.scroll-wrap').scrollTop);
  await expect.poll(()=>page.evaluate(()=>document.querySelector('.scroll-wrap').scrollTop),{timeout:4000}).toBeGreaterThan(early);
  await page.evaluate(()=>{document.getElementById('tocSidebar').classList.add('hidden');});
  await expect(footer).not.toBeInViewport();
});
