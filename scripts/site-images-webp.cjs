// 把 docs/images/_raw 里的截图转成 WebP（体积约为 PNG 的 1/4），社交分享图 og*.png 原样复制。
// 先运行：MAKE_SITE_IMAGES=1 npx playwright test tests/e2e/site-images.spec.js --project=webkit
// 再运行：node scripts/site-images-webp.cjs
const {chromium}=require('@playwright/test');
const fs=require('fs');
const path=require('path');
const RAW=path.join(__dirname,'../docs/images/_raw');
const OUT=path.join(__dirname,'../docs/images');
(async()=>{
  const browser=await chromium.launch();
  const page=await browser.newPage();
  for(const file of fs.readdirSync(RAW).filter(f=>f.endsWith('.png')).sort()){
    const src=path.join(RAW,file);
    if(file.startsWith('og')){fs.copyFileSync(src,path.join(OUT,file));console.log('copy',file);continue;}
    const b64=fs.readFileSync(src).toString('base64');
    const webp=await page.evaluate(async b=>{
      const img=new Image();img.src='data:image/png;base64,'+b;await img.decode();
      const c=document.createElement('canvas');c.width=img.naturalWidth;c.height=img.naturalHeight;
      c.getContext('2d').drawImage(img,0,0);
      return c.toDataURL('image/webp',0.9).split(',')[1];
    },b64);
    const out=path.join(OUT,file.replace(/\.png$/,'.webp'));
    fs.writeFileSync(out,Buffer.from(webp,'base64'));
    console.log(file,'→',(fs.statSync(out).size/1024).toFixed(0)+' KB');
  }
  await browser.close();
})();
