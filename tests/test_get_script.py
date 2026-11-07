"""scripts/get.sh：用本地 file:// 假发布驱动真实脚本，验证签名、校验和与安装/回滚行为。"""
import base64
import hashlib
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mdpreview_core import release_sig  # noqa: E402

SCRIPT = ROOT / 'scripts' / 'get.sh'
VERSION = '9.9.9'


def run(*args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, **kwargs)


def make_app(folder, version=VERSION, bundle_id='tahoeliu.mdpreview'):
    app = Path(folder) / 'mdPreview.app'
    (app / 'Contents/MacOS').mkdir(parents=True)
    executable = app / 'Contents/MacOS/mdPreview'
    executable.write_text('#!/bin/sh\necho mdPreview\n')
    executable.chmod(0o755)
    (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({
        'CFBundleIdentifier': bundle_id, 'CFBundleExecutable': 'mdPreview',
        'CFBundleShortVersionString': version, 'CFBundleVersion': version, 'CFBundlePackageType': 'APPL'}))
    subprocess.run(['codesign', '--force', '--sign', '-', str(app)], check=True, capture_output=True)
    return app


def new_key(folder, name):
    key = Path(folder) / (name + '.pem')
    subprocess.run(['openssl', 'ecparam', '-name', 'prime256v1', '-genkey', '-noout', '-out', str(key)], check=True, capture_output=True)
    public = subprocess.run(['openssl', 'ec', '-in', str(key), '-pubout'], check=True, capture_output=True, text=True).stdout
    return key, public


class GetScriptStatic(unittest.TestCase):
    def test_syntax(self):
        self.assertEqual(run('bash', '-n', str(SCRIPT)).returncode, 0)
        if shutil.which('shellcheck'):
            self.assertEqual(run('shellcheck', '-S', 'warning', str(SCRIPT)).returncode, 0)

    def test_embedded_key_matches_the_pinned_app_key(self):
        pem = re.search(r"<<'PEM' \|\| true\n(.*?)\nPEM\n", SCRIPT.read_text(), re.S).group(1)
        der = subprocess.run(['openssl', 'pkey', '-pubin', '-outform', 'DER'], input=pem.encode(), capture_output=True, check=True).stdout
        self.assertEqual(base64.b64encode(der[-65:]).decode(), release_sig.RELEASE_PUBKEY_B64)
        self.assertEqual((ROOT / 'scripts/release-pubkey.pem').read_text().strip(), pem.strip())

    def test_no_quarantine_manipulation_or_sudo(self):
        body = '\n'.join(line for line in SCRIPT.read_text().splitlines() if not line.lstrip().startswith('#'))
        self.assertNotIn('xattr', body)
        self.assertNotIn('sudo', body)
        self.assertNotIn('spctl', body)


