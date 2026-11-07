"""验证已构建应用里的 Finder 空格预览扩展：结构、签名、沙盒，以及系统真的调用它并渲染成功。

用法：.venv/bin/python scripts/verify-quicklook.py --app path/to/mdPreview.app [--keep-registered]
流程：检查 appex → 向系统登记并启用 → 用系统自带的 qlmanage 预览一个 Markdown 文件 →
读取扩展在自己沙盒容器里写下的诊断（只有成功标志、元素数、耗时，不含正文或路径）→ 取消登记。
预览通过 quicklook/tools/preview-host.swift（QLPreviewView，与 Finder 同一条系统通道）触发；
qlmanage 只走旧式 generator，看不到扩展，所以不用它。需要图形会话；不会修改被检查的应用。

重要：在较新的 macOS 上，第三方 Quick Look 扩展还需要用户在“系统设置 > 通用 > 登录项与扩展 > Quick Look”
里手动启用。若这里超时，请先手动启用再重试（--keep-registered 可保留登记以便手动检查）。
"""
import argparse
import json
import plistlib
import subprocess
import sys
import tempfile
import time
from pathlib import Path

IDENTIFIER = 'tahoeliu.mdpreview.quicklook'
CONTAINER = Path.home() / 'Library/Containers' / IDENTIFIER / 'Data/Library/Caches/last-preview.json'
SAMPLE = '''---
title: Quick Look 验收
---

# 空格预览验收

正文 **粗体** 与公式 $a^2+b^2=c^2$。

$$
\\sum_{i=1}^n i = \\frac{n(n+1)}{2}
$$

![远程图](https://example.com/remote.png)

| 列 A | 列 B |
| --- | --- |
| 一 | 二 |
'''


def run(*args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, **kwargs)


def check_structure(appex):
    plist = plistlib.loads((appex / 'Contents/Info.plist').read_bytes())
    assert plist['CFBundleIdentifier'] == IDENTIFIER, 'unexpected bundle identifier'
    extension = plist['NSExtension']
    assert extension['NSExtensionPointIdentifier'] == 'com.apple.quicklook.preview'
    assert 'net.daringfireball.markdown' in extension['NSExtensionAttributes']['QLSupportedContentTypes']
    executable = appex / 'Contents/MacOS' / plist['CFBundleExecutable']
    assert executable.is_file(), 'extension executable missing'
    web = appex / 'Contents/Resources/web'
    for name in ('preview.html', 'preview.js', 'markdown-pipeline.js', 'purify.min.js', 'marked.min.js', 'katex.min.js', 'content.css'):
        assert (web / name).is_file(), f'missing {name}'
    assert any((web / 'fonts').glob('*.woff2')), 'KaTeX fonts missing'
    entitlements = run('codesign', '-d', '--entitlements', '-', str(appex)).stdout + run('codesign', '-d', '--entitlements', '-', str(appex)).stderr
    assert 'com.apple.security.app-sandbox' in entitlements, 'extension is not sandboxed'
    assert 'network' not in entitlements, 'extension must not request network access'
    archs = run('lipo', '-archs', str(executable)).stdout.split()
    assert len(archs) == 1, f'extension architectures: {archs}'
    return archs[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app', required=True)
    parser.add_argument('--keep-registered', action='store_true')
    args = parser.parse_args()
    app = Path(args.app).resolve()
    appex = app / 'Contents/PlugIns/MDPreviewQuickLook.appex'
    assert appex.is_dir(), 'the app has no Quick Look extension (run quicklook/build.sh)'
    arch = check_structure(appex)
    app_arch = run('lipo', '-archs', str(app / 'Contents/MacOS/mdPreview')).stdout.split()
    assert app_arch == [arch], f'extension arch {arch} differs from app arch {app_arch}'
    assert run('codesign', '--verify', '--deep', '--strict', str(app)).returncode == 0, 'bundle signature invalid'

    registered = False
    preview = None
    try:
        assert run('pluginkit', '-a', str(appex)).returncode == 0, 'pluginkit could not register the extension'
        registered = True
        run('pluginkit', '-e', 'use', '-i', IDENTIFIER)
        run('qlmanage', '-r')
        listing = run('pluginkit', '-m', '-A', '-i', IDENTIFIER, '-v').stdout
        assert IDENTIFIER in listing, 'extension is not visible to the system'
        if CONTAINER.exists():
            CONTAINER.unlink()
        with tempfile.TemporaryDirectory(prefix='ql-verify-') as folder:
            sample = Path(folder) / 'sample.md'
            sample.write_text(SAMPLE, encoding='utf-8')
            host = Path(folder) / 'preview-host'
            build = run('swiftc', '-O', '-o', str(host), str(Path(__file__).resolve().parents[1] / 'quicklook/tools/preview-host.swift'),
                        '-framework', 'Cocoa', '-framework', 'Quartz')
            assert build.returncode == 0, 'cannot compile the preview host: ' + build.stderr[:300]
            started = time.time()
            preview = subprocess.Popen([str(host), str(sample), '45'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = started + 40
            report = None
            while time.time() < deadline:
                if CONTAINER.is_file() and CONTAINER.stat().st_mtime >= started:
                    report = json.loads(CONTAINER.read_text())
                    break
                time.sleep(0.5)
            assert report is not None, ('the system did not use the mdPreview extension within 40 s: enable it in System Settings > '
                                        'General > Login Items & Extensions > Quick Look, or another Markdown extension is preferred')
            assert report.get('ok') is True, f'preview failed: {report}'
            assert report.get('headings', 0) >= 1 and report.get('formulas', 0) >= 2, f'content was not rendered: {report}'
            assert report.get('blocked_images') == 1, f'remote image was not blocked: {report}'
            print(f"Quick Look verified ({arch}): {report}")
    finally:
        if preview is not None:
            preview.terminate()
        if registered and not args.keep_registered:
            run('pluginkit', '-e', 'ignore', '-i', IDENTIFIER)
            run('pluginkit', '-r', str(appex))
            run('qlmanage', '-r')
        if CONTAINER.exists():
            CONTAINER.unlink()


if __name__ == '__main__':
    try:
        main()
    except AssertionError as error:
        print('Quick Look verification FAILED:', error, file=sys.stderr)
        raise SystemExit(1)
