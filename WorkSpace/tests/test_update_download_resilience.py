"""补充下载恢复契约：全部离线、仅临时目录，不导入 GUI 或真实用户配置。

复用既有恢复套件；覆盖其中已被明确修正的 classify 和 HTTP 日期语义。
原生用例使用临时 P-256 密钥与真实 Security 验签，只替换系统 bundle 命令。
"""
import base64
from concurrent.futures import ThreadPoolExecutor
from email.utils import formatdate
import hashlib
import importlib.util
import io
import json
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import test_update_download_recovery as recovery
from mdpreview_core import release, release_sig, update_download


class DownloadResilience(recovery.DownloadRecovery):
    def test_403_rate_limit_is_distinct_and_retries(self):
        self.script['SHA256SUMS'] = [recovery.http_error(403, {'X-RateLimit-Remaining': '0'}) for _ in range(4)]
        error = self.failed('http-rate-limited')
        self.assertEqual(error.http, 403)
        self.assertEqual(update_download.classify(error), 'network')
        self.assertEqual(update_download.error_info(error)['error'], 'rate_limited')
        self.assertEqual(error.attempts, 4)

    def test_huge_or_date_retry_after_does_not_sleep(self):
        # 超长等待或无效日期不占住调用方下载锁；合法短日期另测恢复。
        now = 1_700_000_000
        for value in ('99999999', formatdate(now + 3600, usegmt=True), 'untrusted', 'x' * 1024):
            with self.subTest(value=value[:40]), patch.object(update_download.time, 'time', return_value=now):
                self.script['SHA256SUMS'] = [recovery.http_error(429, {'Retry-After': value})]
                self.assertEqual(self.failed('http-rate-limited').attempts, 1)
        self.assertEqual(self.clock.delays, [])

    def test_http_date_retry_after_recovers_and_closes_response(self):
        now = 1_700_000_000
        error = recovery.http_error(503, {'Retry-After': formatdate(now + 5, usegmt=True)})
        body = error.fp
        self.script['SHA256SUMS'] = [error]
        with patch.object(update_download.time, 'time', return_value=now):
            self.run_download()
        self.assertEqual(self.clock.delays, [5])
        self.assertEqual(self.calls('SHA256SUMS'), 2)
        self.assertTrue(body.closed)

    def test_past_http_date_uses_minimum_backoff(self):
        now = 1_700_000_000
        self.script['SHA256SUMS.sig'] = [recovery.http_error(429, {'Retry-After': formatdate(now - 60, usegmt=True)})]
        with patch.object(update_download.time, 'time', return_value=now):
            self.run_download()
        self.assertEqual(self.clock.delays, [1])

    def test_retry_after_numeric_whitespace_is_accepted(self):
        self.script['SHA256SUMS'] = [recovery.http_error(429, {'Retry-After': ' 3 '})]
        self.run_download()
        self.assertEqual(self.clock.delays, [3])

    def test_budget_limits_http_date_wait(self):
        now = 1_700_000_000
        self.script['SHA256SUMS'] = [recovery.http_error(429, {'Retry-After': formatdate(now + 5, usegmt=True)})]
        with patch.object(update_download.time, 'time', return_value=now), patch.object(update_download, '_NETWORK_BUDGET', 4):
            self.failed('http-rate-limited')
        self.assertEqual(self.clock.delays, [])

    def test_progress_timeout_is_not_a_transport_retry(self):
        for error in (TimeoutError('PRIVATE'), ConnectionResetError('PRIVATE'), ValueError('PRIVATE')):
            with self.subTest(error=type(error).__name__):
                self.requests.clear()
                def callback(percent):
                    if percent > 0:
                        raise error
                with self.assertRaises(update_download.DownloadError) as caught:
                    self.run_download(progress=callback)
                failure = caught.exception
                self.assertEqual(failure.stage, 'progress')
                self.assertEqual(failure.code, 'progress-callback-failed')
                self.assertFalse(failure.retryable)
                self.assertEqual(failure.category, 'unknown')
                self.assertEqual(self.calls(recovery.UNIVERSAL), 1)
                self.assertEqual(list(self.staging.iterdir()), [])
                self.assertNotIn('PRIVATE', json.dumps(update_download.error_info(failure)))
        self.assertEqual(self.clock.delays, [])

    def test_failed_exact_asset_does_not_switch_to_an_unrelated_or_unsigned_asset(self):
        self.trust([recovery.ARM, recovery.UNIVERSAL])
        self.script[recovery.ARM] = [recovery.http_error(404)]
        error = self.failed('http-not-found')
        self.assertEqual(error.stage, 'archive')
        self.assertEqual(self.calls(recovery.UNIVERSAL), 0)
        self.assertEqual(self.clock.delays, [])

    def test_existing_job_survives_retry_exhaustion_and_lock_can_be_reused(self):
        self.staging.mkdir()
        other = self.staging / 'signed-existing'
        other.mkdir()
        marker = other / 'keep'
        marker.write_bytes(b'untouched')
        lock = threading.Lock()
        self.script[recovery.UNIVERSAL] = [TimeoutError() for _ in range(4)]
        with self.assertRaises(update_download.DownloadError), lock:
            self.run_download()
        self.assertTrue(lock.acquire(blocking=False))
        try:
            self.assertEqual(list(self.staging.iterdir()), [other])
            result = self.run_download()
            self.assertTrue(Path(result['staging_app']).is_dir())
            self.assertEqual(marker.read_bytes(), b'untouched')
        finally:
            lock.release()

    def test_concurrent_failure_only_removes_its_own_job(self):
        barrier = threading.Barrier(2)
        def verify(app, team, version):
            barrier.wait(timeout=10)
            if team == 'FAIL':
                raise ValueError('PRIVATE')
            return release.verify_bundle(app, None, version)
        self.bundle.side_effect = verify
        failed_progress, good_progress = [], []
        with ThreadPoolExecutor(max_workers=2) as pool:
            bad = pool.submit(self.run_download, team_id='FAIL', progress=failed_progress.append)
            good = pool.submit(self.run_download, progress=good_progress.append)
            with self.assertRaises(update_download.DownloadError):
                bad.result(timeout=15)
            result = good.result(timeout=15)
        own = Path(result['archive']).parent
        self.assertEqual(list(self.staging.resolve().iterdir()), [own])
        self.assertEqual(Path(result['archive']).read_bytes(), self.payload)
        self.assertEqual(good_progress[-1], 100)
        self.assertNotIn(100, failed_progress)
        self.assertEqual(good_progress, sorted(set(good_progress)))
        self.assertEqual(failed_progress, sorted(set(failed_progress)))

    def test_progress_failure_after_verification_cleans_own_job(self):
        def callback(percent):
            if percent == 100:
                raise RuntimeError('PRIVATE')
        with self.assertRaises(update_download.DownloadError) as caught:
            self.run_download(progress=callback)
        self.assertEqual(caught.exception.stage, 'progress')
        self.assertEqual(list(self.staging.iterdir()), [])
        self.bundle.assert_called_once()

    def test_zip_symlink_cannot_escape_staging(self):
        import stat
        import zipfile
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            entry = zipfile.ZipInfo('mdPreview.app/Contents/link')
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(entry, '../../../escape')
        self.payload = buffer.getvalue()
        self.trust()
        self.assertEqual(self.failed('escaping-symlink').stage, 'extract')
        self.bundle.assert_not_called()

    def test_team_id_and_system_signature_gates_remain_enforced(self):
        native_command = self.start(patch.object(release.subprocess, 'run'))
        native_command.return_value = subprocess.CompletedProcess([], 0, '', 'TeamIdentifier=ABCDEFGHIJ\n')
        result = self.run_download(team_id='ABCDEFGHIJ')
        commands = [call.args[0] for call in native_command.call_args_list]
        app = result['staging_app']
        self.assertIn(['/usr/bin/codesign', '--verify', '--deep', '--strict', app], commands)
        self.assertIn(['/usr/bin/codesign', '-dv', '--verbose=4', app], commands)
        self.assertIn(['/usr/sbin/spctl', '--assess', '--type', 'execute', app], commands)
        native_command.return_value = subprocess.CompletedProcess([], 0, '', 'TeamIdentifier=ZZZZZZZZZZ\n')
        with self.assertRaises(update_download.DownloadError) as caught:
            self.run_download(team_id='ABCDEFGHIJ')
        self.assertEqual(caught.exception.stage, 'bundle')
        self.assertTrue(Path(app).is_dir())


