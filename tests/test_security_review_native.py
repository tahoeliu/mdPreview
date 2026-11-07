"""仅编写：受限环境不执行Python/临时目录操作。"""
import ast
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


def create_worker(path, queue):
    from mdpreview_core.storage import atomic_create
    try:
        atomic_create(path, b'created')
        queue.put(True)
    except FileExistsError:
        queue.put(False)


class ReviewRegression(unittest.TestCase):
    def test_no_clobber_processes_and_symlink(self):
        from mdpreview_core.storage import atomic_create
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder).resolve()/'output'
            context = multiprocessing.get_context('spawn')
            queue = context.Queue()
            workers = [context.Process(target=create_worker, args=(str(target),queue)) for _ in range(2)]
            for worker in workers: worker.start()
            for worker in workers:
                worker.join(10)
                self.assertEqual(worker.exitcode, 0)
            self.assertEqual(sorted([queue.get(timeout=2),queue.get(timeout=2)]), [False,True])
            victim = Path(folder).resolve()/'victim'
            victim.write_bytes(b'unchanged')
            link = Path(folder).resolve()/'link'
            link.symlink_to(victim)
            with self.assertRaises(FileExistsError): atomic_create(link,b'bad')
            self.assertEqual(victim.read_bytes(),b'unchanged')

    def test_create_post_link_failures_rollback_and_close(self):
        from mdpreview_core.storage import atomic_create
        import stat
        for fault in ('fsync', 'unlink'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as folder:
                target=Path(folder).resolve()/'output'
                real_fsync,real_unlink,real_close=os.fsync,os.unlink,os.close
                closed=[]
                def fsync(fd):
                    if fault=='fsync' and stat.S_ISDIR(os.fstat(fd).st_mode):
                        raise OSError('injected-directory-fsync')
                    return real_fsync(fd)
                def unlink(name, **kwargs):
                    if fault=='unlink' and str(name).startswith('.mdpreview-create-'):
                        raise OSError('injected-temp-cleanup')
                    return real_unlink(name,**kwargs)
                def close(fd):
                    closed.append(fd)
                    return real_close(fd)
                with patch('os.fsync',side_effect=fsync),patch('os.unlink',side_effect=unlink),patch('os.close',side_effect=close):
                    with self.assertRaises(OSError):atomic_create(target,b'new')
                self.assertFalse(target.exists(),'失败必须回滚已链接的当前目标')
                self.assertTrue(closed,'cleanup失败不能漏关dirfd')

    def test_old_ack_preserves_new_candidate(self):
        import mdPreview as app
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder).resolve()/'doc.md';file.write_text('A')
            api=app.MarkdownAPI(str(file));api.file_content='A'
            file.write_text('B');old=api.reload_from_disk(api.document_id,0)
            file.write_text('C');new=api.reload_from_disk(api.document_id,0)
            self.assertFalse(api.ack_reload_from_disk(old['candidateId'],api.document_id,0)['success'])
            self.assertEqual(api._reload_candidate['id'],new['candidateId'])
            self.assertTrue(api.ack_reload_from_disk(new['candidateId'],api.document_id,0)['success'])
            self.assertEqual(api.file_content,'C')

    def test_body_native_failure_settles_once(self):
        from mdpreview_core.csp_bridge import run_body
        from unittest.mock import Mock
        window=Mock();window._callbacks={};results=[]
        window.gui.evaluate_js.side_effect=RuntimeError('native-failure')
        run_body(window,'const result=Promise.resolve(42); return result;',results.append)
        self.assertEqual(results,[{'success':False,'error':'native-javascript-failed'}])
        self.assertEqual(window._callbacks,{})

    def test_candidate_rejection_preserves_conflict(self):
        import mdPreview as app
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder).resolve()/'doc.md'
            file.write_text('A')
            api = app.MarkdownAPI(str(file))
            api.file_content = api.cached_content = 'A'
            api._record_baseline_stat(str(file))
            baseline = (api.baseline_mtime_ns,api.baseline_size)
            file.write_text('B')
            candidate = api.reload_from_disk(api.document_id,0)
            self.assertTrue(candidate['success'])
            self.assertEqual(api.file_content,'A')
            self.assertEqual((api.baseline_mtime_ns,api.baseline_size),baseline)
            api.is_dirty=True;api.revision=1;api.cached_content='A+edit'
            self.assertFalse(api.ack_reload_from_disk(candidate['candidateId'],api.document_id,0)['success'])
            saved=api.save_file(str(file),'A+edit',False,1,api.document_id)
            self.assertTrue(saved.get('conflict'))
            self.assertEqual(file.read_text(),'B')

    def test_approved_close_and_cancel(self):
        import mdPreview as app
        from mdpreview_core.export.print_engine import Completion
        from unittest.mock import Mock
        window=Mock();api=app.MarkdownAPI();api.window=window
        app._window_apis[id(window)]=api
        try:
            api._output_completion=Completion();api.is_dirty=True
            with patch.object(app,'_dispatch_js_to'),patch.object(app,'_write_draft'):
                self.assertFalse(app.on_window_closing(window))
                self.assertFalse(api._output_completion.closed)
            api.is_dirty=False
            with patch.object(app,'_dispatch_js_to'),patch.object(app,'_save_window_geometry'):
                app.on_window_closing(window)
                self.assertTrue(api._output_completion.closed)
            api._output_completion=Completion()
            api.reset_to_untitled()
            self.assertTrue(api._output_completion.closed)
        finally:
            app._window_apis.pop(id(window),None)
            app._hidden_windows.pop(id(window),None)

    def test_project_adapter_has_no_eval_wrapper(self):
        source=Path('mdpreview_core/csp_bridge.py').read_text()
        tree=ast.parse(source)
        self.assertFalse(any(isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in ('eval','exec') for node in ast.walk(tree)))
        self.assertNotIn('value = eval(',source)
        self.assertIn('window.gui.evaluate_js(script, window.uid, False)',source)

    def test_headless_formats_use_create(self):
        source=Path('mdPreview.py').read_text()
        self.assertIn('no_clobber=self._no_clobber_output()',source)
        self.assertIn('atomic_create if self._no_clobber_output()',source)
        self.assertIn('atomic_create if no_clobber',Path('mdpreview_core/export/pdf_post.py').read_text())
        self.assertIn('atomic_create if no_clobber',Path('mdpreview_core/export/snapshot.py').read_text())

    def test_update_target_identity(self):
        from mdpreview_core.release import installation_identity, check_installation_identity
        with tempfile.TemporaryDirectory() as folder:
            app=Path(folder).resolve()/'Custom.app'
            (app/'Contents/MacOS').mkdir(parents=True)
            (app/'Contents/MacOS/mdPreview').write_bytes(b'executable-A')
            from mdpreview_core.release import bundle_snapshot, check_startup_snapshot
            startup=bundle_snapshot(app)
            with patch('mdpreview_core.release.verify_bundle',return_value='1.5.0'):
                identity=installation_identity(app)
                self.assertEqual(check_installation_identity(app,identity),app)
                alternate=Path(folder).resolve()/'Other.app';alternate.mkdir()
                with self.assertRaises(ValueError):check_installation_identity(alternate,identity)
                executable=app/'Contents/MacOS/mdPreview'
                executable.rename(executable.with_name('old-executable'))
                executable.write_bytes(b'executable-same-version')
                with self.assertRaises(ValueError):check_startup_snapshot(app,startup)
                app.rename(Path(folder).resolve()/'previous.app')
                (app/'Contents/MacOS').mkdir(parents=True)
                (app/'Contents/MacOS/mdPreview').write_bytes(b'executable-B')
                with self.assertRaises(ValueError):check_installation_identity(app,identity)
                with self.assertRaises(ValueError):check_startup_snapshot(app,startup)


if __name__=='__main__': unittest.main()
