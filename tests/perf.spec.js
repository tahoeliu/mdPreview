const {test,expect}=require('@playwright/test');
const fs=require('node:fs');const path=require('node:path');const {pathToFileURL}=require('node:url');
const ROOT=path.resolve(__dirname,'..');
// 压力样本：每 160 字节一个标题/表格/代码，DOM 密度约为真实文档的 5–10 倍，用来暴露复杂度问题。
function dense(bytes){const block='# Section\n\nMixed 中文 content with **bold** text.\n\n| A | B |\n| --- | --- |\n| one | two |\n\n```javascript\nconst value = 42;\n```\n\n';return block.repeat(Math.ceil(bytes/Buffer.byteLength(block)));}
// 真实长文样本：大段中英混排正文，少量标题、列表、表格、代码。
function realistic(bytes){
 const prose='在长文档里，读者最关心的是**连续阅读**的流畅度与 *准确* 的排版。This paragraph mixes English and 中文 text, with `inline code` and a [link](https://example.com/page). 同一段文字会被重复很多次，用来模拟一份真实的长篇技术文档或者研究报告。';
 const parts=[];let n=0,size=0;
 while(size<bytes){n++;let b='';
  if(n%4===1)b+='## 第 '+n+' 节 Section '+n+'\n\n';
  b+=prose+'\n\n'+prose+prose+'\n\n';
  if(n%6===0)b+='- 列表项一 first item\n- 列表项二 second item\n- 列表项三 third item\n\n';
  if(n%10===0)b+='| 名称 | 数值 | 说明 |\n| --- | --- | --- |\n| alpha | 1 | first |\n| beta | 2 | second |\n\n';
  if(n%15===0)b+='```js\nfunction demo'+n+'(x) {\n  return x * 2;\n}\n```\n\n';
  parts.push(b);size+=Buffer.byteLength(b);}
 return parts.join('');
}
async function measure(page,markdown){
 return page.evaluate(async source=>{
  const begin=performance.now();await loadContent('performance.md',source,720,false,false);const render=performance.now()-begin;
  let start=performance.now();await toggleView();const sourceMode=performance.now()-start;
  start=performance.now();await toggleView();const preview=performance.now()-start;
  start=performance.now();const wrap=document.querySelector('.scroll-wrap');wrap.scrollTop=wrap.scrollHeight;updateScrollSpy();const toc=performance.now()-start;
  return {render,source:sourceMode,preview,toc,nodes:document.getElementById('content').querySelectorAll('*').length,stages:RenderPerformance.snapshot().slice(-8)};
 },markdown);
}
test('WebKit 大文档性能预算',async({page,browserName})=>{
 expect(browserName).toBe('webkit');test.setTimeout(240000);
 await page.goto(pathToFileURL(path.join(ROOT,'index.html')).href);
 await page.waitForFunction(()=>typeof loadContent==='function');
 const results=[];
 for(const bytes of [100*1024,1024*1024,5*1024*1024])results.push({kind:'realistic',bytes,...await measure(page,realistic(bytes))});
 for(const bytes of [200*1024,800*1024])results.push({kind:'dense',bytes,...await measure(page,dense(bytes))});
 fs.mkdirSync(path.join(ROOT,'WorkSpace'),{recursive:true});
 fs.writeFileSync(path.join(ROOT,'WorkSpace/perf.json'),JSON.stringify({engine:browserName,measuredAt:new Date().toISOString(),results,coldStart:{status:'unverified',budgetMs:1500,reason:'浏览器页面不等于原生进程启动'}},null,2));
 const by=(kind,bytes)=>results.find(r=>r.kind===kind&&r.bytes===bytes);
 const slack=process.env.CI?2:1;   // shared CI runners are slower and noisy; the growth-ratio check below stays strict everywhere
 expect(by('realistic',1024*1024).render,'1MB 真实文档首次渲染').toBeLessThan(1500*slack);
 expect(by('realistic',5*1024*1024).render,'5MB 真实文档首次渲染').toBeLessThan(30000*slack);
 // 复杂度守卫：4 倍体积的渲染时间不得超过 9 倍（线性≈4，旧的二次实现 800KB 约 24 倍）。
 const ratio=by('dense',800*1024).render/by('dense',200*1024).render;
 expect(ratio,'渲染时间随体积的增长必须接近线性').toBeLessThan(9);
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
