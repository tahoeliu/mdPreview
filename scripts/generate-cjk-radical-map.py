"""重新生成 mdpreview_core/export/cjk_radicals.py（仅 macOS，开发期工具）。

背景：macOS 的 PDF 引擎把 PingFang 等字体的字形写进 ToUnicode 时，常选“康熙部首/部首补充”码位
（如 ⽂ U+2F42、⻚ U+2EDA）而不是真正的汉字（文 U+6587、页 U+9875）。肉眼看一样，但搜索、复制都对不上。
这里用字体自己的字形表求出权威对应：只收录“与某个且仅一个 CJK 统一汉字共用同一字形”的部首；
对康熙部首同时断言与 Unicode NFKC 结果一致。用法：
  .venv/bin/python scripts/generate-cjk-radical-map.py
"""
import unicodedata
from pathlib import Path

import AppKit
import Foundation

FONT = 'PingFangSC-Regular'
OUT = Path(__file__).resolve().parents[1] / 'mdpreview_core' / 'export' / 'cjk_radicals.py'


def main():
    font = AppKit.NSFont.fontWithName_size_(FONT, 12)
    if font is None:
        raise SystemExit(f'font {FONT} not available')
    storage = AppKit.NSTextStorage.alloc().init()
    layout = AppKit.NSLayoutManager.alloc().init()
    container = AppKit.NSTextContainer.alloc().init()
    layout.addTextContainer_(container)
    storage.addLayoutManager_(layout)

    def glyph(codepoint):
        storage.setAttributedString_(Foundation.NSAttributedString.alloc().initWithString_attributes_(
            chr(codepoint), {AppKit.NSFontAttributeName: font}))
        layout.ensureLayoutForTextContainer_(container)
        return layout.glyphAtIndex_(0) if layout.numberOfGlyphs() else None

    by_glyph = {}
    for codepoint in range(0x4E00, 0xA000):
        value = glyph(codepoint)
        if value:
            by_glyph.setdefault(value, []).append(codepoint)
    table = {}
    for radical in list(range(0x2E80, 0x2EF4)) + list(range(0x2F00, 0x2FD6)):
        value = glyph(radical)
        candidates = by_glyph.get(value, []) if value else []
        if len(candidates) != 1:
            continue
        target = candidates[0]
        if 0x2F00 <= radical <= 0x2FD5:
            nfkc = unicodedata.normalize('NFKC', chr(radical))
            assert len(nfkc) == 1 and ord(nfkc) == target, (hex(radical), hex(target), nfkc)
        table[radical] = target
    lines = ['"""CJK 部首 → 对应汉字（由 scripts/generate-cjk-radical-map.py 依据 PingFang SC 字形表生成，请勿手改）。',
             '',
             '用于修复 macOS 生成的 PDF 中 ToUnicode 指向部首码位的问题，使搜索和复制得到真正的汉字。',
             '"""',
             'RADICAL_TO_IDEOGRAPH = {']
    lines += [f'    0x{key:04X}: 0x{value:04X},  # {chr(key)} -> {chr(value)}' for key, value in sorted(table.items())]
    lines.append('}')
    OUT.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'wrote {len(table)} mappings to {OUT}')


if __name__ == '__main__':
    main()
