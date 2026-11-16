import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { performance } from 'node:perf_hooks';
const root=path.resolve(import.meta.dirname,'..');
let failures=0;
const tests=fs.readdirSync(path.join(root,'tests')).filter(f=>/^test_.*\.js$/.test(f)).sort();
for(const file of tests) {
  // vendor 实测约 70s：两次子进程各约 22s，其余文件读取约 26s；只给此套件额外 I/O 余量。
  const timeout=file==='test_vendor.js'?120000:60000;
  console.log(`运行套件：tests/${file}，预算=${timeout}ms`);
  const started=performance.now();
  const result=spawnSync(process.execPath,[path.join(root,'tests',file)],{cwd:root,stdio:'inherit',timeout});
  const elapsed=Math.round(performance.now()-started);
  if(result.error||result.status!==0) {
    failures++;
    console.error(`套件失败：tests/${file}，elapsed=${elapsed}ms，预算=${timeout}ms，退出码=${result.status}，信号=${result.signal}，错误=${result.error?.code??'无'}`);
  } else {
    console.log(`套件通过：tests/${file}，elapsed=${elapsed}ms`);
  }
}
console.log(`前端门禁：${tests.length} 套，${tests.length-failures} 通过，${failures} 失败`);
process.exitCode=failures?1:0;
