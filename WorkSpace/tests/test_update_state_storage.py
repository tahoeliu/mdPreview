"""真实状态/私有存储边界测试；每测 mkdtemp 保留现场，不注册文件清理。

只在系统调用和时钟边界注入故障；真实模块负责序列化、落盘及失败清理。
生产 private_write 自身会替换目标并 unlink 临时文件，不模拟或禁用该行为。
"""
import errno
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from mdpreview_core import update_state, update_storage


class RetainedFiles(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(
            prefix=f'state-storage-{self._testMethodName}-', dir=ROOT / 'WorkSpace/tests')).resolve()
        self.path = self.root / 'state.json'

    def raw_file(self, path, raw):
        path.write_bytes(raw)
        path.chmod(0o600)
        return path

    def assert_closed(self, descriptor):
        with self.assertRaises(OSError) as caught:
            os.fstat(descriptor)
        self.assertEqual(caught.exception.errno, errno.EBADF)


class PrivateStorageTests(RetainedFiles):
    def test_create_private_nested_directory_and_close_descriptor(self):
        directory = self.root / 'private' / 'nested'
        with update_storage.private_directory(directory, create=True) as descriptor:
            self.assertEqual(os.fstat(descriptor).st_ino, directory.stat().st_ino)
            self.assertEqual(os.fstat(descriptor).st_uid, os.getuid())
        self.assert_closed(descriptor)
        for path in (directory.parent, directory):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
        with update_storage.private_directory(directory) as descriptor:
            self.assertTrue(stat.S_ISDIR(os.fstat(descriptor).st_mode))
        self.assert_closed(descriptor)

    def test_directory_descriptor_closes_when_body_raises(self):
        with self.assertRaisesRegex(RuntimeError, 'body-failed'):
            with update_storage.private_directory(self.root) as descriptor:
                raise RuntimeError('body-failed')
        self.assert_closed(descriptor)

    def test_missing_directory_is_not_created_by_read(self):
        directory = self.root / 'absent'
        with self.assertRaises(FileNotFoundError):
            update_storage.private_read(directory / 'state.json')
        self.assertFalse(directory.exists())

    def test_directory_public_permissions_are_rejected_without_repair(self):
        for mode in (0o701, 0o710, 0o744, 0o777):
            with self.subTest(mode=oct(mode)):
                directory = self.root / oct(mode)
                directory.mkdir()
                directory.chmod(mode)
                for create in (False, True):
                    with self.assertRaisesRegex(ValueError, 'private-directory-required'):
                        with update_storage.private_directory(directory, create=create):
                            self.fail('公开目录不应被接受')
                self.assertEqual(stat.S_IMODE(directory.stat().st_mode), mode)
                self.assertEqual(list(directory.iterdir()), [])

    def test_directory_foreign_owner_is_rejected_and_descriptor_closed(self):
        close = os.close
        with patch.object(update_storage.os, 'getuid', return_value=os.getuid() + 1), \
                patch.object(update_storage.os, 'close', wraps=close) as closed:
            with self.assertRaisesRegex(ValueError, 'private-directory-required'):
                with update_storage.private_directory(self.root):
                    self.fail('非当前用户目录不应被接受')
        self.assert_closed(closed.call_args.args[0])

    def test_symlink_directory_and_ancestor_are_never_followed(self):
        target = self.root / 'target'
        nested = target / 'nested'
        nested.mkdir(mode=0o700, parents=True)
        target.chmod(0o700)
        link = self.root / 'link'
        link.symlink_to(target, target_is_directory=True)
        update_storage.private_write(nested / 'state.json', {'keep': True})
        before = (nested / 'state.json').read_bytes()
        for directory in (link, link / 'nested'):
            with self.subTest(directory=directory):
                for create in (False, True):
                    with self.assertRaises(OSError) as caught:
                        with update_storage.private_directory(directory, create=create):
                            self.fail('符号链接不应被跟随')
                    self.assertIn(caught.exception.errno, (errno.ELOOP, errno.ENOTDIR))
                with self.assertRaises(OSError):
                    update_storage.private_write(directory / 'state.json', {'changed': True})
                with self.assertRaises(OSError):
                    update_storage.private_read(directory / 'state.json')
        self.assertTrue(link.is_symlink())
        self.assertEqual((nested / 'state.json').read_bytes(), before)
        self.assertFalse((target / 'state.json').exists())

    def test_regular_file_cannot_be_used_as_directory(self):
        self.raw_file(self.path, b'keep')
        with self.assertRaises(NotADirectoryError):
            update_storage.private_write(self.path / 'child.json', {})
        self.assertEqual(self.path.read_bytes(), b'keep')

    def test_directory_permission_failure_propagates(self):
        real_open = os.open
        def denied(path, flags, *args, **kwargs):
            if path == self.root.name:
                raise PermissionError(errno.EACCES, 'directory-denied')
            return real_open(path, flags, *args, **kwargs)
        with patch.object(update_storage.os, 'open', side_effect=denied):
            with self.assertRaisesRegex(PermissionError, 'directory-denied'):
                update_storage.private_write(self.path, {})
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_json_roundtrip_is_private_utf8_and_compact(self):
        value = {'version': '2.0.8', 'detail': '测试', 'nested': [None, True, {'count': 2}]}
        update_storage.private_write(self.path, value)
        self.assertEqual(update_storage.private_read(self.path), value)
        self.assertEqual(self.path.read_bytes(), json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8'))
        info = self.path.stat()
        self.assertEqual(stat.S_IMODE(info.st_mode), 0o600)
        self.assertEqual(info.st_uid, os.getuid())
        self.assertEqual(info.st_nlink, 1)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_atomic_replace_preserves_open_old_inode_and_sync_order(self):
        old, new = {'revision': 1}, {'revision': 2, 'detail': '完整替换'}
        update_storage.private_write(self.path, old)
        old_inode = self.path.stat().st_ino
        real_replace, real_sync = os.replace, os.fsync
        events = []
        def sync(fd):
            events.append('directory-sync' if stat.S_ISDIR(os.fstat(fd).st_mode) else 'file-sync')
            return real_sync(fd)
        def replace(source, destination, **kwargs):
            self.assertEqual(update_storage.private_read(self.path), old)
            self.assertEqual(update_storage.private_read(self.root / source), new)
            self.assertEqual(stat.S_IMODE((self.root / source).stat().st_mode), 0o600)
            events.append('replace')
            return real_replace(source, destination, **kwargs)
        with self.path.open('rb') as original, \
                patch.object(update_storage.os, 'fsync', side_effect=sync), \
                patch.object(update_storage.os, 'replace', side_effect=replace):
            update_storage.private_write(self.path, new)
            self.assertEqual(json.load(original), old)
        self.assertEqual(events, ['file-sync', 'replace', 'directory-sync'])
        self.assertNotEqual(self.path.stat().st_ino, old_inode)
        self.assertEqual(update_storage.private_read(self.path), new)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_write_replaces_owned_public_file_with_private_mode(self):
        self.raw_file(self.path, b'{"old":true}').chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'unsafe-private-file'):
            update_storage.private_read(self.path)
        update_storage.private_write(self.path, {'new': True})
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(update_storage.private_read(self.path), {'new': True})

    def test_file_symlink_and_dangling_symlink_are_rejected(self):
        target = self.raw_file(self.root / 'target.json', b'{"keep":true}')
        for name, destination in (('linked.json', target), ('dangling.json', self.root / 'absent.json')):
            with self.subTest(name=name):
                path = self.root / name
                path.symlink_to(destination)
                with self.assertRaisesRegex(ValueError, 'unsafe-private-file'):
                    update_storage.private_write(path, {'changed': True})
                with self.assertRaises(OSError) as caught:
                    update_storage.private_read(path)
                self.assertEqual(caught.exception.errno, errno.ELOOP)
                self.assertTrue(path.is_symlink())
        self.assertEqual(target.read_bytes(), b'{"keep":true}')
        self.assertFalse((self.root / 'absent.json').exists())

    def test_multiple_hardlinks_are_rejected_without_touching_either_name(self):
        self.raw_file(self.path, b'{"keep":true}')
        alias = self.root / 'alias.json'
        os.link(self.path, alias)
        self.assertEqual(self.path.stat().st_nlink, 2)
        for path in (self.path, alias):
            with self.subTest(path=path):
                with self.assertRaisesRegex(ValueError, 'unsafe-private-file'):
                    update_storage.private_read(path)
                with self.assertRaisesRegex(ValueError, 'unsafe-private-file'):
                    update_storage.private_write(path, {'changed': True})
                self.assertEqual(path.read_bytes(), b'{"keep":true}')
        self.assertEqual(self.path.stat().st_ino, alias.stat().st_ino)

    def test_file_foreign_owner_is_rejected_for_read_and_write(self):
        self.raw_file(self.path, b'{"keep":true}')
        uid = os.getuid()
        for operation in (lambda: update_storage.private_read(self.path),
                          lambda: update_storage.private_write(self.path, {'changed': True})):
            with self.subTest(operation=operation), \
                    patch.object(update_storage.os, 'getuid', side_effect=[uid, uid + 1]):
                with self.assertRaisesRegex(ValueError, 'unsafe-private-file'):
                    operation()
        self.assertEqual(self.path.read_bytes(), b'{"keep":true}')

    def test_group_and_other_file_permissions_are_rejected(self):
        for mode in (0o601, 0o610, 0o640, 0o604, 0o666):
            with self.subTest(mode=oct(mode)):
                path = self.raw_file(self.root / f'{mode}.json', b'{}')
                path.chmod(mode)
                with self.assertRaisesRegex(ValueError, 'unsafe-private-file'):
                    update_storage.private_read(path)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode)

    def test_nonregular_files_are_rejected_without_blocking(self):
        directory = self.root / 'directory.json'
        directory.mkdir(mode=0o700)
        with self.assertRaisesRegex(ValueError, 'unsafe-private-file'):
            update_storage.private_write(directory, {})
        with self.assertRaises(OSError):
            update_storage.private_read(directory)
        fifo = self.root / 'fifo.json'
        os.mkfifo(fifo, 0o600)
        descriptor = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
        try:
            with self.assertRaisesRegex(ValueError, 'unsafe-private-file'):
                update_storage.private_read(fifo)
            with self.assertRaisesRegex(ValueError, 'unsafe-private-file'):
                update_storage.private_write(fifo, {})
        finally:
            os.close(descriptor)
        self.assertTrue(stat.S_ISFIFO(fifo.stat().st_mode))
        self.assertTrue(directory.is_dir())

    def test_size_limit_counts_utf8_bytes_and_allows_exact_boundary(self):
        value = {'detail': '测试'}
        update_storage.private_write(self.path, value)
        size = len(self.path.read_bytes())
        self.assertEqual(update_storage.private_read(self.path, limit=size), value)
        for limit in (0, size - 1):
            with self.subTest(limit=limit):
                with self.assertRaisesRegex(ValueError, 'unsafe-private-file'):
                    update_storage.private_read(self.path, limit=limit)

    def test_default_size_limit_rejects_oversized_file(self):
        self.raw_file(self.path, b' ' * (1024 * 1024 + 1))
        with self.assertRaisesRegex(ValueError, 'unsafe-private-file'):
            update_storage.private_read(self.path)

    def test_file_growth_between_fstat_and_read_is_rejected(self):
        self.raw_file(self.path, b'{}')
        inode = self.path.stat().st_ino
        real_fstat = os.fstat
        grown = []
        def grow(fd):
            info = real_fstat(fd)
            if info.st_ino == inode and not grown:
                with self.path.open('ab') as stream:
                    stream.write(b' ')
                grown.append(True)
            return info
        with patch.object(update_storage.os, 'fstat', side_effect=grow):
            with self.assertRaisesRegex(ValueError, 'update-metadata-too-large'):
                update_storage.private_read(self.path, limit=2)
        self.assertEqual(grown, [True])
        self.assertEqual(self.path.read_bytes(), b'{} ')

    def test_missing_invalid_json_and_invalid_utf8_propagate(self):
        with self.assertRaises(FileNotFoundError):
            update_storage.private_read(self.path)
        for index, raw in enumerate((b'', b'{', b'{} trailing', b'\xff')):
            with self.subTest(raw=raw):
                path = self.raw_file(self.root / f'{index}.json', raw)
                with self.assertRaises((json.JSONDecodeError, UnicodeDecodeError)):
                    update_storage.private_read(path)
                self.assertEqual(path.read_bytes(), raw)

    def test_serialization_failure_leaves_existing_file_and_no_temporary(self):
        self.raw_file(self.path, b'{"keep":true}')
        for value in ({'value': float('nan')}, {'value': float('inf')}, {'value': object()}):
            with self.subTest(value=value):
                with self.assertRaises((ValueError, TypeError)):
                    update_storage.private_write(self.path, value)
                self.assertEqual(self.path.read_bytes(), b'{"keep":true}')
                self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_temporary_open_failure_keeps_original(self):
        self.raw_file(self.path, b'{"keep":true}')
        real_open = os.open
        def fail(path, flags, *args, **kwargs):
            if flags & os.O_EXCL:
                raise PermissionError(errno.EACCES, 'temporary-denied')
            return real_open(path, flags, *args, **kwargs)
        with patch.object(update_storage.os, 'open', side_effect=fail):
            with self.assertRaisesRegex(PermissionError, 'temporary-denied'):
                update_storage.private_write(self.path, {'changed': True})
        self.assertEqual(self.path.read_bytes(), b'{"keep":true}')
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_file_fsync_failure_keeps_original_and_real_cleanup_runs(self):
        self.raw_file(self.path, b'{"keep":true}')
        inode = self.path.stat().st_ino
        with patch.object(update_storage.os, 'fsync', side_effect=OSError(errno.ENOSPC, 'file-sync-failed')):
            with self.assertRaisesRegex(OSError, 'file-sync-failed'):
                update_storage.private_write(self.path, {'changed': True})
        self.assertEqual(self.path.read_bytes(), b'{"keep":true}')
        self.assertEqual(self.path.stat().st_ino, inode)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_replace_failure_keeps_original_and_real_cleanup_runs(self):
        self.raw_file(self.path, b'{"keep":true}')
        inode = self.path.stat().st_ino
        with patch.object(update_storage.os, 'replace', side_effect=OSError(errno.EIO, 'replace-failed')):
            with self.assertRaisesRegex(OSError, 'replace-failed'):
                update_storage.private_write(self.path, {'changed': True})
        self.assertEqual(self.path.read_bytes(), b'{"keep":true}')
        self.assertEqual(self.path.stat().st_ino, inode)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_first_write_failure_does_not_publish_partial_file(self):
        with patch.object(update_storage.os, 'replace', side_effect=OSError('replace-failed')):
            with self.assertRaisesRegex(OSError, 'replace-failed'):
                update_storage.private_write(self.path, {'revision': 1})
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_directory_sync_failure_after_replace_reports_error_but_has_complete_json(self):
        update_storage.private_write(self.path, {'revision': 1})
        real_sync = os.fsync
        def fail(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError(errno.EIO, 'directory-sync-failed')
            return real_sync(fd)
        with patch.object(update_storage.os, 'fsync', side_effect=fail):
            with self.assertRaisesRegex(OSError, 'directory-sync-failed'):
                update_storage.private_write(self.path, {'revision': 2})
        # replace 已成功，目录 fsync 失败不能被误报为旧值已回滚。
        self.assertEqual(update_storage.private_read(self.path), {'revision': 2})
        self.assertEqual(list(self.root.iterdir()), [self.path])


class UpdateStateTests(RetainedFiles):
    def setUp(self):
        super().setUp()
        self.store = update_state.UpdateState(self.path)
        self.defaults = self.store.snapshot()
        self.pending = {'version': '2.0.8', 'staging_app': str(self.root / 'staged.app'),
                        'archive': str(self.root / 'signed.zip'),
                        'manifest': str(self.root / 'SHA256SUMS'),
                        'signature': str(self.root / 'SHA256SUMS.sig')}

    def assert_invalid_saved(self, values):
        for index, value in enumerate(values):
            with self.subTest(index=index, value=value):
                path = self.raw_file(self.root / f'invalid-{index}.json', json.dumps(value).encode())
                before = path.read_bytes()
                with self.assertRaisesRegex(ValueError, 'update-state-invalid'):
                    update_state.UpdateState(path)
                self.assertEqual(path.read_bytes(), before)

    def test_missing_state_uses_defaults_without_creating_file(self):
        self.assertEqual(self.defaults, {
            'schema': 1, 'phase': 'idle', 'version': None, 'progress': None,
            'error': None, 'detail': '', 'automatic': True, 'nextRetryAt': None,
            'retryCount': 0, 'deferCount': 0, 'lastCompletedCheck': 0,
            'lastDiscoveryAt': 0, 'pending': None, 'armedForQuit': False})
        self.assertFalse(self.path.exists())
        missing = self.root / 'absent' / 'state.json'
        self.assertEqual(update_state.UpdateState(missing).snapshot(), self.defaults)
        self.assertFalse(missing.parent.exists())

    def test_change_persists_then_returns_public_snapshot(self):
        result = self.store.change(phase='ready', version='2.0.8', progress=100,
                                   pending=self.pending, armedForQuit=True, automatic=False)
        saved = update_storage.private_read(self.path)
        self.assertEqual(saved, self.store.snapshot())
        self.assertEqual(update_state.UpdateState(self.path).snapshot(), saved)
        self.assertEqual(saved['pending'], self.pending)
        self.assertEqual(result, self.store.snapshot(public=True))
        self.assertEqual(result['phase'], 'ready')
        self.assertTrue(result['armedForQuit'])
        self.assertFalse(result['automatic'])
        self.assertEqual(set(saved) - set(result), {'schema', 'pending', 'lastCompletedCheck', 'lastDiscoveryAt'})

    def test_snapshots_are_deep_copies_and_hide_private_fields(self):
        self.store.change(pending=dict(self.pending, assets=['signed.zip']),
                          lastCompletedCheck=123, lastDiscoveryAt=456, diagnostics={'attempts': [1]})
        original = self.store.snapshot()
        snapshot = self.store.snapshot()
        snapshot['pending']['assets'].append('untrusted.zip')
        snapshot['phase'] = 'failed'
        public = self.store.snapshot(public=True)
        public['diagnostics']['attempts'].append(99)
        self.assertTrue({'schema', 'pending', 'lastCompletedCheck', 'lastDiscoveryAt'}.isdisjoint(public))
        self.assertNotIn(str(self.root), json.dumps(public))
        self.assertEqual(self.store.snapshot(), original)
        self.assertEqual(update_storage.private_read(self.path), original)

    def test_invalid_phase_does_not_write_or_mutate(self):
        self.store.change(phase='ready', pending=self.pending)
        original, raw = self.store.snapshot(), self.path.read_bytes()
        for phase in ('deferred', 'unknown', '', None, 1):
            with self.subTest(phase=phase):
                with self.assertRaisesRegex(ValueError, 'update-phase-invalid'):
                    self.store.change(phase=phase, version='9.9.9')
                self.assertEqual(self.store.snapshot(), original)
                self.assertEqual(self.path.read_bytes(), raw)
        self.store.change(progress=42)
        self.assertEqual(self.store.snapshot()['phase'], 'ready')
        self.assertEqual(update_storage.private_read(self.path)['progress'], 42)

    def test_change_replace_failure_preserves_memory_and_disk_then_can_retry(self):
        self.store.change(phase='ready', pending=self.pending, armedForQuit=True)
        original, raw = self.store.snapshot(), self.path.read_bytes()
        with patch.object(update_storage.os, 'replace', side_effect=OSError('persistence-failed')):
            with self.assertRaisesRegex(OSError, 'persistence-failed'):
                self.store.change(phase='failed', armedForQuit=False)
        self.assertEqual(self.store.snapshot(), original)
        self.assertEqual(self.path.read_bytes(), raw)
        self.assertEqual(update_state.UpdateState(self.path).snapshot(), original)
        self.assertEqual(list(self.root.iterdir()), [self.path])
        self.store.change(phase='failed', armedForQuit=False)
        self.assertFalse(update_state.UpdateState(self.path).snapshot()['armedForQuit'])

    def test_change_serialization_failure_does_not_mutate_memory(self):
        self.store.change(phase='idle')
        raw = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.store.change(progress=float('nan'))
        self.assertEqual(self.store.snapshot(), self.defaults)
        self.assertEqual(self.path.read_bytes(), raw)

    def test_post_replace_sync_failure_keeps_memory_old_but_restart_reads_new_state(self):
        self.store.change(phase='idle')
        real_sync = os.fsync
        def fail(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError('directory-sync-failed')
            return real_sync(fd)
        with patch.object(update_storage.os, 'fsync', side_effect=fail):
            with self.assertRaisesRegex(OSError, 'directory-sync-failed'):
                self.store.change(phase='ready', version='2.0.8', pending=self.pending)
        self.assertEqual(self.store.snapshot(), self.defaults)
        restarted = update_state.UpdateState(self.path).snapshot()
        self.assertEqual(restarted['phase'], 'ready')
        self.assertEqual(restarted['pending'], self.pending)

    def test_restart_interrupted_phases_schedule_first_delay_without_spending_budget(self):
        for phase in ('checking', 'downloading', 'preparing', 'installing'):
            with self.subTest(phase=phase):
                path = self.root / f'{phase}.json'
                saved = dict(self.defaults, phase=phase, retryCount=3, nextRetryAt=999,
                             pending=self.pending, version='2.0.8')
                update_storage.private_write(path, saved)
                raw = path.read_bytes()
                with patch.object(update_state.time, 'time', return_value=1000):
                    restarted = update_state.UpdateState(path)
                expected = dict(saved, phase='retrying', nextRetryAt=1060)
                self.assertEqual(restarted.snapshot(), expected)
                self.assertEqual(path.read_bytes(), raw)
                self.assertFalse(restarted.due(True, now=1059))
                self.assertTrue(restarted.due(True, now=1060))

    def test_restart_stable_phases_preserves_retry_and_pending_metadata(self):
        for phase in ('idle', 'retrying', 'ready', 'failed'):
            with self.subTest(phase=phase):
                path = self.root / f'{phase}.json'
                saved = dict(self.defaults, phase=phase, retryCount=4, deferCount=2,
                             nextRetryAt=5000, lastDiscoveryAt=1000, lastCompletedCheck=900,
                             pending=self.pending, version='2.0.8', armedForQuit=True)
                update_storage.private_write(path, saved)
                self.assertEqual(update_state.UpdateState(path).snapshot(), saved)

    def test_restart_legacy_deferred_becomes_ready_without_automatic_action(self):
        saved = dict(self.defaults, phase='deferred', pending=self.pending,
                     version='2.0.8', deferCount=3, nextRetryAt=1)
        update_storage.private_write(self.path, saved)
        restarted = update_state.UpdateState(self.path)
        self.assertEqual(restarted.snapshot(), dict(saved, phase='ready'))
        self.assertFalse(restarted.due(True, now=10 ** 12))
        self.assertEqual(update_storage.private_read(self.path), saved)

    def test_fresh_python_process_restores_persisted_state(self):
        self.store.change(phase='retrying', pending=self.pending, version='2.0.8',
                          retryCount=3, nextRetryAt=9876, automatic=False)
        result = subprocess.run(
            [sys.executable, '-B', '-c',
             'import json, sys; from mdpreview_core.update_state import UpdateState; '
             'print(json.dumps(UpdateState(sys.argv[1]).snapshot()))', str(self.path)],
            cwd=ROOT, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(ROOT),
                               MDPREVIEW_DATA_DIR=str(self.root), MDPREVIEW_DISABLE_UPDATES='1'),
            capture_output=True, text=True, check=True, timeout=30)
        self.assertEqual(json.loads(result.stdout), self.store.snapshot())
        self.assertEqual(result.stderr, '')

    def test_rejects_invalid_container_schema_and_phase(self):
        self.assert_invalid_saved([None, [], 'idle', 1, {},
                                   dict(self.defaults, schema=2), dict(self.defaults, schema=None),
                                   dict(self.defaults, phase='obsolete'), dict(self.defaults, phase=None)])

    def test_rejects_missing_negative_boolean_and_noninteger_counters(self):
        invalid = []
        for field in ('retryCount', 'deferCount'):
            invalid.append({key: value for key, value in self.defaults.items() if key != field})
            invalid.extend(dict(self.defaults, **{field: value}) for value in (-1, True, False, 1.5, '0', None))
        self.assert_invalid_saved(invalid)

    def test_rejects_invalid_nonfinite_and_negative_timestamps(self):
        invalid = []
        for field in ('lastCompletedCheck', 'nextRetryAt', 'lastDiscoveryAt'):
            invalid.extend(dict(self.defaults, **{field: value}) for value in
                           (-1, True, False, '0', float('nan'), float('inf'), -float('inf')))
            if field != 'nextRetryAt':
                invalid.append(dict(self.defaults, **{field: None}))
        self.assert_invalid_saved(invalid)

    def test_accepts_optional_legacy_fields_and_finite_timestamps(self):
        saved = {key: value for key, value in self.defaults.items()
                 if key not in ('armedForQuit', 'lastDiscoveryAt', 'lastCompletedCheck', 'nextRetryAt')}
        update_storage.private_write(self.path, saved)
        self.assertEqual(update_state.UpdateState(self.path).snapshot(), self.defaults)
        for index, value in enumerate((0, 12, 12.5)):
            path = self.root / f'timestamp-{index}.json'
            saved = dict(self.defaults, lastDiscoveryAt=value, lastCompletedCheck=value, nextRetryAt=value)
            update_storage.private_write(path, saved)
            self.assertEqual(update_state.UpdateState(path).snapshot(), saved)

    def test_rejects_invalid_version_type_format_and_length(self):
        values = (True, 123, [], '', '1.2', '1.2.3.4.5', 'v1.2.3', '1.2.3-beta',
                  '1.2.3\n', '../1.2.3', '1' * 29 + '.0.0')
        self.assert_invalid_saved([dict(self.defaults, version=value) for value in values])

    def test_accepts_none_three_four_component_and_length_boundary_versions(self):
        for index, version in enumerate((None, '1.2.3', '1.2.3.4', '1' * 28 + '.0.0')):
            with self.subTest(version=version):
                path = self.root / f'version-{index}.json'
                saved = dict(self.defaults, version=version)
                update_storage.private_write(path, saved)
                self.assertEqual(update_state.UpdateState(path).snapshot(), saved)

    def test_rejects_nonboolean_automatic_and_armed_flags(self):
        invalid = [{key: value for key, value in self.defaults.items() if key != 'automatic'}]
        for field in ('automatic', 'armedForQuit'):
            invalid.extend(dict(self.defaults, **{field: value}) for value in (0, 1, None, 'true', []))
        self.assert_invalid_saved(invalid)

    def test_rejects_pending_with_missing_or_nonstring_required_fields(self):
        values = ([], 'pending', {}, {'version': '2.0.8'}, {'staging_app': '/test.app'},
                  dict(self.pending, staging_app=None), dict(self.pending, staging_app=1),
                  dict(self.pending, version=None), dict(self.pending, version=2))
        self.assert_invalid_saved([dict(self.defaults, pending=value) for value in values])

    def test_storage_corruption_and_unsafe_permissions_are_not_silently_reset(self):
        self.raw_file(self.path, b'{')
        with self.assertRaises(json.JSONDecodeError):
            update_state.UpdateState(self.path)
        self.assertEqual(self.path.read_bytes(), b'{')
        private = self.root / 'valid.json'
        update_storage.private_write(private, self.defaults)
        private.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'unsafe-private-file'):
            update_state.UpdateState(private)
        link = self.root / 'linked.json'
        link.symlink_to(private)
        with self.assertRaises(OSError):
            update_state.UpdateState(link)
        self.assertTrue(link.is_symlink())

    def test_retry_budget_survives_restart_and_failure_disarms(self):
        info = dict(error='network', detail='连接失败', stage='archive', code='network-timeout',
                    http=503, attempts=4, retryable=True)
        self.assertEqual(update_state.RETRY_DELAYS, (60, 300, 1800, 7200))
        self.store.change(phase='ready', pending=self.pending, armedForQuit=True)
        for count, delay in enumerate((60, 300, 1800, 7200), 1):
            with self.subTest(count=count):
                self.store.change(armedForQuit=True)
                result = self.store.failure(info, now=100)
                self.assertEqual(result['phase'], 'retrying')
                self.assertEqual(result['retryCount'], count)
                self.assertEqual(result['nextRetryAt'], 100 + delay)
                self.assertFalse(result['armedForQuit'])
                for key in ('error', 'detail', 'stage', 'code', 'http', 'attempts', 'retryable'):
                    self.assertEqual(result[key], info[key])
                self.assertEqual(update_storage.private_read(self.path), self.store.snapshot())
                self.store = update_state.UpdateState(self.path)
                self.assertEqual(self.store.snapshot()['retryCount'], count)
                self.assertEqual(self.store.snapshot()['pending'], self.pending)
                self.assertFalse(self.store.due(True, now=99 + delay))
                self.assertTrue(self.store.due(True, now=100 + delay))
        for _ in range(2):
            result = self.store.failure(info, now=100)
            self.assertEqual(result['phase'], 'failed')
            self.assertEqual(result['retryCount'], 4)
            self.assertEqual(result['nextRetryAt'], 100 + 7 * 86400)
            self.assertFalse(result['armedForQuit'])
            self.store = update_state.UpdateState(self.path)

    def test_nonretryable_and_truthy_nonboolean_flags_do_not_spend_budget(self):
        for index, flag in enumerate((False, None, 1, 'true')):
            with self.subTest(flag=flag):
                store = update_state.UpdateState(self.root / f'flag-{index}.json')
                store.change(retryCount=2, armedForQuit=True)
                result = store.failure(dict(error='verify', detail='', retryable=flag), now=200)
                self.assertEqual(result['phase'], 'failed')
                self.assertEqual(result['retryCount'], 2)
                self.assertEqual(result['nextRetryAt'], 200 + update_state.CHECK_INTERVAL)
                self.assertFalse(result['armedForQuit'])

    def test_failure_defaults_and_implicit_clock(self):
        with patch.object(update_state.time, 'time', return_value=300):
            result = self.store.failure(dict(error='verify', detail='校验失败'))
        self.assertEqual(result['phase'], 'failed')
        self.assertEqual(result['nextRetryAt'], 300 + update_state.CHECK_INTERVAL)
        self.assertEqual(result['retryCount'], 0)
        self.assertEqual(result['attempts'], 0)
        self.assertFalse(result['retryable'])
        for key in ('stage', 'code', 'http'):
            self.assertIsNone(result[key])
        self.assertEqual(update_storage.private_read(self.path), self.store.snapshot())

    def test_failure_persistence_error_does_not_spend_retry_or_disarm(self):
        self.store.change(phase='ready', armedForQuit=True, retryCount=2, pending=self.pending)
        before, raw = self.store.snapshot(), self.path.read_bytes()
        info = dict(error='network', detail='', retryable=True)
        with patch.object(update_storage.os, 'replace', side_effect=OSError('persistence-failed')):
            with self.assertRaisesRegex(OSError, 'persistence-failed'):
                self.store.failure(info, now=500)
        self.assertEqual(self.store.snapshot(), before)
        self.assertEqual(self.path.read_bytes(), raw)
        result = self.store.failure(info, now=500)
        self.assertEqual(result['retryCount'], 3)
        self.assertEqual(result['nextRetryAt'], 2300)
        self.assertFalse(result['armedForQuit'])

    def test_due_disabled_busy_and_ready_never_run_even_with_expired_deadline(self):
        self.assertFalse(self.store.due(False, now=10 ** 12))
        for phase in ('checking', 'downloading', 'preparing', 'installing', 'ready'):
            with self.subTest(phase=phase):
                self.store.change(phase=phase, nextRetryAt=0, pending=self.pending)
                self.assertFalse(self.store.due(True, now=10 ** 12))

    def test_due_uses_retry_deadline_before_periodic_or_pending_checks(self):
        for phase in ('idle', 'retrying', 'failed'):
            with self.subTest(phase=phase):
                self.store.change(phase=phase, nextRetryAt=500, pending=self.pending,
                                  lastDiscoveryAt=500, lastCompletedCheck=500)
                self.assertFalse(self.store.due(True, now=499.5))
                self.assertTrue(self.store.due(True, now=500))
                self.assertTrue(self.store.due(True, now=501))

    def test_due_failed_without_deadline_uses_latest_discovery_or_completed_check(self):
        for completed, discovery in ((100, 200), (200, 100)):
            with self.subTest(completed=completed, discovery=discovery):
                self.store.change(phase='failed', nextRetryAt=None, pending=self.pending,
                                  lastCompletedCheck=completed, lastDiscoveryAt=discovery)
                self.assertFalse(self.store.due(True, now=200 + update_state.CHECK_INTERVAL - 1))
                self.assertTrue(self.store.due(True, now=200 + update_state.CHECK_INTERVAL))

    def test_due_pending_without_deadline_only_runs_idle(self):
        self.store.change(phase='idle', pending=self.pending, nextRetryAt=None, lastCompletedCheck=500)
        self.assertTrue(self.store.due(True, now=500))
        self.store.change(phase='retrying')
        self.assertFalse(self.store.due(True, now=10 ** 12))

    def test_due_periodic_boundary_and_default_clock(self):
        self.store.change(lastCompletedCheck=100, lastDiscoveryAt=500, pending=None, nextRetryAt=None)
        with patch.object(update_state.time, 'time', return_value=100 + update_state.CHECK_INTERVAL - 1):
            self.assertFalse(self.store.due(True))
        with patch.object(update_state.time, 'time', return_value=100 + update_state.CHECK_INTERVAL):
            self.assertTrue(self.store.due(True))


if __name__ == '__main__':
    unittest.main(verbosity=2)
