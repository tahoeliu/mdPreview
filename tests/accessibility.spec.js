const {test,expect}=require('@playwright/test');
const path=require('node:path');const {pathToFileURL}=require('node:url');
test('阅读与设置无严重无障碍问题',async({page})=>{
 const AxeBuilder=require('@axe-core/playwright').default;
 await page.goto(pathToFileURL(path.resolve(__dirname,'../index.html')).href);
 await page.waitForFunction(()=>typeof loadContent==='function');
 await page.evaluate(()=>loadContent('accessibility.md','# 标题\n\n## 第二节\n\n- [ ] 任务\n\n```js\nconst x=1;\n```',720,false,true));
 for(const reducedMotion of ['reduce','no-preference']){
  await page.emulateMedia({reducedMotion});
  const result=await new AxeBuilder({page}).analyze();
  expect(result.violations.filter(x=>['serious','critical'].includes(x.impact))).toEqual([]);
 }
});
