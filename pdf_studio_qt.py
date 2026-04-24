"""
pdf_studio_qt.py  –  PySide6 entry point for PDF Studio
─────────────────────────────────────────────────────────────────────────────
Run with:
    python pdf_studio_qt.py

Or as a PyInstaller entry point — set this file as the target script and
ensure PySide6, PyMuPDF, pypdf, Pillow, and pytesseract are in the spec.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
#  Auto-install runtime deps when run from source (skipped inside a .exe)
# ─────────────────────────────────────────────────────────────────────────────
IS_FROZEN = getattr(sys, "frozen", False)


def _install_deps():
    if IS_FROZEN or os.environ.get("PDF_STUDIO_SKIP_AUTO_INSTALL") == "1":
        return
    import subprocess
    needed = {
        "PySide6":     "PySide6",
        "pypdf":       "pypdf",
        "PIL":         "Pillow",
        "pytesseract": "pytesseract",
        "fitz":        "PyMuPDF",
    }
    for imp, pkg in needed.items():
        try:
            __import__(imp)
        except ImportError:
            print(f"Installing {pkg}…")
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", pkg, "-q"])


_install_deps()

# ─────────────────────────────────────────────────────────────────────────────
#  Re-export shared symbols (keeps `from pdf_studio_qt import PageRecord` working)
# ─────────────────────────────────────────────────────────────────────────────
from pdf_studio_common import (  # noqa: E402,F401
    IS_FROZEN, STATE_DIR, OPTIONS, OPTION_COLORS, ROTATE_STEP,
    THUMB_W, THUMB_H, ROW_H, PREVIEW_MIN_W,
    RECENT_FILE, SESSION_FILE, MAX_RECENT, SESSION_PERSISTENCE,
    PAGE_SIZES, DARK_THEME, LIGHT_THEME,
    _to_roman, normalize_rotation, rotation_label,
    effective_orientation, get_page_orientation,
    apply_transform, apply_visual_rotation,
    render_page_image_fitz, get_page_info_fitz,
    load_recent_files, save_recent_files, add_recent_file,
    PageRecord, UndoStack,
)

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from UI.pdf_studio_ui_qt import PDFStudioUI  # noqa: E402
from UI.pdf_features import PDFFeatures       # noqa: E402
from pdf_studio_backend import PDFStudioBase  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
#  Splash screen pixmap
# ─────────────────────────────────────────────────────────────────────────────

def _make_splash(w: int = 520, h: int = 300) -> QPixmap:
    pm = QPixmap(w, h)
    pm.fill(QColor("#1E1E2E"))
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Accent bar
    painter.fillRect(0, 0, w, 5, QColor("#89B4FA"))

    # Title
    title_font = QFont("Segoe UI", 30, QFont.Weight.Bold)
    painter.setFont(title_font)
    painter.setPen(QColor("#CDD6F4"))
    painter.drawText(0, 60, w, 80,
                     Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                     "PDF Studio")

    # Tagline
    tag_font = QFont("Segoe UI", 12)
    painter.setFont(tag_font)
    painter.setPen(QColor("#89B4FA"))
    painter.drawText(0, 150, w, 40,
                     Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                     "Professional PDF editing suite")

    # Loading hint
    hint_font = QFont("Segoe UI", 9)
    painter.setFont(hint_font)
    painter.setPen(QColor("#6C7086"))
    painter.drawText(0, h - 36, w, 30,
                     Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                     "Loading…")

    painter.end()
    return pm


# ─────────────────────────────────────────────────────────────────────────────
#  Final composition  MRO: UI shell → feature mixin → backend logic
# ─────────────────────────────────────────────────────────────────────────────

class PDFStudio(PDFStudioUI, PDFFeatures, PDFStudioBase):
    """Concrete application class.

    MRO ensures Qt UI shell methods take priority, the feature mixin
    sits in the middle, and backend logic fills everything else.
    """
    pass


# ─────────────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    # High-DPI support
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("PDF Studio")
    app.setOrganizationName("PDFStudio")

    # ── Splash ──────────────────────────────────────────────────────────
    splash = QSplashScreen(_make_splash(),
                           Qt.WindowType.WindowStaysOnTopHint)
    splash.show()
    app.processEvents()

    # ── Main window ─────────────────────────────────────────────────────
    window = PDFStudio()

    # Center on screen
    screen = app.primaryScreen().availableGeometry()
    W, H = 1360, 820
    window.setGeometry(
        (screen.width()  - W) // 2,
        (screen.height() - H) // 2,
        W, H,
    )

    # Close splash after 1.4 s and show main window
    def _launch():
        splash.finish(window)
        window.show()
        window.raise_()
        window.activateWindow()
        if hasattr(window, "refresh_bookmarks_sidebar"):
            QTimer.singleShot(300, window.refresh_bookmarks_sidebar)

    QTimer.singleShot(1400, _launch)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
