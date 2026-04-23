"""
pdf_studio_common.py
---------------------------------------------------------------------------
Shared symbols used by BOTH pdf_studio.py (entry/launcher) and
pdf_studio_backend.py (business logic).  Kept in its own module so that
neither file needs to import the other at top-level — this is what
eliminates the circular-import crash seen in the PyInstaller build.
"""
from __future__ import annotations
import json
import os
import re
import sys
from pathlib import Path

import tkinter as tk
from PIL import Image, ImageDraw

import fitz  # PyMuPDF

# ─────────────────────────────────────────────────────────────────────────────
#  FROZEN / STATE DIR
# ─────────────────────────────────────────────────────────────────────────────
IS_FROZEN = getattr(sys, "frozen", False)


def _resolve_state_dir() -> Path:
    try:
        if IS_FROZEN:
            if sys.platform == "win32":
                base = Path(os.environ.get("APPDATA") or Path.home())
            elif sys.platform == "darwin":
                base = Path.home() / "Library" / "Application Support"
            else:
                base = Path(
                    os.environ.get("XDG_STATE_HOME")
                    or (Path.home() / ".local" / "state")
                )
            state_dir = base / "PDFStudio"
            state_dir.mkdir(parents=True, exist_ok=True)
            return state_dir
    except Exception:
        pass
    return Path.home()


STATE_DIR = _resolve_state_dir()

# ─────────────────────────────────────────────────────────────────────────────
#  CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
OPTIONS = ["Rotate 90° CW", "Rotate 90° CCW"]
OPTION_COLORS = {
    "Portrait": "#2E7D32",
    "Landscape": "#1565C0",
    "Rotate 90° CW": "#6A1B9A",
    "Rotate 90° CCW": "#E65100",
}
ROTATE_STEP = 90
THUMB_W, THUMB_H = 90, 120
ROW_H = THUMB_H + 16
PREVIEW_MIN_W = 500

RECENT_FILE = STATE_DIR / (
    "pdf_studio_recent.json" if IS_FROZEN else ".pdf_studio_recent.json"
)
SESSION_FILE = STATE_DIR / (
    "pdf_studio_session.json" if IS_FROZEN else ".pdf_studio_session.json"
)
MAX_RECENT = 12
SESSION_PERSISTENCE = False

PAGE_SIZES = {
    "A4": (595, 842),
    "A3": (842, 1191),
    "A5": (420, 595),
    "Letter": (612, 792),
    "Legal": (612, 1008),
    "Tabloid": (792, 1224),
}

DARK_THEME = {
    "bg": "#1E1E2E", "fg": "#CDD6F4", "accent": "#89B4FA",
    "row_even": "#181825", "row_odd": "#1E1E2E",
    "toolbar": "#11111B", "statusbar": "#11111B",
    "select": "#313244", "excluded": "#45293a",
    "preview_bg": "#0E0E16",
}
LIGHT_THEME = {
    "bg": "#F8FAFC", "fg": "#1E293B", "accent": "#2563EB",
    "row_even": "#FFFFFF", "row_odd": "#F0F4FF",
    "toolbar": "#1E2A3A", "statusbar": "#1E2A3A",
    "select": "#DBEAFE", "excluded": "#FEE2E2",
    "preview_bg": "#0F172A",
}


# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _to_roman(num: int) -> str:
    val = [1000, 900, 500, 400, 100, 90, 50, 40, 10, 9, 5, 4, 1]
    syms = ["M", "CM", "D", "CD", "C", "XC", "L", "XL", "X", "IX", "V", "IV", "I"]
    result = ""
    for v, s in zip(val, syms):
        while num >= v:
            result += s
            num -= v
    return result.lower()


def normalize_rotation(value, orig_orient: str = "Portrait") -> int:
    """Return a 0/90/180/270 integer for the given rotation descriptor."""
    if isinstance(value, (int, float)):
        return int(value) % 360
    s = str(value).strip()
    if s in ("Rotate 90° CW", "CW"):
        return 90
    if s in ("Rotate 90° CCW", "CCW"):
        return 270
    if s == "Portrait":
        return 0 if orig_orient == "Portrait" else 270
    if s == "Landscape":
        return 90 if orig_orient == "Portrait" else 0
    m = re.match(r"^(-?\d+)", s)
    if m:
        return int(m.group(1)) % 360
    return 0


def rotation_label(value) -> str:
    deg = normalize_rotation(value)
    if deg == 0:
        return "0°"
    if deg == 90:
        return "90° CW"
    if deg == 180:
        return "180°"
    if deg == 270:
        return "90° CCW"
    return f"{deg}°"


def effective_orientation(orig_orient: str, rotation_deg) -> str:
    """Compute the *displayed* orientation after applying rotation to a page
    whose native orientation is orig_orient.  This is what the UI badge
    should show.  90°/270° flips portrait↔landscape, 0°/180° keeps it."""
    deg = normalize_rotation(rotation_deg) % 180
    base = orig_orient if orig_orient in ("Portrait", "Landscape") else "Portrait"
    if deg == 90:
        return "Landscape" if base == "Portrait" else "Portrait"
    return base


def get_page_orientation(page) -> str:
    box = page.mediabox
    w, h = float(box.width), float(box.height)
    rot = int(page.get("/Rotate") or 0) % 360
    if rot in (90, 270):
        w, h = h, w
    return "Landscape" if w > h else "Portrait"


def apply_transform(page, choice):
    if choice is None:
        return page
    rot = normalize_rotation(choice)
    if rot:
        page.rotate(rot)
    return page


