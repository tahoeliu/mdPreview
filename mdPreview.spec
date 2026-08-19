# mdPreview.spec — PyInstaller build configuration for standalone macOS app

from pathlib import Path

VERSION = Path('VERSION').read_text(encoding='utf-8').strip()
# Versioning rule (user): a feature cycle uses a 3-part version (e.g. 1.3.4);
# internal builds append a 4th segment (e.g. 1.3.4.1). The FULL version string
# (incl. the optional 4th segment) is shown as CFBundleShortVersionString, so
# the About panel reads e.g. "Version 1.4.1.1" (CFBundleVersion is omitted to
# avoid the redundant "(build)" suffix next to the version line). The auto-update
# integrity check reads CFBundleShortVersionString from the staged app instead
# (see mdPreview.py _download_and_extract).
SHORT_VERSION = VERSION
block_cipher = None

a = Analysis(
    ['mdPreview.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('index.html', '.'),
        ('styles.css', '.'),
        ('app.js', '.'),
        ('marked.min.js', '.'),
        ('turndown.js', '.'),
        ('mermaid.min.js', '.'),
        ('html-docx-js.js', '.'),
        ('html2canvas.min.js', '.'),
        ('app_icon.icns', '.'),
        ('doc_icon.icns', '.'),
        # Shown in the standard macOS About panel (bottom "Credits" area).
        # Contains a clickable "GitHub" hyperlink + "©tahoeliu".
        ('Credits.rtf', '.'),
    ],
    hiddenimports=[
        'webview.platforms.cocoa',
        'webview.platforms.edgechromium',
        'webview.js',
        'bottle',
        'proxy_tools',
        'objc',
        'AppKit',
        'Foundation',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'turtle',
        'turtledemo',
        'idlelib',
        'test',
        'tests',
        'curses',
        'sqlite3',
        'lzma',
        'bz2',
        'tarfile',
        'ftplib',
        'imaplib',
        'nntplib',
        'poplib',
        'smtplib',
        'telnetlib',
        'antigravity',
        'ensurepip',
        'venv',
        'py_compile',
        'symtable',
        'lib2to3',
        'pdb',
        'profile',
        'pstats',
        'timeit',
        'trace',
    ],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='mdPreview',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='app_icon.icns',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=['*.dylib'],
    name='mdPreview',
)

app = BUNDLE(
    coll,
    name='mdPreview.app',
    icon='app_icon.icns',
    bundle_identifier='tahoeliu.mdpreview',
    info_plist={
        'CFBundleName': 'mdPreview',
        'CFBundleDisplayName': 'mdPreview',
        'CFBundleShortVersionString': SHORT_VERSION,
        'LSMinimumSystemVersion': '10.13',
        'NSHighResolutionCapable': True,
        'NSAppTransportSecurity': {
            # Keep ATS enabled. mdPreview only uses HTTPS endpoints for update checks,
            # so it does not need global arbitrary network loads.
            'NSAllowsArbitraryLoads': False,
        },
        'CFBundleDocumentTypes': [
            {
                'CFBundleTypeName': 'Markdown Document',
                'CFBundleTypeRole': 'Editor',
                'LSHandlerRank': 'Default',
                'CFBundleTypeIconFile': 'doc_icon.icns',
                'LSItemContentTypes': [
                    'net.daringfireball.markdown',
                    'com.apple.traditional-mac-plain-text',
                    'public.plain-text',
                    'public.text',
                ],
                'CFBundleTypeExtensions': [
                    'md', 'markdown', 'mdown', 'mkd', 'mkdown',
                ],
            }
        ],
        'UTImportedTypeDeclarations': [
            {
                'UTTypeIdentifier': 'net.daringfireball.markdown',
                'UTTypeDescription': 'Markdown Document',
                'UTTypeConformsTo': ['public.plain-text', 'public.text'],
                'UTTypeTagSpecification': {
                    'public.filename-extension': ['md', 'markdown', 'mdown', 'mkd', 'mkdown'],
                    'public.mime-type': ['text/markdown', 'text/x-markdown'],
                },
            },
        ],
    },
)
