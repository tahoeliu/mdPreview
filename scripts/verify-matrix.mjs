import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';

export const required = {
  pdf: ['Preview', 'Safari', 'Chrome', 'Acrobat', 'iOS Files', 'WeChat', 'A4'],
  word: ['Word Mac', 'Word Windows', 'Pages', 'WPS', 'Google Docs', 'LibreOffice', 'Feishu', 'DingTalk'],
  html: ['Safari', 'Chrome', 'Edge Windows', 'mobile', 'dark'],
  png: ['WeChat compressed', 'iPhone Photos'],
  richtext: ['WeChat', 'Feishu', 'DingTalk', 'Outlook', 'Gmail', 'Word', 'Notion', 'Notes'],
  install: ['CLI', 'Homebrew', 'DMG', 'macOS13', 'macOS14', 'macOS15', 'macOS26', 'arm64', 'Intel-Rosetta'],
  headless: ['hidden-window', 'zero-network', 'timeout-no-late-write', 'exit-codes'],
};

export function bundleDigest(root) {
  if (!fs.statSync(root).isDirectory()) throw new Error('待验收应用必须是目录');
  const hash = crypto.createHash('sha256');
  function walk(relative) {
    for (const name of fs.readdirSync(path.join(root, relative)).sort()) {
      const rel = path.join(relative, name), file = path.join(root, rel), stat = fs.lstatSync(file);
      hash.update(JSON.stringify([rel, stat.mode]));
      if (stat.isSymbolicLink()) hash.update(JSON.stringify(['link', fs.readlinkSync(file)]));
      else if (stat.isDirectory()) walk(rel);
      else if (stat.isFile()) {
        hash.update(JSON.stringify(['file', stat.size]));
        const fd = fs.openSync(file, 'r'), buffer = Buffer.alloc(65536);
        try { let count; while ((count = fs.readSync(fd, buffer, 0, buffer.length, null))) hash.update(buffer.subarray(0, count)); }
        finally { fs.closeSync(fd); }
      } else throw new Error('应用包包含不支持的文件类型');
    }
  }
  walk('');
  return hash.digest('hex');
}

export function validateMatrix(matrix, {version, bundleSha256, base}) {
  const meta = matrix.metadata;
  if (!meta || meta.version !== version || meta.bundleSha256 !== bundleSha256 || !meta.reviewer?.trim())
    throw new Error('矩阵必须绑定当前版本、应用包SHA-256及审核人');
  for (const [format, targets] of Object.entries(required)) for (const target of targets) {
    const entry = matrix[format]?.[target], stamp = Date.parse(entry?.verifiedAt);
    if (entry?.status !== 'passed' || !entry.environment?.trim() || !Number.isFinite(stamp) || stamp > Date.now())
      throw new Error('缺失人工通过结论、环境或实测日期：' + format + '/' + target);
    if (typeof entry.evidence !== 'string' || !/\.(png|jpe?g)$/i.test(entry.evidence) || !/^[a-f0-9]{64}$/.test(entry.sha256 || ''))
      throw new Error('必须提供截图与SHA-256：' + format + '/' + target);
    const file = path.resolve(base, entry.evidence);
    if (!fs.statSync(file).isFile()) throw new Error('证据不是文件');
    if (crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex') !== entry.sha256)
      throw new Error('证据摘要不符：' + format + '/' + target);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  const [file, app, version] = process.argv.slice(2);
  if (!file || !app || !version) throw new Error('必须提供矩阵、待验收应用及版本；不能跳过');
  validateMatrix(JSON.parse(fs.readFileSync(file, 'utf8')), {
    version, bundleSha256: bundleDigest(app), base: path.dirname(path.resolve(file)),
  });
  console.log('矩阵版本、应用包及截图摘要匹配；截图内容和结论仍须人工审核');
}
