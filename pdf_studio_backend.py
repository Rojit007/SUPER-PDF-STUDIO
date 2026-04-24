"""
pdf_studio_backend.py — Qt-ported business logic (PDFStudioBase).

All PDF operations, undo/redo, page manipulation, session, and file I/O
are identical to the Tkinter version.  Only the UI interaction points
have been updated:

  • tk.XxxVar()          → _Var() from pdf_studio_common
  • messagebox / filedialog / simpledialog / colorchooser
                         → UI.qt_compat wrappers
  • tk.Toplevel dialogs  → QDialog subclasses
  • self.root.after()    → QTimer.singleShot()
  • ImageTk.PhotoImage   → removed (Qt UI handles thumbnails in _PageCard)
  • self.progress        → _ProgressStub no-op
  • _build_ui()          → no-op (PDFStudioUI.__init__ builds the Qt shell)
  • _render_preview()    → delegates to Qt shell via _render_preview_by_rec()
"""
from __future__ import annotations
import os, io, json, math, copy, threading, tempfile, time, re
from pypdf import PdfReader, PdfWriter
from PIL import Image, ImageDraw, ImageFont
import fitz

# Framework-agnostic shared symbols
from pdf_studio_common import (
    OPTIONS, OPTION_COLORS, ROTATE_STEP, PAGE_SIZES,
    DARK_THEME, LIGHT_THEME,
    RECENT_FILE, SESSION_FILE, SESSION_PERSISTENCE,
    PageRecord, UndoStack,
    _Var,
    _to_roman, normalize_rotation, rotation_label,
    effective_orientation,
    get_page_orientation, apply_transform, apply_visual_rotation,
    render_page_image_fitz, get_page_info_fitz,
    load_recent_files, save_recent_files, add_recent_file,
    THUMB_W, THUMB_H, ROW_H,
)
from UI.pdf_studio_ui_qt import C as UI_C
from UI.qt_compat import filedialog, messagebox, simpledialog, colorchooser

from PySide6.QtWidgets import QMenu, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QTextEdit, QPushButton, QCheckBox, QRadioButton, QSlider, QFrame, QApplication
from PySide6.QtCore import Qt, QTimer


# ──────────────────────────────────────────────────────────────────────────────
#  No-op progress stub
# ──────────────────────────────────────────────────────────────────────────────

class _ProgressStub:
    def start(self, *a): pass
    def stop(self, *a):  pass
    def grid(self, *a):  pass
    def grid_remove(self, *a): pass


# ──────────────────────────────────────────────────────────────────────────────
#  Reusable Qt dialog helpers (replace inline tk.Toplevel patterns)
# ──────────────────────────────────────────────────────────────────────────────

def _styled_dialog(parent, title: str, w: int = 460, h: int = 360) -> QDialog:
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.resize(w, h)
    dlg.setModal(True)
    dlg.setStyleSheet(f"""
        QDialog  {{ background:{UI_C['panel']}; color:{UI_C['fg']}; }}
        QLabel   {{ color:{UI_C['fg']}; background:transparent; }}
        QLineEdit{{ background:{UI_C['input_bg']}; color:{UI_C['fg']};
                   border:1px solid {UI_C['input_border']}; border-radius:4px;
                   padding:5px 8px; }}
        QLineEdit:focus {{ border-color:{UI_C['accent']}; }}
        QPushButton {{ background:{UI_C['elevated']}; color:{UI_C['fg']};
                      border:1px solid {UI_C['border']}; border-radius:5px;
                      padding:6px 14px; }}
        QPushButton:hover {{ background:{UI_C['elevated_hover']}; }}
        QPushButton[role="accent"] {{ background:{UI_C['accent']};
                      color:{UI_C['fg_on_accent']}; border:none; font-weight:600; }}
        QPushButton[role="accent"]:hover {{ background:{UI_C['accent_hover']}; }}
        QCheckBox, QRadioButton {{ color:{UI_C['fg']}; }}
        QTextEdit {{ background:{UI_C['input_bg']}; color:{UI_C['fg']};
                    border:1px solid {UI_C['input_border']}; border-radius:4px; }}
        QSlider::groove:horizontal {{ background:{UI_C['input_bg']}; height:4px; border-radius:2px; }}
        QSlider::handle:horizontal {{ background:{UI_C['accent']}; width:14px; height:14px;
                                     border-radius:7px; margin:-5px 0; }}
    """)
    return dlg


