"""下载恢复回归：模拟网络/时钟/系统签名命令，仅写临时目录，不读取任何私钥。

管线清单的密码学原语使用严格字节匹配替身；真实清单解析、摘要、ZIP 解包与
bundle 身份检查仍执行。原生密码学另以公开发布清单/签名验证，不需要私钥。
"""
import base64
import hashlib
import http.client
import importlib.util
import io
import json
import plistlib
import ssl
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mdpreview_core import release, release_sig, update_download


VERSION = '2.0.8'
ARM = f'mdPreview-{VERSION}-arm64.zip'
INTEL = f'mdPreview-{VERSION}-x86_64.zip'
UNIVERSAL = f'mdPreview-{VERSION}-universal.zip'
BASE = 'https://github.com/tahoeliu/mdPreview/releases/download/v' + VERSION + '/'


def archive_bytes(members=None, version=VERSION, identifier='tahoeliu.mdpreview'):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        if members is None:
            members = {
                'mdPreview.app/Contents/Info.plist': plistlib.dumps({
                    'CFBundleIdentifier': identifier,
                    'CFBundleShortVersionString': version,
                    'CFBundleExecutable': 'mdPreview',
                }),
                'mdPreview.app/Contents/MacOS/mdPreview': b'test-binary',
            }
        for name, content in members.items():
            archive.writestr(name, content)
    return buffer.getvalue()


class Response:
    def __init__(self, data=b'', headers=None, chunks=None, status=200, tick=None):
        self.data = io.BytesIO(data)
        self.headers = headers if headers is not None else {'Content-Length': str(len(data))}
        self.chunks = iter(chunks) if chunks is not None else None
        self.status = status
        self.tick = tick
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def read(self, amount):
        if self.tick:
            self.tick()
        if self.chunks is not None:
            chunk = next(self.chunks, b'')
            if isinstance(chunk, Exception):
                raise chunk
            return chunk
        return self.data.read(amount)

    read1 = read


class Clock:
    def __init__(self):
        self.now = 0
        self.delays = []

    def monotonic(self):
        return self.now

    def sleep(self, delay):
        self.delays.append(delay)
        self.now += delay


def http_error(status, headers=None):
    return urllib.error.HTTPError('https://private.invalid/?secret=PRIVATE', status,
                                  'PRIVATE response /Users/PRIVATE', headers or {}, io.BytesIO(b'PRIVATE'))


