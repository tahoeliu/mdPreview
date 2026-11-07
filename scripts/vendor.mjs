import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = file => fs.readFileSync(path.join(root, file));
const json = file => JSON.parse(read(file));
const sha256 = data => crypto.createHash('sha256').update(data).digest('hex');
const serialize = value => JSON.stringify(value, null, 2) + '\n';
const check = process.argv.includes('--check');
if (process.argv.slice(2).some(arg => arg !== '--check')) throw new Error('仅支持 --check 参数');

// 这里只准备离线资源；旧根目录文件由主代理完成应用接线后删除。
const libraries = [
  { name: 'marked', files: [['marked.min.js', 'vendor/marked.min.js']] },
  { name: 'marked-footnote', files: [['dist/index.umd.js', 'vendor/marked-footnote.umd.js']] },
  { name: 'dompurify', files: [['dist/purify.min.js', 'vendor/purify.min.js']] },
  { name: 'mermaid', files: [['dist/mermaid.min.js', 'vendor/mermaid.min.js']] },
  { name: 'turndown', files: [['dist/turndown.js', 'vendor/turndown.js']] },
  { name: 'katex', files: [['dist/katex.min.js', 'vendor/katex/katex.min.js'], ['dist/katex.min.css', 'vendor/katex/katex.min.css']], fonts: 'dist/fonts' },
  { name: 'docx', files: [['dist/index.umd.cjs', 'vendor/docx.umd.js']] },
  { name: 'html-docx-js', files: [['dist/html-docx.js', 'vendor/html-docx-js.js']], legacy: true }
];
const supplementalLicenses = {
  'marked-footnote@1.4.0': {
    file: 'vendor/license-sources/marked-footnote-LICENSE',
    url: 'https://raw.githubusercontent.com/bent10/marked-extensions/faab750f00af4788397948286fb8f7fe0c929a7e/license',
    reason: 'npm 包 files 白名单遗漏许可证；取 npm view marked-footnote@1.4.0 gitHead 对应上游提交。'
  }
};
const policy = [
  'marked 固定 12.0.0：cjkEmStrong 依赖 Tokenizer.prototype.emStrong 内部签名，本卡不升级应用使用的大版本。Mermaid 私有依赖中的 marked 不替换应用的 marked。',
  'Mermaid 固定 11.16.0，与旧资源声明版本一致；本卡不引入 Mermaid 12 的集成变化。',
  'html-docx-js 仅作为 T10 legacy 回退保留一个版本；html2canvas 已移出依赖与资源清单，根文件由主代理集成 T09 后删除。',
  '许可证覆盖八个直接库的完整已安装运行时依赖闭包（含 peer、类型及 CLI 依赖，保守多收集），并保留浏览器包内嵌的捆绑依赖声明。安装树版本不等于上游预构建包内每个捆绑组件版本；内嵌声明单独保留，不虚构映射。',
  'npm ci --ignore-scripts 后运行 npm run vendor；npm run vendor:check 只校验不写文件。所有资源字节直接复制自 npm 包，不重新压缩或修改。',
  'T30 仅完成依赖准备；index/app.js、spec、资源打包与关于面板由主代理接入。WorkSpace/Credits.rtf 每次生成，不提交缓存。'
];
const project = json('package.json');
const lock = json('package-lock.json');
const outputs = new Map();
const packages = new Map();
const problems = new Set();
const put = (file, value) => outputs.set(file, Buffer.isBuffer(value) ? value : Buffer.from(value));

function resolvePackage(name, from = root) {
  let directory = from;
  while (directory.startsWith(root)) {
    const candidate = path.join(directory, 'node_modules', name);
    if (fs.existsSync(path.join(candidate, 'package.json'))) return path.relative(root, candidate).split(path.sep).join('/');
    if (directory === root) break;
    directory = path.dirname(directory);
  }
  throw new Error(`缺少 npm 包 ${name}（引用方 ${path.relative(root, from)}）`);
}

function licenseSources(directory) {
  const sources = [];
  function walk(relative) {
    for (const entry of fs.readdirSync(path.join(root, directory, relative), { withFileTypes: true }).sort((a, b) => a.name < b.name ? -1 : 1)) {
      if (entry.name === 'node_modules' || entry.name.startsWith('.')) continue;
      const file = path.posix.join(relative, entry.name);
      if (entry.isDirectory()) walk(file);
      else if (/^(licen[cs]e|copying|notice|copyright)([._-].*)?$/i.test(entry.name)) sources.push(`${directory}/${file}`);
    }
  }
  walk('');
  return sources;
}

