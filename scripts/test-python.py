"""各套测试使用独立进程，避免 Cocoa mock 相互污染；产物仅写入 WorkSpace。"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parent.parent
workspace = root / 'WorkSpace'
cache = workspace / 'cache'
cache.mkdir(parents=True, exist_ok=True)
run = Path(tempfile.mkdtemp(prefix='python-tests-', dir=cache))
environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(root),
                   MDPREVIEW_DISABLE_UPDATES='1', TMPDIR=str(run),
                   COVERAGE_FILE=str(run / '.coverage'),
                   PYTEST_ADDOPTS=f'-o cache_dir={cache / "pytest"}',
                   RUFF_CACHE_DIR=str(cache / 'ruff'))
failed = False
for test in sorted((workspace / 'tests').glob('test_*.py')):
    with tempfile.TemporaryDirectory(prefix='app-data-', dir=run) as directory:
        result = subprocess.run(
            [sys.executable, '-B', '-m', 'coverage', 'run', '--parallel-mode',
             '--source=mdpreview_core,mdPreview', str(test)],
            cwd=root, env=dict(environment, MDPREVIEW_DATA_DIR=directory), timeout=300)
        failed |= result.returncode != 0
for args in (
    ['combine', str(run)],
    ['json', '-o', str(workspace / 'python-coverage.json')],
    ['report', '--include=mdpreview_core/*', '--fail-under=90'],
):
    subprocess.run([sys.executable, '-B', '-m', 'coverage', *args],
                   cwd=root, env=environment, check=True)
raise SystemExit(1 if failed else 0)
