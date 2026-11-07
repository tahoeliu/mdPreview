const assert=require('node:assert/strict');const {createApp}=require('./helpers');
(async()=>{const app=await createApp();try{const w=app.w;let text;w.pywebview.api.export_as_write=(p,f,c)=>{text=c;return {success:true}};
 await app.load('# 标题\n\n**粗体**\n\n- 项目\n- [x] 完成\n\n[链接](https://example.com)\n\n| A | B |\n|---|---|\n| 一 | 二 |');
 await w.exportAsWrite('/tmp/test.txt','txt');
 assert.doesNotMatch(text,/\*\*|##|\|---/);assert.match(text,/• 项目/);assert.match(text,/\[x\] 完成/);assert.match(text,/A\tB/);assert.match(text,/链接 \(https:\/\/example.com\)/);
 assert.equal(text,'标题\n\n粗体\n\n• 项目\n[x] 完成\n\n链接 (https://example.com)\n\nA\tB\n\n一\t二\n');
 console.log('纯文本规则及快照断言通过');
}finally{app.close()}})().catch(e=>{console.error(e);process.exitCode=1});
