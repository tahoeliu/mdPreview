# mdPreview.spec — PyInstaller build configuration for standalone macOS app

from pathlib import Path

VERSION = Path('VERSION').read_text(encoding='utf-8').strip()
block_cipher = None

a = Analysis(
    ['markdown_viewer.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('index.html', '.'),
        ('styles.css', '.'),
        ('app.js', '.'),
        ('marked.min.js', '.'),
        ('turndown.js', '.'),
        ('mermaid.min.js', '.'),
        ('app_icon.icns', '.'),
        ('doc_icon.icns', '.'),
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
    bundle_identifier='com.workbuddy.mdpreview',
    info_plist={
        'CFBundleName': 'mdPreview',
        'CFBundleDisplayName': 'mdPreview',
        'CFBundleVersion': VERSION,
        'CFBundleShortVersionString': VERSION,
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
                ],
                'CFBundleTypeExtensions': [
                    'md', 'markdown', 'mdown', 'mkd', 'mkdown',
                ],
            }
        ],
    },
)
