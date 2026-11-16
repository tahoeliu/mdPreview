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
        update = {'installable': True, 'journal': 'recovery-required', 'unsettled': True, secret: 'x',
                  'state': {'phase': 'failed', 'version': '2.0.9', 'code': 'quit-gap-inconclusive',
                            'retryCount': 2, 'pending': True, 'detail': secret, 'http': None,
                            'nested': {'path': secret}, 'big': 10 ** 9}}
        with zipfile.ZipFile(io.BytesIO(archive('1.5.0', config, update))) as bundle:
            self.assertEqual(set(bundle.namelist()), {'environment.json', 'config.json', 'events.json', 'update.json'})
            summary = json.loads(bundle.read('update.json'))
            self.assertEqual(summary['journal'], 'recovery-required')
            self.assertEqual(summary['state']['code'], 'quit-gap-inconclusive')
            self.assertEqual(summary['state']['version'], '2.0.9')
            self.assertEqual(summary['state']['retryCount'], 2)
            self.assertEqual(summary['state']['detail'], 'redacted')
            self.assertEqual(summary['state']['big'], 'redacted')
            self.assertIs(summary['unsettled'], True)
            for name in bundle.namelist():
                self.assertNotIn(secret, bundle.read(name).decode())
            self.assertEqual(json.loads(bundle.read('config.json'))['remote_images'], 'ask')
        self.assertNotIn('private-user', issue_url(secret))
        with zipfile.ZipFile(io.BytesIO(archive('1.5.0', config))) as bundle:
            self.assertEqual(json.loads(bundle.read('update.json')), {})


if __name__ == '__main__':
    unittest.main()