class GetScriptFlow(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(os.path.realpath(self.dir.name))
        self.key, self.public_pem = new_key(self.root, 'key')
        self.release = self.root / 'releases' / ('v' + VERSION)
        self.release.mkdir(parents=True)
        self.install = self.root / 'Applications'
        self.install.mkdir()
        self.arch = 'arm64' if subprocess.run(['sysctl', '-n', 'hw.optional.arm64'], capture_output=True, text=True).stdout.strip() == '1' else 'x86_64'
        self.zip_name = f'mdPreview-{VERSION}-{self.arch}.zip'
        staging = self.root / 'stage'
        staging.mkdir()
        self.app = make_app(staging)
        subprocess.run(['ditto', '-c', '-k', '--keepParent', '--norsrc', '--noextattr', '--noqtn', str(self.app), str(self.release / self.zip_name)], check=True)
        self.sign()

    def sign(self, key=None, names=None):
        names = names or [self.zip_name]
        manifest = ''.join(hashlib.sha256((self.release / n).read_bytes()).hexdigest() + '  ' + n + '\n' for n in names)
        (self.release / 'SHA256SUMS').write_text(manifest)
        subprocess.run(['openssl', 'dgst', '-sha256', '-sign', str(key or self.key), '-out', str(self.release / 'SHA256SUMS.sig'),
                        str(self.release / 'SHA256SUMS')], check=True)

    def script_copy(self, pem=None):
        text = SCRIPT.read_text()
        text = re.sub(r"(<<'PEM' \|\| true\n).*?(\nPEM\n)", lambda m: m.group(1) + (pem or self.public_pem).strip() + m.group(2), text, flags=re.S)
        text = text.replace("DOWNLOAD_BASE=\"https://github.com/${REPO}/releases/download\"", 'DOWNLOAD_BASE="file://%s/releases"' % urllib.parse.quote(str(self.root)))
        text = text.replace("CURL_PROTO='=https'", "CURL_PROTO='=file'")
        text = text.replace('pgrep -x mdPreview', 'false')  # 测试机上可能正运行着真实的 mdPreview
        path = self.root / 'get-test.sh'
        path.write_text(text)
        return path

    def run_script(self, **overrides):
        env = dict(os.environ, MDPREVIEW_VERSION=VERSION, MDPREVIEW_INSTALL_DIR=str(self.install), TMPDIR=str(self.root))
        env.update(overrides)
        return run('bash', str(self.script_copy()), env=env)

    def installed(self):
        return self.install / 'mdPreview.app'

    def test_success_installs_identical_app(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Signature OK', result.stdout)
        self.assertEqual((self.installed() / 'Contents/MacOS/mdPreview').read_text(), (self.app / 'Contents/MacOS/mdPreview').read_text())
        self.assertEqual(run('codesign', '--verify', '--deep', '--strict', str(self.installed())).returncode, 0)
        self.assertEqual([p.name for p in self.install.iterdir()], ['mdPreview.app'])

    def test_tampered_archive_is_rejected_and_existing_install_kept(self):
        make_app(self.install, version='1.0.0')
        data = bytearray((self.release / self.zip_name).read_bytes())
        data[len(data) // 2] ^= 0xFF
        (self.release / self.zip_name).write_bytes(bytes(data))
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('mismatch', result.stderr)
        plist = plistlib.loads((self.installed() / 'Contents/Info.plist').read_bytes())
        self.assertEqual(plist['CFBundleShortVersionString'], '1.0.0')

    def test_signature_from_another_key_is_rejected(self):
        other, _ = new_key(self.root, 'other')
        self.sign(key=other)
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('signature check FAILED', result.stderr)
        self.assertFalse(self.installed().exists())

    def test_tampered_manifest_is_rejected(self):
        manifest = (self.release / 'SHA256SUMS').read_text()
        (self.release / 'SHA256SUMS').write_text(manifest.replace(self.zip_name, 'mdPreview-0.0.0-arm64.zip'))
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.installed().exists())

    def test_archive_not_in_signed_list_is_rejected(self):
        (self.release / 'extra.zip').write_bytes(b'x')
        self.sign(names=['extra.zip'])
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not listed', result.stderr)

    def test_bundle_version_mismatch_is_rejected(self):
        shutil.rmtree(self.root / 'stage')
        staging = self.root / 'stage'
        staging.mkdir()
        wrong = make_app(staging, version='1.2.3')
        (self.release / self.zip_name).unlink()
        subprocess.run(['ditto', '-c', '-k', '--keepParent', '--norsrc', '--noextattr', '--noqtn', str(wrong), str(self.release / self.zip_name)], check=True)
        self.sign()
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('does not match', result.stderr)

    def test_wrong_bundle_identifier_is_rejected(self):
        shutil.rmtree(self.root / 'stage')
        staging = self.root / 'stage'
        staging.mkdir()
        evil = make_app(staging, bundle_id='com.example.other')
        (self.release / self.zip_name).unlink()
        subprocess.run(['ditto', '-c', '-k', '--keepParent', '--norsrc', '--noextattr', '--noqtn', str(evil), str(self.release / self.zip_name)], check=True)
        self.sign()
        self.assertIn('bundle identifier', self.run_script().stderr)

    def test_invalid_version_is_rejected_before_any_download(self):
        result = self.run_script(MDPREVIEW_VERSION='1.0; rm -rf /')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('valid release version', result.stderr)

    def test_replaces_existing_installation(self):
        make_app(self.install, version='1.0.0')
        self.assertEqual(self.run_script().returncode, 0)
        plist = plistlib.loads((self.installed() / 'Contents/Info.plist').read_bytes())
        self.assertEqual(plist['CFBundleShortVersionString'], VERSION)
        self.assertEqual([p.name for p in self.install.iterdir()], ['mdPreview.app'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
