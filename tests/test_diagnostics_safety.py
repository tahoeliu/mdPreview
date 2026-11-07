import io
import json
import unittest
import zipfile
from mdpreview_core.diagnostics import archive, record, issue_url


class DiagnosticsSafety(unittest.TestCase):
    def test_allowlist(self):
        secret = '/Users/private-user/private-document-body'
        record(secret, error=secret)
        record('uncaught', error=secret)
        config = {'recent_files': [secret], 'session': [secret], 'reading_positions': {secret: secret},
                  'settings': {'language': secret, 'font_size': secret, 'remote_images': 'ask', 'extra': secret}}
        with zipfile.ZipFile(io.BytesIO(archive('1.5.0', config))) as bundle:
            self.assertEqual(set(bundle.namelist()), {'environment.json', 'config.json', 'events.json'})
            for name in bundle.namelist():
                self.assertNotIn(secret, bundle.read(name).decode())
            self.assertEqual(json.loads(bundle.read('config.json'))['remote_images'], 'ask')
        self.assertNotIn('private-user', issue_url(secret))


if __name__ == '__main__':
    unittest.main()
