"""Lifetime leases shared by application startup and the update installer."""
import fcntl
import hashlib
import os
from pathlib import Path
import stat

from .update_storage import private_directory


def transaction_root(destination):
    destination = Path(os.path.abspath(destination))
    return destination.parent / ('.mdPreview-install-' + hashlib.sha256(destination.name.encode()).hexdigest()[:16])


class RuntimeLease:
    def __init__(self, destination, exclusive=False, blocking=False):
        self.root = transaction_root(destination)
        self.fd = None
        with private_directory(self.root, create=True) as directory:
            fd = os.open('runtime.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                value = os.fstat(fd)
                if (not stat.S_ISREG(value.st_mode) or value.st_uid != os.getuid()
                        or value.st_nlink != 1 or stat.S_IMODE(value.st_mode) & 0o077):
                    raise ValueError('runtime-lock-invalid')
                fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
                            | (0 if blocking else fcntl.LOCK_NB))
                named = os.stat('runtime.lock', dir_fd=directory, follow_symlinks=False)
                if (named.st_dev, named.st_ino) != (value.st_dev, value.st_ino):
                    raise ValueError('runtime-lock-changed')
                self.fd = fd
                self.identity = (value.st_dev, value.st_ino)
            except BaseException:
                os.close(fd)
                raise

    def check(self):
        with private_directory(self.root) as directory:
            named = os.stat('runtime.lock', dir_fd=directory, follow_symlinks=False)
            if (named.st_dev, named.st_ino) != self.identity or named.st_nlink != 1:
                raise ValueError('runtime-lock-changed')

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
