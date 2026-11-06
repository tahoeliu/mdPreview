"""Atomic persistence with explicit document identity and revision ordering."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import threading
import time
import sys
from pathlib import Path


def atomic_write(path, payload: bytes):
    # Follow the final symlink, preserving the link the user opened.
    target = Path(os.path.realpath(os.path.abspath(path)))
    target.parent.mkdir(parents=True, exist_ok=True)
    old_stat = target.stat() if target.exists() else None
    fd, tmp = tempfile.mkstemp(prefix=f'.{target.name}.', suffix='.tmp', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            if old_stat:
                os.fchmod(stream.fileno(), stat.S_IMODE(old_stat.st_mode))
                if sys.platform == 'darwin':
                    import ctypes
                    library = ctypes.CDLL('/usr/lib/libc.dylib', use_errno=True)
                    copyfile = library.copyfile
                    copyfile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_uint32]
                    copyfile.restype = ctypes.c_int
                    # COPYFILE_METADATA = STAT | ACL | XATTR; never copy file data.
                    if copyfile(os.fsencode(target), os.fsencode(tmp), None, 7) != 0:
                        error = ctypes.get_errno()
                        raise OSError(error, os.strerror(error))
                elif hasattr(os, 'listxattr'):
                    for name in os.listxattr(target):
                        os.setxattr(tmp, name, os.getxattr(target, name))
            stream.flush()
            os.utime(tmp, None)
            os.fsync(stream.fileno())
        os.replace(tmp, target)
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


_draft_lock = threading.RLock()


class DraftStore:
    """One atomic record per document, never a shared Untitled filename."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.lock = _draft_lock

    @staticmethod
    def key(path, document_id):
        if path:
            return hashlib.sha256(os.path.realpath(path).encode()).hexdigest()[:24]
        if not re.fullmatch(r'[a-f0-9-]{36}', document_id or ''):
            raise ValueError('Invalid document identity')
        return 'untitled-' + document_id

    def write(self, path, document_id, revision, content, baseline_digest=None):
        with self.lock:
            current = self.read(path, document_id)
            if current and current.get('documentId') == document_id and current['revision'] > revision:
                return current
            record = {'schema': 1, 'documentId': document_id, 'path': path,
                      'revision': revision, 'content': content, 'updatedAt': time.time(),
                      'baselineHash': baseline_digest}
            destination = self.directory / (self.key(path, document_id) + '.json')
            atomic_write(destination, json.dumps(record, ensure_ascii=False).encode('utf-8'))
            return record

    def read(self, path, document_id):
        with self.lock:
            try:
                record = json.loads((self.directory / (self.key(path, document_id) + '.json')).read_text())
                if (record.get('schema') != 1 or not isinstance(record.get('content'), str)
                        or type(record.get('revision')) is not int):
                    return None
                return record
            except (FileNotFoundError, ValueError, KeyError, TypeError):
                return None

    def remove(self, path, document_id):
        with self.lock:
            (self.directory / (self.key(path, document_id) + '.json')).unlink(missing_ok=True)

    def recoverable(self):
        result = []
        if not self.directory.exists():
            return result
        with self.lock:
            legacy = self.directory / (hashlib.sha256(b'Untitled.md').hexdigest()[:24] + '.md')
            if legacy.is_file():
                import uuid
                identity = str(uuid.uuid4())
                self.write(None, identity, 1, legacy.read_text(encoding='utf-8'))
                legacy.unlink()
        for file in sorted(self.directory.glob('untitled-*.json')):
            identity = file.stem.removeprefix('untitled-')
            try:
                record = self.read(None, identity)
                if record:
                    result.append({'documentId': identity, 'updatedAt': record['updatedAt'],
                                   'preview': record['content'][:100]})
            except (ValueError, KeyError):
                continue
        return result
