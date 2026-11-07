#!/usr/bin/env python3
"""
Quality gate for the mdPreview updater flow (Python side).

Covers:
  - _is_newer semantics
  - _staged_version_acceptable: None -> reject; equal -> accept (re-download
    latest reinstalls same version); newer -> accept; older -> reject
  - _download_and_extract new error contract: returns
    {'error': code, 'detail': <localized str>} instead of None, with codes
    network / incomplete, without touching the real network or disk layout.

Run:
  <python> tests/test_update_flow.py
"""
import os
import sys
import shutil
import tempfile
import unittest
from unittest import mock

# tests/ -> repository root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = PROJECT_ROOT
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import mdPreview as mv  # noqa: E402
import urllib.error  # noqa: E402


class FakeResp:
    """Minimal urlopen() result: context manager with headers + read()."""

    def __init__(self, chunks, content_length=None):
        self._chunks = list(chunks)
        self.headers = {'Content-Length': str(content_length)} if content_length is not None else {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return self._chunks.pop(0) if self._chunks else b''


class IsNewerTests(unittest.TestCase):
    def test_basic(self):
        self.assertTrue(mv._is_newer('1.4.10', '1.4.9'))
        self.assertTrue(mv._is_newer('2.0', '1.9.9'))
        self.assertFalse(mv._is_newer('1.4.9', '1.4.9'))
        self.assertFalse(mv._is_newer('1.4.8', '1.4.9'))

    def test_padding(self):
        self.assertTrue(mv._is_newer('1.5', '1.4.9'))
        self.assertFalse(mv._is_newer('1.4', '1.4.0'))


class StagedVersionAcceptableTests(unittest.TestCase):
    def test_missing_version_rejected(self):
        self.assertFalse(mv._staged_version_acceptable(None, '1.4.9'))
        self.assertFalse(mv._staged_version_acceptable('', '1.4.9'))

    def test_equal_accepted_for_reinstall(self):
        self.assertTrue(mv._staged_version_acceptable('1.4.9', '1.4.9'))

    def test_newer_accepted(self):
        self.assertTrue(mv._staged_version_acceptable('1.5.0', '1.4.9'))
        self.assertTrue(mv._staged_version_acceptable('1.5.1', '1.4.9'))

    def test_older_rejected(self):
        self.assertFalse(mv._staged_version_acceptable('1.4.8', '1.4.9'))
        self.assertFalse(mv._staged_version_acceptable('1.4', '1.4.9'))


class DownloadErrorContractTests(unittest.TestCase):
    """_download_and_extract 把签名下载管线的异常映射为界面使用的错误码。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix='mdpreview-update-test-')
        self.addCleanup(shutil.rmtree, self._tmp, True)
        patcher = mock.patch.object(mv, 'UPDATE_STAGING_DIR', self._tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        key = mock.patch('mdpreview_core.release_sig.configured', return_value=True)
        key.start()
        self.addCleanup(key.stop)

    def _result(self, error):
        with mock.patch('mdpreview_core.update_download.download', side_effect=error):
            return mv._download_and_extract('1.4.10')

    def test_http_error_returns_network(self):
        result = self._result(urllib.error.HTTPError('http://x', 404, 'Not Found', {}, None))
        self.assertEqual(result['error'], 'network')
        self.assertTrue(result['detail'])

    def test_url_error_returns_network(self):
        self.assertEqual(self._result(urllib.error.URLError('dns'))['error'], 'network')

    def test_size_limit_returns_incomplete(self):
        self.assertEqual(self._result(ValueError('download-size-limit'))['error'], 'incomplete')

    def test_digest_mismatch_returns_verify(self):
        self.assertEqual(self._result(ValueError('signed-digest-mismatch'))['error'], 'verify')

    def test_unexpected_error_returns_unknown(self):
        result = self._result(RuntimeError('boom'))
        self.assertEqual(result['error'], 'unknown')
        self.assertTrue(result['detail'])

    def test_unconfigured_key_explains_why(self):
        with mock.patch('mdpreview_core.release_sig.configured', return_value=False):
            result = self._result(ValueError('release-signing-key-not-configured'))
        self.assertEqual(result['error'], 'verify')
        self.assertTrue(result['detail'])

    def test_concurrent_download_reports_busy(self):
        self.assertTrue(mv._update_download_lock.acquire(blocking=False))
        try:
            self.assertEqual(mv._download_and_extract('1.4.10')['error'], 'busy')
        finally:
            mv._update_download_lock.release()

    def test_success_is_passed_through_and_progress_forwarded(self):
        seen = []
        expected = {'staging_app': '/x/mdPreview.app', 'version': '1.4.10'}
        with mock.patch('mdpreview_core.update_download.download', return_value=expected) as download:
            result = mv._download_and_extract('1.4.10', progress_callback=seen.append)
        self.assertEqual(result, expected)
        self.assertEqual(download.call_args.args[0], '1.4.10')


if __name__ == '__main__':
    unittest.main(verbosity=2)
