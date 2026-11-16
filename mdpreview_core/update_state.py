"""进程内唯一更新状态；只持久化安全错误码、签名资产引用及有界重试时间。

正常退出安装模型：
  - ready 表示待装包已验证；后台预先准备 helper，收到 armed 后登记内存事务。
  - armedForQuit 表示允许在正常退出确认完成后提交安装；失败时清除。
  - 普通退出只安装、不重开；只有显式批准更新且通过原退出确认才请求重开。
"""
import copy
import threading
import time
from pathlib import Path
from .update_storage import private_read, private_write

PHASES = frozenset(('idle', 'checking', 'downloading', 'retrying', 'ready', 'preparing',
                    'installing', 'failed'))
RETRY_DELAYS = (60, 300, 1800, 7200)
CHECK_INTERVAL = 7 * 86400


class UpdateState:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.value = {'schema': 1, 'phase': 'idle', 'version': None, 'progress': None,
                      'error': None, 'detail': '', 'automatic': True, 'nextRetryAt': None,
                      'retryCount': 0, 'deferCount': 0, 'lastCompletedCheck': 0, 'lastDiscoveryAt': 0,
                      'pending': None, 'armedForQuit': False}
        try:
            saved = private_read(self.path, 1024 * 1024)
            if isinstance(saved, dict) and saved.get('phase') == 'deferred':
                # 旧自动延期语义已移除：延期等待一律并入 ready 等待用户同意。
                saved = dict(saved, phase='ready')
            if not isinstance(saved, dict) or saved.get('schema') != 1 or saved.get('phase') not in PHASES:
                raise ValueError('update-state-invalid')
            import math
            import re
            for field in ('retryCount', 'deferCount'):
                if type(saved.get(field)) is not int or saved[field] < 0:
                    raise ValueError('update-state-invalid')
            for field in ('lastCompletedCheck', 'nextRetryAt', 'lastDiscoveryAt'):
                value = saved.get(field, 0)
                if value is None and field == 'nextRetryAt':
                    continue
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise ValueError('update-state-invalid')
            version = saved.get('version')
            if version is not None and (not isinstance(version, str) or len(version) > 32
                                        or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)?', version)):
                raise ValueError('update-state-invalid')
            if type(saved.get('automatic')) is not bool or type(saved.get('armedForQuit', False)) is not bool:
                raise ValueError('update-state-invalid')
            pending = saved.get('pending')
            if pending is not None and (not isinstance(pending, dict) or not isinstance(pending.get('staging_app'), str)
                                        or not isinstance(pending.get('version'), str)):
                raise ValueError('update-state-invalid')
            self.value.update(saved)
            if self.value['phase'] in ('checking', 'downloading', 'preparing', 'installing'):
                self.value.update(phase='retrying', nextRetryAt=time.time() + RETRY_DELAYS[0])
        except FileNotFoundError:
            pass

    def snapshot(self, public=False):
        with self.lock:
            result = copy.deepcopy(self.value)
        if public:
            for key in ('schema', 'pending', 'lastCompletedCheck', 'lastDiscoveryAt'):
                result.pop(key, None)
        return result

    def change(self, **patch):
        if patch.get('phase', self.value['phase']) not in PHASES:
            raise ValueError('update-phase-invalid')
        with self.lock:
            updated = dict(self.value, **patch)
            private_write(self.path, updated)
            self.value = updated
            return self.snapshot(public=True)

    def failure(self, info, now=None):
        now = time.time() if now is None else now
        with self.lock:
            count = self.value['retryCount']
            retry = info.get('retryable') is True and count < len(RETRY_DELAYS)
            return self.change(phase='retrying' if retry else 'failed', error=info['error'],
                               detail=info['detail'], stage=info.get('stage'), code=info.get('code'),
                               http=info.get('http'), attempts=info.get('attempts', 0),
                               retryable=info.get('retryable', False),
                               nextRetryAt=now + (RETRY_DELAYS[count] if retry else CHECK_INTERVAL),
                               retryCount=count + 1 if retry else count, armedForQuit=False)

    def due(self, enabled, now=None):
        if not enabled:
            return False
        now = time.time() if now is None else now
        state = self.snapshot()
        if state['phase'] in ('checking', 'downloading', 'preparing', 'installing'):
            return False
        if state['phase'] == 'ready':
            # 同意门控：ready 只等待用户决定（或退出间隙安装），没有自动动作。
            return False
        if state['nextRetryAt'] is not None:
            return now >= state['nextRetryAt']
        if state['phase'] == 'failed':
            return now - max(state['lastDiscoveryAt'], state['lastCompletedCheck']) >= CHECK_INTERVAL
        if state['pending']:
            return state['phase'] == 'idle'
        return now - state['lastCompletedCheck'] >= CHECK_INTERVAL
