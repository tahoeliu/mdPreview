"""用真实应用包跑一遍完整更新下载管线（不联网、不安装）。

假 GitHub 由本地文件提供：release 元数据、SHA256SUMS、签名（一次性测试密钥）和真实应用打出的 ZIP。
管线里的签名校验、摘要校验、安全解包和 codesign/Info.plist 校验全部是真实实现；
最后确认暂存出来的应用与原应用逐文件一致。用法：
  .venv/bin/python scripts/verify-update-e2e.py --app path/to/mdPreview.app
"""
import argparse
import base64
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mdpreview_core import release_sig, update_download  # noqa: E402


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def tree_digest(app):
    digest = hashlib.sha256()
    for path in sorted(p for p in app.rglob('*') if p.is_file() and not p.is_symlink()):
        digest.update(str(path.relative_to(app)).encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app', required=True)
    app = Path(parser.parse_args().app).resolve()
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    with tempfile.TemporaryDirectory(prefix='update-e2e-') as folder:
        work = Path(folder)
        subprocess.run([sys.executable, str(ROOT / 'scripts/package-release.py'), '--app', str(app), '--out', str(work / 'release')],
                       check=True, capture_output=True)
        archive = next((work / 'release').glob('mdPreview-*.zip'))
        subprocess.run(['openssl', 'ecparam', '-name', 'prime256v1', '-genkey', '-noout', '-out', str(work / 'key')], check=True)
        public = subprocess.check_output(['openssl', 'ec', '-in', str(work / 'key'), '-pubout', '-outform', 'DER'], stderr=subprocess.DEVNULL)[-65:]
        manifest = (hashlib.sha256(archive.read_bytes()).hexdigest() + '  ' + archive.name + '\n').encode()
        (work / 'manifest').write_bytes(manifest)
        subprocess.run(['openssl', 'dgst', '-sha256', '-sign', str(work / 'key'), '-out', str(work / 'sig'), str(work / 'manifest')], check=True)
        signature = (work / 'sig').read_bytes()
        metadata = {'tag_name': 'v' + version, 'draft': False, 'prerelease': False,
                    'assets': [{'name': archive.name, 'size': archive.stat().st_size,
                                'digest': 'sha256:' + hashlib.sha256(archive.read_bytes()).hexdigest()}]}

        def urlopen(request, timeout=None):
            url = request.full_url
            if '/releases/tags/' in url:
                return Response(json.dumps(metadata).encode())
            if url.endswith('SHA256SUMS.sig'):
                return Response(signature)
            if url.endswith('SHA256SUMS'):
                return Response(manifest)
            if url.endswith(archive.name):
                return Response(archive.read_bytes())
            raise AssertionError('unexpected request: ' + url)

        progress = []
        with mock.patch.object(release_sig, 'RELEASE_PUBKEY_B64', base64.b64encode(public).decode()), \
                mock.patch.object(urllib.request, 'urlopen', urlopen):
            result = update_download.download(version, '0.0.1', work / 'staging', None, progress.append)
        staged = Path(result['staging_app'])
        assert tree_digest(staged) == tree_digest(app), 'staged application differs from the original'
        assert progress and progress[-1] == 100, 'progress did not complete'
        # 篡改一个字节：同一管线必须拒绝。
        tampered = bytearray(archive.read_bytes())
        tampered[len(tampered) // 2] ^= 0xFF
        archive.write_bytes(bytes(tampered))
        with mock.patch.object(release_sig, 'RELEASE_PUBKEY_B64', base64.b64encode(public).decode()), \
                mock.patch.object(urllib.request, 'urlopen', urlopen):
            try:
                update_download.download(version, '0.0.1', work / 'staging2', None)
            except ValueError as error:
                print('tampered archive rejected:', error)
            else:
                raise AssertionError('tampered archive was accepted')
    print(f'update pipeline e2e passed for {app.name} {version}: staged app identical to original')


if __name__ == '__main__':
    try:
        main()
    except (AssertionError, subprocess.CalledProcessError) as error:
        print('update e2e FAILED:', error, file=sys.stderr)
        raise SystemExit(1)
