# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for PDF Studio v4.

Build:
    Windows:     pyinstaller pdf_studio.spec
    macOS/Linux: pyinstaller pdf_studio.spec

Produces a single-file executable in dist/ with the UI/assets folder
bundled, custom Windows .ico icon, and no console window.

If tkinterdnd2 isn't installed, the drag-and-drop hidden-import will be
silently skipped by PyInstaller.
"""
from PyInstaller.utils.hooks import collect_data_files
import os, sys

block_cipher = None
project_root = os.path.abspath(os.path.dirname(SPECPATH))

# Bundled resources
datas = [
    ('UI/assets', 'UI/assets'),
]

hidden_imports = [
    'PIL._tkinter_finder',
    'pypdf', 'pypdf.generic',
    'fitz',                          # PyMuPDF
    'pdf2image',
    'pytesseract',
    'tkinter', 'tkinter.ttk', 'tkinter.filedialog',
    'tkinter.colorchooser', 'tkinter.simpledialog', 'tkinter.messagebox',
    'tkinter.font',
    'UI.pdf_studio_ui', 'UI.pdf_features', 'UI.dialog_kit',
    'pdf_studio_common', 'pdf_studio_backend',
]

# Optional: drag-and-drop
try:
    import tkinterdnd2                                            # noqa: F401
    hidden_imports.append('tkinterdnd2')
    datas += collect_data_files('tkinterdnd2')
except ImportError:
    pass


a = Analysis(
    ['pdf_studio.py'],
    pathex=[project_root],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    runtime_hooks=[],
    excludes=['matplotlib', 'numpy.random._examples', 'tcl'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PDFStudio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                        # windowed app
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='UI/assets/pdf_studio.ico' if sys.platform == 'win32'
         else 'UI/assets/pdf_studio_icon_256.png',
)
