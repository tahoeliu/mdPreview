"""独立安装助手：后台准备，普通退出提交后替换，不保存或恢复文档。"""
import argparse
import ctypes
import errno
import fcntl
import hashlib
import json
import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

from mdpreview_core.release import (bundle_snapshot, check_installation_identity,
                                    check_startup_snapshot, verify_bundle, version_tuple)
from mdpreview_core.release_zip import extract_verified
from mdpreview_core.update_storage import private_directory, private_read, private_write
from mdpreview_core.update_runtime import RuntimeLease


class _BSDInfo(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in (
        'flags', 'status', 'xstatus', 'pid', 'ppid', 'uid', 'gid', 'ruid', 'rgid',
        'svuid', 'svgid', 'reserved')]
    _fields_ += [('comm', ctypes.c_char * 16), ('name', ctypes.c_char * 32)]
    _fields_ += [(name, ctypes.c_uint32) for name in ('nfiles', 'pgid', 'jobc', 'tdev', 'tpgid')]
    _fields_ += [('nice', ctypes.c_int32), ('start_sec', ctypes.c_uint64), ('start_usec', ctypes.c_uint64)]


def _process_identity(pid):
    """libproc 提供微秒启动身份；不把 kill(pid, 0) 当作原进程身份证明。"""
    if sys.platform != 'darwin':
        raise RuntimeError('process-identity-platform-unsupported')
    lib = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
    lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    lib.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]

    def info():
        value = _BSDInfo()
        ctypes.set_errno(0)
        count = lib.proc_pidinfo(pid, 3, 0, ctypes.byref(value), ctypes.sizeof(value))
        if count != ctypes.sizeof(value):
            if ctypes.get_errno() == errno.ESRCH:
                return None
            # libproc 有时在进程退出后不设置 errno；只有 ESRCH 才能确认退出。
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return None
            raise RuntimeError('process-identity-unavailable')
        return value

    before = info()
    if before is None:
        return None
    path = ctypes.create_string_buffer(4096)
    if lib.proc_pidpath(pid, path, len(path)) <= 0:
        if info() is None:
            return None
        raise RuntimeError('process-executable-unavailable')
    after = info()
    if after is None:
        return None
    identity = lambda value: (value.pid, value.uid, value.start_sec, value.start_usec)
    if identity(before) != identity(after):
        raise RuntimeError('process-identity-changed')
    return (*identity(after), os.fsdecode(path.value))


class _Parent:
    def __init__(self, plan):
        self.pid = plan['pid']
        if self.pid != os.getppid():
            raise ValueError('helper-parent-mismatch')
        self.identity = _process_identity(self.pid)
        executable = Path(plan['destination']) / 'Contents/MacOS/mdPreview'
        if (self.identity is None or self.identity[1] != os.getuid()
                or self.identity[-1] != str(executable)):
            raise ValueError('parent-executable-mismatch')
        binary = executable.stat()
        expected = plan['startupIdentity']
        if (binary.st_dev, binary.st_ino) != (expected['executableDevice'], expected['executableInode']):
            raise ValueError('parent-executable-changed')
        self.exited = False

    def gone(self):
        if self.exited:
            return True
        current = _process_identity(self.pid)
        if current is None:
            self.exited = True
        elif current != self.identity:
            # PID 复用或 exec 均不授权替换，也不对该 PID 发信号。
            raise RuntimeError('parent-process-identity-changed')
        return self.exited


class _LegacyParent:
    """旧版客户端在退出确认完成后才启动助手，随后立刻退出；助手启动时它可能已经不在。

    旧版没有 commit 回执：其授权就是“已确认退出并启动了助手”。这里只等待该进程退出，
    PID 已被其他程序复用时视为已退出，绝不向它发信号。
    """
    def __init__(self, plan):
        self.pid = plan['pid']
        self.executable = str(Path(plan['destination']) / 'Contents/MacOS/mdPreview')
        self.exited = False

    def gone(self):
        if not self.exited:
            current = _process_identity(self.pid)
            self.exited = current is None or current[1] != os.getuid() or current[-1] != self.executable
        return self.exited

    def wait(self, timeout=120):
        deadline = time.monotonic() + timeout
        while not self.gone():
            if time.monotonic() >= deadline:
                raise TimeoutError('legacy-parent-exit-timeout')
            time.sleep(0.2)