def apply_visual_rotation(img, choice):
    rot = normalize_rotation(choice)
    if rot == 90:
        return img.transpose(Image.ROTATE_270)
    if rot == 180:
        return img.transpose(Image.ROTATE_180)
    if rot == 270:
        return img.transpose(Image.ROTATE_90)
    return img


def render_page_image_fitz(pdf_path, page_index, orientation_choice, orig_orient,
                           target_w=None, target_h=None, for_thumb=False):
    try:
        doc = fitz.open(pdf_path)
        page = doc[page_index]
        zoom = 1.5 if for_thumb else 2.5
        if target_w:
            rect = page.rect
            zoom = min((target_w / rect.width) * 1.5, 3.0)
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        doc.close()
        if target_w and target_h:
            img.thumbnail((target_w, target_h), Image.LANCZOS)
        img = apply_visual_rotation(img, orientation_choice)
        return img
    except Exception:
        pass
    w = target_w or THUMB_W
    h = target_h or THUMB_H
    img = Image.new("RGB", (w, h), "#EEEEEE")
    draw = ImageDraw.Draw(img)
    draw.text((w // 2, h // 2), f"Page {page_index + 1}",
              fill="#888888", anchor="mm")
    return img


def get_page_info_fitz(pdf_path, page_index):
    try:
        doc = fitz.open(pdf_path)
        page = doc[page_index]
        rect = page.rect
        text = page.get_text().strip()
        doc.close()
        return {"width": rect.width, "height": rect.height,
                "has_text": bool(text)}
    except Exception:
        return {"width": 595, "height": 842, "has_text": False}


def load_recent_files():
    try:
        if RECENT_FILE.exists():
            data = json.loads(RECENT_FILE.read_text())
            return [p for p in data if os.path.exists(p)]
    except Exception:
        pass
    return []


def save_recent_files(paths):
    try:
        RECENT_FILE.write_text(json.dumps(paths[:MAX_RECENT]))
    except Exception:
        pass


def add_recent_file(path):
    recent = load_recent_files()
    if path in recent:
        recent.remove(path)
    recent.insert(0, path)
    save_recent_files(recent[:MAX_RECENT])


# ─────────────────────────────────────────────────────────────────────────────
#  DATA CLASSES
# ─────────────────────────────────────────────────────────────────────────────
class PageRecord:
    def __init__(self, source_path, source_index, orientation, is_blank=False):
        raw = orientation.get() if hasattr(orientation, "get") else orientation
        if raw in ("Portrait", "Landscape"):
            orig_orient = raw
        else:
            orig_orient = "Portrait"
        self.source_path = source_path
        self.source_index = source_index
        self.orientation = tk.IntVar(value=normalize_rotation(raw, orig_orient))
        self.included = tk.BooleanVar(value=True)
        self.orig_orient = orig_orient
        self.is_blank = is_blank
        self.thumb_img = None
        self.thumb_tk = None
        self.annotations = []
        self.redactions = []
        self._row_widget = None
        self._thumb_label = None
        self._rb_frame = None
        self._rot_value_lbl = None

    def snapshot(self):
        return {
            "source_path": self.source_path,
            "source_index": self.source_index,
            "orientation": int(self.orientation.get()),
            "rotation": int(self.orientation.get()),
            "included": self.included.get(),
            "is_blank": self.is_blank,
            "orig_orient": self.orig_orient,
            "annotations": list(self.annotations),
            "redactions": list(self.redactions),
        }

    @classmethod
    def from_snapshot(cls, snap):
        seed = snap.get("orig_orient", snap.get("orientation", "Portrait"))
        if seed not in ("Portrait", "Landscape"):
            seed = "Portrait"
        rec = cls(snap["source_path"], snap["source_index"],
                  tk.StringVar(value=seed),
                  is_blank=snap.get("is_blank", False))
        rec.included.set(snap.get("included", True))
        rec.orig_orient = seed
        rec.orientation.set(normalize_rotation(
            snap.get("rotation", snap.get("orientation", 0)),
            rec.orig_orient))
        rec.annotations = snap.get("annotations", [])
        rec.redactions = snap.get("redactions", [])
        return rec


class UndoStack:
    def __init__(self, max_depth: int = 60):
        self._undo = []
        self._redo = []
        self.max_depth = max_depth

    def push(self, pages_list, description: str = "action"):
        snap = [r.snapshot() for r in pages_list]
        self._undo.append((description, snap))
        if len(self._undo) > self.max_depth:
            self._undo.pop(0)
        self._redo.clear()

    def undo(self):
        if not self._undo:
            return None, None
        desc, snap = self._undo.pop()
        self._redo.append((desc, snap))
        return desc, snap

    def redo(self):
        if not self._redo:
            return None, None
        desc, snap = self._redo.pop()
        self._undo.append((desc, snap))
        return desc, snap

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def peek_undo(self):
        return self._undo[-1][0] if self._undo else ""

    def peek_redo(self):
        return self._redo[-1][0] if self._redo else ""


__all__ = [
    # constants
    "IS_FROZEN", "STATE_DIR", "OPTIONS", "OPTION_COLORS", "ROTATE_STEP",
    "THUMB_W", "THUMB_H", "ROW_H", "PREVIEW_MIN_W",
    "RECENT_FILE", "SESSION_FILE", "MAX_RECENT", "SESSION_PERSISTENCE",
    "PAGE_SIZES", "DARK_THEME", "LIGHT_THEME",
    # helpers
    "_to_roman", "normalize_rotation", "rotation_label",
    "effective_orientation", "get_page_orientation",
    "apply_transform", "apply_visual_rotation",
    "render_page_image_fitz", "get_page_info_fitz",
    "load_recent_files", "save_recent_files", "add_recent_file",
    # classes
    "PageRecord", "UndoStack",
]
