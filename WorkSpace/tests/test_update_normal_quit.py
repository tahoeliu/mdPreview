"""仅抽取 AST 函数并使用内存替身；不导入应用、不启动进程或访问用户配置。"""
import ast
import copy
from contextlib import nullcontext
import fcntl
import hashlib
import io
import json
import logging
import os
from pathlib import Path, PurePosixPath
import plistlib
import stat
import subprocess
import sys
import threading
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / 'mdPreview.py').read_text()
HEAD_SOURCE = subprocess.check_output(['git', 'show', 'HEAD:mdPreview.py'], cwd=ROOT, text=True)
HEAD_JS = subprocess.check_output(['git', 'show', 'HEAD:app.js'], cwd=ROOT, text=True)


def functions(source=SOURCE):
    return {node.name: node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.FunctionDef)}


class NormalQuitTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.writes = {}
        self.queued = []
        self.workers = []
        self.process = types.SimpleNamespace(pid=902, poll=Mock(return_value=None))
        self.candidate = {'version': '2.0.0', 'staging_app': '/staging/target.app',
                          'archive': '/staging/update.zip', 'manifest': '/staging/SHA256SUMS',
                          'signature': '/staging/SHA256SUMS.sig'}
        self.state = dict(phase='ready', version='2.0.0', pending=self.candidate,
                          armedForQuit=True, automatic=True, code=None, retryCount=0,
                          nextRetryAt=None, lastDiscoveryAt=0, lastCompletedCheck=0)
        self.store = types.SimpleNamespace(value=self.state, lock=threading.RLock())
        self.store.snapshot = lambda **kw: copy.deepcopy(self.state)
        self.store.change = lambda **kw: self.state.update(kw) or dict(self.state)
        state_ns = dict(time=types.SimpleNamespace(time=lambda: 0))
        state_tree = ast.parse((ROOT / 'mdpreview_core/update_state.py').read_text())
        state_nodes = [node for node in state_tree.body if isinstance(node, (ast.Assign, ast.ClassDef))]
        exec(compile(ast.Module(body=state_nodes, type_ignores=[]), 'update_state.py', 'exec'), state_ns)
        self.store.failure = types.MethodType(state_ns['UpdateState'].failure, self.store)
        self.store.due = types.MethodType(state_ns['UpdateState'].due, self.store)
        self.plan = dict(transactionNonce='a' * 32, version='2.0.0',
                         destinationIdentity={'version': '1.0.0'}, commit='/private/commit.json',
                         abort='/private/abort.json')
        self.prepared = dict(plan=self.plan, process=self.process, relaunch=False)
        timer = lambda *a, **k: types.SimpleNamespace(start=lambda: None, cancel=lambda: None)
        thread = lambda **kw: types.SimpleNamespace(start=lambda: self.workers.append(kw['target']))
        self.ns = dict(threading=types.SimpleNamespace(Timer=timer, Thread=thread),
                       os=types.SimpleNamespace(path=__import__('os').path, environ={}, getpid=lambda: 901),
                       sys=types.SimpleNamespace(frozen=True, executable='/running.app/Contents/MacOS/mdPreview', argv=[]),
                       time=types.SimpleNamespace(monotonic=lambda: 0, time=lambda: 0),
                       json=json, logging=logging, re=__import__('re'),
                       uuid=types.SimpleNamespace(uuid4=lambda: types.SimpleNamespace(hex='b' * 32)),
                       HAS_COCOA=True, UPDATE_PRIVATE_DIR='/private', UPDATE_STAGING_DIR='/staging',
                       _STARTUP_BUNDLE_SNAPSHOT={'path': '/running.app'},
                       _pending_update_install=self.prepared, _update_relaunch_requested=False,
                       _state_lock=threading.RLock(),
                       _update_install_lock=threading.RLock(), _update_job_lock=threading.Lock(),
                       _update_state_store=self.store, _update_cancel=threading.Event(),
                       _QUIT_APPROVED=threading.Event(), _QUIT_REQUESTED=threading.Event(),
                       _UI_READY=threading.Event(), _PROCESS_START=0,
                       _update_scheduler_resume=threading.Event(), _update_wakeup=threading.Event(),
                       _update_scheduler_started=False, _update_state_init_lock=threading.RLock(),
                       STARTUP_UPDATE_DELAY=10, CHECK_INTERVAL=7 * 86400,
                       _should_check_update=lambda: self.store.due(self.ns['_auto_update_enabled']()),
                       _install_journal_path=lambda: '/private/journal.json', _remove_private_file=Mock(),
                       _quit_confirmation_active=False, _quit_confirmation_queue=[],
                       _quit_ack_timer=None, _QUIT_ACK_SECONDS=3, _window_apis={},
                       AppHelper=types.SimpleNamespace(callAfter=lambda fn: self.queued.append(fn)),
                       NSApplication=types.SimpleNamespace(sharedApplication=lambda: types.SimpleNamespace(
                           terminate_=lambda _: self.calls.append('terminate'))),
                       _ensure_windows_visible=lambda: self.calls.append('visible'),
                       _focus_window=lambda window: self.calls.append(('focus', window)),
                       _dispatch_js_to=lambda window, code: self.calls.append((window, code)),
                       _get_update_state=lambda: self.store,
                       _broadcast_update=Mock(),
                       _get_current_version=lambda: '1.0.0',
                       _publisher_team_id=lambda: 'TEAM',
                       _staged_version_acceptable=lambda remote, local: tuple(map(int, remote.split('.'))) >= tuple(map(int, local.split('.'))),
                       _verify_pending_update=Mock(side_effect=lambda pending, **kw: pending),
                       verify_bundle=Mock(),
                       _t=lambda en, zh: zh, _opportunistic_marker_path=lambda: '/private/outcome.json',
                       _auto_update_enabled=lambda: True, update_config=Mock(),
                       _download_and_extract=Mock(return_value=self.candidate),
                       _smoke_test_app=Mock(return_value=True), log_exception=Mock())
        names = ('_approve_update', '_begin_prepared_update_quit', '_cancel_update_relaunch',
                 '_decline_update', '_prepare_update_install', '_commit_prepared_update_on_quit',
                 '_begin_quit_confirmation', '_advance_quit_confirmation', '_finish_quit_confirmation',
                 '_cancel_quit_confirmation', '_cancel_quit_ack', '_quit_ack_timeout',
                 '_request_update', '_run_update_job', 'startup_ready', '_update_error', '_fatal_update', '_update_change',
                 '_check_prepared_update', '_schedule_startup_update_check',
                 '_resolve_opportunistic_outcome', '_check_pending_install')
        nodes = functions()
        module = ast.Module(body=[nodes[name] for name in names], type_ignores=[])
        exec(compile(module, str(ROOT / 'mdPreview.py'), 'exec'), self.ns)
        storage = types.ModuleType('mdpreview_core.update_storage')
        storage.private_write = self.write
        storage.private_read = self.read
        release = types.ModuleType('mdpreview_core.release')
        release.installation_identity = Mock(return_value={'version': '1.0.0'})
        release.check_startup_snapshot = Mock()
        diagnostics = types.ModuleType('mdpreview_core.diagnostics')
        diagnostics.record = Mock()
        download = types.ModuleType('mdpreview_core.update_download')
        tree = ast.parse((ROOT / 'mdpreview_core/update_download.py').read_text())
        selected = [node for node in tree.body if isinstance(node, (ast.Import, ast.Assign))
                    or isinstance(node, ast.ImportFrom) and not node.level
                    or isinstance(node, (ast.FunctionDef, ast.ClassDef))
                    and node.name in ('DownloadError', '_error', 'error_info')]
        exec(compile(ast.Module(body=selected, type_ignores=[]), 'update_download.py', 'exec'), download.__dict__)
        self.patches = [patch.dict(sys.modules, {'mdpreview_core.update_storage': storage,
                                                'mdpreview_core.release': release,
                                                'mdpreview_core.update_download': download,
                                                'mdpreview_core.diagnostics': diagnostics}),
                        patch.object(subprocess, 'Popen', return_value=self.process),
                        patch.object(subprocess, 'run', return_value=types.SimpleNamespace(
                            returncode=0, stdout='{"protocol":2,"normalQuit":1}'))]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def write(self, path, payload):
        self.writes[str(path)] = copy.deepcopy(payload)
        if str(path).endswith('commit.json'):
            self.calls.append(('commit', self.ns['_QUIT_APPROVED'].is_set()))

    def read(self, path):
        self.assertIsNone(self.ns['_pending_update_install'])
        self.assertFalse(any(name.endswith('commit.json') for name in self.writes))
        return {'nonce': 'b' * 32, 'pid': 902, 'success': True}

    def drain_ui(self):
        while self.queued:
            self.queued.pop(0)()

    def document(self, dirty=True):
        api = types.SimpleNamespace(window='document', is_dirty=dirty)
        self.ns['_window_apis'] = {1: api}
        return api

    def test_approve_uses_original_prompt_and_cancel_keeps_helper(self):
        api = self.document()
        self.assertTrue(self.ns['_approve_update']()['success'])
        self.assertEqual(self.calls, [])
        self.drain_ui()
        self.assertIn(('document', 'confirmQuitDocument()'), self.calls)
        self.assertTrue(self.prepared['relaunch'])
        self.assertEqual(self.writes, {})
        self.ns['_finish_quit_confirmation'](api, False)
        self.assertIs(self.ns['_pending_update_install'], self.prepared)
        self.assertFalse(self.prepared['relaunch'])
        self.assertFalse(self.ns['_QUIT_APPROVED'].is_set())
        self.assertFalse(self.ns['_update_relaunch_requested'])
        self.assertNotIn('terminate', self.calls)
        self.ns['_begin_quit_confirmation']()
        self.ns['_finish_quit_confirmation'](api, True)
        self.assertFalse(self.writes[self.plan['commit']]['relaunch'])

    def test_commit_only_after_every_document_and_before_approved(self):
        dirty = self.document()
        clean = types.SimpleNamespace(window='clean', is_dirty=False)
        self.ns['_window_apis'][2] = clean
        self.ns['_approve_update']()
        self.drain_ui()
        self.ns['_finish_quit_confirmation'](dirty, True)
        self.assertEqual(self.writes, {})
        self.ns['_finish_quit_confirmation'](clean, True)
        self.assertEqual(self.writes[self.plan['commit']],
                         {'nonce': 'a' * 32, 'pid': 901, 'success': True, 'relaunch': True})
        self.assertIn(('commit', False), self.calls)
        self.drain_ui()
        self.assertIn('terminate', self.calls)

    def test_dirty_timeout_cancels_without_commit(self):
        api = self.document()
        self.ns['_approve_update']()
        self.drain_ui()
        self.ns['_quit_ack_timeout'](api)
        self.drain_ui()
        self.assertFalse(self.ns['_quit_confirmation_active'])
        self.assertFalse(self.prepared['relaunch'])
        self.assertEqual(self.writes, {})

    def test_plain_quit_never_relaunches(self):
        api = self.document(False)
        self.ns['_begin_quit_confirmation']()
        self.ns['_finish_quit_confirmation'](api, True)
        self.assertFalse(self.writes[self.plan['commit']]['relaunch'])

    def test_commit_failure_does_not_block_original_quit(self):
        api = self.document()
        with patch.object(sys.modules['mdpreview_core.update_storage'], 'private_write', side_effect=OSError):
            self.ns['_approve_update']()
            self.drain_ui()
            self.assertFalse(self.ns['_QUIT_APPROVED'].is_set())
            self.ns['_finish_quit_confirmation'](api, True)
        self.assertTrue(self.ns['_QUIT_APPROVED'].is_set())
        self.drain_ui()
        self.assertIn('terminate', self.calls)

    def test_dead_helper_or_version_mismatch_skips_commit(self):
        self.ns['_quit_confirmation_active'] = True
        self.process.poll.return_value = 1
        self.assertFalse(self.ns['_commit_prepared_update_on_quit']())
        self.process.poll.return_value = None
        self.state['version'] = '3.0.0'
        self.assertFalse(self.ns['_commit_prepared_update_on_quit']())
        self.assertEqual(self.writes, {})

    def test_commit_cannot_run_before_confirmation(self):
        self.assertFalse(self.ns['_commit_prepared_update_on_quit']())
        self.ns['_quit_confirmation_active'] = True
        self.ns['_quit_confirmation_queue'] = [self.document()]
        self.assertFalse(self.ns['_commit_prepared_update_on_quit']())
        self.assertEqual(self.writes, {})

    def test_prepare_current_helper_protocol_without_document_access(self):
        self.ns['_pending_update_install'] = None
        self.assertTrue(self.ns['_prepare_update_install'](self.candidate)['success'])
        args = subprocess.Popen.call_args.args[0]
        self.assertEqual(args[:3], ['/running.app/Contents/MacOS/mdPreview', '--install-update-helper', '--plan'])
        self.assertEqual(subprocess.run.call_args.args[0][0], args[0])
        plan = self.writes[args[3]]
        self.assertEqual(set(plan), {'protocol', 'normalQuit', 'transactionNonce', 'pid', 'destination',
                                    'startupIdentity', 'destinationIdentity', 'archive', 'manifest',
                                    'signature', 'staging', 'version', 'teamId', 'ready', 'armed',
                                    'commit', 'abort', 'log'})
        self.assertEqual(plan['protocol'], 2)
        self.assertEqual(plan['normalQuit'], 1)
        self.assertEqual(Path(args[3]).parent, Path('/private/install') / ('b' * 32))
        self.assertFalse(any(name.endswith('commit.json') for name in self.writes))
        self.assertEqual(self.calls, [])
        self.assertEqual(self.queued, [])
        self.ns['_verify_pending_update'].assert_called_once_with(self.candidate, extract=False)
        self.ns['verify_bundle'].assert_called_once_with(Path('/running.app'), 'TEAM', '1.0.0')

    def test_invalid_armed_never_registers_or_quits(self):
        self.ns['_pending_update_install'] = None
        with patch.object(sys.modules['mdpreview_core.update_storage'], 'private_read', return_value={'success': True}):
            result = self.ns['_prepare_update_install'](self.candidate)
        self.assertFalse(result['success'])
        self.assertIsNone(self.ns['_pending_update_install'])
        self.assertEqual(self.state['error'], 'verify')
        self.assertFalse(self.state['retryable'])
        self.assertFalse(self.state['armedForQuit'])
        self.assertTrue(any(name.endswith('abort.json') for name in self.writes))
        self.assertFalse(any(name.endswith('commit.json') for name in self.writes))
        self.assertEqual(self.calls, [])

    def test_background_ready_prepares_without_quit(self):
        self.ns['_pending_update_install'] = None
        self.state['pending'] = None
        self.ns['load_config'] = lambda: {}
        self.assertTrue(self.ns['_request_update'](version='2.0.0')['success'])
        self.workers.pop(0)()
        self.assertTrue(self.state['armedForQuit'])
        self.assertIsNotNone(self.ns['_pending_update_install'])
        self.assertEqual(self.queued, [])
        self.assertEqual(self.calls, [])

    def test_approve_joins_preparing_worker_then_original_quit(self):
        api = self.document()
        self.ns['_pending_update_install'] = None
        self.ns['_request_update'](version='2.0.0')
        self.assertTrue(self.ns['_approve_update']()['joined'])
        self.assertEqual(self.queued, [])
        self.workers.pop(0)()
        self.assertEqual(self.calls, [])
        self.drain_ui()
        self.assertIn(('document', 'confirmQuitDocument()'), self.calls)
        self.ns['_finish_quit_confirmation'](api, False)
        self.assertFalse(any(name.endswith('commit.json') for name in self.writes))

    def test_cancel_while_worker_prepares_clears_delayed_quit(self):
        self.document()
        self.ns['_pending_update_install'] = None
        self.ns['_approve_update']()
        self.ns['_cancel_quit_confirmation']()
        self.workers.pop(0)()
        self.assertEqual(self.queued, [])
        self.assertIsNotNone(self.ns['_pending_update_install'])
        self.assertFalse(self.ns['_pending_update_install']['relaunch'])

    def test_busy_state_never_blocks_quit_commit(self):
        self.ns['_quit_confirmation_active'] = True
        self.store.lock = types.SimpleNamespace(acquire=Mock(return_value=False))
        self.assertFalse(self.ns['_commit_prepared_update_on_quit']())
        self.store.lock.acquire.assert_called_once_with(blocking=False)
        self.assertEqual(self.writes, {})

    def test_startup_receipt_contains_no_workspace(self):
        self.ns['sys'].argv = ['mdPreview', '--update-ready', '/private/install/ready.json']
        self.ns['startup_ready'](object(), 5)
        self.assertEqual(self.writes['/private/install/ready.json'],
                         {'pid': 901, 'version': '1.0.0', 'success': True})
        self.assertTrue(self.ns['_update_scheduler_resume'].is_set())

    def run_scheduler_once(self):
        self.ns['_update_wakeup'] = types.SimpleNamespace(
            clear=lambda: None, set=lambda: None,
            wait=lambda delay: self.ns['_QUIT_REQUESTED'].set() if delay == 60 else None)
        self.ns['_update_scheduler_resume'].set()
        self.ns['_schedule_startup_update_check']()
        self.workers.pop(0)()

    def assert_preflight_failure(self, code, retryable):
        self.assertIsNone(self.ns['_pending_update_install'])
        self.assertFalse(self.ns['_update_relaunch_requested'])
        self.assertFalse(self.state['armedForQuit'])
        self.assertEqual(self.state['code'], code)
        self.assertEqual(self.state['phase'], 'retrying' if retryable else 'failed')
        self.assertEqual(self.state['retryable'], retryable)
        self.assertNotEqual(self.state['error'], 'verify')
        self.assertFalse(any(name.endswith('commit.json') for name in self.writes))
        self.ns['_broadcast_update'].assert_called()

    def install_outcome(self, status='ready', nonce='a' * 32, bundle_version='2.0.0'):
        # 真实 prepare/record、verify_bundle 和 bundle_snapshot 共用内存文件系统。
        # journal 只能由 helper 写出，禁止测试补填 newIdentity.version。
        self.ns['_pending_update_install'] = None
        snapshots, versions = {}, {}
        directory_ids = {}

        class MemoryPath(PurePosixPath):
            def absolute(path):
                return path

            def resolve(path):
                return path

            def is_symlink(path):
                return False

            def is_dir(path):
                return str(path) in snapshots

            def exists(path):
                return str(path) in snapshots

            def is_file(path):
                return str(path.parent.parent.parent) in snapshots and path.name == 'mdPreview'

            def stat(path):
                if str(path) in snapshots:
                    value = snapshots[str(path)]['inode']
                elif path.name == 'mdPreview':
                    value = snapshots[str(path.parent.parent.parent)]['executableInode']
                else:
                    value = directory_ids[str(path)]
                return types.SimpleNamespace(st_dev=1, st_ino=value)

            def open(path, mode):
                self.assertEqual(mode, 'rb')
                app = str(path.parent.parent)
                return io.BytesIO(plistlib.dumps({'CFBundleIdentifier': 'tahoeliu.mdpreview',
                                                  'CFBundleExecutable': 'mdPreview',
                                                  'CFBundleShortVersionString': versions[app],
                                                  'MDPreviewRuntimeLease': 1}))

        def bundle(path, version, inode, parent_inode):
            snapshots[str(path)] = dict(inode=inode, executableInode=inode + 1)
            versions[str(path)] = version
            directory_ids[str(MemoryPath(path).parent)] = parent_inode

        def rename(source, destination):
            snapshots[str(destination)] = snapshots.pop(str(source))
            versions[str(destination)] = versions.pop(str(source))

        def exchange(source, destination):
            source, destination = str(source), str(destination)
            snapshots[source], snapshots[destination] = snapshots[destination], snapshots[source]
            versions[source], versions[destination] = versions[destination], versions[source]

        release_ns = dict(Path=MemoryPath, plistlib=plistlib, re=__import__('re'),
                          subprocess=types.SimpleNamespace(run=Mock()),
                          os=types.SimpleNamespace(access=lambda *args: True, W_OK=os.W_OK))
        nodes = functions((ROOT / 'mdpreview_core/release.py').read_text())
        selected = ('version_tuple', 'verify_bundle', 'bundle_snapshot', 'check_startup_snapshot',
                    'installation_identity', 'check_installation_identity')
        exec(compile(ast.Module(body=[nodes[name] for name in selected], type_ignores=[]),
                     'release.py', 'exec'), release_ns)
        bundle('/running.app', '1.0.0', 10, 2)
        bundle('/staging/target.app', bundle_version, 30, 4)
        old = release_ns['bundle_snapshot']('/running.app')
        plan = dict(self.plan, destination='/running.app', startupIdentity=old,
                    destinationIdentity=dict(old, version='1.0.0'), teamId=None)
        helper_ns = dict(release_ns, hashlib=hashlib, private_write=self.write,
                         _sync_tree=Mock(), _sync_directory=Mock(), _rename_exclusive=rename, _exchange=exchange,
                         shutil=types.SimpleNamespace(copytree=lambda src, dst, **kw:
                             bundle(dst, bundle_version, 20, 3)))
        tree = ast.parse((ROOT / 'scripts/install_update.py').read_text())
        selected = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef))
                    and node.name in ('_Transaction', '_same_bundle')]
        exec(compile(ast.Module(body=selected, type_ignores=[]), 'install_update.py', 'exec'), helper_ns)
        transaction = helper_ns['_Transaction'](plan)
        transaction.check_parent_directory = Mock()
        transaction.prepare('/staging/target.app')
        self.assertNotIn('version', release_ns['bundle_snapshot'](transaction.prepared))
        self.assertEqual(transaction.new_identity['version'], bundle_version)
        if status in ('ready', 'launching', 'rolled-back'):
            transaction.install()
        if status == 'rolled-back':
            transaction.rollback()
        transaction.record(status)
        journal = copy.deepcopy(self.writes[str(transaction.journal)])
        journal['nonce'] = nonce
        marker = {'schema': 1, 'nonce': 'a' * 32, 'version': '2.0.0', 'pid': 901}
        self.writes.clear()
        self.ns['_install_journal_path'] = lambda: transaction.journal
        self.ns['_STARTUP_BUNDLE_SNAPSHOT'] = release_ns['bundle_snapshot']('/running.app')
        self.ns['_publisher_team_id'] = lambda: None
        self.ns['verify_bundle'] = release_ns['verify_bundle']
        self.ns['version_tuple'] = release_ns['version_tuple']
        sys.modules['mdpreview_core.release'].check_startup_snapshot = release_ns['check_startup_snapshot']
        storage = sys.modules['mdpreview_core.update_storage']
        storage.private_directory = lambda path: nullcontext(91)
        present = [True]
        def read(path):
            if str(path).endswith('outcome.json'):
                if not present[0]:
                    raise FileNotFoundError
                return marker
            return journal
        storage.private_read = Mock(side_effect=read)
        self.ns['_remove_private_file'].side_effect = lambda path: present.__setitem__(0, False)
        lock_info = types.SimpleNamespace(st_dev=1, st_ino=90, st_mode=stat.S_IFREG | 0o600,
                                         st_uid=os.getuid(), st_nlink=1)
        root_info = types.SimpleNamespace(st_dev=1, st_ino=91)
        self.ns['os'] = types.SimpleNamespace(**{name: getattr(os, name) for name in
                                                ('O_RDONLY', 'O_NOFOLLOW', 'getuid', 'path')},
                                             open=Mock(return_value=90), close=Mock(), environ={},
                                             fstat=lambda fd: lock_info if fd == 90 else root_info,
                                             stat=Mock(return_value=lock_info))
        for patcher in (patch.object(fcntl, 'flock'), patch.object(Path, 'stat', return_value=root_info)):
            result = patcher.start()
            self.addCleanup(patcher.stop)
            if patcher.attribute == 'flock':
                self.flock = result
        self.release_ns = release_ns
        self.bundle_snapshots = snapshots
        self.bundle_versions = versions
        self.helper_transaction = transaction
        return marker, journal

    def test_helper_dies_between_approval_and_ui_callback(self):
        self.document()
        self.assertTrue(self.ns['_approve_update']()['success'])
        self.ns['_broadcast_update'].reset_mock()
        self.process.poll.return_value = 1
        self.drain_ui()
        self.assertTrue(self.ns['_update_wakeup'].is_set())
        self.assertEqual(self.calls, [])
        self.assertEqual(self.writes, {})
        self.run_scheduler_once()
        self.assert_preflight_failure('helper-preflight-dead', True)
        self.assertEqual(self.state['nextRetryAt'], 60)
        self.assertEqual(self.workers, [])

    def test_scheduler_detects_unapproved_dead_helper_when_auto_disabled(self):
        self.ns['_auto_update_enabled'] = lambda: False
        self.process.poll.return_value = 1
        self.run_scheduler_once()
        self.assert_preflight_failure('helper-preflight-dead', True)
        self.assertEqual(self.queued, [])
        self.assertEqual(self.calls, [])

    def test_missing_prepared_reference_reports_failure(self):
        self.ns['_approve_update']()
        self.ns['_pending_update_install'] = None
        self.drain_ui()
        self.ns['_check_prepared_update']()
        self.assert_preflight_failure('helper-preflight-dead', True)
        self.assertEqual(self.calls, [])

    def test_ui_callback_version_mismatch_is_not_silent(self):
        self.ns['_approve_update']()
        self.state['version'] = '3.0.0'
        self.drain_ui()
        self.ns['_check_prepared_update']()
        self.assert_preflight_failure('helper-preflight-version-mismatch', False)
        self.assertIn('/private/abort.json', self.writes)
        self.assertEqual(self.calls, [])

    def test_ui_callback_stale_phase_reports_recoverable_failure(self):
        self.ns['_approve_update']()
        self.state['phase'] = 'preparing'
        self.drain_ui()
        self.ns['_check_prepared_update']()
        self.assert_preflight_failure('helper-preflight-state-changed', True)
        self.assertEqual(self.calls, [])

    def test_liveness_cleanup_preserves_existing_verification_failure(self):
        self.ns['_approve_update']()
        self.store.failure(dict(error='verify', detail='', code='signed-digest-mismatch', retryable=False))
        self.process.poll.return_value = 1
        self.ns['_broadcast_update'].reset_mock()
        self.drain_ui()
        self.ns['_check_prepared_update']()
        self.assertIsNone(self.ns['_pending_update_install'])
        self.assertFalse(self.ns['_update_relaunch_requested'])
        self.assertEqual(self.state['code'], 'signed-digest-mismatch')
        self.assertFalse(self.state['retryable'])
        self.ns['_broadcast_update'].assert_called()

    def test_ui_callback_busy_locks_only_wake_background_scheduler(self):
        for name in ('install', 'state'):
            with self.subTest(lock=name):
                self.ns['_update_relaunch_requested'] = True
                busy = types.SimpleNamespace(acquire=Mock(return_value=False))
                if name == 'install':
                    context = patch.dict(self.ns, _update_install_lock=busy)
                else:
                    context = patch.object(self.store, 'lock', busy)
                with context:
                    self.ns['_begin_prepared_update_quit']()
                busy.acquire.assert_called_once_with(blocking=False)
                self.assertTrue(self.ns['_update_wakeup'].is_set())
                self.assertEqual(self.calls, [])
                self.assertEqual(self.writes, {})
        self.document()
        self.ns['_check_prepared_update']()
        self.drain_ui()
        self.assertIn(('document', 'confirmQuitDocument()'), self.calls)

    def test_scheduler_does_not_race_preparation_worker(self):
        self.process.poll.return_value = 1
        self.ns['_update_job_lock'].acquire()
        try:
            self.ns['_check_prepared_update']()
        finally:
            self.ns['_update_job_lock'].release()
        self.assertIs(self.ns['_pending_update_install'], self.prepared)
        self.ns['_broadcast_update'].assert_not_called()

    def test_duplicate_ui_callback_preserves_active_confirmation(self):
        self.document()
        self.ns['_approve_update']()
        self.drain_ui()
        self.ns['_begin_prepared_update_quit']()
        self.ns['_check_prepared_update']()
        self.assertTrue(self.ns['_quit_confirmation_active'])
        self.assertTrue(self.ns['_update_relaunch_requested'])
        self.assertTrue(self.prepared['relaunch'])
        self.assertEqual(self.state['phase'], 'preparing')

    def test_scheduler_during_ui_handoff_keeps_live_prepared_helper(self):
        self.ns['_update_relaunch_requested'] = True
        self.prepared['relaunch'] = True
        self.state['phase'] = 'preparing'
        self.ns['_check_prepared_update']()
        self.assertIs(self.ns['_pending_update_install'], self.prepared)
        self.assertTrue(self.ns['_update_relaunch_requested'])
        self.assertEqual(self.writes, {})
        self.ns['_broadcast_update'].assert_not_called()

    def test_manual_approval_clears_cancel_without_enabling_auto(self):
        api = self.document(False)
        self.ns['_auto_update_enabled'] = lambda: False
        self.ns['_update_cancel'].set()
        self.state.update(retryCount=4, deferCount=2, nextRetryAt=7200)
        self.assertTrue(self.ns['_approve_update']()['success'])
        self.assertFalse(self.ns['_update_cancel'].is_set())
        self.assertFalse(self.state['automatic'])
        self.assertEqual(self.state['retryCount'], 0)
        self.assertEqual(self.state['deferCount'], 0)
        self.assertIsNone(self.state['nextRetryAt'])
        self.drain_ui()
        self.ns['_finish_quit_confirmation'](api, True)
        self.assertTrue(self.writes[self.plan['commit']]['relaunch'])
        self.ns['update_config'].assert_not_called()

    def test_environment_disable_does_not_clear_cancel_or_approve(self):
        self.ns['os'].environ['MDPREVIEW_DISABLE_UPDATES'] = '1'
        self.ns['_update_cancel'].set()
        self.assertFalse(self.ns['_approve_update']()['success'])
        self.assertTrue(self.ns['_update_cancel'].is_set())
        self.assertFalse(self.ns['_update_relaunch_requested'])
        self.assertEqual(self.queued, [])

    def test_cancel_after_approval_does_not_quit_without_install(self):
        self.ns['_approve_update']()
        self.ns['_update_cancel'].set()
        self.drain_ui()
        self.ns['_check_prepared_update']()
        self.assert_preflight_failure('helper-preflight-cancelled', False)
        self.assertEqual(self.calls, [])

    def test_cancel_and_version_conflict_take_priority_over_helper_death(self):
        for cancelled in (False, True):
            with self.subTest(cancelled=cancelled):
                self.ns['_pending_update_install'] = self.prepared
                self.ns['_update_relaunch_requested'] = True
                self.state.update(phase='ready', version='3.0.0', armedForQuit=True)
                self.process.poll.return_value = 1
                if cancelled:
                    self.ns['_update_cancel'].set()
                self.ns['_check_prepared_update']()
                code = 'helper-preflight-cancelled' if cancelled else 'helper-preflight-version-mismatch'
                self.assert_preflight_failure(code, False)

    def test_worker_death_before_callback_wakes_scheduler(self):
        self.ns['_pending_update_install'] = None
        self.ns['_approve_update']()
        def finish_then_die(*args, **kwargs):
            self.ns['_pending_update_install'] = self.prepared
            self.process.poll.return_value = 1
        self.ns['_run_update_job'] = finish_then_die
        self.workers.pop(0)()
        self.assertEqual(self.queued, [])
        self.assertTrue(self.ns['_update_wakeup'].is_set())
        self.ns['_check_prepared_update']()
        self.assert_preflight_failure('helper-preflight-dead', True)

    def test_preflight_dead_is_bounded_retryable(self):
        self.ns['_pending_update_install'] = None
        self.process.poll.return_value = 1
        self.assertFalse(self.ns['_prepare_update_install'](self.candidate)['success'])
        self.assert_preflight_failure('helper-preflight-dead', True)
        self.assertTrue(any(name.endswith('abort.json') for name in self.writes))

    def test_preflight_timeout_is_bounded_retryable(self):
        self.ns['_pending_update_install'] = None
        self.ns['time'].monotonic = Mock(side_effect=[0, 45])
        with patch.object(sys.modules['mdpreview_core.update_storage'], 'private_read', side_effect=FileNotFoundError):
            self.assertFalse(self.ns['_prepare_update_install'](self.candidate)['success'])
        self.assert_preflight_failure('helper-preflight-timeout', True)
        self.assertEqual(self.calls, [])

    def test_capability_probe_timeout_is_retryable(self):
        self.ns['_pending_update_install'] = None
        subprocess.run.side_effect = subprocess.TimeoutExpired('helper', 10)
        self.assertFalse(self.ns['_prepare_update_install'](self.candidate)['success'])
        self.assert_preflight_failure('helper-preflight-timeout', True)
        subprocess.Popen.assert_not_called()

    def test_preflight_cancellation_is_not_verification_failure(self):
        self.ns['_pending_update_install'] = None
        self.ns['_update_cancel'].set()
        self.assertFalse(self.ns['_prepare_update_install'](self.candidate)['success'])
        self.assert_preflight_failure('helper-preflight-cancelled', False)

    def test_cancellation_after_armed_is_not_verification_failure(self):
        for success in (True, False):
            with self.subTest(armed_success=success):
                self.ns['_pending_update_install'] = None
                self.ns['_update_cancel'].clear()
                def armed(path):
                    self.ns['_update_cancel'].set()
                    return {'nonce': 'b' * 32, 'pid': 902, 'success': success}
                with patch.object(sys.modules['mdpreview_core.update_storage'], 'private_read', side_effect=armed):
                    self.assertFalse(self.ns['_prepare_update_install'](self.candidate)['success'])
                self.assert_preflight_failure('helper-preflight-cancelled', False)

    def test_cancellation_before_registration_aborts_without_commit(self):
        self.ns['_pending_update_install'] = None
        def write(path, value):
            self.write(path, value)
            if str(path).endswith('outcome.json'):
                self.ns['_update_cancel'].set()
        with patch.object(sys.modules['mdpreview_core.update_storage'], 'private_write', side_effect=write):
            self.assertFalse(self.ns['_prepare_update_install'](self.candidate)['success'])
        self.assert_preflight_failure('helper-preflight-cancelled', False)
        self.assertTrue(any(name.endswith('abort.json') for name in self.writes))

    def test_death_after_armed_is_not_registered(self):
        self.ns['_pending_update_install'] = None
        self.process.poll.side_effect = [None, 1]
        self.assertFalse(self.ns['_prepare_update_install'](self.candidate)['success'])
        self.assert_preflight_failure('helper-preflight-dead', True)

    def test_real_verification_and_identity_failures_remain_nonretryable(self):
        failures = (self.ns['_verify_pending_update'], self.ns['verify_bundle'],
                    sys.modules['mdpreview_core.release'].check_startup_snapshot)
        for verify in failures:
            with self.subTest(check=verify):
                self.ns['_pending_update_install'] = None
                self.state.update(phase='ready', armedForQuit=True)
                verify.side_effect = ValueError('signed-digest-mismatch')
                self.assertFalse(self.ns['_prepare_update_install'](self.candidate)['success'])
                self.assertEqual(self.state['error'], 'verify')
                self.assertEqual(self.state['phase'], 'failed')
                self.assertFalse(self.state['retryable'])
                self.assertFalse(self.state['armedForQuit'])
                verify.side_effect = None
                if verify is self.ns['_verify_pending_update']:
                    verify.return_value = self.candidate
        subprocess.Popen.assert_not_called()

    def test_legacy_helper_capabilities_remain_rejected(self):
        for capabilities in ({'protocol': 1}, {'protocol': 2}):
            with self.subTest(capabilities=capabilities):
                self.ns['_pending_update_install'] = None
                self.state.update(phase='ready', armedForQuit=True)
                subprocess.run.return_value.stdout = json.dumps(capabilities)
                result = self.ns['_prepare_update_install'](self.candidate)
                self.assertFalse(result['success'])
                self.assertEqual(self.state['code'], 'helper-handshake-unavailable')
                self.assertEqual(self.state['phase'], 'failed')
                self.assertFalse(self.state['armedForQuit'])
                self.assertFalse(self.state['retryable'])
        subprocess.Popen.assert_not_called()
        self.assertEqual(self.queued, [])

    def test_failure_clears_armed_and_exhausts_retry_budget(self):
        info = dict(error='unknown', detail='', stage='install_preflight',
                    code='helper-preflight-dead', retryable=True)
        for count, delay in enumerate((60, 300, 1800, 7200), 1):
            self.state['armedForQuit'] = True
            self.store.failure(info, now=100)
            self.assertEqual(self.state['phase'], 'retrying')
            self.assertEqual(self.state['retryCount'], count)
            self.assertEqual(self.state['nextRetryAt'], 100 + delay)
            self.assertFalse(self.state['armedForQuit'])
        self.store.failure(info, now=100)
        self.assertEqual(self.state['phase'], 'failed')
        self.assertEqual(self.state['retryCount'], 4)
        self.assertEqual(self.state['nextRetryAt'], 100 + 7 * 86400)

    def test_ready_journal_running_old_version_blocks_same_startup_and_retry(self):
        marker, journal = self.install_outcome()
        self.ns['_check_pending_install']()
        self.assertEqual(self.state['code'], 'quit-gap-version-unverified')
        self.assertEqual(self.state['phase'], 'failed')
        self.assertFalse(self.state['armedForQuit'])
        self.assertEqual(self.state['pending'], self.candidate)
        for automatic in (True, False):
            self.assertFalse(self.ns['_request_update'](automatic=automatic, version='3.0.0')['success'])
        self.assertEqual(self.workers, [])
        self.assertEqual(self.writes, {})
        self.assertEqual(marker['nonce'], journal['nonce'])
        self.ns['_remove_private_file'].assert_not_called()
        subprocess.Popen.assert_not_called()

    def test_ready_journal_requires_matching_current_and_recorded_versions(self):
        for current, recorded in (('3.0.0', '2.0.0'), ('2.0.0', '3.0.0'), ('2.0.0', None)):
            with self.subTest(current=current, recorded=recorded):
                _, journal = self.install_outcome()
                if recorded is None:
                    journal['newIdentity'].pop('version')
                else:
                    journal['newIdentity']['version'] = recorded
                self.ns['_get_current_version'] = lambda: current
                self.assertTrue(self.ns['_resolve_opportunistic_outcome']())
                self.assertEqual(self.state['code'], 'quit-gap-version-unverified')
                self.assertEqual(self.state['pending'], self.candidate)
        self.ns['_remove_private_file'].assert_not_called()
        self.assertEqual(self.writes, {})

    def test_ready_journal_matching_running_version_settles_successfully(self):
        self.install_outcome()
        self.ns['_check_pending_install']()
        self.assertEqual(self.state['code'], 'quit-gap-version-unverified')
        self.ns['_get_current_version'] = lambda: '2.0.0'
        self.ns['_check_pending_install']()
        self.assertEqual(self.state['phase'], 'idle')
        self.assertIsNone(self.state['pending'])
        self.assertIsNone(self.state['code'])
        self.assertFalse(self.state['armedForQuit'])
        self.ns['_remove_private_file'].assert_called_once_with('/private/outcome.json')
        self.assertEqual(self.workers, [])
        self.assertEqual(self.writes, {})

    def test_nonterminal_journal_preserves_evidence_and_blocks_replay(self):
        for status in ('preparing', 'prepared', 'armed', 'moving-old', 'old-moved',
                       'installing', 'installed', 'launching', 'recovery-required'):
            with self.subTest(status=status):
                self.install_outcome(status=status)
                self.state.update(phase='ready', armedForQuit=True)
                self.ns['_check_pending_install']()
                self.assertEqual(self.state['code'], 'quit-gap-version-unverified' if status == 'launching'
                                 else 'quit-gap-inconclusive')
                self.assertFalse(self.state['armedForQuit'])
                self.assertFalse(self.ns['_request_update'](automatic=False, retry=True)['success'])
        self.assertEqual(self.state['pending'], self.candidate)
        self.ns['_remove_private_file'].assert_not_called()
        self.assertEqual(self.workers, [])
        self.assertEqual(self.writes, {})

    def test_missing_or_conflicting_journal_blocks_replay(self):
        for journal in (None, {'nonce': 'c' * 32, 'state': 'ready'}):
            with self.subTest(journal=journal):
                marker, _ = self.install_outcome()
                def read(path):
                    if str(path).endswith('outcome.json'):
                        return marker
                    if journal is None:
                        raise FileNotFoundError
                    return journal
                sys.modules['mdpreview_core.update_storage'].private_read = read
                self.state.update(phase='ready', armedForQuit=True)
                self.ns['_check_pending_install']()
                self.assertEqual(self.state['code'], 'quit-gap-inconclusive')
                self.assertFalse(self.state['armedForQuit'])
        self.ns['_remove_private_file'].assert_not_called()
        self.assertEqual(self.workers, [])

    def test_unreadable_outcome_keeps_evidence_and_blocks_startup(self):
        self.ns['_pending_update_install'] = None
        sys.modules['mdpreview_core.update_storage'].private_read = Mock(side_effect=ValueError('unsafe-file'))
        self.ns['_check_pending_install']()
        self.assertEqual(self.state['code'], 'quit-gap-inconclusive')
        self.assertFalse(self.state['armedForQuit'])
        self.ns['_remove_private_file'].assert_not_called()
        self.assertEqual(self.workers, [])

    def test_rolled_back_or_cancelled_outcome_uses_bounded_retry(self):
        for status in ('rolled-back', 'cancelled'):
            with self.subTest(status=status):
                self.install_outcome(status=status)
                self.state.update(phase='ready', armedForQuit=True, retryCount=0)
                self.ns['_check_pending_install']()
                self.assertEqual(self.state['code'], 'quit-gap-install-failed')
                self.assertEqual(self.state['phase'], 'retrying')
                self.assertEqual(self.state['retryCount'], 1)
                self.assertFalse(self.state['armedForQuit'])
                self.assertEqual(self.state['pending'], self.candidate)
                self.assertEqual(self.workers, [])

    def test_helper_records_verified_version_not_requested_version(self):
        _, journal = self.install_outcome(bundle_version='2.0.0.0')
        self.assertEqual(self.helper_transaction.plan['version'], '2.0.0')
        self.assertEqual(journal['newIdentity']['version'], '2.0.0.0')
        self.ns['_get_current_version'] = lambda: '2.0.0'
        self.ns['_check_pending_install']()
        self.assertEqual(self.state['code'], 'quit-gap-version-unverified')
        self.ns['_remove_private_file'].assert_not_called()

    def test_same_version_other_bundle_or_executable_inode_is_rejected(self):
        for key in ('device', 'inode', 'parentDevice', 'parentInode',
                    'executableDevice', 'executableInode', 'path'):
            with self.subTest(identity=key):
                self.install_outcome()
                self.ns['_get_current_version'] = lambda: '2.0.0'
                current = self.ns['_STARTUP_BUNDLE_SNAPSHOT']
                current[key] = '/other.app' if key == 'path' else current[key] + 1
                self.ns['_check_pending_install']()
                self.assertIn(self.state['code'], ('quit-gap-version-unverified', 'quit-gap-inconclusive'))
                self.assertEqual(self.state['pending'], self.candidate)
                self.assertFalse(self.state['armedForQuit'])
        self.ns['_remove_private_file'].assert_not_called()
        self.assertEqual(self.writes, {})

    def test_disk_swap_after_startup_is_rejected(self):
        for key in ('inode', 'executableInode'):
            with self.subTest(identity=key):
                self.install_outcome()
                self.ns['_get_current_version'] = lambda: '2.0.0'
                self.bundle_snapshots['/running.app'][key] += 1
                self.ns['_check_pending_install']()
                self.assertEqual(self.state['code'], 'quit-gap-version-unverified')
        self.ns['_remove_private_file'].assert_not_called()

    def test_swap_during_signature_verification_is_rejected(self):
        self.install_outcome()
        self.ns['_get_current_version'] = lambda: '2.0.0'
        self.release_ns['subprocess'].run.side_effect = lambda *args, **kwargs: self.bundle_snapshots[
            '/running.app'].__setitem__('executableInode', 999)
        self.ns['_check_pending_install']()
        self.assertEqual(self.state['code'], 'quit-gap-version-unverified')
        self.ns['_remove_private_file'].assert_not_called()

    def test_disk_version_or_signature_failure_keeps_evidence(self):
        for signature_failure in (False, True):
            with self.subTest(signature=signature_failure):
                self.install_outcome()
                self.ns['_get_current_version'] = lambda: '2.0.0'
                if signature_failure:
                    self.release_ns['subprocess'].run.side_effect = ValueError('signature-invalid')
                else:
                    self.bundle_versions['/running.app'] = '3.0.0'
                self.ns['_check_pending_install']()
                self.assertEqual(self.state['code'], 'quit-gap-version-unverified')
        self.ns['_remove_private_file'].assert_not_called()

    def test_conflicting_journal_source_or_schema_blocks_settlement(self):
        changes = ({'schema': True}, {'schema': 2}, {'destination': '/other.app'},
                   {'prepared': '/other/prepared.app'}, {'previous': '/other/previous.app'},
                   {'rejected': '/other/rejected.app'}, {'extra': True})
        for values in changes:
            with self.subTest(values=values):
                _, journal = self.install_outcome()
                journal.update(values)
                self.ns['_get_current_version'] = lambda: '2.0.0'
                self.ns['_check_pending_install']()
                self.assertEqual(self.state['code'], 'quit-gap-inconclusive')
        self.ns['_remove_private_file'].assert_not_called()
        self.assertEqual(self.writes, {})

    def test_active_launching_settles_via_existing_scheduler_without_install(self):
        _, journal = self.install_outcome(status='launching')
        self.ns['_get_current_version'] = lambda: '2.0.0'
        self.state['retryCount'] = 3
        self.flock.side_effect = BlockingIOError
        self.ns['_check_pending_install']()
        self.assertEqual(self.state['phase'], 'retrying')
        self.assertEqual(self.state['code'], 'quit-gap-settlement-pending')
        self.assertEqual(self.state['nextRetryAt'], 60)
        self.assertEqual(self.state['retryCount'], 3)
        self.assertFalse(self.state['armedForQuit'])
        self.flock.assert_called_once_with(90, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.ns['os'].open.assert_called_once_with('lock', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=91)
        self.ns['os'].close.assert_called_once_with(90)
        self.ns['_remove_private_file'].assert_not_called()
        self.assertEqual(self.queued, [])
        self.flock.side_effect = None
        self.helper_transaction.record('ready')
        journal.update(self.writes.pop(str(self.helper_transaction.journal)))
        self.ns['_should_check_update'] = lambda: self.store.due(True, now=60)
        self.run_scheduler_once()
        self.assertEqual(len(self.workers), 1)
        self.ns['_QUIT_REQUESTED'].clear()
        self.workers.pop(0)()
        self.assertEqual(self.state['phase'], 'idle')
        self.assertIsNone(self.state['pending'])
        self.assertIsNone(self.state['code'])
        self.assertEqual(self.state['retryCount'], 0)
        self.ns['_remove_private_file'].assert_called_once_with('/private/outcome.json')
        self.ns['_download_and_extract'].assert_not_called()
        subprocess.Popen.assert_not_called()
        self.assertEqual(self.queued, [])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.writes, {})

    def test_repeated_busy_settlement_does_not_spend_retry_budget(self):
        self.install_outcome(status='launching')
        self.flock.side_effect = BlockingIOError
        for attempt in range(6):
            self.ns['_check_pending_install']()
            self.assertEqual(self.state['retryCount'], 0)
            self.assertEqual(self.state['phase'], 'retrying')
        self.assertTrue(self.ns['_request_update'](automatic=False, retry=True)['started'])
        self.workers.pop(0)()
        self.assertEqual(self.state['code'], 'quit-gap-settlement-pending')
        self.assertEqual(self.queued, [])
        self.assertEqual(self.calls, [])
        self.ns['_download_and_extract'].assert_not_called()
        subprocess.Popen.assert_not_called()

    def test_auto_disabled_still_settles_without_enabling_or_installing(self):
        _, journal = self.install_outcome(status='launching')
        self.ns['_auto_update_enabled'] = lambda: False
        self.ns['_get_current_version'] = lambda: '2.0.0'
        self.ns['os'].environ['MDPREVIEW_DISABLE_UPDATES'] = '1'
        self.flock.side_effect = BlockingIOError
        timer = types.SimpleNamespace(start=Mock())
        self.ns['threading'].Timer = Mock(return_value=timer)
        self.ns['_check_pending_install']()
        self.ns['threading'].Timer.assert_called_once_with(60, self.ns['_check_pending_install'])
        self.assertTrue(timer.daemon)
        timer.start.assert_called_once()
        self.flock.side_effect = None
        self.helper_transaction.record('ready')
        journal.update(self.writes.pop(str(self.helper_transaction.journal)))
        self.ns['threading'].Timer.call_args.args[1]()
        self.assertEqual(self.state['phase'], 'idle')
        self.assertIsNone(self.state['pending'])
        self.assertEqual(self.ns['os'].environ['MDPREVIEW_DISABLE_UPDATES'], '1')
        self.assertEqual(self.workers, [])
        self.assertEqual(self.queued, [])
        self.ns['_download_and_extract'].assert_not_called()
        subprocess.Popen.assert_not_called()

    def test_released_nonterminal_lock_requires_review_not_replay(self):
        self.install_outcome(status='launching')
        self.flock.side_effect = BlockingIOError
        self.ns['_check_pending_install']()
        self.assertEqual(self.state['code'], 'quit-gap-settlement-pending')
        self.flock.side_effect = None
        self.ns['_check_pending_install']()
        self.assertEqual(self.state['code'], 'quit-gap-version-unverified')
        self.assertFalse(self.ns['_request_update'](automatic=False, retry=True)['success'])
        self.ns['_remove_private_file'].assert_not_called()
        self.assertEqual(self.workers, [])
        self.assertEqual(self.writes, {})

    def test_unsafe_or_replaced_lock_blocks_settlement(self):
        for failure in ('missing', 'symlink', 'permissions', 'replaced'):
            with self.subTest(lock=failure):
                self.install_outcome()
                self.ns['_get_current_version'] = lambda: '2.0.0'
                if failure == 'missing':
                    self.ns['os'].open.side_effect = FileNotFoundError
                elif failure in ('symlink', 'permissions'):
                    info = self.ns['os'].fstat(90)
                    info.st_mode = stat.S_IFLNK | 0o600 if failure == 'symlink' else stat.S_IFREG | 0o644
                else:
                    original = self.ns['os'].stat.return_value
                    replaced = types.SimpleNamespace(st_dev=1, st_ino=999)
                    self.ns['os'].stat.side_effect = [original, replaced]
                self.ns['_check_pending_install']()
                self.assertEqual(self.state['code'], 'quit-gap-inconclusive')
        self.ns['_remove_private_file'].assert_not_called()

    def test_safe_cancel_or_rollback_retries_same_version_when_due(self):
        for status in ('cancelled', 'rolled-back'):
            with self.subTest(status=status):
                self.install_outcome(status=status)
                self.state.update(retryCount=0, phase='ready')
                self.ns['_check_pending_install']()
                self.assertEqual(self.state['retryCount'], 1)
                self.assertFalse(self.store.due(True, now=59))
                self.assertTrue(self.store.due(True, now=60))
                self.ns['_fetch_latest_version'] = Mock(return_value='2.0.0')
                self.ns['_is_newer'] = lambda remote, local: remote != local
                self.ns['_prepare_update_install'] = Mock(return_value={'success': True})
                self.ns['_should_check_update'] = lambda: self.store.due(True, now=60)
                self.ns['_update_scheduler_started'] = False
                self.ns['_QUIT_REQUESTED'].clear()
                self.run_scheduler_once()
                self.assertEqual(len(self.workers), 1)
                self.ns['_QUIT_REQUESTED'].clear()
                self.workers.pop(0)()
                self.assertEqual(self.state['phase'], 'ready')
                self.assertEqual(self.state['retryCount'], 1)
                self.ns['_fetch_latest_version'].assert_called_once()
                self.ns['_prepare_update_install'].assert_called_once_with(self.candidate)
                self.ns['_download_and_extract'].assert_not_called()
                self.assertFalse(any(name.endswith('commit.json') for name in self.writes))
        self.assertEqual(self.queued, [])
        self.assertEqual(self.calls, [])

    def test_exhausted_safe_install_retry_only_discovers_same_version(self):
        self.install_outcome(status='cancelled')
        self.state['retryCount'] = 4
        self.ns['_check_pending_install']()
        self.assertEqual(self.state['phase'], 'failed')
        self.ns['_fetch_latest_version'] = Mock(return_value='2.0.0')
        self.ns['_is_newer'] = lambda remote, local: remote != local
        self.ns['_prepare_update_install'] = Mock()
        self.assertTrue(self.ns['_request_update']()['started'])
        self.workers.pop(0)()
        self.ns['_fetch_latest_version'].assert_called_once()
        self.ns['_prepare_update_install'].assert_not_called()
        self.assertEqual(self.state['phase'], 'failed')
        self.assertEqual(self.state['retryCount'], 4)
        self.assertEqual(self.state['nextRetryAt'], 7 * 86400)

    def test_cancel_or_rollback_must_match_running_old_identity(self):
        for status in ('cancelled', 'rolled-back'):
            with self.subTest(status=status):
                _, journal = self.install_outcome(status=status)
                journal['oldIdentity']['executableInode'] += 1
                self.ns['_check_pending_install']()
                self.assertEqual(self.state['code'], 'quit-gap-version-unverified')
                self.assertEqual(self.state['retryCount'], 0)
        self.ns['_remove_private_file'].assert_not_called()

    def test_pending_check_preserves_this_process_prepared_install(self):
        self.ns['_check_pending_install']()
        self.assertIs(self.ns['_pending_update_install'], self.prepared)
        self.assertEqual(self.state['phase'], 'ready')
        self.ns['_broadcast_update'].assert_not_called()
        self.assertEqual(self.writes, {})

    def test_helper_parent_death_without_commit_is_rejected_in_memory(self):
        nodes = functions((ROOT / 'scripts/install_update.py').read_text())
        ns = dict(time=types.SimpleNamespace(monotonic=lambda: 0),
                  _check_abort=Mock(), _committed=Mock(return_value=False))
        exec(compile(ast.Module(body=[nodes['_wait_commit_exit']], type_ignores=[]),
                     'install_update.py', 'exec'), ns)
        parent = types.SimpleNamespace(gone=lambda: True)
        with self.assertRaisesRegex(RuntimeError, 'parent-exited-without-commit'):
            ns['_wait_commit_exit'](self.plan, parent)
        self.assertEqual(ns['_committed'].call_count, 2)
        self.assertEqual(self.writes, {})

    def test_helper_plain_quit_run_plan_does_not_launch_any_application(self):
        nodes = functions((ROOT / 'scripts/install_update.py').read_text())
        plan = dict(self.plan, destination='/running.app', startupIdentity={},
                    archive='/assets/update.zip', manifest='/assets/SHA256SUMS',
                    signature='/assets/SHA256SUMS.sig', teamId=None,
                    armed='/memory/armed.json', ready='/memory/ready.json')
        transaction = types.SimpleNamespace(acquire=Mock(), prepare=Mock(), install=Mock(),
                                             record=Mock(), close=Mock(), directory=Path('/transaction'),
                                             root=Path('/transaction'), owned=True, state='ready', collect=Mock(),
                                             prepared=Path('/transaction/prepared.app'), new_identity={})
        asset_info = types.SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=1, st_nlink=1)
        ns = dict(Path=Path, stat=stat, _load_plan=lambda path: plan,
                  RuntimeLease=Mock(return_value=types.SimpleNamespace(check=Mock(), close=Mock())),
                  shutil=types.SimpleNamespace(disk_usage=lambda path: types.SimpleNamespace(free=10**12)),
                  _Parent=lambda plan: types.SimpleNamespace(gone=lambda: False),
                  _Transaction=lambda plan: transaction,
                  check_startup_snapshot=Mock(), check_installation_identity=Mock(),
                  private_directory=lambda path: nullcontext(), verify_bundle=Mock(),
                  extract_verified=Mock(return_value='/staged.app'), _check_abort=Mock(),
                  private_write=Mock(), _wait_commit_exit=Mock(return_value={'relaunch': False}),
                  _selfcheck=Mock(), _same_bundle=Mock(),
                  _launch=Mock(side_effect=AssertionError('普通退出禁止重开应用')),
                  _wait_ready=Mock(), _note=Mock(),
                  os=types.SimpleNamespace(path=types.SimpleNamespace(lexists=lambda path: False),
                                           getuid=lambda: 1, getpid=lambda: 902))
        exec(compile(ast.Module(body=[nodes['run_plan']], type_ignores=[]),
                     'install_update.py', 'exec'), ns)
        with patch.object(Path, 'lstat', return_value=asset_info):
            self.assertTrue(ns['run_plan']('/memory/install-plan.json'))
        transaction.install.assert_called_once()
        ns['_selfcheck'].assert_called_once()
        self.assertEqual([call.args[0] for call in transaction.record.call_args_list], ['armed', 'ready'])
        transaction.close.assert_called_once()
        ns['_launch'].assert_not_called()
        ns['_wait_ready'].assert_not_called()

    def test_helper_ready_accepts_both_receipt_formats_only_for_current_live_process(self):
        nodes = functions((ROOT / 'scripts/install_update.py').read_text())
        ns = dict(time=types.SimpleNamespace(monotonic=lambda: 0), _check_abort=Mock(),
                  _optional=Mock())
        exec(compile(ast.Module(body=[nodes['_wait_ready']], type_ignores=[]),
                     'install_update.py', 'exec'), ns)
        plan = dict(self.plan, ready='/memory/ready.json')
        good = dict(pid=self.process.pid, version='2.0.0')
        # 启动回执可省略 success；这不放宽退出计划、armed 或 commit 的协议。
        for marker in (good, dict(good, success=True)):
            with self.subTest(accepted=marker):
                self.process.poll.reset_mock()
                ns['_optional'].reset_mock()
                ns['_optional'].return_value = marker
                ns['_wait_ready'](plan, self.process)
                ns['_optional'].assert_called_once_with(plan['ready'])
                self.assertEqual(self.process.poll.call_count, 2)
            for polls in ([0], [None, 0]):
                with self.subTest(exited=marker, polls=polls):
                    self.process.poll.side_effect = polls
                    with self.assertRaisesRegex(RuntimeError, 'updated-process-exited'):
                        ns['_wait_ready'](plan, self.process)
                    self.process.poll.side_effect = None
        for receipt in (good, dict(good, success=True)):
            invalid = (dict(receipt, success=1), dict(receipt, success=False),
                       dict(receipt, success=None), dict(receipt, workspaceRestored=True),
                       dict(receipt, extra=True), dict(receipt, pid=True),
                       dict(receipt, pid=999), dict(receipt, version='1.0.0'),
                       {key: value for key, value in receipt.items() if key != 'pid'},
                       {key: value for key, value in receipt.items() if key != 'version'}, [])
            for marker in invalid:
                with self.subTest(rejected=marker):
                    ns['_optional'].return_value = marker
                    with self.assertRaisesRegex(RuntimeError, 'application-ready-mismatch'):
                        ns['_wait_ready'](plan, self.process)
        self.assertEqual(self.writes, {})

    def test_original_document_and_quit_protection_matches_head(self):
        baseline = HEAD_SOURCE
        old, new = functions(baseline), functions()
        names = ('_begin_quit_confirmation', '_quit_ack_timeout', 'applicationShouldTerminate_',
                 'store_content', 'get_initial_content', 'discard_draft', 'recover_untitled',
                 'set_dirty', 'reset_to_untitled', 'save_file', 'ack_reload_from_disk',
                 'create_window', '_forget_window', 'on_window_closing', 'update_main_window')
        for name in names:
            with self.subTest(name=name):
                self.assertEqual(ast.get_source_segment(SOURCE, new[name]),
                                 ast.get_source_segment(baseline, old[name]))
        old_advance, new_advance = copy.deepcopy(old['_advance_quit_confirmation']), copy.deepcopy(new['_advance_quit_confirmation'])
        old_advance.body[-1].orelse = old_advance.body[-1].orelse[-2:]
        new_advance.body[-1].orelse = new_advance.body[-1].orelse[1:]
        self.assertEqual(ast.dump(old_advance), ast.dump(new_advance))
        js = (ROOT / 'app.js').read_text()
        old_js = HEAD_JS
        start, end = '  async function confirmQuitDocument()', "  document.getElementById('modalOverlay').addEventListener"
        self.assertEqual(js[js.index(start):js.index(end)], old_js[old_js.index(start):old_js.index(end)])
        for name in ('prepareUpdateCheckpoint', 'restoreUpdateView', 'guardUpdateOperation',
                     '_update_barrier', '_update_restore', '_update_exit_committed', '_perform_approved_install'):
            self.assertNotIn(name, SOURCE + js)


if __name__ == '__main__':
    unittest.main()
