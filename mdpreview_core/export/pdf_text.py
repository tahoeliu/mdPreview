"""修复 macOS 生成的 PDF 中 CJK 文本映射（ToUnicode）。

问题：macOS 的 PDF 引擎常把 PingFang 等字体的字形映射到“康熙部首/部首补充”码位（⽂ ⻚ ⽤ …），
而不是真正的汉字（文 页 用 …）。屏幕上看不出区别，但在 PDF 阅读器里搜索“文”找不到、复制出来的也是部首。

做法：
1. canonical(text) 把部首码位换成对应汉字（表由字体字形生成，见 cjk_radicals.py），用于在页面文本里定位标题、链接；
   部首与汉字都是单个 UTF-16 码元，所以字符串偏移保持对齐。
2. repair(data) 用“增量更新”追加修正后的 ToUnicode 对象：原有字节一个都不改，只在文件末尾追加新对象、
   新 xref 段和新 trailer（/Prev 指向旧 xref）。任何不认识的结构（xref 流、加密、间接 /Length 等）都原样返回。
"""
import re
import unicodedata
import zlib

from .cjk_radicals import RADICAL_TO_IDEOGRAPH

_TABLE = {chr(key): chr(value) for key, value in RADICAL_TO_IDEOGRAPH.items()}


def canonical_char(char):
    mapped = _TABLE.get(char)
    if mapped:
        return mapped
    if '豈' <= char <= '﫿':  # CJK 兼容汉字：NFKC 给出唯一的统一汉字
        folded = unicodedata.normalize('NFKC', char)
        if len(folded) == 1:
            return folded
    return char


def canonical(text):
    """长度不变的规范化：部首/兼容汉字 → 对应的统一汉字。"""
    return ''.join(canonical_char(char) for char in text)


def _canonical_hex(destination):
    """ToUnicode 目标串（UTF-16BE 十六进制）规范化；返回新的十六进制串。"""
    raw = bytes.fromhex(destination.decode('ascii'))
    if len(raw) % 2:
        raise ValueError('odd-length destination')
    text = raw.decode('utf-16-be')
    return canonical(text).encode('utf-16-be').hex().upper().encode('ascii')


_HEX = rb'<([0-9A-Fa-f]+)>'
_CHAR = re.compile(_HEX + rb'\s*<([0-9A-Fa-f]*)>')
_RANGE_SIMPLE = re.compile(_HEX + rb'\s*' + _HEX + rb'\s*<([0-9A-Fa-f]*)>')
_RANGE_ARRAY = re.compile(_HEX + rb'\s*' + _HEX + rb'\s*\[([^\]]*)\]')


def _parse_cmap(text):
    """返回 (head, entries, tail)；entries 为 [(源码十六进制串, 目标十六进制串)]。"""
    first = re.search(rb'begin(?:bfchar|bfrange)', text)
    ends = list(re.finditer(rb'end(?:bfchar|bfrange)', text))
    if not first or not ends:
        return None
    head, tail = text[:first.start()], text[ends[-1].end():]
    entries = []
    for block in re.finditer(rb'beginbfchar(.*?)endbfchar', text, re.S):
        entries.extend(_CHAR.findall(block.group(1)))
    for block in re.finditer(rb'beginbfrange(.*?)endbfrange', text, re.S):
        body = block.group(1)
        # 先处理数组形式，再处理三元组形式，避免互相误匹配。
        for low, high, items in _RANGE_ARRAY.findall(body):
            width = len(low)
            start, stop = int(low, 16), int(high, 16)
            values = re.findall(_HEX, items)
            if stop < start or stop - start + 1 != len(values):
                raise ValueError('malformed bfrange array')
            for offset, value in enumerate(values):
                entries.append((b'%0*X' % (width, start + offset), value))
        body = _RANGE_ARRAY.sub(b'', body)
        for low, high, destination in _RANGE_SIMPLE.findall(body):
            width = len(low)
            start, stop = int(low, 16), int(high, 16)
            if stop < start or stop - start > 65535:
                raise ValueError('malformed bfrange')
            base = bytes.fromhex(destination.decode('ascii'))
            if not base or len(base) % 2:
                raise ValueError('malformed destination')
            units = base.decode('utf-16-be')
            last, step = ord(units[-1]), 0
            for code in range(start, stop + 1):
                shifted = units[:-1] + chr(last + step)
                entries.append((b'%0*X' % (width, code), shifted.encode('utf-16-be').hex().upper().encode('ascii')))
                step += 1
    return head, entries, tail


