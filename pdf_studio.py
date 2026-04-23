"""
PDF Studio – entry point / launcher.

All shared symbols live in ``pdf_studio_common`` to avoid the circular
import that crashed the PyInstaller build (pdf_studio → backend → pdf_studio).
Backend business logic lives in ``pdf_studio_backend``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
#  Bootstrap: install runtime deps when launched from source (skipped in .exe)
# ─────────────────────────────────────────────────────────────────────────────
IS_FROZEN = getattr(sys, "frozen", False)


def install_deps():
    if IS_FROZEN or os.environ.get("PDF_STUDIO_SKIP_AUTO_INSTALL") == "1":
        return
    import subprocess
    needed = {
        "pypdf": "pypdf",
        "PIL": "Pillow",
        "pdf2image": "pdf2image",
        "pytesseract": "pytesseract",
        "fitz": "PyMuPDF",
    }
    for imp, pkg in needed.items():
        try:
            __import__(imp)
        except ImportError:
            print(f"Installing {pkg}…")
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", pkg, "-q"]
            )


install_deps()

# ─────────────────────────────────────────────────────────────────────────────
#  Re-export shared symbols so any legacy code doing
#  `from pdf_studio import PageRecord, …` keeps working.
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

import tkinter as tk  # noqa: E402

from UI.pdf_studio_ui import PDFStudioUI  # noqa: E402
from UI.pdf_features import PDFFeatures   # noqa: E402
from UI.dialog_kit import Splash          # noqa: E402

from pdf_studio_backend import PDFStudioBase  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
#  Final composition — MRO: UI shell → feature mixin → backend logic
# ─────────────────────────────────────────────────────────────────────────────
class PDFStudio(PDFStudioUI, PDFFeatures, PDFStudioBase):
    """Concrete application class.  Method-resolution order lets UI buttons
    call backend logic while the feature mixin can override either."""
    pass


def main():
    root = tk.Tk()
    # Splash first — hides root and shows it automatically after N ms
    Splash(root, duration_ms=1500)

    app = PDFStudio(root)
    root.update_idletasks()
    W, H = 1360, 820
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{W}x{H}+{(sw - W) // 2}+{(sh - H) // 2}")

    if hasattr(app, "refresh_bookmarks_sidebar"):
        root.after(200, app.refresh_bookmarks_sidebar)

    root.mainloop()


if __name__ == "__main__":
    main()
