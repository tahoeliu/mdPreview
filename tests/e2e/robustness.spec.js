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
// Each fixture: a document that must survive "type a letter, delete it" in rendered mode byte for byte.
const FIX={
 setext:'Title\n=====\n\nSub\n---\n\nText here.\n',
 nestedLists:'- a\n  - b\n    - c\n  - d\n- e\n\n1. one\n   1. one-a\n   2. one-b\n2. two\n',
 orderedStart:'5. five\n6. six\n7. seven\n\nText.\n',
 taskNested:'- [x] done\n  - [ ] sub open\n  - [x] sub done\n- [ ] open\n\nText.\n',
 fences:'```js\nlet a = 1;\n```\n\n~~~py\nprint(1)\n~~~\n\n````md\n```inner\n```\n````\n\nText.\n',
 indentedCode:'Intro paragraph.\n\n    indented code\n    more code\n\nText.\n',
 tableAlign:'| Left | Center | Right |\n|:-----|:------:|------:|\n| **b** | `c` | [l](http://x.y) |\n| a\\|b | | 3 |\n\nText.\n',
 quotes:'> level one\n>\n> > level two\n> > - item\n>\n> back\n\nText.\n',
 rules:'Above\n\n---\n\nBelow\n\n***\n\nEnd\n',
 html:'<details>\n<summary>More</summary>\n\nHidden **text**.\n\n</details>\n\nText.\n',
 comments:'Before\n\n<!-- a comment -->\n\nAfter\n',
 footnotes:'Claim[^1] and another[^note].\n\n[^1]: First note.\n[^note]: Second note.\n',
 math:'Inline $a^2+b^2=c^2$ here.\n\n$$\n\\sum_{i=1}^n i = \\frac{n(n+1)}{2}\n$$\n',
 mermaid:'Text.\n\n```mermaid\nsequenceDiagram\n  A->>B: hi\n  B-->>A: yo\n```\n',
 alerts:'> [!NOTE]\n> Note text.\n\n> [!TIP]\n> Tip text.\n\n> [!WARNING]\n> Warn text.\n\nText.\n',
 links:'See [ref][1] and <https://example.com> and [inline](http://a.b "title").\n\n[1]: http://ref.example "Ref"\n',
 images:'![alt text](pic.png "Title")\n\nText.\n',
 emphasis:'snake_case_word and 2*3*4 and **bold** and *it* and ***both*** and ~~gone~~.\n',
 hardBreaks:'line one  \nline two\\\nline three\n\nNext paragraph.\n',
 escapes:'\\*not italic\\* and \\# not heading and 1\\. not list and \\[not link\\].\n',
 frontmatter:'---\ntitle: Doc\ntags: [a, b]\n---\n\n# Heading\n\nText.\n',
 cjk:'# 中文标题\n\n这是一段中文，包含**加粗**和`代码`，以及 English 混排。\n\n- 列表一\n- 列表二\n',
 emoji:'Hello 👋 world 🚀 and 👨‍👩‍👧 family.\n',
 longLine:'word '.repeat(400).trim()+'\n',
 emptyCells:'| A | B |\n|---|---|\n|  | x |\n| y |  |\n\nText.\n',
 mixed:'# H1\n\nPara with <kbd>Ctrl</kbd> and &amp; entity and &copy;.\n\n- item\n\n  continued para in item\n\n- next\n\n```\nplain fence\n```\n',
};
for(const [name,doc] of Object.entries(FIX)){
  test('round trip: '+name+' survives a no-op edit in the rendered page unchanged',async({page})=>{
    await load(page,doc);
    const cand=page.locator('#content > p, #content > h1, #content > h2');
    for(const which of ['first','last']){ await cand[which]().click(); await page.keyboard.type('Z'); await page.keyboard.press('Backspace'); }
    const out=await page.evaluate(md);
    const a=out.replace(/\s+$/,''),b=doc.replace(/\s+$/,'');
    if(a!==b) console.log('DIFF '+name+'\n--- expected\n'+b+'\n--- got\n'+a+'\n=== end');
    expect(a).toBe(b);
  });
}

