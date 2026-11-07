"""把已构建并验收的 mdPreview.app 打成发布 ZIP：mdPreview-<版本>-<架构>.zip。

用法：.venv/bin/python scripts/package-release.py --app path/to/mdPreview.app --out folder
- 架构取自主程序的 Mach-O（必须是单一架构），文件名因此不会说谎。
- 版本必须与 VERSION 和应用内 Info.plist 一致。
- 生成后立即用更新器同一个严格解包器再解一遍，保证用户端一定能装。
签名（SHA256SUMS / .sig）由 scripts/sign-release.mjs 在持有私钥的环境里单独完成。
"""
import argparse
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mdpreview_core.release_zip import extract  # noqa: E402


def architecture(app):
    binary = app / 'Contents/MacOS/mdPreview'
    archs = subprocess.check_output(['lipo', '-archs', str(binary)], text=True).split()
    if len(archs) != 1 or archs[0] not in ('arm64', 'x86_64'):
        raise SystemExit(f'expected a single-architecture executable, got {archs!r}')
    return archs[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    app = Path(args.app).resolve()
    out = Path(args.out).resolve()
    if app.name != 'mdPreview.app' or not (app / 'Contents/Info.plist').is_file():
        raise SystemExit('--app must be a built mdPreview.app')
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    if info.get('CFBundleShortVersionString') != version:
        raise SystemExit(f"app version {info.get('CFBundleShortVersionString')} does not match VERSION {version}")
    arch = architecture(app)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f'mdPreview-{version}-{arch}.zip'
    if target.exists():
        raise SystemExit(f'{target} already exists')
    # --norsrc/--noextattr/--noqtn 避免产生 __MACOSX 成员和隔离属性；--keepParent 让成员以 mdPreview.app/ 开头。
    subprocess.run(['ditto', '-c', '-k', '--keepParent', '--norsrc', '--noextattr', '--noqtn', str(app), str(target)], check=True)
    with tempfile.TemporaryDirectory(prefix='package-check-') as folder:
        staged = extract(target, Path(folder) / 'verified')
        if not (staged / 'Contents/MacOS/mdPreview').is_file():
            raise SystemExit('packaged archive lacks the main executable')
    print(f'{target} ({target.stat().st_size // 1024 // 1024} MB, {arch}) passed the updater extraction checks')


if __name__ == '__main__':
    main()
