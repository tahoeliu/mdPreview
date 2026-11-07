const {test,expect}=require('@playwright/test');
const fs=require('node:fs');const path=require('node:path');const {pathToFileURL}=require('node:url');
const ROOT=path.resolve(__dirname,'..');
function fixture(bytes){const block='# Section\n\nMixed 中文 content with **bold** text.\n\n| A | B |\n| --- | --- |\n| one | two |\n\n```javascript\nconst value = 42;\n```\n\n';return block.repeat(Math.ceil(bytes/Buffer.byteLength(block)));}
test('WebKit 大文档性能预算',async({page,browserName})=>{
 expect(browserName).toBe('webkit');test.setTimeout(180000);
 await page.goto(pathToFileURL(path.join(ROOT,'index.html')).href);
 await page.waitForFunction(()=>typeof loadContent==='function');
 const results=[];
 for(const bytes of [100*1024,1024*1024,5*1024*1024]){
  const result=await page.evaluate(async markdown=>{
   const begin=performance.now();await loadContent('performance.md',markdown,720,false,false);const render=performance.now()-begin;
   let start=performance.now();await toggleView();const source=performance.now()-start;
   start=performance.now();await toggleView();const preview=performance.now()-start;
   start=performance.now();const wrap=document.querySelector('.scroll-wrap');wrap.scrollTop=wrap.scrollHeight;updateScrollSpy();const toc=performance.now()-start;
   return {render,source,preview,toc,stages:RenderPerformance.snapshot()};
  },fixture(bytes));results.push({bytes,...result});
 }
 fs.writeFileSync(path.join(ROOT,'WorkSpace/perf.json'),JSON.stringify({engine:browserName,measuredAt:new Date().toISOString(),results,coldStart:{status:'unverified',budgetMs:1500,reason:'浏览器页面不等于原生进程启动'}},null,2));
 expect(results[1].render).toBeLessThan(1500);expect(results[2].render).toBeLessThan(30000);
});
test('原生冷启动预算',async()=>{
 expect(process.env.MDPREVIEW_COLD_START_RESULT,'需要原生进程到首屏的实测数据').toBeTruthy();
 expect(process.env.MDPREVIEW_VERIFY_APP,'必须绑定待验收应用').toBeTruthy();
 const data=JSON.parse(fs.readFileSync(process.env.MDPREVIEW_COLD_START_RESULT,'utf8'));
 const {bundleDigest}=await import('../scripts/verify-matrix.mjs');
 expect(data.bundleSha256).toBe(bundleDigest(process.env.MDPREVIEW_VERIFY_APP));
 expect(data.version).toBe(fs.readFileSync(path.join(ROOT,'VERSION'),'utf8').trim());
 expect(typeof data.environment).toBe('string');expect(data.environment.trim()).not.toBe('');
 expect(Number.isFinite(Date.parse(data.measuredAt))).toBe(true);expect(Date.parse(data.measuredAt)).toBeLessThanOrEqual(Date.now());
 expect(data.kind).toBe('native-process-first-screen');expect(data.milliseconds).toBeGreaterThan(0);expect(data.milliseconds).toBeLessThan(1500);
});
