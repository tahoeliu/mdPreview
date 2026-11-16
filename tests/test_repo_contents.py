"""What gets published to GitHub: source, resources, docs, and tests that a runner actually executes.

Local scratch (WorkSpace/, logs, one-off probes, working notes, personal paths, keys) stays on the
maintainer's machine. This suite runs with every other one (CI, the release build and
scripts/verify-all.sh), so a release cannot be cut while something local-only is committed.
See "What belongs in the repository" in dev/RELEASE.md.
"""
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LOCAL_ONLY_FOLDERS = ('WorkSpace/', 'outputs/', 'dev/history/', '.workbuddy/', '.claude/',
                      'node_modules/', '.venv/', 'test-results/', 'playwright-report/')
LOCAL_ONLY_NAMES = re.compile(r'(^|/)(\.DS_Store|\.env[^/]*|[^/]*\.(log|bak|tmp|orig|p12|key))$')
PUBLIC_KEYS = {'scripts/release-pubkey.pem'}
PRIVATE_KEY = re.compile(r'BEGIN [A-Z ]*PRIVATE KEY')
HOME_PATH = re.compile(r'/Users/([A-Za-z0-9._-]+)')
PLACEHOLDER_HOMES = {'me', 'SECRET', 'PRIVATE', 'private-user', 'someone'}

# Files in scripts/ and tests/ that no runner, workflow, script or document mentions.
# Each one is here on purpose, with the reason it is published anyway.
STANDALONE = {
    'scripts/__init__.py': 'lets the suites import scripts.install_update',
    'scripts/install-local.sh': 'maintainer tool: put a local build into /Applications',
    'scripts/install_signed.py': 'command-line install of a published, signed release',
    'tests/generate_output_fixtures.py': 'regenerates the synthetic samples in tests/fixtures/output',
}
DISCOVERED = re.compile(r'^tests/(test_[^/]+\.(py|js)|e2e/[^/]+\.spec\.js)$')
NOT_SEARCHED = ('vendor/', 'docs/images/', 'package-lock.json', 'CHANGELOG.md', 'THIRD_PARTY_NOTICES.md')


def tracked():
    result = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, capture_output=True)
    if result.returncode != 0:
        return None
    return [name for name in result.stdout.decode().split('\0') if name and (ROOT / name).is_file()]


def text(name):
    data = (ROOT / name).read_bytes()
    return None if b'\0' in data[:8192] else data.decode('utf-8', 'replace')


class RepositoryContents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = tracked()
        if cls.files is None:
            raise unittest.SkipTest('not a git checkout')

    def test_no_local_only_folders_or_files(self):
        stray = [name for name in self.files
                 if name.startswith(LOCAL_ONLY_FOLDERS) or LOCAL_ONLY_NAMES.search(name)
                 or (name.endswith('.pem') and name not in PUBLIC_KEYS)]
        self.assertEqual(stray, [], 'local-only files are committed')

    def test_no_private_keys_or_personal_paths(self):
        problems = []
        for name in self.files:
            content = text(name)
            if content is None:
                continue
            if PRIVATE_KEY.search(content):
                problems.append(f'{name}: private key')
            homes = set(HOME_PATH.findall(content)) - PLACEHOLDER_HOMES
            if homes:
                problems.append(f'{name}: personal path /Users/{sorted(homes)[0]}')
        self.assertEqual(problems, [])

    def test_every_script_and_test_helper_is_used(self):
        candidates = [name for name in self.files
                      if re.match(r'^(scripts|tests)/[^/]+$', name) and not DISCOVERED.match(name)]
        searchable = {name: text(name) for name in self.files if not name.startswith(NOT_SEARCHED)}
        unused = [name for name in candidates if name not in STANDALONE and not any(
            content and Path(name).name in content
            for other, content in searchable.items() if other != name)]
        self.assertEqual(unused, [], 'nothing runs or mentions these; wire them in, list them in '
                                     'STANDALONE with a reason, or keep them out of the repository')
        self.assertEqual(sorted(set(STANDALONE) - set(self.files)), [], 'STANDALONE lists missing files')


if __name__ == '__main__':
    unittest.main(verbosity=2)
