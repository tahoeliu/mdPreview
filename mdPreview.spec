# mdPreview.spec — PyInstaller build configuration for standalone macOS app

block_cipher = None

a = Analysis(
    ['markdown_viewer.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('index.html', '.'),
        ('marked.min.js', '.'),
        ('turndown.js', '.'),
        ('mermaid.min.js', '.'),
        ('app_icon.icns', '.'),
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
    excludes=[],
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
    upx_exclude=[],
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
        'CFBundleVersion': '1.2.2',
        'CFBundleShortVersionString': '1.2.2',
        'LSMinimumSystemVersion': '10.13',
        'NSHighResolutionCapable': True,
        'NSAppTransportSecurity': {
            'NSAllowsArbitraryLoads': True,
        },
        'CFBundleDocumentTypes': [
            {
                'CFBundleTypeName': 'Markdown Document',
                'CFBundleTypeRole': 'Viewer',
                'LSHandlerRank': 'Default',
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
