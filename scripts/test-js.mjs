import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
const root=path.resolve(import.meta.dirname,'..');
let failed=false;
for(const file of fs.readdirSync(path.join(root,'tests')).filter(f=>/^test_.*\.js$/.test(f)).sort()) {
  const result=spawnSync(process.execPath,[path.join(root,'tests',file)],{cwd:root,stdio:'inherit',timeout:60000});
  if(result.status!==0) failed=true;
}
process.exitCode=failed?1:0;
