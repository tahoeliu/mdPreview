"""实际 helper journal + 主程序 AST 隔离测试；仅使用保留的临时假应用，不启动 GUI。"""
import ast
import copy
import fcntl
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from mdpreview_core import release
from mdpreview_core.update_state import UpdateState, RETRY_DELAYS
from mdpreview_core.update_storage import private_read, private_write
from scripts import install_update as helper

SOURCE = (ROOT / 'mdPreview.py').read_text()
NODES = {node.name: node for node in ast.parse(SOURCE).body if isinstance(node, ast.FunctionDef)}
ARTIFACTS = Path(tempfile.mkdtemp(prefix='interrupted-run-', dir=Path(__file__).parent)).resolve()


class InterruptedTests(unittest.TestCase):
    def setUp(self):
        self.transactions = []
        self.signature_hook = None
        self.signature_error = None
        self.forbidden = []
        for target in ('subprocess.Popen', 'os.kill', 'scripts.install_update._launch',
                       'scripts.install_update._Transaction.install', 'scripts.install_update._committed'):
            patcher = patch(target, side_effect=AssertionError('隔离测试禁止安装、进程或提交操作'))
            mocked = patcher.start()
            self.forbidden.append(mocked)
            self.addCleanup(patcher.stop)
        patcher = patch.object(subprocess, 'run', side_effect=self.codesign)
        self.codesign_mock = patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.close_transactions)

    def tearDown(self):
        for mocked in self.forbidden:
            mocked.assert_not_called()

    def close_transactions(self):
        for transaction in self.transactions:
            transaction.close()

    def codesign(self, command, **kwargs):
        self.assertIn(command[0], ('/usr/bin/codesign', '/usr/sbin/spctl'))
        self.assertTrue(Path(command[-1]).is_relative_to(ARTIFACTS))
        if self.signature_hook:
            hook, self.signature_hook = self.signature_hook, None
            hook()
        if self.signature_error:
            raise self.signature_error
        return types.SimpleNamespace(returncode=0, stdout='', stderr='TeamIdentifier=ABCDEFGHIJ\n')

    def bundle(self, path, version):
        (path / 'Contents/MacOS').mkdir(parents=True)
        (path / 'Contents/MacOS/mdPreview').write_bytes(b'fake-app-not-executable')
        (path / 'Contents/Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier': 'tahoeliu.mdpreview', 'CFBundleExecutable': 'mdPreview',
            'MDPreviewRuntimeLease': 1,
            'CFBundleShortVersionString': version}))

    def fixture(self, phase='armed', retry_count=0):
        base = Path(tempfile.mkdtemp(prefix='case-', dir=ARTIFACTS))
        destination, staged = base / 'mdPreview.app', base / 'staged.app'
        self.bundle(destination, '1.0.0')
        self.bundle(staged, '2.0.0')
        startup = release.bundle_snapshot(destination)
        old = release.installation_identity(destination)
        nonce = 'a' * 32
        support = base / 'data'
        plan_dir = support / 'UpdateTransactions/install' / nonce
        plan = dict(protocol=2, normalQuit=1, transactionNonce=nonce, pid=os.getppid(),
                    destination=str(destination), startupIdentity=startup, destinationIdentity=old,
                    staging=str(staged), version='2.0.0', teamId='ABCDEFGHIJ')
        for key, name in (('archive', 'update.zip'), ('manifest', 'SHA256SUMS'), ('signature', 'SHA256SUMS.sig')):
            asset = base / name
            asset.write_bytes(('保留测试资产-' + key).encode())
            plan[key] = str(asset)
        for key in ('ready', 'armed', 'commit', 'abort', 'log'):
            plan[key] = str(plan_dir / ('install.log' if key == 'log' else key + '.json'))
        plan_path = plan_dir / 'install-plan.json'
        private_write(plan_path, plan)
        with patch.dict(os.environ, MDPREVIEW_DATA_DIR=str(support)):
            plan = helper._load_plan(plan_path)
        transaction = helper._Transaction(plan)
        self.transactions.append(transaction)
        transaction.acquire()
        if phase != 'preparing':
            transaction.prepare(staged)
        if phase not in ('preparing', 'prepared'):
            transaction.record(phase)
        private_write(plan['log'], {'state': phase, 'pendingPreserved': True})
        if phase == 'armed':
            private_write(plan['armed'], {'nonce': nonce, 'pid': os.getpid(), 'success': True})
        journal = private_read(transaction.journal)
        transaction.close()
        store = UpdateState(support / 'UpdateTransactions/state.json')
        pending = {key: plan[key] for key in ('archive', 'manifest', 'signature', 'version')}
        pending['staging_app'] = str(staged)
        store.change(phase='ready', version='2.0.0', pending=pending, armedForQuit=True,
                     retryCount=retry_count)
        ns = dict(os=os, re=re, time=types.SimpleNamespace(time=lambda: 100),
                  hashlib=hashlib, logging=logging, _STARTUP_BUNDLE_SNAPSHOT=startup,
                  UPDATE_PRIVATE_DIR=str(support / 'UpdateTransactions'),
                  _get_current_version=lambda: '1.0.0', _publisher_team_id=lambda: 'ABCDEFGHIJ',
                  verify_bundle=release.verify_bundle, _get_update_state=lambda: store,
                  _broadcast_update=Mock(), _t=lambda en, zh: zh, update_config=Mock(),
                  _update_install_lock=threading.RLock(), _pending_update_install=None,
                  _QUIT_REQUESTED=threading.Event(), _QUIT_APPROVED=threading.Event(),
                  _auto_update_enabled=lambda: True, _update_wakeup=threading.Event(),
                  _request_update=Mock(side_effect=AssertionError('结算不得自动安装')))
        names = ('_resolve_opportunistic_outcome', '_update_state_name', '_opportunistic_marker_path', '_install_journal_path',
                 '_check_pending_install', '_remove_private_file', '_fatal_update', '_update_change')
        exec(compile(ast.Module(body=[NODES[name] for name in names], type_ignores=[]),
                     str(ROOT / 'mdPreview.py'), 'exec'), ns)
        marker_path = Path(ns['_opportunistic_marker_path']())
        private_write(marker_path, {'schema': 1, 'nonce': nonce, 'version': '2.0.0', 'pid': os.getpid()})
        return types.SimpleNamespace(base=base, destination=destination, staged=staged, plan=plan,
                                     transaction=transaction, journal=journal, store=store, ns=ns,
                                     marker=marker_path, pending=pending)

    def acquire(self, case):
        plan = dict(case.plan, transactionNonce='b' * 32)
        transaction = helper._Transaction(plan)
        self.transactions.append(transaction)
        try:
            transaction.acquire()
        finally:
            transaction.close()
        return transaction

    def evidence(self, case):
        ignored = {case.transaction.journal, case.store.path, case.marker}
        result = {}
        for path in case.base.rglob('*'):
            if path in ignored:
                continue
            info = path.lstat()
            data = os.readlink(path) if path.is_symlink() else path.read_bytes() if path.is_file() else None
            result[str(path.relative_to(case.base))] = (info.st_dev, info.st_ino, info.st_mode, data)
        return result

    def assert_no_install(self, case):
        self.assertFalse(os.path.lexists(case.plan['commit']))
        self.assertFalse(os.path.lexists(case.transaction.root / ('b' * 32)))
        case.ns['_request_update'].assert_not_called()
        for mocked in self.forbidden:
            mocked.assert_not_called()

    def reject(self, case, entry):
        before = case.transaction.journal.read_bytes()
        if entry == 'helper':
            with self.assertRaises((ValueError, RuntimeError, OSError, subprocess.SubprocessError)):
                self.acquire(case)
        else:
            case.ns['_check_pending_install']()
            state = case.store.snapshot()
            self.assertEqual(state['phase'], 'failed')
            self.assertIn(state['code'], ('quit-gap-inconclusive', 'quit-gap-version-unverified'))
            self.assertEqual(state['retryCount'], 0)
            self.assertTrue(case.marker.exists())
            self.assertEqual(state['pending'], case.pending)
        self.assertEqual(case.transaction.journal.read_bytes(), before)
        self.assert_no_install(case)

    def test_atomic_exchange_crash_boundaries_settle_durably(self):
        for phase, exchange, rollback in (('exchanging', False, False), ('exchanging', True, False),
                                          ('exchanged', True, False), ('launching', True, False),
                                          ('rollback-exchanging', True, True)):
            with self.subTest(phase=phase, exchange=exchange, rollback=rollback):
                case = self.fixture(phase)
                if exchange:
                    helper._exchange(case.destination, case.transaction.prepared)
                if rollback:
                    case.transaction.prepared.rename(case.transaction.previous)
                    helper._exchange(case.destination, case.transaction.previous)
                running = release.bundle_snapshot(case.destination)
                current_version = '2.0.0' if exchange and not rollback else '1.0.0'
                case.ns['_STARTUP_BUNDLE_SNAPSHOT'] = running
                case.ns['_get_current_version'] = lambda: current_version
                self.assertFalse(case.ns['_resolve_opportunistic_outcome']())
                expected = 'ready' if current_version == '2.0.0' else 'rolled-back' if rollback else 'cancelled'
                self.assertEqual(private_read(case.transaction.journal)['state'], expected)
                self.assertFalse(case.marker.exists())
                case.plan['startupIdentity'] = running
                case.plan['destinationIdentity'] = dict(running, version=current_version)
                self.acquire(case)
                self.assertEqual(case.destination.stat().st_ino, running['inode'])

    def test_three_unreplaced_phases_cancel_only_and_preserve_materials(self):
        for phase in ('preparing', 'prepared', 'armed'):
            for entry in ('helper', 'main'):
                with self.subTest(phase=phase, entry=entry):
                    case = self.fixture(phase)
                    before = self.evidence(case)
                    if entry == 'helper':
                        with self.assertRaisesRegex(RuntimeError, '^interrupted-install-cancelled$'):
                            self.acquire(case)
                        self.assertTrue(case.marker.exists())
                        self.assertEqual(case.store.snapshot()['retryCount'], 0)
                    else:
                        with patch('mdpreview_core.update_state.time.time', return_value=100):
                            case.ns['_check_pending_install']()
                        state = case.store.snapshot()
                        self.assertEqual(state['phase'], 'retrying')
                        self.assertEqual(state['retryCount'], 1)
                        self.assertEqual(state['nextRetryAt'], 160)
                        self.assertEqual(state['pending'], case.pending)
                        self.assertFalse(state['armedForQuit'])
                        self.assertFalse(case.marker.exists())
                    self.assertEqual(private_read(case.transaction.journal), dict(case.journal, state='cancelled'))
                    self.assertEqual(self.evidence(case), before)
                    self.assert_no_install(case)

    def test_helper_cancellation_consumes_once_via_existing_main_settlement(self):
        case = self.fixture('preparing')
        with self.assertRaisesRegex(RuntimeError, '^interrupted-install-cancelled$'):
            self.acquire(case)
        case.ns['_check_pending_install']()
        self.assertEqual(case.store.snapshot()['retryCount'], 1)
        case.ns['_check_pending_install']()
        self.assertEqual(case.store.snapshot()['retryCount'], 1)
        self.assert_no_install(case)

    def test_existing_retry_budget_is_not_reset_or_bypassed(self):
        for count in range(len(RETRY_DELAYS) + 1):
            with self.subTest(retry_count=count):
                case = self.fixture('armed', count)
                with patch('mdpreview_core.update_state.time.time', return_value=100):
                    case.ns['_check_pending_install']()
                state = case.store.snapshot()
                exhausted = count == len(RETRY_DELAYS)
                self.assertEqual(state['phase'], 'failed' if exhausted else 'retrying')
                self.assertEqual(state['retryCount'], count if exhausted else count + 1)
                self.assertEqual(state['nextRetryAt'], 100 + (7 * 86400 if exhausted else RETRY_DELAYS[count]))
                self.assert_no_install(case)

    def test_later_and_unknown_phases_are_never_replayed(self):
        for phase in ('moving-old', 'old-moved', 'installing', 'installed', 'launching',
                      'recovery-required', 'unknown', ''):
            for entry in ('helper', 'main'):
                with self.subTest(phase=phase, entry=entry):
                    self.reject(self.fixture(phase), entry)

    def test_strict_journal_schema_paths_and_nonce(self):
        mutations = [dict(schema=True), dict(schema=2), dict(extra=True), dict(nonce='x' * 32),
                     dict(nonce='../escape'), dict(nonce='b' * 32), dict(destination='/other.app'),
                     dict(previous='/other/previous.app'), dict(prepared='/other/prepared.app'),
                     dict(rejected='/other/rejected.app'), dict(newIdentity=None), dict(oldIdentity=None)]
        for index, mutation in enumerate(mutations + [None, []]):
            for entry in ('helper', 'main'):
                with self.subTest(mutation=index, entry=entry):
                    case = self.fixture()
                    journal = dict(case.journal, **mutation) if isinstance(mutation, dict) else mutation
                    private_write(case.transaction.journal, journal)
                    self.reject(case, entry)
        for field in ('nonce', 'oldIdentity', 'newIdentity', 'previous'):
            for entry in ('helper', 'main'):
                with self.subTest(missing=field, entry=entry):
                    case = self.fixture()
                    journal = dict(case.journal)
                    journal.pop(field)
                    private_write(case.transaction.journal, journal)
                    self.reject(case, entry)

    def test_identity_schema_and_every_old_snapshot_field(self):
        for key in ('path', 'device', 'inode', 'parentDevice', 'parentInode',
                    'executableDevice', 'executableInode', 'version', 'extra'):
            for entry in ('helper', 'main'):
                with self.subTest(identity=key, entry=entry):
                    case = self.fixture()
                    journal = copy.deepcopy(case.journal)
                    old = journal['oldIdentity']
                    old[key] = '/other.app' if key == 'path' else '9.0.0' if key == 'version' else old.get(key, 0) + 1
                    private_write(case.transaction.journal, journal)
                    self.reject(case, entry)
        for entry in ('helper', 'main'):
            case = self.fixture()
            journal = copy.deepcopy(case.journal)
            journal['oldIdentity']['device'] = True
            private_write(case.transaction.journal, journal)
            self.reject(case, entry)

    def test_changed_application_executable_parent_and_signature(self):
        for change in ('bundle', 'executable', 'parent', 'signature', 'version'):
            for entry in ('helper', 'main'):
                with self.subTest(change=change, entry=entry):
                    case = self.fixture()
                    if change == 'bundle':
                        case.destination.rename(case.base / 'original.app')
                        self.bundle(case.destination, '1.0.0')
                    elif change == 'executable':
                        binary = case.destination / 'Contents/MacOS/mdPreview'
                        binary.rename(binary.with_name('original'))
                        binary.write_bytes(b'changed-inode')
                    elif change == 'parent':
                        original = case.base.with_name(case.base.name + '-original')
                        case.base.rename(original)
                        case.base.mkdir(mode=0o700)
                        for path in original.iterdir():
                            path.rename(case.base / path.name)
                    elif change == 'signature':
                        self.signature_error = subprocess.CalledProcessError(1, 'codesign')
                    else:
                        info = case.destination / 'Contents/Info.plist'
                        value = plistlib.loads(info.read_bytes())
                        value['CFBundleShortVersionString'] = '1.0.1'
                        info.write_bytes(plistlib.dumps(value))
                    try:
                        self.reject(case, entry)
                    finally:
                        self.signature_error = None

    def test_previous_and_rejected_any_entry_including_dangling_links_refuse(self):
        for name in ('previous', 'rejected'):
            for kind in ('directory', 'file', 'live-link', 'dangling-link'):
                for entry in ('helper', 'main'):
                    with self.subTest(name=name, kind=kind, entry=entry):
                        case = self.fixture()
                        path = getattr(case.transaction, name)
                        if kind == 'directory':
                            path.mkdir()
                        elif kind == 'file':
                            path.write_bytes(b'evidence')
                        else:
                            path.symlink_to(case.destination if kind == 'live-link' else case.base / 'missing')
                        self.reject(case, entry)
                        self.assertTrue(os.path.lexists(path))

    def test_held_original_lock_never_settles_or_spends_budget(self):
        for phase in ('preparing', 'prepared', 'armed', 'moving-old'):
            case = self.fixture(phase)
            fd = os.open(case.transaction.root / 'lock', os.O_RDWR)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            before = case.transaction.journal.read_bytes()
            try:
                with self.assertRaises(BlockingIOError):
                    self.acquire(case)
                for _ in range(2):
                    case.ns['_check_pending_install']()
                    state = case.store.snapshot()
                    self.assertEqual(state['code'], 'quit-gap-settlement-pending')
                    self.assertEqual(state['retryCount'], 0)
                    self.assertTrue(case.marker.exists())
                    self.assertEqual(case.transaction.journal.read_bytes(), before)
                self.assert_no_install(case)
            finally:
                os.close(fd)
            if phase != 'moving-old':
                case.ns['_check_pending_install']()
                self.assertEqual(private_read(case.transaction.journal)['state'], 'cancelled')
            else:
                self.reject(case, 'main')

    def test_missing_symlink_hardlink_and_public_lock_refuse(self):
        for kind in ('missing', 'symlink', 'hardlink', 'permissions'):
            for entry in ('helper', 'main'):
                with self.subTest(kind=kind, entry=entry):
                    case = self.fixture()
                    lock = case.transaction.root / 'lock'
                    if kind in ('missing', 'symlink'):
                        lock.rename(lock.with_name('original-lock'))
                        if kind == 'symlink':
                            lock.symlink_to(lock.with_name('original-lock'))
                    elif kind == 'hardlink':
                        os.link(lock, lock.with_name('second-link'))
                    else:
                        lock.chmod(0o644)
                    self.reject(case, entry)
                    if kind == 'missing':
                        self.assertFalse(os.path.lexists(lock))

    def test_private_transaction_and_root_directory_required(self):
        for kind in ('root-mode', 'transaction-mode', 'transaction-link', 'root-link'):
            for entry in ('helper', 'main'):
                with self.subTest(kind=kind, entry=entry):
                    case = self.fixture()
                    path = case.transaction.root if kind.startswith('root') else case.transaction.directory
                    if kind.endswith('mode'):
                        path.chmod(0o755)
                    else:
                        moved = path.with_name(path.name + '-original')
                        path.rename(moved)
                        path.symlink_to(moved, target_is_directory=True)
                    self.reject(case, entry)

    def test_mutation_during_signature_check_is_rejected_before_cancel_write(self):
        for kind in ('executable', 'lock', 'directory', 'root', 'journal', 'previous', 'rejected'):
            for entry in ('helper', 'main'):
                with self.subTest(kind=kind, entry=entry):
                    case = self.fixture()
                    before = case.transaction.journal.read_bytes()
                    def mutate():
                        if kind == 'executable':
                            path = case.destination / 'Contents/MacOS/mdPreview'
                            path.rename(path.with_name('original'))
                            path.write_bytes(b'changed-inode')
                        elif kind == 'lock':
                            path = case.transaction.root / 'lock'
                            path.rename(path.with_name('original-lock'))
                            path.touch(mode=0o600)
                        elif kind in ('directory', 'root'):
                            path = getattr(case.transaction, kind)
                            moved = path.with_name(path.name + '-original')
                            path.rename(moved)
                            path.mkdir(mode=0o700)
                            for child in moved.iterdir():
                                child.rename(path / child.name)
                        elif kind == 'journal':
                            private_write(case.transaction.journal, case.journal)
                        else:
                            getattr(case.transaction, kind).symlink_to(case.base / 'missing')
                    if entry == 'main':
                        # 主程序先做原有验证；在共享结算函数的验证时才注入置换。
                        original = helper.verify_bundle
                        def verify(*args, **kwargs):
                            self.signature_hook = mutate
                            return original(*args, **kwargs)
                        context = patch.object(helper, 'verify_bundle', side_effect=verify)
                    else:
                        self.signature_hook = mutate
                        context = patch.object(helper, 'verify_bundle', wraps=helper.verify_bundle)
                    with context:
                        self.reject(case, entry)
                    self.assertEqual(case.transaction.journal.read_bytes(), before)

    def test_marker_nonce_conflict_does_not_cancel_other_transaction(self):
        case = self.fixture()
        marker = private_read(case.marker)
        marker['nonce'] = 'c' * 32
        private_write(case.marker, marker)
        self.reject(case, 'main')

    def test_failed_cancel_write_preserves_original_journal_and_materials(self):
        for entry in ('helper', 'main'):
            with self.subTest(entry=entry):
                case = self.fixture()
                before = self.evidence(case)
                original = os.replace
                def fail_cancel(source, destination, **kwargs):
                    if str(source).startswith('.cancel-'):
                        raise OSError('模拟取消日志写入失败')
                    return original(source, destination, **kwargs)
                with patch.object(os, 'replace', side_effect=fail_cancel):
                    self.reject(case, entry)
                self.assertEqual(self.evidence(case), before)


if __name__ == '__main__':
    output = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(InterruptedTests)
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    text = output.getvalue()
    (ARTIFACTS / 'test-results.txt').write_text(text)
    print(text, end='')
    print('隔离测试产物保留于 ' + str(ARTIFACTS))
    raise SystemExit(not result.wasSuccessful())
