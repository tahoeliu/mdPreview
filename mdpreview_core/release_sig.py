"""固定信任根的 ECDSA P-256 验证；未配置生产公钥时关闭更新。"""
import base64
import re

# 必须由维护者经独立渠道核验后填写；不能从下载包、API或环境变量获取。
RELEASE_PUBKEY_B64 = ''


def configured():
    try:
        raw = base64.b64decode(RELEASE_PUBKEY_B64, validate=True)
        return len(raw) == 65 and raw[0] == 4
    except (ValueError, TypeError):
        return False


def verify(message, der_sig):
    if not configured() or not isinstance(message, bytes) or not isinstance(der_sig, bytes):
        return False
    if not message or len(message) > 1048576 or not 8 <= len(der_sig) <= 80:
        return False
    try:
        import Security
        import Foundation
        raw = base64.b64decode(RELEASE_PUBKEY_B64, validate=True)
        attrs = {Security.kSecAttrKeyType: Security.kSecAttrKeyTypeECSECPrimeRandom,
                 Security.kSecAttrKeyClass: Security.kSecAttrKeyClassPublic,
                 Security.kSecAttrKeySizeInBits: 256}
        key, error = Security.SecKeyCreateWithData(Foundation.NSData.dataWithBytes_length_(raw, len(raw)), attrs, None)
        if key is None or error is not None:
            return False
        result = Security.SecKeyVerifySignature(key, Security.kSecKeyAlgorithmECDSASignatureMessageX962SHA256,
                    Foundation.NSData.dataWithBytes_length_(message, len(message)),
                    Foundation.NSData.dataWithBytes_length_(der_sig, len(der_sig)), None)
        if not isinstance(result, tuple) or len(result) != 2:
            return False
        ok, error = result
        return bool(ok) and error is None
    except Exception:
        return False


def signed_digest(manifest, signature, filename):
    if not verify(manifest, signature):
        raise ValueError('release-signature-invalid-or-unconfigured')
    entries = {}
    for line in manifest.decode('ascii').splitlines():
        match = re.fullmatch(r'([a-f0-9]{64}) [ *]([A-Za-z0-9][A-Za-z0-9._-]*)', line)
        if not match or match[2] in entries:
            raise ValueError('invalid-checksum-manifest')
        entries[match[2]] = match[1]
    if filename not in entries:
        raise ValueError('asset-not-signed')
    return entries[filename]
