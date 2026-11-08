const {test,expect}=require('@playwright/test');
const path=require('node:path');const {pathToFileURL}=require('node:url');

const SETTINGS={language:'system',restore_session:false,auto_update:false,font_size:16,page_width:720,remote_images:'ask',auto_reload:true};
const OUTPUT={paper:'auto',margins:'normal',font:'normal',page_numbers:true,show_urls:false,hide_frontmatter:true,h1_new_page:false,pdf_layout:'paged',png_width:'original'};
const DOCUMENT='# 标题\n\n## 第二节\n\n正文里的**加粗**文字\n\n- [ ] 任务\n\n> [!NOTE]\n> 提示块\n\n```js\nconst x=1;\n```\n\n| 列 A | 列 B |\n| --- | --- |\n| 一 | 二 |\n\n[链接](https://example.com)';

async function violations(page){
 const AxeBuilder=require('@axe-core/playwright').default;
 const result=await new AxeBuilder({page}).analyze();
 return result.violations.filter(x=>['serious','critical'].includes(x.impact)).map(x=>({id:x.id,impact:x.impact,nodes:x.nodes.slice(0,3).map(n=>n.html.slice(0,120))}));
}

// 每个界面状态都要在浅色/深色、减弱动态效果开/关下通过 serious 及以上检查。
for(const [state,prepare] of [
 ['阅读视图',async page=>{await page.evaluate(d=>loadContent('accessibility.md',d,720,false,true),DOCUMENT);}],
 ['设置对话框',async page=>{
   await page.evaluate(([settings,output])=>{window.pywebview={api:{get_settings:async()=>settings,get_output_settings:async()=>output,get_app_info:async()=>({version:'2.0.0'}),set_settings:async()=>({success:true,settings})}};},[SETTINGS,OUTPUT]);
   await page.evaluate(d=>loadContent('accessibility.md',d,720,false,true),DOCUMENT);
   await page.evaluate(()=>openSettings());await page.waitForSelector('#modalOverlay.visible');}],
 ['查找栏',async page=>{await page.evaluate(d=>loadContent('accessibility.md',d,720,false,true),DOCUMENT);await page.evaluate(()=>openFindBar());await page.waitForSelector('#findBar.visible');}],
 ['空白文档欢迎页',async page=>{await page.evaluate(()=>loadContent('Untitled.md','',720,false,true));}],
 ['长文阅读辅助与跳转标题',async page=>{
   const long='# 长文\n\n'+Array.from({length:12},(_,i)=>'## 第 '+(i+1)+' 节\n\n'+'这是一段很长的正文，用来让文档超过两屏。'.repeat(40)+'\n').join('\n');
   await page.evaluate(d=>loadContent('accessibility.md',d,720,false,true),long);
   await page.evaluate(()=>{document.querySelector('.scroll-wrap').scrollTop=800;});
   await page.waitForSelector('.read-hud.on');
   await page.evaluate(()=>openGoToHeading());await page.waitForSelector('#gotoOverlay');}],
 ['顶部格式工具条',async page=>{
   await page.evaluate(d=>loadContent('accessibility.md',d,720,false,true),DOCUMENT);
   await page.click('#content p');
   await page.waitForSelector('.edit-bar:not([hidden])');
   await page.click('.edit-bar button[data-kind="table"]');
   await page.waitForSelector('.edit-table-group:not([hidden])');}],
 ['源码视图',async page=>{await page.evaluate(d=>loadContent('accessibility.md',d,720,false,true),DOCUMENT);await page.evaluate(()=>toggleView());}],
]){
 for(const colorScheme of ['light','dark']){
  test(`无严重无障碍问题：${state}（${colorScheme}）`,async({page})=>{
   await page.goto(pathToFileURL(path.resolve(__dirname,'../index.html')).href);
   await page.waitForFunction(()=>typeof loadContent==='function');
   await prepare(page);
   for(const reducedMotion of ['reduce','no-preference']){
    await page.emulateMedia({reducedMotion,colorScheme});
    expect(await violations(page),`${state}/${colorScheme}/${reducedMotion}`).toEqual([]);
   }
  });
 }
}
