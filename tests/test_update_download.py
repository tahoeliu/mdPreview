"""签名 ZIP 更新下载管线：使用一次性测试密钥，全程不联网。"""
import base64
import hashlib
import http.client
import io
import plistlib
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mdpreview_core import release, release_sig, update_download  # noqa: E402

VERSION = '9.9.9'
ZIP_NAME = f'mdPreview-{VERSION}-universal.zip'


class FakeResponse:
    def __init__(self, data, headers=None, status=200):
        self._stream = io.BytesIO(data)
        self.headers = {'Content-Length': str(len(data))} if headers is None else dict(headers)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, amount=-1):
        return self._stream.read(amount)


def make_archive(version=VERSION):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('mdPreview.app/Contents/Info.plist', plistlib.dumps({
            'CFBundleIdentifier': 'tahoeliu.mdpreview',
            'CFBundleExecutable': 'mdPreview', 'CFBundleShortVersionString': version}))
        archive.writestr('mdPreview.app/Contents/MacOS/mdPreview', 'binary')
    return buffer.getvalue()


class Fixture:
    """签名清单直连假发布：真实 P-256 签名，API 始终不可用。"""

    def __init__(self, folder, archive=None):
        self.root = root = Path(folder)
        subprocess.run(['openssl', 'ecparam', '-name', 'prime256v1', '-genkey', '-noout', '-out', str(root / 'key')], check=True)
        public = subprocess.check_output(['openssl', 'ec', '-in', str(root / 'key'), '-pubout', '-outform', 'DER'],
                                         stderr=subprocess.DEVNULL)[-65:]
        self.public_b64 = base64.b64encode(public).decode()
        self.archive = archive if archive is not None else make_archive()
        self.sign_manifest()
        self.requests = []
        self.api_status = 503
        self.archive_headers = None
        self.archive_status = 200
        self.base = 'https://github.com/tahoeliu/mdPreview/releases/download/v' + VERSION + '/'

    def sign_manifest(self, filename=ZIP_NAME):
        signing = Path(tempfile.mkdtemp(prefix='signing-', dir=self.root))
        self.manifest = (hashlib.sha256(self.archive).hexdigest() + '  ' + filename + '\n').encode()
        (signing / 'manifest').write_bytes(self.manifest)
        subprocess.run(['openssl', 'dgst', '-sha256', '-sign', str(self.root / 'key'),
                        '-out', str(signing / 'sig'), str(signing / 'manifest')], check=True)
        self.signature = (signing / 'sig').read_bytes()

    def urlopen(self, request, timeout=None, context=None):
        url = request.full_url
        self.requests.append(url)
        if url.startswith('https://api.github.com/'):
            raise urllib.error.HTTPError(url, self.api_status, 'API 不可用', {}, None)
        if url == self.base + 'SHA256SUMS.sig':
            return FakeResponse(self.signature)
        if url == self.base + 'SHA256SUMS':
            return FakeResponse(self.manifest)
        if url == self.base + ZIP_NAME:
            return FakeResponse(self.archive, self.archive_headers, self.archive_status)
        raise AssertionError('意外请求 ' + url)