def _load_plan(path):
    path = Path(os.path.abspath(path))
    plan = private_read(path, 1024 * 1024)
    fields = {'protocol', 'normalQuit', 'transactionNonce', 'pid', 'destination',
              'startupIdentity', 'destinationIdentity', 'archive', 'manifest', 'signature',
              'staging', 'version', 'teamId', 'ready', 'armed', 'commit', 'abort', 'log'}
    if (not isinstance(plan, dict) or set(plan) != fields
            or type(plan['protocol']) is not int or plan['protocol'] != 2
            or type(plan['normalQuit']) is not int or plan['normalQuit'] != 1):
        raise ValueError('install-plan-invalid')
    nonce = plan.get('transactionNonce')
    if not isinstance(nonce, str) or not re.fullmatch(r'[a-f0-9]{32}', nonce):
        raise ValueError('install-nonce-invalid')
    support = (Path(os.path.realpath(os.environ['MDPREVIEW_DATA_DIR']))
               if os.environ.get('MDPREVIEW_DATA_DIR')
               else Path.home() / 'Library/Application Support/mdPreview')
    directory = support / 'UpdateTransactions' / 'install' / nonce
    if path != directory / 'install-plan.json':
        raise ValueError('install-plan-location-invalid')
    for field, name in (('ready', 'ready.json'),
                        ('armed', 'armed.json'), ('commit', 'commit.json'),
                        ('abort', 'abort.json'), ('log', 'install.log')):
        if plan.get(field) != str(path.parent / name):
            raise ValueError('install-marker-location-invalid')
    if type(plan.get('pid')) is not int or plan['pid'] <= 1 or plan['pid'] == os.getpid():
        raise ValueError('install-parent-invalid')
    version_tuple(plan.get('version'))
    if plan['teamId'] is not None and (not isinstance(plan['teamId'], str)
                                       or not re.fullmatch(r'[A-Z0-9]{10}', plan['teamId'])):
        raise ValueError('install-publisher-invalid')
    startup, destination = plan.get('startupIdentity'), plan.get('destinationIdentity')
    if (not isinstance(startup, dict) or not isinstance(destination, dict)
            or set(startup) != {'path', 'device', 'inode', 'parentDevice', 'parentInode',
                                'executableDevice', 'executableInode'}
            or set(destination) != set(startup) | {'version'}
            or any(type(startup[key]) is not int or startup[key] < 0 for key in startup if key != 'path')
            or any(type(destination[key]) is not type(value) or destination[key] != value
                   for key, value in startup.items())
            or plan.get('destination') != startup['path']):
        raise ValueError('startup-plan-identity-mismatch')
    version_tuple(destination.get('version'))
    for key in ('destination', 'staging', 'archive', 'manifest', 'signature'):
        value = plan.get(key)
        if (not isinstance(value, str) or not Path(value).is_absolute()
                or str(Path(value)) != value or os.path.abspath(value) != value or '\x00' in value):
            raise ValueError('install-path-invalid')
    return plan


def _optional(path):
    try:
        return private_read(path, 1024 * 1024)
    except FileNotFoundError:
        return None


def _check_abort(plan):
    try:
        private_read(plan['abort'], 1024 * 1024)
    except FileNotFoundError:
        return
    raise RuntimeError('installation-aborted')


