import concurrent.futures
import hashlib
import json
import os
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest import mock

import mdPreview as app
from mdpreview_core.storage import DraftStore, atomic_write
from mdpreview_core.release import version_tuple, verify_asset, transactional_install, verify_bundle


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.patches=[mock.patch.object(app,'DRAFT_DIR',str(self.root/'drafts')),
                      mock.patch.object(app,'CONFIG_FILE',str(self.root/'config.json')),
                      mock.patch.object(app,'LEGACY_CONFIG_FILE',str(self.root/'legacy.json')),
                      mock.patch.object(app,'APP_SUPPORT_DIR',str(self.root))]
        for patch in self.patches:patch.start();self.addCleanup(patch.stop)

    def test_independent_untitled_recovery(self):
        one,two=app.MarkdownAPI(),app.MarkdownAPI()
        one.set_dirty(True);two.set_dirty(True)
        self.assertTrue(one.store_content('ONE',1,one.document_id)['success'])
        two.store_content('TWO',1,two.document_id)
        self.assertEqual(len(DraftStore(app.DRAFT_DIR).recoverable()),2)
        recovered=app.MarkdownAPI()
        data=recovered.recover_untitled(one.document_id)['data']
        self.assertEqual(data['content'],'ONE');self.assertTrue(data['draftRecovered'])
        recovered.discard_draft()
        self.assertEqual(len(DraftStore(app.DRAFT_DIR).recoverable()),1)

    def test_save_preserves_newer_bridge_revision(self):
        path=self.root/'doc.md';path.write_text('A')
        api=app.MarkdownAPI(str(path));api.get_initial_content();api.store_content('B',1,api.document_id)
        entered=threading.Event();release=threading.Event();original=app._safe_write_text
        def delayed(target,text,encoding='utf-8'):
            if target==str(path):entered.set();release.wait(3)
            return original(target,text,encoding)
        with mock.patch.object(app,'_safe_write_text',side_effect=delayed):
            with concurrent.futures.ThreadPoolExecutor() as pool:
                saved=pool.submit(api.save_file,str(path),'B',False,1,api.document_id)
                self.assertTrue(entered.wait(2));api.store_content('C',2,api.document_id);release.set()
                self.assertTrue(saved.result()['success'])
        self.assertEqual(path.read_text(),'B');self.assertEqual(api.cached_content,'C');self.assertTrue(api.is_dirty)
        self.assertEqual(DraftStore(app.DRAFT_DIR).read(str(path),api.document_id)['content'],'C')

    def test_stale_bridge_and_save_rejected(self):
        api=app.MarkdownAPI();identity=api.document_id
        api.store_content('latest',4,identity)
        self.assertFalse(api.store_content('old',3,identity)['success'])
        self.assertFalse(api.save_file(str(self.root/'x.md'),'old',False,1,'wrong')['success'])
        self.assertEqual(api.cached_content,'latest')

    def test_failed_draft_does_not_acknowledge(self):
        api=app.MarkdownAPI();api.set_dirty(True)
        with mock.patch.object(app,'_write_draft',return_value=None):
            self.assertFalse(api.store_content('edit',1,api.document_id)['success'])
        self.assertTrue(api.store_content('edit',1,api.document_id)['success'])

    def test_utf16_byte_order_and_bom_are_preserved(self):
        for encoding,bom in [('utf-16-le',b'\xff\xfe'),('utf-16-be',b'\xfe\xff')]:
            with self.subTest(encoding=encoding):
                path=self.root/(encoding+'.md');raw=bom+'中文\r\n'.encode(encoding);path.write_bytes(raw)
                api=app.MarkdownAPI(str(path));data=api.get_initial_content();self.assertEqual(data['content'],'中文\r\n')
                self.assertTrue(api.save_file(str(path),data['content'])['success']);self.assertEqual(path.read_bytes(),raw)

    def test_same_mtime_size_external_change(self):
        path=self.root/'doc.md';path.write_text('aaa')
        api=app.MarkdownAPI(str(path));api.get_initial_content();before=path.stat()
        path.write_text('bbb');os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
        self.assertTrue(api.save_file(str(path),'ccc')['conflict']);self.assertEqual(path.read_text(),'bbb')

    def test_file_permissions_symlink_and_xattrs(self):
        path=self.root/'real.md';path.write_text('before');path.chmod(0o644)
        import subprocess
        subprocess.run(['xattr','-w','com.mdpreview.test','metadata',str(path)],check=True)
        link=self.root/'link.md';link.symlink_to(path)
        atomic_write(link,b'after')
        self.assertTrue(link.is_symlink());self.assertEqual(path.read_text(),'after')
        self.assertEqual(path.stat().st_mode&0o777,0o644);self.assertEqual(subprocess.check_output(['xattr','-p','com.mdpreview.test',str(path)]).strip(),b'metadata')

    def test_failed_replace_preserves_original(self):
        path=self.root/'doc.md';path.write_text('original')
        with mock.patch('mdpreview_core.storage.os.replace',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):atomic_write(path,b'new')
        self.assertEqual(path.read_text(),'original');self.assertFalse(list(self.root.glob('*.tmp')))

    def test_all_encodings_round_trip(self):
        for encoding in ['utf-8','utf-8-sig','utf-16','gb18030']:
            with self.subTest(encoding=encoding):
                path=self.root/(encoding+'.md');path.write_bytes('中文 café\r\n'.encode(encoding))
                api=app.MarkdownAPI(str(path));data=api.get_initial_content()
                self.assertTrue(api.save_file(str(path),data['content'])['success'])
                self.assertEqual(path.read_bytes(),'中文 café\r\n'.encode(encoding))

    def test_config_updates_are_serialized(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i:app.update_config({str(i):i}),range(50)))
        self.assertEqual(len(app.load_config()),50)

    def test_invalid_versions_rejected(self):
        for value in [None,'not-a-version','1.2','1.2.3beta','1.2.3/../x']:
            self.assertFalse(app._staged_version_acceptable(value,'1.4.9'))
        self.assertTrue(version_tuple('1.5.0')>version_tuple('1.4.9'))

    def test_asset_digest_and_size(self):
        digest=hashlib.sha256(b'package').hexdigest();asset={'digest':'sha256:'+digest,'size':7}
        verify_asset(digest,7,asset)
        for bad_digest,bad_size in [('0'*64,7),(digest,8)]:
            with self.assertRaises(ValueError):verify_asset(bad_digest,bad_size,asset)
        with self.assertRaises(ValueError):verify_asset(digest,7,{'size':7})

    def test_transaction_rolls_back_copy_verify_launch_failures(self):
        staged=self.root/'staged.app';staged.mkdir();(staged/'version').write_text('new')
        destination=self.root/'app.app';destination.mkdir();(destination/'version').write_text('old')
        with mock.patch('mdpreview_core.release.shutil.copytree',side_effect=OSError('copy failed before creating directory')):
            with self.assertRaises(OSError):transactional_install(staged,destination,lambda p:None,lambda p:None,lambda p:True)
        self.assertEqual((destination/'version').read_text(),'old')
        for phase in ['verify','launch','ready']:
            def verify(path):
                if phase=='verify':raise RuntimeError('verification failed')
            def launch(path):
                if phase=='launch':raise RuntimeError('launch failed')
            with self.assertRaises(RuntimeError):transactional_install(staged,destination,verify,launch,lambda p:False)
            self.assertEqual((destination/'version').read_text(),'old')
            self.assertFalse(list(self.root.glob('.mdPreview-*')))
        transactional_install(staged,destination,lambda p:None,lambda p:None,lambda p:True)
        self.assertEqual((destination/'version').read_text(),'new')

    def test_unsafe_external_protocol_rejected(self):
        with mock.patch('webbrowser.open') as opened:
            for url in ['javascript:alert(1)','file:///etc/passwd','java\tscript:alert(1)','unknown://example']:
                self.assertFalse(app.MarkdownAPI().open_external_link(url)['success'])
            opened.assert_not_called()

    def test_recovery_of_legacy_untitled_and_corrupt_records(self):
        directory=self.root/'drafts';directory.mkdir()
        legacy=directory/(hashlib.sha256(b'Untitled.md').hexdigest()[:24]+'.md');legacy.write_text('old unsaved text')
        store=DraftStore(directory);recovered=store.recoverable()
        self.assertEqual(len(recovered),1);self.assertFalse(legacy.exists())
        self.assertEqual(store.read(None,recovered[0]['documentId'])['content'],'old unsaved text')
        invalid=str(uuid.uuid4());(directory/('untitled-'+invalid+'.json')).write_text('{invalid')
        self.assertEqual(len(store.recoverable()),1)
        self.assertIsNone(store.read(None,'../../escape'))

    def test_draft_write_order_and_invalid_schema(self):
        store=DraftStore(self.root/'drafts');identity=str(uuid.uuid4())
        store.write(None,identity,5,'latest');store.write(None,identity,4,'older')
        self.assertEqual(store.read(None,identity)['content'],'latest')
        path=store.directory/('untitled-'+identity+'.json');record=json.loads(path.read_text());record['schema']=999;path.write_text(json.dumps(record))
        self.assertIsNone(store.read(None,identity))
        store.remove(None,identity);store.remove(None,identity)
        self.assertEqual(store.recoverable(),[])

    def test_bundle_identity_executable_version_and_signer(self):
        import plistlib
        from types import SimpleNamespace
        bundle=self.root/'new.app';(bundle/'Contents/MacOS').mkdir(parents=True)
        (bundle/'Contents/MacOS/mdPreview').write_bytes(b'executable')
        plist=bundle/'Contents/Info.plist'
        info={'CFBundleIdentifier':'tahoeliu.mdpreview','CFBundleExecutable':'mdPreview','CFBundleShortVersionString':'1.5.0'}
        plist.write_bytes(plistlib.dumps(info))
        with mock.patch('mdpreview_core.release.subprocess.run',return_value=SimpleNamespace(stderr='TeamIdentifier=ABCDEFGHIJ\n')):
            self.assertEqual(verify_bundle(bundle,None,'1.5.0'),'1.5.0')
            self.assertEqual(verify_bundle(bundle,'ABCDEFGHIJ','1.5.0'),'1.5.0')
            with self.assertRaises(ValueError):verify_bundle(bundle,'wrong')
            with self.assertRaises(ValueError):verify_bundle(bundle,None,'1.5.1')
            with self.assertRaises(ValueError):verify_bundle(bundle,'ZZZZZZZZZZ')
            info['CFBundleIdentifier']='another.app';plist.write_bytes(plistlib.dumps(info))
            with self.assertRaises(ValueError):verify_bundle(bundle)
            info['CFBundleIdentifier']='tahoeliu.mdpreview';info['CFBundleExecutable']='wrong';plist.write_bytes(plistlib.dumps(info))
            with self.assertRaises(ValueError):verify_bundle(bundle)

    def test_update_lock_is_exclusive_and_released(self):
        app._update_download_lock.acquire()
        try:self.assertEqual(app._download_and_extract('1.5.0')['error'],'busy')
        finally:app._update_download_lock.release()
        with mock.patch('mdpreview_core.update_download.download',side_effect=ValueError('signed-digest-mismatch')):
            self.assertEqual(app._download_and_extract('1.5.0')['error'],'verify')
        # 失败后锁必须已释放，下一次下载才不会永久卡在 busy。
        self.assertTrue(app._update_download_lock.acquire(blocking=False))
        app._update_download_lock.release()

    def test_quit_cancellation_restores_state(self):
        api=app.MarkdownAPI();api.window=object()
        with mock.patch.object(app,'_window_apis',{id(api.window):api}),mock.patch.object(app,'_dispatch_js_to') as dispatch:
            app._quit_confirmation_active=False
            app._begin_quit_confirmation();self.assertTrue(app._quit_confirmation_active)
            app._finish_quit_confirmation(api,False)
            self.assertFalse(app._quit_confirmation_active);self.assertFalse(app._QUIT_APPROVED.is_set())

    def test_untitled_reset_clears_identity_and_encoding(self):
        api=app.MarkdownAPI();before=api.document_id;api.encoding='gb18030';api.store_content('edit',2,before)
        api.reset_to_untitled();self.assertNotEqual(before,api.document_id);self.assertEqual(api.encoding,'utf-8');self.assertFalse(api.is_dirty)
        self.assertFalse(api.store_content('old',3,before)['success'])

    def test_new_install_failure_removes_only_new_application(self):
        staged=self.root/'staged.app';staged.mkdir();(staged/'version').write_text('new')
        destination=self.root/'new.app'
        with self.assertRaises(RuntimeError):transactional_install(staged,destination,lambda p:None,lambda p:None,lambda p:False)
        self.assertFalse(destination.exists());self.assertTrue(staged.exists())

    def test_update_waits_for_actual_process_exit(self):
        from mdpreview_core.release import wait_for_exit
        with mock.patch('mdpreview_core.release.os.kill',side_effect=ProcessLookupError):wait_for_exit(123)
        with mock.patch('mdpreview_core.release.time.monotonic',side_effect=[0,2]):
            with self.assertRaises(TimeoutError):wait_for_exit(123,timeout=1)

    def test_portable_image_export_validates_data_paths_and_size(self):
        from mdpreview_core.images import export_image
        document=self.root/'doc.md';document.write_text('doc')
        for filename,payload,mime in [('a.png',b'\x89PNG\r\n\x1a\nbytes','image/png'),('a.jpg',b'\xff\xd8\xffbytes','image/jpeg'),('a.gif',b'GIF89abytes','image/gif'),('a.webp',b'RIFF0000WEBPbytes','image/webp')]:
            (self.root/filename).write_bytes(payload)
            self.assertTrue(export_image(document,filename).startswith('data:'+mime+';base64,'))
        (self.root/'bad.png').write_bytes(b'not an image')
        for path in ['../outside.png','bad.png']:
            with self.assertRaises(ValueError):export_image(document,path)
        with self.assertRaises(ValueError):export_image(None,'a.png')
        large=self.root/'large.png'
        with large.open('wb') as stream:stream.truncate(21*1024*1024)
        with self.assertRaises(ValueError):export_image(document,'large.png')

    def test_read_failure_cannot_overwrite_original(self):
        path=self.root/'doc.md';path.write_text('precious original')
        api=app.MarkdownAPI(str(path))
        with mock.patch.object(app,'_detect_text_encoding',side_effect=PermissionError('unreadable')):
            data=api.get_initial_content()
        self.assertIn('readError',data);self.assertEqual(data['content'],'')
        self.assertFalse(api.save_file(str(path),'error text',True)['success'])
        self.assertEqual(path.read_text(),'precious original')

    def test_recovered_draft_detects_external_modification(self):
        path=self.root/'doc.md';path.write_text('original')
        first=app.MarkdownAPI(str(path));first.get_initial_content();first.store_content('draft edits',1,first.document_id)
        path.write_text('external edits')
        recovered=app.MarkdownAPI(str(path));data=recovered.get_initial_content()
        self.assertTrue(data['externalConflict']);self.assertTrue(recovered.save_file(str(path),'draft edits')['conflict'])
        self.assertEqual(path.read_text(),'external edits')


if __name__=='__main__':unittest.main()
