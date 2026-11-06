"""Inventory history without deleting or rewriting recoverable backups."""
import hashlib
import json
from pathlib import Path

root=Path(__file__).resolve().parent.parent
rows=[]
for directory in [root/'WorkSpace/app-backups',root/'WorkSpace/backups',root/'outputs']:
    if not directory.exists():continue
    for entry in sorted(directory.iterdir()):
        if entry.is_symlink():continue
        size=sum(file.stat().st_size for file in entry.rglob('*') if file.is_file() and not file.is_symlink()) if entry.is_dir() else entry.stat().st_size
        rows.append({'path':str(entry.relative_to(root)),'bytes':size,'modifiedAt':entry.stat().st_mtime})
destination=root/'WorkSpace/backup-inventory.json';destination.write_text(json.dumps(rows,indent=2))
print('Preserved backup inventory: '+str(destination))
