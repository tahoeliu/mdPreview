const {test,expect}=require('@playwright/test');
test('T04 原生打印等待延迟并在取消失败后恢复源码状态',async({page})=>{
 await page.goto('/');
 await page.evaluate(async()=>{
  window.pywebview={api:{set_dirty(){},store_content(){},startup_ready(){},get_output_settings(){return {font:'normal'}},print_document(){return new Promise(r=>window.finishPrint=r)}}};
  await loadContent('/tmp/print.md','# 标题\n\n正文',720,false,true);
  await toggleView();
  window.pendingPrint=printDocument();
 });
 await expect(page.locator('html')).toHaveAttribute('data-output','print');
 await expect(page.locator('#textarea')).not.toBeVisible();
 expect(await page.evaluate(()=>printDocument())).toEqual({success:false,error:'output-busy'});
 await expect.poll(()=>page.evaluate(()=>typeof window.finishPrint)).toBe('function');
 await page.evaluate(async()=>{finishPrint({success:false,cancelled:true});await pendingPrint});
 await expect(page.locator('#textarea')).toBeVisible();
 await expect(page.locator('html')).not.toHaveAttribute('data-output','print');
 await page.evaluate(async()=>{pywebview.api.print_document=()=>Promise.reject(new Error('native'));await printDocument()});
 await expect(page.locator('#textarea')).toBeVisible();
});