function visit(directory, usedBy, seen = new Set()) {
  if (seen.has(directory)) return;
  seen.add(directory);
  const pkg = json(`${directory}/package.json`);
  const locked = lock.packages[directory];
  if (!locked || pkg.version !== locked.version || !locked.integrity || !locked.resolved) {
    throw new Error(`安装包与 package-lock 不一致或缺少来源：${directory}`);
  }
  let record = packages.get(directory);
  if (!record) {
    const id = `${pkg.name}@${pkg.version}`;
    const sources = licenseSources(directory);
    const supplement = supplementalLicenses[id];
    if (supplement) sources.push(supplement.file);
    if (!sources.length) problems.add(`${id} 缺少许可证全文`);
    const texts = sources.map(source => {
      if (!fs.existsSync(path.join(root, source))) {
        problems.add(`${id} 缺少许可证源文件 ${source}`);
        return '';
      }
      const bytes = read(source);
      if (!bytes.toString().trim()) problems.add(`${id} 许可证为空：${source}`);
      return `===== ${source} =====\n${bytes.toString().trimEnd()}\n`;
    });
    const licenseFile = `vendor/licenses/${pkg.name.replace('@', '').replaceAll('/', '__')}@${pkg.version}.txt`;
    put(licenseFile, texts.join('\n'));
    record = {
      id: directory, name: pkg.name, version: pkg.version, license: pkg.license || locked.license || '未声明',
      resolved: locked.resolved, integrity: locked.integrity, licenseFile,
      licenseSources: sources, ...(supplement ? { supplementalSource: supplement } : {}),
      dependencies: [], usedBy: []
    };
    packages.set(directory, record);
  }
  record.usedBy.push(usedBy);
  const dependencies = { ...pkg.dependencies, ...pkg.optionalDependencies, ...pkg.peerDependencies };
  for (const name of Object.keys(dependencies).sort()) {
    let dependency;
    try { dependency = resolvePackage(name, path.join(root, directory)); }
    catch (error) {
      if (pkg.optionalDependencies?.[name] || pkg.peerDependenciesMeta?.[name]?.optional) continue;
      throw error;
    }
    if (!record.dependencies.includes(dependency)) record.dependencies.push(dependency);
    visit(dependency, usedBy, seen);
  }
}

