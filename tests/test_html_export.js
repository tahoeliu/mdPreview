const assert=require('node:assert/strict');
const fs=require('node:fs'); const path=require('node:path');
const {createApp}=require('./helpers');
(async()=>{const app=await createApp();try{
 const w=app.w;
 w.pywebview.api.get_export_css=()=>({css:['tokens','content','print'].map(n=>fs.readFileSync(path.join(__dirname,'../css/'+n+'.css'),'utf8')).join('\n'),version:'1.5.0'});
 let html; w.pywebview.api.export_as_write=(p,f,c)=>{html=c;return {success:true}};
 await app.load('---\nlang: ja\n---\n# 中文标题\n\n## 二\n\n## 三\n\n## 四\n\n## 五\n\n```js\nconst a = 1;\n```');
 await w.exportAsWrite('/tmp/test.html','html');
 assert.match(html,/<html lang="ja"/);assert.match(html,/name="generator"/);assert.match(html,/export-toc/);assert.match(html,/\.tok-keyword/);assert.match(html,/<article class="markdown"/);assert.doesNotMatch(html,/<(?:link|script)\b/);
 console.log('HTML导出断言通过');
}finally{app.close()}})().catch(e=>{console.error(e);process.exitCode=1});
