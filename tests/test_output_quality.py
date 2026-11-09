"""T03 打印字号、层级、缩放隔离与真实输出质量回归。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures/output'


class FixtureTests(unittest.TestCase):
    def test_inventory_and_provenance(self):
        manifest = json.loads((FIXTURES / 'manifest.json').read_text())
        self.assertEqual(len(manifest['fixtures']), 11)
        self.assertFalse(manifest['real_ai_exports_available'])
        for name in manifest['fixtures']:
            self.assertTrue((FIXTURES / name).is_file(), name)
        self.assertGreater(len((FIXTURES / 'zh-longform.md').read_text()), 3000)
        self.assertEqual(len((FIXTURES / 'wide-table.md').read_text().splitlines()[4:]), 30)
        self.assertEqual(len((FIXTURES / 'long-code.md').read_text().split('```python\n')[1].split('```')[0].splitlines()), 120)
        for name in ('chatgpt', 'claude'):
            self.assertIn('SYNTHETIC SUBSTITUTE', (FIXTURES / f'ai-export-{name}.md').read_text())


@unittest.skipUnless(sys.platform == 'darwin', '需要 macOS 原生打印服务')
class OutputBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        check = subprocess.run([sys.executable, '-I', '-B', '-c',
                                'import AppKit, Foundation, WebKit, Quartz, objc'], capture_output=True)
        if check.returncode:
            raise unittest.SkipTest('缺少 PyObjC 原生框架')
        out = ROOT / 'WorkSpace/outputs/T03'
        out.mkdir(parents=True, exist_ok=True)
        cls.out = Path(tempfile.mkdtemp(prefix='baseline-', dir=out))

    def probe(self, name, *args):
        # A shared CI runner now and then hands back a page that has not been laid out yet; retry that
        # transient case. A genuine regression fails every attempt.
        for attempt in range(3):
            # The probe refuses to overwrite earlier evidence, so every retry writes a new file.
            target = self.out / (f'{name}.pdf' if attempt == 0 else f'{name}.retry{attempt}.pdf')
            command = [sys.executable, '-I', '-B', str(ROOT / 'scripts/output_probe.py'),
                       '--out', str(target), '--json', *map(str, args)]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                    env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'), timeout=60)
            if result.returncode == 0:
                break
        (self.out / f'{name}.stdout.log').write_text(result.stdout)
        (self.out / f'{name}.stderr.log').write_text(result.stderr)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        metrics = json.loads(result.stdout)
        (self.out / f'{name}.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + '\n')
        print(f'OUTPUT_BASELINE {name}: {json.dumps(metrics, ensure_ascii=False)}', flush=True)
        return metrics

    def test_01_calibration(self):
        html = self.out / 'calibration.html'
        html.write_text('''<!doctype html><html><head><meta charset="utf-8"></head><body>
<div class="scroll-wrap"><div class="page"><article class="markdown">
<h1>HHeading One</h1><h2>HHeading Two</h2><h3>HHeading Three</h3>
<p>HBody paragraph 中文正文测试。</p><pre><code>HCode block line</code></pre>
<table><thead><tr><th>HTh</th></tr></thead><tbody><tr><td>HTd cell</td></tr></tbody></table>
<a href="https://github.com/tahoeliu/mdPreview">项目源码</a>
</article></div></div></body></html>''', encoding='utf-8')
        for name, options in [('light', []), ('zoom22', ['--font-size', '22px']), ('dark', ['--dark'])]:
            with self.subTest(name=name):
                css = ','.join(str(ROOT / 'css' / f'{part}.css') for part in ('tokens', 'content', 'app', 'print'))
                metrics = self.probe(name, '--html', html, '--css', css, *options)
                glyphs = metrics['glyph_heights']
                self.assertTrue(8.0 <= glyphs['body'] <= 8.8, glyphs)
                self.assertGreater(glyphs['h1'], glyphs['h2'])
                self.assertGreater(glyphs['h2'], glyphs['h3'])
                self.assertGreater(glyphs['h3'], glyphs['body'])
                self.assertTrue(any(v < 254 for v in metrics['code_region_luminance']))
                self.assertTrue(any(v < 254 for v in metrics['code_background_luminance']))
                self.assertEqual(metrics['text_bboxes_outside_margin'], 0)
                if name == 'light':
                    baseline = glyphs
                elif name == 'zoom22':
                    for key in baseline:
                        self.assertLess(abs(glyphs[key] - baseline[key]), 0.2)

    def test_02_all_markdown_fixtures(self):
        for fixture in sorted(FIXTURES.glob('*.md')):
            with self.subTest(fixture=fixture.name):
                self.probe(fixture.stem, '--markdown', fixture)


if __name__ == '__main__':
    unittest.main(verbosity=2)
