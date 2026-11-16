"""Real OS leases and atomic exchange, isolated fake bundles; never touches installed apps."""
import importlib.util
import ast
import errno
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mdpreview_core.update_runtime import RuntimeLease, transaction_root
from scripts import install_update as helper


class ReleaseSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='update-safety-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.destination = self.root / 'mdPreview.app'
        self.destination.mkdir()

    def test_multiple_readers_block_writer_and_release_allows_writer(self):
        first = RuntimeLease(self.destination)
        second = RuntimeLease(self.destination)
        try:
            with self.assertRaises(BlockingIOError):
                RuntimeLease(self.destination, exclusive=True)
            first.close()
            with self.assertRaises(BlockingIOError):
                RuntimeLease(self.destination, exclusive=True)
        finally:
            first.close()
            second.close()
        with RuntimeLease(self.destination, exclusive=True):
            with self.assertRaises(BlockingIOError):
                RuntimeLease(self.destination)

    def test_subprocess_startup_cannot_cross_exclusive_lease(self):
        code = ('from mdpreview_core.update_runtime import RuntimeLease; import sys; '
                'lease=RuntimeLease(sys.argv[1], blocking=True); print("started", flush=True)')
        with RuntimeLease(self.destination, exclusive=True):
            process = subprocess.Popen([sys.executable, '-B', '-c', code, str(self.destination)],
                                       cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                with self.assertRaises(subprocess.TimeoutExpired):
                    process.wait(timeout=0.2)
            except BaseException:
                process.kill()
                process.communicate()
                raise
        stdout, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(stdout.strip(), 'started')

    def test_exchange_survives_immediate_process_death_with_both_names(self):
        prepared = self.root / 'prepared.app'
        prepared.mkdir()
        (self.destination / 'version').write_text('old')
        (prepared / 'version').write_text('new')
        code = ('from scripts.install_update import _exchange; import os,sys; '
                '_exchange(sys.argv[1],sys.argv[2]); os._exit(77)')
        result = subprocess.run([sys.executable, '-B', '-c', code, str(self.destination), str(prepared)],
                                cwd=ROOT, timeout=10)
        self.assertEqual(result.returncode, 77)
        self.assertEqual((self.destination / 'version').read_text(), 'new')
        self.assertEqual((prepared / 'version').read_text(), 'old')
        helper._exchange(self.destination, prepared)
        self.assertEqual((self.destination / 'version').read_text(), 'old')

    def test_symlink_lock_rejected(self):
        root = transaction_root(self.destination)
        root.mkdir(mode=0o700)
        target = self.root / 'other'
        target.write_text('preserved')
        (root / 'runtime.lock').symlink_to(target)
        with self.assertRaises(OSError):
            RuntimeLease(self.destination)
        self.assertEqual(target.read_text(), 'preserved')

    def test_replaced_lock_detected(self):
        with RuntimeLease(self.destination) as lease:
            lock = lease.root / 'runtime.lock'
            lock.rename(lease.root / 'old.lock')
            lock.touch(mode=0o600)
            with self.assertRaisesRegex(ValueError, 'runtime-lock-changed'):
                lease.check()

    def test_startup_lock_problems_open_without_updates(self):
        nodes = ast.parse((ROOT / 'mdPreview.py').read_text()).body
        startup = next(node for node in nodes if isinstance(node, ast.If)
                       and 'frozen' in ast.unparse(node.test))
        code = compile(ast.Module(body=[startup], type_ignores=[]), str(ROOT / 'mdPreview.py'), 'exec')
        for error in (ValueError('private-directory-required'), ValueError('runtime-lock-invalid'),
                      PermissionError(errno.EPERM, 'tcc'), OSError(errno.ENOSPC, 'full')):
            with self.subTest(error=str(error)), patch('mdpreview_core.release.bundle_snapshot',
                    return_value={'path': str(self.destination)}), \
                    patch('mdpreview_core.update_runtime.RuntimeLease', side_effect=error):
                ns = dict(sys=SimpleNamespace(frozen=True, executable=str(self.destination / 'Contents/MacOS/mdPreview'),
                                              argv=[]), _RUNTIME_LEASE=None)
                exec(code, ns)
                self.assertIsNone(ns['_STARTUP_BUNDLE_SNAPSHOT'])
                self.assertIsNone(ns['_RUNTIME_LEASE'])

    def test_installer_refuses_the_same_broken_lock_a_running_copy_ignored(self):
        with RuntimeLease(self.destination) as lease:
            root = lease.root
        root.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'private-directory-required'):
            RuntimeLease(self.destination, exclusive=True)
        root.chmod(0o700)
        (root / 'runtime.lock').chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'runtime-lock-invalid'):
            RuntimeLease(self.destination, exclusive=True)

    def test_startup_readonly_disables_updates_but_identity_failure_refuses(self):
        nodes = ast.parse((ROOT / 'mdPreview.py').read_text()).body
        startup = next(node for node in nodes if isinstance(node, ast.If)
                       and 'frozen' in ast.unparse(node.test))
        code = compile(ast.Module(body=[startup], type_ignores=[]), str(ROOT / 'mdPreview.py'), 'exec')
        for error in (OSError(errno.EROFS, 'readonly'), PermissionError(errno.EACCES, 'denied')):
            with self.subTest(error=error.errno), patch('mdpreview_core.release.bundle_snapshot',
                    return_value={'path': str(self.destination)}), \
                    patch('mdpreview_core.update_runtime.RuntimeLease', side_effect=error):
                ns = dict(sys=SimpleNamespace(frozen=True, executable=str(self.destination / 'Contents/MacOS/mdPreview'),
                                              argv=[]), _RUNTIME_LEASE=None)
                exec(code, ns)
                self.assertIsNone(ns['_STARTUP_BUNDLE_SNAPSHOT'])
        lease = Mock()
        with patch('mdpreview_core.release.bundle_snapshot', return_value={'path': str(self.destination)}), \
                patch('mdpreview_core.update_runtime.RuntimeLease', return_value=lease), \
                patch('mdpreview_core.release.check_startup_snapshot', side_effect=ValueError('changed')):
            ns = dict(sys=SimpleNamespace(frozen=True, executable=str(self.destination / 'Contents/MacOS/mdPreview'),
                                          argv=[]), _RUNTIME_LEASE=None)
            with self.assertRaises(SystemExit):
                exec(code, ns)
            lease.close.assert_called_once()

    def test_public_and_hardlinked_runtime_locks_refuse(self):
        with RuntimeLease(self.destination) as lease:
            lock = lease.root / 'runtime.lock'
        lock.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'runtime-lock-invalid'):
            RuntimeLease(self.destination)
        lock.chmod(0o600)
        os.link(lock, self.root / 'hardlink')
        with self.assertRaisesRegex(ValueError, 'runtime-lock-invalid'):
            RuntimeLease(self.destination)

    def test_corrupt_candidate_released_for_next_download(self):
        spec = importlib.util.spec_from_file_location('normal_quit_fixture', ROOT / 'WorkSpace/tests/test_update_normal_quit.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fixture = module.NormalQuitTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.ns['_verify_pending_update'].side_effect = FileNotFoundError()
        fixture.ns['_run_update_job'](False, version='2.0.0', retry=True)
        self.assertIsNone(fixture.state['pending'])
        fixture.ns['load_config'] = lambda: {}
        fixture.ns['_prepare_update_install'] = Mock()
        fixture.ns['_run_update_job'](False, version='2.0.0', retry=True)
        fixture.ns['_download_and_extract'].assert_called_once()

    def test_update_state_is_separate_per_install_location(self):
        import hashlib
        nodes = {node.name: node for node in ast.parse((ROOT / 'mdPreview.py').read_text()).body
                 if isinstance(node, ast.FunctionDef)}
        names = {}
        for path in ('/Applications/mdPreview.app', '/Users/someone/Applications/mdPreview.app', None):
            ns = dict(os=os, hashlib=hashlib, _STARTUP_BUNDLE_SNAPSHOT={'path': path} if path else None)
            exec(compile(ast.Module(body=[nodes['_update_state_name']], type_ignores=[]), 'mdPreview.py', 'exec'), ns)
            names[path] = (ns['_update_state_name']('state'), ns['_update_state_name']('opportunistic'))
        self.assertEqual(names[None], ('state.json', 'opportunistic.json'))
        self.assertEqual(len({name for pair in names.values() for name in pair}), 6)
        for pair in names.values():
            for name in pair:
                self.assertRegex(name, r'^(state|opportunistic)(-[a-f0-9]{16})?\.json$')

    def legacy_plan(self):
        staging = self.root / 'UpdateStaging/job/install'
        app = staging / 'mdPreview.app'
        app.mkdir(parents=True)
        staging.chmod(0o700)
        identity = {'path': str(self.destination), 'device': 1, 'inode': 2, 'parentDevice': 3,
                    'parentInode': 4, 'executableDevice': 5, 'executableInode': 6}
        plan = {'pid': os.getppid(), 'staging': str(app), 'destination': str(self.destination),
                'destinationIdentity': dict(identity, version='2.0.8'), 'startupIdentity': identity,
                'teamId': None, 'version': '2.0.9'}
        for key in ('archive', 'manifest', 'signature', 'ready', 'log'):
            plan[key] = str(staging / key)
        path = staging / 'install-plan.json'
        helper.private_write(path, plan)
        return path, plan

    def test_legacy_entry_is_converted_and_installed_through_the_new_transaction(self):
        path, plan = self.legacy_plan()
        with patch.dict(os.environ, MDPREVIEW_DATA_DIR=str(self.root)), \
                patch.object(helper, 'verify_bundle'), patch.object(helper, 'check_startup_snapshot'), \
                patch.object(helper, 'check_installation_identity'), patch.object(helper, '_show_migration') as prompt, \
                patch.object(helper, 'run_plan') as install:
            helper.main(['--plan', str(path)])
            prompt.assert_not_called()
            (converted_path,), options = install.call_args
            self.assertEqual(options, {'legacy': True})
            converted = helper._load_plan(converted_path)
        self.assertEqual(converted_path.parent.parent, self.root / 'UpdateTransactions/install')
        for key in ('pid', 'destination', 'startupIdentity', 'destinationIdentity', 'archive',
                    'manifest', 'signature', 'staging', 'version', 'teamId'):
            self.assertEqual(converted[key], plan[key])
        # The old plan's own marker locations are never trusted.
        self.assertNotIn(plan['ready'], converted.values())
        self.assertTrue(self.destination.is_dir())

    def test_legacy_failure_reopens_old_app_and_explains_manual_install(self):
        path, plan = self.legacy_plan()
        (self.destination / 'Contents/MacOS').mkdir(parents=True)
        (self.destination / 'Contents/MacOS/mdPreview').write_text('old')
        with patch.dict(os.environ, MDPREVIEW_DATA_DIR=str(self.root)), \
                patch.object(helper, 'verify_bundle'), patch.object(helper, 'check_startup_snapshot'), \
                patch.object(helper, 'check_installation_identity'), patch.object(helper, '_show_migration') as prompt, \
                patch.object(helper.subprocess, 'run') as run, \
                patch.object(helper, 'run_plan', side_effect=RuntimeError('prepared-application-selfcheck-failed')):
            with self.assertRaises(RuntimeError):
                helper.main(['--plan', str(path)])
            prompt.assert_called_once_with('2.0.9')
            self.assertEqual(run.call_args.args[0], ['/usr/bin/open', str(self.destination)])

    def test_legacy_parent_waits_for_exit_and_treats_reused_pid_as_gone(self):
        plan = {'pid': 4242, 'destination': str(self.destination)}
        executable = str(self.destination / 'Contents/MacOS/mdPreview')
        states = [(4242, os.getuid(), 1, 2, executable), (4242, os.getuid(), 1, 2, executable), None]
        with patch.object(helper, '_process_identity', side_effect=lambda pid: states.pop(0)), \
                patch.object(helper.time, 'sleep'), patch.object(helper.os, 'kill', side_effect=AssertionError):
            parent = helper._LegacyParent(plan)
            parent.wait()
            self.assertTrue(parent.exited and not states)
        with patch.object(helper, '_process_identity', return_value=(4242, os.getuid(), 9, 9, '/usr/bin/other')):
            self.assertTrue(helper._LegacyParent(plan).gone())
        with patch.object(helper, '_process_identity', return_value=(4242, os.getuid(), 1, 2, executable)), \
                patch.object(helper.time, 'sleep'), patch.object(helper.time, 'monotonic', side_effect=[0, 0, 500]):
            with self.assertRaisesRegex(TimeoutError, 'legacy-parent-exit-timeout'):
                helper._LegacyParent(plan).wait()

    def test_invalid_legacy_plans_are_refused_without_any_action(self):
        path, plan = self.legacy_plan()
        for invalid in (dict(plan, pid=True), dict(plan, staging='/tmp/foreign.app'),
                        dict(plan, teamId='invalid'), dict(plan, archive='../bad'),
                        dict(plan, extra=1), {key: value for key, value in plan.items() if key != 'log'}):
            helper.private_write(path, invalid)
            with patch.dict(os.environ, MDPREVIEW_DATA_DIR=str(self.root)), \
                    patch.object(helper, 'verify_bundle'), patch.object(helper, 'check_startup_snapshot'), \
                    patch.object(helper, 'check_installation_identity'), \
                    patch.object(helper, '_show_migration') as prompt, patch.object(helper, 'run_plan') as install:
                with self.assertRaises(ValueError):
                    helper.main(['--plan', str(path)])
                prompt.assert_not_called()
                install.assert_not_called()
        helper.private_write(path, plan)
        with patch.dict(os.environ, MDPREVIEW_DATA_DIR=str(self.root)), \
                patch.object(helper, 'verify_bundle', side_effect=ValueError('bad-signature')), \
                patch.object(helper, 'run_plan') as install:
            with self.assertRaisesRegex(ValueError, 'bad-signature'):
                helper.main(['--plan', str(path)])
            install.assert_not_called()
        self.assertFalse((self.root / 'UpdateTransactions').exists())

if __name__ == '__main__':
    unittest.main(verbosity=2)