class DownloadRecovery(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='mdpreview-download-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.staging = self.root / 'staging'
        self.payload = archive_bytes()
        self.signature = b'fixture-signature'
        self.manifest = (hashlib.sha256(self.payload).hexdigest() + '  ' + UNIVERSAL + '\n').encode()
        self.trusted_manifest = self.manifest
        self.script = {}
        self.requests = []
        self.responses = []
        self.progress = []
        self.clock = Clock()
        self.auth = self.start(patch.object(release_sig, 'verify', side_effect=self.authenticate))
        self.bundle = self.start(patch.object(update_download, 'verify_bundle', wraps=release.verify_bundle))
        self.start(patch.object(release.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', 'TeamIdentifier=ABCDEFGHIJ\n')))
        self.start(patch.object(update_download.platform, 'machine', return_value='arm64'))
        self.urlopen = self.start(patch.object(update_download.urllib.request, 'urlopen', side_effect=self.open))
        self.start(patch.object(update_download.time, 'monotonic', side_effect=self.clock.monotonic))
        self.start(patch.object(update_download.time, 'sleep', side_effect=self.clock.sleep))

    def start(self, patcher):
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def authenticate(self, manifest, signature):
        return manifest == self.trusted_manifest and signature == b'fixture-signature'

    def trust(self, names=None, manifest=None):
        self.manifest = manifest if manifest is not None else ''.join(
            hashlib.sha256(self.payload).hexdigest() + '  ' + name + '\n'
            for name in (names if names is not None else [UNIVERSAL])).encode()
        self.trusted_manifest = self.manifest

    def open(self, request, timeout):
        self.requests.append(request)
        self.assertTrue(request.full_url.startswith(BASE), request.full_url)
        self.assertGreater(timeout, 0)
        self.assertLessEqual(timeout, 30)
        self.assertIsNone(request.get_header('Authorization'))
        self.assertIsNone(request.get_header('Range'))
        name = request.full_url.removeprefix(BASE)
        script = self.script.get(name)
        if script:
            result = script.pop(0)
        elif name == 'SHA256SUMS':
            result = self.manifest
        elif name == 'SHA256SUMS.sig':
            result = self.signature
        elif name in (ARM, INTEL, UNIVERSAL):
            result = self.payload
        else:
            raise AssertionError('非预期的资源请求')
        if isinstance(result, Exception):
            raise result
        response = result if isinstance(result, Response) else Response(result)
        self.responses.append(response)
        return response

    def run_download(self, **kwargs):
        return update_download.download(VERSION, '2.0.7', self.staging,
                                        progress=kwargs.pop('progress', self.progress.append), **kwargs)

    def calls(self, name):
        return sum(request.full_url == BASE + name for request in self.requests)

    def failed(self, code=None):
        with self.assertRaises(update_download.DownloadError) as caught:
            self.run_download()
        error = caught.exception
        if code:
            self.assertEqual(error.code, code)
        self.assertNotIn(100, self.progress)
        self.assertFalse(self.staging.exists() and any(self.staging.glob('signed-*')))
        self.assertTrue(all(response.closed for response in self.responses))
        return error

    def test_complete_download_without_api_preserves_return_contract(self):
        # 若错误地访问 API，此替身返回用户复现的 403，而非伪造可用的元数据。
        direct = self.open
        def api_blocked(request, timeout):
            if request.full_url.startswith('https://api.github.com/'):
                raise http_error(403, {'X-RateLimit-Remaining': '0'})
            return direct(request, timeout)
        self.urlopen.side_effect = api_blocked
        result = self.run_download(team_id='ABCDEFGHIJ')
        self.assertEqual(set(result), {'staging_app', 'version', 'archive', 'manifest', 'signature',
                                       'dmg_path', 'size', 'content_length'})
        self.assertEqual(result['version'], VERSION)
        self.assertEqual(result['dmg_path'], '')
        self.assertEqual(result['size'], len(self.payload))
        self.assertEqual(result['content_length'], len(self.payload))
        self.assertEqual(Path(result['archive']).read_bytes(), self.payload)
        self.assertTrue((Path(result['staging_app']) / 'Contents/MacOS/mdPreview').is_file())
        self.assertEqual(self.progress[-1], 100)
        self.assertEqual(self.progress, sorted(set(self.progress)))
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(self.clock.delays, [])
        self.bundle.assert_called_once_with(Path(result['staging_app']), 'ABCDEFGHIJ', VERSION)
        self.assertGreaterEqual(self.auth.call_count, 2)

    def test_exact_architecture_precedes_universal(self):
        self.trust([UNIVERSAL, ARM, INTEL])
        result = self.run_download()
        self.assertEqual(Path(result['archive']).name, ARM)
        self.assertEqual(self.calls(UNIVERSAL), 0)

    def test_intel_selection(self):
        self.trust([ARM, UNIVERSAL, INTEL])
        with patch.object(update_download.platform, 'machine', return_value='x86_64'):
            result = self.run_download()
        self.assertEqual(Path(result['archive']).name, INTEL)

    def test_universal_used_only_when_exact_name_absent(self):
        self.trust([f'mdPreview-{VERSION}-arm64.zip.old', UNIVERSAL])
        self.assertEqual(Path(self.run_download()['archive']).name, UNIVERSAL)

    def test_missing_exact_version_and_lookalikes_rejected(self):
        for names in ([INTEL], ['mdPreview-2.0.9-arm64.zip'], [ARM + '.old'], [ARM.upper()], []):
            with self.subTest(names=names):
                self.trust(names)
                self.failed('compatible-zip-not-found')
        self.assertEqual(self.calls(ARM) + self.calls(UNIVERSAL), 0)

    def test_no_universal_fallback_for_invalid_signature(self):
        self.signature = b'other-signature'
        error = self.failed('release-signature-invalid-or-unconfigured')
        self.assertEqual(error.stage, 'manifest_verify')
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.clock.delays, [])

    def test_tampered_manifest_rejected(self):
        self.manifest += b'extra'
        self.failed('release-signature-invalid-or-unconfigured')

    def test_strict_manifest_names_duplicates_encoding_and_digest(self):
        digest = hashlib.sha256(self.payload).hexdigest().encode()
        invalid = [
            digest + b'  ../' + ARM.encode() + b'\n',
            digest + b'  /' + ARM.encode() + b'\n',
            digest + b'  sub\\' + ARM.encode() + b'\n',
            digest + b'  ' + ARM.encode() + b'\x00\n',
            (digest + b'  ' + ARM.encode() + b'\n') * 2,
            digest.upper() + b'  ' + ARM.encode() + b'\n',
            digest + b'  \xff.zip\n',
        ]
        for manifest in invalid:
            with self.subTest(manifest=manifest):
                self.trust(manifest=manifest)
                error = self.failed()
                self.assertEqual(error.stage, 'manifest_verify')
        self.assertEqual(self.calls(ARM), 0)

    def test_preflight_never_uses_network_or_disk(self):
        for version in ('../../2.0.8', '2.0.8?x=1', '2.0.8/extra', '２.０.８', '2.0.8\n', '2.' + '0' * 40 + '.8', None):
            with self.subTest(version=version), self.assertRaises(update_download.DownloadError):
                update_download.download(version, '2.0.7', self.staging)
        with patch.object(release_sig, 'RELEASE_PUBKEY_B64', ''):
            self.failed('release-signing-key-not-configured')
        with patch.object(update_download.platform, 'machine', return_value='ppc64'):
            self.failed('unsupported-architecture')
        with self.assertRaisesRegex(update_download.DownloadError, 'downgrade'):
            update_download.download('2.0.6', '2.0.7', self.staging)
        self.urlopen.assert_not_called()
        self.assertFalse(self.staging.exists())

    def test_same_version_allowed(self):
        result = update_download.download(VERSION, VERSION, self.staging)
        self.assertEqual(result['version'], VERSION)

    def test_transient_manifest_and_signature_retried(self):
        self.script['SHA256SUMS'] = [TimeoutError(), http_error(503)]
        self.script['SHA256SUMS.sig'] = [ConnectionResetError()]
        self.run_download()
        self.assertEqual(self.calls('SHA256SUMS'), 3)
        self.assertEqual(self.calls('SHA256SUMS.sig'), 2)
        self.assertEqual(self.clock.delays, [1, 2, 1])

    def test_manifest_clean_truncation_retried(self):
        self.script['SHA256SUMS'] = [Response(b'abc', headers={'Content-Length': str(len(self.manifest))})]
        self.run_download()
        self.assertEqual(self.calls('SHA256SUMS'), 2)

    def test_partial_archive_restarted_not_appended(self):
        partial = Response(headers={'Content-Length': str(len(self.payload))},
                           chunks=[self.payload[:50], ConnectionResetError()])
        self.script[UNIVERSAL] = [partial]
        result = self.run_download()
        self.assertEqual(self.calls(UNIVERSAL), 2)
        self.assertEqual(Path(result['archive']).read_bytes(), self.payload)
        self.assertEqual(self.progress, sorted(set(self.progress)))

    def test_timeout_incomplete_read_remote_disconnect_and_tls_eof_retry(self):
        for error in (TimeoutError(), http.client.IncompleteRead(b'partial'),
                      http.client.RemoteDisconnected(), ssl.SSLEOFError()):
            with self.subTest(error=type(error).__name__):
                self.script[UNIVERSAL] = [Response(chunks=[error])]
                self.run_download()
        self.assertEqual(self.calls(UNIVERSAL), 8)

    def test_clean_eof_with_length_retries(self):
        self.script[UNIVERSAL] = [Response(self.payload[:40], headers={'Content-Length': str(len(self.payload))})]
        result = self.run_download()
        self.assertEqual(result['size'], len(self.payload))
        self.assertEqual(self.calls(UNIVERSAL), 2)

    def test_clean_eof_without_length_retries_digest_then_succeeds(self):
        self.script[UNIVERSAL] = [Response(self.payload[:40], headers={}), Response(self.payload, headers={})]
        result = self.run_download()
        self.assertIsNone(result['content_length'])
        self.assertEqual(result['size'], len(self.payload))
        self.assertEqual(self.calls(UNIVERSAL), 2)

    def test_chunked_or_missing_length_download_is_fully_verified(self):
        self.script[UNIVERSAL] = [Response(self.payload, headers={'Transfer-Encoding': 'chunked'})]
        result = self.run_download()
        self.assertIsNone(result['content_length'])
        self.assertEqual(result['size'], len(self.payload))
        self.assertEqual(self.progress[-1], 100)

    def test_tampered_archive_never_reaches_extract_or_bundle(self):
        self.payload += b'tampered'
        with patch.object(update_download, 'extract_verified') as extract:
            error = self.failed('signed-digest-mismatch')
        self.assertEqual(error.stage, 'digest')
        self.assertEqual(error.attempts, 4)
        self.assertEqual(self.calls(UNIVERSAL), 4)
        self.assertEqual(self.clock.delays, [1, 2, 4])
        extract.assert_not_called()
        self.bundle.assert_not_called()

    def test_retries_exhausted_keep_http_stage_code(self):
        self.script[UNIVERSAL] = [http_error(503) for _ in range(4)]
        error = self.failed('http-transient')
        info = update_download.error_info(error)
        self.assertEqual(info['http'], 503)
        self.assertEqual(info['stage'], 'archive')
        self.assertEqual(info['attempts'], 4)
        self.assertTrue(info['retryable'])
        self.assertEqual(self.clock.delays, [1, 2, 4])

    def test_rate_limit_retry_after_and_http_error_closed(self):
        error = http_error(429, {'Retry-After': '3'})
        body = error.fp
        self.script['SHA256SUMS'] = [error]
        self.run_download()
        self.assertEqual(self.clock.delays, [3])
        self.assertTrue(body.closed)

    def test_403_rate_limit_is_distinct_and_retries(self):
        self.script['SHA256SUMS'] = [http_error(403, {'X-RateLimit-Remaining': '0'}) for _ in range(4)]
        error = self.failed('http-rate-limited')
        self.assertEqual(error.http, 403)
        # 精确类别在 category/error_info；classify 是兼容旧的四种分类（HTTP 归 network）。
        self.assertEqual(error.category, 'rate_limited')
        self.assertEqual(update_download.classify(error), 'network')
        self.assertEqual(error.attempts, 4)

    def test_permanent_http_errors_not_retried(self):
        for status, category in ((403, 'forbidden'), (404, 'not_found'), (401, 'http'), (410, 'http')):
            with self.subTest(status=status):
                self.script['SHA256SUMS'] = [http_error(status)]
                error = self.failed()
                self.assertEqual(error.http, status)
                self.assertEqual(error.category, category)
                self.assertEqual(error.attempts, 1)
        self.assertEqual(self.clock.delays, [])

    def test_all_server_errors_and_408_retry(self):
        self.script['SHA256SUMS'] = [http_error(408), http_error(500), http_error(599)]
        self.run_download()
        self.assertEqual(self.clock.delays, [1, 2, 4])

    def test_huge_or_date_retry_after_does_not_sleep(self):
        for retry_after in ('99999999', 'Wed, 11 Nov 2099 12:00:00 GMT', 'untrusted'):
            with self.subTest(retry_after=retry_after):
                self.progress.clear()
                self.clock.delays.clear()
                self.script['SHA256SUMS'] = [http_error(429, {'Retry-After': retry_after})]
                with patch.object(update_download.time, 'time', return_value=0):
                    error = self.failed('http-rate-limited')
                self.assertEqual(error.attempts, 1)
        self.assertEqual(self.clock.delays, [])

    def test_budget_shared_across_resources_and_backoff(self):
        with patch.object(update_download, '_NETWORK_BUDGET', 2):
            self.script['SHA256SUMS'] = [TimeoutError()]
            self.script['SHA256SUMS.sig'] = [http_error(503)]
            error = self.failed('http-transient')
        self.assertEqual(error.stage, 'signature')
        self.assertEqual(self.clock.delays, [1])
        self.assertEqual(self.calls(UNIVERSAL), 0)

    def test_stream_deadline_stops_drip_feed(self):
        def tick():
            self.clock.now += 0.6
        with patch.object(update_download, '_NETWORK_BUDGET', 1):
            self.script[UNIVERSAL] = [Response(headers={}, chunks=[b'x'] * 20, tick=tick)]
            error = self.failed('retry-budget-exhausted')
        self.assertEqual(error.stage, 'archive')
        self.assertEqual(self.calls(UNIVERSAL), 1)
        self.assertEqual(self.clock.delays, [])

    def test_no_network_budget_left_after_connect(self):
        direct = self.open
        def slow_connect(request, timeout):
            self.clock.now += 2
            return direct(request, timeout)
        self.urlopen.side_effect = slow_connect
        with patch.object(update_download, '_NETWORK_BUDGET', 1):
            self.failed('retry-budget-exhausted')
        self.assertEqual(len(self.requests), 1)

    def test_tls_certificate_failure_never_retried(self):
        self.script['SHA256SUMS'] = [urllib.error.URLError(ssl.SSLCertVerificationError('PRIVATE'))]
        error = self.failed('tls-verification-failed')
        self.assertEqual(error.category, 'verify')
        self.assertEqual(self.clock.delays, [])

    def test_manifest_and_signature_limit_with_and_without_length(self):
        for name, limit in (('SHA256SUMS', 1048576), ('SHA256SUMS.sig', 80)):
            for headers in ({}, {'Content-Length': str(limit + 1)}):
                with self.subTest(name=name, headers=headers):
                    self.script[name] = [Response(b'x' * (limit + 1), headers=headers)]
                    error = self.failed('download-size-limit')
                    self.assertFalse(error.retryable)
        self.assertEqual(self.clock.delays, [])

    def test_archive_limit_with_and_without_length(self):
        with patch.object(update_download, '_MAX_ARCHIVE', 64):
            for headers in ({}, {'Content-Length': str(len(self.payload))}):
                with self.subTest(headers=headers):
                    self.script[UNIVERSAL] = [Response(self.payload, headers=headers)]
                    self.failed('download-size-limit')
        self.assertEqual(self.clock.delays, [])

    def test_invalid_length_and_unsolicited_partial_response(self):
        for length in ('-1', 'abc', '1, 2', '9' * 5000):
            with self.subTest(length=length[:20]):
                self.script[UNIVERSAL] = [Response(self.payload, headers={'Content-Length': length})]
                self.failed('invalid-content-length')
        self.script[UNIVERSAL] = [Response(self.payload, status=206)]
        self.assertEqual(self.failed('unexpected-http-status').http, 206)
        self.script[UNIVERSAL] = [Response(self.payload, headers={'Content-Encoding': 'gzip'})]
        self.failed('unexpected-content-encoding')
        self.assertEqual(self.clock.delays, [])

    def test_response_exceeding_declared_length_is_retried(self):
        self.script[UNIVERSAL] = [Response(self.payload, headers={'Content-Length': '1'})]
        self.run_download()
        self.assertEqual(self.calls(UNIVERSAL), 2)

    def test_empty_archive_rejected(self):
        self.payload = b''
        self.failed('signed-digest-mismatch')
        self.bundle.assert_not_called()

    def test_zip_traversal_rejected_after_digest_verification(self):
        self.payload = archive_bytes({'mdPreview.app/../../escape': b'bad'})
        self.trust()
        error = self.failed('unsafe-archive-path')
        self.assertEqual(error.stage, 'extract')
        self.assertFalse((self.root / 'escape').exists())
        self.assertEqual(self.calls(UNIVERSAL), 1)
        self.bundle.assert_not_called()

    def test_signed_non_zip_is_rejected(self):
        self.payload = b'not-a-zip'
        self.trust()
        error = self.failed('extract-verification-failed')
        self.assertEqual(error.category, 'verify')

    def test_bundle_version_identity_and_code_signature_fail_closed(self):
        for payload in (archive_bytes(version='2.0.7'), archive_bytes(identifier='other.app')):
            with self.subTest(digest=hashlib.sha256(payload).hexdigest()):
                self.payload = payload
                self.trust()
                error = self.failed('verification-failed')
                self.assertEqual(error.stage, 'bundle')
        self.payload = archive_bytes()
        self.trust()
        with patch.object(release.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'codesign', stderr=b'PRIVATE')):
            error = self.failed('bundle-verification-failed')
        self.assertEqual(error.category, 'verify')

    def test_progress_never_100_before_bundle_verification(self):
        def verify(app, team, version):
            self.assertNotIn(100, self.progress)
            return release.verify_bundle(app, team, version)
        self.bundle.side_effect = verify
        self.run_download()
        self.assertEqual(self.progress[-1], 100)
        self.assertLess(max(self.progress[:-1]), 100)

    def test_failure_only_cleans_own_job_including_partial_extraction(self):
        self.staging.mkdir()
        other = self.staging / 'signed-another-job'
        other.mkdir()
        (other / 'keep').write_text('keep')
        def fail_extract(archive, manifest, signature, destination):
            destination.mkdir()
            (destination / 'partial').write_bytes(b'partial')
            (destination / 'link').symlink_to(other, target_is_directory=True)
            raise ValueError('unsafe-archive-path')
        with patch.object(update_download, 'extract_verified', side_effect=fail_extract):
            with self.assertRaises(update_download.DownloadError):
                self.run_download()
        self.assertEqual(list(self.staging.iterdir()), [other])
        self.assertEqual((other / 'keep').read_text(), 'keep')
        self.assertNotIn(100, self.progress)

    def test_staging_symlink_and_parent_traversal_rejected(self):
        target = self.root / 'target'
        target.mkdir()
        self.staging.symlink_to(target, target_is_directory=True)
        self.failed('unsafe-staging-path')
        self.assertEqual(list(target.iterdir()), [])
        self.staging = self.root / 'foo' / '..' / 'staging'
        self.failed('unsafe-staging-path')

    def test_resolved_job_paths_survive_caller_path_alias(self):
        alias = self.root / 'alias'
        target = self.root / 'target'
        target.mkdir()
        alias.symlink_to(target, target_is_directory=True)
        self.staging = alias / 'staging'
        result = self.run_download()
        self.assertEqual(Path(result['archive']), Path(result['archive']).resolve())
        self.assertTrue(Path(result['archive']).is_relative_to(target.resolve()))

    def test_permission_error_is_not_retried_or_exposed(self):
        with patch.object(update_download.tempfile, 'mkdtemp', side_effect=PermissionError('/Users/PRIVATE')):
            error = self.failed('local-io-error')
        self.assertEqual(error.stage, 'staging')
        self.assertEqual(self.clock.delays, [])
        self.assertNotIn('PRIVATE', json.dumps(update_download.error_info(error)))

    def test_cleanup_failure_preserves_original_and_reports_flag(self):
        self.bundle.side_effect = ValueError('PRIVATE bundle failure')
        with patch.object(update_download.shutil, 'rmtree', side_effect=PermissionError('PRIVATE')):
            with self.assertRaises(update_download.DownloadError) as caught:
                self.run_download()
        error = caught.exception
        self.assertEqual(error.stage, 'bundle')
        self.assertEqual(error.code, 'verification-failed')
        self.assertTrue(update_download.error_info(error)['cleanup_failed'])
        self.assertNotIn('PRIVATE', json.dumps(update_download.error_info(error)))

    def test_callback_failure_cleans_job(self):
        def callback(value):
            if value >= 96:
                raise RuntimeError('PRIVATE callback')
        with self.assertRaises(update_download.DownloadError):
            self.run_download(progress=callback)
        self.assertEqual(list(self.staging.iterdir()), [])


class ErrorContract(unittest.TestCase):
    def test_classify_old_categories_and_new_http_categories(self):
        # classify 保持旧的四种分类（HTTP 类别一律归 network）；
        # 精确 HTTP 类别由 error_info['error'] 提供。
        cases = [
            (urllib.error.URLError('PRIVATE'), 'network'),
            (TimeoutError(), 'network'),
            (ConnectionResetError(), 'network'),
            (http.client.IncompleteRead(b'x'), 'incomplete'),
            (ValueError('download-size-limit'), 'incomplete'),
            (ValueError('archive-too-large'), 'incomplete'),
            (ValueError('signed-digest-mismatch'), 'verify'),
            (RuntimeError('PRIVATE'), 'unknown'),
            (PermissionError('PRIVATE'), 'unknown'),
            (http_error(403), 'network'),
            (http_error(403, {'X-RateLimit-Remaining': '0'}), 'network'),
            (http_error(429), 'network'),
            (http_error(404), 'network'),
            (http_error(503), 'network'),
            (http_error(401), 'network'),
        ]
        precise = {(403, None): 'forbidden', (403, '0'): 'rate_limited', (429, None): 'rate_limited',
                   (404, None): 'not_found', (401, None): 'http'}
        for error, category in cases:
            with self.subTest(error=type(error).__name__, category=category):
                self.assertEqual(update_download.classify(error), category)
                info = update_download.error_info(error)
                self.assertEqual(info['stage'], 'unknown')
                self.assertTrue(info['detail'])
                self.assertNotIn('PRIVATE', json.dumps(info))
                if isinstance(error, urllib.error.HTTPError):
                    key = (error.code, error.headers.get('X-RateLimit-Remaining'))
                    if key in precise:
                        self.assertEqual(info['error'], precise[key])

    def test_exception_is_value_error_with_json_safe_contract(self):
        error = update_download.DownloadError('signature', 'http-rate-limited', 'rate_limited', 429, True, 4)
        self.assertIsInstance(error, ValueError)
        self.assertEqual(str(error), 'http-rate-limited')
        self.assertEqual(update_download.error_info(error), {
            'error': 'rate_limited', 'stage': 'signature', 'code': 'http-rate-limited',
            'http': 429, 'detail': 'GitHub 请求受到限流，请稍后重试。', 'retryable': True,
            'attempts': 4, 'cleanup_failed': False,
        })


@unittest.skipUnless(importlib.util.find_spec('Security') and importlib.util.find_spec('Foundation'),
                     '需要项目原生 Python 环境的 Security/Foundation')
class NativePublicSignature(unittest.TestCase):
    # 2026-11-11 从官方 v2.0.8 下载的公开数据；仅作验签回归，不联网、不读取私钥。
    manifest = (
        b'24b175450493054dbbc316306c00ccc3dd4dfef66b91e7291f3e9f9595122181  mdPreview-2.0.8-arm64.dmg\n'
        b'5904f7bcc1da66d8c661f1cb262cd80a7b47d26c9a324c1cdb29b05401005001  mdPreview-2.0.8-arm64.zip\n'
        b'3f181381778324789120bc2caf1606bbc0d5770ae39ffce9be4a856460b6ef46  mdPreview-2.0.8-x86_64.dmg\n'
        b'85b6560126f17ea50441675db97ae087961ec6d623ad16710bd7e3ec647fe47c  mdPreview-2.0.8-x86_64.zip\n'
    )
    signature = base64.b64decode('MEUCIQDwPTehLESygUpyci8aV3SKIo4qJ/PJGfmqxXGiaqZaAAIgBk/7dP3jCVNEGGKG1f42HeW3hyZjb95kvtBd27xO5sI=')

    def test_builtin_public_key_verifies_official_manifest(self):
        self.assertEqual(release_sig.signed_digest(self.manifest, self.signature, ARM),
                         '5904f7bcc1da66d8c661f1cb262cd80a7b47d26c9a324c1cdb29b05401005001')
        self.assertEqual(release_sig.signed_digest(self.manifest, self.signature, INTEL),
                         '85b6560126f17ea50441675db97ae087961ec6d623ad16710bd7e3ec647fe47c')

    def test_changed_manifest_or_signature_rejected(self):
        for manifest, signature in ((self.manifest + b'x', self.signature),
                                    (self.manifest, self.signature[:-1] + bytes([self.signature[-1] ^ 1]))):
            with self.subTest(signature=signature), self.assertRaisesRegex(ValueError, 'signature'):
                release_sig.signed_digest(manifest, signature, ARM)

    def test_official_signature_cannot_authorize_other_filename(self):
        with self.assertRaisesRegex(ValueError, 'asset-not-signed'):
            release_sig.signed_digest(self.manifest, self.signature, UNIVERSAL)


if __name__ == '__main__':
    unittest.main(verbosity=2)