// One edit in a document full of tricky constructs must change only that spot.
const BIG='---\ntitle: Big\n---\n\nSetext\n======\n\nIntro with [ref][1] and <https://example.com> and snake_case.\n\n<!-- keep me -->\n\n- a\n  - b\n    - c\n- d\n\n- [x] done\n- [ ] open\n\n~~~py\nprint(1)\n~~~\n\n| A | B |\n|:--|--:|\n| 1 | 2 |\n\n> quote line\n\n***\n\n<details>\n<summary>More</summary>\n\nHidden.\n\n</details>\n\nFootnote[^n] here.\n\n![pic](a.png "Title")\n\n[1]: http://ref.example "Ref"\n[^n]: The note.\n\nEditable paragraph here.\n\nTail.\n';
const rest=(doc,a,b)=>doc.replace(a,b);
test('editing one paragraph changes only that paragraph in a document full of tricky syntax',async({page})=>{
  await load(page,BIG);
  const p=page.locator('#content p',{hasText:'Editable paragraph here.'});
  await p.click();
  await page.keyboard.press('End');
  await page.keyboard.type(' EDITED');
  expect((await page.evaluate(md)).replace(/\s+$/,'')).toBe(rest(BIG,'Editable paragraph here.','Editable paragraph here. EDITED').replace(/\s+$/,''));
});
test('editing a list item only rewrites that list; the rest stays exactly as written',async({page})=>{
  await load(page,BIG);
  await page.locator('#content li',{hasText:'d'}).filter({hasNotText:'done'}).first().click();
  await page.keyboard.press('End'); await page.keyboard.type('X');
  const out=await page.evaluate(md);
  for(const keep of ['Setext\n======','[ref][1]','<https://example.com>','<!-- keep me -->','~~~py\nprint(1)\n~~~','|:--|--:|','***','<details>\n<summary>More</summary>','![pic](a.png "Title")','[1]: http://ref.example "Ref"','[^n]: The note.','title: Big']) expect(out).toContain(keep);
  expect(out).toContain('dX');
});
test('editing a table cell, a heading and a quote leaves the other blocks untouched',async({page})=>{
  await load(page,BIG);
  await page.locator('#content td',{hasText:'1'}).first().click(); await page.keyboard.press('End'); await page.keyboard.type('9');
  await page.locator('#content blockquote p').first().click(); await page.keyboard.press('End'); await page.keyboard.type('!');
  const out=await page.evaluate(md);
  expect(out).toContain('quote line!');
  expect(out).toMatch(/\| 19 \| 2 \|/);
  for(const keep of ['Setext\n======','[ref][1]','<!-- keep me -->','~~~py\nprint(1)\n~~~','***','<details>\n<summary>More</summary>','![pic](a.png "Title")','[1]: http://ref.example "Ref"']) expect(out).toContain(keep);
});
test('deleting a paragraph removes only it',async({page})=>{
  await load(page,BIG);
  await page.locator('#content p',{hasText:'Tail.'}).click();
  await page.locator('#content p',{hasText:'Tail.'}).click({clickCount:3}); await page.keyboard.press('Backspace');
  const out=await page.evaluate(md);
  expect(out).not.toContain('Tail.');
  for(const keep of ['<!-- keep me -->','~~~py\nprint(1)\n~~~','***','Editable paragraph here.','[1]: http://ref.example "Ref"']) expect(out).toContain(keep);
});
test('adding a new paragraph keeps everything else',async({page})=>{
  await load(page,BIG);
  await page.locator('#content p',{hasText:'Editable paragraph here.'}).click();
  await page.keyboard.press('End'); await page.keyboard.press('Enter'); await page.keyboard.type('Brand new paragraph');
  const out=await page.evaluate(md);
  expect(out).toContain('Editable paragraph here.\n\nBrand new paragraph');
  for(const keep of ['<!-- keep me -->','~~~py\nprint(1)\n~~~','***','Setext\n======','[1]: http://ref.example "Ref"']) expect(out).toContain(keep);
});
test('editing a paragraph keeps snake_case words and <autolinks> as written',async({page})=>{
  await load(page,'Use snake_case_name and <https://example.com> here.\n\nOther.\n');
  await page.locator('#content p').first().click({position:{x:2,y:8}});
  await page.keyboard.press('Meta+ArrowRight');
  await page.keyboard.type(' ok');
  expect((await page.evaluate(md)).replace(/\s+$/,'')).toBe('Use snake_case_name and <https://example.com> here. ok\n\nOther.');
});
test('Chinese bold: ** next to full-width punctuation and Latin text still renders as bold',async({page})=>{
  const cases={
    '**定位：**S1':'<strong>定位：</strong>S1',
    '这是**“引用”**文字':'这是<strong>“引用”</strong>文字',
    '前**（备注）**后':'前<strong>（备注）</strong>后',
    '**加粗**中文':'<strong>加粗</strong>中文',
    '使用**注意：**Abc和**重点，**123':'使用<strong>注意：</strong>Abc和<strong>重点，</strong>123',
  };
  for(const [src,expected] of Object.entries(cases)){
    const html=await page.evaluate(s=>MarkdownPipeline.parse(s),src);
    expect(html,src).toContain(expected);
  }
  // English text is unchanged: not bold, as CommonMark says
  const en=await page.evaluate(()=>MarkdownPipeline.parse('a**"quoted"**b and 2**3**4'));
  expect(en).not.toContain('<strong>"quoted"');
});
test('nested lists add no empty caret-landing paragraphs inside list items',async({page})=>{
  await load(page,'- a\n  - b\n    - c\n- d\n\nText\n');
  expect(await page.locator('#content li .render-caret-spacer').count()).toBe(0);
  const gap=await page.evaluate(()=>{const c=document.querySelector('#content li li li').getBoundingClientRect(),d=[...document.querySelectorAll('#content > ul > li')].pop().getBoundingClientRect();return d.top-c.bottom;});
  expect(gap).toBeLessThan(24);
});
test('turning paragraphs into bullet, numbered and task lists writes clean Markdown (no trailing spaces)',async({page})=>{
  await load(page,'Intro\n\nSecond paragraph here.\n\nThird line.\n\nFourth.\n');
  const bar=kind=>page.locator(`.edit-bar button[data-kind="${kind}"]`);
  const para=t=>page.locator('#content p',{hasText:t});
  await para('Second').click({clickCount:3}); await bar('ul').click();
  await para('Third').click({clickCount:3}); await bar('ol').click();
  await para('Fourth').click({clickCount:3}); await bar('task').click();
  const out=await page.evaluate(md);
  expect(out).toMatch(/^- Second paragraph here\.$/m);
  expect(out).toMatch(/^1\. Third line\.$/m);
  expect(out).toMatch(/^- \[ \] Fourth\.$/m);
  expect(out).not.toMatch(/ +$/m);
});
for(const scheme of ['light','dark']){
  test(`list markers and inline code stay readable in ${scheme} mode`,async({page})=>{
    await page.emulateMedia({colorScheme:scheme});
    await load(page,'- item with `code`\n\n1. numbered\n');
    const lum=c=>{const m=c.match(/[\d.]+/g).map(Number);return (0.2126*m[0]+0.7152*m[1]+0.0722*m[2])/255;};
    const got=await page.evaluate(()=>{const bg=getComputedStyle(document.body).backgroundColor;const li=document.querySelector('#content ul li'),ol=document.querySelector('#content ol li'),code=li.querySelector('code');return {bg,ul:getComputedStyle(li,'::marker').color,ol:getComputedStyle(ol,'::marker').color,code:getComputedStyle(code).color};});
    for(const k of ['ul','ol','code']) expect(Math.abs(lum(got[k])-lum(got.bg)),k).toBeGreaterThan(0.6);
  });
}
test('checked and unchecked task boxes have exactly the same size and shape',async({page})=>{
  await load(page,'- [x] done\n- [ ] open\n');
  const boxes=await page.evaluate(()=>[...document.querySelectorAll('#content .task-toggle')].map(b=>{const r=b.getBoundingClientRect(),c=getComputedStyle(b);return {w:Math.round(r.width*10)/10,h:Math.round(r.height*10)/10,radius:c.borderTopLeftRadius,border:c.borderTopWidth,checked:b.getAttribute('aria-checked')};}));
  expect(boxes).toHaveLength(2);
  expect(boxes[0].w).toBe(boxes[1].w); expect(boxes[0].h).toBe(boxes[1].h);
  expect(boxes[0].radius).toBe(boxes[1].radius); expect(boxes[0].border).toBe(boxes[1].border);
  expect(boxes[0].w).toBeGreaterThan(10);
});
for(const scheme of ['light','dark']){
  test(`bullets, numbers and both checkbox states share one colour in ${scheme} mode`,async({page})=>{
    await page.emulateMedia({colorScheme:scheme});
    await load(page,'- bullet\n\n1. number\n\n- [x] done\n- [ ] open\n');
    const c=await page.evaluate(()=>{const ul=document.querySelector('#content > ul:not(:has(.task-toggle)) > li'),ol=document.querySelector('#content ol > li'),on=document.querySelector('.task-toggle[aria-checked="true"]'),off=document.querySelector('.task-toggle[aria-checked="false"]');return {ul:getComputedStyle(ul,'::marker').color,ol:getComputedStyle(ol,'::marker').color,onBg:getComputedStyle(on).backgroundColor,onBorder:getComputedStyle(on).borderTopColor,offBorder:getComputedStyle(off).borderTopColor};});
    for(const k of ['ol','onBg','onBorder','offBorder']) expect(c[k],k).toBe(c.ul);
  });
}
test('callouts can be edited in the rendered page; the label stays fixed and other callouts are untouched',async({page})=>{
  const doc='> [!NOTE]\n> Note text.\n\n> [!WARNING]\n> Warn text.\n\nTail.\n';
  await load(page,doc);
  expect(await page.locator('.markdown-alert').first().evaluate(e=>e.isContentEditable)).toBe(true);
  await page.locator('.markdown-alert').first().locator('p:not(.markdown-alert-title)').click();
  await page.keyboard.press('End'); await page.keyboard.type(' more');
  await page.keyboard.press('Enter'); await page.keyboard.type('Second line');
  const out=(await page.evaluate(md)).replace(/\s+$/,'');
  expect(out).toContain('> [!NOTE]\n> Note text. more\n>\n> Second line');
  expect(out).toContain('> [!WARNING]\n> Warn text.\n\nTail.');
  expect(await page.locator('.markdown-alert-title').first().getAttribute('contenteditable')).toBe('false');
});

