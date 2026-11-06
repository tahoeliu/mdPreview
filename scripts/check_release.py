"""Reproducible source/resource/build gates. Ad-hoc distribution is intentional."""
import argparse
import ast
import hashlib
import json
import plistlib
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from mdpreview_core.release import version_tuple, verify_bundle

def check_source():
    version=(ROOT/'VERSION').read_text().strip();version_tuple(version)
    if json.loads((ROOT/'package.json').read_text())['version']!=version:raise ValueError('Package and app versions differ')
    for path in [ROOT/'mdPreview.py',*list((ROOT/'mdpreview_core').rglob('*.py'))]:ast.parse(path.read_text())
    checks=json.loads((ROOT/'vendor/checksums.json').read_text())
    for file,digest in checks.items():
        if hashlib.sha256((ROOT/file).read_bytes()).hexdigest()!=digest:raise ValueError('Vendored asset differs: '+file)
    for file in ['app.js','frontend/bridge.js','frontend/output/prepare.js','frontend/output/plaintext.js','frontend/document-session.js','frontend/markdown-pipeline.js','frontend/image-viewer.js']:subprocess.run(['node','--check',str(ROOT/file)],check=True)
    for file in ['index.html','css/tokens.css','css/content.css','css/app.css','css/print.css','release-policy.json','VERSION']:
        if not (ROOT/file).is_file():raise ValueError('Missing resource: '+file)
    print('Source release gates PASS')

def check_app(path):
    path=Path(path);verify_bundle(path,expected_version=(ROOT/'VERSION').read_text().strip())
    resources=path/'Contents/Resources'
    for file in ['index.html','css/tokens.css','css/content.css','css/app.css','css/print.css','app.js','purify.min.js','marked-footnote.umd.js','frontend/bridge.js','frontend/output/prepare.js','frontend/output/plaintext.js','frontend/document-session.js','frontend/markdown-pipeline.js','frontend/image-viewer.js','release-policy.json','VERSION']:
        if not (resources/file).is_file():raise ValueError('Missing packaged resource: '+file)
    with (path/'Contents/Info.plist').open('rb') as stream:info=plistlib.load(stream)
    if info.get('NSAppTransportSecurity',{}).get('NSAllowsArbitraryLoads'):raise ValueError('ATS is globally disabled')
    print('Application identity, resources and code signature PASS (ad-hoc distribution)')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',action='store_true');parser.add_argument('--app')
    args=parser.parse_args()
    if args.source:check_source()
    if args.app:check_app(args.app)
