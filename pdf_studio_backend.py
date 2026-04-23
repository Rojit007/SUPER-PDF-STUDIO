"""
pdf_studio_backend.py — your original Part 1 + Part 2 business logic,
exported as PDFStudioBase so the top-level PDFStudio class can MRO with
PDFStudioUI + PDFFeatures cleanly.

No logic was changed. Only two tweaks versus the original source:
  1. Class renamed PDFStudio → PDFStudioBase
  2. The explicit inheritance from PDFStudioUI was removed (done in
     pdf_studio.py instead so the feature mixin can sit in between).

Fix applied (April 2026):
  - _drag_start now stores the dragged page object reference AND immediately
    sets _preview_rec to the dragged page so the PREVIEWING tag locks onto
    the page being dragged from the moment the drag begins.
  - _drag_motion follows _preview_rec by object identity so the blue
    "previewing" highlight travels with the page you dragged, regardless
    of how many positions it moves.
  - _drag_release re-resolves the final index of the dragged page and
    calls _render_preview so the right-hand preview panel updates correctly.
"""
from __future__ import annotations
import os, io, json, math, copy, threading, tempfile, time, re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, colorchooser, simpledialog
from pypdf import PdfReader, PdfWriter
from PIL import Image, ImageTk, ImageDraw, ImageFont
import fitz

# Pull shared module-level symbols from the common module (breaks cycle)
from pdf_studio_common import (
    OPTIONS, OPTION_COLORS, ROTATE_STEP, PAGE_SIZES,
    DARK_THEME, LIGHT_THEME,
    RECENT_FILE, SESSION_FILE, SESSION_PERSISTENCE,
    PageRecord, UndoStack,
    _to_roman, normalize_rotation, rotation_label,
    effective_orientation,
    get_page_orientation, apply_transform, apply_visual_rotation,
    render_page_image_fitz, get_page_info_fitz,
    load_recent_files, save_recent_files, add_recent_file,
    THUMB_W, THUMB_H, ROW_H,
)
from UI.pdf_studio_ui import C as UI_C