def _committed(plan):
    try:
        value = private_read(plan['commit'], 1024 * 1024)
    except FileNotFoundError:
        return False
    if (not isinstance(value, dict) or set(value) != {'nonce', 'pid', 'success', 'relaunch'}
            or value.get('nonce') != plan['transactionNonce']
            or value.get('success') is not True or type(value.get('pid')) is not int
            or value['pid'] != plan['pid'] or type(value.get('relaunch')) is not bool):
        raise ValueError('installation-commit-invalid')
    return value


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _sync_tree(path):
    for root, directories, files in os.walk(path, followlinks=False, topdown=False):
        for name in files:
            file = Path(root) / name
            if file.is_symlink():
                continue
            fd = os.open(file, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise ValueError('prepared-file-invalid')
                os.fsync(fd)
            finally:
                os.close(fd)
        _sync_directory(root)


def _rename_exclusive(source, destination):
    """同卷不覆盖改名；未知平台拒绝，不降级为可能覆盖第三方目录的 replace。"""
    lib = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'darwin':
        rename = lib.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        result = rename(os.fsencode(source), os.fsencode(destination), 4)  # RENAME_EXCL
    elif sys.platform.startswith('linux') and hasattr(lib, 'renameat2'):
        rename = lib.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
    else:
        raise RuntimeError('exclusive-rename-unsupported')
    if result != 0:
        raise OSError(ctypes.get_errno(), 'exclusive-rename-failed')


def _exchange(source, destination):
    """Both names remain present even if the helper dies immediately after the syscall."""
    lib = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'darwin':
        rename = lib.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        result = rename(os.fsencode(source), os.fsencode(destination), 2)  # RENAME_SWAP
    elif sys.platform.startswith('linux') and hasattr(lib, 'renameat2'):
        rename = lib.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = rename(-100, os.fsencode(source), -100, os.fsencode(destination), 2)
    else:
        raise RuntimeError('atomic-exchange-unsupported')
    if result != 0:
        raise OSError(ctypes.get_errno(), 'atomic-exchange-failed')


def _same_bundle(path, expected):
    current = bundle_snapshot(path)
    if any(current[key] != expected[key] for key in ('device', 'inode', 'executableDevice', 'executableInode')):
        raise ValueError('transaction-bundle-identity-changed')


def _cancel_unreplaced_transaction(journal_path, saved, startup, lock, root_identity,
                                  team_id=None, nonce=None):
    """只结算可证明未替换的遗留事务；调用方持原锁，不重放安装或提交。"""
    journal_path = Path(journal_path)
    destination = Path(startup['path'])
    root = destination.parent / ('.mdPreview-install-' + hashlib.sha256(destination.name.encode()).hexdigest()[:16])
    fields = {'schema', 'nonce', 'state', 'destination', 'previous', 'prepared',
              'rejected', 'oldIdentity', 'newIdentity'}
    if (not isinstance(saved, dict) or set(saved) != fields
            or type(saved['schema']) is not int or saved['schema'] != 1
            or not isinstance(saved['nonce'], str) or not re.fullmatch(r'[a-f0-9]{32}', saved['nonce'])
            or (nonce is not None and saved['nonce'] != nonce)
            or saved['state'] not in ('preparing', 'prepared', 'armed', 'exchanging')
            or saved['destination'] != str(destination) or journal_path != root / 'journal.json'
            or any(saved[key] != str(root / saved['nonce'] / name)
                   for key, name in (('previous', 'previous.app'), ('prepared', 'prepared.app'),
                                     ('rejected', 'rejected.app')))):
        raise ValueError('interrupted-journal-invalid')
    keys = {'path', 'device', 'inode', 'parentDevice', 'parentInode',
            'executableDevice', 'executableInode', 'version'}
    old, new = saved['oldIdentity'], saved['newIdentity']
    for value in ((old,) if new is None and saved['state'] == 'preparing' else (old, new)):
        if (not isinstance(value, dict) or set(value) != keys
                or any(type(value[key]) is not int or value[key] < 0 for key in keys - {'path', 'version'})):
            raise ValueError('transaction-identity-invalid')
        version_tuple(value['version'])
    if (not isinstance(old, dict) or {key: old[key] for key in keys - {'version'}} != startup
            or (new is not None and new['path'] != saved['prepared'])):
        raise ValueError('transaction-identity-mismatch')
    transaction_directory = root / saved['nonce']
    with private_directory(root) as directory, private_directory(transaction_directory) as transaction:
        directory_info = os.fstat(transaction)
        transaction_identity = (directory_info.st_dev, directory_info.st_ino)
        journal_info = os.stat('journal.json', dir_fd=directory, follow_symlinks=False)
        if new is not None and (new['parentDevice'], new['parentInode']) != transaction_identity:
            raise ValueError('transaction-directory-changed')

        def check(expected):
            for path, identity in ((root, root_identity), (transaction_directory, transaction_identity)):
                with private_directory(path) as current_fd:
                    current = os.fstat(current_fd)
                    if (current.st_dev, current.st_ino) != identity:
                        raise ValueError('transaction-directory-changed')
            opened = os.fstat(directory)
            locked = os.fstat(lock)
            named = os.stat('lock', dir_fd=directory, follow_symlinks=False)
            if ((opened.st_dev, opened.st_ino) != root_identity
                    or not stat.S_ISREG(locked.st_mode) or locked.st_uid != os.getuid()
                    or locked.st_nlink != 1 or stat.S_IMODE(locked.st_mode) & 0o077
                    or (locked.st_dev, locked.st_ino) != (named.st_dev, named.st_ino)):
                raise ValueError('transaction-lock-changed')
            # 只把 ENOENT 当作不存在；悬空链接、权限错误及其他目录项一律拒绝。
            for name in ('previous.app', 'rejected.app'):
                try:
                    os.stat(name, dir_fd=transaction, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                raise ValueError('interrupted-transaction-has-backup')
            check_startup_snapshot(destination, startup)
            if private_read(journal_path) != expected:
                raise ValueError('transaction-journal-changed')

        check(saved)
        if verify_bundle(destination, team_id, old['version']) != old['version']:
            raise ValueError('running-version-mismatch')
        # 固定原目录 fd 写入，避免签名验证期间目录置换将结算写到别处。
        cancelled = dict(saved, state='cancelled')
        temporary = '.cancel-' + os.urandom(16).hex()
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(json.dumps(cancelled, allow_nan=False, separators=(',', ':')).encode('utf-8'))
                stream.flush()
                os.fsync(stream.fileno())
            check(saved)
            current = os.stat('journal.json', dir_fd=directory, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (journal_info.st_dev, journal_info.st_ino):
                raise ValueError('transaction-journal-changed')
            os.replace(temporary, 'journal.json', src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
            check(cancelled)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
    return cancelled


def _settle_exchanged_transaction(journal_path, saved, status, startup, lock, root_identity):
    """Persist a verified running bundle's terminal outcome under the original lock."""
    if status not in ('ready', 'rolled-back'):
        raise ValueError('invalid-settlement-state')
    journal_path = Path(journal_path)
    with private_directory(journal_path.parent) as directory:
        original = os.stat(journal_path.name, dir_fd=directory, follow_symlinks=False)

        def check():
            with private_directory(journal_path.parent) as current_fd:
                current = os.fstat(current_fd)
            named = os.stat('lock', dir_fd=directory, follow_symlinks=False)
            locked = os.fstat(lock)
            journal = os.stat(journal_path.name, dir_fd=directory, follow_symlinks=False)
            if ((current.st_dev, current.st_ino) != root_identity
                    or (named.st_dev, named.st_ino) != (locked.st_dev, locked.st_ino)
                    or locked.st_nlink != 1
                    or (journal.st_dev, journal.st_ino) != (original.st_dev, original.st_ino)
                    or private_read(journal_path) != saved):
                raise ValueError('transaction-settlement-changed')
            check_startup_snapshot(startup['path'], startup)

        check()
        temporary = '.settle-' + os.urandom(16).hex()
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(json.dumps(dict(saved, state=status), allow_nan=False).encode('utf-8'))
                stream.flush()
                os.fsync(stream.fileno())
            check()
            os.replace(temporary, journal_path.name, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass


class _Transaction:
    """锁覆盖安装、回退及启动确认；遗留事务仅可保守取消，不自动重放。"""
    def __init__(self, plan):
        self.plan = plan
        self.destination = Path(plan['destination'])
        key = hashlib.sha256(self.destination.name.encode()).hexdigest()[:16]
        self.root = self.destination.parent / ('.mdPreview-install-' + key)
        self.directory = self.root / plan['transactionNonce']
        self.prepared = self.directory / 'prepared.app'
        self.previous = self.directory / 'previous.app'
        self.rejected = self.directory / 'rejected.app'
        self.journal = self.root / 'journal.json'
        self.lock = None
        self.root_identity = None
        self.directory_identity = None
        self.owned = False
        self.new_identity = None
        self.old_moved = False
        self.new_installed = False
        self.state = 'preparing'

    def acquire(self):
        check_startup_snapshot(self.destination, self.plan['startupIdentity'])
        created_lock = False
        with private_directory(self.root, create=True) as directory:
            try:
                fd = os.open('lock', os.O_RDWR | os.O_NOFOLLOW, dir_fd=directory)
            except FileNotFoundError:
                try:
                    os.stat('journal.json', dir_fd=directory, follow_symlinks=False)
                except FileNotFoundError:
                    fd = os.open('lock', os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=directory)
                    created_lock = True
                else:
                    raise ValueError('interrupted-install-lock-missing')
            try:
                info = os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077):
                    raise ValueError('install-lock-invalid')
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                named = os.stat('lock', dir_fd=directory, follow_symlinks=False)
                current = os.fstat(directory)
                with private_directory(self.root) as current_fd:
                    root = os.fstat(current_fd)
                if ((info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)
                        or (root.st_dev, root.st_ino) != (current.st_dev, current.st_ino)):
                    raise ValueError('transaction-lock-changed')
                self.root_identity = (current.st_dev, current.st_ino)
                self.lock = fd
            except BaseException:
                os.close(fd)
                raise
        try:
            saved = private_read(self.journal)
        except FileNotFoundError:
            saved = None
        else:
            if (created_lock or not isinstance(saved, dict) or type(saved.get('schema')) is not int
                    or saved['schema'] != 1 or saved.get('destination') != str(self.destination)):
                raise RuntimeError('interrupted-install-requires-review')
            if saved.get('state') in ('preparing', 'prepared', 'armed'):
                _cancel_unreplaced_transaction(self.journal, saved, self.plan['startupIdentity'],
                                              self.lock, self.root_identity, self.plan['teamId'])
                # 本次只取消旧事务；由调用方已有的有界重试另建计划。
                raise RuntimeError('interrupted-install-cancelled')
            if saved.get('state') not in ('ready', 'rolled-back', 'cancelled'):
                raise RuntimeError('interrupted-install-requires-review')
        self.directory.mkdir(mode=0o700)
        current = self.directory.stat()
        self.directory_identity = (current.st_dev, current.st_ino)
        _sync_directory(self.root)
        self.owned = True
        self.record('preparing')

    def record(self, state):
        self.check_parent_directory()
        self.state = state
        value = {'schema': 1, 'nonce': self.plan['transactionNonce'], 'state': state,
                 'destination': str(self.destination), 'previous': str(self.previous),
                 'prepared': str(self.prepared), 'rejected': str(self.rejected),
                 'oldIdentity': self.plan['destinationIdentity'], 'newIdentity': self.new_identity}
        private_write(self.journal, value)

    def collect(self):
        """Keep this transaction and one older terminal backup; never collect unknown work."""
        self.check_parent_directory()
        private_write(self.directory / 'terminal.json', private_read(self.journal))
        candidates = []
        for directory in self.root.iterdir():
            if directory == self.directory or not re.fullmatch(r'[a-f0-9]{32}', directory.name):
                continue
            try:
                with private_directory(directory) as descriptor:
                    saved = private_read(directory / 'terminal.json')
                    identity = os.fstat(descriptor)
                if (not isinstance(saved, dict) or saved.get('nonce') != directory.name or saved.get('destination') != str(self.destination)
                        or saved.get('state') not in ('ready', 'rolled-back', 'cancelled')
                        or any(saved.get(key) != str(directory / name) for key, name in
                               (('previous', 'previous.app'), ('prepared', 'prepared.app'), ('rejected', 'rejected.app')))):
                    continue
                candidates.append((directory, identity))
            except (OSError, ValueError):
                continue
        for directory, identity in sorted(candidates, key=lambda item: item[1].st_mtime, reverse=True)[1:]:
            self.check_parent_directory()
            # fd-relative deletion refuses symlink substitution; changed identities are evidence.
            with private_directory(self.root) as descriptor:
                named = os.stat(directory.name, dir_fd=descriptor, follow_symlinks=False)
                if (named.st_dev, named.st_ino) != (identity.st_dev, identity.st_ino):
                    raise ValueError('cleanup-directory-changed')
                if not shutil.rmtree.avoids_symlink_attacks:
                    raise ValueError('cleanup-platform-unsupported')
                shutil.rmtree(directory.name, dir_fd=descriptor)
        extracted = self.directory / 'extracted'
        if extracted.is_dir() and not extracted.is_symlink():
            shutil.rmtree(extracted)

    def check_parent_directory(self):
        parent = self.destination.parent
        current = parent.stat()
        expected = self.plan['startupIdentity']
        if (parent.resolve() != parent or (current.st_dev, current.st_ino)
                != (expected['parentDevice'], expected['parentInode'])):
            raise ValueError('installation-parent-changed')
        for path, identity in ((self.root, self.root_identity), (self.directory, self.directory_identity)):
            with private_directory(path) as fd:
                current = os.fstat(fd)
                if (current.st_dev, current.st_ino) != identity:
                    raise ValueError('transaction-directory-changed')
        locked, named = os.fstat(self.lock), (self.root / 'lock').lstat()
        if (not stat.S_ISREG(named.st_mode) or locked.st_nlink != 1
                or (locked.st_dev, locked.st_ino) != (named.st_dev, named.st_ino)):
            raise ValueError('transaction-lock-changed')

    def prepare(self, staged):
        self.check_parent_directory()
        with (Path(staged) / 'Contents/Info.plist').open('rb') as stream:
            metadata = plistlib.load(stream)
        if type(metadata.get('MDPreviewRuntimeLease')) is not int or metadata['MDPreviewRuntimeLease'] != 1:
            raise ValueError('target-runtime-lease-unsupported')
        shutil.copytree(staged, self.prepared, symlinks=True)
        version = verify_bundle(self.prepared, self.plan['teamId'], self.plan['version'])
        self.new_identity = dict(bundle_snapshot(self.prepared), version=version)
        if self.new_identity['device'] != self.plan['startupIdentity']['device']:
            raise ValueError('prepared-volume-mismatch')
        _sync_tree(self.prepared)
        probe = self.directory / 'rename-probe.app'
        _rename_exclusive(self.prepared, probe)
        _rename_exclusive(probe, self.prepared)
        _same_bundle(self.prepared, self.new_identity)
        _sync_directory(self.directory)
        check_installation_identity(self.destination, self.plan['destinationIdentity'])
        self.record('prepared')

    def install(self):
        self.check_parent_directory()
        check_installation_identity(self.destination, self.plan['destinationIdentity'])
        _same_bundle(self.prepared, self.new_identity)
        verify_bundle(self.prepared, self.plan['teamId'], self.plan['version'])
        self.record('exchanging')
        self.check_parent_directory()
        check_installation_identity(self.destination, self.plan['destinationIdentity'])
        _same_bundle(self.prepared, self.new_identity)
        _exchange(self.destination, self.prepared)
        self.old_moved = True
        self.new_installed = True
        _sync_directory(self.destination.parent)
        _sync_directory(self.directory)
        _same_bundle(self.prepared, self.plan['startupIdentity'])
        _rename_exclusive(self.prepared, self.previous)
        _sync_directory(self.directory)
        _same_bundle(self.destination, self.new_identity)
        self.record('exchanged')

    def rollback(self):
        # 调用方已确认自己的新进程停止；不递归删除目标，先核对并隔离本事务包。
        self.check_parent_directory()
        if self.old_moved and not self.previous.exists():
            _same_bundle(self.prepared, self.plan['startupIdentity'])
            _rename_exclusive(self.prepared, self.previous)
        if self.old_moved:
            _same_bundle(self.previous, self.plan['startupIdentity'])
            verify_bundle(self.previous, expected_version=self.plan['destinationIdentity']['version'])
        if self.new_installed:
            _same_bundle(self.destination, self.new_identity)
            self.record('rollback-exchanging')
            _exchange(self.destination, self.previous)
            self.new_installed = False
            self.old_moved = False
            # 改名后再次核对，遇到竞态置换时不删除、不恢复覆盖，也不宣称已回滚。
            _same_bundle(self.previous, self.new_identity)
            _rename_exclusive(self.previous, self.rejected)
        if self.old_moved:
            _rename_exclusive(self.previous, self.destination)
            self.old_moved = False
        check_installation_identity(self.destination, self.plan['destinationIdentity'])
        # 即便同步失败，也先完成安全路径恢复；保留材料供后续审查。
        _sync_directory(self.destination.parent)
        _sync_directory(self.directory)

    def close(self):
        if self.lock is not None:
            os.close(self.lock)
            self.lock = None


def _selfcheck(app, directory, timeout=25):
    """退出时安装不会重开应用，无法事后确认可启动；替换前让待装副本无界面地真实渲染一次。

    使用隔离数据目录并禁用更新；失败则本次事务取消，现有应用保持不变。
    """
    work = Path(directory) / 'selfcheck'
    work.mkdir(mode=0o700)
    source, output = work / 'check.md', work / 'check.html'
    source.write_text('# mdPreview\n\nself-check\n', encoding='utf-8')
    environment = {key: value for key, value in os.environ.items() if not key.startswith('MDPREVIEW_')}
    environment.update(MDPREVIEW_DATA_DIR=str(work / 'data'), MDPREVIEW_DISABLE_UPDATES='1',
                       MDPREVIEW_HEADLESS_TIMEOUT='20')
    try:
        result = subprocess.run([str(Path(app) / 'Contents/MacOS/mdPreview'), '--headless-export',
                                 str(source), str(output), 'html'], env=environment, timeout=timeout,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode != 0 or not output.is_file() or output.stat().st_size < 100:
            raise RuntimeError('prepared-application-selfcheck-failed')
    except subprocess.TimeoutExpired:
        raise RuntimeError('prepared-application-selfcheck-timeout') from None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _wait_commit_exit(plan, parent, timeout=None):
    # 后台准备可能早于用户退出数天；默认无截止时间，但持续检查取消和父进程身份。
    deadline = None if timeout is None else time.monotonic() + timeout
    while deadline is None or time.monotonic() < deadline:
        _check_abort(plan)
        _committed(plan)
        if parent.gone():
            # 退出与第一次读 commit 可能交错；确认退出后重读最终提交。
            _check_abort(plan)
            committed = _committed(plan)
            if not committed:
                raise RuntimeError('parent-exited-without-commit')
            return committed
        time.sleep(0.5)
    raise TimeoutError('parent-commit-exit-timeout')


def _launch(app, ready):
    command = [str(Path(app) / 'Contents/MacOS/mdPreview'), '--update-ready', str(ready)]
    return subprocess.Popen(command, start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _wait_ready(plan, process, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('updated-process-exited')
        _check_abort(plan)
        marker = _optional(plan['ready'])
        if marker is not None:
            # 启动回执不是退出授权：旧目标包仅回 PID/版本；仍绑定本次活的子进程。
            # 明确失败或附加未知字段不能被当作旧版成功回执。
            if (not isinstance(marker, dict)
                    or set(marker) not in ({'pid', 'version'}, {'pid', 'version', 'success'})
                    or marker.get('version') != plan['version']
                    or type(marker.get('pid')) is not int or marker['pid'] != process.pid
                    or ('success' in marker and marker['success'] is not True)):
                raise RuntimeError('application-ready-mismatch')
            if process.poll() is not None:
                raise RuntimeError('updated-process-exited')
            return
        time.sleep(0.1)
    raise TimeoutError('application-ready-timeout')


def _stop(process):
    if process is None:
        return True
    try:
        if process.poll() is None:
            # 首屏失败不代表没有用户输入；只等待自己的子进程自然退出。
            process.wait(timeout=5)
        return process.poll() is not None
    except Exception:
        return False


def _note(plan, state, error=None):
    # 日志失败不阻止回退；不记录文档或未筛选的异常消息。
    try:
        private_write(plan['log'], {'nonce': plan['transactionNonce'], 'state': state,
                                    'errorType': type(error).__name__ if error else None,
                                    'pendingPreserved': True})
    except Exception:
        pass


def run_plan(path, legacy=False):
    plan = parent = transaction = process = lease = None
    try:
        plan = _load_plan(path)
        parent = _LegacyParent(plan) if legacy else _Parent(plan)
        if legacy and version_tuple(plan['version']) < version_tuple(plan['destinationIdentity']['version']):
            raise ValueError('update-downgrade-refused')
        check_startup_snapshot(plan['destination'], plan['startupIdentity'])
        check_installation_identity(plan['destination'], plan['destinationIdentity'])
        transaction = _Transaction(plan)
        transaction.acquire()
        for marker in ('armed', 'commit', 'ready', 'abort'):
            if os.path.lexists(plan[marker]):
                raise ValueError('installation-marker-already-exists')
        archive = Path(plan['archive'])
        with private_directory(archive.parent):
            for key in ('archive', 'manifest', 'signature'):
                asset = Path(plan[key])
                info = asset.lstat()
                if (asset.parent != archive.parent or not stat.S_ISREG(info.st_mode)
                        or info.st_uid != os.getuid() or info.st_nlink != 1):
                    raise ValueError('unsafe-release-asset')
            staged = extract_verified(archive, plan['manifest'], plan['signature'], transaction.directory / 'extracted')
        verify_bundle(staged, plan['teamId'], plan['version'])
        size = sum(item.stat().st_size for item in Path(staged).rglob('*') if item.is_file() and not item.is_symlink())
        if shutil.disk_usage(transaction.root).free < size + 64 * 1024 * 1024:
            raise OSError(errno.ENOSPC, 'update-insufficient-space')
        _check_abort(plan)
        transaction.prepare(staged)
        _check_abort(plan)
        _selfcheck(transaction.prepared, transaction.directory)
        _same_bundle(transaction.prepared, transaction.new_identity)
        verify_bundle(transaction.prepared, plan['teamId'], plan['version'])
        _check_abort(plan)
        if not legacy and parent.gone():
            raise RuntimeError('parent-exited-before-armed')
        transaction.record('armed')
        private_write(plan['armed'], {'nonce': plan['transactionNonce'], 'pid': os.getpid(), 'success': True})
        if legacy:
            parent.wait()
            committed = {'relaunch': True}
        else:
            committed = _wait_commit_exit(plan, parent)
        _check_abort(plan)
        lease = RuntimeLease(plan['destination'], exclusive=True)
        lease.check()
        transaction.install()
        if not committed['relaunch']:
            transaction.record('ready')
            _note(plan, 'ready-no-relaunch')
            return True
        _check_abort(plan)
        transaction.record('launching')
        lease.close()
        lease = None
        process = _launch(plan['destination'], plan['ready'])
        _wait_ready(plan, process)
        _same_bundle(transaction.destination, transaction.new_identity)
        transaction.record('ready')
        _note(plan, 'ready')
        return True
    except BaseException as error:
        # 未获得事务所有权时不改别人的回执；故障回退始终静默，不重开旧应用。
        if transaction is not None and transaction.owned:
            state = 'cancelled'
            try:
                if transaction.old_moved or transaction.new_installed:
                    if parent is None or not parent.exited or not _stop(process):
                        raise RuntimeError('application-exit-unconfirmed')
                    if lease is None:
                        lease = RuntimeLease(plan['destination'], exclusive=True)
                    lease.check()
                    transaction.rollback()
                    state = 'rolled-back'
                transaction.record(state)
                _note(plan, 'failed-old-preserved', error)
            except BaseException as rollback_error:
                try:
                    transaction.record('recovery-required')
                except BaseException:
                    pass
                _note(plan, 'recovery-required', rollback_error)
            try:
                private_write(plan['armed'], {'nonce': plan['transactionNonce'], 'pid': os.getpid(), 'success': False})
            except BaseException:
                pass
        raise
    finally:
        if lease is not None:
            lease.close()
        if transaction is not None:
            if transaction.owned and transaction.state in ('ready', 'rolled-back', 'cancelled'):
                try:
                    transaction.collect()
                except (OSError, ValueError):
                    _note(plan, 'cleanup-deferred')
            transaction.close()


def main(argv=None):
    parser = argparse.ArgumentParser()
    options = parser.add_mutually_exclusive_group(required=True)
    options.add_argument('--plan')
    options.add_argument('--capabilities', action='store_true')
    args = parser.parse_args(argv)
    if args.capabilities:
        print(json.dumps({'protocol': 2, 'normalQuit': 1}))
        return
    legacy = _legacy_handoff(args.plan)
    if legacy is None:
        run_plan(args.plan)
        return
    try:
        run_plan(legacy, legacy=True)
    except BaseException:
        # 旧版用户点的是“安装并重启”：失败时旧应用已原样保留，重新打开它并说明如何手动安装。
        version, destination = _legacy_failure_context(legacy)
        if destination is not None:
            subprocess.run(['/usr/bin/open', destination], capture_output=True, timeout=15, check=False)
        if version is not None:
            _show_migration(version)
        raise


def _legacy_handoff(path):
    """Old clients cannot authorize protocol 2. Offer an explicit, non-destructive migration."""
    path = Path(os.path.abspath(path))
    support = (Path(os.path.realpath(os.environ['MDPREVIEW_DATA_DIR']))
               if os.environ.get('MDPREVIEW_DATA_DIR') else Path.home() / 'Library/Application Support/mdPreview')
    staging = support / 'UpdateStaging'
    if not path.is_relative_to(staging):
        return None
    if path.resolve() != path or path.name != 'install-plan.json':
        raise ValueError('legacy-plan-location-invalid')
    # Historical writers used ordinary atomic text files, possibly mode 0644.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or info.st_size > 1024 * 1024 or stat.S_IMODE(info.st_mode) & 0o022):
            raise ValueError('legacy-plan-unsafe')
        plan = json.load(stream)
    fields = {'pid', 'staging', 'destination', 'destinationIdentity', 'startupIdentity',
              'teamId', 'version', 'archive', 'manifest', 'signature', 'ready', 'log'}
    if not isinstance(plan, dict) or set(plan) != fields:
        raise ValueError('legacy-plan-invalid')
    if (type(plan['pid']) is not int or plan['pid'] <= 1
            or (plan['teamId'] is not None and (not isinstance(plan['teamId'], str)
                or not re.fullmatch(r'[A-Z0-9]{10}', plan['teamId'])))):
        raise ValueError('legacy-plan-invalid')
    for key in ('staging', 'destination', 'archive', 'manifest', 'signature', 'ready', 'log'):
        value = plan[key]
        if (not isinstance(value, str) or '\x00' in value or not Path(value).is_absolute()
                or os.path.abspath(value) != value):
            raise ValueError('legacy-plan-invalid')
    version_tuple(plan['version'])
    app = Path(plan['staging'])
    if (not app.is_relative_to(path.parent) or app.resolve() != app
            or not app.is_relative_to(staging) or path.parent != app.parent):
        raise ValueError('legacy-staging-invalid')
    if getattr(sys, 'frozen', False) and Path(sys.executable) != app / 'Contents/MacOS/mdPreview':
        raise ValueError('legacy-helper-mismatch')
    verify_bundle(app, plan['teamId'], plan['version'])
    check_startup_snapshot(plan['destination'], plan['startupIdentity'])
    check_installation_identity(plan['destination'], plan['destinationIdentity'])
    # 旧计划本身不被执行：只取其中经过上面校验的字段，重建一份新协议计划并走同一套
    # 验签、自检、原子交换、回滚流程。
    nonce = os.urandom(16).hex()
    directory = support / 'UpdateTransactions' / 'install' / nonce
    converted = {'protocol': 2, 'normalQuit': 1, 'transactionNonce': nonce, 'pid': plan['pid'],
                 'destination': plan['destination'], 'startupIdentity': plan['startupIdentity'],
                 'destinationIdentity': plan['destinationIdentity'], 'archive': plan['archive'],
                 'manifest': plan['manifest'], 'signature': plan['signature'],
                 'staging': plan['staging'], 'version': plan['version'], 'teamId': plan['teamId'],
                 'ready': str(directory / 'ready.json'), 'armed': str(directory / 'armed.json'),
                 'commit': str(directory / 'commit.json'), 'abort': str(directory / 'abort.json'),
                 'log': str(directory / 'install.log')}
    private_write(directory / 'install-plan.json', converted)
    return directory / 'install-plan.json'


def _legacy_failure_context(path):
    try:
        plan = private_read(path)
        version_tuple(plan['version'])
        destination = plan['destination']
        return plan['version'], destination if Path(destination, 'Contents/MacOS/mdPreview').is_file() else None
    except Exception:
        return None, None


def _show_migration(version):
    from AppKit import NSApplication, NSAlert
    application = NSApplication.sharedApplication()
    application.activateIgnoringOtherApps_(True)
    alert = NSAlert.alloc().init()
    alert.setMessageText_('mdPreview could not update itself / mdPreview 未能自动更新')
    alert.setInformativeText_(
        'The update could not be installed automatically. Your current mdPreview and your '
        'documents have not been changed. To update, download the new version, quit mdPreview, '
        'and replace the app in your Applications folder.\n\n'
        '未能自动完成更新。当前的 mdPreview 和你的文档都没有改动。如需更新，请下载新版本，退出 mdPreview 后，在“应用程序”文件夹中替换它。')
    alert.addButtonWithTitle_('Download / 下载')
    alert.addButtonWithTitle_('Later / 稍后')
    if alert.runModal() == 1000:
        subprocess.run(['/usr/bin/open', 'https://github.com/tahoeliu/mdPreview/releases/tag/v' + version],
                       check=True, timeout=15)


if __name__ == '__main__':
    main()
