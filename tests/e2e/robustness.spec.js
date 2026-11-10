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
