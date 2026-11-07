const assert=require('node:assert/strict');
const {createApp}=require('./helpers');
let assertions=0;
function check(value,message){assert.ok(value,message);assertions++;}
(async()=>{
  const app=await createApp();const {w}=app;
  try {
    let dirty=null;w.pywebview.api.set_dirty=value=>{dirty=value;return Promise.resolve(true)};
    await app.load('recovered','/tmp/a.md',true);check(dirty===true,'Recovered draft remains dirty');
    await app.load('A');await w.toggleView();app.input('B');
    let finish;w.pywebview.api.save_file=()=>new Promise(resolve=>finish=resolve);
    const pending=w.saveFile();await new Promise(r=>setTimeout(r,10));app.input('C');finish({success:true});
    const saved=await pending;check(w.getCurrentMarkdown()==='C','Save must not replace newer input');check(!saved.saved && saved.snapshotSaved,'Only saved snapshot acknowledged');check(dirty,'New input remains dirty');
    w.pywebview.api.save_file=()=>Promise.resolve({success:true});await w.saveFile();check(dirty===false,'Subsequent save acknowledges latest revision');
    await app.load('Aa');await w.toggleView();let calls=0;w.pywebview.api.store_content=()=>{calls++;return Promise.resolve({success:true})};
    app.input('BB');await w.pushContentToPython();check(calls===1,'Hash-colliding edits are synchronized');
    app.input('changed');let attempt=0;w.pywebview.api.store_content=()=>{attempt++;return attempt===1?Promise.reject(new Error('offline')):Promise.resolve({success:true})};
    check(await w.pushContentToPython()===false,'Bridge failure is reported');check(await w.pushContentToPython()===true && attempt===2,'Failed draft can be retried');
    await app.load('old');await w.toggleView();app.input('save old');
    w.pywebview.api.save_file=()=>new Promise(resolve=>finish=resolve);const stale=w.saveFile();await new Promise(r=>setTimeout(r,10));
    await app.load('new document','/tmp/new.md');finish({success:true});check((await stale).stale,'Old response rejects changed identity');check(w.getCurrentMarkdown()==='new document','Old save cannot alter new document');
    await app.load('```bash\necho $HOME $USER\n```');check(w.document.querySelector('#content code').textContent==='echo $HOME $USER\n','Shell dollars stay intact');
    await app.load('Intro\n\n$$x^2$$\n\nText[^note-2]\n\n[^note-2]: **Footnote** body\n\n| Name | Link |\n| --- | --- |\n| **Bold** | [Site](https://example.com) |');
    const content=w.document.getElementById('content');check(!!content.querySelector('sup a'),'Footnote reference rendered');check(!!content.querySelector('.footnotes'),'Footnotes appended');
    content.querySelector('p').textContent='Edited intro';content.dispatchEvent(new w.Event('input'));const round=w.getCurrentMarkdown();
    check(round.includes('$$x^2$$'),'Block math round trip');check(round.includes('[^note-2]'),'Footnote label round trip');check(round.includes('[^note-2]: **Footnote** body'),'Footnote definition round trip');check(round.includes('**Bold**'),'Table bold round trip');check(round.includes('[Site](https://example.com)'),'Table URL round trip');
    await app.load('Hello $x+1$ world');content.querySelector('p').appendChild(w.document.createTextNode('!'));content.dispatchEvent(new w.Event('input'));check(w.getCurrentMarkdown().includes('$x+1$'),'Inline math round trip');
    await app.load('![local](images/demo.png)');content.dispatchEvent(new w.Event('input'));check(w.getCurrentMarkdown().includes('(images/demo.png)'),'Relative image preserved on save');
    let exported='';w.pywebview.api.export_as_write=(path,format,body)=>{exported=body;return Promise.resolve({success:true})};
    await app.load('OLD');await w.toggleView();app.input('LATEST');await w.exportAsWrite('/tmp/test.html','html');check(exported.includes('LATEST')&&!exported.includes('<p>OLD</p>'),'HTML export uses newest source');
    w.pywebview.api.save_as_choose=()=>Promise.resolve({success:true,path:'/tmp/test.html',format:'html'});
    const result=await w.saveAsFile();check(result.exported&&!result.saved,'Non-Markdown export cannot authorize discarding dirty source');
    const banner=w.document.createElement('div');banner.style.display='flex';w.document.body.append(banner);
    const indicator=w.document.getElementById('modeIndicator');indicator.style.display='block';
    w.pywebview.api.get_output_settings=()=>({font:'normal',pdf_layout:'paged'});
    for(const fail of [false,true]){
      w.pywebview.api.export_as_write=async()=>{
        check(indicator.style.display==='none'&&banner.style.display==='none','PDF hides fixed and dynamic overlays');
        check(w.document.querySelector('.scroll-wrap').style.display!=='none','PDF keeps document visible');
        if(fail)throw new Error('capture failed');return {success:true};
      };
      try{await w.exportAsWrite('/tmp/test.pdf','pdf');check(!fail,'PDF succeeds');}catch(error){check(fail&&error.message==='capture failed','PDF failure propagates');}
      check(indicator.style.display==='block'&&banner.style.display==='flex','PDF restores interface after success or failure');
      check(w.document.getElementById('source').style.display!=='none','PDF restores source mode');
    }
    banner.remove();
    const attacks=['<img src=x onerror="alert(1)">','<a href="java&#x09;script:alert(1)">a</a>','<svg><script>alert(1)</script></svg>','<iframe srcdoc="x"></iframe>','<a href="data:text/html,x">a</a>','<img src="file:///etc/passwd">','<div style="background:url(https://example.com)">x</div>','<form><input name=save_file></form>'];
    for(const raw of attacks){const root=w.document.createElement('div');root.innerHTML=w.sanitizeHtmlString(raw);check(!root.querySelector('script,iframe,svg,form,input'),'Blocked active elements');for(const element of root.querySelectorAll('*'))for(const attribute of element.attributes){check(!attribute.name.startsWith('on'),'No event attributes');if(attribute.name==='href'||attribute.name==='src')check(w.MarkdownPipeline.safeURL(attribute.value,element.tagName==='IMG'),'No dangerous URLs');}}
    await app.load('<div id=textarea data-raw=hidden>safe</div>');check(w.document.querySelector('#content #textarea')===null,'Document cannot shadow source editor ID');check(w.document.querySelector('#content [data-raw]')===null,'Untrusted HTML cannot inject trusted source metadata');
    await app.load('<div class=mermaid-diagram data-source=hidden>visible text</div>');w.document.getElementById('content').dispatchEvent(new w.Event('input'));check(w.getCurrentMarkdown().includes('visible text'),'HTML cannot impersonate generated source blocks');
    await app.load('Intro\n\n[^unused]: Keep this definition');w.document.querySelector('#content p').append(' edit');w.document.getElementById('content').dispatchEvent(new w.Event('input'));check(w.getCurrentMarkdown().includes('[^unused]: Keep this definition'),'Unreferenced footnotes survive paragraph edits');
    const svg=w.sanitizeMermaidSvg('<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><script>alert(1)</script><text>safe</text></svg>');check(!/onload|<script/i.test(svg)&&svg.includes('safe'),'SVG fail-closed sanitation');
    // Deterministic adversarial dollars/brackets in code never participate in extensions.
    for(let i=0;i<60;i++){const text='var'+i+' = "$HOME $USER $$x$$ [^note] <tag>"';await app.load('```text\n'+text+'\n```');check(w.document.querySelector('#content code').textContent===text+'\n','Code preservation case '+i);}
    await require('./t32-contract.cjs')(w);
    console.log('Integrity/security: '+assertions+' assertions PASS');
  } finally {app.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