class CompatibleErrorContract(recovery.ErrorContract):
    def test_classify_old_categories_and_new_http_categories(self):
        for status, category in ((403, 'forbidden'), (404, 'not_found'), (429, 'rate_limited'), (500, 'network'), (401, 'http')):
            with self.subTest(status=status):
                raw = recovery.http_error(status)
                converted = update_download._error(raw, 'manifest')
                for error in (raw, converted):
                    self.assertEqual(update_download.classify(error), 'network')
                    info = update_download.error_info(error)
                    self.assertEqual(info['error'], category)
                    self.assertEqual(info['http'], status)
                    self.assertNotIn('PRIVATE', json.dumps(info))
                raw.close()
        for error, category in ((TimeoutError(), 'network'), (urllib.error.URLError('dns'), 'network'),
                                (ValueError('archive-too-large'), 'incomplete'),
                                (ValueError('signed-digest-mismatch'), 'verify'),
                                (PermissionError('PRIVATE'), 'unknown')):
            self.assertEqual(update_download.classify(error), category)
        self.assertEqual(update_download.classify(ssl.SSLCertVerificationError()), 'verify')


@unittest.skipUnless(importlib.util.find_spec('Security') and importlib.util.find_spec('Foundation'),
                     '需要原生 Python 环境的 Security/Foundation')
