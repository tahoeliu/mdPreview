from pathlib import Path
import Quartz, Foundation
root = Path(__file__).resolve().parents[1]
p = sorted((root / 'WorkSpace/outputs/T03').glob('baseline-*/light.pdf'), key=lambda p: p.stat().st_mtime)[-1]
doc = Quartz.PDFDocument.alloc().initWithURL_(Foundation.NSURL.fileURLWithPath_(str(p)))
page = doc.pageAtIndex_(0)
text = str(page.string())
print(repr(text), page.numberOfCharacters())
for marker in ['HHeading One','HHeading Two','HHeading Three','HBody','HCode','HTd']:
    pos=text.index(marker)
    offset=len(text[:pos].encode('utf-16-le'))//2
    print(marker, pos, offset)
    for i in range(max(0,offset-2), offset+3):
        sel=page.selectionForRange_(Foundation.NSMakeRange(i,1))
        print(i, repr(str(sel.string())), page.characterBoundsAtIndex_(i), sel.boundsForPage_(page))
