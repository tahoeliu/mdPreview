"""Detached updater. Runs from a copied standard-library-only helper directory."""
import argparse
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from mdpreview_core.release import transactional_install, verify_bundle, wait_for_exit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', required=True)
    args = parser.parse_args()
    plan = json.loads(Path(args.plan).read_text())
    logging.basicConfig(filename=plan['log'], level=logging.INFO)
    wait_for_exit(plan['pid'])
    marker = Path(plan['ready'])
    marker.unlink(missing_ok=True)
    def launch(app):
        subprocess.run(['open', '-n', str(app), '--args', '--update-ready', str(marker)], check=True, timeout=10)
    def ready(app):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if marker.is_file():
                try:
                    data = json.loads(marker.read_text())
                    if data.get('version') == plan['version'] and isinstance(data.get('pid'), int):
                        os.kill(data['pid'], 0)
                        return True
                except (ValueError, OSError):
                    pass
            time.sleep(0.1)
        # Only terminate the executable at this destination before rollback.
        subprocess.run(['pkill', '-f', str(app / 'Contents/MacOS/mdPreview')], capture_output=True)
        return False
    try:
        transactional_install(plan['staging'], plan['destination'],
                              lambda app: verify_bundle(app, plan['teamId'], plan['version']), launch, ready)
        logging.info('Update ready: %s', plan['version'])
    except Exception:
        logging.exception('Update failed; previous application restored when possible')
        subprocess.run(['open', plan['destination']], capture_output=True, timeout=10)
        raise


if __name__ == '__main__':
    main()
