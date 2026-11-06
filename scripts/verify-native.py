"""Run outside restricted execution contexts; never touch the installed app/data."""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

root=Path(__file__).resolve().parent.parent
parser=argparse.ArgumentParser();parser.add_argument('--app',default=str(root/'WorkSpace/dist/release-1.5.0/mdPreview.app'))
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
print('Native WKWebView save/export/Unicode/quit verification PASS; evidence: '+str(data))
