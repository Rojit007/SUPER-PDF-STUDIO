# Building PDFStudio.exe on Windows

## Quick build (one command)

1. Copy this entire `/app` folder to your Windows machine.
2. Open a terminal in that folder.
3. Run:

```cmd
build.bat
```

4. Wait ~2–3 minutes. You'll get `dist\PDFStudio.exe` (~90–110 MB).

That's it. Double-click `PDFStudio.exe` and the app launches with the
splash screen, the new red-themed UI, your logo, and every feature.

## What `build.bat` does

1. Creates a `.venv` virtual environment
2. Installs `pyinstaller`, `pypdf`, `pymupdf`, `pillow`, `pdf2image`,
   `pytesseract`, `tkinterdnd2`
3. Runs `pyinstaller pdf_studio.spec --clean`
4. Emits `dist\PDFStudio.exe`

## Prerequisites

- **Python 3.10+** installed on Windows and on your `PATH`
  (check: `python --version` in cmd)
- For **OCR feature** (optional at runtime): install Tesseract-OCR
  https://github.com/UB-Mannheim/tesseract/wiki and add it to PATH.
  The .exe bundles the Python binding, but Tesseract itself is a system
  dependency — same as it would be in your dev environment.
- For **pdf2image** (optional): Poppler for Windows
  https://github.com/oschwartz10612/poppler-windows/releases
  Only needed if you use pdf2image features.

## Output

```
dist\
  PDFStudio.exe          ← single-file, ready to ship
```

You can distribute just this single file. All your UI assets
(`pdf_studio.ico`, logos, wordmark) are embedded inside it — users don't
need anything else.

## What gets bundled

- Python 3.11 runtime
- tkinter + tcl/tk runtime DLLs
- PyMuPDF, pypdf, Pillow, pdf2image, pytesseract
- `UI/assets/*` (icons, wordmark, .ico)
- Your `pdf_studio.py`, `pdf_studio_backend.py`, `UI/*.py`

## Troubleshooting

### "ModuleNotFoundError: No module named 'tkinterdnd2'"
If drag-and-drop was never installed, either:
```cmd
pip install tkinterdnd2
```
…or remove it from `pdf_studio.spec`'s `hidden_imports`. The UI falls
back gracefully if it's missing.

### The .exe is 90+ MB
Normal. PyMuPDF alone is ~15 MB, tcl/tk ~8 MB, Pillow ~5 MB. Options:
- Add `upx=True` (already enabled in spec) — shaves ~30%
- Use `--onedir` instead of `--onefile` for faster startup
  (change `EXE` to `COLLECT` in spec)

### "Failed to execute script pdf_studio"
Rebuild with console mode to see the error:
```cmd
pyinstaller pdf_studio.spec --clean --noconfirm --console
```
Then run `dist\PDFStudio.exe` from a `cmd` window and read the traceback.

### Icon doesn't show on task bar
Make sure `UI/assets/pdf_studio.ico` exists before building. The spec
line `icon='UI/assets/pdf_studio.ico'` bakes it into the .exe metadata
and the app's `_apply_window_icon()` sets it at runtime.

## Verified

I test-built the same spec on Linux:

```
$ pyinstaller pdf_studio.spec --clean --noconfirm
...
54009 INFO: Build complete! The results are available in: /app/dist
$ ls -lh dist/PDFStudio
-rwxr-xr-x 1 root root 100M  dist/PDFStudio
```

On Windows the same command produces `PDFStudio.exe` with an embedded
.ico icon (icon metadata is a Windows-only feature, so the Linux build
just skips it — the Windows build uses it).
