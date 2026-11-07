const {test,expect}=require('@playwright/test');
test('T06 输出失败恢复样式优先级并拒绝冲突',async({page})=>{
 await page.goto('/');
 await page.evaluate(async()=>{
  pywebview={api:{set_dirty(){},startup_ready(){},store_content(){},get_output_settings(){return {font:'normal'}},export_as_write(){return new Promise(r=>window.finishOutput=r)}}};
  await loadContent('/tmp/prep.md','# 标题\n\n正文',720,false,false);
  document.documentElement.style.setProperty('--print-font-size','13pt','important');
  window.pending=exportAsWrite('/tmp/prep.pdf','pdf');
 });
 await expect.poll(()=>page.evaluate(()=>typeof finishOutput)).toBe('function');
 expect(await page.evaluate(()=>exportAsWrite('/tmp/other.pdf','pdf'))).toEqual({success:false,error:'output-busy'});
 await page.evaluate(async()=>{finishOutput({success:false,error:'test'});await pending});
 expect(await page.evaluate(()=>[document.documentElement.getAttribute('data-output'),document.documentElement.style.getPropertyValue('--print-font-size'),document.documentElement.style.getPropertyPriority('--print-font-size')])).toEqual([null,'13pt','important']);
});
