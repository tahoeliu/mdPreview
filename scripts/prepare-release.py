"""Bind Homebrew metadata to an already built, verified local DMG. No publishing."""
import hashlib
import re
from pathlib import Path

root=Path(__file__).resolve().parent.parent
version=(root/'VERSION').read_text().strip()
asset=root/'WorkSpace/dist'/('release-'+version)/'mdPreview.dmg'
digest=hashlib.sha256(asset.read_bytes()).hexdigest()
cask=root/'Casks/mdpreview.rb';text=cask.read_text()
text=re.sub(r'version "[^"]+"','version "'+version+'"',text)
text=re.sub(r'sha256 "[^"]+"','sha256 "'+digest+'"',text)
cask.write_text(text)
print('Versioned cask prepared; upload the matching asset explicitly: '+str(asset))
