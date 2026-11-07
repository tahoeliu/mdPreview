"""Bounded raster export from the opened document's own directory."""
import base64
import os
from pathlib import Path
from urllib.parse import unquote
import re
import tempfile
from datetime import datetime


def save_asset(document_path, data, ext):
    if not document_path or not Path(document_path).is_file():
        return {'success': False, 'need_save': True}
    if not isinstance(data, str) or len(data) > 28 * 1024 * 1024:
        raise ValueError('invalid-image-size')
    ext = str(ext).lower().lstrip('.')
    raw = base64.b64decode(data.split(',', 1)[-1], validate=True)
    signatures = {'png': raw.startswith(b'\x89PNG\r\n\x1a\n'), 'jpg': raw.startswith(b'\xff\xd8\xff'),
                  'jpeg': raw.startswith(b'\xff\xd8\xff'), 'gif': raw.startswith((b'GIF87a', b'GIF89a')),
                  'webp': raw.startswith(b'RIFF') and raw[8:12] == b'WEBP'}
    if not signatures.get(ext) or len(raw) > 20 * 1024 * 1024:
        raise ValueError('invalid-image-data')
    base = Path(document_path).resolve().parent
    folder = base / 'assets'
    folder.mkdir(exist_ok=True)
    if folder.is_symlink() or folder.resolve().parent != base:
        raise ValueError('unsafe-assets-directory')
    stem = re.sub(r'[^A-Za-z0-9._-]', '_', Path(document_path).stem)[:80] or 'image'
    name = stem + '-' + datetime.now().strftime('%Y%m%d-%H%M%S')
    fd, temp = tempfile.mkstemp(prefix='.image-', dir=folder)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        for index in range(10000):
            target = folder / (name + ('-'+str(index) if index else '') + '.' + ext)
            try:
                os.link(temp, target)
                return {'success': True, 'path': 'assets/' + target.name}
            except FileExistsError:
                continue
        raise ValueError('image-name-exhausted')
    finally:
        os.unlink(temp)


def export_image(document_path, relative_path):
    if not document_path or not isinstance(relative_path, str):
        raise ValueError('An image export needs a saved document')
    base = Path(document_path).resolve().parent
    target = (base / unquote(relative_path)).resolve()
    if os.path.commonpath([target, base]) != str(base):
        raise ValueError('Image is outside the document directory')
    if target.stat().st_size > 20 * 1024 * 1024:
        raise ValueError('Image exceeds 20 MB export limit')
    raw = target.read_bytes()
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):
        mime = 'image/png'
    elif raw.startswith(b'\xff\xd8\xff'):
        mime = 'image/jpeg'
    elif raw.startswith((b'GIF87a', b'GIF89a')):
        mime = 'image/gif'
    elif raw.startswith(b'RIFF') and raw[8:12] == b'WEBP':
        mime = 'image/webp'
    else:
        raise ValueError('Unsupported raster image data')
    return 'data:' + mime + ';base64,' + base64.b64encode(raw).decode('ascii')
