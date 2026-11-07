"""Run outside restricted execution contexts; never touch the installed app/data."""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

root=Path(__file__).resolve().parent.parent
parser=argparse.ArgumentParser();parser.add_argument('--app',default=str(root/'WorkSpace/dist'/('release-'+(root/'VERSION').read_text().strip())/'mdPreview.app'))
args=parser.parse_args();app=Path(args.app)
data=root/'WorkSpace/native-verification'/str(time.time_ns());data.mkdir(parents=True)
source=data/'native.md';source.write_text('# Native verification\n\nInitial document',encoding='utf-8')
environment=dict(os.environ,MDPREVIEW_DATA_DIR=str(data),MDPREVIEW_DISABLE_UPDATES='1')
output=(data/'process.log').open('w')
process=subprocess.Popen([str(app/'Contents/MacOS/mdPreview'),str(source),'--selftest-integrity'],env=environment,stdout=output,stderr=output)
try:
    process.wait(timeout=90)
except subprocess.TimeoutExpired:
    process.kill();process.wait();raise SystemExit('FAIL: native application did not exit; '+str(data))
result_path=data/'native-result.json'
if not result_path.is_file():raise SystemExit('BLOCKED/FAIL: application never completed native tests; '+str(data))
result=json.loads(result_path.read_text())
if not result.get('success'):raise SystemExit('FAIL: '+json.dumps(result,ensure_ascii=False))
if 'NEW CONTENT' not in source.read_text():raise SystemExit('FAIL: saved Markdown missing latest source')
if 'NEW CONTENT' not in (data/'export.html').read_text():raise SystemExit('FAIL: exported HTML is stale')
if not (data/'export.pdf').read_bytes().startswith(b'%PDF'):raise SystemExit('FAIL: invalid PDF output')
from Foundation import NSURL
from Quartz import PDFDocument
pdf=PDFDocument.alloc().initWithURL_(NSURL.fileURLWithPath_(str(data/'export.pdf')))
pdf_text=str(pdf.string()) if pdf is not None else ''
if 'NEW CONTENT' not in pdf_text:raise SystemExit('FAIL: PDF missing latest document content')
for ui_text in ['mdSource', 'mdPreview', 'Saved', '已保存']:
    if ui_text in pdf_text:raise SystemExit('FAIL: PDF contains application UI: '+ui_text)
if process.returncode!=0:raise SystemExit('FAIL: abnormal native quit '+str(process.returncode))
# 同一个候选包执行 CLI，不安装应用；失败或无产物必须阻断门禁。
long_source=data/'cli-long.md'
long_source.write_text(('# CLI 多页输出\n\n' + '正文用于验证分页与文本完整性。\n\n' * 30) * 8, encoding='utf-8')
cli=app/'Contents/Resources/bin/mdpreview'
if not os.access(cli, os.X_OK):raise SystemExit('FAIL: packaged CLI is not executable')
cli_env=dict(environment, MDPREVIEW_APP=str(app))
for fmt in ('pdf', 'html', 'docx', 'txt', 'png'):
    target=data/('cli-output.'+fmt)
    completed=subprocess.run([str(cli), 'export', str(long_source), '--to', fmt, '-o', str(target)],
                             env=cli_env, capture_output=True, timeout=190)
    if completed.returncode!=0:raise SystemExit('FAIL: CLI '+fmt+' exit '+str(completed.returncode))
    if fmt=='png':
        candidates=list(data.glob('cli-output*.png'))
        if not candidates or any(not item.read_bytes().startswith(b'\x89PNG\r\n\x1a\n') for item in candidates):
            raise SystemExit('FAIL: CLI PNG missing or invalid')
    elif not target.is_file() or target.stat().st_size==0:raise SystemExit('FAIL: CLI missing '+fmt)
    if fmt=='pdf':
        document=PDFDocument.alloc().initWithURL_(NSURL.fileURLWithPath_(str(target)))
        if document is None or document.pageCount()<=1:raise SystemExit('FAIL: CLI PDF must have multiple pages')
        if '正文用于验证分页' not in str(document.string()):raise SystemExit('FAIL: CLI PDF text missing')
    if fmt=='docx':
        import zipfile
        with zipfile.ZipFile(target) as archive:
            if 'word/document.xml' not in archive.namelist():raise SystemExit('FAIL: CLI OOXML missing')
invalid=subprocess.run([str(cli), 'export', str(long_source), '--to', 'invalid'], env=cli_env, capture_output=True, timeout=10)
if invalid.returncode!=1:raise SystemExit('FAIL: CLI argument exit code')
print('Native WKWebView and CLI output verification PASS; evidence: '+str(data))
print('Window visibility and zero network requests still require independent observation evidence.')
