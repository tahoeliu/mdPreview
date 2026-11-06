"""WKPDF 屏幕快照的白底 2× PNG 栅格化及分片提交。"""
import math
import os
from pathlib import Path
import tempfile
from mdpreview_core.storage import atomic_write


def render(pdf_data, destination, scale=2, max_pixels=120_000_000):
    import Foundation
    import Quartz as Q
    data = Foundation.NSData.dataWithBytes_length_(pdf_data, len(pdf_data))
    provider = Q.CGDataProviderCreateWithCFData(data)
    doc = Q.CGPDFDocumentCreateWithProvider(provider)
    if not doc or not Q.CGPDFDocumentGetNumberOfPages(doc):
        raise ValueError('invalid-snapshot-pdf')
    page = Q.CGPDFDocumentGetPage(doc, 1)
    bounds = Q.CGPDFPageGetBoxRect(page, Q.kCGPDFMediaBox)
    width = math.ceil(bounds.size.width*scale)
    height = math.ceil(bounds.size.height*scale)
    if width <= 0 or height <= 0 or width > max_pixels:
        raise ValueError('invalid-snapshot-size')
    slice_height = max(1, min(height, max_pixels//width))
    count = math.ceil(height/slice_height)
    target = Path(destination)
    paths = [target] if count == 1 else [target.with_name(f'{target.stem}-{i+1}.png') for i in range(count)]
    if count > 1 and any(path.exists() for path in paths):
        raise FileExistsError('split-output-exists')
    committed = []
    with tempfile.TemporaryDirectory(prefix='.mdpreview-png-', dir=target.parent) as directory:
        staged = []
        for index in range(count):
            offset = index*slice_height
            h = min(slice_height, height-offset)
            context = Q.CGBitmapContextCreate(None,width,h,8,width*4,Q.CGColorSpaceCreateDeviceRGB(),Q.kCGImageAlphaPremultipliedLast)
            if context is None:
                raise MemoryError('snapshot-allocation-failed')
            Q.CGContextSetRGBFillColor(context,1,1,1,1)
            Q.CGContextFillRect(context,Q.CGRectMake(0,0,width,h))
            Q.CGContextTranslateCTM(context,0,h+offset-height)
            Q.CGContextScaleCTM(context,scale,scale)
            Q.CGContextTranslateCTM(context,-bounds.origin.x,-bounds.origin.y)
            Q.CGContextDrawPDFPage(context,page)
            image = Q.CGBitmapContextCreateImage(context)
            encoded = Foundation.NSMutableData.data()
            output = Q.CGImageDestinationCreateWithData(encoded,'public.png',1,None)
            Q.CGImageDestinationAddImage(output,image,None)
            if not Q.CGImageDestinationFinalize(output):
                raise OSError('png-encode-failed')
            stage = Path(directory)/f'{index}.png'
            atomic_write(stage,bytes(encoded))
            staged.append(stage)
            del context, image, encoded
        if count == 1:
            atomic_write(target,staged[0].read_bytes())
        else:
            try:
                for stage, path in zip(staged,paths):
                    # 同目录硬链接保证不覆盖意外出现的同名文件。
                    os.link(stage,path)
                    committed.append((path,path.stat().st_ino))
            except Exception:
                for path, inode in committed:
                    if path.exists() and path.stat().st_ino == inode:
                        path.unlink()
                raise
    return [str(path) for path in paths]
