#!/usr/bin/env bash
# ============================================================
# PDF Studio v4 — macOS / Linux build script
# Produces a native binary in dist/PDFStudio
# (Use build.bat on Windows to produce a .exe)
# ============================================================
set -euo pipefail

echo "==================================================="
echo " Building PDF Studio v4  (`uname -s`)"
echo "==================================================="

# Create & activate venv
if [ ! -d ".venv" ]; then
    echo "[1/4] Creating virtual environment..."
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "[2/4] Installing dependencies..."
pip install --upgrade pip -q
pip install -q pyinstaller pypdf pymupdf pillow pdf2image pytesseract tkinterdnd2 || true

echo "[3/4] Cleaning previous build..."
rm -rf build dist __pycache__

echo "[4/4] Running PyInstaller..."
pyinstaller pdf_studio.spec --clean --noconfirm

echo
echo "==================================================="
echo "  Build finished"
echo "  Executable: $(pwd)/dist/PDFStudio"
ls -lh dist/PDFStudio 2>/dev/null || ls -lh dist/
echo "==================================================="
