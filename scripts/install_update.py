"""Detached updater. Runs from a copied standard-library-only helper directory."""
import argparse
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from mdpreview_core.release import transactional_install, verify_bundle, wait_for_exit, check_installation_identity, check_startup_snapshot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', required=True)
    args = parser.parse_args()
    plan = json.loads(Path(args.plan).read_text())
    if any(plan['destinationIdentity'].get(key) != value for key, value in plan['startupIdentity'].items()):
        raise ValueError('startup-plan-identity-mismatch')
    logging.basicConfig(filename=plan['log'], level=logging.INFO)
    from mdpreview_core.release_zip import extract_verified
    import uuid
    staged = extract_verified(plan['archive'], plan['manifest'], plan['signature'],
                              Path(plan['archive']).parent / ('helper-' + uuid.uuid4().hex))
    verify_bundle(staged, plan['teamId'], plan['version'])
    check_startup_snapshot(plan['destination'], plan['startupIdentity'])
    check_installation_identity(plan['destination'], plan['destinationIdentity'])
    wait_for_exit(plan['pid'])
    check_startup_snapshot(plan['destination'], plan['startupIdentity'])
    check_installation_identity(plan['destination'], plan['destinationIdentity'])
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
        transactional_install(staged, plan['destination'],
                              lambda app: verify_bundle(app, plan['teamId'], plan['version']), launch, ready,
                              destination_identity=plan['destinationIdentity'])
        logging.info('Update ready: %s', plan['version'])
    except Exception:
        logging.exception('Update failed; previous application restored when possible')
        subprocess.run(['open', plan['destination']], capture_output=True, timeout=10)
        raise


if __name__ == '__main__':
    main()
