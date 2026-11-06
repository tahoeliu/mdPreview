import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
const root = path.resolve(import.meta.dirname, '..');
const copies = {
  'purify.min.js': 'node_modules/dompurify/dist/purify.min.js',
  'marked-footnote.umd.js': 'node_modules/marked-footnote/dist/index.umd.js'
};
for (const [target, source] of Object.entries(copies)) fs.copyFileSync(path.join(root, source), path.join(root, target));
const files = ['marked.min.js','mermaid.min.js','turndown.js','html-docx-js.js','html2canvas.min.js',...Object.keys(copies)];
const checks = Object.fromEntries(files.map(file => [file,crypto.createHash('sha256').update(fs.readFileSync(path.join(root,file))).digest('hex')]));
fs.mkdirSync(path.join(root,'vendor/licenses'),{recursive:true});
for (const name of ['dompurify','marked-footnote']) {
  const license = ['LICENSE','LICENSE.txt','license'].find(f => fs.existsSync(path.join(root,'node_modules',name,f)));
  if (license) fs.copyFileSync(path.join(root,'node_modules',name,license),path.join(root,'vendor/licenses',name+'.txt'));
}
fs.writeFileSync(path.join(root,'vendor/checksums.json'),JSON.stringify(checks,null,2)+'\n');
console.log('Offline dependencies and SHA-256 manifest generated');
