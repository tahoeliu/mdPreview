"""各套测试使用独立进程，避免 Cocoa mock 相互污染；产物仅写入 WorkSpace。"""
import argparse
from contextlib import nullcontext
import os
import subprocess
import sys
import tempfile
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--retain-artifacts', action='store_true',
                    help='保留运行器创建的数据目录和 coverage 产物；不禁用各测试或生产代码自身的清理')
options = parser.parse_args()

root = Path(__file__).resolve().parent.parent
workspace = root / 'WorkSpace'
cache = workspace / 'cache'
cache.mkdir(parents=True, exist_ok=True)
run = Path(tempfile.mkdtemp(prefix='python-tests-', dir=cache))
print(f'测试运行目录：{run}', flush=True)
if options.retain_artifacts:
    print('保留模式仅覆盖运行器；各测试及生产代码的自清理仍可能触发保护。', flush=True)
    parallel_coverage = run / 'coverage-parts'
    parallel_coverage.mkdir()
else:
    parallel_coverage = run
coverage_report = (run if options.retain_artifacts else workspace) / 'python-coverage.json'
environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(root),
                   MDPREVIEW_DISABLE_UPDATES='1', TMPDIR=str(run),
                   COVERAGE_FILE=str(run / '.coverage'),
                   PYTEST_ADDOPTS=f'-o cache_dir={run / "pytest"}',
                   RUFF_CACHE_DIR=str(run / 'ruff'))
failed = False
tests = sorted((root / 'tests').glob('test_*.py'))
for test in tests:
    # 中断恢复包含两端真实文件/签名故障注入，实测约534秒；仅此套件扩展预算。
    timeout = 600 if test.name == 'test_update_interrupted.py' else 300
    print(f'运行套件：{test.relative_to(root)}，预算={timeout}秒', flush=True)
    data_directory = (nullcontext(tempfile.mkdtemp(prefix='app-data-', dir=run))
                      if options.retain_artifacts else tempfile.TemporaryDirectory(prefix='app-data-', dir=run))
    with data_directory as directory:
        try:
            result = subprocess.run(
                [sys.executable, '-B', '-m', 'coverage', 'run', '--branch', '--parallel-mode',
                 '--source=mdpreview_core,mdPreview,scripts.install_update', str(test)],
                cwd=root, env=dict(environment, MDPREVIEW_DATA_DIR=directory,
                                   COVERAGE_FILE=str(parallel_coverage / '.coverage')), timeout=timeout)
            failed |= result.returncode != 0
        except subprocess.TimeoutExpired:
            print(f'套件超时：{test.relative_to(root)}（{timeout} 秒）', file=sys.stderr, flush=True)
            failed = True
for args in (
    ['combine', *(['--keep'] if options.retain_artifacts else []), str(parallel_coverage)],
    ['json', '-o', str(coverage_report)],
    ['report', '-m', '--include=scripts/install_update.py'],
    ['report', '-m', '--include=mdpreview_core/*', '--fail-under=90'],
):
    subprocess.run([sys.executable, '-B', '-m', 'coverage', *args],
                   cwd=root, env=environment, check=True)
raise SystemExit(1 if failed else 0)
