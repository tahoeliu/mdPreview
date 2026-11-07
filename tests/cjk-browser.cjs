const { chromium, webkit } = require('../node_modules/playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const out = path.join(root, 'WorkSpace/outputs');
(async () => {
 const results = [];
 for (const [name, engine] of Object.entries({chromium, webkit})) {
  const browser = await engine.launch({headless:true});
  try {
   const page = await browser.newPage({viewport:{width:1100,height:760},colorScheme:'light'});
   const errors = []; page.on('pageerror', e => errors.push(e.message));
   await page.route('**/*', route => route.request().url().startsWith('file:') ? route.continue() : route.abort());
   await page.goto('file://' + root + '/index.html');
   await page.waitForFunction(() => typeof loadContent === 'function');
   await page.evaluate(async () => {
    window.pywebview = {api:{set_dirty:async()=>true,store_content:async()=>({success:true}),startup_ready(){},save_file:async(p,c)=>{window.saved=c;return {success:true};},export_as_write:async(p,f,c)=>{window.exported=c;return {success:true};}}};
    await ensureTurndown();
    await loadContent('/tmp/synthetic-kya.md','# 文件B KYA与委托关系技术要求\n\n**身份对象与信任关系：**区分用户、服务主体、智能体、执行实例、委托方与被委托方。\n\n**身份与执行实例绑定：**规定身份材料、密钥及版本关联；核验用户授权是否对应预期实例。\n\n**委托关系与权限传递：**规定父子委托、跨平台核验及委托不扩权规则。\n\n**状态与生命周期：**规定身份状态、密钥轮换、版本变化、撤销与恢复的关联处理。\n\n**接口及符合性：**规定身份和委托证明的最低数据与验证方法。',720,false,false);
   });
   assert.equal(await page.locator('#content strong').count(),5);
   assert.equal(await page.locator('#content strong').first().evaluate(el=>getComputedStyle(el).fontWeight),'700');
   await page.screenshot({path:path.join(out,'cjk-'+name+'.png')});
   await page.keyboard.press('Meta+e');
   await page.locator('#textarea').fill('**标题：**正文');
   await page.keyboard.press('Meta+s');
   await page.waitForFunction(()=>window.saved==='**标题：**正文');
   await page.keyboard.press('Meta+e');
   await page.locator('#content strong').waitFor({state:'visible'});
   await page.locator('#content').click();
   await page.keyboard.press('Meta+End');
   await page.keyboard.type('!');
   assert.ok((await page.evaluate(()=>getCurrentMarkdown())).includes('**标题：**'));
   await page.evaluate(()=>exportAsWrite('/tmp/synthetic.html','html'));
   assert.ok((await page.evaluate(()=>window.exported)).includes('<strong>标题：</strong>'));
   assert.deepEqual(errors,[]);
   results.push({engine:name,result:'PASS',checks:['five labels','font 700','keyboard toggle','source edit','save bridge','preview edit','HTML export','page errors'],bridge:'mock: no user files written'});
  } finally { await browser.close(); }
 }
 fs.writeFileSync(path.join(out,'cjk-browser-results.json'),JSON.stringify(results,null,2));
 console.log(JSON.stringify(results,null,2));
})().catch(e=>{console.error(e);process.exitCode=1;});
