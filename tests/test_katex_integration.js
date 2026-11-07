const assert=require('node:assert/strict');
const {createApp}=require('./helpers');
(async()=>{const app=await createApp();try{
 const {w}=app;
 const source=String.raw`开头 $x+1$ 和 \(y^2\)。

$$
\frac{a}{b}
$$

\[\sqrt{x}\]

错误 $\frac{a}$

转义 \\(not math\\)

` + '\n`$code$`\n\n```tex\n$notMath$\n```';
 await app.load(source);
 const root=w.document.querySelector('#content');
 assert.equal(root.querySelectorAll('.katex').length,4);
 assert.equal(root.querySelectorAll('.katex-error').length,1);
 assert.equal(root.querySelectorAll('.math-inline,.math-block').length,5);
 assert.equal(root.querySelector('code').textContent,'$code$');
 const mathOnly=w.document.createElement('div');mathOnly.append(root.querySelector('.math-inline').cloneNode(true));
 assert.equal(w.toPlainText(mathOnly),'x+1\n');
 const exported=w.MarkdownPipeline.cleanExport(root.innerHTML);
 assert.match(exported,/<math[ >]/);
 assert.match(exported,/math-rendered/);
 const sizeProbe=w.document.createElement('span');sizeProbe.style.fontFamily='"KaTeX_Size4"';root.querySelector('.katex').append(sizeProbe);
 const css=await w.MathRenderer.exportCSS(root);
 sizeProbe.remove();
 assert.match(css,/font-family:["']?KaTeX_Size4/);
 assert.match(css,/data:font\/woff2;base64,/);
 assert.doesNotMatch(css,/url\(["']?fonts\//);
 assert.doesNotMatch(css,/url\(["']?https?:/);
 const raw=[...root.querySelectorAll('[data-raw].math-inline,[data-raw].math-block')].map(e=>e.dataset.raw);
 root.querySelector('p').append(' 编辑');root.dispatchEvent(new w.Event('input'));
 const saved=w.getCurrentMarkdown();for(const value of raw)assert.ok(saved.includes(value));
 const cleaned=w.MarkdownPipeline.cleanMath('<span style="background:url(https://example.com);color:red" onclick="x()">x</span><svg><a href="https://example.com"><path d="M0 0"/></a></svg><img src="x"><math><mi>x</mi></math>');
 assert.doesNotMatch(cleaned,/url\(|href=|src=|onclick|<img|<a[ >]/i);
 assert.match(cleaned,/<math/);
 console.log('KaTeX分隔符、回写和净化断言通过');
}finally{app.close()}})().catch(e=>{console.error(e);process.exitCode=1});
