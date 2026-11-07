"""仅供用户显式调用；未知公钥或签名失败时安装关闭。"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mdpreview_core.release_sig import configured
from mdpreview_core.update_download import download
from mdpreview_core.release import transactional_install, verify_bundle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version')
    parser.add_argument('--destination', default='/Applications/mdPreview.app')
    args = parser.parse_args()
    if not configured():
        parser.error('release public key is not configured; installation disabled')
    import platform
    if sys.platform != 'darwin' or int(platform.mac_ver()[0].split('.')[0]) < 13:
        parser.error('macOS 13 or newer required')
    if subprocess.run(['pgrep', '-x', 'mdPreview'], capture_output=True).returncode == 0:
        parser.error('quit mdPreview first')
    if not args.version:
        import json
        import urllib.request
        request = urllib.request.Request('https://api.github.com/repos/tahoeliu/mdPreview/releases/latest', headers={'User-Agent': 'mdPreview'})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read(2000001)
            if len(data) > 2000000:
                parser.error('release metadata too large')
            metadata = json.loads(data)
        if metadata.get('draft') or metadata.get('prerelease'):
            parser.error('non-stable release refused')
        args.version = str(metadata.get('tag_name', '')).removeprefix('v')
    target = Path(args.destination).expanduser().absolute()
    if target.name != 'mdPreview.app' or not target.parent.is_dir():
        parser.error('destination must be mdPreview.app in an existing directory')
    if not os.access(target.parent, os.W_OK):
        parser.error('destination not writable; choose --destination ~/Applications/mdPreview.app')
    # 不自动清理失败产物，保留用于诊断；不禁用系统隔离保护。
    staging = tempfile.mkdtemp(prefix='mdpreview-signed-install-')
    result = download(args.version, '0.0.0', staging)
    def verify(app):
        verify_bundle(app, expected_version=args.version)
    from mdpreview_core.release_zip import extract_verified
    import time
    import json
    verified = extract_verified(result['archive'], result['manifest'], result['signature'],
                                Path(staging) / 'install-verified')
    probe = Path(staging) / 'startup-probe'
    marker = probe / 'UpdateStaging' / 'ready.json'
    marker.parent.mkdir(parents=True)
    process = None

    def launch(app):
        nonlocal process
        environment = dict(os.environ, MDPREVIEW_DATA_DIR=str(probe), MDPREVIEW_DISABLE_UPDATES='1')
        process = subprocess.Popen([str(app / 'Contents/MacOS/mdPreview'), '--update-ready', str(marker)],
                                   env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def stop_probe():
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    def ready(app):
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    return False
                if marker.is_file():
                    data = json.loads(marker.read_text())
                    return data.get('pid') == process.pid and data.get('version') == args.version
                time.sleep(0.1)
            return False
        finally:
            stop_probe()

    try:
        transactional_install(verified, target, verify, launch, ready)
    finally:
        stop_probe()
    print('Verified installation and isolated startup check complete. Open the application manually.')


if __name__ == '__main__':
    main()
