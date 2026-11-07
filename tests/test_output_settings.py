import sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import mdPreview as mv

class SettingsTests(unittest.TestCase):
    def test_persist_and_validate(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'WorkSpace/cache') as directory:
            with patch.object(mv,'CONFIG_FILE',str(Path(directory)/'config.json')), patch.object(mv,'LEGACY_CONFIG_FILE',str(Path(directory)/'old.json')), patch.object(mv,'APP_SUPPORT_DIR',directory):
                api=mv.MarkdownAPI()
                self.assertEqual(api.get_output_settings()['font'],'normal')
                self.assertTrue(api.set_output_settings({'paper':'letter','page_numbers':False})['success'])
                self.assertEqual(mv.MarkdownAPI().get_output_settings()['paper'],'letter')
                self.assertFalse(api.get_output_settings()['page_numbers'])
                self.assertFalse(api.set_output_settings({'paper':'evil'})['success'])
                self.assertFalse(api.set_output_settings({'page_numbers':'false'})['success'])
                self.assertEqual(api.get_output_settings()['paper'],'letter')

if __name__=='__main__': unittest.main()
