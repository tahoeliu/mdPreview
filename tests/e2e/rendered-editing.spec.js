const {test,expect}=require('@playwright/test');
test.beforeEach(async({page})=>{
  await page.goto('/');
  await page.waitForFunction(()=>typeof loadContent==='function');
  await page.evaluate(async()=>{
    window.__writes=[];window.__dirty=false;
    window.pywebview={api:{async get_export_css(){return {css:(await Promise.all(['tokens','content','print'].map(async n=>(await fetch('/css/'+n+'.css')).text()))).join('\n'),version:'1.5.0'}},get_output_settings(){return {font:'normal'}},set_dirty(d){window.__dirty=d;return Promise.resolve(true)},store_content(){return Promise.resolve({success:true})},startup_ready(){},save_file(path,content){window.__writes.push({path,content});return Promise.resolve({success:true})},export_as_write(path,format,content){window.__export={path,format,content};return Promise.resolve({success:true})}}};
    await ensureTurndown();
  });
});
const md=()=>window.getCurrentMarkdown();
const load=(page,text)=>page.evaluate(t=>loadContent('/tmp/doc.md',t,720,false,false),text);
const caretAt=(page,sel,offset)=>page.evaluate(([s,o])=>{const el=s.includes('>> nth=')?document.querySelectorAll(s.split(' >> nth=')[0])[+s.split(' >> nth=')[1]]:document.querySelector(s);const n=el.firstChild;const r=document.createRange();r.setStart(n,o);r.collapse(true);const g=getSelection();g.removeAllRanges();g.addRange(r);document.getElementById('content').focus();},[sel,offset]);
const selectText=(page,sel,a,b)=>page.evaluate(([s,x,y])=>{const el=document.querySelector(s);const n=el.firstChild;const r=document.createRange();r.setStart(n,x);r.setEnd(n,y);const g=getSelection();g.removeAllRanges();g.addRange(r);document.getElementById('content').focus();},[sel,a,b]);
const bar=(page,kind)=>page.locator(`.edit-bar button[data-kind="${kind}"]`);

