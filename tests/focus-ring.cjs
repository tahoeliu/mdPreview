const { chromium, webkit } = require('../node_modules/playwright');
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
    window.pywebview = {api:{set_dirty:async()=>true,store_content:async()=>({success:true}),startup_ready(){},save_file:async(p,c)=>({success:true}),export_as_write:async(p,f,c)=>({success:true})}};
    await ensureTurndown();
    await loadContent('/tmp/synthetic-focus.md','**标题：**正文测试','# Original title',false,false);
   });
   await page.locator('#content').waitFor({state:'visible'});
   // Case 1: keyboard-focus the contenteditable via Shift+Tab (forces :focus-visible in browsers honoring it)
   await page.keyboard.press('Shift+Tab');
   const viaKeyboard = await page.evaluate(() => {
     const c = document.getElementById('content');
     return { matches: c.matches(':focus-visible'), style: getComputedStyle(c).outlineStyle, width: getComputedStyle(c).outlineWidth };
   });
   // Case 2: programmatic focus (mouse-like path, most conservative check)
   const viaProgram = await page.evaluate(() => {
     const c = document.getElementById('content');
     c.focus({preventScroll:true});
     return { matches: c.matches(':focus-visible'), style: getComputedStyle(c).outlineStyle, width: getComputedStyle(c).outlineWidth };
   });
   assert.equal(viaKeyboard.style, 'none', `keyboard focus outline on #content should be none, got ${JSON.stringify(viaKeyboard)}`);
   assert.equal(viaProgram.style, 'none', `programmatic focus outline on #content should be none, got ${JSON.stringify(viaProgram)}`);
   // Source-mode textarea must also stay ring-free
   await page.keyboard.press('Meta+e');
   const ta = await page.evaluate(() => {
     const t = document.getElementById('textarea');
     t.focus();
     return { style: getComputedStyle(t).outlineStyle };
   });
   assert.equal(ta.style, 'none', `textarea focus outline should be none, got ${JSON.stringify(ta)}`);
   // Controls keep focus indication: expand the find bar first, then focus its visible button
   await page.keyboard.press('Meta+f');
   await page.waitForFunction(() => {
     const bar = document.getElementById('findBar');
     return bar && !bar.classList.contains('hidden') && getComputedStyle(bar).display !== 'none';
   });
   const btn = page.locator('#findClose');
   await btn.waitFor({state:'visible'});
   const btnOutline = await btn.evaluate(el => {
     el.focus();
     return getComputedStyle(el).outlineStyle;
   });
   assert.equal(btnOutline, 'solid', `control button focus ring must remain, got ${btnOutline}`);
   // Theme coverage: dark mode must keep the same behavior
   const darkContent = await page.evaluate(async () => {
     document.documentElement.classList.add('dark');
     await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
     const c = document.getElementById('content');
     c.focus({preventScroll:true});
     return getComputedStyle(c).outlineStyle;
   });
   assert.equal(darkContent, 'none', `dark theme content focus ring should be none, got ${darkContent}`);
   assert.deepEqual(errors,[]);
   await page.screenshot({path:path.join(out,'focus-ring-'+name+'.png')});
   results.push({engine:name,result:'PASS',checks:['content keyboard focus ring suppressed','content programmatic focus ring suppressed','textarea focus ring suppressed','control focus ring kept','page errors']});
  } finally { await browser.close(); }
 }
 require('node:fs').writeFileSync(path.join(out,'focus-ring-results.json'),JSON.stringify(results,null,2));
 console.log(JSON.stringify(results,null,2));
})().catch(e=>{console.error(e);process.exitCode=1;});
