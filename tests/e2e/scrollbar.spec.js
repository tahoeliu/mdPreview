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
test('the scrollbar is invisible at rest, shows while scrolling and fades away a moment later',async({page})=>{
  const md=Array.from({length:120},(_,i)=>'## Section '+i+'\n\n'+'Some words to read. '.repeat(30)).join('\n\n');
  await page.evaluate(m=>loadContent('/tmp/long.md',m,720,false,false),md);
  const thumb=()=>page.evaluate(()=>document.querySelector('.read-thumb').classList.contains('on'));
  await page.waitForTimeout(500);
  expect(await thumb()).toBe(false);
  await page.mouse.move(300,300); await page.mouse.wheel(0,600);
  await expect.poll(thumb).toBe(true);
  const box=await page.evaluate(()=>{const t=document.querySelector('.read-thumb').getBoundingClientRect();return {top:t.top,h:t.height,vh:innerHeight};});
  expect(box.h).toBeGreaterThanOrEqual(32); expect(box.top).toBeGreaterThan(0); expect(box.top+box.h).toBeLessThanOrEqual(box.vh);
  await expect.poll(thumb,{timeout:5000}).toBe(false);
  // the native scrollbar is gone
  expect(await page.evaluate(()=>getComputedStyle(document.querySelector('.scroll-wrap')).scrollbarWidth)).toBe('none');
});
