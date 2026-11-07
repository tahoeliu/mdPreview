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
    for file in ['app.js','frontend/bridge.js','frontend/output/prepare.js','frontend/output/plaintext.js','frontend/math.js','frontend/reading.js','frontend/reading-progress.js','frontend/settings.js','frontend/editor.js','frontend/i18n.js','frontend/performance.js','frontend/onboarding.js','frontend/headless.js','frontend/syntax.js','frontend/tables.js','frontend/updates.js','frontend/find.js','frontend/paste.js','frontend/outline.js','frontend/output.js','frontend/rendered-editing.js','frontend/conversion.js','frontend/rendering.js','frontend/feedback.js','frontend/save-dialogs.js','frontend/csp-api.js','frontend/output/raster.js','frontend/output/docx.js','frontend/output/richtext.js','frontend/document-session.js','frontend/markdown-pipeline.js','frontend/image-viewer.js']:subprocess.run(['node','--check',str(ROOT/file)],check=True)
    for file in ['index.html','css/tokens.css','css/content.css','css/app.css','css/print.css','release-policy.json','VERSION','CHANGELOG.md','THIRD_PARTY_NOTICES.md','frontend/en.json','frontend/zh-Hans.json','frontend/zh-Hant.json','frontend/shortcuts.json','frontend/welcome.json']:
        if not (ROOT/file).is_file():raise ValueError('Missing resource: '+file)
    print('Source release gates PASS')

def check_app(path):
    path=Path(path);verify_bundle(path,expected_version=(ROOT/'VERSION').read_text().strip())
    resources=path/'Contents/Resources'
    for file in ['index.html','css/tokens.css','css/content.css','css/app.css','css/print.css','app.js','frontend/bridge.js','frontend/output/prepare.js','frontend/output/plaintext.js','frontend/math.js','frontend/reading.js','frontend/reading-progress.js','frontend/settings.js','frontend/editor.js','frontend/i18n.js','frontend/performance.js','frontend/onboarding.js','frontend/headless.js','frontend/syntax.js','frontend/tables.js','frontend/updates.js','frontend/find.js','frontend/paste.js','frontend/outline.js','frontend/output.js','frontend/rendered-editing.js','frontend/conversion.js','frontend/rendering.js','frontend/feedback.js','frontend/save-dialogs.js','frontend/csp-api.js','frontend/output/raster.js','frontend/output/docx.js','frontend/output/richtext.js','frontend/document-session.js','frontend/markdown-pipeline.js','frontend/image-viewer.js','release-policy.json','VERSION','CHANGELOG.md','THIRD_PARTY_NOTICES.md','frontend/en.json','frontend/zh-Hans.json','frontend/zh-Hant.json','frontend/shortcuts.json','frontend/welcome.json']:
        if not (resources/file).is_file():raise ValueError('Missing packaged resource: '+file)
    manifest=json.loads((ROOT/'vendor/manifest.json').read_text())
    for library in manifest['libraries']:
        for asset in library['files']:
            file=resources/asset['target']
            if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=asset['sha256']:
                raise ValueError('Packaged vendor mismatch: '+asset['target'])
    with (path/'Contents/Info.plist').open('rb') as stream:info=plistlib.load(stream)
    if info.get('NSAppTransportSecurity',{}).get('NSAllowsArbitraryLoads'):raise ValueError('ATS is globally disabled')
    print('Application identity, resources and code signature PASS (ad-hoc distribution)')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',action='store_true');parser.add_argument('--app')
    args=parser.parse_args()
    if args.source:check_source()
    if args.app:check_app(args.app)
