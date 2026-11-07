import base64
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from mdpreview_core import release_sig


class Signatures(unittest.TestCase):
    def test_unconfigured_closed(self):
        with patch.object(release_sig, 'RELEASE_PUBKEY_B64', ''):
            self.assertFalse(release_sig.verify(b'manifest', b'signature'))

    def test_real_security_framework(self):
        # 只在授权原生测试环境运行；密钥只用于临时测试，绝不写生产配置。
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            subprocess.run(['openssl', 'ecparam', '-name', 'prime256v1', '-genkey', '-noout', '-out', str(root/'key')], check=True)
            public = subprocess.check_output(['openssl', 'ec', '-in', str(root/'key'), '-pubout', '-outform', 'DER'])[-65:]
            message = b'0' * 64 + b'  mdPreview-1.0.0-arm64.zip\n'
            (root/'manifest').write_bytes(message)
            subprocess.run(['openssl', 'dgst', '-sha256', '-sign', str(root/'key'), '-out', str(root/'sig'), str(root/'manifest')], check=True)
            signature = (root/'sig').read_bytes()
            with patch.object(release_sig, 'RELEASE_PUBKEY_B64', base64.b64encode(public).decode()):
                self.assertTrue(release_sig.verify(message, signature))
                self.assertFalse(release_sig.verify(message+b'x', signature))
            subprocess.run(['openssl', 'ecparam', '-name', 'prime256v1', '-genkey', '-noout', '-out', str(root/'other')], check=True)
            other = subprocess.check_output(['openssl', 'ec', '-in', str(root/'other'), '-pubout', '-outform', 'DER'])[-65:]
            with patch.object(release_sig, 'RELEASE_PUBKEY_B64', base64.b64encode(other).decode()):
                self.assertFalse(release_sig.verify(message, signature))


if __name__ == '__main__':
    unittest.main()
