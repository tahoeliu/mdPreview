"""阅读位置只保存路径摘要；按更新时间淘汰至 300 项。"""
import hashlib
import math
import os
import time


def position_key(path):
    return hashlib.sha256(os.path.realpath(path).encode('utf-8')).hexdigest()


def remember(values, path, position):
    if not isinstance(position, dict):
        raise ValueError('invalid-position')
    ratio = position.get('ratio', 0)
    heading = position.get('headingId', '')
    if type(ratio) not in (int, float) or not math.isfinite(ratio) or not 0 <= ratio <= 1:
        raise ValueError('invalid-ratio')
    if not isinstance(heading, str) or len(heading) > 512:
        raise ValueError('invalid-heading')
    result = {k: v for k, v in (values.items() if isinstance(values, dict) else []) if isinstance(k, str) and len(k) == 64 and all(c in '0123456789abcdef' for c in k) and isinstance(v, dict) and isinstance(v.get('updatedAt'), (int, float))}
    key = position_key(path)
    result.pop(key, None)
    result[key] = {'ratio': ratio, 'headingId': heading, 'updatedAt': time.time()}
    return dict(sorted(result.items(), key=lambda item: item[1]['updatedAt'])[-300:])


def visible_frame(frame, screens):
    if not isinstance(frame, list) or len(frame) != 4 or any(type(x) not in (int, float) or not math.isfinite(x) for x in frame):
        return False
    x, y, width, height = frame
    if width < 680 or height < 400:
        return False
    return any(min(x+width, sx+sw)-max(x, sx) >= 100 and min(y+height, sy+sh)-max(y, sy) >= 100 for sx, sy, sw, sh in screens)
