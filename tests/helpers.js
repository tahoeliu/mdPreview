const { JSDOM } = require('jsdom');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
function verifyFrontendLoading(html) {
  const assert = require('node:assert/strict');
  const scripts = [...html.matchAll(/<script src="([^"]+)"[^>]*>/g)].map(match => match[1]);
  const gate = fs.readFileSync(path.join(root, 'scripts/check_release.py'), 'utf8');
  const spec = fs.readFileSync(path.join(root, 'mdPreview.spec'), 'utf8');
  assert.ok(spec.includes("('frontend', 'frontend')"), '打包必须包含完整前端目录');
  assert.equal(new Set(scripts).size, scripts.length, '脚本不能重复加载');
  for (const file of scripts.filter(file => file.startsWith('frontend/'))) {
    assert.ok(fs.existsSync(path.join(root, file)), '缺少模块：' + file);
    assert.ok(scripts.indexOf(file) < scripts.indexOf('app.js'), '模块必须先于入口加载');
    assert.ok(gate.includes("'" + file + "'"), '发布门禁遗漏模块：' + file);
  }
}
async function createApp() {
  const html = fs.readFileSync(path.join(root,'index.html'),'utf8');
  verifyFrontendLoading(html);
  const dom = new JSDOM(html, {
    url:'file://' + root + '/index.html', resources:'usable', runScripts:'dangerously', pretendToBeVisual:true,
    beforeParse(window) { window.TextEncoder=TextEncoder;window.TextDecoder=TextDecoder; window.matchMedia=()=>({matches:false,addEventListener(){},removeEventListener(){}}); }
  });
  await new Promise((resolve,reject)=> { dom.window.addEventListener('load',resolve); setTimeout(()=>reject(new Error('App load timeout')),5000).unref(); });
  const w=dom.window;
  w.HTMLElement.prototype.scrollTo=function(){};
  w.pywebview={api:{get_export_css:()=>({css:['tokens','content','print'].map(n=>fs.readFileSync(path.join(root,'css',n+'.css'),'utf8')).join('\n'),version:'1.5.0'}),get_output_settings:()=>({font:'normal'}),set_dirty:()=>Promise.resolve(true),store_content:()=>Promise.resolve({success:true}),startup_ready(){},save_file:()=>Promise.resolve({success:true})}};
  w.pywebview.api.get_math_export_css=(families)=>{
    const css=fs.readFileSync(path.join(root,'vendor/katex/katex.min.css'),'utf8');
    return css.replace(/@font-face\s*\{[^}]+\}/g,block=>{
      const family=block.match(/font-family\s*:\s*["']?(KaTeX_(?:Size[1-4]|[A-Za-z]+))/);
      if(!family||!families.includes(family[1]))return '';
      const file=block.match(/url\(["']?fonts\/([A-Za-z0-9_-]+\.woff2)["']?\)/);
      if(!file)throw new Error('测试字体缺失');
      const data=fs.readFileSync(path.join(root,'vendor/katex/fonts',file[1])).toString('base64');
      return block.replace(/src\s*:[^;}]+/,'src:url(data:font/woff2;base64,'+data+') format("woff2")');
    });
  };
  await w.ensureTurndown();
  return {w,dom,load:async(md,path='/tmp/test.md',recovered=false,meta={})=>w.loadContent(path,md,720,recovered,false,meta),
    input(value){const ta=w.document.getElementById('textarea');ta.value=value;ta.dispatchEvent(new w.Event('input'));},
    close(){w.prepareForClose();dom.window.close();}};
}
module.exports={createApp};
