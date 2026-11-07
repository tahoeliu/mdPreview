"""诊断数据只从固定类型的白名单构造，绝不读取原始日志。"""
import io
import json
import platform
import re
import threading
import time
import zipfile
from collections import deque
from urllib.parse import urlencode
from .settings import settings

_events = deque(maxlen=2000)
_lock = threading.Lock()
_KINDS = {'startup', 'uncaught', 'thread-uncaught', 'frontend-error'}
_ERRORS = {'ValueError', 'TypeError', 'RuntimeError', 'OSError', 'MemoryError', 'TimeoutError', 'Other'}


def record(kind, error=None, milliseconds=None):
    if kind not in _KINDS:
        return
    item = {'kind': kind, 'time': int(time.time())}
    if error is not None:
        item['error'] = error if error in _ERRORS else 'Other'
    if type(milliseconds) in (int, float) and 0 <= milliseconds <= 86400000:
        item['milliseconds'] = round(milliseconds, 2)
    with _lock:
        _events.append(item)


def metadata(version):
    def numeric(value):
        return value if re.fullmatch(r'[0-9]+(?:\.[0-9]+){0,3}', str(value)) else 'unknown'
    arch = platform.machine()
    return {'version': numeric(version), 'os': numeric(platform.mac_ver()[0]),
            'arch': arch if arch in ('arm64', 'x86_64') else 'unknown'}


def issue_url(version):
    return 'https://github.com/tahoeliu/mdPreview/issues/new?' + urlencode({'template': 'bug.yml', **metadata(version)})


def archive(version, config):
    output = io.BytesIO()
    with _lock:
        events = list(_events)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for name, value in [('environment.json', metadata(version)),
                            ('config.json', settings(config)), ('events.json', events)]:
            bundle.writestr(name, json.dumps(value, ensure_ascii=False, indent=2))
    return output.getvalue()