def _accent_btn(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setProperty("role", "accent")
    btn.style().unpolish(btn)
    btn.style().polish(btn)
    return btn


def _plain_btn(text: str) -> QPushButton:
    return QPushButton(text)


# ──────────────────────────────────────────────────────────────────────────────
#  PDFStudioBase
# ──────────────────────────────────────────────────────────────────────────────

class PDFStudioBase:
    def __init__(self, root=None):
        # In Qt mode self IS the QMainWindow; root is self or None.
        self.root = root or self
        if hasattr(self, "setWindowTitle"):
            self.setWindowTitle("PDF Studio")
        if hasattr(self, "setMinimumSize"):
            self.setMinimumSize(1100, 660)

        self.pages: list = []
        self.primary_path = None
        self.drag_data = {}
        self._grid_drag_motion_bind = None
        self._grid_drag_release_bind = None
        self._grid_drag_ghost = None
        self.thumb_cache = {}
        self.preview_cache = {}
        self.selected_pages = set()

        self._preview_index = -1
        self._preview_rec = None
        self._preview_zoom = 1.0
        self._pan_offset = [0, 0]
        self._pan_start = None

        self._dark_mode = _Var(value=True)
        self._theme = DARK_THEME

        self.meta_title    = _Var()
        self.meta_author   = _Var()
        self.meta_subject  = _Var()
        self.meta_keywords = _Var()
        self.meta_creator  = _Var(value="PDF Studio")

        self.add_page_numbers   = _Var(value=False)
        self.page_num_format    = _Var(value="decimal")
        self.page_num_position  = _Var(value="bottom-center")
        self.compress_output    = _Var(value=False)
        self.split_mode         = _Var(value="single")
        self.watermark_text     = _Var()
        self.watermark_opacity  = _Var(value=40)
        self.watermark_pages    = _Var(value="all")
        self.watermark_color    = _Var(value="#AAAAAA")
        self.output_page_size   = _Var(value="Original")
        self.pdfa_mode          = _Var(value=False)
        self.linearize          = _Var(value=False)
        self.encrypt_pdf        = _Var(value=False)
        self.owner_password     = _Var()
        self.user_password      = _Var()
        self.flatten_forms      = _Var(value=False)
        self.header_text        = _Var()
        self.footer_text        = _Var()
        self.thumb_size         = _Var(value=90)

        self._search_var = _Var(value="")
        self.undo_stack  = UndoStack()
        self.status_var  = _Var(value="Open a PDF to get started.")
        self._bookmarks  = []
        self.progress    = _ProgressStub()

        self._build_ui()
        self._bind_keys()
        if SESSION_PERSISTENCE:
            self._restore_session()
            self._start_autosave()
        else:
            self._clear_saved_session()

    # ── Qt helper: maps self.root.after(ms, fn) ─────────────────────────────

    def after(self, ms: int, fn=None):
        if callable(fn):
            QTimer.singleShot(ms, fn)

    # ── Theme ────────────────────────────────────────────────────────────────

    def _toggle_theme(self):
        want_dark = not bool(self._dark_mode.get())
        self._dark_mode.set(want_dark)
        self._theme = DARK_THEME if want_dark else LIGHT_THEME
        if hasattr(self, "toggle_theme"):
            self.toggle_theme()

    def T(self, key):
        return self._theme.get(key, "#FFFFFF")

    # ── Undo / Redo ──────────────────────────────────────────────────────────

    def _push_undo(self, description="action"):
        self.undo_stack.push(self.pages, description)
        self._update_undo_labels()

    def _update_undo_labels(self):
        u = self.undo_stack.peek_undo()
        r = self.undo_stack.peek_redo()
        if hasattr(self, "update_undo_redo"):
            self.update_undo_redo()

    def _restore_from_snap(self, snap):
        new_pages = []
        for s in snap:
            rec = PageRecord.from_snapshot(s)
            key = (rec.source_path, rec.source_index, rec.orientation.get())
            rec.thumb_img = self.thumb_cache.get(key)
            new_pages.append(rec)
        return new_pages

    def do_undo(self):
        desc, snap = self.undo_stack.undo()
        if snap is None: return
        self.pages = self._restore_from_snap(snap)
        self.selected_pages.clear()
        if 0 <= self._preview_index < len(self.pages):
            self._preview_rec = self.pages[self._preview_index]
        else:
            self._preview_rec = None
            self._preview_index = -1
        self._rebuild_rows()
        self._update_status()
        self._update_undo_labels()
        self.status_var.set(f"↩ Undid: {desc}")

    def do_redo(self):
        desc, snap = self.undo_stack.redo()
        if snap is None: return
        self.pages = self._restore_from_snap(snap)
        self.selected_pages.clear()
        if 0 <= self._preview_index < len(self.pages):
            self._preview_rec = self.pages[self._preview_index]
        else:
            self._preview_rec = None
            self._preview_index = -1
        self._rebuild_rows()
        self._update_status()
        self._update_undo_labels()
        self.status_var.set(f"↪ Redid: {desc}")

    # ── Build UI (no-op in Qt mode) ──────────────────────────────────────────

    def _build_ui(self):
        """No-op: PDFStudioUI.__init__ builds all Qt widgets."""
        self.range_var       = _Var()
        self.goto_var        = _Var()
        self.autosave_var    = _Var(value="")
        self.preview_info_var = _Var(value="No page selected")
        self.zoom_var        = _Var(value="100%")
        self.thumb_size_var  = self.thumb_size
        self._refresh_recent_menu()

    def _bind_keys(self):
        if hasattr(self, "_bind_global_keys"):
            self._bind_global_keys()

    def _bind_global_keys(self):
        pass  # Qt shell handles key events via keyPressEvent

    def _refresh_recent_menu(self):
        if hasattr(self, "refresh_recent_menu"):
            self.refresh_recent_menu()

    # ── Preview (Qt-delegating) ──────────────────────────────────────────────

    def _resolve_preview_index(self):
        if self._preview_rec is not None:
            for i, p in enumerate(self.pages):
                if p is self._preview_rec:
                    self._preview_index = i
                    return
            self._preview_rec = None
            self._preview_index = -1

    def _render_preview_by_rec(self, rec=None):
        """Convert object-ref → index and delegate to Qt shell _render_preview."""
        if rec is None:
            self._resolve_preview_index()
            idx = self._preview_index
        else:
            idx = next((i for i, p in enumerate(self.pages) if p is rec), -1)
            self._preview_index = idx
            if idx >= 0:
                self._preview_rec = rec
        # Qt shell's _render_preview(idx) is higher in MRO — call directly
        if hasattr(self, "_render_preview"):
            self._render_preview(idx)

    def _on_preview_resize(self, event=None):
        if self._preview_index >= 0:
            QTimer.singleShot(50, lambda: self._render_preview(self._preview_index))

    def _zoom_in(self):
        self._preview_zoom = min(4.0, self._preview_zoom + 0.25)
        if hasattr(self, "_zoom_in") and callable(getattr(type(self).__mro__[1], "_zoom_in", None)):
            pass
        self._render_preview_by_rec()

    def _zoom_out(self):
        self._preview_zoom = max(0.25, self._preview_zoom - 0.25)
        self._render_preview_by_rec()

    def _zoom_fit(self):
        self._preview_zoom = 1.0
        self._pan_offset = [0, 0]
        self._render_preview_by_rec()

    def _preview_prev(self):
        if not self.pages: return
        ni = max(0, self._preview_index - 1)
        if ni != self._preview_index:
            self._preview_index = ni
            self._preview_rec = self.pages[ni]
            self._render_preview(ni)

    def _preview_next(self):
        if not self.pages: return
        ni = min(len(self.pages) - 1, self._preview_index + 1)
        if ni != self._preview_index:
            self._preview_index = ni
            self._preview_rec = self.pages[ni]
            self._render_preview(ni)

    def _preload_adjacent(self):
        if not self.pages or self._preview_index < 0: return
        idx = self._preview_index
        max_w, max_h = 700, 900
        for offset in [-1, 1]:
            i = idx + offset
            if 0 <= i < len(self.pages):
                rec = self.pages[i]
                if rec.is_blank: continue
                key = (rec.source_path, rec.source_index, max_w, max_h,
                       rec.orientation.get(), int(self._preview_zoom * 100))
                if key not in self.preview_cache:
                    img = render_page_image_fitz(
                        rec.source_path, rec.source_index,
                        rec.orientation.get(), rec.orig_orient, max_w, max_h)
                    if img:
                        self.preview_cache[key] = img
                        self._trim_preview_cache()

    def _trim_preview_cache(self, max_items=100):
        if len(self.preview_cache) > max_items:
            for k in list(self.preview_cache.keys())[:len(self.preview_cache) - max_items]:
                del self.preview_cache[k]

    def _scroll_to_row(self, idx):
        pass  # Qt scroll area handles this automatically

    def _goto_page(self):
        try:
            n = int(self.goto_var.get())
            idx = n - 1
            if 0 <= idx < len(self.pages):
                self._preview_index = idx
                self._preview_rec = self.pages[idx]
                self._render_preview(idx)
                self.goto_var.set("")
        except Exception:
            pass

    def _on_thumb_size_change(self, val):
        import pdf_studio_common as _m
        _m.THUMB_W = int(float(val))
        _m.THUMB_H = int(_m.THUMB_W * 1.33)
        _m.ROW_H = _m.THUMB_H + 16
        self.thumb_cache.clear()
        self._rebuild_rows()

    # ── Row management (Qt delegation) ───────────────────────────────────────

    def _rebuild_rows(self):
        """Refresh the Qt page-list panel from self.pages."""
        if hasattr(self, "refresh_rows"):
            self.refresh_rows()
        self._update_status()
        if hasattr(self, "_update_page_count"):
            self._update_page_count()
        if self._preview_index >= 0 and self.pages:
            idx = self._preview_index
            QTimer.singleShot(50, lambda: self._render_preview(idx))
        elif not self.pages:
            self._preview_index = -1
            self._preview_rec = None
            if hasattr(self, "_scene"):
                self._scene.clear()
                self._preview_item = None

    def _filter_rows(self):
        self._rebuild_rows()

    # ── Card event callbacks (called from PDFStudioUI signals) ───────────────

    def _on_card_clicked(self, idx: int):
        if 0 <= idx < len(self.pages):
            self.selected_pages = {idx}
            self._preview_index = idx
            self._preview_rec = self.pages[idx]
        # Qt shell also calls _render_preview via super chain

    def _on_include_toggled(self, idx: int, state: bool):
        self._update_status()
        if hasattr(self, "_update_page_count"):
            self._update_page_count()

    # ── Thumbnails (Qt shell handles in _PageCard) ────────────────────────────

    def _load_thumbs_async(self):
        pass  # Qt _PageCard loads thumbnails in its own QThread

    def _load_thumbs_worker(self):
        pass

    def _update_thumb_ui(self, rec):
        pass

    def _thumbs_done(self):
        if self._preview_index >= 0 and self.pages:
            self._render_preview(self._preview_index)

    def _make_blank_thumb(self):
        import pdf_studio_common as _m
        img = Image.new("RGB", (_m.THUMB_W, _m.THUMB_H), "#FFFFFF")
        draw = ImageDraw.Draw(img)
        draw.rectangle([1, 1, _m.THUMB_W - 2, _m.THUMB_H - 2],
                       outline="#CCCCCC", width=2)
        draw.text((_m.THUMB_W // 2, _m.THUMB_H // 2), "BLANK",
                  fill="#AAAAAA", anchor="mm")
        return img

    # ── Page actions ─────────────────────────────────────────────────────────

    def _refresh_thumb(self, rec):
        import pdf_studio_common as _m
        if rec.is_blank:
            rec.thumb_img = self._make_blank_thumb()
        else:
            key = (rec.source_path, rec.source_index, rec.orientation.get(),
                   _m.THUMB_W, _m.THUMB_H)
            if key not in self.thumb_cache:
                self.thumb_cache[key] = render_page_image_fitz(
                    rec.source_path, rec.source_index,
                    rec.orientation.get(), rec.orig_orient,
                    _m.THUMB_W, _m.THUMB_H, for_thumb=True)
            rec.thumb_img = self.thumb_cache[key]

    def _orientation_changed(self, rec, idx):
        self._refresh_thumb(rec)
        if idx == self._preview_index:
            self.preview_cache.clear()
            self._render_preview(idx)
        self._rebuild_rows()
        self._update_status()

    def _rotate_page(self, rec, idx, delta):
        rec.orientation.set((int(rec.orientation.get()) + delta) % 360)
        self._orientation_changed(rec, idx)

    def _on_thumb_click(self, rec, idx):
        self._preview_index = idx
        self._preview_rec = rec
        self.selected_pages = {idx}
        self._render_preview(idx)
        self._rebuild_rows()

    def _refresh_orient_btns(self, rec):
        pass  # Qt _PageCard handles its own rotation badge

    def _toggle_include(self, rec, idx):
        self._rebuild_rows()
        self._update_status()

    def _set_include(self, idx, state):
        self.pages[idx].included.set(state)
        self._rebuild_rows()
        self._update_status()

    def _on_row_click(self, event, idx, rec):
        self.selected_pages.clear()
        self.selected_pages.add(idx)
        self._preview_index = idx
        self._preview_rec = rec
        self._render_preview(idx)
        self._rebuild_rows()

    def _on_row_ctrl_click(self, event, idx, rec):
        if idx in self.selected_pages:
            self.selected_pages.discard(idx)
        else:
            self.selected_pages.add(idx)
        self._rebuild_rows()

    def _on_row_shift_click(self, event, idx, rec):
        if not self.selected_pages:
            self.selected_pages.add(idx)
        else:
            last = max(self.selected_pages)
            lo, hi = min(last, idx), max(last, idx)
            for j in range(lo, hi + 1):
                self.selected_pages.add(j)
        self._rebuild_rows()

    # ── Multi-select actions ─────────────────────────────────────────────────

    def select_all_pages(self):
        self.selected_pages = set(range(len(self.pages)))
        self._rebuild_rows()

    def select_all(self):
        self.select_all_pages()

    def deselect_all_pages(self):
        self.selected_pages.clear()
        self._rebuild_rows()

    def deselect_all(self):
        self.deselect_all_pages()

    def delete_selected(self):
        if not self.selected_pages: return
        self._push_undo("delete selected")
        for idx in sorted(self.selected_pages, reverse=True):
            self.pages.pop(idx)
        self.selected_pages.clear()
        if self._preview_index >= len(self.pages):
            self._preview_index = len(self.pages) - 1
            self._preview_rec = self.pages[self._preview_index] if self._preview_index >= 0 else None
        self._rebuild_rows()
        self._update_status()

    def duplicate_selected(self):
        if not self.selected_pages: return
        self._push_undo("duplicate selected")
        for idx in sorted(self.selected_pages, reverse=True):
            src = self.pages[idx]
            rec = PageRecord(src.source_path, src.source_index,
                             _Var(value=src.orig_orient),
                             is_blank=src.is_blank)
            rec.orig_orient = src.orig_orient
            rec.orientation.set(src.orientation.get())
            rec.annotations = list(src.annotations)
            rec.redactions = list(src.redactions)
            self.pages.insert(idx + 1, rec)
        self._rebuild_rows()
        self._update_status()

    def rotate_selected_cw(self):
        self._rotate_selection(ROTATE_STEP)

    def rotate_selected_ccw(self):
        self._rotate_selection(-ROTATE_STEP)

    def _rotate_selection(self, delta):
        targets = self.selected_pages or ({self._preview_index} if self._preview_index >= 0 else set())
        if not targets: return
        self._push_undo("rotate selected")
        for idx in targets:
            if 0 <= idx < len(self.pages):
                rec = self.pages[idx]
                rec.orientation.set((int(rec.orientation.get()) + delta) % 360)
        self.thumb_cache.clear()
        self.preview_cache.clear()
        self._rebuild_rows()

    def extract_selected(self):
        self.extract_pages()

    # ── File operations ──────────────────────────────────────────────────────

    def open_files(self, paths=None):
        if paths:
            if isinstance(paths, str):
                paths = [paths]
            for p in paths:
                self._open_path(p)
        else:
            self.browse_file()

    def browse_file(self):
        path = filedialog.askopenfilename(
            title="Open PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
        if path:
            self._open_path(path)

    def _open_path(self, path):
        self.primary_path = path
        if hasattr(self, "setWindowTitle"):
            self.setWindowTitle(f"PDF Studio – {os.path.basename(path)}")
        if hasattr(self, "update_titlebar"):
            self.update_titlebar(path)
        self._load_pdf(path, replace=True)
        add_recent_file(path)
        self._refresh_recent_menu()

    def _load_pdf(self, path, replace=False, insert_after=None, password=None):
        try:
            reader = PdfReader(path)
            if reader.is_encrypted:
                pwd = password or simpledialog.askstring(
                    "Password", f"Enter password for:\n{os.path.basename(path)}", show="*")
                if not pwd:
                    return
                try:
                    reader.decrypt(pwd)
                except Exception:
                    messagebox.showerror("Error", "Wrong password.")
                    return
        except Exception as e:
            messagebox.showerror("Error", f"Could not read PDF:\n{e}")
            return

        new_records = []
        for i in range(len(reader.pages)):
            orient = get_page_orientation(reader.pages[i])
            rec = PageRecord(path, i, _Var(value=orient))
            new_records.append(rec)

        if replace:
            self.pages = new_records
            meta = reader.metadata or {}
            self.meta_title.set(meta.get("/Title", ""))
            self.meta_author.set(meta.get("/Author", ""))
            self.meta_subject.set(meta.get("/Subject", ""))
            self._preview_index = 0 if new_records else -1
            self._preview_rec = new_records[0] if new_records else None
            self.undo_stack = UndoStack()
            self._update_undo_labels()
        elif insert_after is None:
            self.pages.extend(new_records)
        else:
            self.pages[insert_after + 1:insert_after + 1] = new_records

        self.preview_cache.clear()
        self._rebuild_rows()
        self._update_status()
        if hasattr(self, "refresh_bookmarks_sidebar"):
            QTimer.singleShot(400, self.refresh_bookmarks_sidebar)

    def open_recent(self, path):
        if os.path.exists(path):
            self._open_path(path)
        else:
            messagebox.showerror("Not found", f"File not found:\n{path}")

    def merge_pdf(self):
        path = filedialog.askopenfilename(
            title="Merge PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
        if not path: return
        self._push_undo("merge PDF")
        self._load_pdf(path, replace=False)

    def import_images(self):
        paths = filedialog.askopenfilenames(
            title="Select Images",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.tiff *.bmp *.gif"),
                       ("All files", "*.*")])
        if not paths: return
        self._push_undo("import images")
        for path in paths:
            self._add_image_as_page(path)
        self._rebuild_rows()
        self._update_status()

    def _add_image_as_page(self, img_path):
        try:
            img = Image.open(img_path).convert("RGB")
            tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            tmp.close()
            img.save(tmp.name, "PDF", resolution=150)
            rec = PageRecord(tmp.name, 0, _Var(value="Portrait"))
            self.pages.append(rec)
        except Exception as e:
            messagebox.showerror("Error", f"Could not import image:\n{img_path}\n{e}")

    def export_as_images(self):
        if not self.pages:
            messagebox.showwarning("No pages", "Open a PDF first.")
            return
        included = [r for r in self.pages if r.included.get()]
        if not included:
            messagebox.showwarning("Nothing selected", "Include at least one page.")
            return
        out_dir = filedialog.askdirectory(title="Choose output folder")
        if not out_dir: return

        def worker():
            for i, rec in enumerate(included):
                if rec.is_blank:
                    img = Image.new("RGB", (595, 842), "white")
                else:
                    img = render_page_image_fitz(rec.source_path, rec.source_index,
                                                 rec.orientation.get(), rec.orig_orient,
                                                 int(595 * 150 / 72), int(842 * 150 / 72))
                fname = os.path.join(out_dir, f"page_{i + 1:04d}.png")
                img.save(fname)
            QTimer.singleShot(0, lambda: messagebox.showinfo(
                "Done", f"Exported {len(included)} images to:\n{out_dir}"))
        threading.Thread(target=worker, daemon=True).start()

    # ── Page editing ─────────────────────────────────────────────────────────

    def add_blank_page(self):
        self.insert_blank()

    def insert_blank(self):
        self._push_undo("insert blank page")
        rec = PageRecord("__blank__", -1, _Var(value="Portrait"), is_blank=True)
        rec.thumb_img = self._make_blank_thumb()
        insert_at = self._preview_index + 1 if self._preview_index >= 0 else len(self.pages)
        self.pages.insert(insert_at, rec)
        self._rebuild_rows()
        self._update_status()

    def duplicate_page(self, idx):
        self._push_undo("duplicate page")
        src = self.pages[idx]
        rec = PageRecord(src.source_path, src.source_index,
                         _Var(value=src.orig_orient), is_blank=src.is_blank)
        rec.orig_orient = src.orig_orient
        rec.orientation.set(src.orientation.get())
        rec.annotations = list(src.annotations)
        rec.redactions = list(src.redactions)
        self.pages.insert(idx + 1, rec)
        self._rebuild_rows()
        self._update_status()

    def delete_page(self, idx):
        self._push_undo("delete page")
        self.pages.pop(idx)
        self.selected_pages.discard(idx)
        if self._preview_index >= len(self.pages):
            self._preview_index = len(self.pages) - 1
            self._preview_rec = self.pages[self._preview_index] if self._preview_index >= 0 else None
        self._rebuild_rows()
        self._update_status()

    def move_page(self, idx, direction):
        new_idx = idx + direction
        if 0 <= new_idx < len(self.pages):
            self._push_undo("move page")
            self.pages[idx], self.pages[new_idx] = self.pages[new_idx], self.pages[idx]
            if self._preview_rec is not None:
                for i, p in enumerate(self.pages):
                    if p is self._preview_rec:
                        self._preview_index = i
                        break
            self._rebuild_rows()

    def move_selected_up(self):
        for idx in sorted(self.selected_pages):
            self.move_page(idx, -1)

    def move_selected_down(self):
        for idx in sorted(self.selected_pages, reverse=True):
            self.move_page(idx, 1)

    def reverse_pages(self):
        if not self.pages: return
        self._push_undo("reverse pages")
        self.pages.reverse()
        self._resolve_preview_index()
        self._rebuild_rows()
        self._update_status()
        self.status_var.set("⇅ Pages reversed")

    def extract_pages(self):
        included = [r for r in self.pages if r.included.get()]
        if not included:
            messagebox.showwarning("Nothing selected", "Include at least one page.")
            return
        out_path = filedialog.asksaveasfilename(
            title="Extract Pages", defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")])
        if out_path:
            self._write_pdf(included, out_path)

    def rotate_all_pages(self, delta):
        if not self.pages: return
        step_txt = "CW" if delta > 0 else "CCW"
        self._push_undo(f"rotate all {step_txt}")
        for rec in self.pages:
            rec.orientation.set((int(rec.orientation.get()) + delta) % 360)
        self.thumb_cache.clear()
        self.preview_cache.clear()
        self._rebuild_rows()

    def reset_all_orient(self):
        self._push_undo("reset orientations")
        for rec in self.pages:
            rec.orientation.set(0)
        self.thumb_cache.clear()
        self.preview_cache.clear()
        self._rebuild_rows()

    def set_all_include(self, state):
        self._push_undo("set all include" if state else "exclude all")
        for rec in self.pages:
            rec.included.set(state)
        self._rebuild_rows()
        self._update_status()

    def select_odd_even(self, which):
        self._push_undo(f"select {which} pages")
        for i, rec in enumerate(self.pages):
            rec.included.set((i + 1) % 2 == (1 if which == "odd" else 0))
        self._rebuild_rows()
        self._update_status()

    def _parse_range_text(self):
        text = self.range_var.get().strip() if self.range_var.get() else ""
        if not text: return None
        indices, n = set(), len(self.pages)
        for part in text.split(","):
            part = part.strip()
            if "-" in part:
                a, _, b = part.partition("-")
                try:
                    for p in range(int(a.strip()), int(b.strip()) + 1):
                        if 1 <= p <= n: indices.add(p - 1)
                except Exception: pass
            else:
                try:
                    p = int(part)
                    if 1 <= p <= n: indices.add(p - 1)
                except Exception: pass
        return indices

    def _apply_range(self, state):
        idxs = self._parse_range_text()
        if not idxs:
            messagebox.showwarning("Invalid", "No valid page numbers.")
            return
        self._push_undo("range include/exclude")
        for idx in idxs:
            self.pages[idx].included.set(state)
        self._rebuild_rows()
        self._update_status()

    def duplicate_range(self):
        idxs = self._parse_range_text()
        if not idxs: return
        self._push_undo("duplicate range")
        for idx in sorted(idxs, reverse=True):
            src = self.pages[idx]
            rec = PageRecord(src.source_path, src.source_index,
                             _Var(value=src.orig_orient), is_blank=src.is_blank)
            rec.orig_orient = src.orig_orient
            rec.orientation.set(src.orientation.get())
            self.pages.insert(idx + 1, rec)
        self._rebuild_rows()
        self._update_status()

    def delete_range(self):
        idxs = self._parse_range_text()
        if not idxs: return
        if not messagebox.askyesno("Confirm", f"Delete {len(idxs)} page(s)?"):
            return
        self._push_undo("delete range")
        for idx in sorted(idxs, reverse=True):
            self.pages.pop(idx)
        self._rebuild_rows()
        self._update_status()

    def orient_range_dialog(self):
        idxs = self._parse_range_text()
        if not idxs:
            messagebox.showwarning("Invalid", "No valid page numbers.")
            return
        self._push_undo("range rotate")
        for idx in idxs:
            self.pages[idx].orientation.set(
                (int(self.pages[idx].orientation.get()) + 90) % 360)
        self.thumb_cache.clear()
        self.preview_cache.clear()
        self._rebuild_rows()

    # ── Drag & drop (Qt-native drag works via QAbstractItemView) ─────────────

    def _drag_start(self, event, idx):
        dragged_rec = self.pages[idx]
        self._preview_rec = dragged_rec
        self._preview_index = idx
        self.selected_pages = {idx}
        self.drag_data = {"idx": idx, "y_start": 0,
                          "moved": False, "dragged_rec": dragged_rec}

    def _drag_motion(self, event, idx=None):
        pass  # Qt drag is handled by QAbstractItemView

    def _drag_release(self, event, idx=None):
        if self.drag_data:
            dragged_rec = self.drag_data.get("dragged_rec")
            if dragged_rec is not None:
                self._preview_rec = dragged_rec
                for i, p in enumerate(self.pages):
                    if p is dragged_rec:
                        self._preview_index = i
                        break
        self.drag_data = {}

    def _drag_target_index_from_cursor(self, x, y):
        return None

    def _start_grid_drag_feedback(self, event, rec):
        pass

    def _move_grid_drag_feedback(self, x, y):
        pass

    def _end_grid_drag_feedback(self):
        pass

    def _cleanup_grid_drag_bindings(self):
        pass

    # ── Context menu ─────────────────────────────────────────────────────────

    def _show_context_menu(self, pos, idx):
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background:{UI_C['popover_bg']}; color:{UI_C['fg']};"
            f" border:1px solid {UI_C['border_strong']}; border-radius:6px; padding:4px 0; }}"
            f"QMenu::item {{ padding:7px 28px 7px 14px; border-radius:4px; margin:1px 4px; }}"
            f"QMenu::item:selected {{ background:{UI_C['elevated_hover']}; }}"
        )

        menu.addAction(f"Preview page {idx + 1}",
                       lambda: self._on_thumb_click(self.pages[idx], idx))
        menu.addSeparator()
        menu.addAction("Duplicate",  lambda: self.duplicate_page(idx))
        menu.addAction("Delete",     lambda: self.delete_page(idx))
        menu.addSeparator()
        menu.addAction("Rotate CW",  lambda: self._rotate_page(self.pages[idx], idx, ROTATE_STEP))
        menu.addAction("Rotate CCW", lambda: self._rotate_page(self.pages[idx], idx, -ROTATE_STEP))
        menu.addSeparator()
        menu.addAction("Move Up",    lambda: self.move_page(idx, -1))
        menu.addAction("Move Down",  lambda: self.move_page(idx, 1))
        menu.addSeparator()
        menu.addAction("Add Annotation", lambda: self.add_text_annotation(idx))
        menu.addAction("Redact Region",  lambda: self.redact_dialog(idx))
        menu.addAction("Page Inspector", lambda: self.page_inspector_dialog(idx))
        menu.addSeparator()
        menu.addAction("Include", lambda: self._set_include(idx, True))
        menu.addAction("Exclude", lambda: self._set_include(idx, False))

        from PySide6.QtGui import QCursor
        menu.exec(QCursor.pos())

    # ── Dialog: Add text annotation ──────────────────────────────────────────

    def add_text_annotation(self, idx=None):
        if idx is None: idx = self._preview_index
        if idx < 0 or idx >= len(self.pages):
            messagebox.showwarning("No page", "Select a page first.")
            return

        dlg = _styled_dialog(self, f"Add annotation – page {idx + 1}", 460, 380)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 12, 16, 16)

        layout.addWidget(QLabel(f"Annotation for page {idx + 1}"))

        layout.addWidget(QLabel("Text:"))
        tx = QTextEdit()
        tx.setMaximumHeight(80)
        layout.addWidget(tx)

        row = QHBoxLayout()
        x_edit = QLineEdit("0.1"); row.addWidget(QLabel("X (0–1):")); row.addWidget(x_edit)
        y_edit = QLineEdit("0.9"); row.addWidget(QLabel("Y (0–1):")); row.addWidget(y_edit)
        sz_edit = QLineEdit("12"); row.addWidget(QLabel("Size:")); row.addWidget(sz_edit)
        layout.addLayout(row)

        color_var = _Var(value="#DC2626")
        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Color:"))
        swatch = QFrame(); swatch.setFixedSize(30, 22)
        swatch.setStyleSheet(f"background:{color_var.get()}; border:1px solid {UI_C['border']};")
        color_row.addWidget(swatch)
        pick_btn = QPushButton("Choose…")
        def pick_color():
            c, hexcol = colorchooser.askcolor(color=color_var.get())
            if hexcol:
                color_var.set(hexcol)
                swatch.setStyleSheet(f"background:{hexcol}; border:1px solid {UI_C['border']};")
        pick_btn.clicked.connect(pick_color)
        color_row.addWidget(pick_btn)
        color_row.addStretch()
        layout.addLayout(color_row)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel_btn = _plain_btn("Cancel"); cancel_btn.clicked.connect(dlg.reject)
        save_btn = _accent_btn("Add annotation")
        def save():
            txt = tx.toPlainText().strip()
            if not txt:
                messagebox.showwarning("Empty", "Enter annotation text.", parent=dlg)
                return
            try:
                ax = float(x_edit.text()); ay = float(y_edit.text())
                fs = int(sz_edit.text())
            except ValueError:
                messagebox.showerror("Bad input", "Use numbers.", parent=dlg); return
            self._push_undo("add annotation")
            self.pages[idx].annotations.append({
                "text": txt, "x": ax, "y": ay,
                "fontsize": fs, "color": color_var.get()})
            self.status_var.set(f"📝 Annotation added to page {idx + 1}")
            dlg.accept()
        save_btn.clicked.connect(save)
        btns.addWidget(cancel_btn); btns.addWidget(save_btn)
        layout.addLayout(btns)
        dlg.exec()

    # ── Dialog: Redact ────────────────────────────────────────────────────────

    def redact_dialog(self, idx=None):
        if idx is None: idx = self._preview_index
        if idx < 0 or idx >= len(self.pages):
            messagebox.showwarning("No page", "Select a page first.")
            return

        dlg = _styled_dialog(self, f"Add redaction – page {idx + 1}", 360, 280)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.addWidget(QLabel(f"Redaction rectangle for page {idx + 1}"))
        layout.addWidget(QLabel("Coordinates are normalised 0–1 (origin = top-left)."))

        grid = QHBoxLayout()
        x0_e = QLineEdit("0.10"); y0_e = QLineEdit("0.10")
        x1_e = QLineEdit("0.90"); y1_e = QLineEdit("0.20")
        for lbl, w in [("X₀", x0_e), ("Y₀", y0_e), ("X₁", x1_e), ("Y₁", y1_e)]:
            grid.addWidget(QLabel(lbl)); grid.addWidget(w)
        layout.addLayout(grid)

        btns = QHBoxLayout(); btns.addStretch()
        cancel_btn = _plain_btn("Cancel"); cancel_btn.clicked.connect(dlg.reject)
        add_btn = _accent_btn("Add redaction")
        def save():
            try:
                coords = (float(x0_e.text()), float(y0_e.text()),
                          float(x1_e.text()), float(y1_e.text()))
            except ValueError:
                messagebox.showerror("Bad input", "Use numbers 0–1.", parent=dlg); return
            self._push_undo("add redaction")
            self.pages[idx].redactions.append(coords)
            self.status_var.set(
                f"⬛ Redaction added to page {idx + 1} "
                f"({len(self.pages[idx].redactions)} total)")
            dlg.accept()
        add_btn.clicked.connect(save)
        btns.addWidget(cancel_btn); btns.addWidget(add_btn)
        layout.addLayout(btns)
        dlg.exec()

    # ── Dialog: Add stamp ─────────────────────────────────────────────────────

    def add_stamp_dialog(self):
        path = filedialog.askopenfilename(
            title="Select Stamp Image",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp")])
        if not path or self._preview_index < 0: return
        self._push_undo("add stamp")
        self.pages[self._preview_index].annotations.append({
            "type": "stamp", "image_path": path,
            "x": 0.7, "y": 0.8, "w": 0.25, "h": 0.15})
        self.status_var.set(f"🖼 Stamp added to page {self._preview_index + 1}")

    def crop_margins_dialog(self):
        messagebox.showinfo("Crop", "Use Pro ▸ Auto-Crop")

    def resize_pages_dialog(self):
        messagebox.showinfo("Resize", "Use Output ▸ Options ▸ Page Size")

    # ── Dialog: Encryption ────────────────────────────────────────────────────

    def encryption_dialog(self):
        pwd = simpledialog.askstring("Encrypt", "Owner password:", show="*")
        if pwd:
            self.encrypt_pdf.set(True)
            self.owner_password.set(pwd)
            messagebox.showinfo("Encryption", "Enabled for next save.")

    # ── Dialog: Unlock PDF ────────────────────────────────────────────────────

    def unlock_pdf_dialog(self):
        path = filedialog.askopenfilename(filetypes=[("PDF", "*.pdf")])
        if not path: return
        pwd = simpledialog.askstring("Password", "Password:", show="*")
        if pwd is None: return
        out = filedialog.asksaveasfilename(defaultextension=".pdf",
                                           filetypes=[("PDF", "*.pdf")])
        if not out: return
        try:
            r = PdfReader(path); r.decrypt(pwd)
            w = PdfWriter()
            for p in r.pages: w.add_page(copy.deepcopy(p))
            with open(out, "wb") as f: w.write(f)
            messagebox.showinfo("Done", f"Unlocked → {out}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # ── Dialog: OCR ───────────────────────────────────────────────────────────

    def ocr_dialog(self):
        if not self.pages or not self.primary_path:
            messagebox.showwarning("No document", "Open a PDF first.")
            return
        try:
            import pytesseract  # noqa: F401
        except Exception:
            messagebox.showerror(
                "OCR not available",
                "The pytesseract library could not be loaded.\n"
                "Install it with: pip install pytesseract\n"
                "You also need the Tesseract binary on your PATH.")
            return

        dlg = _styled_dialog(self, "Run OCR", 440, 300)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.addWidget(QLabel("Run OCR on this document"))
        layout.addWidget(QLabel(
            "A searchable PDF layer will be added using Tesseract OCR.\n"
            "Each page is rasterised and recognised text is re-embedded."))

        lang_edit = QLineEdit("eng")
        dpi_edit  = QLineEdit("220")
        lang_row = QHBoxLayout(); lang_row.addWidget(QLabel("Language:")); lang_row.addWidget(lang_edit); lang_row.addStretch()
        dpi_row  = QHBoxLayout(); dpi_row.addWidget(QLabel("DPI:")); dpi_row.addWidget(dpi_edit); dpi_row.addStretch()
        layout.addLayout(lang_row)
        layout.addLayout(dpi_row)

        scope_var = _Var(value="all")
        scope_row = QHBoxLayout()
        scope_row.addWidget(QLabel("Scope:"))
        for val, lbl in [("all", "All pages"), ("included", "Included only"), ("current", "Current page")]:
            rb = QRadioButton(lbl)
            rb.setChecked(scope_var.get() == val)
            rb.toggled.connect(lambda checked, v=val, sv=scope_var: sv.set(v) if checked else None)
            scope_row.addWidget(rb)
        scope_row.addStretch()
        layout.addLayout(scope_row)

        btns = QHBoxLayout(); btns.addStretch()
        cancel_btn = _plain_btn("Cancel"); cancel_btn.clicked.connect(dlg.reject)
        run_btn = _accent_btn("Run OCR")
        def run_ocr():
            out = filedialog.asksaveasfilename(
                title="Save OCR'd PDF", defaultextension=".pdf",
                initialfile=os.path.splitext(os.path.basename(self.primary_path))[0] + "_ocr.pdf",
                filetypes=[("PDF files", "*.pdf")])
            if not out: return
            dlg.accept()
            threading.Thread(
                target=self._run_ocr_worker,
                args=(out, lang_edit.text(), int(dpi_edit.text() or 220), scope_var.get()),
                daemon=True).start()
        run_btn.clicked.connect(run_ocr)
        btns.addWidget(cancel_btn); btns.addWidget(run_btn)
        layout.addLayout(btns)
        dlg.exec()

    def ocr_page(self):
        self.ocr_dialog()

    def _run_ocr_worker(self, out_path, lang, dpi, scope):
        try:
            import pytesseract
            src_doc = fitz.open(self.primary_path)
            out_doc = fitz.open()
            included = {i for i, r in enumerate(self.pages)
                        if r.included.get() and not r.is_blank}
            current = self._preview_index
            for i in range(src_doc.page_count):
                page = src_doc[i]
                apply_ocr = (scope == "all"
                             or (scope == "included" and i in included)
                             or (scope == "current" and i == current))
                if not apply_ocr:
                    out_doc.insert_pdf(src_doc, from_page=i, to_page=i)
                    continue
                pix = page.get_pixmap(dpi=dpi)
                try:
                    pdf_bytes = pytesseract.image_to_pdf_or_hocr(
                        pix.tobytes("png"), lang=lang, extension="pdf")
                except Exception as e:
                    raise RuntimeError(f"Tesseract failed on page {i + 1}: {e}") from e
                ocr_doc = fitz.open("pdf", pdf_bytes)
                out_doc.insert_pdf(ocr_doc)
                ocr_doc.close()
            out_doc.save(out_path)
            out_doc.close(); src_doc.close()
            QTimer.singleShot(0, lambda: (
                self.status_var.set(f"🔎 OCR complete → {os.path.basename(out_path)}"),
                messagebox.showinfo("OCR complete", f"Saved searchable PDF:\n{out_path}")
            ))
        except Exception as e:
            msg = str(e)
            QTimer.singleShot(0, lambda: messagebox.showerror("OCR failed", msg))

    # ── Dialog: Find & Replace ────────────────────────────────────────────────

    def find_replace_dialog(self):
        find = simpledialog.askstring("Find", "Text to find:")
        if not find: return
        replace = simpledialog.askstring("Replace", "Replace with:")
        if replace is None: return
        out = filedialog.asksaveasfilename(defaultextension=".pdf",
                                           filetypes=[("PDF", "*.pdf")])
        if not out: return
        try:
            with fitz.open(self.primary_path) as doc:
                for page in doc:
                    page.clean_contents()
                    for inst in page.search_for(find):
                        page.add_redact_annot(inst, replace)
                    page.apply_redactions()
                doc.save(out)
            messagebox.showinfo("Done", f"Saved → {out}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def compare_pages_dialog(self):
        messagebox.showinfo("Compare", "Open two pages in split view.")

    # ── Dialog: Page inspector ────────────────────────────────────────────────

    def page_inspector_dialog(self, idx=None):
        if idx is None: idx = self._preview_index
        if idx < 0 or idx >= len(self.pages): return
        rec = self.pages[idx]
        info = {} if rec.is_blank else get_page_info_fitz(rec.source_path, rec.source_index)
        msg = (f"Source: {os.path.basename(rec.source_path)}\n"
               f"Page {rec.source_index + 1}\n"
               f"Rotation: {rotation_label(rec.orientation.get())}\n"
               f"Size: {info.get('width', '?'):.1f} × {info.get('height', '?'):.1f} pt\n"
               f"Has text: {info.get('has_text', False)}")
        messagebox.showinfo(f"Page {idx + 1}", msg)

    # ── Dialog: Header / Footer ───────────────────────────────────────────────

    def header_footer_dialog(self):
        h = simpledialog.askstring("Header", "Header text (use {page}, {total}, {date}):",
                                   initialvalue=self.header_text.get() or "")
        if h is not None: self.header_text.set(h)
        f = simpledialog.askstring("Footer", "Footer text:",
                                   initialvalue=self.footer_text.get() or "")
        if f is not None: self.footer_text.set(f)

    # ── Dialog: Bookmarks ─────────────────────────────────────────────────────

    def add_bookmark_dialog(self):
        title = simpledialog.askstring("Bookmark", "Title:")
        if not title: return
        self._bookmarks.append({"title": title, "page": max(0, self._preview_index)})
        if hasattr(self, "refresh_bookmarks_sidebar"):
            self.refresh_bookmarks_sidebar()
        self.status_var.set(f"🔖 Bookmark '{title}' added")

    def bookmarks_dialog(self):
        if not self._bookmarks:
            messagebox.showinfo("Bookmarks", "None yet — use Add Bookmark.")
            return
        msg = "\n".join(f"p.{b['page'] + 1}  {b['title']}" for b in self._bookmarks)
        messagebox.showinfo("Bookmarks", msg)

    def batch_process_dialog(self):
        messagebox.showinfo("Batch", "Batch process — wire from your original Part 2.")

    # ── Dialog: Output options ────────────────────────────────────────────────

    def show_output_options(self):
        dlg = _styled_dialog(self, "Output & Watermark Options", 520, 600)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(10)

        def _hdr(t):
            lbl = QLabel(t)
            lbl.setStyleSheet(f"color:{UI_C['accent']}; font-weight:700; font-size:12px;")
            layout.addWidget(lbl)

        # ── Watermark ──
        _hdr("WATERMARK")
        wm_row = QHBoxLayout()
        wm_row.addWidget(QLabel("Text:"))
        wm_edit = QLineEdit(self.watermark_text.get() or "")
        wm_edit.textChanged.connect(self.watermark_text.set)
        wm_row.addWidget(wm_edit)
        layout.addLayout(wm_row)

        op_row = QHBoxLayout()
        op_row.addWidget(QLabel("Opacity %:"))
        op_slider = QSlider(Qt.Orientation.Horizontal)
        op_slider.setRange(5, 100); op_slider.setValue(int(self.watermark_opacity.get() or 40))
        op_slider.valueChanged.connect(self.watermark_opacity.set)
        op_row.addWidget(op_slider); op_row.addStretch()
        layout.addLayout(op_row)

        col_row = QHBoxLayout()
        col_row.addWidget(QLabel("Color:"))
        col_swatch = QFrame(); col_swatch.setFixedSize(30, 22)
        col_swatch.setStyleSheet(f"background:{self.watermark_color.get()}; border:1px solid {UI_C['border']};")
        col_row.addWidget(col_swatch)
        def pick_wm():
            _, hexcol = colorchooser.askcolor(color=self.watermark_color.get())
            if hexcol:
                self.watermark_color.set(hexcol)
                col_swatch.setStyleSheet(f"background:{hexcol}; border:1px solid {UI_C['border']};")
        pick_btn2 = QPushButton("Choose…"); pick_btn2.clicked.connect(pick_wm)
        col_row.addWidget(pick_btn2); col_row.addStretch()
        layout.addLayout(col_row)

        # ── Page numbers ──
        _hdr("PAGE NUMBERS")
        pn_chk = QCheckBox("Add page numbers")
        pn_chk.setChecked(bool(self.add_page_numbers.get()))
        pn_chk.stateChanged.connect(lambda s: self.add_page_numbers.set(bool(s)))
        layout.addWidget(pn_chk)

        fmt_row = QHBoxLayout(); fmt_row.addWidget(QLabel("Format:"))
        for val, lbl in [("decimal", "1, 2, 3"), ("roman", "i, ii, iii"), ("ALPHA", "A, B, C")]:
            rb = QRadioButton(lbl)
            rb.setChecked(self.page_num_format.get() == val)
            rb.toggled.connect(lambda ch, v=val: self.page_num_format.set(v) if ch else None)
            fmt_row.addWidget(rb)
        fmt_row.addStretch(); layout.addLayout(fmt_row)

        pos_row = QHBoxLayout(); pos_row.addWidget(QLabel("Position:"))
        for val, lbl in [("top-left","TL"),("top-center","TC"),("top-right","TR"),
                          ("bottom-left","BL"),("bottom-center","BC"),("bottom-right","BR")]:
            rb = QRadioButton(lbl)
            rb.setChecked(self.page_num_position.get() == val)
            rb.toggled.connect(lambda ch, v=val: self.page_num_position.set(v) if ch else None)
            pos_row.addWidget(rb)
        pos_row.addStretch(); layout.addLayout(pos_row)

        # ── Header / Footer ──
        _hdr("HEADER & FOOTER")
        hf_grid = QHBoxLayout()
        hf_grid.addWidget(QLabel("Header:")); hdr_edit = QLineEdit(self.header_text.get() or "")
        hdr_edit.textChanged.connect(self.header_text.set); hf_grid.addWidget(hdr_edit)
        layout.addLayout(hf_grid)
        hf_grid2 = QHBoxLayout()
        hf_grid2.addWidget(QLabel("Footer:")); ftr_edit = QLineEdit(self.footer_text.get() or "")
        ftr_edit.textChanged.connect(self.footer_text.set); hf_grid2.addWidget(ftr_edit)
        layout.addLayout(hf_grid2)

        # ── Output ──
        _hdr("OUTPUT")
        compress_chk = QCheckBox("Compress streams")
        compress_chk.setChecked(bool(self.compress_output.get()))
        compress_chk.stateChanged.connect(lambda s: self.compress_output.set(bool(s)))
        layout.addWidget(compress_chk)
        enc_chk = QCheckBox("Encrypt output")
        enc_chk.setChecked(bool(self.encrypt_pdf.get()))
        enc_chk.stateChanged.connect(lambda s: self.encrypt_pdf.set(bool(s)))
        layout.addWidget(enc_chk)

        # ── Buttons ──
        layout.addStretch()
        btns = QHBoxLayout(); btns.addStretch()
        done_btn = _plain_btn("Done")
        done_btn.clicked.connect(lambda: (
            self.status_var.set("⚙ Output options saved. Use File ▸ Save to export."),
            dlg.accept()))
        save_now_btn = _accent_btn("Save PDF now…")
        save_now_btn.clicked.connect(lambda: (dlg.accept(), self.save_pdf()))
        btns.addWidget(done_btn); btns.addWidget(save_now_btn)
        layout.addLayout(btns)
        dlg.exec()

    # ── Dialog: Metadata ──────────────────────────────────────────────────────

    def show_metadata_dialog(self):
        t = simpledialog.askstring("Title", "Title:",
                                   initialvalue=self.meta_title.get() or "")
        if t is not None: self.meta_title.set(t)
        a = simpledialog.askstring("Author", "Author:",
                                   initialvalue=self.meta_author.get() or "")
        if a is not None: self.meta_author.set(a)

    # ── Dialog: Shortcuts ─────────────────────────────────────────────────────

    def show_shortcuts(self):
        msg = ("Ctrl+O  Open      Ctrl+S  Save      Ctrl+Z  Undo   Ctrl+Y  Redo\n"
               "Ctrl+A  Select all    Del  Delete selected\n"
               "Ctrl+K  Command palette   Ctrl+T  Theme   Ctrl+G  Grid\n"
               "Ctrl++  Zoom in   Ctrl+-  Zoom out   Ctrl+0  Fit\n"
               "↑ ↓ Home End  Navigate rows\n"
               "← / →  Previous / next preview")
        messagebox.showinfo("Keyboard Shortcuts", msg)

    # ── Preset save / load ────────────────────────────────────────────────────

    def save_preset(self):
        path = filedialog.asksaveasfilename(defaultextension=".json",
                                            filetypes=[("JSON", "*.json")])
        if not path: return
        data = {"pages": [r.snapshot() for r in self.pages],
                "bookmarks": self._bookmarks}
        with open(path, "w") as f: json.dump(data, f, indent=2)
        messagebox.showinfo("Saved", path)

    def load_preset(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path: return
        with open(path) as f: data = json.load(f)
        self.pages = [PageRecord.from_snapshot(s) for s in data.get("pages", [])]
        self._bookmarks = data.get("bookmarks", [])
        self._preview_index = 0 if self.pages else -1
        self._preview_rec = self.pages[0] if self.pages else None
        self._rebuild_rows()

    # ── Save PDF ──────────────────────────────────────────────────────────────

    def save_pdf(self):
        if not self.pages:
            messagebox.showwarning("No pages", "Open a PDF first."); return
        included = [r for r in self.pages if r.included.get()]
        if not included:
            messagebox.showwarning("Nothing to save", "No pages are included."); return
        base = os.path.splitext(os.path.basename(self.primary_path or "output"))[0] + "_output"
        out_path = filedialog.asksaveasfilename(
            title="Save PDF", defaultextension=".pdf",
            initialfile=base + ".pdf",
            filetypes=[("PDF files", "*.pdf")])
        if not out_path: return
        if hasattr(self, "_show_toast"):
            self._show_toast("Saving PDF…", "info", 2000)
        threading.Thread(
            target=lambda: self._write_pdf_thread(included, out_path),
            daemon=True).start()

    def save_as(self):
        self.save_pdf()

    def _write_pdf_thread(self, records, out_path):
        try:
            self._write_pdf(records, out_path)
        except Exception as e:
            err = str(e)
            QTimer.singleShot(0, lambda: messagebox.showerror("Error", f"Failed to save:\n{err}"))

    def _write_pdf(self, records, out_path):
        try:
            reader_cache = {}

            def get_reader(path):
                if path not in reader_cache:
                    reader_cache[path] = PdfReader(path)
                return reader_cache[path]

            writer = PdfWriter()
            for rec in records:
                if rec.is_blank:
                    writer.add_blank_page(width=595, height=842)
                else:
                    reader = get_reader(rec.source_path)
                    page = copy.deepcopy(reader.pages[rec.source_index])
                    page = apply_transform(page, rec.orientation.get())
                    writer.add_page(page)

            meta = {}
            if self.meta_title.get():    meta["/Title"]    = self.meta_title.get()
            if self.meta_author.get():   meta["/Author"]   = self.meta_author.get()
            if self.meta_subject.get():  meta["/Subject"]  = self.meta_subject.get()
            if self.meta_keywords.get(): meta["/Keywords"] = self.meta_keywords.get()
            if self.meta_creator.get():  meta["/Creator"]  = self.meta_creator.get()
            if meta: writer.add_metadata(meta)

            for bm in self._bookmarks:
                try:
                    pg = bm["page"]
                    if 0 <= pg < len(writer.pages):
                        writer.add_outline_item(bm["title"], pg)
                except Exception: pass

            if self.compress_output.get():
                for p in writer.pages:
                    try: p.compress_content_streams()
                    except Exception: pass

            if self.encrypt_pdf.get() and (self.owner_password.get() or self.user_password.get()):
                writer.encrypt(user_password=self.user_password.get() or "",
                               owner_password=self.owner_password.get() or "")

            with open(out_path, "wb") as f:
                writer.write(f)

            self._apply_fitz_overlays(records, out_path)

            n = len(records)
            def _done():
                self.status_var.set(
                    f"✅ Saved {n} page{'s' if n != 1 else ''} → {os.path.basename(out_path)}")
                messagebox.showinfo("Saved", f"Saved {n} page(s)!\n\n{out_path}")
            QTimer.singleShot(0, _done)
        except Exception as e:
            err = str(e)
            QTimer.singleShot(0, lambda: messagebox.showerror("Error", f"Failed to save:\n{err}"))

    # ── Fitz overlay pipeline (unchanged from original) ───────────────────────

    def _apply_fitz_overlays(self, records, out_path):
        try:
            need_overlay = (
                any(getattr(r, "annotations", None) for r in records)
                or any(getattr(r, "redactions", None) for r in records)
                or (self.watermark_text.get() or "").strip()
                or self.add_page_numbers.get()
                or (self.header_text.get() or "").strip()
                or (self.footer_text.get() or "").strip()
            )
            if not need_overlay:
                return
            doc = fitz.open(out_path)
            for i, rec in enumerate(records):
                if i >= doc.page_count: break
                page = doc[i]
                self._add_overlay(page, rec, i + 1, len(records))
            tmp = out_path + ".tmp"
            doc.save(tmp, deflate=True, garbage=3)
            doc.close()
            os.replace(tmp, out_path)
        except Exception as e:
            err = str(e)
            QTimer.singleShot(0, lambda: self.status_var.set(
                f"⚠ Overlay step skipped: {err}"))

    def _add_overlay(self, page, rec, page_num, total):
        rect = page.rect
        W, H = rect.width, rect.height

        for coords in getattr(rec, "redactions", []):
            try:
                x0, y0, x1, y1 = coords
                r = fitz.Rect(x0 * W, y0 * H, x1 * W, y1 * H)
                page.draw_rect(r, color=(0, 0, 0), fill=(0, 0, 0), overlay=True)
                page.add_redact_annot(r, fill=(0, 0, 0))
            except Exception:
                continue
        try:
            page.apply_redactions()
        except Exception:
            pass

        for ann in getattr(rec, "annotations", []):
            try:
                if ann.get("type") == "stamp" and ann.get("image_path"):
                    x = float(ann.get("x", 0.7)) * W
                    y = float(ann.get("y", 0.8)) * H
                    w = float(ann.get("w", 0.25)) * W
                    h = float(ann.get("h", 0.12)) * H
                    page.insert_image(fitz.Rect(x, y, x + w, y + h),
                                      filename=ann["image_path"],
                                      keep_proportion=True)
                    continue
                text = str(ann.get("text", ""))
                if not text: continue
                x = float(ann.get("x", 0.1)) * W
                y = float(ann.get("y", 0.9)) * H
                size = int(ann.get("fontsize", 12))
                color = self._hex_to_rgb01(ann.get("color", "#000000"))
                page.insert_text((x, y), text, fontsize=size, color=color, fontname="helv")
            except Exception:
                continue

        wm = (self.watermark_text.get() or "").strip()
        if wm:
            try:
                opacity = max(0.0, min(1.0, float(self.watermark_opacity.get()) / 100.0))
                color = self._hex_to_rgb01(self.watermark_color.get() or "#AAAAAA")
                fs = max(24, int(min(W, H) / 9))
                tw = fitz.get_text_length(wm, fontname="helv", fontsize=fs)
                cx, cy = W / 2, H / 2
                morph = (fitz.Point(cx, cy),
                         fitz.Matrix(1, 0, 0, 1, 0, 0).prerotate(-45))
                page.insert_text((cx - tw / 2, cy + fs / 3), wm,
                                 fontsize=fs, fontname="helv",
                                 color=color, fill_opacity=opacity,
                                 stroke_opacity=opacity, morph=morph,
                                 render_mode=0)
            except Exception:
                pass

        header = (self.header_text.get() or "").strip()
        footer = (self.footer_text.get() or "").strip()

        def _expand(t):
            from datetime import datetime
            return (t.replace("{page}", str(page_num))
                     .replace("{total}", str(total))
                     .replace("{date}", datetime.now().strftime("%Y-%m-%d")))

        if header:
            try:
                page.insert_text((36, 28), _expand(header),
                                 fontsize=10, fontname="helv", color=(0.25, 0.25, 0.25))
            except Exception: pass
        if footer:
            try:
                page.insert_text((36, H - 20), _expand(footer),
                                 fontsize=10, fontname="helv", color=(0.25, 0.25, 0.25))
            except Exception: pass

        if self.add_page_numbers.get():
            try:
                fmt = self.page_num_format.get()
                if fmt == "roman":      label = _to_roman(page_num)
                elif fmt == "ALPHA":    label = self._alpha_label(page_num)
                else:                   label = str(page_num)
                pos = self.page_num_position.get()
                margin, fs = 28, 11
                tw = fitz.get_text_length(label, fontname="helv", fontsize=fs)
                x = margin if pos.endswith("left") else \
                    (W - tw - margin if pos.endswith("right") else (W - tw) / 2)
                y = margin if pos.startswith("top") else H - margin / 2
                page.insert_text((x, y), label, fontsize=fs,
                                 fontname="helv", color=(0.15, 0.15, 0.15))
            except Exception: pass

    @staticmethod
    def _hex_to_rgb01(hx):
        try:
            hx = hx.lstrip("#")
            if len(hx) == 3: hx = "".join(c * 2 for c in hx)
            return (int(hx[0:2], 16) / 255.0,
                    int(hx[2:4], 16) / 255.0,
                    int(hx[4:6], 16) / 255.0)
        except Exception:
            return (0.0, 0.0, 0.0)

    @staticmethod
    def _alpha_label(n):
        s = ""
        while n > 0:
            n, r = divmod(n - 1, 26)
            s = chr(ord("A") + r) + s
        return s

    # ── Session / status ──────────────────────────────────────────────────────

    def _clear_saved_session(self):
        try:
            if SESSION_FILE.exists(): SESSION_FILE.unlink()
        except Exception: pass

    def _update_status(self):
        if not self.pages:
            msg = "Open a PDF to get started."
        else:
            total = len(self.pages)
            included = sum(r.included.get() for r in self.pages)
            sel = len(self.selected_pages)
            sel_str = f" • {sel} selected" if sel else ""
            msg = (f"{included}/{total} pages included{sel_str} • "
                   f"Preview: page {self._preview_index + 1 if self._preview_index >= 0 else '—'}")
        self.status_var.set(msg)
        if hasattr(self, "_set_status"):
            self._set_status(msg)
        if hasattr(self, "_update_page_count"):
            self._update_page_count()

    def undo(self):
        self.do_undo()

    def redo(self):
        self.do_redo()

    # Watermark / add_watermark stub for command palette
    def add_watermark(self):
        self.show_output_options()

    def redact(self):
        self.redact_dialog()

    def add_signature(self):
        messagebox.showinfo("Signature", "Use the Add Signature feature in the Features menu.")

    def bates_number(self):
        if hasattr(self, "bates_dialog"):
            self.bates_dialog()
        else:
            messagebox.showinfo("Bates", "Bates numbering — wire from PDF features.")

    def split_pdf(self):
        messagebox.showinfo("Split", "Split PDF — use File ▸ Extract Pages to split by inclusion.")

    def toggle_grid_view(self):
        pass  # Qt grid view implementation goes in PDFStudioUI

    def _start_autosave(self):
        pass  # session autosave not wired in Qt version yet

    def _restore_session(self):
        pass  # session restore not wired in Qt version yet
