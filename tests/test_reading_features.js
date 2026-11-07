const assert=require('node:assert/strict');
const {createApp}=require('./helpers');
(async()=>{const a=await createApp();try{
 const w=a.w;
 const md='```md\n- [ ] 代码任务\n```\n\n- [ ] 真任务\n  - [x] 子任务\n\n> [!NOTE]\n> 提示正文';
 await a.load(md);
 const root=w.document.getElementById('content');
 assert.equal(root.querySelectorAll('.task-toggle').length,2);
 assert.ok(root.querySelector('.markdown-alert-note'));
 assert.ok(root.querySelector('.code-copy-btn'));
 root.querySelector('.task-toggle').click();await new Promise(r=>setTimeout(r,30));
 assert.match(w.getCurrentMarkdown(),/```md\n- \[ \] 代码任务/);
 assert.match(w.getCurrentMarkdown(),/- \[x\] 真任务/);
 const positions=w.ReadingFeatures.tasks('> - [ ] 引用\n>   - [x] 子项\n\n```\n- [ ] 代码\n```');
 assert.equal(positions.length,2);
 const original='> - [ ] 引用\n>   - [x] 子项\n\n```\n- [ ] 代码\n```';
 assert.equal(original[positions[0].offset],' ');assert.equal(original[positions[1].offset],'x');
 await a.load('![远程](https://example.com/p.png)\n\n<img src="https://example.com/a" srcset="https://example.com/b 2x">');
 for(const img of root.querySelectorAll('img')){assert.ok(!/^https?:/.test(img.getAttribute('src')||''));assert.equal(img.hasAttribute('srcset'),false);}
 assert.equal(root.querySelectorAll('img[data-remote-src]').length,2);
 assert.ok(w.MarkdownPipeline.parse('<img src="https://example.com/x">').includes('data-remote-src'));
 assert.match(w.getCurrentMarkdown(),/https:\/\/example.com\/p.png/);
 console.log('T13–T16 定向断言通过');
}finally{a.close()}})().catch(e=>{console.error(e);process.exitCode=1});
