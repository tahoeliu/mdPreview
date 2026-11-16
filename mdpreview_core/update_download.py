"""固定公钥验证的 ZIP 下载管线；GitHub API 不参与信任或可用性判断。"""
import errno
from email.utils import parsedate_to_datetime
import hashlib
import hmac
import http.client
import platform
import re
import shutil
import ssl
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from .release import verify_bundle, version_tuple
from .release_sig import configured, signed_digest
from .release_zip import extract_verified


_MAX_ARCHIVE = 300 * 1024 * 1024
_MAX_ATTEMPTS = 4
_NETWORK_BUDGET = 600
_REQUEST_TIMEOUT = 30
_MAX_RETRY_DELAY = 30

# 只映射已知验证错误；不把远端响应、URL、本地路径或系统异常文本交给界面。
_VERIFY_CODES = {
    'release-signing-key-not-configured', 'update-downgrade-refused',
    'unsupported-architecture', 'compatible-zip-not-found', 'invalid-release-version',
    'release-signature-invalid-or-unconfigured', 'invalid-checksum-manifest',
    'asset-not-signed', 'signed-digest-mismatch', 'signed-archive-digest-mismatch',
    'archive-expansion-limit', 'unsafe-archive-path', 'unexpected-archive-member',
    'unsupported-archive-member', 'invalid-symlink', 'unsafe-symlink',
    'escaping-symlink', 'escaping-symlink-chain', 'cyclic-symlink',
    'write-through-symlink', 'extraction-destination-must-not-exist',
    'unsafe-staging-path',
}
_DETAILS = {
    'network': '下载连接中断或超时，自动恢复未完成。',
    'incomplete': '下载不完整或超过大小限制，未使用该更新包。',
    'rate_limited': 'GitHub 请求受到限流，请稍后重试。',
    'forbidden': 'GitHub 拒绝了下载请求。',
    'not_found': '此版本的签名清单或更新包暂不可用。',
    'http': '下载服务器返回了异常状态。',
    'verify': '更新安全校验失败，未使用该更新包。',
    'unknown': '下载更新时发生本地处理错误。',
}


class DownloadError(ValueError):
    """安全的错误契约；保留 ValueError 兼容性，str(error) 仅含固定错误码。"""

    def __init__(self, stage, code, category='verify', http=None, retryable=False, attempts=0):
        super().__init__(code)
        self.stage = stage
        self.code = code
        self.http = http
        self.category = category
        self.detail = _DETAILS[category]
        self.retryable = retryable
        self.attempts = attempts
        self.cleanup_failed = False


def _error(error, stage, attempts=0):
    if isinstance(error, DownloadError):
        return error
    if isinstance(error, urllib.error.HTTPError):
        status = error.code
        headers = error.headers or {}
        if status == 429 or (status == 403 and
                            (headers.get('X-RateLimit-Remaining') == '0' or headers.get('Retry-After'))):
            code, category, retryable = 'http-rate-limited', 'rate_limited', True
        elif status == 403:
            code, category, retryable = 'http-forbidden', 'forbidden', False
        elif status == 404:
            code, category, retryable = 'http-not-found', 'not_found', False
        elif status == 408 or 500 <= status <= 599:
            code, category, retryable = 'http-transient', 'network', True
        else:
            code, category, retryable = 'http-error', 'http', False
        return DownloadError(stage, code, category, status, retryable, attempts)
    if isinstance(error, http.client.IncompleteRead):
        return DownloadError(stage, 'incomplete-download', 'incomplete', retryable=True, attempts=attempts)
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(reason, ssl.SSLEOFError):
        return DownloadError(stage, 'connection-interrupted', 'network', retryable=True, attempts=attempts)
    if isinstance(reason, ssl.SSLError):
        return DownloadError(stage, 'tls-verification-failed', attempts=attempts)
    if isinstance(reason, (TimeoutError, ConnectionError, http.client.RemoteDisconnected)):
        code = 'network-timeout' if isinstance(reason, TimeoutError) else 'connection-interrupted'
        return DownloadError(stage, code, 'network', retryable=True, attempts=attempts)
    if isinstance(error, urllib.error.URLError):
        return DownloadError(stage, 'network-error', 'network', retryable=True, attempts=attempts)
    if isinstance(error, OSError) and error.errno in (errno.ECONNRESET, errno.ECONNABORTED, errno.ETIMEDOUT):
        return DownloadError(stage, 'connection-interrupted', 'network', retryable=True, attempts=attempts)
    if isinstance(error, ValueError):
        code = str(error)
        if code in ('download-size-limit', 'archive-too-large'):
            return DownloadError(stage, code, 'incomplete', attempts=attempts)
        return DownloadError(stage, code if code in _VERIFY_CODES else 'verification-failed', attempts=attempts)
    if stage in ('extract', 'bundle'):
        return DownloadError(stage, stage + '-verification-failed', attempts=attempts)
    return DownloadError(stage, 'local-io-error' if isinstance(error, OSError) else 'unexpected-error',
                         'unknown', attempts=attempts)


