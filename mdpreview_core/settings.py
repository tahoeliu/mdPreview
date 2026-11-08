"""应用设置采用离线默认值，仅接受明确的类型和范围。"""
import re

DEFAULTS = {'language': 'system', 'appearance': 'system', 'restore_session': False, 'auto_update': True, 'format_bar': False,
            'font_size': 16, 'reading_font': 'sans', 'toggle_shortcut': 'cmd+e', 'page_width': 720, 'remote_images': 'ask', 'auto_reload': True}
CHOICES = {'language': ('system', 'en', 'zh-Hans', 'zh-Hant', 'ja', 'ko', 'de', 'fr', 'es'),
           'appearance': ('system', 'light', 'dark'),
           'reading_font': ('sans', 'serif'),
           'remote_images': ('ask', 'always', 'never')}


def validated(patch):
    if not isinstance(patch, dict):
        raise ValueError('invalid-settings')
    result = {}
    for key, value in patch.items():
        if key not in DEFAULTS:
            continue
        if key == 'toggle_shortcut':
            valid = isinstance(value, str) and re.fullmatch(r'(?:(?:cmd|ctrl|alt|shift)\+)+[a-z0-9]', value) is not None and ('cmd' in value or 'ctrl' in value) and len(set(value.split('+')[:-1])) == len(value.split('+')) - 1
        elif key in CHOICES:
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