class DownloadPipeline(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix='update-download-', dir=ROOT / 'WorkSpace'))
        self.addCleanup(__import__('shutil').rmtree, self.folder, True)
        self.staging = self.folder / 'staging'
        self.fixture = Fixture(self.folder)
        for patcher in (patch.object(release_sig, 'RELEASE_PUBKEY_B64', self.fixture.public_b64),
                        patch('platform.machine', return_value='arm64'),
                        patch.object(update_download.time, 'sleep'),
                        patch.object(update_download, 'verify_bundle', side_effect=self.verify_bundle)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def verify_bundle(self, app, team, version):
        self.assertTrue(Path(app).is_relative_to(self.staging))
        with patch.object(release.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as codesign:
            result = release.verify_bundle(app, team, version)
        codesign.assert_called_once_with(
            ['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)],
            check=True, capture_output=True, timeout=30)
        return result

    def run_download(self, **extra):
        with patch('urllib.request.urlopen', side_effect=self.fixture.urlopen):
            return update_download.download(VERSION, '1.0.0', self.staging, **extra)

    def assert_manifest_only(self):
        self.assertEqual(self.fixture.requests,
                         [self.fixture.base + name for name in ('SHA256SUMS', 'SHA256SUMS.sig')])
        self.assertFalse(self.staging.exists())
        update_download.verify_bundle.assert_not_called()

    def test_happy_path_stages_verified_app_and_reports_progress(self):
        seen = []
        result = self.run_download(progress=seen.append)
        self.assertEqual(result['version'], VERSION)
        self.assertTrue((Path(result['staging_app']) / 'Contents/MacOS/mdPreview').is_file())
        self.assertTrue(Path(result['manifest']).is_file() and Path(result['signature']).is_file())
        self.assertEqual(seen[-1], 100)
        self.assertEqual(seen, sorted(seen))
        self.assertEqual(result['size'], len(self.fixture.archive))
        self.assertEqual(result['content_length'], len(self.fixture.archive))
        self.assertEqual(self.fixture.requests, [self.fixture.base + name
                         for name in ('SHA256SUMS', 'SHA256SUMS.sig', ZIP_NAME)])
        update_download.verify_bundle.assert_called_once()

    def test_api_unavailable_does_not_block_signed_direct_download(self):
        for status in (403, 429, 503):
            with self.subTest(status=status):
                self.fixture.api_status = status
                self.fixture.requests.clear()
                result = self.run_download()
                self.assertEqual(Path(result['archive']).read_bytes(), self.fixture.archive)
                self.assertEqual(self.fixture.requests, [self.fixture.base + name
                                 for name in ('SHA256SUMS', 'SHA256SUMS.sig', ZIP_NAME)])

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
        with self.assertRaisesRegex(update_download.DownloadError, 'signed-digest-mismatch') as caught:
            self.run_download()
        self.assertEqual(caught.exception.stage, 'digest')
        update_download.verify_bundle.assert_not_called()

    def test_signature_from_another_key_rejected(self):
        other = tempfile.mkdtemp(prefix='other-key-', dir=self.folder)
        self.fixture.signature = Fixture(other, archive=self.fixture.archive).signature
        with self.assertRaisesRegex(ValueError, 'signature'):
            self.run_download()
        self.assert_manifest_only()

    def test_tampered_manifest_rejected(self):
        first = self.fixture.manifest[:1]
        self.fixture.manifest = (b'b' if first == b'a' else b'a') + self.fixture.manifest[1:]
        with self.assertRaisesRegex(ValueError, 'release-signature-invalid-or-unconfigured'):
            self.run_download()
        self.assert_manifest_only()

    def test_unsigned_asset_name_rejected(self):
        self.fixture.sign_manifest(f'mdPreview-{VERSION}-x86_64.zip')
        self.fixture.manifest += (hashlib.sha256(self.fixture.archive).hexdigest() + '  ' + ZIP_NAME + '\n').encode()
        with self.assertRaisesRegex(ValueError, 'release-signature-invalid-or-unconfigured'):
            self.run_download()
        self.assert_manifest_only()

    def test_missing_compatible_zip(self):
        self.fixture.sign_manifest(f'mdPreview-{VERSION}-x86_64.zip')
        self.assertTrue(release_sig.verify(self.fixture.manifest, self.fixture.signature))
        with self.assertRaisesRegex(ValueError, 'compatible-zip-not-found'):
            self.run_download()
        self.assert_manifest_only()

    def test_signed_manifest_for_wrong_version_rejected(self):
        self.fixture.sign_manifest('mdPreview-0.0.1-universal.zip')
        self.assertTrue(release_sig.verify(self.fixture.manifest, self.fixture.signature))
        with self.assertRaisesRegex(ValueError, 'compatible-zip-not-found'):
            self.run_download()
        self.assert_manifest_only()

    def test_signed_archive_with_wrong_bundle_version_rejected(self):
        self.fixture.archive = make_archive('0.0.1')
        self.fixture.sign_manifest()
        with self.assertRaisesRegex(update_download.DownloadError, 'verification-failed') as caught:
            self.run_download()
        self.assertEqual(caught.exception.stage, 'bundle')
        update_download.verify_bundle.assert_called_once()

    def test_nonrelease_versions_rejected_before_network(self):
        for version in ('draft', VERSION + '-rc.1', 'v' + VERSION):
            with self.subTest(version=version), \
                    patch('urllib.request.urlopen', side_effect=AssertionError('禁止联网')):
                with self.assertRaisesRegex(ValueError, 'invalid-release-version'):
                    update_download.download(version, '1.0.0', self.staging)

    def test_unsupported_architecture(self):
        with patch('platform.machine', return_value='ppc64'):
            with self.assertRaisesRegex(ValueError, 'unsupported-architecture'):
                self.run_download()

    def test_size_limit_on_manifest(self):
        self.fixture.manifest = b'a' * 2_000_000
        with self.assertRaisesRegex(ValueError, 'download-size-limit'):
            self.run_download()

    def test_content_length_mismatch_rejected(self):
        for difference, code in ((1, 'incomplete-download'), (-1, 'content-length-mismatch')):
            with self.subTest(difference=difference):
                self.fixture.archive_headers = {'Content-Length': str(len(self.fixture.archive) + difference)}
                with self.assertRaises(update_download.DownloadError) as caught:
                    self.run_download()
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(caught.exception.stage, 'archive')
                self.assertEqual(caught.exception.category, 'incomplete')
                update_download.verify_bundle.assert_not_called()

    def test_missing_content_length_still_requires_signed_digest(self):
        self.fixture.archive_headers = {}
        result = self.run_download()
        self.assertIsNone(result['content_length'])
        self.assertEqual(result['size'], len(self.fixture.archive))
        update_download.verify_bundle.reset_mock()
        self.fixture.archive += b'tampered'
        with self.assertRaisesRegex(ValueError, 'signed-digest-mismatch'):
            self.run_download()
        update_download.verify_bundle.assert_not_called()

    def test_partial_response_rejected_even_with_signed_bytes(self):
        self.fixture.archive_status = 206
        with self.assertRaises(update_download.DownloadError) as caught:
            self.run_download()
        self.assertEqual(caught.exception.code, 'unexpected-http-status')
        self.assertEqual(caught.exception.http, 206)
        self.assertEqual(caught.exception.stage, 'archive')
        update_download.verify_bundle.assert_not_called()


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
