const {chromium}=require('@playwright/test');
const {pathToFileURL}=require('node:url');const path=require('node:path');const assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({headless:true});try{
 const page=await browser.newPage();let requests=0;
 await page.route('https://example.com/**',route=>{requests++;return route.fulfill({status:200,contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWZkAAAAASUVORK5CYII=','base64')});});
 await page.goto(pathToFileURL(path.resolve(__dirname,'../index.html')).href);
 await page.waitForFunction(()=>typeof loadContent==='function');
 await page.evaluate(async()=>{window.pywebview={api:{set_dirty:()=>true,store_content:()=>({success:true}),startup_ready:()=>true}};await loadContent('/test.md','![外部](https://example.com/a.png)\n\n<img src="https://example.com/b.png" srcset="https://example.com/c.png 2x">',720,false,true);});
 assert.equal(requests,0);assert.equal(await page.locator('#content img[src]').count(),0);
 await page.locator('.remote-image-bar button').first().click();
 await page.waitForFunction(()=>[...document.querySelectorAll('#content img')].every(img=>img.complete));
 assert.ok(requests>0);
 assert.equal(await page.locator('[onclick]').count(),0);
 console.log('真实 Chromium：默认零远程图请求，明确加载后才请求；CSP脚本加载通过');
}finally{await browser.close();}})().catch(error=>{console.error(error);process.exitCode=1});
