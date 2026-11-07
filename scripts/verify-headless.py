"""对已构建应用做真实无头导出验收：五种格式、产物结构与质量断言。

用法：.venv/bin/python scripts/verify-headless.py --app path/to/mdPreview.app
每种格式 90 秒内必须成功；产物结构（分页、书签、页码、Word 标题样式、HTML 自包含等）必须正确。
"""
import argparse
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests' / 'fixtures' / 'output'


def export(app, source, fmt, target):
    result = subprocess.run(['bash', str(ROOT / 'scripts' / 'mdpreview'), 'export', str(source), '--to', fmt, '-o', str(target)],
                            env={'MDPREVIEW_APP': str(app), 'PATH': '/usr/bin:/bin'}, capture_output=True, text=True, timeout=120)
    if result.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        raise AssertionError(f'{source.name} -> {fmt} failed (exit {result.returncode}): {result.stderr.strip()}')


def check_pdf(path, minimum_pages, bookmarks):
    import Foundation
    import Quartz
    document = Quartz.PDFDocument.alloc().initWithURL_(Foundation.NSURL.fileURLWithPath_(str(path)))
    assert document is not None, 'PDF cannot be opened'
    pages = document.pageCount()
    assert pages >= minimum_pages, f'expected >= {minimum_pages} pages, got {pages}'
    for index in range(pages):
        text = (document.pageAtIndex_(index).string() or '').strip()
        assert f'{index + 1} / {pages}' in text, f'page {index + 1} footer missing: {text[-30:]!r}'
    outline = document.outlineRoot()
    if bookmarks:
        assert outline is not None and outline.numberOfChildren() > 0, 'PDF outline missing'
    title = document.documentAttributes().get(Quartz.PDFDocumentTitleAttribute)
    assert title, 'PDF title missing'
    text = str(document.string() or '')
    # macOS 常把 文/页 等字存成部首码位；出现任何部首说明搜索与复制会出错。
    radicals = sorted({c for c in text if 0x2E80 <= ord(c) <= 0x2FD5})
    assert not radicals, 'PDF text contains CJK radical lookalikes: ' + ''.join(radicals)
    return pages


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app', required=True)
    args = parser.parse_args()
    app = Path(args.app).resolve()
    assert (app / 'Contents/MacOS/mdPreview').is_file(), 'not an application bundle'
    with tempfile.TemporaryDirectory(prefix='verify-headless-') as folder:
        out = Path(folder)
        source = FIXTURES / 'zh-longform.md'
        for fmt in ('txt', 'html', 'docx', 'pdf', 'png'):
            export(app, source, fmt, out / f'long.{fmt}')
        pages = check_pdf(out / 'long.pdf', 2, bookmarks=True)
        import Foundation
        import Quartz
        long_text = str(Quartz.PDFDocument.alloc().initWithURL_(Foundation.NSURL.fileURLWithPath_(str(out / 'long.pdf'))).string())
        assert '正文' in long_text and '阅读工具' in long_text, 'Chinese body text is not searchable in the PDF'
        document = zipfile.ZipFile(out / 'long.docx').read('word/document.xml').decode()
        assert 'altChunk' not in document, 'DOCX still uses altChunk'
        assert 'w:val="Heading1"' in document and 'w:val="Heading2"' in document, 'DOCX lacks heading styles'
        # 第二个独立的 OOXML 解析器（macOS 自带 textutil）必须能读出正文。
        plain = subprocess.run(['textutil', '-convert', 'txt', '-stdout', str(out / 'long.docx')], capture_output=True, text=True, timeout=60)
        assert plain.returncode == 0 and '阅读工具' in plain.stdout, 'textutil cannot read the DOCX body'
        for fixture, check in (('wide-table', lambda z, x: '<w:tbl>' in x), ('math', lambda z, x: any(n.startswith('word/media/') for n in z.namelist())),
                               ('mermaid', lambda z, x: any(n.startswith('word/media/') for n in z.namelist()))):
            export(app, FIXTURES / f'{fixture}.md', 'docx', out / f'{fixture}.docx')
            archive = zipfile.ZipFile(out / f'{fixture}.docx')
            assert check(archive, archive.read('word/document.xml').decode()), f'DOCX for {fixture} lacks its table/images'
            assert subprocess.run(['textutil', '-convert', 'txt', '-stdout', str(out / f'{fixture}.docx')], capture_output=True, timeout=60).returncode == 0
        export(app, FIXTURES / 'footnotes.md', 'docx', out / 'footnotes.docx')
        notes_doc = zipfile.ZipFile(out / 'footnotes.docx').read('word/document.xml').decode()
        ids = re.findall(r'<w:footnoteReference w:id="(\d+)"', notes_doc)
        assert len(ids) >= 2 and len(set(ids)) == len(ids), 'footnote references must have unique ids'
        html = (out / 'long.html').read_text(encoding='utf-8')
        assert '<script' not in html and '<link' not in html, 'HTML is not self-contained'
        assert re.search(r'<html[^>]*lang="zh', html), 'HTML lang not detected'
        text = (out / 'long.txt').read_text(encoding='utf-8')
        assert '##' not in text and '**' not in text, 'TXT still contains Markdown markup'
        png = (out / 'long.png').read_bytes()
        assert png[:8] == b'\x89PNG\r\n\x1a\n', 'PNG signature invalid'
        # Mermaid 与公式必须真的渲染，而不是原样输出源码。
        export(app, FIXTURES / 'math.md', 'pdf', out / 'math.pdf')
        export(app, FIXTURES / 'mermaid.md', 'pdf', out / 'mermaid.pdf')
        export(app, FIXTURES / 'wide-table.md', 'pdf', out / 'wide.pdf')
        math_pages = check_pdf(out / 'math.pdf', 1, bookmarks=False)
        check_pdf(out / 'mermaid.pdf', 1, bookmarks=False)
        wide_pages = check_pdf(out / 'wide.pdf', 2, bookmarks=False)
        # 已存在的输出必须被拒绝，且不被改动。
        before = (out / 'long.txt').read_bytes()
        refused = subprocess.run(['bash', str(ROOT / 'scripts' / 'mdpreview'), 'export', str(source), '--to', 'txt', '-o', str(out / 'long.txt')],
                                 env={'MDPREVIEW_APP': str(app), 'PATH': '/usr/bin:/bin'}, capture_output=True, text=True, timeout=60)
        assert refused.returncode != 0 and (out / 'long.txt').read_bytes() == before, 'existing output was not protected'
    print(f'headless acceptance passed: long={pages} pages, math={math_pages}, wide-table={wide_pages}')


if __name__ == '__main__':
    try:
        main()
    except AssertionError as error:
        print('headless acceptance FAILED:', error, file=sys.stderr)
        raise SystemExit(1)