def _rewrite_cmap(text):
    """规范化 CMap 中的目标字符；没有需要改的内容时返回 None。"""
    parsed = _parse_cmap(text)
    if parsed is None:
        return None
    head, entries, tail = parsed
    rewritten, changed = [], False
    for source, destination in entries:
        fixed = _canonical_hex(destination) if destination else destination
        changed = changed or fixed.upper() != destination.upper()
        rewritten.append((source, fixed))
    if not changed:
        return None
    blocks = []
    for index in range(0, len(rewritten), 100):  # PDF 规范：每个 bfchar 块最多 100 项
        chunk = rewritten[index:index + 100]
        blocks.append(b'%d beginbfchar\n' % len(chunk) + b''.join(b'<' + s + b'> <' + d + b'>\n' for s, d in chunk) + b'endbfchar\n')
    return head + b''.join(blocks) + tail


def _last_object(data, number):
    matches = list(re.finditer(rb'(?:^|[\r\n])%d 0 obj\b' % number, data))
    if not matches:
        raise ValueError('object not found')
    start = matches[-1].end()
    stream_at = data.find(b'stream', start)
    end_obj = data.find(b'endobj', start)
    if stream_at < 0 or (0 <= end_obj < stream_at):
        raise ValueError('not a stream object')
    dictionary = data[start:stream_at]
    length_match = re.search(rb'/Length\s+(\d+)(?!\s+\d+\s+R)', dictionary)
    if not length_match:
        raise ValueError('indirect or missing length')
    body_at = stream_at + len(b'stream')
    if data[body_at:body_at + 2] == b'\r\n':
        body_at += 2
    elif data[body_at:body_at + 1] == b'\n':
        body_at += 1
    else:
        raise ValueError('bad stream keyword')
    length = int(length_match.group(1))
    if data[body_at + length:body_at + length + 12].lstrip(b'\r\n ')[:9] != b'endstream':
        raise ValueError('length does not match stream end')
    return dictionary, data[body_at:body_at + length]


def _repair(data):
    tail = re.search(rb'startxref\s+(\d+)\s+%%EOF\s*$', data)
    if not tail or b'/Encrypt' in data:
        return data
    previous = int(tail.group(1))
    trailer_at = data.rfind(b'trailer', 0, tail.start())
    if trailer_at < 0 or data[previous:previous + 4] != b'xref':
        return data  # xref 流等现代结构：不处理
    trailer = data[trailer_at:tail.start()]
    size = int(re.search(rb'/Size\s+(\d+)', trailer).group(1))
    root = re.search(rb'/Root\s+(\d+\s+\d+\s+R)', trailer).group(1)
    info = re.search(rb'/Info\s+(\d+\s+\d+\s+R)', trailer)
    identifier = re.search(rb'/ID\s*\[.*?\]', trailer, re.S)
    numbers = sorted({int(n) for n in re.findall(rb'/ToUnicode\s+(\d+)\s+0\s+R', data)})
    replacements = []
    for number in numbers:
        try:
            dictionary, stream = _last_object(data, number)
            if b'/FlateDecode' in dictionary:
                if re.search(rb'/Filter\s*\[', dictionary) or b'/DecodeParms' in dictionary:
                    continue
                text = zlib.decompress(stream)
            elif b'/Filter' in dictionary:
                continue
            else:
                text = stream
            fixed = _rewrite_cmap(text)
        except (ValueError, zlib.error, UnicodeError):
            continue
        if fixed is not None:
            replacements.append((number, zlib.compress(fixed, 9)))
    if not replacements:
        return data
    output = bytearray(data if data.endswith(b'\n') else data + b'\n')
    offsets = []
    for number, payload in replacements:
        offsets.append((number, len(output)))
        output += b'%d 0 obj\n<< /Length %d /Filter /FlateDecode >>\nstream\n' % (number, len(payload)) + payload + b'\nendstream\nendobj\n'
    xref_at = len(output)
    output += b'xref\n'
    for number, offset in offsets:
        output += b'%d 1\n%010d 00000 n \n' % (number, offset)
    output += b'trailer\n<< /Size %d /Root %s' % (size, root)
    if info:
        output += b' /Info ' + info.group(1)
    if identifier:
        output += b' ' + identifier.group(0)
    output += b' /Prev %d >>\nstartxref\n%d\n%%%%EOF\n' % (previous, xref_at)
    return bytes(output)


def repair(data):
    """返回修复后的 PDF 字节；无需修复或结构不认识时原样返回，绝不抛出。"""
    try:
        return _repair(bytes(data))
    except (ValueError, AttributeError, TypeError, OverflowError, UnicodeError):
        return bytes(data)
