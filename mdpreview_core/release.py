"""Fail-closed release identity and transactional local installation."""
from __future__ import annotations

import os
import plistlib
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+\.\d+\.\d+(?:\.\d+)?', value):
        raise ValueError('Invalid release version')
    parts = tuple(map(int, value.split('.')))
    return parts + (0,) * (4 - len(parts))


def verify_bundle(app, team_id=None, expected_version=None):
    if team_id and not re.fullmatch(r'[A-Z0-9]{10}', team_id):
        raise ValueError('Invalid publisher Team ID')
    app = Path(app)
    with (app / 'Contents/Info.plist').open('rb') as stream:
        info = plistlib.load(stream)
    if info.get('CFBundleIdentifier') != 'tahoeliu.mdpreview':
        raise ValueError('Unexpected application identity')
    version = info.get('CFBundleShortVersionString')
    version_tuple(version)
    if expected_version and version_tuple(version) != version_tuple(expected_version):
        raise ValueError('Release and application versions differ')
    executable = info.get('CFBundleExecutable')
    if executable != 'mdPreview' or not (app / 'Contents/MacOS/mdPreview').is_file():
        raise ValueError('Missing application executable')
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)],
                   check=True, capture_output=True, timeout=30)
    if team_id:
        signature = subprocess.run(['/usr/bin/codesign', '-dv', '--verbose=4', str(app)],
                                   check=True, capture_output=True, text=True, timeout=10)
        if f'TeamIdentifier={team_id}' not in signature.stderr.splitlines():
            raise ValueError('Unexpected update publisher')
        subprocess.run(['/usr/sbin/spctl', '--assess', '--type', 'execute', str(app)],
                       check=True, capture_output=True, timeout=30)
    return version


def verify_asset(payload_digest, size, asset):
    import hmac
    digest = asset.get('digest', '')
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', digest or ''):
        raise ValueError('GitHub release does not provide a SHA-256 digest')
    if size != asset.get('size') or not hmac.compare_digest(payload_digest, digest[7:]):
        raise ValueError('Update asset differs from the published GitHub release')


def bundle_snapshot(app):
    app = Path(app).absolute()
    if app.is_symlink() or app.resolve() != app or not app.is_dir() or app.suffix != '.app':
        raise ValueError('unsafe-install-destination')
    executable = app / 'Contents/MacOS/mdPreview'
    if executable.is_symlink() or not executable.is_file():
        raise ValueError('unsafe-main-executable')
    current, parent, binary = app.stat(), app.parent.stat(), executable.stat()
    return {'path': str(app), 'device': current.st_dev, 'inode': current.st_ino,
            'parentDevice': parent.st_dev, 'parentInode': parent.st_ino,
            'executableDevice': binary.st_dev, 'executableInode': binary.st_ino}


def check_startup_snapshot(app, snapshot):
    if not snapshot or bundle_snapshot(app) != snapshot:
        raise ValueError('running-copy-changed-restart-required')


def installation_identity(app):
    app = Path(app).absolute()
    if app.is_symlink() or app.resolve() != app or not app.is_dir() or app.suffix != '.app':
        raise ValueError('unsafe-install-destination')
    version = verify_bundle(app)
    if not os.access(app.parent, os.W_OK):
        raise PermissionError('application-parent-not-writable')
    return dict(bundle_snapshot(app), version=version)


def check_installation_identity(app, expected):
    if installation_identity(app) != expected:
        raise ValueError('installed-copy-changed')
    return Path(app)


def transactional_install(staged, destination, verify, launch, wait_ready, destination_identity=None):
    """Pre-copy on the target volume; restore the exact old path on failure."""
    staged, destination = Path(staged), Path(destination)
    token = uuid.uuid4().hex
    prepared = destination.parent / f'.mdPreview-prepared-{token}.app'
    previous = destination.parent / f'.mdPreview-previous-{token}.app'
    old_moved = False
    new_installed = False
    try:
        shutil.copytree(staged, prepared, symlinks=True)
        verify(prepared)
        if destination_identity is not None:
            check_installation_identity(destination, destination_identity)
        if destination.exists():
            os.replace(destination, previous)
            old_moved = True
        os.replace(prepared, destination)
        new_installed = True
        launch(destination)
        if not wait_ready(destination):
            raise RuntimeError('Updated application did not become ready')
    except Exception:
        if old_moved:
            if destination.exists():
                shutil.rmtree(destination)
            os.replace(previous, destination)
        elif new_installed and destination.exists():
            shutil.rmtree(destination)
        raise
    finally:
        shutil.rmtree(prepared, ignore_errors=True)
    shutil.rmtree(previous, ignore_errors=True)


def wait_for_exit(pid, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    raise TimeoutError('Previous application is still running; installation cancelled')