class NativeSignedDownload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix='mdpreview-ephemeral-signing-')
        cls.addClassCleanup(temporary.cleanup)
        cls.root = Path(temporary.name)
        cls.key = cls.root / 'key'
        subprocess.run(['openssl', 'ecparam', '-name', 'prime256v1', '-genkey', '-noout', '-out', str(cls.key)], check=True, capture_output=True)
        public = subprocess.check_output(['openssl', 'ec', '-in', str(cls.key), '-pubout', '-outform', 'DER'], stderr=subprocess.DEVNULL)[-65:]
        cls.public = base64.b64encode(public).decode()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='mdpreview-native-download-')
        self.addCleanup(temporary.cleanup)
        self.staging = Path(temporary.name) / 'staging'
        self.requests = []
        self.responses = []
        self.progress = []
        self.payload = recovery.archive_bytes()
        self.prepare()
        for patcher in (patch.object(release_sig, 'RELEASE_PUBKEY_B64', self.public),
                        patch.object(update_download.platform, 'machine', return_value='arm64'),
                        patch.object(update_download.urllib.request, 'urlopen', side_effect=self.open),
                        patch.object(update_download.time, 'sleep'),
                        patch.object(release.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', 'TeamIdentifier=ABCDEFGHIJ\n'))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def prepare(self, names=None):
        names = names or [recovery.ARM, recovery.UNIVERSAL]
        self.manifest = ''.join(hashlib.sha256(self.payload).hexdigest() + '  ' + name + '\n' for name in names).encode()
        signature = subprocess.run(['openssl', 'dgst', '-sha256', '-sign', str(self.key)], input=self.manifest, capture_output=True, check=True)
        self.signature = signature.stdout

    def open(self, request, timeout):
        self.requests.append(request.full_url)
        if request.full_url.startswith('https://api.github.com/'):
            raise recovery.http_error(403, {'X-RateLimit-Remaining': '0'})
        self.assertTrue(request.full_url.startswith(recovery.BASE))
        self.assertIsNone(request.get_header('Range'))
        self.assertIsNone(request.get_header('Authorization'))
        name = request.full_url.removeprefix(recovery.BASE)
        contents = {'SHA256SUMS': self.manifest, 'SHA256SUMS.sig': self.signature,
                    recovery.ARM: self.payload, recovery.UNIVERSAL: self.payload}
        response = recovery.Response(contents[name])
        self.responses.append(response)
        return response

    def download(self):
        return update_download.download(recovery.VERSION, '2.0.7', self.staging, 'ABCDEFGHIJ', self.progress.append)

    def test_full_native_signature_digest_extraction_and_bundle_identity_without_api(self):
        result = self.download()
        self.assertEqual(self.requests, [recovery.BASE + name for name in ('SHA256SUMS', 'SHA256SUMS.sig', recovery.ARM)])
        self.assertEqual(Path(result['archive']).read_bytes(), self.payload)
        self.assertEqual(Path(result['manifest']).read_bytes(), self.manifest)
        self.assertEqual(Path(result['signature']).read_bytes(), self.signature)
        self.assertTrue((Path(result['staging_app']) / 'Contents/MacOS/mdPreview').is_file())
        self.assertEqual(self.progress[-1], 100)
        self.assertTrue(all(response.closed for response in self.responses))

    def test_real_signature_rejects_changed_manifest_before_zip_request(self):
        self.manifest += b'x'
        with self.assertRaisesRegex(update_download.DownloadError, 'release-signature-invalid'):
            self.download()
        self.assertEqual(len(self.requests), 2)
        self.assertFalse(self.staging.exists())

    def test_real_signature_rejects_changed_signature_before_zip_request(self):
        self.signature = self.signature[:-1] + bytes([self.signature[-1] ^ 1])
        with self.assertRaisesRegex(update_download.DownloadError, 'release-signature-invalid'):
            self.download()
        self.assertEqual(len(self.requests), 2)
        self.assertFalse(self.staging.exists())

    def test_real_signed_digest_rejects_tampered_zip_after_bounded_retries(self):
        self.payload += b'corrupted'
        with self.assertRaises(update_download.DownloadError) as caught:
            self.download()
        self.assertEqual(caught.exception.stage, 'digest')
        self.assertEqual(caught.exception.attempts, 4)
        self.assertEqual(len(self.requests), 6)
        self.assertEqual(list(self.staging.iterdir()), [])
        self.assertNotIn(100, self.progress)


if __name__ == '__main__':
    unittest.main(verbosity=2)
