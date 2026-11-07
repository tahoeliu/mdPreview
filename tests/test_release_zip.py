import tempfile
import unittest
import zipfile
from pathlib import Path
from mdpreview_core.release_zip import extract


class ZipSafety(unittest.TestCase):
    def test_traversal_and_duplicate(self):
        for members in [['../escape'], ['/absolute'], ['mdPreview.app/../escape'],
                        ['mdPreview.app/A', 'mdPreview.app/a'],
                        ['mdPreview.app/é', 'mdPreview.app/e\u0301']]:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with zipfile.ZipFile(root/'input.zip', 'w') as archive:
                    for name in members:
                        archive.writestr(name, 'data')
                with self.assertRaises(ValueError):
                    extract(root/'input.zip', root/'output')
                self.assertFalse((root/'output').exists())

    def test_symlink_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with zipfile.ZipFile(root/'input.zip', 'w') as archive:
                member = zipfile.ZipInfo('mdPreview.app/link')
                member.create_system = 3
                member.external_attr = 0o120777 << 16
                archive.writestr(member, '../../escape')
            with self.assertRaises(ValueError):
                extract(root/'input.zip', root/'output')

    def test_symlink_chain_and_cycle(self):
        for links in [
            {'mdPreview.app/a/b': '..', 'mdPreview.app/link': 'a/b/../../outside'},
            {'mdPreview.app/a': 'b', 'mdPreview.app/b': 'a'},
        ]:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with zipfile.ZipFile(root/'input.zip', 'w') as archive:
                    for name, target in links.items():
                        member = zipfile.ZipInfo(name)
                        member.create_system = 3
                        member.external_attr = 0o120777 << 16
                        archive.writestr(member, target)
                with self.assertRaises(ValueError):
                    extract(root/'input.zip', root/'output')
                self.assertFalse((root/'output').exists())

    def test_valid_framework_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with zipfile.ZipFile(root/'input.zip', 'w') as archive:
                archive.writestr('mdPreview.app/F/Versions/A/F', 'binary')
                for name, target in {'mdPreview.app/F/Versions/Current': 'A',
                                     'mdPreview.app/F/F': 'Versions/Current/F'}.items():
                    member = zipfile.ZipInfo(name)
                    member.create_system = 3
                    member.external_attr = 0o120777 << 16
                    archive.writestr(member, target)
            app = extract(root/'input.zip', root/'output')
            self.assertEqual((app/'F/F').read_text(), 'binary')


if __name__ == '__main__':
    unittest.main()
