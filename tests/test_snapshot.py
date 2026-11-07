import sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
class SnapshotTests(unittest.TestCase):
 def test_native_png_dimensions_splitting_and_conflict(self):
  import Foundation, Quartz
  from mdpreview_core.export import snapshot
  source=ROOT/'tests/fixtures/native-long.pdf'
  with tempfile.TemporaryDirectory(dir=ROOT/'WorkSpace/cache') as directory:
   target=Path(directory)/'image.png'
   paths=snapshot.render(source.read_bytes(),target,max_pixels=1000000)
   self.assertGreater(len(paths),1)
   for name in paths:
    data=Path(name).read_bytes();self.assertTrue(data.startswith(b'\x89PNG\r\n\x1a\n'))
    image=Quartz.CGImageSourceCreateWithData(Foundation.NSData.dataWithBytes_length_(data,len(data)),None)
    props=Quartz.CGImageSourceCopyPropertiesAtIndex(image,0,None)
    self.assertEqual(props[Quartz.kCGImagePropertyPixelWidth],1190)
   before=Path(paths[0]).read_bytes()
   with self.assertRaises(FileExistsError): snapshot.render(source.read_bytes(),target,max_pixels=1000000)
   self.assertEqual(Path(paths[0]).read_bytes(),before)
   second=Path(directory)/'failure.png'
   with patch.object(snapshot,'atomic_write',side_effect=OSError('disk')):
    with self.assertRaises(OSError):snapshot.render(source.read_bytes(),second)
   self.assertFalse(second.exists())
   third=Path(directory)/'rollback.png'
   real_link=snapshot.os.link
   calls=[]
   def fail_second(src,dst):
    calls.append(dst)
    if len(calls)==2: raise OSError('disk')
    return real_link(src,dst)
   with patch.object(snapshot.os,'link',side_effect=fail_second):
    with self.assertRaises(OSError):snapshot.render(source.read_bytes(),third,max_pixels=1000000)
   self.assertFalse(third.with_name('rollback-1.png').exists())
   from mdpreview_core.export.print_engine import Completion
   state=Completion(); state.finish(True); state.close()
   with self.assertRaises(RuntimeError):snapshot.render(source.read_bytes(),second,commit_guard=state.commit_guard)
   self.assertFalse(second.exists())
 def test_no_clobber_post_link_failure_rolls_back_all_slices(self):
  import os,stat
  from mdpreview_core.export import snapshot
  source=ROOT/'tests/fixtures/native-long.pdf'
  for fault in ('fsync','unlink'):
   with self.subTest(fault=fault),tempfile.TemporaryDirectory(dir=ROOT/'WorkSpace/cache') as directory:
    target=Path(directory).resolve()/'postlink.png'
    real_fsync,real_unlink,real_create=os.fsync,os.unlink,snapshot.atomic_create
    active={'index':0}
    def create(path,payload):
     active['index']+=1
     return real_create(path,payload)
    def fsync(fd):
     if fault=='fsync' and active['index']==2 and stat.S_ISDIR(os.fstat(fd).st_mode):raise OSError('post-link-fsync')
     return real_fsync(fd)
    def unlink(name,*args,**kwargs):
     if fault=='unlink' and active['index']==2 and str(name).startswith('.mdpreview-create-'):raise OSError('post-link-unlink')
     return real_unlink(name,*args,**kwargs)
    with patch.object(snapshot,'atomic_create',side_effect=create),patch('os.fsync',side_effect=fsync),patch('os.unlink',side_effect=unlink):
     with self.assertRaises(OSError):snapshot.render(source.read_bytes(),target,max_pixels=1000000,no_clobber=True)
    self.assertFalse(list(target.parent.glob('postlink*.png')))
if __name__=='__main__':unittest.main()
