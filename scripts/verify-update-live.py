"""The packaged app must be able to reach the real update server.

Everything else about updating is tested offline with a stand-in server. This one check uses the
built app itself and the real network, because a packaged app does not behave like the source
tree: it carries its own Python and OpenSSL, whose default certificate folder is a path on the
build machine. Those defaults are deliberately pointed at nothing here, as on a user's Mac.
Nothing is installed: the app only looks up the latest version, in a throwaway data folder.
  .venv/bin/python scripts/verify-update-live.py --app path/to/mdPreview.app
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app', required=True)
    app = Path(parser.parse_args().app).resolve()
    with tempfile.TemporaryDirectory(prefix='update-live-') as folder:
        data = Path(folder).resolve()
        (data / 'config.json').write_text(json.dumps({'onboarded': True, 'default_handler_offered': True}))
        environment = {key: value for key, value in os.environ.items() if not key.startswith('MDPREVIEW_')}
        environment.update(MDPREVIEW_DATA_DIR=str(data), SSL_CERT_FILE='/nonexistent/cert.pem',
                           SSL_CERT_DIR='/nonexistent/certs')
        process = subprocess.Popen([str(app / 'Contents/MacOS/mdPreview')], env=environment,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline, state = time.monotonic() + 120, None
            while time.monotonic() < deadline and process.poll() is None:
                files = list((data / 'UpdateTransactions').glob('state*.json'))
                if files:
                    try:
                        state = json.loads(files[0].read_text())
                    except ValueError:
                        state = None
                    if state and (state.get('lastCompletedCheck') or state.get('version')
                                  or state.get('phase') in ('failed', 'retrying')):
                        break
                time.sleep(0.5)
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        summary = {key: (state or {}).get(key) for key in ('phase', 'version', 'error', 'code', 'stage')}
        reached = bool(state) and not state.get('error') and (state.get('lastCompletedCheck') or state.get('version'))
        if not reached:
            raise SystemExit('update live check FAILED: the packaged app could not look up the latest version: '
                             + json.dumps(summary))
        print('update live check passed: packaged app reached the update server', json.dumps(summary))


if __name__ == '__main__':
    main()
