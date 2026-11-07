"""Isolated native WKWebView test; no application install or personal data writes."""
import os
import sys
import pathlib
import threading
root = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.environ['MDPREVIEW_DATA_DIR'] = str(root / 'WorkSpace/outputs/native-image-viewer')
os.environ['MDPREVIEW_DISABLE_UPDATES'] = '1'
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
data = pathlib.Path(os.environ['MDPREVIEW_DATA_DIR'])
data.mkdir(exist_ok=True)
fixture = data / 'native-fixture.txt'
fixture.write_text('Isolated native test\n')
(data / 'native-image.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#edf3ff"/></svg>')
base = (root / 'tests/native-check.js').read_text()
extra = (root / 'tests/native-image-viewer.js').read_text()
script = base.replace('    await pywebview.api.native_integrity_completed({success:true, checks});', extra + '\n    await pywebview.api.native_integrity_completed({success:true, checks});').replace('String(error && error.stack || error)', 'String(error) + " | " + String(error && error.stack || "")')
import mdPreview as app

def test_hook(window):
    def execute():
        if not app._UI_READY.wait(30):
            os._exit(5)
        app._dispatch_js_to(window, script)
    threading.Thread(target=execute, daemon=True).start()

app._maybe_run_selftest = test_hook
sys.argv = [str(root / 'mdPreview.py'), str(fixture), '--selftest-integrity']
app.main()
