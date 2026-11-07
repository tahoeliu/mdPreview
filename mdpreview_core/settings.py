"""应用设置采用离线默认值，仅接受明确的类型和范围。"""
DEFAULTS = {'language': 'system', 'restore_session': False, 'auto_update': True,
            'font_size': 16, 'page_width': 720, 'remote_images': 'ask', 'auto_reload': True}
CHOICES = {'language': ('system', 'en', 'zh-Hans', 'zh-Hant'),
           'remote_images': ('ask', 'always', 'never')}


def validated(patch):
    if not isinstance(patch, dict):
        raise ValueError('invalid-settings')
    result = {}
    for key, value in patch.items():
        if key not in DEFAULTS:
            continue
        if key in CHOICES:
            valid = isinstance(value, str) and value in CHOICES[key]
        elif key in ('font_size', 'page_width'):
            low, high = (12, 24) if key == 'font_size' else (360, 2016)
            valid = type(value) is int and low <= value <= high
        else:
            valid = type(value) is bool
        if not valid:
            raise ValueError('invalid-setting-' + key)
        result[key] = value
    return result


def settings(config):
    result = dict(DEFAULTS)
    saved = config.get('settings', {})
    for key, value in saved.items() if isinstance(saved, dict) else []:
        try:
            result.update(validated({key: value}))
        except ValueError:
            pass
    return result
