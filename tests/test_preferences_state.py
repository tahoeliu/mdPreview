import unittest
from mdpreview_core.settings import settings, validated
from mdpreview_core.reading_state import remember, position_key

class PreferencesTests(unittest.TestCase):
    def test_offline(self):
        self.assertFalse(settings({})['auto_update'])
        self.assertEqual(settings({})['remote_images'], 'ask')
        with self.assertRaises(ValueError): validated({'font_size': True})
        self.assertEqual(validated({'unknown': 3}), {})

    def test_lru(self):
        values = {}
        for n in range(301):
            values = remember(values, '/test/'+str(n), {'ratio': .5, 'headingId': 'h'})
        self.assertEqual(len(values), 300)
        self.assertNotIn(position_key('/test/0'), values)
        self.assertFalse(any('/test' in key for key in values))

if __name__ == '__main__': unittest.main()