// ── Tables must be edited perfectly: only the touched cell changes, everything else is exactly as written ──
const TABLE_DOC='Before.\n\n|Name|Qty|Note|\n|:--|:-:|--:|\n|apple|1|**fresh** `code`|\n|a\\|b||[link](http://x.y)|\n|中文单元格|3|最后一列|\n\nBetween.\n\n| A | B |\n|---|---|\n| one | two |\n\nAfter.\n';
const cell=(page,text)=>page.locator('#content td, #content th',{hasText:text}).first();
test('table: editing one cell changes only that cell; alignment, formatting, escaped pipe, empty cell and CJK survive',async({page})=>{
  await load(page,TABLE_DOC);
  await cell(page,'apple').click(); await page.keyboard.press('End'); await page.keyboard.type('s');
  const out=await page.evaluate(md);
  expect(out).toContain('|Name|Qty|Note|\n|:--|:-:|--:|');           // header and alignment row untouched
  expect(out).toContain('| apples | 1 | **fresh** `code` |');          // only this row rewritten
  expect(out).toContain('|a\\|b||[link](http://x.y)|');               // escaped pipe + empty cell row untouched
  expect(out).toContain('|中文单元格|3|最后一列|');                   // CJK row untouched
  expect(out).toContain('| A | B |\n|---|---|\n| one | two |');       // second table untouched
  expect(out).toContain('Before.\n\n|Name');
  expect(out).toContain('last'.length?'\n\nBetween.\n\n| A | B |':'');
});
test('table: editing the header and a CJK cell keeps every other row byte for byte',async({page})=>{
  await load(page,TABLE_DOC);
  await cell(page,'Qty').click(); await page.keyboard.press('End'); await page.keyboard.type('!');
  await cell(page,'最后一列').click(); await page.keyboard.press('End'); await page.keyboard.type('。');
  const out=await page.evaluate(md);
  expect(out).toMatch(/\| Name \| Qty! \| Note \|\n\|:--\|:-:\|--:\|/);
  expect(out).toContain('|apple|1|**fresh** `code`|');
  expect(out).toContain('最后一列。');
  expect(out).toContain('|a\\|b||[link](http://x.y)|');
});
test('table: typing a pipe inside a cell is escaped so the table stays intact',async({page})=>{
  await load(page,'|A|B|\n|-|-|\n|x|y|\n');
  await cell(page,'x').click(); await page.keyboard.press('End'); await page.keyboard.type('|z');
  const out=await page.evaluate(md);
  expect(out).toContain('x\\|z');
  expect((out.match(/\n\|/g)||[]).length).toBeGreaterThanOrEqual(2);
});
test('table: undoing an edit restores the original text exactly',async({page})=>{
  await load(page,TABLE_DOC);
  await cell(page,'apple').click(); await page.keyboard.press('End'); await page.keyboard.type('XYZ');
  for(let i=0;i<3;i++) await page.keyboard.press('Meta+z');
  expect((await page.evaluate(md)).replace(/\s+$/,'')).toBe(TABLE_DOC.replace(/\s+$/,''));
});
test('table: adding a row and a column through the editor keeps the rest of the table readable',async({page})=>{
  await load(page,'|A|B|\n|:-|-:|\n|1|2|\n|3|4|\n');
  await cell(page,'4').click(); await page.keyboard.press('End');
  await page.keyboard.press('Tab');                        // Tab in the last cell adds a row
  await page.keyboard.type('5');
  const out=await page.evaluate(md);
  expect(out).toContain('|A|B|\n|:-|-:|\n|1|2|\n|3|4|');
  expect(out).toMatch(/\| 5 \|/);
  const rows=out.trim().split('\n').filter(l=>l.startsWith('|'));
  expect(rows.length).toBe(5);
  for(const r of rows) expect((r.match(/(?<!\\)\|/g)||[]).length).toBe(3);   // every row still has two cells
});
test('table: a line break inside a cell stays inside the cell',async({page})=>{
  await load(page,'|A|B|\n|-|-|\n|one|two|\n');
  await cell(page,'one').click(); await page.keyboard.press('End'); await page.keyboard.press('Shift+Enter'); await page.keyboard.type('next');
  const out=await page.evaluate(md);
  const rows=out.trim().split('\n').filter(l=>l.startsWith('|'));
  expect(rows.length).toBe(3);                              // the table did not break into extra lines
  expect(out).toMatch(/one.*next/);
});
test('table: a long table is edited without losing or reordering rows',async({page})=>{
  const rows=Array.from({length:150},(_,i)=>`|row${i}|${i}|text ${i}|`);
  const doc='|H1|H2|H3|\n|---|---|---|\n'+rows.join('\n')+'\n\nEnd\n';
  await load(page,doc);
  await cell(page,'row2').click(); await page.keyboard.press('End'); await page.keyboard.type('Y');
  let out=await page.evaluate(md);
  expect(out).toContain('| row2Y | 2 | text 2 |');
  expect(out.replace('| row2Y | 2 | text 2 |','|row2|2|text 2|').replace(/\s+$/,'')).toBe(doc.replace(/\s+$/,''));
  // a row deep in the table is just as editable: nothing is folded away
  expect(await page.locator('.fold-more').count()).toBe(0);
  await cell(page,'row77').click(); await page.keyboard.press('End'); await page.keyboard.type('X');
  out=await page.evaluate(md);
  expect(out).toContain('| row77X | 77 | text 77 |');
  expect(out.replace('| row77X | 77 | text 77 |','|row77|77|text 77|').replace('| row2Y | 2 | text 2 |','|row2|2|text 2|').replace(/\s+$/,'')).toBe(doc.replace(/\s+$/,''));
});
test('on-screen buttons such as "Show all N rows" never leak into the saved Markdown',async({page})=>{
  const rows=Array.from({length:60},(_,i)=>`|r${i}|${i}|`).join('\n');
  const code=Array.from({length:80},(_,i)=>`line ${i}`).join('\n');
  await load(page,'|H|V|\n|-|-|\n'+rows+'\n\nMiddle paragraph.\n\n```\n'+code+'\n```\n\nEnd.\n');
  expect(await page.locator('.fold-more').count()).toBeGreaterThan(0);
  await page.locator('#content p',{hasText:'Middle paragraph.'}).click(); await page.keyboard.press('End'); await page.keyboard.type('!');
  const out=await page.evaluate(md);
  expect(out).not.toMatch(/Show all|显示全部|Copy/);
  expect(out).toContain('Middle paragraph.!');
  expect(out).toContain('line 79');
});
test('front matter can be edited in place; only its text changes',async({page})=>{
  const doc='---\ntitle: One\ntags: [a, b]\n---\n\n# Heading\n\nBody text.\n';
  await load(page,doc);
  expect(await page.locator('.frontmatter-body').evaluate(e=>e.isContentEditable)).toBe(true);
  await page.locator('.frontmatter-body').click();
  await page.evaluate(()=>{const n=document.querySelector('.frontmatter-body').firstChild,at=n.textContent.indexOf('[a, b]')+6;const r=document.createRange();r.setStart(n,at);r.collapse(true);const g=getSelection();g.removeAllRanges();g.addRange(r);});
  await page.keyboard.type('\ndate: 2026-11-10');
  const out=await page.evaluate(md);
  expect(out.startsWith('---\ntitle: One\ntags: [a, b]\ndate: 2026-11-10\n---\n\n# Heading')).toBe(true);
  expect(out).toContain('Body text.');
  expect(await page.locator('#editHintBubble.visible').count()).toBe(0);
});
test('front matter that is not touched is saved exactly as written',async({page})=>{
  const doc='---\ntitle: "Quoted: yes"\nsummary: >\n  folded text\n  more text\n---\n\nBody.\n';
  await load(page,doc);
  await page.locator('#content p',{hasText:'Body.'}).click(); await page.keyboard.press('End'); await page.keyboard.type('!');
  expect((await page.evaluate(md)).replace(/\s+$/,'')).toBe(doc.replace('Body.','Body.!').replace(/\s+$/,''));
});
