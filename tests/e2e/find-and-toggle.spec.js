const {test,expect}=require('@playwright/test');
const fs=require('fs');
test.beforeEach(async({page})=>{
  await page.setViewportSize({width:900,height:600});
  await page.goto('/');
  await page.waitForFunction(()=>typeof loadContent==='function');
  await page.evaluate(async()=>{
    const settings={language:'en',appearance:'system',restore_session:false,auto_update:true,format_bar:false,font_size:16,reading_font:'sans',toggle_shortcut:'cmd+e',page_width:720,remote_images:'ask',auto_reload:true};
    window.pywebview={api:{get_export_css(){return Promise.resolve({css:'',version:'2.0.0'});},get_output_settings(){return Promise.resolve({font:'normal'});},get_settings(){return Promise.resolve(settings);},set_dirty(){return Promise.resolve(true);},store_content(){return Promise.resolve({success:true});},startup_ready(){}}};
    await ensureTurndown();
  });
  const md='# T\n\n'+'filler paragraph. '.repeat(400)+'\n\n| Name | Value |\n|---|--:|\n| alpha | 1 |\n| beta | 22 |\n\n- one\n- nested item\n\nHere[^1].\n\n[^1]: The footnote text.\n';
  await page.evaluate(m=>loadContent('/tmp/f.md',m,720,false,false),md);
  await page.waitForTimeout(500);
});
for(const q of ['alpha','beta','nested','footnote text']){
  test('Find highlights and scrolls to a match inside a table, list or footnote: '+q,async({page})=>{
    await page.evaluate(()=>openFindBar());
    await page.fill('#findInput',q); await page.keyboard.press('Enter');
    await expect(page.locator('mark.find-highlight.current')).toHaveCount(1);
    const inView=await page.evaluate(()=>{const r=document.querySelector('mark.current').getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight;});
    expect(inView).toBe(true);
  });
}
test('the outline toggle does not overlap the Find box',async({page})=>{
  await page.evaluate(()=>openFindBar());
  const r=await page.evaluate(()=>{const a=document.querySelector('.toc-toggle').getBoundingClientRect(),b=document.getElementById('findInput').getBoundingClientRect();return {toggleRight:a.right,inputLeft:b.left,toggleVisible:getComputedStyle(document.querySelector('.toc-toggle')).display!=='none'};});
  if(r.toggleVisible) expect(r.inputLeft).toBeGreaterThanOrEqual(r.toggleRight);
});
test('typing a query in source view never types into the document',async({page})=>{
  await page.evaluate(()=>{ toggleView(); });
  await page.waitForTimeout(400);
  const before=await page.evaluate(()=>document.getElementById('textarea').value);
  await page.evaluate(()=>openFindBar());
  await page.keyboard.type('beta item',{delay:40});
  const after=await page.evaluate(()=>({doc:document.getElementById('textarea').value,q:document.getElementById('findInput').value}));
  expect(after.q).toBe('beta item');
  expect(after.doc).toBe(before);
});
test('⌘F closes the Find box when it is already active, and the close button is always inside the window',async({page})=>{
  await page.evaluate(()=>openFindBar());
  await expect(page.locator('#findBar')).toBeVisible();
  const r=await page.evaluate(()=>document.getElementById('findClose').getBoundingClientRect().right);
  expect(r).toBeLessThanOrEqual(900);
  await page.keyboard.press('Meta+f');
  await expect(page.locator('#findBar')).toBeHidden();
  await page.keyboard.press('Meta+f');
  await expect(page.locator('#findBar')).toBeVisible();
  await page.locator('#findClose').click();
  await expect(page.locator('#findBar')).toBeHidden();
});
test('the code copy button is an icon, not text',async({page})=>{
  await page.evaluate(m=>loadContent('/tmp/c.md',m,720,false,false),'```js\nlet a = 1;\n```\n');
  const b=page.locator('.code-copy-btn');
  await expect(b).toHaveCount(1);
  expect(await b.evaluate(e=>e.textContent.trim())).toBe('');
  await expect(b.locator('svg')).toHaveCount(1);
  expect(await b.getAttribute('aria-label')).toBeTruthy();
});
test('in source view the close button is the last control of the Find bar',async({page})=>{
  await page.evaluate(()=>{toggleView();openFindBar();});
  await page.waitForTimeout(300);
  const r=await page.evaluate(()=>{const els=[...document.querySelectorAll('#findBar > *')].filter(e=>e.offsetParent!==null).map(e=>({id:e.id||e.className,right:e.getBoundingClientRect().right}));return {last:els.reduce((a,b)=>b.right>a.right?b:a),close:els.find(e=>e.id==='findClose')};});
  expect(r.close.right).toBeGreaterThanOrEqual(r.last.right-1);
});