const entries = [];
for (const library of libraries) {
  const directory = resolvePackage(library.name);
  const pkg = json(`${directory}/package.json`);
  if (project.devDependencies[library.name] !== pkg.version || lock.packages[''].devDependencies[library.name] !== pkg.version) {
    throw new Error(`${library.name} 必须使用与 lock 一致的固定版本`);
  }
  visit(directory, library.name);
  let bundledPackages;
  if (library.name === 'mermaid') {
    // 上游预构建包还包含未列在 dependencies 的 js-yaml，以源映射核对覆盖。
    const sourceMap = json(`${directory}/dist/mermaid.min.js.map`);
    bundledPackages = [...new Set(sourceMap.sources.map(source =>
      source.match(/node_modules\/(?:\.pnpm\/[^/]+\/node_modules\/)?((?:@[^/]+\/)?[^/]+)/)?.[1]
    ).filter(Boolean))].sort();
    for (const name of bundledPackages) visit(resolvePackage(name, path.join(root, directory)), library.name);
  }
  const copies = [...library.files];
  if (library.fonts) {
    for (const name of fs.readdirSync(path.join(root, directory, library.fonts)).sort()) {
      // 保留 CSS 引用的全部字体格式，避免离线加载出现 404。
      if (/\.(woff2?|ttf)$/.test(name)) copies.push([`${library.fonts}/${name}`, `vendor/katex/fonts/${name}`]);
    }
  }
  const files = copies.map(([source, target]) => {
    const sourcePath = `${directory}/${source}`;
    const bytes = read(sourcePath);
    put(target, bytes);
    return { source: sourcePath, target, sha256: sha256(bytes) };
  });
  const embedded = files.filter(file => /\.js$/.test(file.target)).flatMap(file => {
    const text = read(file.source).toString();
    return [...text.matchAll(/^\s*\/\*[!*][\s\S]*?\*\//gm)]
      .filter(match => /licen[cs]e|copyright/i.test(match[0]))
      .map(match => `===== ${file.source} =====\n${match[0]}\n`);
  });
  const bundledNotices = embedded.length ? `vendor/bundled-notices/${library.name}.txt` : null;
  if (bundledNotices) put(bundledNotices, embedded.join('\n'));
  entries.push({ name: library.name, version: pkg.version, legacy: !!library.legacy, files, bundledNotices, ...(bundledPackages ? { bundledPackages } : {}) });
}
if (problems.size) throw new Error([...problems].sort().join('\n'));
const records = [...packages.values()].sort((a, b) => a.id < b.id ? -1 : 1);
for (const pkg of records) pkg.usedBy = [...new Set(pkg.usedBy)].sort();
const manifest = { schemaVersion: 1, policy, libraries: entries, packages: records };
put('vendor/manifest.json', serialize(manifest));
const sections = [
  '# 第三方软件声明\n\n由 scripts/vendor.mjs 自动生成；请勿手工编辑。\n',
  '## 版本与集成说明\n\n' + policy.map(line => `- ${line}`).join('\n') + '\n',
  '## 直接依赖\n\n| 库 | 固定版本 | 许可证 |\n|---|---|---|\n' + entries.map(lib => {
    const pkg = records.find(pkg => pkg.name === lib.name && pkg.version === lib.version);
    return `| ${lib.name} | ${lib.version} | ${pkg.license} |`;
  }).join('\n') + '\n'
];
for (const pkg of records) {
  sections.push(`## ${pkg.name} ${pkg.version}\n\n许可证：${pkg.license}\n\n依赖来源：${pkg.usedBy.join(', ')}\n\nnpm 来源：${pkg.resolved}\n\n完整性：\`${pkg.integrity}\`\n` +
    (pkg.supplementalSource ? `\n许可证补充来源：${pkg.supplementalSource.url}\n\n${pkg.supplementalSource.reason}\n` : '') +
    `\n~~~~text\n${outputs.get(pkg.licenseFile).toString()}~~~~\n`);
}
for (const lib of entries.filter(lib => lib.bundledNotices)) {
  sections.push(`## ${lib.name} 浏览器包内嵌第三方声明\n\n保留预构建包原文，补充安装依赖树许可证。\n\n~~~~text\n${outputs.get(lib.bundledNotices).toString()}~~~~\n`);
}
const notices = sections.join('\n');
put('THIRD_PARTY_NOTICES.md', notices);
function rtfEscape(text) {
  return text.replace(/\\/g, '\\\\').replace(/[{}]/g, '\\$&').replace(/\r/g, '').replace(/\n/g, '\\par\n')
    .replace(/[^\x00-\x7f]/g, character => {
      const code = character.charCodeAt(0);
      return `\\u${code > 32767 ? code - 65536 : code}?`;
    });
}
put('WorkSpace/Credits.rtf', '{\\rtf1\\ansi\\ansicpg1252\\uc1{\\fonttbl{\\f0 Helvetica;}}\\f0\\fs20\n' + rtfEscape(notices) + '\n}\n');
const checksums = Object.fromEntries([...outputs].filter(([file]) => !file.startsWith('WorkSpace/')).sort(([a], [b]) => a < b ? -1 : 1).map(([file, bytes]) => [file, sha256(bytes)]));
put('vendor/checksums.json', serialize(checksums));
// 先把全部输入验证完毕再落盘；缺包/缺许可证不产生伪完整清单。
const mismatches = [];
for (const [file, bytes] of outputs) {
  if (fs.existsSync(path.join(root, file)) && read(file).equals(bytes)) continue;
  if (check) mismatches.push(file);
  else {
    fs.mkdirSync(path.dirname(path.join(root, file)), { recursive: true });
    fs.writeFileSync(path.join(root, file), bytes);
  }
}
if (mismatches.length) throw new Error(`资源缺失或与固定来源不一致：\n${mismatches.join('\n')}`);
console.log(`${check ? '校验通过' : '生成完成'}：${entries.length} 个库，${records.length} 个依赖许可证，${Object.keys(checksums).length} 项 SHA-256。`);
