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


test('new table: typing lands in the first body cell; Enter and Tab move between cells and keep the table intact',async({page})=>{
  await load(page,'Intro\n\nOutro');
  await page.click('#content p >> nth=0');
  await bar(page,'insert').click();
  await page.click('.edit-menu button[data-kind="table"]');
  await page.keyboard.type('等等');
  await page.keyboard.press('Enter');
  await page.keyboard.type('下一行');
  await page.keyboard.press('Tab');
  await page.keyboard.type('右');
  const shape=await page.evaluate(()=>{const t=document.querySelector('#content table');return {rows:t.rows.length,cells:[...t.rows].map(r=>r.cells.length),text:[...t.tBodies[0].rows].map(r=>[...r.cells].map(c=>c.textContent))};});
  expect(shape.cells).toEqual([3,3,3]);
  expect(shape.text[0][0]).toBe('等等');
  expect(shape.text[1][0]).toBe('下一行');
  expect(shape.text[1][1]).toBe('右');
  expect(await page.evaluate(md)).toMatch(/\| 等等 \|/);
  await page.keyboard.press('Enter');                       // last row: a new row is added
  expect(await page.evaluate(()=>document.querySelector('#content table').rows.length)).toBe(4);
});
test('link editor has a back button, apply and remove',async({page})=>{
  await load(page,'Visit site today');
  await page.click('#content p');
  await selectText(page,'#content p',6,10);
  await bar(page,'link').click();
  await expect(page.locator('.edit-link-back')).toBeVisible();
  await page.locator('.edit-link-back').click();
  await expect(bar(page,'bold')).toBeVisible();
  await selectText(page,'#content p',6,10);
  await bar(page,'link').click();
  await page.keyboard.type('example.com');
  await page.locator('.edit-bar .edit-done').click();
  expect(await page.evaluate(md)).toContain('[site](https://example.com');
  await page.evaluate(()=>{const a=document.querySelector('#content a');const r=document.createRange();r.selectNodeContents(a);const g=getSelection();g.removeAllRanges();g.addRange(r);});
  await bar(page,'link').click();
  await page.locator('.edit-link-remove').click();
  expect(await page.evaluate(md)).not.toContain('](');
});
test('indent works on paragraphs and list items; outdent only where it means something',async({page})=>{
  await load(page,'Plain\n\n> quoted\n\n- a\n- b');
  await page.locator('#content p',{hasText:'Plain'}).click();
  await expect(bar(page,'indent')).toBeEnabled();
  await expect(bar(page,'outdent')).toBeDisabled();
  await bar(page,'indent').click();
  expect(await page.evaluate(md)).toMatch(/- Plain/);
  await page.locator('#content blockquote').click();
  await expect(bar(page,'outdent')).toBeEnabled();
  await page.locator('#content li',{hasText:'b'}).last().click();
  await bar(page,'indent').click();
  expect(await page.evaluate(md)).toMatch(/- a\n\s+- b/);
});
test('task button toggles on and off, shows as selected and hides the bullet',async({page})=>{
  await load(page,'Buy milk');
  await page.click('#content p');
  await bar(page,'task').click();
  await expect(bar(page,'task')).toHaveClass(/on/);
  expect(await page.evaluate(()=>getComputedStyle(document.querySelector('#content li')).listStyleType)).toBe('none');
  await bar(page,'task').click();
  expect(await page.evaluate(md)).not.toContain('[ ]');
});
test('text style menu offers Body and Heading 1–6',async({page})=>{
  await load(page,'Alpha');
  await page.click('#content p');
  await bar(page,'style').click();
  await expect(page.locator('.edit-menu button')).toHaveCount(7);
  await page.locator('.edit-menu button[data-kind="h5"]').click();
  expect(await page.evaluate(md)).toContain('##### Alpha');
});
test('Insert menu: code block, divider, note, diagram and formula',async({page})=>{
  await load(page,'First\n\nLast');
  for(const [kind,check] of [['codeblock',()=>page.locator('#content pre')],['rule',()=>page.locator('#content hr')],['note',()=>page.locator('#content .markdown-alert')],['formula',()=>page.locator('#content .math-block')],['diagram',()=>page.locator('#content .mermaid-diagram')]]){
    await page.click('#content p >> nth=0');
    await bar(page,'insert').click();
    await page.click(`.edit-menu button[data-kind="${kind}"]`);
    await expect(check()).toHaveCount(1,{timeout:15000});
  }
  const out=await page.evaluate(md);
  expect(out).toContain('> [!NOTE]');
  expect(out).toContain('```mermaid');
  expect(out).toMatch(/\$\$/);
  expect(out).toMatch(/---/);
  await page.keyboard.press('Meta+z');
});
test('the bar covers the top of the page instead of pushing it down, and fades in and out',async({page})=>{
  await load(page,'# Title\n\nHello');
  const top=await page.evaluate(()=>document.querySelector('#content h1').getBoundingClientRect().top);
  await page.click('#content p');
  await expect(page.locator('.edit-bar')).toBeVisible();
  const after=await page.evaluate(()=>document.querySelector('#content h1').getBoundingClientRect().top);
  expect(after).toBe(top);
  await page.keyboard.press('Escape');
  await expect(page.locator('.edit-bar')).toBeHidden();
});
test('an existing Mermaid diagram (with arrows) survives editing the text next to it',async({page})=>{
  await load(page,'```mermaid\ngraph TD\n  A --> B\n```\n\nText');
  await expect(page.locator('#content .mermaid-diagram')).toHaveCount(1,{timeout:15000});
  await page.locator('#content p',{hasText:'Text'}).click();
  await caretAt(page,'#content p',4);
  await page.keyboard.type('!');
  const out=await page.evaluate(md);
  expect(out).toContain('```mermaid\ngraph TD\n  A --> B\n```');
  expect(out).toContain('Text!');
});
test('Insert ▸ Table offers a size grid on hover and inserts exactly that size',async({page})=>{
  await load(page,'Intro\n\nOutro');
  await page.click('#content p >> nth=0');
  await bar(page,'insert').click();
  await page.locator('.edit-menu button[data-kind="table"]').hover();
  await expect(page.locator('.edit-picker')).toBeVisible();
  await page.locator('.edit-picker-cell[data-r="4"][data-c="5"]').hover();
  await expect(page.locator('.edit-picker-size')).toHaveText('4 × 5');
  await page.locator('.edit-picker-cell[data-r="4"][data-c="5"]').click();
  const shape=await page.evaluate(()=>{const t=document.querySelector('#content table');return [t.rows.length,t.rows[0].cells.length];});
  expect(shape).toEqual([4,5]);
  await page.keyboard.press('Meta+z');
  await expect(page.locator('#content table')).toHaveCount(0);
});
test('toolbar icons share one visual size',async({page})=>{
  await load(page,'Hello');
  await page.click('#content p');
  await expect(page.locator('.edit-bar button svg.edit-icon').first()).toBeVisible();
  const sizes=await page.evaluate(()=>[...document.querySelectorAll('.edit-bar > button svg.edit-icon')].map(svg=>{const g=svg.firstElementChild.getBoundingClientRect();return Math.round(Math.max(g.width,g.height));}));
  expect(sizes.length).toBeGreaterThan(10);
  expect(Math.max(...sizes)-Math.min(...sizes)).toBeLessThanOrEqual(4);
});
test('section arrows appear only while a heading is hovered; the outline toggle clears the top bar',async({page})=>{
  await page.setViewportSize({width:1200,height:760});
  await load(page,'# One\n\ntext\n\n## Two\n\nmore\n\n## Three\n\nlast');
  await expect(page.locator('.fold-toggle').first()).toBeAttached();
  const shown=()=>page.evaluate(()=>[...document.querySelectorAll('.fold-toggle')].map(b=>+getComputedStyle(b).opacity));
  expect((await shown()).every(o=>o===0)).toBe(true);
  await page.locator('#content h2').first().hover();
  await expect.poll(async()=>(await shown()).filter(o=>o>0.2).length).toBe(1);
  await page.mouse.move(600,700);
  await expect.poll(async()=>(await shown()).every(o=>o===0),{timeout:3000}).toBe(true);
  await page.click('#content p >> nth=0');
  await expect(page.locator('.edit-bar')).toBeVisible();
  await page.waitForTimeout(400);
  const gap=await page.evaluate(()=>{const b=document.querySelector('.edit-bar').getBoundingClientRect(),t=document.getElementById('tocToggle').getBoundingClientRect();return t.top-b.bottom;});
  expect(gap).toBeGreaterThanOrEqual(0);
});
test('source mode shows the top bar by default and its buttons edit the Markdown text',async({page})=>{
  await load(page,'Alpha\n\nBeta');
  await page.keyboard.press('Meta+e');
  const sbar=page.locator('.source-bar');
  await expect(sbar).toBeVisible();
  const ta=page.locator('#textarea');
  await ta.evaluate(el=>{el.focus();el.setSelectionRange(0,5);});
  await sbar.locator('button[data-kind="bold"]').click();
  await expect(ta).toHaveValue(/^\*\*Alpha\*\*/);
  await sbar.locator('button[data-kind="style"]').click();
  await page.locator('.edit-menu button[data-kind="h2"]').click();
  await expect(ta).toHaveValue(/^## \*\*Alpha\*\*/);
  await ta.evaluate(el=>{el.focus();el.setSelectionRange(el.value.length-4,el.value.length);});
  await sbar.locator('button[data-kind="ul"]').click();
  await expect(ta).toHaveValue(/- Beta$/);
  await sbar.locator('button[data-kind="insert"]').click();
  await page.locator('.edit-menu button[data-kind="table"]').click();
  await expect(ta).toHaveValue(/\| --- \| --- \| --- \|/);
  await sbar.locator('button[data-kind="undo"]').click();
  await expect(ta).not.toHaveValue(/\| --- \|/);
  await page.keyboard.press('Meta+e');
  await expect(sbar).toBeHidden();
});
test('a single line break inside a paragraph survives editing, and Enter on an empty paragraph adds nothing',async({page})=>{
  await load(page,'Line one\nLine two\n\nPara');
  await page.locator('#content p',{hasText:'Line one'}).click();
  await page.keyboard.press('End');
  await page.keyboard.type('!');
  const out=await page.evaluate(md);
  expect(out).toMatch(/Line one\s*\n\s*Line two!?|Line one\s*\nLine two/);
  expect(out).not.toContain('Line oneLine');
  await page.locator('#content p',{hasText:'Para'}).click();
  await page.keyboard.press('End');
  await page.keyboard.press('Enter');
  await page.keyboard.press('Enter');
  await page.keyboard.press('Enter');
  const empties=await page.evaluate(()=>[...document.querySelectorAll('#content > p')].filter(p=>!p.textContent.trim()).length);
  expect(empties).toBeLessThanOrEqual(1);
  await page.keyboard.type('Next');
  expect(await page.evaluate(md)).toMatch(/Para\n\nNext/);
});
test('⌘B / ⌘I work in the rendered page and the B button lights up inside bold text',async({page})=>{
  await load(page,'plain **bold** end');
  await page.locator('#content strong').click();
  await expect(bar(page,'bold')).toHaveClass(/on/);
  await page.locator('#content p').click({position:{x:2,y:8}});
  await expect(bar(page,'bold')).not.toHaveClass(/on/);
  await selectText(page,'#content p',0,5);
  await page.keyboard.press('Meta+b');
  expect(await page.evaluate(md)).toContain('**plain**');
  await page.keyboard.press('Meta+i');
  expect(await page.evaluate(md)).toMatch(/\*\*\*?plain/);
});
