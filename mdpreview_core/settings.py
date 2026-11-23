"""应用设置采用离线默认值，仅接受明确的类型和范围。"""
import json
import re
from functools import lru_cache
from pathlib import Path

DEFAULTS = {'language': 'system', 'appearance': 'system', 'restore_session': False, 'auto_update': True, 'format_bar': False,
            'font_size': 16, 'reading_font': 'sans', 'toggle_shortcut': 'cmd+e', 'page_width': 720, 'remote_images': 'ask', 'auto_reload': True}
CHOICES = {'language': ('system', 'en', 'zh-Hans', 'zh-Hant', 'ja', 'ko', 'de', 'fr', 'es'),
           'appearance': ('system', 'light', 'dark'),
           'reading_font': ('sans', 'serif'),
           'remote_images': ('ask', 'always', 'never')}

@lru_cache(maxsize=1)
def _reserved_shortcuts():
    path = Path(__file__).resolve().parents[1] / 'frontend' / 'shortcuts.json'
    items = json.loads(path.read_text(encoding='utf-8'))
    names = {'command': 'cmd', 'control': 'ctrl', 'option': 'alt', 'shift': 'shift'}
    return frozenset(
        (frozenset(names[modifier] for modifier in item['modifiers']), item['key'])
        for item in items if item['action'] != 'toggleView:'
    )


def validated(patch):
    if not isinstance(patch, dict):
        raise ValueError('invalid-settings')
    result = {}
    for key, value in patch.items():
        if key not in DEFAULTS:
            continue
        if key == 'toggle_shortcut':
            valid = False
            if isinstance(value, str) and re.fullmatch(r'(?:(?:cmd|ctrl|alt|shift)\+)+[a-z0-9]', value):
                *modifiers, letter = value.split('+')
                mask = frozenset(modifiers)
                valid = (bool(mask & {'cmd', 'ctrl'}) and len(mask) == len(modifiers)
                         and (mask, letter) not in _reserved_shortcuts())
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
