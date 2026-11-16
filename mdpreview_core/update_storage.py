"""Private update metadata only; never stores or restores document contents."""
import json
import os
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def private_directory(path, create=False):
    path = Path(os.path.abspath(path))
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                    os.fsync(fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError('private-directory-required')
        yield fd
    finally:
        os.close(fd)


def private_write(path, value):
    path = Path(path)
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    temporary = '.' + uuid.uuid4().hex
    with private_directory(path.parent, create=True) as directory:
        try:
            try:
                existing = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
                if not stat.S_ISREG(existing.st_mode) or existing.st_uid != os.getuid() or existing.st_nlink != 1:
                    raise ValueError('unsafe-private-file')
            except FileNotFoundError:
                pass
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass


def private_read(path, limit=1024 * 1024):
    path = Path(path)
    with private_directory(path.parent) as directory:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
                    or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > limit):
                raise ValueError('unsafe-private-file')
            raw = stream.read(limit + 1)
            if len(raw) > limit:
                raise ValueError('update-metadata-too-large')
            return json.loads(raw)
