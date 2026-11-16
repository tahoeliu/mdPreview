"""The packaged app must be able to reach the real update server.

Everything else about updating is tested offline with a stand-in server. This one check uses the
built app itself and the real network, because a packaged app does not behave like the source
tree: it carries its own Python and OpenSSL, whose default certificate folder is a path on the
build machine. Those defaults are deliberately pointed at nothing here, as on a user's Mac.
Nothing is installed and no window opens: the app only looks up the latest version.
  .venv/bin/python scripts/verify-update-live.py --app path/to/mdPreview.app
"""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app', required=True)
    app = Path(parser.parse_args().app).resolve()
    environment = {key: value for key, value in os.environ.items() if not key.startswith('MDPREVIEW_')}
    environment.update(SSL_CERT_FILE='/nonexistent/cert.pem', SSL_CERT_DIR='/nonexistent/certs')
    try:
        result = subprocess.run([str(app / 'Contents/MacOS/mdPreview'), '--update-check-selftest'],
                                env=environment, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        raise SystemExit('update live check FAILED: the packaged app has no --update-check-selftest entry '
                         '(built before this gate existed) or never answered') from None
    try:
        answer = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        answer = {'error': 'no-answer', 'code': result.stderr.strip()[-200:]}
    if result.returncode != 0 or not re.fullmatch(r'[0-9]+(\.[0-9]+){2,3}', str(answer.get('latest', ''))):
        raise SystemExit('update live check FAILED: the packaged app could not look up the latest version: '
                         + json.dumps(answer))
    print('update live check passed: packaged app reached the update server, latest is', answer['latest'])


if __name__ == '__main__':
    main()