def classify(error):
    """兼容旧调用方的四种分类；精确 HTTP 类别由 error_info 提供。"""
    category = _error(error, 'unknown').category
    return 'network' if category in ('rate_limited', 'forbidden', 'not_found', 'http') else category


def error_info(error):
    """供调用方透传的安全、可 JSON 序列化错误；不含底层异常文本。

    error 是精确分类（含 rate_limited/forbidden/not_found/http）；classify 仍返回旧四分类。
    retryable 描述故障是否可能恢复，不表示仍有自动重试额度；本次调用已结束。
    attempts 是失败资源的尝试次数；下载前或解包/应用验证错误为 0。
    """
    error = _error(error, 'unknown')
    return {'error': error.category, 'stage': error.stage, 'code': error.code,
            'http': error.http, 'detail': error.detail, 'retryable': error.retryable,
            'attempts': error.attempts, 'cleanup_failed': error.cleanup_failed}


class _Transfers:
    def __init__(self):
        # 协作式总预算；底层 DNS/连接阻塞仍受 urllib/操作系统超时行为约束。
        self.deadline = time.monotonic() + _NETWORK_BUDGET

    def remaining(self, stage):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise DownloadError(stage, 'retry-budget-exhausted', 'network')
        return remaining

    def run(self, stage, operation):
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                self.remaining(stage)
                return operation()
            except Exception as cause:
                error = _error(cause, stage, attempt)
                error.attempts = attempt
                delay = 2 ** (attempt - 1)
                if isinstance(cause, urllib.error.HTTPError):
                    # 不接受无界 Retry-After；过长的等待直接交给调用方，不占住下载线程。
                    retry_after = (cause.headers or {}).get('Retry-After', '').strip()
                    if retry_after:
                        if len(retry_after) > 128:
                            delay = _MAX_RETRY_DELAY + 1
                        elif re.fullmatch(r'[0-9]{1,8}', retry_after):
                            delay = max(delay, int(retry_after))
                        else:
                            try:
                                retry_date = parsedate_to_datetime(retry_after)
                                if retry_date.tzinfo is None:
                                    raise ValueError('invalid-retry-date')
                                delay = max(delay, retry_date.timestamp() - time.time())
                            except (ValueError, TypeError, OverflowError):
                                delay = _MAX_RETRY_DELAY + 1
                    cause.close()
                if not error.retryable or attempt == _MAX_ATTEMPTS:
                    raise error from None
                if delay > _MAX_RETRY_DELAY or delay >= self.deadline - time.monotonic():
                    raise error from None
                time.sleep(delay)
        raise AssertionError('unreachable')

    def read(self, url, limit, stage, output=None, progress=None):
        request = urllib.request.Request(url, headers={'User-Agent': 'mdPreview', 'Accept-Encoding': 'identity'})
        with urllib.request.urlopen(request, timeout=min(_REQUEST_TIMEOUT, self.remaining(stage))) as response:
            status = getattr(response, 'status', 200)
            if status != 200:
                # 不发送 Range，因此 206 也不能作为完整资产接受。
                raise DownloadError(stage, 'unexpected-http-status', 'http', http=status)
            headers = getattr(response, 'headers', {})
            if headers.get('Content-Encoding', 'identity').lower() != 'identity':
                raise DownloadError(stage, 'unexpected-content-encoding')
            length = headers.get('Content-Length')
            if length is not None:
                if not re.fullmatch(r'[0-9]{1,12}', length):
                    raise DownloadError(stage, 'invalid-content-length', 'incomplete')
                length = int(length)
                if length > limit:
                    raise DownloadError(stage, 'download-size-limit', 'incomplete')
            data = bytearray() if output is None else None
            digest = hashlib.sha256()
            size = 0
            # read1 每次最多一次底层读取，避免 read(n) 在慢速滴流中无限等待凑满 n。
            read = getattr(response, 'read1', response.read)
            while True:
                self.remaining(stage)
                chunk = read(min(65536, limit - size + 1))
                self.remaining(stage)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise DownloadError(stage, 'download-size-limit', 'incomplete')
                if length is not None and size > length:
                    raise DownloadError(stage, 'content-length-mismatch', 'incomplete', retryable=True)
                if output is None:
                    data.extend(chunk)
                else:
                    output.write(chunk)
                    digest.update(chunk)
                if progress:
                    # 无 Content-Length 时不伪造精确进度；按大小上限保守估计。
                    progress(min(95, size * 95 // max(1, length if length is not None else limit)))
            if length is not None and size != length:
                raise DownloadError(stage, 'incomplete-download', 'incomplete', retryable=True)
            if output is None:
                return bytes(data)
            return digest.hexdigest(), size, length


def download(version, installed_version, staging, team_id=None, progress=None):
    """签名清单优先；每资源至多四次，所有传输共享预算，失败只清理本次 job。

    成功保留原六个字段，另附 size（实际字节数）、content_length（可为 None）。
    Content-Length 只用于完整性/进度提示，可信内容始终由签名摘要决定。
    """
    stage = 'preflight'
    job = None
    success = False
    failure = None
    last_progress = -1

    def report(percent):
        nonlocal last_progress
        if progress and percent > last_progress:
            try:
                progress(percent)
            except Exception:
                # UI 回调失败不是网络故障，不能因此重新下载或泄漏回调的异常文本。
                raise DownloadError('progress', 'progress-callback-failed', 'unknown') from None
            last_progress = percent

    try:
        if not configured():
            raise ValueError('release-signing-key-not-configured')
        if not isinstance(version, str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)?', version) or len(version) > 32:
            raise ValueError('invalid-release-version')
        if version_tuple(version) < version_tuple(installed_version):
            raise ValueError('update-downgrade-refused')
        arch = platform.machine()
        if arch not in ('arm64', 'x86_64'):
            raise ValueError('unsupported-architecture')
        base = 'https://github.com/tahoeliu/mdPreview/releases/download/v' + version + '/'
        transfers = _Transfers()
        report(0)
        stage = 'manifest'
        manifest = transfers.run(stage, lambda: transfers.read(base + 'SHA256SUMS', 1048576, stage))
        stage = 'signature'
        signature = transfers.run(stage, lambda: transfers.read(base + 'SHA256SUMS.sig', 80, stage))
        stage = 'manifest_verify'
        # signed_digest 先验签并严格解析完整清单；只在已验签但缺少精确架构时尝试 universal。
        for filename in (f'mdPreview-{version}-{arch}.zip', f'mdPreview-{version}-universal.zip'):
            try:
                expected = signed_digest(manifest, signature, filename)
                break
            except ValueError as error:
                if str(error) != 'asset-not-signed':
                    raise
        else:
            raise ValueError('compatible-zip-not-found')

        stage = 'staging'
        root = Path(staging)
        if root.is_symlink() or '..' in root.parts:
            raise ValueError('unsafe-staging-path')
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        root = root.resolve(strict=True)
        job = Path(tempfile.mkdtemp(prefix='signed-', dir=root))
        archive = job / filename
        stage = 'archive'

        def fetch_archive():
            # 重试从零开始，不续接旧 job、不拼接跨响应字节；每次都独立验证完整摘要。
            archive.unlink(missing_ok=True)
            with archive.open('xb') as output:
                digest, size, length = transfers.read(base + filename, _MAX_ARCHIVE, stage, output, report)
            if not hmac.compare_digest(digest, expected):
                # 无长度头的干净 EOF 也可能是截断；重取但绝不放宽摘要验证。
                raise DownloadError('digest', 'signed-digest-mismatch', retryable=True)
            return size, length

        size, length = transfers.run(stage, fetch_archive)
        report(96)
        (job / 'SHA256SUMS').write_bytes(manifest)
        (job / 'SHA256SUMS.sig').write_bytes(signature)
        stage = 'extract'
        app = extract_verified(archive, job / 'SHA256SUMS', job / 'SHA256SUMS.sig', job / 'verified')
        report(98)
        stage = 'bundle'
        verify_bundle(app, team_id, version)
        report(100)
        success = True
        return {'staging_app': str(app), 'version': version, 'archive': str(archive),
                'manifest': str(job / 'SHA256SUMS'), 'signature': str(job / 'SHA256SUMS.sig'),
                'dmg_path': '', 'size': size, 'content_length': length}
    except Exception as cause:
        failure = _error(cause, stage)
        raise failure from None
    finally:
        if job is not None and not success:
            try:
                shutil.rmtree(job)
            except OSError:
                if failure is not None:
                    failure.cleanup_failed = True
