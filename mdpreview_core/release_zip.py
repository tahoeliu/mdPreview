"""验证已签名 ZIP 后受限解包；所有成员检查完成后才写入空目录。"""
import hashlib
import io
import unicodedata
import hmac
import os
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath
from .release_sig import signed_digest


def verify_archive(archive, manifest, signature):
    archive = Path(archive)
    expected = signed_digest(Path(manifest).read_bytes(), Path(signature).read_bytes(), archive.name)
    if archive.stat().st_size > 300 * 1024 * 1024:
        raise ValueError('archive-too-large')
    digest = hashlib.sha256()
    with archive.open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            digest.update(chunk)
    if not hmac.compare_digest(expected, digest.hexdigest()):
        raise ValueError('signed-archive-digest-mismatch')
    return digest.hexdigest()


def extract_verified(archive, manifest, signature, destination):
    # 只解包已经验签的不可变字节，避免路径替换或原文件并发修改。
    archive = Path(archive)
    expected = signed_digest(Path(manifest).read_bytes(), Path(signature).read_bytes(), archive.name)
    with archive.open('rb') as stream:
        payload = stream.read(300 * 1024 * 1024 + 1)
    if len(payload) > 300 * 1024 * 1024:
        raise ValueError('archive-too-large')
    if not hmac.compare_digest(expected, hashlib.sha256(payload).hexdigest()):
        raise ValueError('signed-archive-digest-mismatch')
    return extract(io.BytesIO(payload), destination)


def _canonical(name):
    return unicodedata.normalize('NFC', name).casefold()


def extract(archive, destination):
    destination = Path(destination)
    if destination.exists():
        raise ValueError('extraction-destination-must-not-exist')
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        if len(entries) > 100000 or sum(x.file_size for x in entries) > 1500 * 1024 * 1024:
            raise ValueError('archive-expansion-limit')
        names = set()
        links = {}
        for entry in entries:
            name = entry.filename.rstrip('/')
            path = PurePosixPath(name)
            if not name or '\\' in name or '\x00' in name or name.startswith('/') or any(x in ('', '.', '..') for x in name.split('/')):
                raise ValueError('unsafe-archive-path')
            if path.parts[0] != 'mdPreview.app' or _canonical(name) in names or entry.flag_bits & 1:
                raise ValueError('unexpected-archive-member')
            names.add(_canonical(name))
            mode = entry.external_attr >> 16
            kind = stat.S_IFMT(mode)
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK):
                raise ValueError('unsupported-archive-member')
            if stat.S_ISLNK(mode):
                if entry.file_size > 4096:
                    raise ValueError('invalid-symlink')
                target = bundle.read(entry).decode('utf-8')
                if not target or target.startswith('/') or '\\' in target or '\x00' in target:
                    raise ValueError('unsafe-symlink')
                resolved = os.path.normpath(str(path.parent / target))
                if resolved != 'mdPreview.app' and not resolved.startswith('mdPreview.app/'):
                    raise ValueError('escaping-symlink')
                links[_canonical(name)] = target
        # 按真实逐组件语义展开链接，再处理 ..；词法 normpath 不足以检查链接链。
        for name in links:
            pending = name.split('/')
            resolved = []
            hops = 0
            while pending:
                part = pending.pop(0)
                if part in ('', '.'):
                    continue
                if part == '..':
                    if len(resolved) <= 1:
                        raise ValueError('escaping-symlink-chain')
                    resolved.pop()
                    continue
                resolved.append(part)
                target = links.get(_canonical('/'.join(resolved)))
                if target is not None:
                    hops += 1
                    if hops > 40:
                        raise ValueError('cyclic-symlink')
                    resolved.pop()
                    pending = target.split('/') + pending
            if not resolved or _canonical(resolved[0]) != 'mdpreview.app':
                raise ValueError('escaping-symlink-chain')
        for entry in entries:
            path = PurePosixPath(entry.filename)
            if any(_canonical(str(parent)) in links for parent in path.parents):
                raise ValueError('write-through-symlink')
        destination.mkdir(mode=0o700)
        for entry in entries:
            target = destination / entry.filename
            mode = entry.external_attr >> 16
            if stat.S_ISLNK(mode):
                continue
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(entry) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output, 65536)
                target.chmod(0o755 if mode & 0o111 else 0o644)
        for name, target in links.items():
            # 保留原始大小写；casefold仅用于拒绝冲突。
            original = next(x.filename for x in entries if _canonical(x.filename.rstrip('/')) == name)
            link = destination / original
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(target)
    return destination / 'mdPreview.app'
