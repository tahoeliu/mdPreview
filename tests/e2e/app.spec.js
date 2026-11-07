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
test('source editing, save and preview preserve Unicode',async({page})=>{
  await page.evaluate(()=>loadContent('/tmp/doc.md','# 文档\n\nInitial',720,false,true));
  await page.keyboard.press('Meta+e');
  await page.locator('#textarea').fill('# 文档\n\n中文 日本語 العربية café 🧪');
  await page.keyboard.press('Meta+s');
  await expect.poll(()=>page.evaluate(()=>window.__writes.at(-1)?.content)).toContain('🧪');
  await page.keyboard.press('Meta+e');
  await expect(page.locator('#content')).toContainText('العربية');
});
test('preview paste is undoable in a real engine',async({page})=>{
  await page.evaluate(async()=>{await loadContent('/tmp/doc.md','Alpha',720,false,false);const p=document.querySelector('#content p');const r=document.createRange();r.selectNodeContents(p);r.collapse(false);const sel=getSelection();sel.removeAllRanges();sel.addRange(r);document.getElementById('content').focus();pasteMdIntoRendered(' **BOLD**');});
  await expect(page.locator('#content')).toContainText('BOLD');
  await page.keyboard.press('Meta+z');
  await expect(page.locator('#content')).not.toContainText('BOLD');
});
test('recovery remains dirty and save race retains later input',async({page})=>{
  const result=await page.evaluate(async()=>{
    await loadContent('/tmp/doc.md','draft',720,true,false);const recovered=window.__dirty;
    await toggleView();const ta=document.getElementById('textarea');ta.value='B';ta.dispatchEvent(new Event('input'));
    let complete;pywebview.api.save_file=()=>new Promise(resolve=>complete=resolve);
    const pending=saveFile();await new Promise(r=>setTimeout(r,10));ta.value='C';ta.dispatchEvent(new Event('input'));complete({success:true});await pending;
    return {recovered,text:ta.value,dirty:window.__dirty};
  });
  expect(result).toEqual({recovered:true,text:'C',dirty:true});
});
test('math, footnotes and table links survive unrelated preview editing',async({page})=>{
  const result=await page.evaluate(async()=>{
    await loadContent('/tmp/doc.md','Intro\n\n$$x^2$$\n\nA[^n]\n\n[^n]: body\n\n| a | b |\n| --- | --- |\n| **bold** | [link](https://example.com) |',720,false,false);
    const content=document.getElementById('content');content.querySelector('p').append(' edit');content.dispatchEvent(new Event('input'));return getCurrentMarkdown();
  });
  expect(result).toContain('$$x^2$$');expect(result).toContain('[^n]: body');expect(result).toContain('**bold**');expect(result).toContain('[link](https://example.com)');
});
test('untrusted document cannot execute scripts or retain encoded script URLs',async({page})=>{
  const result=await page.evaluate(async()=>{
    window.__attacked=false;
    await loadContent('/tmp/doc.md','<img src=x onerror="window.__attacked=true"><a href="java&#x09;script:window.__attacked=true">link</a><iframe srcdoc="x"></iframe>',720,false,false);
    await new Promise(r=>setTimeout(r,50));return {attacked:window.__attacked,href:document.querySelector('#content a').getAttribute('href'),iframe:!!document.querySelector('#content iframe')};
  });
  expect(result.attacked).toBe(false);expect(result.href).toBeNull();expect(result.iframe).toBe(false);
});
test('source-mode HTML export is current and restores editor',async({page})=>{
  await page.evaluate(async()=>{await loadContent('/tmp/doc.md','OLD',720,false,false);await toggleView();const ta=document.getElementById('textarea');ta.value='LATEST';ta.dispatchEvent(new Event('input'));await exportAsWrite('/tmp/out.html','html');});
  expect(await page.evaluate(()=>window.__export.content)).toContain('LATEST');await expect(page.locator('#textarea')).toBeVisible();
});
test('Mermaid is rendered and included in export',async({page})=>{
  await page.evaluate(()=>loadContent('/tmp/doc.md','```mermaid\nflowchart LR\n A[Start] --> B[End]\n```',720,false,false));
  await expect(page.locator('#content .mermaid-diagram svg')).toBeVisible();
  await page.evaluate(()=>exportAsWrite('/tmp/out.html','html'));
  expect(await page.evaluate(()=>window.__export.content)).toContain('<svg');
});
test('a heading named like a library does not break lazy-loaded Mermaid',async({page})=>{
  await page.evaluate(()=>loadContent('/tmp/doc.md','## Mermaid\n\n```mermaid\nflowchart LR\n A[Start] --> B[End]\n```',720,false,false));
  await expect(page.locator('#content .mermaid-diagram svg')).toBeVisible();
});
test('replace controls are hidden in preview and shown in source mode',async({page})=>{
  await page.evaluate(()=>loadContent('/tmp/doc.md','alpha',720,false,false));
  await page.keyboard.press('Meta+f');
  await expect(page.locator('#findBar')).toBeVisible();
  await expect(page.locator('.replace-action').first()).toBeHidden();
  await page.keyboard.press('Escape');
  await page.keyboard.press('Meta+e');
  await page.keyboard.press('Meta+f');
  await expect(page.locator('.replace-action').first()).toBeVisible();
});
test('selecting text shows the formatting toolbar and bold round-trips to Markdown',async({page})=>{
  await page.evaluate(()=>loadContent('/tmp/doc.md','Hello brave world',720,false,false));
  await page.evaluate(()=>{const p=document.querySelector('#content p');const r=document.createRange();r.setStart(p.firstChild,6);r.setEnd(p.firstChild,11);const s=getSelection();s.removeAllRanges();s.addRange(r);document.dispatchEvent(new Event('mouseup'));});
  const bold=page.locator('.format-toolbar button[data-kind="bold"]');
  await expect(bold).toBeVisible();
  await bold.click();
  await expect(page.locator('#content strong, #content b')).toHaveText('brave');
  expect(await page.evaluate(()=>getCurrentMarkdown())).toContain('**brave**');
  await page.keyboard.press('Meta+e');
  await expect(page.locator('.format-toolbar')).toBeHidden();
});
test('long document renders its tail and source outline navigates',async({page},testInfo)=>{
  const measurements=await page.evaluate(async()=>{
    const text=Array.from({length:800},(_,i)=>'# Section '+i+'\n\n'+('Reading text 中文. '.repeat(10))).join('\n\n');
    const start=performance.now();await loadContent('/tmp/long.md',text,720,false,false);const render=performance.now()-start;
    const last=document.querySelector('#content h1:last-of-type')?.textContent;await toggleView();const source=performance.now()-start-render;
    return {renderMs:render,sourceMs:source,last,chars:text.length};
  });
  expect(measurements.last).toBe('Section 799');expect(measurements.renderMs).toBeLessThan(10000);
  await testInfo.attach('timings',{body:JSON.stringify(measurements),contentType:'application/json'});
});
test('light, dark and Chinese visual smoke',async({page},testInfo)=>{
  await page.evaluate(()=>loadContent('/tmp/doc.md','# 阅读示例\n\n**Bold** and *italic*.\n\n| 列一 | Column |\n| --- | --- |\n| 中文 | Value |\n\n```js\nconst message = "hello";\n```',720,false,true));
  await page.screenshot({path:'WorkSpace/'+testInfo.project.name+'-light.png',fullPage:true});
  await page.emulateMedia({colorScheme:'dark'});
  await page.screenshot({path:'WorkSpace/'+testInfo.project.name+'-dark.png',fullPage:true});
  await expect(page.locator('#content')).toContainText('阅读示例');
});
