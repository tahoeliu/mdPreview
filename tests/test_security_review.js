const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {createApp}=require('./helpers');
(async()=>{
 const app=await createApp();
 try {
  const w=app.w;
  for(const raw of ['<video poster="https://example.com/track.png"></video>', '<table background="https://example.com/track.png"><tr><td>x</td></tr></table>', '<audio src="https://example.com/track.mp3"></audio>']){
   await app.load(raw);
   const content=w.document.querySelector('#content');
   assert.equal(content.querySelector('[poster],[background],audio[src],video[src]'),null,'插入DOM前必须移除不支持的资源入口');
   assert.ok(w.getCurrentMarkdown().includes(raw),'回写必须保留原始HTML');
  }
  let renders=0;
  w.mermaid={initialize(){},render:async()=>{renders++;return {svg:'<svg></svg>'};}};
  await app.load('```mermaid\nflowchart LR\nA@{ img: "https://example.com/track.png", label: "图片" }\n```');
  await w.LazyRender.flush();
  assert.equal(renders,0,'图片形状必须在调用Mermaid前拒绝');
  assert.match(w.document.querySelector('#content').textContent,/禁用|blocked/i);
  assert.match(w.getCurrentMarkdown(),/img:/);
  for(const source of ['flowchart LR\nA＠{ img: "https://example.com/x" }', '%%{init: {"securityLevel":"loose"}}%%\nflowchart LR\nA-->B', 'flowchart LR\nA["<img src=https://example.com/x>"]']){
   await app.load('```mermaid\n'+source+'\n```');await w.LazyRender.flush();assert.equal(renders,0);
  }
  w.mermaid.mermaidAPI={getDiagramFromText:async()=>({db:{getVertices:()=>({A:{img:'https://example.com/x'}})}})};
  await app.load('```mermaid\nflowchart LR\nA-->B\n```');await w.LazyRender.flush();assert.equal(renders,0,'parser层发现图片同样拒绝');
  let resolveRead,acks=0;
  w.pywebview.api.reload_from_disk=()=>new Promise(resolve=>{resolveRead=resolve;});
  w.pywebview.api.ack_reload_from_disk=()=>{acks++;return {success:true};};
  await app.load('A','/tmp/review.md',false,{documentId:'review',revision:0});
  const pending=w.reloadFromDisk();
  app.input('A+edit');
  resolveRead({success:true,content:'B',candidateId:'candidate',documentId:'review'});
  assert.equal(await pending,false);assert.equal(acks,0);assert.equal(w.getCurrentMarkdown(),'A+edit');
  await app.load('A','/tmp/review.md',false,{documentId:'review',revision:0});
  w.pywebview.api.reload_from_disk=async()=>({success:true,content:'B',candidateId:'candidate',documentId:'review'});
  assert.equal(await w.reloadFromDisk(),true);assert.equal(acks,1);
  await app.load('A','/tmp/review.md',false,{documentId:'review',revision:0});
  const reads=[];w.pywebview.api.reload_from_disk=()=>new Promise(resolve=>reads.push(resolve));
  const first=w.reloadFromDisk(),second=w.reloadFromDisk();
  reads[1]({success:true,content:'C',candidateId:'C'});assert.equal(await second,true);
  reads[0]({success:true,content:'B',candidateId:'B'});assert.equal(await first,false);
  assert.equal(w.getCurrentMarkdown(),'C','迟到旧响应不得覆盖新响应');
  w.pywebview.api.reload_from_disk=async()=>({success:true,content:'D',candidateId:'D'});
  w.pywebview.api.ack_reload_from_disk=async()=>({success:false,conflict:true});
  assert.equal(await w.reloadFromDisk(),false);
  assert.match(w.document.body.textContent,/同步冲突|sync conflict/i,'ACK失败必须明确提示');
 } finally {app.close();}
 const code=fs.readFileSync('frontend/csp-api.js','utf8');
 const native=fs.readFileSync('mdpreview_core/csp_bridge.py','utf8');
 assert.ok(native.includes('window.gui.evaluate_js(script, window.uid, False)'));assert.ok(!native.includes('value = eval('));
 assert.ok(!/unsafe-eval/.test(fs.readFileSync('index.html','utf8')+fs.readFileSync('frontend/headless.js','utf8')));
 const apiPath='.venv/lib/python3.13/site-packages/webview/js/api.js';
 assert.ok(fs.existsSync(apiPath),'必须提供受支持pywebview模板以检查适配契约');
 const apiSource=fs.readFileSync(apiPath,'utf8');
 const start=apiSource.indexOf('  _createApi: function (funcList) {'),end=apiSource.indexOf('  _jsApiCallback: function (funcName, params, id) {',start);
 assert.ok(start>=0&&end>start);assert.match(apiSource.slice(start,end),/new Function/);
 assert.doesNotMatch(apiSource.slice(0,start)+'  _createApi: null,\n'+apiSource.slice(end),/new Function\(/);

 for(const headless of [false,true]){
  const callbacks={};let sent;
  const window={HEADLESS_EXPORT:headless,pywebview:{api:{},_returnValuesCallbacks:callbacks,_checkValue(name,resolve,reject,id){callbacks[name][id]=resolve;},_jsApiCallback(name,args,id){sent={name,args,id};callbacks[name][id]('ok');}}};
  const context=vm.createContext({window,Promise,crypto:require('node:crypto').webcrypto},{codeGeneration:{strings:false,wasm:false}});
  vm.runInContext(code,context);
  window.pywebview._createApi([{func:'export_as_write',params:['default']}]);
  assert.equal(await window.pywebview.api.export_as_write('target','txt'),'ok');assert.equal(sent.name,'export_as_write');assert.deepEqual(Array.from(sent.args),['target','txt']);
  assert.throws(()=>window.pywebview._createApi([{func:'__proto__.polluted'}]));
  const results=[];window.pywebview._asyncCallback=(value,id)=>results.push({value:JSON.parse(value),id});
  await vm.runInContext('window.pywebview._runBody("body", function(){const result=Promise.resolve(42); return result;})',context);
  assert.equal(results[0].value.value,42);assert.equal(results[0].value.success,true);
  await vm.runInContext('window.pywebview._runBody("missing", function(){return missingFunction();})',context);
  await vm.runInContext('window.pywebview._runBody("reject", function(){return Promise.reject(new Error("failure"));})',context);
  assert.equal(results.length,3);assert.equal(results[1].value.success,false);assert.equal(results[2].value.success,false);
 }
 console.log('七项审查：资源入口、Mermaid预拒绝、外改ACK和无eval闭包回归通过');
})().catch(error=>{console.error(error);process.exitCode=1;});
