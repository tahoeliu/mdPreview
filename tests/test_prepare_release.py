import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location('prepare_release', ROOT / 'scripts' / 'prepare-release.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)

ARM, INTEL = 'a' * 64, 'b' * 64
SUMS = f'{ARM}  mdPreview-2.0.0-arm64.zip\n{INTEL}  mdPreview-2.0.0-x86_64.zip\n{"c" * 64}  mdPreview-2.0.0-arm64.dmg\n'

CHANGELOG = '''# Changelog

## Unreleased

- nothing yet

## [2.0.0] - 2026-11-10

### Added
- Faster large documents

## [1.5.0] - 2026-10-01

- older
'''


class CaskTests(unittest.TestCase):
    def test_renders_both_architectures_from_signed_manifest(self):
        text = prepare.render_cask(SUMS, '2.0.0')
        self.assertIn('version "2.0.0"', text)
        self.assertIn(f'arm:   "{ARM}"', text)
        self.assertIn(f'intel: "{INTEL}"', text)
        self.assertNotIn('c' * 64, text)  # DMG 哈希不得混入
        self.assertIn('mdPreview-#{version}-#{arch}.zip', text)
        self.assertIn('--no-quarantine', text)

    def test_ruby_syntax_is_valid(self):
        ruby = shutil.which('ruby')
        if not ruby:
            self.skipTest('ruby not available')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'mdpreview.rb'
            path.write_text(prepare.render_cask(SUMS))
            result = subprocess.run([ruby, '-c', str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_missing_architecture(self):
        with self.assertRaisesRegex(ValueError, 'x86_64'):
            prepare.render_cask(f'{ARM}  mdPreview-2.0.0-arm64.zip\n')

    def test_rejects_mixed_versions_and_wrong_expected_version(self):
        mixed = SUMS + f'{ARM}  mdPreview-1.9.0-arm64.zip\n'
        with self.assertRaisesRegex(ValueError, 'exactly one version'):
            prepare.render_cask(mixed)
        with self.assertRaisesRegex(ValueError, 'expected 3.0.0'):
            prepare.render_cask(SUMS, '3.0.0')

    def test_rejects_malformed_manifest(self):
        for bad in ('not a manifest\n', f'{ARM}  a.zip\n{ARM}  a.zip\n', 'g' * 64 + '  mdPreview-2.0.0-arm64.zip\n'):
            with self.subTest(bad=bad[:20]):
                with self.assertRaises(ValueError):
                    prepare.render_cask(bad)


class NotesTests(unittest.TestCase):
    def test_extracts_exact_section(self):
        notes = prepare.release_notes(CHANGELOG, '2.0.0')
        self.assertIn('Faster large documents', notes)
        self.assertNotIn('older', notes)
        self.assertNotIn('nothing yet', notes)

    def test_missing_or_empty_section_fails(self):
        with self.assertRaises(ValueError):
            prepare.release_notes(CHANGELOG, '9.9.9')
        with self.assertRaises(ValueError):
            prepare.release_notes('## [2.0.0]\n\n## [1.0.0]\nx\n', '2.0.0')

    def test_version_is_matched_literally(self):
        with self.assertRaises(ValueError):
            prepare.release_notes(CHANGELOG, '2.0.')


if __name__ == '__main__':
    unittest.main(verbosity=2)
