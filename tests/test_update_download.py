"""签名 ZIP 更新下载管线：使用一次性测试密钥，全程不联网。"""
import base64
import hashlib
import http.client
import io
import json
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mdpreview_core import release_sig, update_download  # noqa: E402

VERSION = '9.9.9'
ZIP_NAME = f'mdPreview-{VERSION}-universal.zip'


class FakeResponse:
    def __init__(self, data):
        self._stream = io.BytesIO(data)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, amount=-1):
        return self._stream.read(amount)


def make_archive():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('mdPreview.app/Contents/Info.plist', 'plist')
        archive.writestr('mdPreview.app/Contents/MacOS/mdPreview', 'binary')
    return buffer.getvalue()


class Fixture:
    """一个自洽的假发布：元数据、SHA256SUMS、签名与 ZIP 都由测试密钥生成。"""

    def __init__(self, folder, archive=None):
        root = Path(folder)
        subprocess.run(['openssl', 'ecparam', '-name', 'prime256v1', '-genkey', '-noout', '-out', str(root / 'key')], check=True)
        public = subprocess.check_output(['openssl', 'ec', '-in', str(root / 'key'), '-pubout', '-outform', 'DER'],
                                         stderr=subprocess.DEVNULL)[-65:]
        self.public_b64 = base64.b64encode(public).decode()
        self.archive = archive if archive is not None else make_archive()
        self.manifest = (hashlib.sha256(self.archive).hexdigest() + '  ' + ZIP_NAME + '\n').encode()
        (root / 'manifest').write_bytes(self.manifest)
        subprocess.run(['openssl', 'dgst', '-sha256', '-sign', str(root / 'key'), '-out', str(root / 'sig'), str(root / 'manifest')], check=True)
        self.signature = (root / 'sig').read_bytes()
        self.metadata = {'tag_name': 'v' + VERSION, 'draft': False, 'prerelease': False,
                         'assets': [{'name': ZIP_NAME, 'size': len(self.archive),
                                     'digest': 'sha256:' + hashlib.sha256(self.archive).hexdigest()}]}

    def urlopen(self, request, timeout=None):
        url = request.full_url
        if url.endswith('/releases/tags/v' + VERSION):
            return FakeResponse(json.dumps(self.metadata).encode())
        if url.endswith('SHA256SUMS.sig'):
            return FakeResponse(self.signature)
        if url.endswith('SHA256SUMS'):
            return FakeResponse(self.manifest)
        if url.endswith(ZIP_NAME):
            return FakeResponse(self.archive)
        raise AssertionError('unexpected url ' + url)


class DownloadPipeline(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.staging = Path(self.folder.name) / 'staging'
        self.fixture = Fixture(self.folder.name)
        for patcher in (patch.object(release_sig, 'RELEASE_PUBKEY_B64', self.fixture.public_b64),
                        patch('platform.machine', return_value='arm64'),
                        patch.object(update_download, 'verify_bundle', side_effect=lambda app, team, version: version)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_download(self, **extra):
        with patch('urllib.request.urlopen', side_effect=self.fixture.urlopen):
            return update_download.download(VERSION, '1.0.0', self.staging, **extra)

    def test_happy_path_stages_verified_app_and_reports_progress(self):
        seen = []
        result = self.run_download(progress=seen.append)
        self.assertEqual(result['version'], VERSION)
        self.assertTrue((Path(result['staging_app']) / 'Contents/MacOS/mdPreview').is_file())
        self.assertTrue(Path(result['manifest']).is_file() and Path(result['signature']).is_file())
        self.assertEqual(seen[-1], 100)
        self.assertEqual(seen, sorted(seen))

    def test_unconfigured_key_makes_no_network_request(self):
        with patch.object(release_sig, 'RELEASE_PUBKEY_B64', ''), \
                patch('urllib.request.urlopen', side_effect=AssertionError('network used')):
            with self.assertRaisesRegex(ValueError, 'not-configured'):
                update_download.download(VERSION, '1.0.0', self.staging)

    def test_downgrade_refused(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('network used')):
            with self.assertRaisesRegex(ValueError, 'downgrade'):
                update_download.download('1.0.0', '2.0.0', self.staging)

    def test_tampered_archive_rejected(self):
        original = self.fixture.archive
        self.fixture.archive = original + b'tampered'
        with self.assertRaisesRegex(ValueError, 'digest-mismatch|differs'):
            self.run_download()

    def test_signature_from_another_key_rejected(self):
        with tempfile.TemporaryDirectory() as other:
            self.fixture.signature = Fixture(other).signature
        with self.assertRaisesRegex(ValueError, 'signature'):
            self.run_download()

    def test_tampered_manifest_rejected(self):
        first = self.fixture.manifest[:1]
        self.fixture.manifest = (b'b' if first == b'a' else b'a') + self.fixture.manifest[1:]
        with self.assertRaises(ValueError):
            self.run_download()

    def test_unsigned_asset_name_rejected(self):
        self.fixture.metadata['assets'][0]['name'] = f'mdPreview-{VERSION}-arm64.zip'
        with self.assertRaisesRegex(ValueError, 'asset-not-signed'):
            self.run_download()

    def test_missing_compatible_zip(self):
        self.fixture.metadata['assets'] = []
        with self.assertRaisesRegex(ValueError, 'compatible-zip-not-found'):
            self.run_download()

    def test_draft_prerelease_and_wrong_tag_rejected(self):
        for change in ({'draft': True}, {'prerelease': True}, {'tag_name': 'v0.0.1'}):
            with self.subTest(change=change):
                self.fixture.metadata.update(change)
                with self.assertRaisesRegex(ValueError, 'unexpected-release'):
                    self.run_download()
                self.fixture.metadata.update({'draft': False, 'prerelease': False, 'tag_name': 'v' + VERSION})

    def test_unsupported_architecture(self):
        with patch('platform.machine', return_value='ppc64'):
            with self.assertRaisesRegex(ValueError, 'unsupported-architecture'):
                self.run_download()

    def test_size_limit_on_manifest(self):
        self.fixture.manifest = b'a' * 2_000_000
        with self.assertRaisesRegex(ValueError, 'download-size-limit'):
            self.run_download()

    def test_published_size_mismatch_rejected(self):
        self.fixture.metadata['assets'][0]['size'] += 1
        with self.assertRaises(ValueError):
            self.run_download()


class Classify(unittest.TestCase):
    def test_codes(self):
        self.assertEqual(update_download.classify(urllib.error.HTTPError('u', 404, 'x', {}, None)), 'network')
        self.assertEqual(update_download.classify(urllib.error.URLError('dns')), 'network')
        self.assertEqual(update_download.classify(TimeoutError()), 'network')
        self.assertEqual(update_download.classify(http.client.IncompleteRead(b'x')), 'incomplete')
        self.assertEqual(update_download.classify(ValueError('download-size-limit')), 'incomplete')
        self.assertEqual(update_download.classify(ValueError('archive-too-large')), 'incomplete')
        self.assertEqual(update_download.classify(ValueError('signed-digest-mismatch')), 'verify')
        self.assertEqual(update_download.classify(RuntimeError('boom')), 'unknown')
        self.assertEqual(update_download.classify(PermissionError('disk')), 'unknown')


if __name__ == '__main__':
    unittest.main(verbosity=2)
