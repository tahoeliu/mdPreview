"""签名 ZIP 下载管线：信任根缺失时不发起网络请求。"""
import hashlib
import json
import platform
import http.client
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from .release import verify_asset, verify_bundle, version_tuple
from .release_sig import configured, signed_digest
from .release_zip import extract_verified


def classify(error):
    """把下载管线异常归类为界面使用的错误码：network | incomplete | verify | unknown。"""
    if isinstance(error, (urllib.error.URLError, TimeoutError)):
        return 'network'
    if isinstance(error, http.client.IncompleteRead):
        return 'incomplete'
    if isinstance(error, ValueError):
        if str(error) in ('download-size-limit', 'archive-too-large'):
            return 'incomplete'
        return 'verify'
    return 'unknown'


def download(version, installed_version, staging, team_id=None, progress=None):
    if not configured():
        raise ValueError('release-signing-key-not-configured')
    version_tuple(version)
    if version_tuple(version) < version_tuple(installed_version):
        raise ValueError('update-downgrade-refused')
    base = 'https://github.com/tahoeliu/mdPreview/releases/download/v' + version + '/'
    def fetch(url, limit):
        request = urllib.request.Request(url, headers={'User-Agent': 'mdPreview'})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(limit + 1)
            if len(data) > limit:
                raise ValueError('download-size-limit')
            return data
    metadata = json.loads(fetch('https://api.github.com/repos/tahoeliu/mdPreview/releases/tags/v' + version, 2000000))
    if metadata.get('tag_name') != 'v' + version or metadata.get('draft') or metadata.get('prerelease'):
        raise ValueError('unexpected-release')
    arch = platform.machine()
    if arch not in ('arm64', 'x86_64'):
        raise ValueError('unsupported-architecture')
    assets = {item['name']: item for item in metadata.get('assets', [])}
    candidates = [f'mdPreview-{version}-{arch}.zip', f'mdPreview-{version}-universal.zip']
    filename = next((name for name in candidates if name in assets), None)
    if filename is None:
        raise ValueError('compatible-zip-not-found')
    manifest = fetch(base + 'SHA256SUMS', 1048576)
    signature = fetch(base + 'SHA256SUMS.sig', 80)
    expected = signed_digest(manifest, signature, filename)
    Path(staging).mkdir(parents=True, exist_ok=True)
    job = Path(tempfile.mkdtemp(prefix='signed-', dir=staging))
    archive = job / filename
    request = urllib.request.Request(base + filename, headers={'User-Agent': 'mdPreview'})
    digest = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(request, timeout=60) as response, archive.open('xb') as output:
        while True:
            chunk = response.read(65536)
            if not chunk:
                break
            size += len(chunk)
            if size > 300 * 1024 * 1024:
                raise ValueError('download-size-limit')
            output.write(chunk)
            digest.update(chunk)
            if progress:
                progress(min(99, size * 100 // max(1, assets[filename]['size'])))
    if digest.hexdigest() != expected:
        raise ValueError('signed-digest-mismatch')
    verify_asset(digest.hexdigest(), size, assets[filename])
    (job / 'SHA256SUMS').write_bytes(manifest)
    (job / 'SHA256SUMS.sig').write_bytes(signature)
    app = extract_verified(archive, job / 'SHA256SUMS', job / 'SHA256SUMS.sig', job / 'verified')
    verify_bundle(app, team_id, version)
    if progress:
        progress(100)
    return {'staging_app': str(app), 'version': version, 'archive': str(archive),
            'manifest': str(job / 'SHA256SUMS'), 'signature': str(job / 'SHA256SUMS.sig'), 'dmg_path': ''}
