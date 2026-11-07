const {test,expect}=require('@playwright/test');
test('T09 暗色手机PNG使用540px原生快照并恢复',async({page})=>{
 await page.emulateMedia({colorScheme:'dark'});await page.goto('/');
 const result=await page.evaluate(async()=>{
  window.pywebview={api:{set_dirty(){},startup_ready(){},store_content(){},get_output_settings(){return {png_width:'mobile'}},export_as_write(path,format,payload,size){window.capture={format,payload,size,bg:getComputedStyle(document.body).backgroundColor};return {success:true,paths:[path]}}}};
  await loadContent('/tmp/png.md','# 图片\n\n正文\n\n```js\nconst a=1;\n```',720,false,false);
  const before=document.querySelector('.page').style.cssText;
  await exportAsWrite('/tmp/png.png','png');
  return {capture:window.capture,restored:document.querySelector('.page').style.cssText===before,output:document.documentElement.hasAttribute('data-output')};
 });
 expect(result.capture.size.width).toBe(540);expect(result.capture.payload).toBe('');expect(result.capture.bg).toBe('rgb(255, 255, 255)');expect(result.restored).toBe(true);expect(result.output).toBe(false);
});
