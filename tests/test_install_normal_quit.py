"""普通退出协议隔离测试；旧 test_install_update_safe 的工作区恢复协议已失效。

仅在临时目录操作假包；签名、父进程和应用启动均模拟，不执行真实应用。
"""
import copy
import io
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from contextlib import redirect_stdout
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / 'WorkSpace' / 'test-scratch'
SCRATCH.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
from scripts import install_update as helper
from mdpreview_core import release
from mdpreview_core.update_storage import private_read, private_write


class FakeProcess:
    def __init__(self):
        self.pid = 765432
        self.returncode = None
        self.exits_on_wait = True
        self.actions = []

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.actions.append(('wait', timeout))
        if self.exits_on_wait:
            self.returncode = 0
        if self.returncode is None:
            raise subprocess.TimeoutExpired('fake-process', timeout)
        return self.returncode

    def terminate(self):
        raise AssertionError('禁止强制终止应用')

    def kill(self):
        raise AssertionError('禁止强杀应用')


class NormalQuitInstallerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='normal-quit-installer-', dir=SCRATCH)).resolve()
        self.patch(mock.patch.dict(os.environ, {'MDPREVIEW_DATA_DIR': str(self.root)}))
        self.destination = self.make_bundle(self.root / 'mdPreview.app', '1.0.0')
        self.source = self.make_bundle(self.root / 'staged.app', '2.0.0')
        self.nonce = uuid.uuid4().hex
        self.directory = self.root / 'UpdateTransactions/install' / self.nonce
        self.assets = self.root / 'assets'
        self.assets.mkdir(mode=0o700)
        for name in ('release.zip', 'SHA256SUMS', 'SHA256SUMS.sig'):
            (self.assets / name).write_bytes(b'fake-signed-release')
        self.startup = release.bundle_snapshot(self.destination)
        self.plan = {
            'protocol': 2, 'normalQuit': 1, 'transactionNonce': self.nonce, 'pid': os.getppid(),
            'destination': str(self.destination), 'startupIdentity': self.startup,
            'destinationIdentity': dict(self.startup, version='1.0.0'),
            'archive': str(self.assets / 'release.zip'), 'manifest': str(self.assets / 'SHA256SUMS'),
            'signature': str(self.assets / 'SHA256SUMS.sig'), 'staging': str(self.source),
            'version': '2.0.0', 'teamId': 'ABCDEFGHIJ',
        }
        for key, name in (('ready', 'ready.json'), ('armed', 'armed.json'), ('commit', 'commit.json'),
                          ('abort', 'abort.json'), ('log', 'install.log')):
            self.plan[key] = str(self.directory / name)
        self.plan_path = self.directory / 'install-plan.json'
        private_write(self.plan_path, self.plan)
        self.parent_identity = (self.plan['pid'], os.getuid(), 100, 23,
                                str(self.destination / 'Contents/MacOS/mdPreview'))
        self.parent_alive = True
        self.relaunch = False
        self.process = FakeProcess()
        self.launches = []
        self.events = []
        self.real_launch = helper._launch
        self.real_selfcheck = helper._selfcheck
        self.patch(mock.patch.object(helper, '_selfcheck', side_effect=lambda app, directory:
                                     self.events.append(('selfcheck', Path(app).name))))
        self.patch(mock.patch.object(helper, '_process_identity', side_effect=lambda pid:
                                     self.parent_identity if self.parent_alive else None))
        self.patch(mock.patch.object(helper, 'verify_bundle', side_effect=self.verify))
        self.patch(mock.patch.object(release, 'verify_bundle', side_effect=self.verify))
        self.patch(mock.patch.object(helper, 'extract_verified', side_effect=self.extract))
        self.patch(mock.patch.object(helper, '_launch', side_effect=self.launch))
        self.patch(mock.patch.object(helper.time, 'sleep', side_effect=self.handshake))
        self.patch(mock.patch.object(subprocess, 'run', side_effect=AssertionError('禁止外部命令')))
        self.patch(mock.patch.object(subprocess, 'Popen', side_effect=AssertionError('禁止启动真实应用')))
        self.patch(mock.patch.object(os, 'kill', side_effect=AssertionError('禁止向真实进程发信号')))

    def patch(self, patcher):
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def make_bundle(self, app, version):
        self.assertTrue(app.is_relative_to(self.root))
        (app / 'Contents/MacOS').mkdir(parents=True)
        (app / 'Contents/MacOS/mdPreview').write_bytes(version.encode())
        (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString': version,
                                                              'MDPreviewRuntimeLease': 1}))
        return app

    def verify(self, app, team_id=None, expected_version=None):
        self.assertTrue(Path(app).is_relative_to(self.root))
        version = plistlib.loads((Path(app) / 'Contents/Info.plist').read_bytes())['CFBundleShortVersionString']
        if expected_version is not None and version != expected_version:
            raise ValueError('假包版本不符')
        self.events.append(('verify', Path(app).name))
        return version

    def extract(self, archive, manifest, signature, destination):
        self.assertTrue(self.parent_alive)
        self.assertEqual(self.launches, [])
        self.events.append('signature')
        destination.mkdir(mode=0o700)
        return Path(shutil.copytree(self.source, destination / 'mdPreview.app'))

    def handshake(self, _):
        self.assertTrue(self.parent_alive)
        self.assertEqual(private_read(self.plan['armed']),
                         {'nonce': self.nonce, 'pid': os.getpid(), 'success': True})
        transaction = helper._Transaction(self.plan)
        self.assertEqual(private_read(transaction.journal)['state'], 'armed')
        self.assertTrue(transaction.prepared.is_dir())
        self.assert_old()
        self.events.append('armed-before-exit')
        self.commit()
        self.parent_alive = False

    def commit(self, **changes):
        value = dict(nonce=self.nonce, pid=self.plan['pid'], success=True, relaunch=self.relaunch)
        value.update(changes)
        private_write(self.plan['commit'], value)

    def marker(self, **changes):
        value = dict(pid=self.process.pid, version='2.0.0', success=True)
        value.update(changes)
        private_write(self.plan['ready'], value)

    def launch(self, app, ready):
        self.assertFalse(self.parent_alive)
        self.assertTrue(self.relaunch)
        self.assertEqual(str(app), str(self.destination))
        self.assertEqual(ready, self.plan['ready'])
        self.assertEqual(self.verify(app), '2.0.0')
        self.launches.append((str(app), ready))
        self.marker()
        return self.process

    def assert_old(self):
        self.assertEqual(release.bundle_snapshot(self.destination), self.startup)
        self.assertEqual(self.verify(self.destination), '1.0.0')

    def journal_state(self):
        return private_read(helper._Transaction(self.plan).journal)['state']

    def test_capabilities_without_plan(self):
        with redirect_stdout(io.StringIO()) as output:
            helper.main(['--capabilities'])
        self.assertEqual(json.loads(output.getvalue()), {'protocol': 2, 'normalQuit': 1})
        helper.extract_verified.assert_not_called()
        helper._launch.assert_not_called()

    def test_plan_needs_no_documents_or_checkpoint(self):
        self.assertEqual(helper._load_plan(self.plan_path), self.plan)
        self.assertEqual({path.name for path in self.directory.iterdir()}, {'install-plan.json'})
        import inspect
        # 只有替换前的无界面自检可以用隔离环境运行待装副本；真正启动新版时不得改环境。
        source = Path(helper.__file__).read_text().replace(inspect.getsource(self.real_selfcheck), '')
        self.assertNotIn('_selfcheck(', inspect.getsource(self.real_launch))
        for forbidden in ('CheckpointStore', '_check_checkpoint', '_recover', 'update_checkpoint',
                          'workspaceRestored', 'restore-result', 'active.json', '--update-paused',
                          'MDPREVIEW_DISABLE_UPDATES'):
            self.assertNotIn(forbidden, source)

    def test_plain_quit_commit_installs_without_any_launch(self):
        self.assertTrue(helper.run_plan(self.plan_path))
        self.assertEqual(self.verify(self.destination), '2.0.0')
        self.assertLess(self.events.index('signature'), self.events.index('armed-before-exit'))
        self.assertEqual(self.journal_state(), 'ready')
        self.assertEqual(private_read(self.plan['log'])['state'], 'ready-no-relaunch')
        self.assertEqual(self.launches, [])
        self.assertFalse(Path(self.plan['ready']).exists())
        helper._same_bundle(helper._Transaction(self.plan).previous, self.startup)

    def test_explicit_relaunch_needs_only_application_ready(self):
        self.relaunch = True
        self.assertTrue(helper.run_plan(self.plan_path))
        self.assertEqual(self.launches, [(str(self.destination), self.plan['ready'])])
        self.assertEqual(self.process.actions, [])
        self.assertEqual(self.journal_state(), 'ready')
        self.assertFalse((self.directory / 'checkpoint.json').exists())

    def test_second_runtime_instance_prevents_install_without_forced_exit(self):
        with helper.RuntimeLease(self.destination):
            with self.assertRaises(BlockingIOError):
                helper.run_plan(self.plan_path)
        self.assert_old()
        self.assertEqual(self.journal_state(), 'cancelled')
        self.assertEqual(self.launches, [])

    def test_another_new_instance_prevents_rollback(self):
        self.relaunch = True
        leases = []
        def ready_failure(*args):
            leases.append(helper.RuntimeLease(self.destination))
            raise TimeoutError('ready-timeout')
        try:
            with mock.patch.object(helper, '_wait_ready', side_effect=ready_failure):
                with self.assertRaises(TimeoutError):
                    helper.run_plan(self.plan_path)
            self.assertEqual(self.verify(self.destination), '2.0.0')
            self.assertEqual(self.journal_state(), 'recovery-required')
            helper._same_bundle(helper._Transaction(self.plan).previous, self.startup)
        finally:
            for lease in leases:
                lease.close()

    def test_insufficient_space_fails_before_arming_or_replacement(self):
        with mock.patch.object(helper.shutil, 'disk_usage', return_value=mock.Mock(free=0)):
            with self.assertRaises(OSError) as caught:
                helper.run_plan(self.plan_path)
        self.assertEqual(caught.exception.errno, 28)
        self.assert_old()
        self.assertNotIn('armed-before-exit', self.events)
        self.assertEqual(self.journal_state(), 'cancelled')

    def test_target_without_runtime_protocol_is_rejected(self):
        (self.source / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString': '2.0.0'}))
        with self.assertRaisesRegex(ValueError, 'target-runtime-lease-unsupported'):
            helper.run_plan(self.plan_path)
        self.assert_old()
        self.assertNotIn('armed-before-exit', self.events)

    def test_terminal_retention_keeps_current_and_one_older_and_unknown_evidence(self):
        transaction = helper._Transaction(self.plan)
        transaction.acquire()
        try:
            transaction.record('cancelled')
            for index in range(5):
                directory = transaction.root / (str(index) * 32)
                value = dict(private_read(transaction.journal), nonce=directory.name)
                for key in ('previous', 'prepared', 'rejected'):
                    value[key] = str(directory / (key + '.app'))
                private_write(directory / 'terminal.json', value)
                (directory / 'payload').write_bytes(b'retired')
            unknown = transaction.root / ('f' * 32)
            unknown.mkdir(mode=0o700)
            (unknown / 'evidence').write_bytes(b'preserved')
            for _ in range(3):
                transaction.collect()
            terminals = list(transaction.root.glob('*/terminal.json'))
            self.assertEqual(len(terminals), 2)
            self.assertEqual((unknown / 'evidence').read_bytes(), b'preserved')
        finally:
            transaction.close()

    def test_exit_without_commit_never_installs_or_launches(self):
        helper.time.sleep.side_effect = lambda _: setattr(self, 'parent_alive', False)
        with self.assertRaisesRegex(RuntimeError, 'without-commit'):
            helper.run_plan(self.plan_path)
        self.assert_old()
        self.assertEqual(self.launches, [])
        self.assertEqual(self.journal_state(), 'cancelled')

    def test_abort_wins_over_commit_even_after_exit(self):
        self.relaunch = True
        def abort(_):
            self.commit()
            private_write(self.plan['abort'], {'nonce': self.nonce})
            self.parent_alive = False
        helper.time.sleep.side_effect = abort
        with self.assertRaisesRegex(RuntimeError, 'aborted'):
            helper.run_plan(self.plan_path)
        self.assert_old()
        self.assertEqual(self.launches, [])

    def test_null_abort_also_cancels(self):
        private_write(self.plan['abort'], None)
        with self.assertRaisesRegex(RuntimeError, 'aborted'):
            helper._check_abort(self.plan)

    def test_commit_while_parent_alive_does_not_install(self):
        turns = []
        def wait(_):
            self.assert_old()
            self.assertEqual(self.launches, [])
            self.commit()
            turns.append(True)
            if len(turns) == 3:
                self.parent_alive = False
        helper.time.sleep.side_effect = wait
        self.assertTrue(helper.run_plan(self.plan_path))
        self.assertEqual(len(turns), 3)

    def test_prepared_wait_has_no_two_minute_or_multiday_deadline(self):
        parent = mock.Mock()
        parent.gone.side_effect = [False, False, True]
        commit = dict(nonce=self.nonce, pid=self.plan['pid'], success=True, relaunch=False)
        with mock.patch.object(helper, '_committed', return_value=commit), \
                mock.patch.object(helper.time, 'sleep') as sleep, \
                mock.patch.object(helper.time, 'monotonic', side_effect=[0, 121, 7 * 86400]) as clock:
            self.assertEqual(helper._wait_commit_exit(self.plan, parent), commit)
        self.assertEqual(sleep.call_count, 2)
        clock.assert_not_called()

    def test_commit_written_between_read_and_exit_is_reread(self):
        parent = mock.Mock()
        def gone():
            self.commit()
            return True
        parent.gone.side_effect = gone
        self.assertFalse(helper._wait_commit_exit(self.plan, parent)['relaunch'])

    def test_commit_payload_strictly_binds_nonce_pid_and_relaunch(self):
        good = dict(nonce=self.nonce, pid=self.plan['pid'], success=True, relaunch=False)
        invalid = [None, {}, {key: value for key, value in good.items() if key != 'relaunch'}]
        invalid += [dict(good, **change) for change in (
            {'nonce': '0' * 32}, {'pid': True}, {'pid': 1}, {'success': 1},
            {'relaunch': 1}, {'relaunch': None}, {'checkpoint': 'obsolete'})]
        for value in invalid:
            with self.subTest(value=value):
                private_write(self.plan['commit'], value)
                with self.assertRaisesRegex(ValueError, 'commit-invalid'):
                    helper._committed(self.plan)

    def test_plan_rejects_old_extra_and_missing_fields(self):
        invalid = [dict(self.plan, checkpoint='obsolete'), dict(self.plan, opportunistic=True),
                   dict(self.plan, protocol=1), dict(self.plan, normalQuit=True),
                   {key: value for key, value in self.plan.items() if key != 'normalQuit'}]
        for plan in invalid:
            with self.subTest(plan=plan):
                private_write(self.plan_path, plan)
                with self.assertRaisesRegex(ValueError, 'plan-invalid'):
                    helper._load_plan(self.plan_path)

    def test_plan_rejects_each_marker_outside_nonce_directory(self):
        for key in ('ready', 'armed', 'commit', 'abort', 'log'):
            with self.subTest(key=key):
                private_write(self.plan_path, dict(self.plan, **{key: str(self.root / 'outside.json')}))
                with self.assertRaisesRegex(ValueError, 'marker-location'):
                    helper._load_plan(self.plan_path)

    def test_plan_rejects_wrong_private_root(self):
        wrong = self.root / 'other/install' / self.nonce / 'install-plan.json'
        private_write(wrong, self.plan)
        with self.assertRaisesRegex(ValueError, 'plan-location'):
            helper._load_plan(wrong)

    def test_plan_rejects_invalid_pid_identity_paths_and_team(self):
        invalid = [dict(self.plan, pid=True), dict(self.plan, teamId=123),
                   dict(self.plan, archive=str(self.root / '../release.zip')),
                   dict(self.plan, version='bad'), dict(self.plan, staging='relative.app')]
        for field in ('startupIdentity', 'destinationIdentity'):
            plan = copy.deepcopy(self.plan)
            plan[field]['inode'] = True
            invalid.append(plan)
        for plan in invalid:
            with self.subTest(plan=plan):
                private_write(self.plan_path, plan)
                with self.assertRaises(ValueError):
                    helper._load_plan(self.plan_path)

    def test_plan_file_symlink_is_rejected(self):
        original = self.plan_path.with_name('original.json')
        self.plan_path.rename(original)
        self.plan_path.symlink_to(original)
        with self.assertRaises((ValueError, OSError)):
            helper._load_plan(self.plan_path)

    def test_nonce_directory_symlink_is_rejected(self):
        original = self.directory.with_name('original')
        self.directory.rename(original)
        self.directory.symlink_to(original, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)):
            helper._load_plan(self.plan_path)

    def test_preexisting_marker_symlink_never_touches_target(self):
        victim = self.root / 'victim.json'
        victim.write_bytes(b'untouched')
        Path(self.plan['ready']).symlink_to(victim)
        with self.assertRaisesRegex(ValueError, 'marker-already-exists'):
            helper.run_plan(self.plan_path)
        self.assertEqual(victim.read_bytes(), b'untouched')
        self.assert_old()
        self.assertEqual(self.launches, [])

    def test_preexisting_commit_is_rejected(self):
        self.commit()
        with self.assertRaisesRegex(ValueError, 'marker-already-exists'):
            helper.run_plan(self.plan_path)
        self.assert_old()
        self.assertEqual(self.launches, [])

    def test_ready_requires_matching_live_child_and_no_workspace_ack(self):
        for change in ({'pid': True}, {'pid': 2}, {'version': '1.0.0'}, {'success': False}, {'success': 1}):
            with self.subTest(change=change):
                self.marker(**change)
                with self.assertRaisesRegex(RuntimeError, 'ready-mismatch'):
                    helper._wait_ready(self.plan, self.process)
        self.marker()
        helper._wait_ready(self.plan, self.process)

    def test_legacy_ready_accepts_only_pid_and_version(self):
        private_write(self.plan['ready'], dict(pid=self.process.pid, version='2.0.0'))
        helper._wait_ready(self.plan, self.process)
        private_write(self.plan['ready'], dict(pid=self.process.pid, version='2.0.0', unexpected=True))
        with self.assertRaisesRegex(RuntimeError, 'ready-mismatch'):
            helper._wait_ready(self.plan, self.process)

    def test_ready_cannot_ack_exited_process(self):
        self.marker()
        self.process.returncode = 1
        with self.assertRaisesRegex(RuntimeError, 'process-exited'):
            helper._wait_ready(self.plan, self.process)

    def test_ready_cannot_follow_symlink_or_public_file(self):
        victim = self.root / 'victim.json'
        private_write(victim, dict(pid=self.process.pid, version='2.0.0', success=True))
        Path(self.plan['ready']).symlink_to(victim)
        with self.assertRaises((ValueError, OSError)):
            helper._wait_ready(self.plan, self.process)
        self.assertTrue(Path(self.plan['ready']).is_symlink())
        self.assertEqual(private_read(victim), dict(pid=self.process.pid, version='2.0.0', success=True))
        self.plan['ready'] = str(self.directory / 'public-ready.json')
        self.marker()
        Path(self.plan['ready']).chmod(0o644)
        with self.assertRaises(ValueError):
            helper._wait_ready(self.plan, self.process)

    def test_ready_timeout_is_not_parent_wait_timeout(self):
        with mock.patch.object(helper.time, 'monotonic', side_effect=[0, 0, 31]), \
                mock.patch.object(helper.time, 'sleep'):
            with self.assertRaisesRegex(TimeoutError, 'application-ready-timeout'):
                helper._wait_ready(self.plan, self.process)

    def test_launch_only_passes_ready_and_inherits_external_environment(self):
        with mock.patch.dict(os.environ, {'MDPREVIEW_DISABLE_UPDATES': 'external-value'}), \
                mock.patch.object(subprocess, 'Popen', return_value=self.process) as popen:
            self.assertIs(self.real_launch(self.destination, self.plan['ready']), self.process)
            self.assertEqual(os.environ['MDPREVIEW_DISABLE_UPDATES'], 'external-value')
        self.assertEqual(popen.call_args.args[0],
                         [str(self.destination / 'Contents/MacOS/mdPreview'), '--update-ready', self.plan['ready']])
        self.assertNotIn('env', popen.call_args.kwargs)
        self.assertTrue(popen.call_args.kwargs['start_new_session'])

    def test_signature_failure_never_launches_even_if_parent_exits(self):
        def fail(*args):
            self.parent_alive = False
            raise ValueError('bad-signature')
        helper.extract_verified.side_effect = fail
        with self.assertRaisesRegex(ValueError, 'bad-signature'):
            helper.run_plan(self.plan_path)
        self.assert_old()
        self.assertEqual(self.launches, [])

    def test_prepared_copy_is_selfchecked_before_arming(self):
        self.assertTrue(helper.run_plan(self.plan_path))
        self.assertLess(self.events.index(('selfcheck', 'prepared.app')), self.events.index('armed-before-exit'))

    def test_selfcheck_failure_never_arms_or_replaces(self):
        with mock.patch.object(helper, '_selfcheck', side_effect=RuntimeError('prepared-application-selfcheck-failed')):
            with self.assertRaises(RuntimeError):
                helper.run_plan(self.plan_path)
        self.assertTrue(self.parent_alive)
        self.assertFalse(private_read(self.plan['armed'])['success'])
        self.assert_old()
        self.assertEqual(self.journal_state(), 'cancelled')
        self.assertEqual(self.launches, [])

    def test_selfcheck_runs_prepared_binary_isolated_and_cleans_up(self):
        calls = []

        def run(command, **options):
            calls.append((command, options))
            if self.selfcheck_result == 0:
                Path(command[3]).write_text('x' * 200)
            return subprocess.CompletedProcess(command, self.selfcheck_result)
        app = self.root / 'candidate.app'
        with mock.patch.dict(os.environ, {'MDPREVIEW_SECRET_FLAG': '1'}), \
                mock.patch.object(subprocess, 'run', side_effect=run):
            self.selfcheck_result = 0
            self.real_selfcheck(app, self.root)
            command, options = calls[0]
            self.assertEqual(command[:2], [str(app / 'Contents/MacOS/mdPreview'), '--headless-export'])
            self.assertEqual(command[4], 'html')
            self.assertNotIn('MDPREVIEW_SECRET_FLAG', options['env'])
            self.assertEqual(options['env']['MDPREVIEW_DISABLE_UPDATES'], '1')
            self.assertTrue(Path(options['env']['MDPREVIEW_DATA_DIR']).is_relative_to(self.root / 'selfcheck'))
            self.assertFalse((self.root / 'selfcheck').exists())
            self.selfcheck_result = 2
            with self.assertRaisesRegex(RuntimeError, 'selfcheck-failed'):
                self.real_selfcheck(app, self.root)
            self.assertFalse((self.root / 'selfcheck').exists())
        with mock.patch.object(subprocess, 'run', side_effect=subprocess.TimeoutExpired('x', 1)):
            with self.assertRaisesRegex(RuntimeError, 'selfcheck-timeout'):
                self.real_selfcheck(app, self.root)

    def test_prepare_failure_keeps_parent_and_old_app(self):
        with mock.patch.object(helper, '_sync_tree', side_effect=OSError('disk-full')):
            with self.assertRaises(OSError):
                helper.run_plan(self.plan_path)
        self.assertTrue(self.parent_alive)
        self.assertFalse(private_read(self.plan['armed'])['success'])
        self.assert_old()
        self.assertEqual(self.launches, [])

    def test_parent_dies_before_armed_never_installs(self):
        def extract(*args):
            staged = self.extract(*args)
            self.parent_alive = False
            return staged
        helper.extract_verified.side_effect = extract
        with self.assertRaisesRegex(RuntimeError, 'before-armed'):
            helper.run_plan(self.plan_path)
        self.assert_old()
        self.assertEqual(self.launches, [])

    def test_failure_after_exchange_rolls_back_without_missing_destination(self):
        sync = helper._sync_directory
        failed = False
        def fail(path):
            nonlocal failed
            if Path(path) == self.destination.parent and self.verify(self.destination) == '2.0.0' and not failed:
                failed = True
                raise OSError('sync-new-failed')
            return sync(path)
        with mock.patch.object(helper, '_sync_directory', side_effect=fail):
            with self.assertRaisesRegex(OSError, 'sync-new-failed'):
                helper.run_plan(self.plan_path)
        self.assert_old()
        self.assertEqual(self.launches, [])
        self.assertEqual(self.journal_state(), 'rolled-back')

    def test_launch_failure_rolls_back_without_reopening_old(self):
        self.relaunch = True
        helper._launch.side_effect = OSError('exec-failed')
        with self.assertRaisesRegex(OSError, 'exec-failed'):
            helper.run_plan(self.plan_path)
        helper._launch.assert_called_once()
        self.assert_old()
        self.assertEqual(self.journal_state(), 'rolled-back')

    def test_failed_ready_waits_for_natural_exit_then_rolls_back(self):
        self.relaunch = True
        with mock.patch.object(helper, '_wait_ready', side_effect=RuntimeError('ready-failed')):
            with self.assertRaisesRegex(RuntimeError, 'ready-failed'):
                helper.run_plan(self.plan_path)
        self.assertEqual(self.process.actions, [('wait', 5)])
        self.assert_old()
        self.assertEqual(len(self.launches), 1)
        self.assertTrue(helper._Transaction(self.plan).rejected.is_dir())
        self.assertEqual(self.journal_state(), 'rolled-back')

    def test_live_child_is_never_killed_or_rolled_back(self):
        self.relaunch = True
        self.process.exits_on_wait = False
        with mock.patch.object(helper, '_wait_ready', side_effect=RuntimeError('ready-failed')):
            with self.assertRaisesRegex(RuntimeError, 'ready-failed'):
                helper.run_plan(self.plan_path)
        self.assertEqual(self.process.actions, [('wait', 5)])
        self.assertEqual(self.verify(self.destination), '2.0.0')
        helper._same_bundle(helper._Transaction(self.plan).previous, self.startup)
        self.assertEqual(self.journal_state(), 'recovery-required')
        self.assertEqual(len(self.launches), 1)
        self.assertTrue(self.source.is_dir())
        self.assertTrue(Path(self.plan['archive']).is_file())

    def test_foreign_destination_is_not_overwritten_on_rollback(self):
        self.relaunch = True
        def fail(*args):
            helper._rename_exclusive(self.destination, self.root / 'moved-new.app')
            self.make_bundle(self.destination, '9.0.0')
            raise RuntimeError('destination-changed')
        with mock.patch.object(helper, '_wait_ready', side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, 'destination-changed'):
                helper.run_plan(self.plan_path)
        self.assertEqual(self.verify(self.destination), '9.0.0')
        helper._same_bundle(helper._Transaction(self.plan).previous, self.startup)
        self.assertEqual(self.journal_state(), 'recovery-required')
        self.assertEqual(len(self.launches), 1)

    def test_journal_failure_after_launch_preserves_live_app(self):
        self.relaunch = True
        self.process.exits_on_wait = False
        write = helper.private_write
        def fail(path, value):
            if Path(path).name == 'journal.json' and value['state'] == 'ready':
                raise OSError('journal-failed')
            return write(path, value)
        with mock.patch.object(helper, 'private_write', side_effect=fail):
            with self.assertRaisesRegex(OSError, 'journal-failed'):
                helper.run_plan(self.plan_path)
        self.assertEqual(self.verify(self.destination), '2.0.0')
        helper._same_bundle(helper._Transaction(self.plan).previous, self.startup)
        self.assertEqual(self.journal_state(), 'recovery-required')

    def test_lock_blocks_second_helper_without_touching_receipt(self):
        transaction = helper._Transaction(self.plan)
        transaction.acquire()
        self.addCleanup(transaction.close)
        marker = dict(nonce=self.nonce, pid=12345, success=True)
        private_write(self.plan['armed'], marker)
        with self.assertRaises(BlockingIOError):
            helper.run_plan(self.plan_path)
        self.assertEqual(private_read(self.plan['armed']), marker)
        helper.extract_verified.assert_not_called()
        self.assert_old()

    def test_interrupted_journal_is_not_replayed(self):
        transaction = helper._Transaction(self.plan)
        self.addCleanup(transaction.close)
        transaction.acquire()
        transaction.prepare(self.source)
        transaction.record('moving-old')
        transaction.close()
        before = transaction.journal.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'requires-review'):
            helper.run_plan(self.plan_path)
        self.assertEqual(transaction.journal.read_bytes(), before)
        helper.extract_verified.assert_not_called()
        self.assertEqual(self.launches, [])

    def test_exclusive_rename_does_not_overwrite_destination(self):
        first, second = self.root / 'first', self.root / 'second'
        first.mkdir()
        second.mkdir()
        with self.assertRaises(OSError):
            helper._rename_exclusive(first, second)
        self.assertTrue(first.is_dir())
        self.assertTrue(second.is_dir())

    def test_parent_pid_reuse_cannot_authorize_install(self):
        def reuse(_):
            self.commit()
            self.parent_identity = (*self.parent_identity[:2], 999, 0, self.parent_identity[-1])
        helper.time.sleep.side_effect = reuse
        with self.assertRaisesRegex(RuntimeError, 'identity-changed'):
            helper.run_plan(self.plan_path)
        self.assert_old()
        self.assertEqual(self.launches, [])

    def test_parent_must_be_actual_current_application(self):
        with self.assertRaisesRegex(ValueError, 'parent-mismatch'):
            helper._Parent(dict(self.plan, pid=self.plan['pid'] + 1))
        self.parent_identity = (*self.parent_identity[:-1], str(self.source / 'Contents/MacOS/mdPreview'))
        with self.assertRaisesRegex(ValueError, 'executable-mismatch'):
            helper._Parent(self.plan)


if __name__ == '__main__':
    unittest.main(verbosity=2)
