@echo off
REM ============================================================
REM PDF Studio v4 - Windows build script
REM ------------------------------------------------------------
REM 1. Installs dependencies into a fresh venv
REM 2. Runs PyInstaller with the bundled .spec
REM 3. Emits dist\PDFStudio.exe
REM ============================================================
setlocal enabledelayedexpansion

echo.
echo ===================================================
echo  Building PDF Studio v4 (Windows .exe)
echo ===================================================
echo.

REM --- Create venv if missing ---
if not exist ".venv\" (
    echo [1/4] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 goto :fail
)

call .venv\Scripts\activate.bat

echo [2/4] Installing dependencies...
python -m pip install --upgrade pip -q
python -m pip install -q pyinstaller pypdf pymupdf pillow pdf2image pytesseract tkinterdnd2

echo [3/4] Cleaning previous build...
if exist "build"  rmdir /s /q build
if exist "dist"   rmdir /s /q dist
if exist "__pycache__" rmdir /s /q __pycache__

echo [4/4] Running PyInstaller...
pyinstaller pdf_studio.spec --clean --noconfirm
if errorlevel 1 goto :fail

echo.
echo ===================================================
echo   Build finished
echo   Executable: dist\PDFStudio.exe
echo ===================================================
echo.
dir dist\PDFStudio.exe
goto :end

:fail
echo.
echo [ERROR] Build failed. See output above.
exit /b 1

:end
endlocal