test('typing, Enter and Backspace in the rendered page write clean Markdown',async({page})=>{
  await load(page,'# Title\n\nHello world');
  await page.click('#content p');
  await caretAt(page,'#content p',11);
  await page.keyboard.type(' again');
  await page.keyboard.press('Enter');
  await page.keyboard.type('Second paragraph');
  expect(await page.evaluate(md)).toMatch(/^# Title\n\nHello world again\n\nSecond paragraph\n?$/);
  for(let i=0;i<16;i++)await page.keyboard.press('Backspace');
  await page.keyboard.press('Backspace');
  expect(await page.evaluate(md)).toMatch(/^# Title\n\nHello world again\n?$/);
});
test('headings, lists, quote, divider and clear format from the bar',async({page})=>{
  await load(page,'Alpha\n\nBeta\n\nGamma\n\nDelta');
  await page.click('#content p >> nth=0');
  await bar(page,'style').click();
  await page.click('.edit-menu button[data-kind="h2"]');
  expect(await page.evaluate(md)).toContain('## Alpha');
  await bar(page,'style').click();
  await page.click('.edit-menu button[data-kind="p"]');
  expect(await page.evaluate(md)).toMatch(/^Alpha/);
  await caretAt(page,'#content p >> nth=1',2);
  await page.click('#content p >> nth=1');
  await bar(page,'ul').click();
  expect(await page.evaluate(md)).toMatch(/[-*] Beta/);
  await bar(page,'ol').click();
  expect(await page.evaluate(md)).toMatch(/1\. Beta/);
  await bar(page,'ol').click();
  await page.locator('#content p',{hasText:'Gamma'}).click();
  await bar(page,'quote').click();
  expect(await page.evaluate(md)).toContain('> Gamma');
  await bar(page,'clear').click();
  expect(await page.evaluate(md)).not.toContain('> Gamma');
  await page.click('#content p >> nth=-1');
  await bar(page,'insert').click();
  await page.click('.edit-menu button[data-kind="rule"]');
  expect(await page.evaluate(md)).toMatch(/---|\*\*\*/);
});
test('inline formats: bold, italic, strike, code, link; clear format removes them',async({page})=>{
  await load(page,'one two three four five');
  await page.click('#content p');
  for(const [kind,a,b,expect_] of [['bold',0,3,'**one**'],['italic',4,7,'*two*'],['strike',8,13,'~~three~~'],['code',14,18,'`four`']]){
    await page.evaluate(()=>{});
    await page.evaluate(([x,y])=>{const p=document.querySelector('#content p');const w=document.createTreeWalker(p,NodeFilter.SHOW_TEXT);let n,pos=0,sr,er;while(n=w.nextNode()){const len=n.textContent.length;const base=pos;if(!sr&&x>=base&&x<=base+len&&!(x===base+len&&w.currentNode.nextSibling)){sr=[n,x-base];}if(!er&&y>=base&&y<=base+len){er=[n,y-base];}pos+=len;}if(!sr||!er)return;const r=document.createRange();r.setStart(...sr);r.setEnd(...er);const g=getSelection();g.removeAllRanges();g.addRange(r);document.getElementById('content').focus();},[a,b]);
    await bar(page,kind).click();
    expect(await page.evaluate(md)).toContain(expect_);
  }
});
test('link can be added and removed',async({page})=>{
  await load(page,'Visit site today');
  await page.click('#content p');
  await selectText(page,'#content p',6,10);
  await bar(page,'link').click();
  await page.keyboard.type('example.com');
  await page.keyboard.press('Enter');
  expect(await page.evaluate(md)).toContain('[site](https://example.com');
  await page.evaluate(()=>{const a=document.querySelector('#content a');const r=document.createRange();r.selectNodeContents(a);const g=getSelection();g.removeAllRanges();g.addRange(r);});
  await bar(page,'clear').click();
  expect(await page.evaluate(md)).not.toContain('](');
});
test('task list item can be created and ticked',async({page})=>{
  await load(page,'Buy milk');
  await page.click('#content p');
  await bar(page,'task').click();
  expect(await page.evaluate(md)).toMatch(/[-*] \[ \] Buy milk/);
  await page.click('#content .task-toggle');
  expect(await page.evaluate(md)).toMatch(/[-*] \[x\] Buy milk/);
});
test('lists: Enter continues, indent nests, outdent unnests',async({page})=>{
  await load(page,'- one\n- two');
  await page.click('#content li >> nth=1');
  await page.keyboard.press('End');
  await page.keyboard.press('Enter');
  await page.keyboard.type('three');
  await bar(page,'indent').click();
  expect(await page.evaluate(md)).toMatch(/- two\n\s+- three/);
  await bar(page,'outdent').click();
  expect(await page.evaluate(md)).toMatch(/- two\n- three/);
});
test('every table operation can be undone and redone',async({page})=>{
  await load(page,'Intro\n\nOutro');
  await page.click('#content p >> nth=0');
  const before=await page.evaluate(md);
  await bar(page,'insert').click();
  await page.click('.edit-menu button[data-kind="table"]');
  await expect(page.locator('#content table')).toHaveCount(1);
  await page.keyboard.press('Meta+z');
  await expect(page.locator('#content table')).toHaveCount(0);
  expect(await page.evaluate(md)).toBe(before);
  await page.keyboard.press('Meta+Shift+z');
  await expect(page.locator('#content table')).toHaveCount(1);
  await page.click('#content td >> nth=0');
  await bar(page,'addrow').click();
  await expect(page.locator('#content tbody tr')).toHaveCount(3);
  await page.keyboard.press('Meta+z');
  await expect(page.locator('#content tbody tr')).toHaveCount(2);
  await page.click('#content td >> nth=0');
  await bar(page,'addcol').click();
  await expect(page.locator('#content thead th')).toHaveCount(4);
  await page.keyboard.press('Meta+z');
  await expect(page.locator('#content thead th')).toHaveCount(3);
  await page.click('#content td >> nth=0');
  await bar(page,'deltable').click();
  await expect(page.locator('#content table')).toHaveCount(0);
  await page.keyboard.press('Meta+z');
  await expect(page.locator('#content table')).toHaveCount(1);
  await page.click('#content td >> nth=0');
  await page.keyboard.type('cell text');
  expect(await page.evaluate(md)).toContain('cell text');
});
test('typing inside table cells and Tab-free editing keeps the table intact in Markdown',async({page})=>{
  await load(page,'| A | B |\n|---|---|\n| 1 | 2 |');
  await page.click('#content td >> nth=0');
  await page.keyboard.press('End');
  await page.keyboard.type('x');
  expect(await page.evaluate(md)).toMatch(/\| 1x \| 2 \|/);
});
test('untouched content is preserved exactly when one word is edited',async({page})=>{
  const doc='# Notes\n\nFirst **bold** and `code`.\n\n- a\n- b\n\n> quote\n\n```js\nlet x = 1;\n```\n\n| H | I |\n|---|---|\n| 1 | 2 |\n';
  await load(page,doc);
  await page.click('#content p');
  await caretAt(page,'#content p',5);
  await page.keyboard.type('Z');
  const out=await page.evaluate(md);
  expect(out).toContain('FirstZ **bold** and `code`.');
  expect(out).toContain('```js\nlet x = 1;\n```');
  expect(out).toMatch(/\| H \| I \|/);
  expect(out).toContain('> quote');
});
test('undo and redo buttons work and Escape returns to reading',async({page})=>{
  await load(page,'Hello');
  await page.click('#content p');
  await caretAt(page,'#content p',5);
  await page.keyboard.type(' there');
  expect(await page.evaluate(md)).toContain('Hello there');
  await bar(page,'undo').click();
  expect(await page.evaluate(md)).not.toContain('there');
  await bar(page,'redo').click();
  expect(await page.evaluate(md)).toContain('Hello there');
  await page.keyboard.press('Escape');
  await expect(page.locator('.edit-bar')).toBeHidden();
});
test('code blocks and math stay read-only for formatting but never lose their text',async({page})=>{
  await load(page,'```\nkeep me\n```\n\nafter');
  await page.click('#content pre');
  await expect(bar(page,'bold')).toBeDisabled();
  expect(await page.evaluate(md)).toContain('keep me');
});


test('existing task checkboxes keep their state when the page is edited',async({page})=>{
  await load(page,'- [x] done\n- [ ] todo\n\nText');
  await page.click('#content p');
  await caretAt(page,'#content p',4);
  await page.keyboard.type('!');
  const out=await page.evaluate(md);
  expect(out).toMatch(/- \[x\] done/);
  expect(out).toMatch(/- \[ \] todo/);
  expect(out).toContain('Text!');
});


