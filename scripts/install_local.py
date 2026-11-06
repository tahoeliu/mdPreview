import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from mdpreview_core.release import transactional_install, verify_bundle

if __name__=='__main__':
    source,destination=sys.argv[1:3]
    transactional_install(source,destination,lambda app:verify_bundle(app),lambda app:None,lambda app:True)
    print('Installed verified application: '+destination)
