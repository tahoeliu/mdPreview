"""语言包一致性：三份键集合相同；繁体中文不得残留简体字（用 macOS 内置的 ICU 简繁转换检查）。"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / 'frontend'


def load(name):
    return json.loads((FRONTEND / f'{name}.json').read_text(encoding='utf-8'))


class MoreLanguageTests(unittest.TestCase):
    def test_every_language_covers_every_key_with_matching_placeholders(self):
        import re
        english = load('en')
        pattern = r'\{\w+\}|%s'
        for name in ('ja', 'ko', 'de', 'fr', 'es'):
            data = load(name)
            self.assertEqual(set(english), set(data), name)
            for key, value in data.items():
                self.assertTrue(isinstance(value, str) and value.strip(), f'{name}: empty value for {key!r}')
                self.assertEqual(sorted(re.findall(pattern, value)), sorted(re.findall(pattern, key)), f'{name}: placeholders {key!r}')

    def test_example_documents_exist_for_every_language(self):
        examples = json.loads((FRONTEND / 'welcome.json').read_text(encoding='utf-8'))
        for name in ('en', 'zh-Hans', 'zh-Hant', 'ja', 'ko', 'de', 'fr', 'es'):
            self.assertIn(name, examples)
            self.assertIn(f'lang: {name}', examples[name])

    def test_languages_are_selectable_and_normalised(self):
        from mdpreview_core.settings import CHOICES
        for name in ('ja', 'ko', 'de', 'fr', 'es'):
            self.assertIn(name, CHOICES['language'])


class LocaleTests(unittest.TestCase):
    def test_same_keys_and_no_empty_values(self):
        english, hans, hant = load('en'), load('zh-Hans'), load('zh-Hant')
        self.assertEqual(set(english), set(hans))
        self.assertEqual(set(english), set(hant))
        for name, data in (('en', english), ('zh-Hans', hans), ('zh-Hant', hant)):
            for key, value in data.items():
                self.assertTrue(isinstance(value, str) and value.strip(), f'{name}: empty value for {key!r}')

    def test_placeholders_are_preserved(self):
        english, hans, hant = load('en'), load('zh-Hans'), load('zh-Hant')
        import re
        for key in english:
            expected = sorted(re.findall(r'\{\w+\}', english[key]))
            self.assertEqual(sorted(re.findall(r'\{\w+\}', hans[key])), expected, f'zh-Hans placeholders: {key!r}')
            self.assertEqual(sorted(re.findall(r'\{\w+\}', hant[key])), expected, f'zh-Hant placeholders: {key!r}')

    @unittest.skipUnless(sys.platform == 'darwin', 'uses the ICU transliterator bundled with macOS')
    def test_traditional_chinese_has_no_residual_simplified_characters(self):
        import Foundation
        residues = []
        for key, value in load('zh-Hant').items():
            converted = Foundation.NSString.stringWithString_(value).stringByApplyingTransform_reverse_('Hans-Hant', False)
            if converted is not None and str(converted) != value:
                residues.append((value, str(converted)))
        self.assertEqual(residues, [], 'zh-Hant still contains simplified characters')

    def test_simplified_and_traditional_differ_for_chinese_text(self):
        hans, hant = load('zh-Hans'), load('zh-Hant')
        different = sum(1 for key in hans if hans[key] != hant[key])
        self.assertGreater(different, len(hans) // 4, 'zh-Hant looks like a copy of zh-Hans')


if __name__ == '__main__':
    unittest.main(verbosity=2)