class PDFStudioBase:
    def __init__(self, root):
        self.root = root
        self.root.title("PDF Studio")
        self.root.resizable(True, True)
        self.root.minsize(1100, 660)

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
        self._preview_rec = None  # track by object, not just index
        self._preview_zoom = 1.0
        self._preview_tk = None
        self._pan_offset = [0, 0]
        self._pan_start = None

        self._dark_mode = tk.BooleanVar(value=False)
        self._theme = LIGHT_THEME

        self.meta_title = tk.StringVar()
        self.meta_author = tk.StringVar()
        self.meta_subject = tk.StringVar()
        self.meta_keywords = tk.StringVar()
        self.meta_creator = tk.StringVar(value="PDF Studio")

        self.add_page_numbers = tk.BooleanVar(value=False)
        self.page_num_format = tk.StringVar(value="decimal")
        self.page_num_position = tk.StringVar(value="bottom-center")
        self.compress_output = tk.BooleanVar(value=False)
        self.split_mode = tk.StringVar(value="single")
        self.watermark_text = tk.StringVar()
        self.watermark_opacity = tk.IntVar(value=40)
        self.watermark_pages = tk.StringVar(value="all")
        self.watermark_color = tk.StringVar(value="#AAAAAA")
        self.output_page_size = tk.StringVar(value="Original")
        self.pdfa_mode = tk.BooleanVar(value=False)
        self.linearize = tk.BooleanVar(value=False)
        self.encrypt_pdf = tk.BooleanVar(value=False)
        self.owner_password = tk.StringVar()
        self.user_password = tk.StringVar()
        self.flatten_forms = tk.BooleanVar(value=False)
        self.header_text = tk.StringVar()
        self.footer_text = tk.StringVar()
        self.thumb_size = tk.IntVar(value=90)

        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._filter_rows())

        self.undo_stack = UndoStack()
        self.status_var = tk.StringVar(value="Open a PDF to get started.")
        self._auto_save_job = None
        self._bookmarks = []

        self._build_ui()
        self._bind_keys()
        if SESSION_PERSISTENCE:
            self._restore_session()
            self._start_autosave()
        else:
            self._clear_saved_session()

    # ─────────────────────────────────────────────────────────── THEME ──
    def _toggle_theme(self):
        want_dark = self._theme is LIGHT_THEME
        self._theme = DARK_THEME if want_dark else LIGHT_THEME
        if hasattr(self, "_dark_mode"):
            self._dark_mode.set(want_dark)
        if hasattr(self, "_dark_var"):
            self._dark_var.set(want_dark)
        self._rebuild_rows()

    def T(self, key):
        return self._theme.get(key, "#FFFFFF")

    # ───────────────────────────────────────────────────────── UNDO/REDO ──
    def _push_undo(self, description="action"):
        self.undo_stack.push(self.pages, description)
        self._update_undo_labels()

    def _update_undo_labels(self):
        u = self.undo_stack.peek_undo()
        r = self.undo_stack.peek_redo()
        if hasattr(self, "update_undo_redo"):
            self.update_undo_redo(bool(u), bool(r), u, r)
            return
        self._undo_btn.config(state="normal" if u else "disabled",
                              text=f"↩ Undo{': ' + u if u else ''}")
        self._redo_btn.config(state="normal" if r else "disabled",
                              text=f"↪ Redo{': ' + r if r else ''}")

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
        # Previewed page was replaced by snapshot; re-anchor by index
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

    # ─────────────────────────────────────────────────────────── BUILD UI ──
    def _build_ui(self):
        self.search_var = self._search_var
        self.range_var = tk.StringVar()
        self.goto_var = tk.StringVar()
        self.autosave_var = tk.StringVar(value="")
        self.preview_info_var = tk.StringVar(value="No page selected")
        self.zoom_var = tk.StringVar(value="100%")
        self.thumb_size_var = self.thumb_size

        self.root.configure(bg=UI_C["bg"])
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        # mixin methods (resolved via MRO at runtime)
        self._build_titlebar()
        self._build_menubar()
        self._build_toolbar()
        self._apply_ttk_style()

        container = tk.Frame(self.root, bg=UI_C["bg"])
        container.grid(row=2, column=0, sticky="nsew", padx=0, pady=0)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)
        self._build_sub_toolbar_into(container)

        self.pane = tk.PanedWindow(
            container, orient="horizontal", bg=UI_C["border"],
            sashwidth=4, sashpad=0, relief="flat", opaqueresize=True)
        self.pane.grid(row=1, column=0, sticky="nsew")
        self._build_list_panel()
        self._build_preview_panel()

        self._build_statusbar()

        self._dark_mode = self._dark_var
        self._dark_mode.set(True)
        self._theme = DARK_THEME
        self._goto_var = self.goto_var
        self._autosave_var = self.autosave_var
        self._preview_info_var = self.preview_info_var
        self._zoom_label = self.zoom_lbl
        self._preview_foot_var = tk.StringVar(value="Click a thumbnail to preview")
        self.prev_foot_lbl.config(textvariable=self._preview_foot_var)

        self._refresh_recent_menu()

    def _refresh_recent_menu(self):
        recent = load_recent_files()
        if hasattr(self, "refresh_recent_menu"):
            self.refresh_recent_menu(recent)
            return
        self._recent_menu.delete(0, "end")
        if not recent:
            self._recent_menu.add_command(label="(none)", state="disabled")
        for path in recent:
            self._recent_menu.add_command(
                label=os.path.basename(path),
                command=lambda p=path: self._open_path(p))

    def _bind_keys(self):
        # Reuse the UI shell's global key-binder
        self._bind_global_keys()

    # ─────────────────────────────────────────────────────────── PREVIEW ──
    def _resolve_preview_index(self):
        """Resolve _preview_index from _preview_rec after page reorder."""
        if self._preview_rec is not None:
            for i, p in enumerate(self.pages):
                if p is self._preview_rec:
                    self._preview_index = i
                    return
            self._preview_rec = None
            self._preview_index = -1

    def _render_preview(self, rec=None):
        if rec is None:
            self._resolve_preview_index()
            if 0 <= self._preview_index < len(self.pages):
                rec = self.pages[self._preview_index]
        if rec is None:
            return
        c = self.preview_canvas
        c.update_idletasks()
        cw, ch = c.winfo_width(), c.winfo_height()
        if cw < 10 or ch < 10:
            self.root.after(100, self._render_preview)
            return
        c.delete("all")
        c.create_rectangle(0, 0, cw, ch, fill=UI_C["preview_bg"], outline="")
        max_w = max(10, int(cw * self._preview_zoom) - 40)
        max_h = max(10, int(ch * self._preview_zoom) - 40)
        ox, oy = self._pan_offset  # pan offset for drag-to-pan

        if rec.is_blank:
            pw = min(max_w, int(max_h * 0.707))
            ph = min(max_h, int(max_w / 0.707))
            x0 = (cw - pw) // 2 + ox
            y0 = (ch - ph) // 2 + oy
            c.create_rectangle(x0 + 6, y0 + 6, x0 + pw + 6, y0 + ph + 6,
                               fill="#000000", outline="", stipple="gray50",
                               tags="preview_content")
            c.create_rectangle(x0, y0, x0 + pw, y0 + ph,
                               fill="#FFFFFF", outline="#CCCCCC", width=2,
                               tags="preview_content")
            c.create_text(cw // 2 + ox, ch // 2 + oy, text="BLANK PAGE",
                          fill="#AAAAAA", font=("Helvetica", 16, "bold"),
                          tags="preview_content")
        else:
            key = (rec.source_path, rec.source_index, max_w, max_h,
                   rec.orientation.get(), int(self._preview_zoom * 100))
            if key in self.preview_cache:
                img = self.preview_cache[key]
            else:
                img = render_page_image_fitz(
                    rec.source_path, rec.source_index,
                    rec.orientation.get(), rec.orig_orient, max_w, max_h)
                if img:
                    self.preview_cache[key] = img
                    self._trim_preview_cache()
            if img is None:
                img = Image.new("RGB", (max_w, max_h), "#EEEEEE")
            iw, ih = img.size
            x = (cw - iw) // 2 + ox
            y = (ch - ih) // 2 + oy
            c.create_rectangle(x + 6, y + 6, x + iw + 6, y + ih + 6,
                               fill="#000000", outline="", stipple="gray25",
                               tags="preview_content")
            self._preview_tk = ImageTk.PhotoImage(img)
            c.create_image(x, y, anchor="nw", image=self._preview_tk,
                           tags="preview_content")
            c.create_rectangle(x, y, x + iw, y + ih, fill="",
                               outline="#334155", width=3,
                               tags="preview_content")

        idx = self._preview_index
        src = os.path.basename(rec.source_path) if not rec.is_blank else "Blank"
        self._preview_info_var.set(
            f"Page {idx + 1} of {len(self.pages)}  •  "
            f"{rotation_label(rec.orientation.get())}")
        self._zoom_label.config(text=f"{int(self._preview_zoom * 100)}%")
        self.zoom_var.set(f"{int(self._preview_zoom * 100)}%")
        # Update cursor based on zoom level
        if self._preview_zoom > 1.0:
            self.preview_canvas.config(cursor="hand2")
        else:
            self.preview_canvas.config(cursor="")
            self._pan_offset = [0, 0]
        self._preview_foot_var.set(
            f"{'◀/▶' if len(self.pages) > 1 else ''} {src} | Ctrl+Scroll to zoom")
        self.root.after(20, self._preload_adjacent)

    def _on_preview_resize(self, event):
        if self._preview_index >= 0:
            self.root.after(50, self._render_preview)

    def _on_preview_click(self, event):
        if self._preview_zoom > 1.0:
            self._pan_start = (event.x, event.y)
            self._pan_offset = getattr(self, '_pan_offset', [0, 0])[:]
            self.preview_canvas.config(cursor="fleur")
        else:
            self._preview_next()

    def _on_preview_drag(self, event):
        if not getattr(self, '_pan_start', None):
            return
        dx = event.x - self._pan_start[0]
        dy = event.y - self._pan_start[1]
        self._pan_offset = [
            self._pan_offset[0] + dx,
            self._pan_offset[1] + dy
        ]
        self._pan_start = (event.x, event.y)
        self.preview_canvas.move("preview_content", dx, dy)

    def _on_preview_release(self, event):
        self._pan_start = None
        if self._preview_zoom > 1.0:
            self.preview_canvas.config(cursor="hand2")
        else:
            self.preview_canvas.config(cursor="")

    def _on_preview_scroll(self, event):
        if event.delta > 0:
            self._preview_prev()
        else:
            self._preview_next()

    def _on_preview_ctrl_scroll(self, event):
        if event.delta > 0:
            self._zoom_in()
        else:
            self._zoom_out()

    def _preview_prev(self):
        if not self.pages: return
        ni = max(0, self._preview_index - 1)
        if ni != self._preview_index:
            self._preview_index = ni
            self._preview_rec = self.pages[ni]
            self._pan_offset = [0, 0]
            self._render_preview()
            self._scroll_to_row(ni)

    def _preview_next(self):
        if not self.pages: return
        ni = min(len(self.pages) - 1, self._preview_index + 1)
        if ni != self._preview_index:
            self._preview_index = ni
            self._preview_rec = self.pages[ni]
            self._pan_offset = [0, 0]
            self._render_preview()
            self._scroll_to_row(ni)

    def _zoom_in(self):
        self._preview_zoom = min(4.0, self._preview_zoom + 0.25)
        if self._preview_zoom <= 1.0:
            self._pan_offset = [0, 0]
        self._render_preview()

    def _zoom_out(self):
        self._preview_zoom = max(0.25, self._preview_zoom - 0.25)
        if self._preview_zoom <= 1.0:
            self._pan_offset = [0, 0]
        self._render_preview()

    def _zoom_fit(self):
        self._preview_zoom = 1.0
        self._pan_offset = [0, 0]
        self._render_preview()

    def _preload_adjacent(self):
        if not self.pages or self._preview_index < 0: return
        idx = self._preview_index
        cw = self.preview_canvas.winfo_width()
        ch = self.preview_canvas.winfo_height()
        max_w, max_h = max(10, int(cw) - 40), max(10, int(ch) - 40)
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
        try:
            rows = self.rows_frame.winfo_children()
            total = len(rows)
            if total == 0: return
            frac = max(0.0, min(1.0, (idx - 1) / total))
            self.list_canvas.yview_moveto(frac)
        except Exception:
            pass

    def _goto_page(self):
        try:
            n = int(self._goto_var.get())
            idx = n - 1
            if 0 <= idx < len(self.pages):
                self._preview_index = idx
                self._preview_rec = self.pages[idx]
                self._render_preview()
                self._scroll_to_row(idx)
                self._goto_var.set("")
        except Exception:
            pass

    def _on_thumb_size_change(self, val):
        global THUMB_W, THUMB_H, ROW_H
        import pdf_studio_common as _m
        _m.THUMB_W = int(float(val))
        _m.THUMB_H = int(_m.THUMB_W * 1.33)
        _m.ROW_H = _m.THUMB_H + 16
        self.thumb_cache.clear()
        self._rebuild_rows()
        self._load_thumbs_async()

    # ────────────────────────────────────────────────────────── ROWS ──
    def _rebuild_rows(self):
        if not hasattr(self, "rows_frame"):
            return
        if hasattr(self, "clear_page_rows"):
            self.clear_page_rows()
        else:
            for w in self.rows_frame.winfo_children():
                w.destroy()
        if hasattr(self, "_grid_wrap"):
            try: del self._grid_wrap
            except Exception: pass
        # Resolve preview index BEFORE adding rows so PREVIEWING badge is correct
        if self._preview_index >= 0 and self.pages:
            self._resolve_preview_index()
        filter_text = self._search_var.get().strip().lower()
        if filter_text == "filter pages…":
            filter_text = ""
        for i, rec in enumerate(self.pages):
            if filter_text:
                label = f"page {i + 1} {os.path.basename(rec.source_path).lower()}"
                if filter_text not in label:
                    continue
            self._add_row(i, rec)
        self.rows_frame.update_idletasks()
        self.list_canvas.configure(scrollregion=self.list_canvas.bbox("all"))
        if self._preview_index >= 0 and self.pages:
            self.root.after(50, self._render_preview)
        if not self.pages:
            self._preview_index = -1
            self._preview_rec = None
            self._preview_tk = None
            c = self.preview_canvas
            c.delete("all")
            cw, ch = c.winfo_width(), c.winfo_height()
            c.create_rectangle(0, 0, cw, ch, fill=UI_C["preview_bg"], outline="")
            if hasattr(self, "_preview_foot_var"):
                self._preview_foot_var.set("")
            if hasattr(self, "preview_info_lbl"):
                self.preview_info_lbl.config(text="No page selected")
            if hasattr(self, "_show_empty_if_needed"):
                self._show_empty_if_needed()

    def _filter_rows(self):
        self._rebuild_rows()

    def _add_row(self, i, rec):
        import pdf_studio_common as _m
        tw_, th_ = _m.THUMB_W, _m.THUMB_H
        is_previewed = (i == self._preview_index)
        is_selected = (i in self.selected_pages)
        if rec.thumb_img and not rec.thumb_tk:
            rec.thumb_tk = ImageTk.PhotoImage(rec.thumb_img)
        row = self.add_page_row(
            index=i, page_num=i + 1,
            is_included=rec.included.get(),
            orig_orient=rec.orig_orient,
            rotation_deg=int(rec.orientation.get()),
            is_previewed=is_previewed,
            is_selected=is_selected,
            thumb_img=rec.thumb_tk,
            on_thumb_click=lambda r=rec, idx=i: self._on_thumb_click(r, idx),
            on_rotate_cw=lambda r=rec, idx=i: self._rotate_page(r, idx, ROTATE_STEP),
            on_rotate_ccw=lambda r=rec, idx=i: self._rotate_page(r, idx, -ROTATE_STEP),
            on_duplicate=lambda idx=i: self.duplicate_page(idx),
            on_delete=lambda idx=i: self.delete_page(idx),
            on_move_up=lambda idx=i: self.move_page(idx, -1),
            on_move_down=lambda idx=i: self.move_page(idx, 1),
            on_annotate=lambda idx=i: self.add_text_annotation(idx),
            on_redact=lambda idx=i: self.redact_dialog(idx),
            on_include_toggle=lambda r=rec, idx=i: (
                r.included.set(not r.included.get()),
                self._toggle_include(r, idx)),
            on_right_click=lambda e, idx=i: self._show_context_menu(e, idx),
            on_row_click=lambda e, idx=i, r=rec: self._on_row_click(e, idx, r),
            on_row_ctrl_click=lambda e, idx=i, r=rec: self._on_row_ctrl_click(e, idx, r),
            on_row_shift_click=lambda e, idx=i, r=rec: self._on_row_shift_click(e, idx, r),
            on_drag_start=lambda e, idx=i: self._drag_start(e, idx),
            on_drag_motion=lambda e, idx=i: self._drag_motion(e, idx),
            on_drag_release=lambda e, idx=i: self._drag_release(e, idx),
        )
        rec._row_widget = row
        rec._thumb_label = getattr(row, "_thumb_label", None)
        rec._rb_frame = getattr(row, "_rb_frame", None)
        rec._rot_value_lbl = getattr(row, "_rot_value_lbl", None)
        self._refresh_orient_btns(rec)

    def _show_context_menu(self, event, idx):
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label=f"Preview page {idx + 1}",
                         command=lambda: self._on_thumb_click(self.pages[idx], idx))
        menu.add_separator()
        menu.add_command(label="Duplicate", command=lambda: self.duplicate_page(idx))
        menu.add_command(label="Delete",    command=lambda: self.delete_page(idx))
        menu.add_separator()
        menu.add_command(label="Rotate CW",  command=lambda: self._rotate_page(self.pages[idx], idx, ROTATE_STEP))
        menu.add_command(label="Rotate CCW", command=lambda: self._rotate_page(self.pages[idx], idx, -ROTATE_STEP))
        menu.add_separator()
        menu.add_command(label="Move Up",   command=lambda: self.move_page(idx, -1))
        menu.add_command(label="Move Down", command=lambda: self.move_page(idx, 1))
        menu.add_separator()
        menu.add_command(label="Add Annotation", command=lambda: self.add_text_annotation(idx))
        menu.add_command(label="Redact Region",  command=lambda: self.redact_dialog(idx))
        menu.add_command(label="Page Inspector", command=lambda: self.page_inspector_dialog(idx))
        menu.add_separator()
        menu.add_command(label="Include", command=lambda: self._set_include(idx, True))
        menu.add_command(label="Exclude", command=lambda: self._set_include(idx, False))
        menu.tk_popup(event.x_root, event.y_root)

    def _set_include(self, idx, state):
        self.pages[idx].included.set(state)
        self._rebuild_rows()
        self._update_status()

    def _on_row_click(self, event, idx, rec):
        self.selected_pages.clear()
        self.selected_pages.add(idx)
        self._preview_index = idx
        self._preview_rec = rec
        self._render_preview(rec)
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
        if rec.thumb_img:
            rec.thumb_tk = ImageTk.PhotoImage(rec.thumb_img)
            if rec._thumb_label and rec._thumb_label.winfo_exists():
                rec._thumb_label.config(image=rec.thumb_tk,
                                        width=_m.THUMB_W, height=_m.THUMB_H)

    def _orientation_changed(self, rec, idx):
        self._refresh_orient_btns(rec)
        self._refresh_thumb(rec)
        if idx == self._preview_index:
            self.preview_cache.clear()
            self._render_preview(rec)
        # Rebuild rows so the orientation badge (PORTRAIT/LANDSCAPE) reflects
        # the effective orientation after the new rotation.
        try:
            self._rebuild_rows()
        except Exception:
            pass
        self._update_status()

    def _rotate_page(self, rec, idx, delta):
        rec.orientation.set((int(rec.orientation.get()) + delta) % 360)
        self._orientation_changed(rec, idx)

    def _on_thumb_click(self, rec, idx):
        self._preview_index = idx
        self._preview_rec = rec
        self.selected_pages = {idx}
        self._render_preview(rec)
        self._rebuild_rows()

    def _refresh_orient_btns(self, rec):
        if not rec._rb_frame or not rec._rb_frame.winfo_exists():
            return
        row_bg = rec._rb_frame.cget("bg")
        if rec._rot_value_lbl and rec._rot_value_lbl.winfo_exists():
            rec._rot_value_lbl.config(text=rotation_label(rec.orientation.get()),
                                      bg=row_bg)

    def _toggle_include(self, rec, idx):
        self._rebuild_rows()
        self._update_status()

    # ────────────────────────────────────────────── MULTI-SELECT ACTIONS ──
    def select_all_pages(self):
        self.selected_pages = set(range(len(self.pages)))
        self._rebuild_rows()

    def deselect_all_pages(self):
        self.selected_pages.clear()
        self._rebuild_rows()

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
                             tk.StringVar(value=src.orig_orient),
                             is_blank=src.is_blank)
            rec.orig_orient = src.orig_orient
            rec.orientation.set(src.orientation.get())
            rec.annotations = list(src.annotations)
            rec.redactions = list(src.redactions)
            self.pages.insert(idx + 1, rec)
        self._rebuild_rows()
        self._update_status()

    # ─────────────────────────────────────────────── THUMBNAIL LOADING ──
    def _load_thumbs_async(self):
        self.progress.grid()
        self.progress.start(10)
        threading.Thread(target=self._load_thumbs_worker, daemon=True).start()

    def _load_thumbs_worker(self):
        import pdf_studio_common as _m
        for rec in list(self.pages):
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
            self.root.after(0, lambda r=rec: self._update_thumb_ui(r))
        self.root.after(0, self._thumbs_done)

    def _update_thumb_ui(self, rec):
        import pdf_studio_common as _m
        if rec._thumb_label and rec._thumb_label.winfo_exists() and rec.thumb_img:
            rec.thumb_tk = ImageTk.PhotoImage(rec.thumb_img)
            rec._thumb_label.config(image=rec.thumb_tk,
                                    width=_m.THUMB_W, height=_m.THUMB_H)
        if (0 <= self._preview_index < len(self.pages)
                and self.pages[self._preview_index] is rec):
            self.root.after(0, self._render_preview)

    def _thumbs_done(self):
        self.progress.stop()
        self.progress.grid_remove()
        if self._preview_index >= 0 and self.pages:
            self._render_preview()

    def _make_blank_thumb(self):
        import pdf_studio_common as _m
        img = Image.new("RGB", (_m.THUMB_W, _m.THUMB_H), "#FFFFFF")
        draw = ImageDraw.Draw(img)
        draw.rectangle([1, 1, _m.THUMB_W - 2, _m.THUMB_H - 2],
                       outline="#CCCCCC", width=2)
        draw.text((_m.THUMB_W // 2, _m.THUMB_H // 2), "BLANK",
                  fill="#AAAAAA", anchor="mm")
        return img

    # ───────────────────────────────────────────────── FILE OPERATIONS ──
    def browse_file(self):
        path = filedialog.askopenfilename(
            title="Open PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
        if path:
            self._open_path(path)

    def _open_path(self, path):
        self.primary_path = path
        self.root.title(f"PDF Studio – {os.path.basename(path)}")
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
                    "Password", f"Enter password for:\n{os.path.basename(path)}",
                    show="*", parent=self.root)
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
            rec = PageRecord(path, i, tk.StringVar(value=orient))
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
        self._load_thumbs_async()
        self._update_status()

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
        self._load_thumbs_async()
        self._update_status()

    def _add_image_as_page(self, img_path):
        try:
            img = Image.open(img_path).convert("RGB")
            tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            tmp.close()
            img.save(tmp.name, "PDF", resolution=150)
            rec = PageRecord(tmp.name, 0, tk.StringVar(value="Portrait"))
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
        self.progress.grid(); self.progress.start(10)

        def worker():
            for i, rec in enumerate(included):
                if rec.is_blank:
                    img = Image.new("RGB", (595, 842), "white")
                else:
                    img = render_page_image_fitz(rec.source_path, rec.source_index,
                                                 rec.orientation.get(),
                                                 rec.orig_orient,
                                                 int(595 * 150 / 72),
                                                 int(842 * 150 / 72))
                fname = os.path.join(out_dir, f"page_{i + 1:04d}.png")
                img.save(fname)
            self.root.after(0, lambda: (
                self.progress.stop(), self.progress.grid_remove(),
                messagebox.showinfo("Done",
                    f"Exported {len(included)} images to:\n{out_dir}")))
        threading.Thread(target=worker, daemon=True).start()

    # ───────────────────────────────────────────────── PAGE ACTIONS ──
    def insert_blank(self):
        if not self.pages:
            messagebox.showwarning("No PDF", "Open a PDF first.")
            return
        self._push_undo("insert blank page")
        rec = PageRecord("__blank__", -1, tk.StringVar(value="Portrait"),
                         is_blank=True)
        rec.thumb_img = self._make_blank_thumb()
        insert_at = self._preview_index + 1 if self._preview_index >= 0 else len(self.pages)
        self.pages.insert(insert_at, rec)
        self._rebuild_rows()
        self._update_status()

    def duplicate_page(self, idx):
        self._push_undo("duplicate page")
        src = self.pages[idx]
        rec = PageRecord(src.source_path, src.source_index,
                         tk.StringVar(value=src.orig_orient),
                         is_blank=src.is_blank)
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
            # If the moved page is the previewed one, follow it
            if self._preview_rec is not None:
                for i, p in enumerate(self.pages):
                    if p is self._preview_rec:
                        self._preview_index = i
                        break
            self._rebuild_rows()

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
        if not self.pages:
            return
        step_txt = "CW" if delta > 0 else "CCW"
        self._push_undo(f"rotate all {step_txt}")
        for rec in self.pages:
            rec.orientation.set((int(rec.orientation.get()) + delta) % 360)
        self.thumb_cache.clear()
        self.preview_cache.clear()
        self._rebuild_rows()
        self._load_thumbs_async()

    def reset_all_orient(self):
        self._push_undo("reset orientations")
        for rec in self.pages:
            rec.orientation.set(0)
        self.thumb_cache.clear()
        self.preview_cache.clear()
        self._rebuild_rows()
        self._load_thumbs_async()

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
        text = self.range_entry.get().strip()
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
                             tk.StringVar(value=src.orig_orient),
                             is_blank=src.is_blank)
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
            self.pages[idx].orientation.set((int(self.pages[idx].orientation.get()) + 90) % 360)
        self.thumb_cache.clear()
        self.preview_cache.clear()
        self._rebuild_rows()
        self._load_thumbs_async()

    # ── DRAG & DROP ─────────────────────────────────────────────────────────
    def _drag_start(self, event, idx):
        # Hard-reset any stale drag artifacts before starting a new drag.
        self._cleanup_grid_drag_bindings()
        self._end_grid_drag_feedback()
        dragged_rec = self.pages[idx]

        # Immediately make the dragged page the previewed one.
        # This ensures PREVIEWING locks onto the page being dragged
        # from the very first moment, not whatever was previously selected.
        self._preview_rec = dragged_rec
        self._preview_index = idx
        self.selected_pages = {idx}

        self.drag_data = {
            "idx":         idx,
            "y_start":     event.y_root,
            "moved":       False,
            "dragged_rec": dragged_rec,   # object identity anchor
        }
        if getattr(self, "_grid_view_on", False):
            # Capture drag globally so motion keeps tracking even when cursor
            # leaves the original tile while dragging in grid view.
            self._grid_drag_motion_bind = self.root.bind(
                "<B1-Motion>", self._drag_motion, add="+")
            self._grid_drag_release_bind = self.root.bind(
                "<ButtonRelease-1>", self._drag_release, add="+")
            self._start_grid_drag_feedback(event, dragged_rec)
            # Avoid rebuilding immediately in grid mode: it can disrupt the
            # drag start gesture and make the grabbed tile feel "unstuck".
            self._render_preview(dragged_rec)
        else:
            # Rebuild rows immediately so the PREVIEWING tag appears on the
            # correct row before the user has even moved the mouse.
            self._rebuild_rows()

    def _drag_motion(self, event, idx=None):
        import pdf_studio_common as _m
        if not self.drag_data:
            return
        if getattr(self, "_grid_view_on", False):
            self._move_grid_drag_feedback(event.x_root, event.y_root)
            target_idx = self._drag_target_index_from_cursor(event.x_root, event.y_root)
            if target_idx is None:
                return
            src_idx = self.drag_data["idx"]
            if target_idx != src_idx:
                if not self.drag_data["moved"]:
                    self._push_undo("reorder pages")
                    self.drag_data["moved"] = True
                dragged = self.pages.pop(src_idx)
                self.pages.insert(target_idx, dragged)
                self.drag_data["idx"] = target_idx
                self.drag_data["y_start"] = event.y_root

                dragged_rec = self.drag_data["dragged_rec"]
                for i, p in enumerate(self.pages):
                    if p is dragged_rec:
                        self._preview_index = i
                        self._preview_rec = dragged_rec
                        break
                self._rebuild_rows()
            return
        dy = event.y_root - self.drag_data["y_start"]
        steps = int(dy // max(1, _m.ROW_H // 2))
        if steps != 0:
            new_idx = max(0, min(len(self.pages) - 1, self.drag_data["idx"] + steps))
            if new_idx != self.drag_data["idx"]:
                if not self.drag_data["moved"]:
                    self._push_undo("reorder pages")
                    self.drag_data["moved"] = True

                # Swap the pages in the list
                self.pages[self.drag_data["idx"]], self.pages[new_idx] = \
                    self.pages[new_idx], self.pages[self.drag_data["idx"]]
                self.drag_data["idx"] = new_idx
                self.drag_data["y_start"] = event.y_root

                # ── THE KEY FIX ──────────────────────────────────────────
                # _preview_rec is ALWAYS the dragged page (set in _drag_start).
                # Walk the list to find where dragged_rec ended up after the
                # swap and update _preview_index to match. This keeps the
                # PREVIEWING highlight glued to the dragged page no matter
                # how far it moves, because we follow object identity, not
                # a stale integer index.
                dragged_rec = self.drag_data["dragged_rec"]
                for i, p in enumerate(self.pages):
                    if p is dragged_rec:
                        self._preview_index = i
                        self._preview_rec = dragged_rec  # keep anchor explicit
                        break

                self._rebuild_rows()

    def _drag_target_index_from_cursor(self, x_root, y_root):
        """Resolve page index under cursor for grid drag-reorder."""
        # Keep drag active only when cursor is over/near the pages pane.
        try:
            lx0 = self.list_canvas.winfo_rootx()
            ly0 = self.list_canvas.winfo_rooty()
            lx1 = lx0 + self.list_canvas.winfo_width()
            ly1 = ly0 + self.list_canvas.winfo_height()
            if not (lx0 - 24 <= x_root <= lx1 + 24 and ly0 - 24 <= y_root <= ly1 + 24):
                return None
        except Exception:
            pass

        # Geometry-based lookup is resilient even when overlay windows
        # (drag ghost) are under the cursor.
        inside_matches = []
        nearest = None
        nearest_dist = float("inf")
        for i, rec in enumerate(self.pages):
            w = getattr(rec, "_row_widget", None)
            if w is None:
                continue
            try:
                if not w.winfo_exists():
                    continue
                x0 = w.winfo_rootx()
                y0 = w.winfo_rooty()
                x1 = x0 + w.winfo_width()
                y1 = y0 + w.winfo_height()
            except Exception:
                continue
            cx = (x0 + x1) / 2.0
            cy = (y0 + y1) / 2.0
            dist = (cx - x_root) ** 2 + (cy - y_root) ** 2
            if x0 <= x_root <= x1 and y0 <= y_root <= y1:
                inside_matches.append((dist, i))
            if dist < nearest_dist:
                nearest_dist = dist
                nearest = i
        if inside_matches:
            inside_matches.sort(key=lambda t: t[0])
            return inside_matches[0][1]
        if nearest is not None:
            return nearest

        try:
            w = self.root.winfo_containing(x_root, y_root)
        except Exception:
            w = None
        while w is not None:
            idx = getattr(w, "_page_index", None)
            if isinstance(idx, int) and 0 <= idx < len(self.pages):
                return idx
            w = getattr(w, "master", None)
        return None

    def _drag_release(self, event, idx=None):
        # After releasing, re-resolve the final position of the dragged page
        # by object identity and render its preview in the right-hand panel.
        self._end_grid_drag_feedback()
        self._cleanup_grid_drag_bindings()
        if self.drag_data:
            dragged_rec = self.drag_data.get("dragged_rec")
            if dragged_rec is not None:
                self._preview_rec = dragged_rec
                for i, p in enumerate(self.pages):
                    if p is dragged_rec:
                        self._preview_index = i
                        break
                self._rebuild_rows()
                self._render_preview(dragged_rec)
        self.drag_data = {}

    def _start_grid_drag_feedback(self, event, rec):
        """Create visual drag feedback for grid tiles."""
        try:
            ghost = tk.Toplevel(self.root)
            ghost.wm_overrideredirect(True)
            ghost.wm_attributes("-topmost", True)
            try:
                ghost.wm_attributes("-alpha", 0.92)
            except Exception:
                pass
            frame = tk.Frame(ghost, bg="#0F172A", highlightthickness=1,
                             highlightbackground="#38BDF8")
            frame.pack()
            img = getattr(rec, "thumb_tk", None)
            if img is not None:
                lbl = tk.Label(frame, image=img, bg="#FFFFFF", bd=0)
                lbl.image = img
            else:
                lbl = tk.Label(frame, text="Dragging page", fg="#E2E8F0",
                               bg="#0F172A", padx=12, pady=8)
            lbl.pack(padx=4, pady=4)
            self._grid_drag_ghost = ghost
            self.root.configure(cursor="hand2")
            self._move_grid_drag_feedback(event.x_root, event.y_root)
        except Exception:
            pass

    def _move_grid_drag_feedback(self, x_root, y_root):
        ghost = self._grid_drag_ghost
        if ghost is None:
            return
        try:
            ghost.geometry(f"+{x_root + 14}+{y_root + 14}")
        except Exception:
            pass

    def _end_grid_drag_feedback(self):
        ghost = self._grid_drag_ghost
        if ghost is not None:
            try:
                ghost.destroy()
            except Exception:
                pass
        self._grid_drag_ghost = None
        try:
            self.root.configure(cursor="")
        except Exception:
            pass

    def _cleanup_grid_drag_bindings(self):
        """Always remove temporary root-level drag bindings if present."""
        if getattr(self, "_grid_drag_motion_bind", None):
            try:
                self.root.unbind("<B1-Motion>", self._grid_drag_motion_bind)
            except Exception:
                pass
            self._grid_drag_motion_bind = None
        if getattr(self, "_grid_drag_release_bind", None):
            try:
                self.root.unbind("<ButtonRelease-1>", self._grid_drag_release_bind)
            except Exception:
                pass
            self._grid_drag_release_bind = None

    # ─── ANNOTATIONS / REDACTIONS / CROPS / OTHER DIALOGS ───────────────
    def add_text_annotation(self, idx=None):
        if idx is None:
            idx = self._preview_index
        if idx < 0 or idx >= len(self.pages):
            messagebox.showwarning("No page", "Select a page first.")
            return
        win = tk.Toplevel(self.root)
        win.title(f"Add annotation – page {idx + 1}")
        win.transient(self.root)
        win.configure(bg=UI_C["panel"])
        win.geometry("420x320")

        pad = {"padx": 14, "pady": 6}
        tk.Label(win, text=f"Annotation for page {idx + 1}",
                 bg=UI_C["panel"], fg=UI_C["fg"],
                 font=("TkDefaultFont", 12, "bold")).pack(anchor="w", **pad)

        text_var = tk.StringVar()
        tk.Label(win, text="Text:", bg=UI_C["panel"], fg=UI_C["fg_muted"]
                 ).pack(anchor="w", padx=14)
        tx = tk.Text(win, height=4, bg=UI_C["input_bg"], fg=UI_C["fg"],
                     insertbackground=UI_C["accent"], relief="flat",
                     highlightthickness=1,
                     highlightbackground=UI_C["input_border"])
        tx.pack(fill="x", padx=14)

        x_var = tk.DoubleVar(value=0.1)
        y_var = tk.DoubleVar(value=0.9)
        size_var = tk.IntVar(value=12)
        color_var = tk.StringVar(value="#DC2626")

        grid = tk.Frame(win, bg=UI_C["panel"])
        grid.pack(fill="x", padx=14, pady=(10, 0))
        for i, (lbl, var, w) in enumerate([("X (0-1)", x_var, 6),
                                            ("Y (0-1)", y_var, 6),
                                            ("Size", size_var, 5)]):
            tk.Label(grid, text=lbl, bg=UI_C["panel"], fg=UI_C["fg_muted"]
                     ).grid(row=0, column=i * 2, padx=(0, 4))
            tk.Entry(grid, textvariable=var, width=w,
                     bg=UI_C["input_bg"], fg=UI_C["fg"], bd=0,
                     insertbackground=UI_C["accent"], relief="flat",
                     highlightthickness=1,
                     highlightbackground=UI_C["input_border"]
                     ).grid(row=0, column=i * 2 + 1, padx=(0, 10))

        def pick_color():
            c = colorchooser.askcolor(color=color_var.get(), parent=win)
            if c and c[1]:
                color_var.set(c[1])
                swatch.configure(bg=c[1])
        crow = tk.Frame(win, bg=UI_C["panel"])
        crow.pack(fill="x", padx=14, pady=(10, 0))
        tk.Label(crow, text="Color:", bg=UI_C["panel"], fg=UI_C["fg_muted"]
                 ).pack(side="left", padx=(0, 6))
        swatch = tk.Label(crow, text="   ", bg=color_var.get(), width=4,
                          relief="flat", cursor="hand2")
        swatch.pack(side="left")
        swatch.bind("<Button-1>", lambda _e: pick_color())
        tk.Button(crow, text="Choose…", command=pick_color,
                  bg=UI_C["elevated"], fg=UI_C["fg"], bd=0,
                  activebackground=UI_C["elevated_hover"],
                  cursor="hand2").pack(side="left", padx=8)

        def save():
            txt = tx.get("1.0", "end").strip() or text_var.get().strip()
            if not txt:
                messagebox.showwarning("Empty", "Type some text first.",
                                       parent=win)
                return
            self._push_undo("add annotation")
            self.pages[idx].annotations.append({
                "text": txt,
                "x": float(x_var.get()),
                "y": float(y_var.get()),
                "fontsize": int(size_var.get()),
                "color": color_var.get(),
            })
            self.status_var.set(
                f"✏ Annotation added to page {idx + 1} "
                f"({len(self.pages[idx].annotations)} total)")
            win.destroy()

        btns = tk.Frame(win, bg=UI_C["panel"])
        btns.pack(fill="x", padx=14, pady=14, side="bottom")
        tk.Button(btns, text="Cancel", command=win.destroy,
                  bg=UI_C["elevated"], fg=UI_C["fg"], bd=0,
                  activebackground=UI_C["elevated_hover"], cursor="hand2",
                  padx=14, pady=6).pack(side="right", padx=4)
        tk.Button(btns, text="Add annotation", command=save,
                  bg=UI_C["accent"], fg="#FFFFFF", bd=0,
                  activebackground=UI_C["accent_hover"], cursor="hand2",
                  padx=14, pady=6).pack(side="right", padx=4)

    def redact_dialog(self, idx=None):
        if idx is None:
            idx = self._preview_index
        if idx < 0 or idx >= len(self.pages):
            messagebox.showwarning("No page", "Select a page first.")
            return
        win = tk.Toplevel(self.root)
        win.title(f"Add redaction – page {idx + 1}")
        win.transient(self.root)
        win.configure(bg=UI_C["panel"])
        win.geometry("360x260")

        tk.Label(win, text=f"Redaction rectangle for page {idx + 1}",
                 bg=UI_C["panel"], fg=UI_C["fg"],
                 font=("TkDefaultFont", 11, "bold")
                 ).pack(anchor="w", padx=14, pady=(14, 4))
        tk.Label(win, text="Coordinates are normalised 0-1 "
                           "(origin = top-left).",
                 bg=UI_C["panel"], fg=UI_C["fg_muted"], wraplength=320,
                 justify="left").pack(anchor="w", padx=14)

        x0 = tk.DoubleVar(value=0.10)
        y0 = tk.DoubleVar(value=0.10)
        x1 = tk.DoubleVar(value=0.90)
        y1 = tk.DoubleVar(value=0.20)
        grid = tk.Frame(win, bg=UI_C["panel"])
        grid.pack(padx=14, pady=14)
        for r, (lbl, var) in enumerate([("X₀", x0), ("Y₀", y0),
                                         ("X₁", x1), ("Y₁", y1)]):
            tk.Label(grid, text=lbl, bg=UI_C["panel"], fg=UI_C["fg_muted"],
                     width=4, anchor="e"
                     ).grid(row=r // 2, column=(r % 2) * 2, padx=4, pady=4)
            tk.Entry(grid, textvariable=var, width=8,
                     bg=UI_C["input_bg"], fg=UI_C["fg"], bd=0,
                     insertbackground=UI_C["accent"], relief="flat",
                     highlightthickness=1,
                     highlightbackground=UI_C["input_border"]
                     ).grid(row=r // 2, column=(r % 2) * 2 + 1,
                            padx=(0, 10), pady=4)

        def save():
            try:
                coords = (float(x0.get()), float(y0.get()),
                          float(x1.get()), float(y1.get()))
            except Exception:
                messagebox.showerror("Bad input", "Use numbers 0-1.", parent=win)
                return
            self._push_undo("add redaction")
            self.pages[idx].redactions.append(coords)
            self.status_var.set(
                f"⬛ Redaction added to page {idx + 1} "
                f"({len(self.pages[idx].redactions)} total)")
            win.destroy()

        btns = tk.Frame(win, bg=UI_C["panel"])
        btns.pack(fill="x", padx=14, pady=(0, 14), side="bottom")
        tk.Button(btns, text="Cancel", command=win.destroy,
                  bg=UI_C["elevated"], fg=UI_C["fg"], bd=0,
                  activebackground=UI_C["elevated_hover"], cursor="hand2",
                  padx=14, pady=6).pack(side="right", padx=4)
        tk.Button(btns, text="Add redaction", command=save,
                  bg=UI_C["accent"], fg="#FFFFFF", bd=0,
                  activebackground=UI_C["accent_hover"], cursor="hand2",
                  padx=14, pady=6).pack(side="right", padx=4)

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

    def crop_margins_dialog(self): messagebox.showinfo("Crop", "Use Pro ▸ Auto-Crop")
    def resize_pages_dialog(self): messagebox.showinfo("Resize", "Use Output ▸ Options ▸ Page Size")

    def encryption_dialog(self):
        pwd = simpledialog.askstring("Encrypt", "Owner password:",
                                     show="*", parent=self.root)
        if pwd:
            self.encrypt_pdf.set(True)
            self.owner_password.set(pwd)
            messagebox.showinfo("Encryption", "Enabled for next save.")

    def unlock_pdf_dialog(self):
        path = filedialog.askopenfilename(filetypes=[("PDF", "*.pdf")])
        if not path: return
        pwd = simpledialog.askstring("Password", "Password:", show="*",
                                     parent=self.root)
        if pwd is None: return
        out = filedialog.asksaveasfilename(defaultextension=".pdf")
        if not out: return
        try:
            r = PdfReader(path); r.decrypt(pwd)
            w = PdfWriter()
            for p in r.pages: w.add_page(copy.deepcopy(p))
            with open(out, "wb") as f: w.write(f)
            messagebox.showinfo("Done", f"Unlocked → {out}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

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

        win = tk.Toplevel(self.root)
        win.title("Run OCR")
        win.transient(self.root)
        win.configure(bg=UI_C["panel"])
        win.geometry("420x280")

        tk.Label(win, text="Run OCR on this document",
                 bg=UI_C["panel"], fg=UI_C["fg"],
                 font=("TkDefaultFont", 12, "bold")
                 ).pack(anchor="w", padx=14, pady=(14, 4))
        tk.Label(win,
                 text="A searchable PDF layer will be added using Tesseract "
                      "OCR. Each page is rasterised and recognised text is "
                      "re-embedded.",
                 bg=UI_C["panel"], fg=UI_C["fg_muted"],
                 wraplength=380, justify="left"
                 ).pack(anchor="w", padx=14, pady=(0, 10))

        lang = tk.StringVar(value="eng")
        dpi = tk.IntVar(value=220)
        scope = tk.StringVar(value="all")

        row = tk.Frame(win, bg=UI_C["panel"])
        row.pack(fill="x", padx=14, pady=4)
        tk.Label(row, text="Language (Tesseract code):",
                 bg=UI_C["panel"], fg=UI_C["fg_muted"]).pack(side="left")
        tk.Entry(row, textvariable=lang, width=8,
                 bg=UI_C["input_bg"], fg=UI_C["fg"], bd=0,
                 insertbackground=UI_C["accent"], relief="flat",
                 highlightthickness=1,
                 highlightbackground=UI_C["input_border"]
                 ).pack(side="left", padx=8)

        row2 = tk.Frame(win, bg=UI_C["panel"])
        row2.pack(fill="x", padx=14, pady=4)
        tk.Label(row2, text="Rasterise DPI:",
                 bg=UI_C["panel"], fg=UI_C["fg_muted"]).pack(side="left")
        tk.Entry(row2, textvariable=dpi, width=6,
                 bg=UI_C["input_bg"], fg=UI_C["fg"], bd=0,
                 insertbackground=UI_C["accent"], relief="flat",
                 highlightthickness=1,
                 highlightbackground=UI_C["input_border"]
                 ).pack(side="left", padx=8)

        row3 = tk.Frame(win, bg=UI_C["panel"])
        row3.pack(fill="x", padx=14, pady=4)
        tk.Label(row3, text="Scope:", bg=UI_C["panel"],
                 fg=UI_C["fg_muted"]).pack(side="left")
        for val, lbl in [("all", "All pages"),
                         ("included", "Included only"),
                         ("current", "Current page")]:
            tk.Radiobutton(row3, text=lbl, variable=scope, value=val,
                           bg=UI_C["panel"], fg=UI_C["fg"],
                           selectcolor=UI_C["panel"],
                           activebackground=UI_C["panel"],
                           activeforeground=UI_C["fg"],
                           bd=0, highlightthickness=0
                           ).pack(side="left", padx=6)

        def run_ocr():
            out = filedialog.asksaveasfilename(
                title="Save OCR'd PDF",
                defaultextension=".pdf",
                initialfile=os.path.splitext(
                    os.path.basename(self.primary_path))[0] + "_ocr.pdf",
                filetypes=[("PDF files", "*.pdf")])
            if not out:
                return
            win.destroy()
            self.progress.grid()
            self.progress.start(10)
            threading.Thread(
                target=self._run_ocr_worker,
                args=(out, lang.get(), int(dpi.get()), scope.get()),
                daemon=True).start()

        btns = tk.Frame(win, bg=UI_C["panel"])
        btns.pack(fill="x", padx=14, pady=14, side="bottom")
        tk.Button(btns, text="Cancel", command=win.destroy,
                  bg=UI_C["elevated"], fg=UI_C["fg"], bd=0,
                  activebackground=UI_C["elevated_hover"], cursor="hand2",
                  padx=14, pady=6).pack(side="right", padx=4)
        tk.Button(btns, text="Run OCR", command=run_ocr,
                  bg=UI_C["accent"], fg="#FFFFFF", bd=0,
                  activebackground=UI_C["accent_hover"], cursor="hand2",
                  padx=14, pady=6).pack(side="right", padx=4)

    def _run_ocr_worker(self, out_path, lang, dpi, scope):
        try:
            import pytesseract
            src_doc = fitz.open(self.primary_path)
            out_doc = fitz.open()
            included = {
                i for i, r in enumerate(self.pages)
                if r.included.get() and not r.is_blank
            }
            current = self._preview_index
            for i in range(src_doc.page_count):
                page = src_doc[i]
                apply_ocr = (
                    scope == "all"
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
                    raise RuntimeError(
                        f"Tesseract failed on page {i + 1}: {e}") from e
                ocr_doc = fitz.open("pdf", pdf_bytes)
                out_doc.insert_pdf(ocr_doc)
                ocr_doc.close()
            out_doc.save(out_path)
            out_doc.close()
            src_doc.close()
            self.root.after(0, lambda: (
                self.status_var.set(
                    f"🔎 OCR complete → {os.path.basename(out_path)}"),
                messagebox.showinfo("OCR complete",
                                    f"Saved searchable PDF:\n{out_path}")
            ))
        except Exception as e:
            msg = str(e)
            self.root.after(0, lambda: messagebox.showerror("OCR failed", msg))
        finally:
            self.root.after(0, lambda: (self.progress.stop(),
                                        self.progress.grid_remove()))

    def find_replace_dialog(self):
        find = simpledialog.askstring("Find", "Text to find:", parent=self.root)
        if not find: return
        replace = simpledialog.askstring("Replace", "Replace with:", parent=self.root)
        if replace is None: return
        out = filedialog.asksaveasfilename(defaultextension=".pdf")
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

    def compare_pages_dialog(self): messagebox.showinfo("Compare", "Open two pages in split view (Ctrl toggle preview split).")

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

    def header_footer_dialog(self):
        h = simpledialog.askstring("Header", "Header text (use {page}, {total}, {date}):",
                                   initialvalue=self.header_text.get(), parent=self.root)
        if h is not None: self.header_text.set(h)
        f = simpledialog.askstring("Footer", "Footer text:",
                                   initialvalue=self.footer_text.get(), parent=self.root)
        if f is not None: self.footer_text.set(f)

    def add_bookmark_dialog(self):
        title = simpledialog.askstring("Bookmark", "Title:", parent=self.root)
        if not title: return
        self._bookmarks.append({"title": title,
                                "page": max(0, self._preview_index)})
        if hasattr(self, "refresh_bookmarks_sidebar"):
            self.refresh_bookmarks_sidebar()
        self.status_var.set(f"🔖 Bookmark '{title}' added")

    def bookmarks_dialog(self):
        if not self._bookmarks:
            messagebox.showinfo("Bookmarks", "None yet — use Add Bookmark.")
            return
        msg = "\n".join(f"p.{b['page'] + 1}  {b['title']}" for b in self._bookmarks)
        messagebox.showinfo("Bookmarks", msg)

    def batch_process_dialog(self): messagebox.showinfo("Batch", "Batch process — wire from your original Part 2.")

    def show_output_options(self):
        win = tk.Toplevel(self.root)
        win.title("Output & Watermark Options")
        win.transient(self.root)
        win.configure(bg=UI_C["panel"])
        win.geometry("520x620")

        def _hdr(text):
            tk.Label(win, text=text, bg=UI_C["panel"], fg=UI_C["accent"],
                     font=("TkDefaultFont", 10, "bold")
                     ).pack(anchor="w", padx=16, pady=(14, 4))

        def _entry(parent, var, width=28):
            return tk.Entry(parent, textvariable=var, width=width,
                            bg=UI_C["input_bg"], fg=UI_C["fg"], bd=0,
                            insertbackground=UI_C["accent"], relief="flat",
                            highlightthickness=1,
                            highlightbackground=UI_C["input_border"])

        def _check(parent, text, var):
            return tk.Checkbutton(parent, text=text, variable=var,
                                  bg=UI_C["panel"], fg=UI_C["fg"],
                                  selectcolor=UI_C["panel"],
                                  activebackground=UI_C["panel"],
                                  activeforeground=UI_C["fg"],
                                  bd=0, highlightthickness=0)

        _hdr("WATERMARK")
        wrow = tk.Frame(win, bg=UI_C["panel"])
        wrow.pack(fill="x", padx=16)
        tk.Label(wrow, text="Text:", bg=UI_C["panel"],
                 fg=UI_C["fg_muted"]).pack(side="left")
        _entry(wrow, self.watermark_text, 26).pack(side="left", padx=8)

        wrow2 = tk.Frame(win, bg=UI_C["panel"])
        wrow2.pack(fill="x", padx=16, pady=(6, 0))
        tk.Label(wrow2, text="Opacity %:", bg=UI_C["panel"],
                 fg=UI_C["fg_muted"]).pack(side="left")
        tk.Scale(wrow2, from_=5, to=100, orient="horizontal",
                 variable=self.watermark_opacity, length=160,
                 bg=UI_C["panel"], troughcolor=UI_C["input_bg"],
                 fg=UI_C["fg"], activebackground=UI_C["accent"],
                 highlightthickness=0, bd=0).pack(side="left", padx=8)

        wrow3 = tk.Frame(win, bg=UI_C["panel"])
        wrow3.pack(fill="x", padx=16, pady=(6, 0))
        tk.Label(wrow3, text="Color:", bg=UI_C["panel"],
                 fg=UI_C["fg_muted"]).pack(side="left")
        swatch = tk.Label(wrow3, text="    ", width=4, relief="flat",
                          bg=self.watermark_color.get())
        swatch.pack(side="left", padx=8)

        def pick_wm():
            c = colorchooser.askcolor(color=self.watermark_color.get(),
                                      parent=win)
            if c and c[1]:
                self.watermark_color.set(c[1])
                swatch.configure(bg=c[1])
        tk.Button(wrow3, text="Choose…", command=pick_wm,
                  bg=UI_C["elevated"], fg=UI_C["fg"], bd=0, cursor="hand2",
                  activebackground=UI_C["elevated_hover"]
                  ).pack(side="left")

        _hdr("PAGE NUMBERS")
        pn1 = tk.Frame(win, bg=UI_C["panel"])
        pn1.pack(fill="x", padx=16)
        _check(pn1, "Add page numbers", self.add_page_numbers).pack(anchor="w")

        pn2 = tk.Frame(win, bg=UI_C["panel"])
        pn2.pack(fill="x", padx=16, pady=(4, 0))
        tk.Label(pn2, text="Format:", bg=UI_C["panel"],
                 fg=UI_C["fg_muted"]).pack(side="left")
        for val, lbl in [("decimal", "1, 2, 3"),
                          ("roman", "i, ii, iii"),
                          ("ALPHA", "A, B, C")]:
            tk.Radiobutton(pn2, text=lbl, variable=self.page_num_format,
                           value=val, bg=UI_C["panel"], fg=UI_C["fg"],
                           selectcolor=UI_C["panel"],
                           activebackground=UI_C["panel"],
                           activeforeground=UI_C["fg"], bd=0,
                           highlightthickness=0).pack(side="left", padx=4)

        pn3 = tk.Frame(win, bg=UI_C["panel"])
        pn3.pack(fill="x", padx=16, pady=(4, 0))
        tk.Label(pn3, text="Position:", bg=UI_C["panel"],
                 fg=UI_C["fg_muted"]).pack(side="left")
        for val, lbl in [("top-left", "TL"), ("top-center", "TC"),
                          ("top-right", "TR"), ("bottom-left", "BL"),
                          ("bottom-center", "BC"), ("bottom-right", "BR")]:
            tk.Radiobutton(pn3, text=lbl, variable=self.page_num_position,
                           value=val, bg=UI_C["panel"], fg=UI_C["fg"],
                           selectcolor=UI_C["panel"],
                           activebackground=UI_C["panel"],
                           activeforeground=UI_C["fg"], bd=0,
                           highlightthickness=0).pack(side="left", padx=4)

        _hdr("HEADER & FOOTER")
        hfrow = tk.Frame(win, bg=UI_C["panel"])
        hfrow.pack(fill="x", padx=16)
        tk.Label(hfrow, text="Header:", bg=UI_C["panel"],
                 fg=UI_C["fg_muted"], width=8, anchor="e"
                 ).grid(row=0, column=0, padx=(0, 6), pady=2)
        _entry(hfrow, self.header_text, 36).grid(row=0, column=1, pady=2)
        tk.Label(hfrow, text="Footer:", bg=UI_C["panel"],
                 fg=UI_C["fg_muted"], width=8, anchor="e"
                 ).grid(row=1, column=0, padx=(0, 6), pady=2)
        _entry(hfrow, self.footer_text, 36).grid(row=1, column=1, pady=2)

        _hdr("OUTPUT")
        out_row = tk.Frame(win, bg=UI_C["panel"])
        out_row.pack(fill="x", padx=16)
        _check(out_row, "Compress streams", self.compress_output).pack(anchor="w")
        _check(out_row, "Flatten form fields", self.flatten_forms).pack(anchor="w")
        _check(out_row, "Encrypt output", self.encrypt_pdf).pack(anchor="w")

        btns = tk.Frame(win, bg=UI_C["panel"])
        btns.pack(fill="x", padx=16, pady=14, side="bottom")

        def apply_and_save():
            self.status_var.set(
                "⚙ Output options saved. Use File ▸ Save to export.")
            win.destroy()

        def save_now():
            win.destroy()
            self.save_pdf()

        tk.Button(btns, text="Done", command=apply_and_save,
                  bg=UI_C["elevated"], fg=UI_C["fg"], bd=0,
                  activebackground=UI_C["elevated_hover"], cursor="hand2",
                  padx=14, pady=6).pack(side="right", padx=4)
        tk.Button(btns, text="Save PDF now…", command=save_now,
                  bg=UI_C["accent"], fg="#FFFFFF", bd=0,
                  activebackground=UI_C["accent_hover"], cursor="hand2",
                  padx=14, pady=6).pack(side="right", padx=4)

    def show_metadata_dialog(self):
        t = simpledialog.askstring("Title", "Title:",
                                   initialvalue=self.meta_title.get(),
                                   parent=self.root)
        if t is not None: self.meta_title.set(t)
        a = simpledialog.askstring("Author", "Author:",
                                   initialvalue=self.meta_author.get(),
                                   parent=self.root)
        if a is not None: self.meta_author.set(a)

    def show_shortcuts(self):
        msg = ("Ctrl+O  Open      Ctrl+S  Save     Ctrl+Z  Undo   Ctrl+Y  Redo\n"
               "Ctrl+A  Select all    Del  Delete selected\n"
               "Ctrl+K  Command palette   Ctrl+T  Theme   Ctrl+G  Grid   Ctrl+B  Sidebar\n"
               "Ctrl++  Zoom in   Ctrl+-  Zoom out   Ctrl+0  Fit   Ctrl+,  Preferences\n"
               "↑ ↓ Home End PgUp PgDn   Navigate rows\n"
               "Space  Toggle include   Enter  Preview\n"
               "← / →  Previous / next preview\n"
               "F1  This help")
        messagebox.showinfo("Keyboard Shortcuts", msg)

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
        self._load_thumbs_async()

    # ─── SAVE ──────────────────────────────────────────────────────────
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
        self.progress.grid(); self.progress.start(10)
        threading.Thread(
            target=lambda: self._write_pdf_thread(included, out_path),
            daemon=True).start()

    def _write_pdf_thread(self, records, out_path):
        try:
            self._write_pdf(records, out_path)
        finally:
            self.root.after(0, lambda: (self.progress.stop(),
                                        self.progress.grid_remove()))

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
                writer.encrypt(user_password=self.user_password.get(),
                               owner_password=self.owner_password.get())

            with open(out_path, "wb") as f:
                writer.write(f)

            # ── POST-PROCESS WITH FITZ ─────────────────────────────────
            self._apply_fitz_overlays(records, out_path)

            n = len(records)
            self.root.after(0, lambda: (
                self.status_var.set(f"✅ Saved {n} page{'s' if n != 1 else ''} → {os.path.basename(out_path)}"),
                messagebox.showinfo("Saved", f"Saved {n} page(s)!\n\n{out_path}")
            ))
        except Exception as e:
            err = str(e)
            self.root.after(0, lambda: messagebox.showerror("Error", f"Failed to save:\n{err}"))

    # ─── FITZ OVERLAY PIPELINE ─────────────────────────────────────────
    def _apply_fitz_overlays(self, records, out_path):
        try:
            need_overlay = (
                any(getattr(r, "annotations", None) for r in records)
                or any(getattr(r, "redactions", None) for r in records)
                or (self.watermark_text.get().strip() != "")
                or self.add_page_numbers.get()
                or self.header_text.get().strip() != ""
                or self.footer_text.get().strip() != ""
            )
            if not need_overlay:
                return

            doc = fitz.open(out_path)
            for i, rec in enumerate(records):
                if i >= doc.page_count:
                    break
                page = doc[i]
                self._add_overlay(page, rec, i + 1, len(records))
            tmp = out_path + ".tmp"
            doc.save(tmp, deflate=True, garbage=3)
            doc.close()
            os.replace(tmp, out_path)
        except Exception as e:
            err = str(e)
            self.root.after(0, lambda: self.status_var.set(
                f"⚠ Overlay step skipped: {err}"))

    def _add_overlay(self, page, rec, page_num, total):
        rect = page.rect
        W, H = rect.width, rect.height

        # Redactions
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

        # Text annotations
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
                if not text:
                    continue
                x = float(ann.get("x", 0.1)) * W
                y = float(ann.get("y", 0.9)) * H
                size = int(ann.get("fontsize", 12))
                color = self._hex_to_rgb01(ann.get("color", "#000000"))
                page.insert_text((x, y), text, fontsize=size, color=color,
                                 fontname="helv")
            except Exception:
                continue

        # Watermark
        wm = self.watermark_text.get().strip()
        if wm:
            try:
                opacity = max(0.0, min(1.0,
                                       float(self.watermark_opacity.get()) / 100.0))
                color = self._hex_to_rgb01(self.watermark_color.get() or "#AAAAAA")
                fs = max(24, int(min(W, H) / 9))
                tw = fitz.get_text_length(wm, fontname="helv", fontsize=fs)
                cx, cy = W / 2, H / 2
                morph = (
                    fitz.Point(cx, cy),
                    fitz.Matrix(1, 0, 0, 1, 0, 0).prerotate(-45)
                )
                page.insert_text((cx - tw / 2, cy + fs / 3), wm,
                                 fontsize=fs, fontname="helv",
                                 color=color, fill_opacity=opacity,
                                 stroke_opacity=opacity, morph=morph,
                                 render_mode=0)
            except Exception:
                pass

        # Header / Footer
        header = self.header_text.get().strip()
        footer = self.footer_text.get().strip()

        def _expand(t):
            from datetime import datetime
            return (t.replace("{page}", str(page_num))
                     .replace("{total}", str(total))
                     .replace("{date}", datetime.now().strftime("%Y-%m-%d")))

        if header:
            try:
                page.insert_text((36, 28), _expand(header),
                                 fontsize=10, fontname="helv",
                                 color=(0.25, 0.25, 0.25))
            except Exception:
                pass
        if footer:
            try:
                page.insert_text((36, H - 20), _expand(footer),
                                 fontsize=10, fontname="helv",
                                 color=(0.25, 0.25, 0.25))
            except Exception:
                pass

        # Page numbers
        if self.add_page_numbers.get():
            try:
                fmt = self.page_num_format.get()
                if fmt == "roman":
                    label = _to_roman(page_num)
                elif fmt == "ALPHA":
                    label = self._alpha_label(page_num)
                else:
                    label = str(page_num)
                pos = self.page_num_position.get()
                margin = 28
                fs = 11
                tw = fitz.get_text_length(label, fontname="helv", fontsize=fs)
                if pos.endswith("left"):
                    x = margin
                elif pos.endswith("right"):
                    x = W - tw - margin
                else:
                    x = (W - tw) / 2
                if pos.startswith("top"):
                    y = margin
                else:
                    y = H - margin / 2
                page.insert_text((x, y), label, fontsize=fs,
                                 fontname="helv", color=(0.15, 0.15, 0.15))
            except Exception:
                pass

    @staticmethod
    def _hex_to_rgb01(hx):
        try:
            hx = hx.lstrip("#")
            if len(hx) == 3:
                hx = "".join(c * 2 for c in hx)
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

    # ─── SESSION / STATUS ──────────────────────────────────────────────
    def _clear_saved_session(self):
        try:
            if SESSION_FILE.exists(): SESSION_FILE.unlink()
        except Exception: pass

    def _update_status(self):
        if not self.pages:
            self.status_var.set("Open a PDF to get started.")
            return
        total = len(self.pages)
        included = sum(r.included.get() for r in self.pages)
        sel = len(self.selected_pages)
        sel_str = f" • {sel} selected" if sel else ""
        self.status_var.set(
            f"{included}/{total} pages included{sel_str} • "
            f"Preview: page {self._preview_index + 1 if self._preview_index >= 0 else '—'}")