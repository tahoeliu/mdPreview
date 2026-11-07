const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto');const {createApp}=require('./helpers');
(async()=>{const a=await createApp();try{
 const w=a.w;let finished=null,args=null;
 w.HEADLESS_EXPORT=true;w.pywebview.api.headless_finish=value=>{finished=value;};
 const original=w.exportAsWrite;w.exportAsWrite=async(...values)=>{args=values;return {success:true};};
 await w.runHeadlessExport({headless:true,path:'test.md',content:'# Export',outputPath:'/tmp/result.txt',outputFormat:'txt',settings:{remote_images:'never',auto_update:false,language:'en'}});
 assert.deepEqual(args,['/tmp/result.txt','txt']);assert.equal(finished,true);w.exportAsWrite=original;
 const code=fs.readFileSync('mdpreview_core/release_sig.py','utf8');assert.match(code,/RELEASE_PUBKEY_B64 = ''/);assert.match(code,/if not configured\(\)/);
 const download=fs.readFileSync('mdpreview_core/update_download.py','utf8');assert.ok(download.indexOf('if not configured()')<download.indexOf('metadata = json.loads'));
 const pair=crypto.generateKeyPairSync('ec',{namedCurve:'prime256v1'}),other=crypto.generateKeyPairSync('ec',{namedCurve:'prime256v1'});
 const message=Buffer.from('isolated-test-only'),signature=crypto.sign('sha256',message,pair.privateKey);
 assert.ok(crypto.verify('sha256',message,pair.publicKey,signature));assert.ok(!crypto.verify('sha256',Buffer.from('tampered'),pair.publicKey,signature));assert.ok(!crypto.verify('sha256',message,other.publicKey,signature));
 let payload=null;w.pywebview.api.export_as_write=async(...values)=>{payload=values;return {success:true};};
 await w.runHeadlessExport({headless:true,path:'test.md',content:'# Export\n\n真实正文',outputPath:'/tmp/result.txt',outputFormat:'txt',settings:{remote_images:'never',auto_update:false,language:'en'}});
 assert.equal(finished,true);assert.equal(payload[1],'txt');assert.match(payload[2],/真实正文/);assert.doesNotMatch(payload[2],/# Export/);
 const python=fs.readFileSync('mdPreview.py','utf8');assert.match(python,/def _export_commit_guard/);assert.match(python,/with self\._export_commit_guard\(\):/);
 const headless=fs.readFileSync('mdpreview_core/headless.py','utf8');assert.match(headless,/api\._headless_lifecycle = lifecycle/);assert.match(headless,/response\.get\('paths', \[str\(target\)\]\)/);
 const {validateMatrix,required}=await import('../scripts/verify-matrix.mjs');
 assert.throws(()=>validateMatrix({}, {version:'test',bundleSha256:'x',base:process.cwd()}));
 const matrix={metadata:{version:'test',bundleSha256:'x',reviewer:'test-only'}};
 for(const [format,targets] of Object.entries(required)){matrix[format]={};for(const target of targets)matrix[format][target]={status:'not-tested'};}
 assert.throws(()=>validateMatrix(matrix,{version:'test',bundleSha256:'x',base:process.cwd()}));
 console.log('CLI真实TXT前端管线、签名关闭与矩阵拒绝契约通过；不替代Python Security或原生验收');
}finally{a.close();}})().catch(e=>{console.error(e);process.exitCode=1});
