"""Bounded raster export from the opened document's own directory."""
import base64
import os
from pathlib import Path
from urllib.parse import unquote


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
