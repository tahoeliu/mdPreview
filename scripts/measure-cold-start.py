"""测量已构建应用的“进程启动 → 首屏”耗时，输出发布门禁需要的 JSON。

用法：.venv/bin/python scripts/measure-cold-start.py --app mdPreview.app --out cold-start.json [--runs 5]
每次运行使用全新的隔离数据目录；只结束自己启动的进程，不影响已打开的 mdPreview。
取中位数，避免偶发抖动或首次运行的磁盘缓存影响结论。
"""
import argparse
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERN = re.compile(r'\[startup\] process to first screen: (\d+)ms')


def one_run(app, document):
    with tempfile.TemporaryDirectory(prefix='cold-start-') as data:
        log = Path(data) / 'Logs' / 'mdPreview.log'
        env = dict(os.environ, MDPREVIEW_DATA_DIR=data, MDPREVIEW_DISABLE_UPDATES='1')
        process = subprocess.Popen([str(app / 'Contents/MacOS/mdPreview'), str(document)], env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.time() + 60
            while time.time() < deadline:
                if log.is_file():
                    match = PATTERN.search(log.read_text(encoding='utf-8', errors='replace'))
                    if match:
                        return int(match.group(1))
                if process.poll() is not None:
                    raise RuntimeError('application exited before reaching the first screen')
                time.sleep(0.2)
            raise RuntimeError('no first-screen log line within 60 seconds')
        finally:
            process.terminate()
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                process.kill()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--runs', type=int, default=5)
    args = parser.parse_args()
    app = Path(args.app).resolve()
    out = Path(args.out)
    if out.exists():
        parser.error('output file already exists')
    document = ROOT / 'tests' / 'fixtures' / 'output' / 'zh-longform.md'
    digest = subprocess.check_output(['node', '--input-type=module', '-e',
                                      "import {bundleDigest} from './scripts/verify-matrix.mjs'; console.log(bundleDigest(process.argv[1]));",
                                      str(app)], cwd=ROOT, text=True).strip()
    samples = [one_run(app, document) for _ in range(max(1, args.runs))]
    result = {
        'kind': 'native-process-first-screen',
        'milliseconds': int(statistics.median(samples)),
        'samples': samples,
        'bundleSha256': digest,
        'version': (ROOT / 'VERSION').read_text(encoding='utf-8').strip(),
        'environment': f'macOS {platform.mac_ver()[0]} {platform.machine()}',
        'measuredAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    }
    out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(f"cold start median {result['milliseconds']}ms over {len(samples)} runs: {samples}")


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as error:
        print('cold-start measurement failed:', error, file=sys.stderr)
        raise SystemExit(1)
