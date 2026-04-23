"""
PDF Studio – UI Shell  (v2: full Acrobat-parity chrome)
─────────────────────────────────────────────────────────────────────────────
Additions over v1:
    • Smooth animated drag-to-reorder  (variable row heights, eased motion)
    • Command palette  (Ctrl+K  / Ctrl+Shift+P)
    • Drag-and-drop file opening (graceful fallback without tkinterdnd2)
    • Custom dark / cream canvas scrollbars
    • Grid view toggle  (list vs 4/6/8 column thumbnail grid)
    • Bookmarks / outline sidebar (collapsible)
    • Keyboard navigation  (↑ ↓ Space Enter Home End PgUp PgDn)
    • Toast notifications  (corner slide-in)
    • Breadcrumb path in titlebar (click a segment → reveal in OS file mgr)
    • Recent-files cards on empty state
    • Hover popover on thumbnails (text snippet preview)
    • Undo history dropdown
    • Preferences dialog
    • Splash screen for .exe cold-start

Contract with host PDFStudio class is preserved – every original hook
(`_build_*`, `add_page_row`, `update_titlebar`, `refresh_recent_menu`,
`update_undo_redo`, `clear_page_rows`) still exists and behaves.
"""
from __future__ import annotations
import os
import sys
import subprocess
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from PIL import ImageTk


# ─────────────────────────────────────────────────────────────────────────────
#  DESIGN TOKENS
# ─────────────────────────────────────────────────────────────────────────────

C_DARK = {
    "bg": "#0E0E17", "panel": "#141423", "panel_alt": "#1A1A2C",
    "elevated": "#1F1F33", "elevated_hover": "#272742",
    "elevated_sel": "#3A2330",
    "border": "#262638", "border_strong": "#35354F", "divider": "#1F1F33",
    "fg": "#E6E6F0", "fg_muted": "#9A9AB8", "fg_dim": "#5E5E78",
    "fg_on_accent": "#FFFFFF",
    "accent": "#DC2626", "accent_hover": "#EF4444", "accent_dim": "#7A1515",
    "accent2": "#60A5FA",
    "success": "#4ADE80", "warning": "#FBBF24", "danger": "#F87171",
    "info": "#60A5FA",
    "row_even": "#141423", "row_odd": "#181828",
    "excluded": "#2A1A20", "excluded_tint": "#4A2030",
    "selected_bar": "#DC2626", "preview_bg": "#07070D",
    "scroll_trough": "#141423", "scroll_thumb": "#2F2F47",
    "scroll_hover": "#DC2626",
    "toolbar": "#141423", "statusbar": "#0B0B13",
    "shadow": "#05050A", "kbd_bg": "#1F1F33", "kbd_fg": "#FCA5A5",
    "focus_ring": "#DC2626",
    "popover_bg": "#1F1F33",
    "input_bg": "#2C2C44", "input_border": "#4A4A6A",
    "input_focus": "#DC2626",
    "brand_red": "#DC2626", "brand_navy": "#1E2431",
}

C_LIGHT = {
    "bg": "#F7F5F0", "panel": "#FFFFFF", "panel_alt": "#FBF8F1",
    "elevated": "#FFFFFF", "elevated_hover": "#FEE2E2",
    "elevated_sel": "#FECACA",
    "border": "#E6E0D4", "border_strong": "#D4CCBB", "divider": "#EDE7D9",
    "fg": "#1E2431", "fg_muted": "#475569", "fg_dim": "#94909E",
    "fg_on_accent": "#FFFFFF",
    "accent": "#DC2626", "accent_hover": "#B91C1C", "accent_dim": "#FCA5A5",
    "accent2": "#1E2431",
    "success": "#16A34A", "warning": "#D97706", "danger": "#DC2626",
    "info": "#2563EB",
    "row_even": "#FFFFFF", "row_odd": "#FBF8F1",
    "excluded": "#FDECE7", "excluded_tint": "#F8C5B5",
    "selected_bar": "#DC2626", "preview_bg": "#1E2431",
    "scroll_trough": "#EDE7D9", "scroll_thumb": "#C9C0AE",
    "scroll_hover": "#DC2626",
    "toolbar": "#FFFFFF", "statusbar": "#FBF8F1",
    "shadow": "#D4CCBB", "kbd_bg": "#FEE2E2", "kbd_fg": "#7A1515",
    "focus_ring": "#DC2626",
    "popover_bg": "#FFFFFF",
    "input_bg": "#F1EDE3", "input_border": "#C9C0AE",
    "input_focus": "#DC2626",
    "brand_red": "#DC2626", "brand_navy": "#1E2431",
}

C = dict(C_DARK)


def _set_palette(dark: bool) -> None:
    src = C_DARK if dark else C_LIGHT
    for k in list(C.keys()):
        C.pop(k)
    C.update(src)


# ─────────────────────────────────────────────────────────────────────────────
#  ASSETS  (PyInstaller-aware)
# ─────────────────────────────────────────────────────────────────────────────

def _assets_dir():
    """Resolve the assets folder for both normal runs and PyInstaller .exe."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        p = os.path.join(base, "UI", "assets")
        if os.path.isdir(p):
            return p
        p = os.path.join(base, "assets")
        if os.path.isdir(p):
            return p
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def asset_path(name):
    """Return absolute path to an asset file by name."""
    return os.path.join(_assets_dir(), name)


# Lazy-loaded Tk PhotoImage cache (keyed by filename)
_IMG_CACHE = {}


def load_brand_image(name, max_w=None, max_h=None):
    """Load a bundled PNG as ImageTk.PhotoImage (cached). Returns None on
    failure so the UI can fall back to a vector-drawn logo."""
    key = (name, max_w, max_h)
    if key in _IMG_CACHE:
        return _IMG_CACHE[key]
    try:
        from PIL import Image, ImageTk
        p = asset_path(name)
        if not os.path.isfile(p):
            return None
        im = Image.open(p).convert("RGBA")
        if max_w or max_h:
            w, h = im.size
            scale = min((max_w or w) / w, (max_h or h) / h)
            if scale < 1:
                im = im.resize((int(w * scale), int(h * scale)),
                               Image.LANCZOS)
        tkimg = ImageTk.PhotoImage(im)
        _IMG_CACHE[key] = tkimg
        return tkimg
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
#  FONTS
# ─────────────────────────────────────────────────────────────────────────────

def _pick_font(candidates, fallback="TkDefaultFont"):
    try:
        available = set(tkfont.families())
    except Exception:
        return fallback
    for name in candidates:
        if name in available:
            return name
    return fallback


def _fonts():
    ui = _pick_font([
        "Inter", "Segoe UI Variable", "Segoe UI", "SF Pro Text",
        "Ubuntu", "Cantarell", "Helvetica Neue", "Helvetica", "Arial"])
    mono = _pick_font([
        "JetBrains Mono", "Fira Code", "Cascadia Code", "SF Mono",
        "Consolas", "Menlo", "DejaVu Sans Mono", "Courier New"])
    display = _pick_font([
        "Space Grotesk", "Inter", "Segoe UI Semibold", "SF Pro Display",
        "Helvetica Neue", "Helvetica", "Arial"])
    return ui, mono, display


# ─────────────────────────────────────────────────────────────────────────────
#  TOOLTIP + HOVER BUTTON
# ─────────────────────────────────────────────────────────────────────────────

class _Tooltip:
    def __init__(self, widget, text, delay_ms=380):
        self.widget, self.text, self.delay = widget, text, delay_ms
        self.tip, self._after = None, None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _=None):
        self._cancel()
        self._after = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._after:
            try:
                self.widget.after_cancel(self._after)
            except Exception:
                pass
            self._after = None

    def _show(self):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        self.tip.configure(bg=C["border_strong"])
        inner = tk.Frame(self.tip, bg=C["popover_bg"], bd=0,
                         highlightthickness=1,
                         highlightbackground=C["border_strong"])
        inner.pack(padx=1, pady=1)
        tk.Label(inner, text=self.text, bg=C["popover_bg"], fg=C["fg"],
                 font=("TkDefaultFont", 9), padx=10, pady=5).pack()

    def _hide(self, _=None):
        self._cancel()
        if self.tip:
            try:
                self.tip.destroy()
            except Exception:
                pass
            self.tip = None


class _HoverButton(tk.Frame):
    def __init__(self, master, label="", glyph="", command=None, style="ghost",
                 tooltip=None, compact=False, font=None, fg_override=None):
        super().__init__(master, bg=master.cget("bg"), bd=0,
                         highlightthickness=0)
        self._command = command or (lambda: None)
        self._style = style
        self._enabled = True
        self._fg_override = fg_override
        self._base_bg, self._base_fg = self._resolve(False)
        self._hover_bg, self._hover_fg = self._resolve(True)
        padx = 8 if compact else 12
        pady = 4 if compact else 6
        self._inner = tk.Frame(self, bg=self._base_bg, bd=0,
                               highlightthickness=0)
        self._inner.pack(fill="both", expand=True)
        fui = font or ("TkDefaultFont", 9 if compact else 10,
                       "bold" if style == "accent" else "normal")
        if glyph:
            self._gl = tk.Label(
                self._inner, text=glyph, bg=self._base_bg, fg=self._base_fg,
                font=("TkDefaultFont", 11 if compact else 13), padx=0, pady=0)
            self._gl.pack(side="left",
                          padx=(padx, 4 if label else padx), pady=pady)
        else:
            self._gl = None
        if label:
            self._lbl = tk.Label(
                self._inner, text=label, bg=self._base_bg, fg=self._base_fg,
                font=fui, padx=0, pady=0)
            self._lbl.pack(side="left",
                           padx=(0 if glyph else padx, padx), pady=pady)
        else:
            self._lbl = None
        for w in (self, self._inner, self._gl, self._lbl):
            if w is None:
                continue
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)
            w.bind("<Button-1>", self._on_click)
            w.bind("<ButtonRelease-1>", self._on_release)
        if tooltip:
            _Tooltip(self, tooltip)

    def _resolve(self, hover):
        if self._style == "accent":
            return (C["accent_hover"] if hover else C["accent"],
                    C["fg_on_accent"])
        if self._style == "solid":
            return (C["elevated_hover"] if hover else C["elevated"],
                    self._fg_override or C["fg"])
        if self._style == "danger":
            return (C["danger"] if hover else C["elevated"],
                    "#FFFFFF" if hover else C["danger"])
        if self._style == "success":
            return (C["success"] if hover else C["elevated"],
                    "#FFFFFF" if hover else C["success"])
        return (C["elevated_hover"] if hover else self.master.cget("bg"),
                self._fg_override or (C["fg"] if hover else C["fg_muted"]))

    def _apply(self, bg, fg):
        self._inner.configure(bg=bg)
        if self._gl:
            self._gl.configure(bg=bg, fg=fg)
        if self._lbl:
            self._lbl.configure(bg=bg, fg=fg)

    def _on_enter(self, _=None):
        if self._enabled:
            self._apply(self._hover_bg, self._hover_fg)

    def _on_leave(self, _=None):
        if self._enabled:
            self._apply(self._base_bg, self._base_fg)

    def _on_click(self, _=None):
        if self._enabled:
            self._apply(self._hover_bg, self._hover_fg)

    def _on_release(self, _=None):
        if self._enabled:
            self._on_enter()
            self._command()

    def set_enabled(self, state):
        self._enabled = bool(state)
        if self._enabled:
            self._apply(self._base_bg, self._base_fg)
        else:
            self._apply(self._base_bg, C["fg_dim"])

    def set_text(self, text):
        if self._lbl:
            self._lbl.configure(text=text)


def _divider(parent, orient="vertical", pad=8):
    if orient == "vertical":
        f = tk.Frame(parent, bg=C["border"], width=1)
        f.pack(side="left", fill="y", padx=pad, pady=6)
    else:
        f = tk.Frame(parent, bg=C["border"], height=1)
        f.pack(side="top", fill="x", padx=pad, pady=4)
    return f


# ─────────────────────────────────────────────────────────────────────────────
#  CUSTOM SCROLLBAR (canvas-drawn, themable)
# ─────────────────────────────────────────────────────────────────────────────

class _CanvasScrollbar(tk.Canvas):
    """A slim dark-theme scrollbar drawn on a canvas."""
    def __init__(self, master, target_canvas, width=8):
        super().__init__(master, width=width, bg=C["scroll_trough"],
                         highlightthickness=0, bd=0)
        self.target = target_canvas
        self._dragging = False
        self._drag_offset = 0
        self.bind("<Configure>", self._redraw)
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", lambda _e: setattr(
            self, "_dragging", False))
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self._hover = False

    def set(self, lo, hi):
        self._lo, self._hi = float(lo), float(hi)
        self._redraw()

    def _redraw(self, _=None):
        self.delete("all")
        h = self.winfo_height()
        w = self.winfo_width()
        if h <= 1:
            return
        lo = getattr(self, "_lo", 0.0)
        hi = getattr(self, "_hi", 1.0)
        if hi - lo >= 0.999:
            return
        color = C["scroll_hover"] if self._hover else C["scroll_thumb"]
        y0 = int(lo * h) + 2
        y1 = int(hi * h) - 2
        if y1 - y0 < 20:
            y1 = y0 + 20
        self.create_rectangle(2, y0, w - 2, y1, fill=color, outline="",
                              width=0)

    def _on_enter(self, _=None):
        self._hover = True
        self._redraw()

    def _on_leave(self, _=None):
        self._hover = False
        self._redraw()

    def _on_press(self, event):
        h = self.winfo_height()
        lo = getattr(self, "_lo", 0.0)
        hi = getattr(self, "_hi", 1.0)
        y0 = int(lo * h)
        y1 = int(hi * h)
        if y0 <= event.y <= y1:
            self._dragging = True
            self._drag_offset = event.y - y0
        else:
            # click in trough — center
            frac = max(0.0, min(1.0, (event.y - (y1 - y0) / 2) / h))
            self.target.yview_moveto(frac)

    def _on_drag(self, event):
        if not self._dragging:
            return
        h = self.winfo_height()
        lo = getattr(self, "_lo", 0.0)
        hi = getattr(self, "_hi", 1.0)
        vis = hi - lo
        y0 = event.y - self._drag_offset
        frac = max(0.0, min(1.0 - vis, y0 / h))
        self.target.yview_moveto(frac)


# ─────────────────────────────────────────────────────────────────────────────
#  TOAST HOST (brief dialog_kit.Toast stub; real impl in dialog_kit)
# ─────────────────────────────────────────────────────────────────────────────

def _get_toaster(ui):
    """Lazy singleton toast host attached to the UI."""
    if not hasattr(ui, "_toaster"):
        try:
            from UI.dialog_kit import Toast
            ui._toaster = Toast(ui.root)
        except Exception:
            ui._toaster = None
    return ui._toaster


# ─────────────────────────────────────────────────────────────────────────────
#  ANIMATED DRAG-REORDER MANAGER
# ─────────────────────────────────────────────────────────────────────────────

class _DragManager:
    """Turn pack'd page rows into a smooth, animated drag-reorder surface.

    Strategy:
      1. On first drag, snapshot every row's y/height and switch to place()
         layout at those positions.
      2. Lift the grabbed row (raise_, bg=accent_dim) and let it follow the
         cursor. Other rows animate toward shifted positions using an
         eased interpolation on an `after` tick (16 ms / ~60 fps).
      3. On release, commit the new order on `ui.pages`, push an undo,
         restore pack geometry, and trigger a normal redraw.
    """

    def __init__(self, ui):
        self.ui = ui
        self.active = False
        self._src_index = None
        self._cur_index = None
        self._rows = []                 # list of tk.Frame in DOM order
        self._order = []                # list of ui-indices (may reorder)
        self._heights = []
        self._targets = {}              # widget → target y
        self._y_offsets = []            # cumulative y
        self._cursor_off = 0            # click offset within dragged row
        self._tick_scheduled = False
        self._row_frame = None
        self._grab_origin = 0

    # ── public API ───────────────────────────────────────────────────────
    def start(self, event, index):
        ui = self.ui
        if self.active:
            return
        rows = [r for r in ui.rows_frame.winfo_children()
                if r not in getattr(ui, "_non_row_widgets", ())]
        # filter out the empty-state hint
        rows = [r for r in rows if r is not getattr(ui, "_empty_hint", None)
                and r is not getattr(ui, "_recent_panel", None)]
        if index >= len(rows) or not rows:
            return

        self.active = True
        self._rows = rows
        self._order = list(range(len(rows)))
        self._src_index = index
        self._cur_index = index
        self._row_frame = ui.rows_frame

        # Capture y + height for each row
        ui.rows_frame.update_idletasks()
        self._heights = [r.winfo_height() for r in rows]
        self._y_offsets = []
        y = 0
        for h in self._heights:
            self._y_offsets.append(y)
            y += h

        # Switch every row to place()
        for i, r in enumerate(rows):
            r.pack_forget()
            r.place(x=0, y=self._y_offsets[i], relwidth=1, height=self._heights[i])

        ui.rows_frame.configure(height=y)

        dragged = rows[index]
        dragged.configure(bg=C["accent_dim"])
        try:
            dragged.lift()
        except Exception:
            pass
        self._cursor_off = event.y_root - dragged.winfo_rooty()
        self._grab_origin = dragged.winfo_rooty()

        # Bind to root so motion/release work even outside the row
        ui.root.bind("<B1-Motion>", self._on_motion, add="+")
        ui.root.bind("<ButtonRelease-1>", self._on_release, add="+")

    # ── motion / tick ────────────────────────────────────────────────────
    def _on_motion(self, event):
        if not self.active:
            return
        rows = self._rows
        dragged = rows[self._src_index]
        # Place dragged at cursor y within rows_frame
        frame_y = event.y_root - self._row_frame.winfo_rooty() - self._cursor_off
        max_y = sum(self._heights) - self._heights[self._src_index]
        frame_y = max(0, min(max_y, frame_y))
        dragged.place(y=frame_y)

        # Decide target index based on cursor position
        mid = frame_y + self._heights[self._src_index] / 2
        # Compute indices other than the source in logical order, then pick
        # insertion index
        other_positions = []
        cy = 0
        for i in self._order:
            if i == self._src_index:
                continue
            other_positions.append((i, cy, cy + self._heights[i]))
            cy += self._heights[i]

        new_logical = len(other_positions)
        for pos, (_, y0, y1) in enumerate(other_positions):
            if mid < (y0 + y1) / 2:
                new_logical = pos
                break

        # Convert back to "insertion index in full list"
        if new_logical != self._cur_index_to_logical():
            self._set_logical(new_logical)

        self._schedule_tick()

    def _cur_index_to_logical(self):
        # Position of src in current order
        return self._order.index(self._src_index)

    def _set_logical(self, new_logical):
        order = [i for i in self._order if i != self._src_index]
        new_logical = max(0, min(len(order), new_logical))
        order.insert(new_logical, self._src_index)
        self._order = order
        self._compute_targets()

    def _compute_targets(self):
        y = 0
        for i in self._order:
            if i != self._src_index:
                self._targets[self._rows[i]] = y
            y += self._heights[i]

    def _schedule_tick(self):
        if self._tick_scheduled or not self.active:
            return
        self._tick_scheduled = True
        self.ui.root.after(16, self._tick)

    def _tick(self):
        self._tick_scheduled = False
        if not self.active:
            return
        done_all = True
        for w, ty in list(self._targets.items()):
            try:
                cy = w.winfo_y()
            except Exception:
                continue
            if abs(cy - ty) < 1:
                w.place(y=ty)
                continue
            done_all = False
            # Ease-out: move 28% of remaining distance
            ny = cy + (ty - cy) * 0.28
            w.place(y=int(ny))
        if not done_all:
            self._schedule_tick()

    # ── release ──────────────────────────────────────────────────────────
    def _on_release(self, _event):
        if not self.active:
            return
        self.active = False
        ui = self.ui
        try:
            ui.root.unbind("<B1-Motion>")
            ui.root.unbind("<ButtonRelease-1>")
        except Exception:
            pass

        # Commit new order
        if self._order and self._order != list(range(len(self._rows))):
            if hasattr(ui, "_push_undo"):
                try:
                    ui._push_undo("reorder pages")
                except Exception:
                    pass
            if hasattr(ui, "pages") and len(ui.pages) == len(self._rows):
                ui.pages = [ui.pages[i] for i in self._order]
                tx = _get_toaster(ui)
                if tx:
                    tx.show(f"Page {self._src_index + 1} "
                            f"moved to position {self._order.index(self._src_index) + 1}",
                            kind="success")

        # Restore pack layout by rebuilding
        if hasattr(ui, "_rebuild_rows"):
            try:
                ui._rebuild_rows()
            except Exception:
                pass
        if hasattr(ui, "_update_status"):
            try:
                ui._update_status()
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
#  COMMAND PALETTE
# ─────────────────────────────────────────────────────────────────────────────

class _CommandPalette:
    """Overlay palette triggered by Ctrl+K.

    Commands are registered via `ui._register_cmd(name, key_hint, callback,
    group='...')`. Palette fuzzy-filters by label.
    """

    def __init__(self, ui):
        self.ui = ui
        self.win = None

    def register_defaults(self):
        ui = self.ui
        r = ui._register_cmd
        r("Open PDF…", "Ctrl+O", self._safe("browse_file"), "file")
        r("Save PDF…", "Ctrl+S", self._safe("save_pdf"), "file")
        r("Merge PDF…", "", self._safe("merge_pdf"), "file")
        r("Import Images…", "", self._safe("import_images"), "file")
        r("Export as Images…", "", self._safe("export_as_images"), "file")
        r("Extract Included Pages…", "", self._safe("extract_pages"), "file")
        r("Batch Process Folder…", "", self._safe("batch_process_dialog"),
          "file")
        r("Save Preset…", "", self._safe("save_preset"), "file")
        r("Load Preset…", "", self._safe("load_preset"), "file")

        r("Undo", "Ctrl+Z", self._safe("do_undo"), "edit")
        r("Redo", "Ctrl+Y", self._safe("do_redo"), "edit")
        r("Select All Pages", "Ctrl+A", self._safe("select_all_pages"),
          "edit")
        r("Deselect All", "", self._safe("deselect_all_pages"), "edit")
        r("Delete Selected Pages", "Del", self._safe("delete_selected"),
          "edit")
        r("Duplicate Selected Pages", "", self._safe("duplicate_selected"),
          "edit")

        r("Insert Blank Page", "", self._safe("insert_blank"), "page")
        r("Reverse Page Order", "", self._safe("reverse_pages"), "page")
        r("Rotate All Clockwise", "",
          lambda: self._safe("rotate_all_pages")(90), "page")
        r("Rotate All Counter-Clockwise", "",
          lambda: self._safe("rotate_all_pages")(-90), "page")
        r("Reset All Orientations", "", self._safe("reset_all_orient"),
          "page")
        r("Include All Pages", "",
          lambda: self._safe("set_all_include")(True), "page")
        r("Exclude All Pages", "",
          lambda: self._safe("set_all_include")(False), "page")
        r("Select Odd Pages", "",
          lambda: self._safe("select_odd_even")("odd"), "page")
        r("Select Even Pages", "",
          lambda: self._safe("select_odd_even")("even"), "page")

        r("Add Text Annotation…", "", self._safe("add_text_annotation"),
          "tool")
        r("Add Image Stamp…", "", self._safe("add_stamp_dialog"), "tool")
        r("Redact Region…", "", self._safe("redact_dialog"), "tool")
        r("Crop Margins…", "", self._safe("crop_margins_dialog"), "tool")
        r("Resize Pages…", "", self._safe("resize_pages_dialog"), "tool")
        r("Header / Footer…", "", self._safe("header_footer_dialog"), "tool")
        r("Run OCR…", "", self._safe("ocr_dialog"), "tool")
        r("Find & Replace Text…", "", self._safe("find_replace_dialog"),
          "tool")
        r("Compare Pages Side-by-Side…", "",
          self._safe("compare_pages_dialog"), "tool")
        r("Page Inspector…", "", self._safe("page_inspector_dialog"), "tool")
        r("Encrypt PDF…", "", self._safe("encryption_dialog"), "tool")
        r("Unlock Password PDF…", "", self._safe("unlock_pdf_dialog"),
          "tool")
        r("Add Bookmark…", "", self._safe("add_bookmark_dialog"), "tool")
        r("Manage Bookmarks…", "", self._safe("bookmarks_dialog"), "tool")

        # New feature hooks (wired only if backend mixes in pdf_features)
        r("Bates Numbering…", "", self._safe("bates_dialog"), "pro")
        r("Keyword Bulk Redaction…", "",
          self._safe("keyword_redact_dialog"), "pro")
        r("Signature Tool…", "", self._safe("signature_dialog"), "pro")
        r("Hyperlink Editor…", "", self._safe("hyperlinks_dialog"), "pro")
        r("Attachment Extractor…", "",
          self._safe("attachments_dialog"), "pro")
        r("Auto-generate TOC…", "", self._safe("toc_auto_dialog"), "pro")
        r("Measuring Tool…", "", self._safe("measure_dialog"), "pro")
        r("Auto-Crop Whitespace", "", self._safe("auto_crop_dialog"), "pro")
        r("Form Fields (Fill / Flatten)…", "",
          self._safe("form_fields_dialog"), "pro")
        r("Highlight Text…", "",
          lambda: self._safe("markup_dialog")("highlight"), "pro")
        r("Strike-through Text…", "",
          lambda: self._safe("markup_dialog")("strikeout"), "pro")
        r("Underline Text…", "",
          lambda: self._safe("markup_dialog")("underline"), "pro")
        r("Sticky Note…", "",
          lambda: self._safe("markup_dialog")("note"), "pro")
        r("Toggle Split View", "", self._safe("toggle_split_view"), "pro")

        r("Output Options…", "", self._safe("show_output_options"), "out")
        r("Edit Metadata…", "", self._safe("show_metadata_dialog"), "out")
        r("Preferences…", "Ctrl+,", self._safe("show_preferences"), "out")
        r("Toggle Theme", "Ctrl+T", self.ui._invoke_toggle_theme, "view")
        r("Toggle Grid View", "Ctrl+G", self.ui._toggle_grid_view, "view")
        r("Toggle Sidebar", "Ctrl+B", self.ui._toggle_sidebar, "view")
        r("Zoom In", "Ctrl+=", self._safe("_zoom_in"), "view")
        r("Zoom Out", "Ctrl+-", self._safe("_zoom_out"), "view")
        r("Fit Preview", "Ctrl+0", self._safe("_zoom_fit"), "view")
        r("Keyboard Shortcuts", "F1", self._safe("show_shortcuts"), "help")

    def _safe(self, name):
        def caller(*a, **kw):
            fn = getattr(self.ui, name, None)
            if callable(fn):
                return fn(*a, **kw)
        return caller

    def open(self):
        if self.win and tk.Toplevel.winfo_exists(self.win):
            try:
                self.win.lift()
                self.entry.focus_set()
                return
            except Exception:
                pass
        self._build()

    def _build(self):
        ui = self.ui
        win = tk.Toplevel(ui.root)
        self.win = win
        win.wm_overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=C["border_strong"])

        # Dim backdrop (best-effort — not on all window managers)
        w, h = 640, 460
        rx, ry = ui.root.winfo_rootx(), ui.root.winfo_rooty()
        rw = ui.root.winfo_width()
        x = rx + (rw - w) // 2
        y = ry + 80
        win.geometry(f"{w}x{h}+{x}+{y}")

        inner = tk.Frame(win, bg=C["panel"], bd=0)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        top = tk.Frame(inner, bg=C["panel"])
        top.pack(fill="x", padx=14, pady=(14, 8))
        tk.Label(top, text="⌕", bg=C["panel"], fg=C["accent"],
                 font=("TkDefaultFont", 16, "bold")
                 ).pack(side="left", padx=(0, 8))
        var = tk.StringVar()
        self.entry = tk.Entry(
            top, textvariable=var, bd=0, bg=C["panel"], fg=C["fg"],
            insertbackground=C["accent"],
            font=("TkDefaultFont", 14), relief="flat",
            highlightthickness=0)
        self.entry.pack(side="left", fill="x", expand=True, ipady=6)

        hint = tk.Label(top, text="esc",
                        bg=C["kbd_bg"], fg=C["kbd_fg"],
                        font=("TkFixedFont", 9, "bold"),
                        padx=6, pady=2)
        hint.pack(side="right")

        tk.Frame(inner, bg=C["border"], height=1).pack(fill="x")

        # list
        body = tk.Frame(inner, bg=C["panel"])
        body.pack(fill="both", expand=True, padx=0, pady=0)
        self.listbox = tk.Listbox(
            body, bd=0, bg=C["panel"], fg=C["fg"],
            selectbackground=C["accent"], selectforeground=C["fg_on_accent"],
            activestyle="none", font=("TkDefaultFont", 11),
            highlightthickness=0, relief="flat")
        self.listbox.pack(fill="both", expand=True, padx=0, pady=0)

        # footer hint
        foot = tk.Frame(inner, bg=C["panel_alt"], height=30)
        foot.pack(fill="x")
        foot.pack_propagate(False)
        for text, hint_text in [("↑↓", "navigate"), ("↵", "run"),
                                ("esc", "close")]:
            chip = tk.Frame(foot, bg=C["panel_alt"])
            chip.pack(side="left", padx=10, pady=6)
            tk.Label(chip, text=text, bg=C["kbd_bg"], fg=C["kbd_fg"],
                     font=("TkFixedFont", 8, "bold"),
                     padx=6, pady=2).pack(side="left")
            tk.Label(chip, text=" " + hint_text, bg=C["panel_alt"],
                     fg=C["fg_muted"],
                     font=("TkDefaultFont", 9)).pack(side="left")

        self._cmds = list(ui._commands)
        self._matches = list(self._cmds)

        def _populate(query=""):
            q = query.lower().strip()
            self.listbox.delete(0, "end")
            if not q:
                self._matches = list(self._cmds)
            else:
                scored = []
                for c in self._cmds:
                    label = c["label"].lower()
                    if q in label:
                        score = label.find(q)
                        scored.append((score, c))
                    else:
                        # fuzzy: all chars appear in order
                        i = 0
                        for ch in label:
                            if i < len(q) and ch == q[i]:
                                i += 1
                        if i == len(q):
                            scored.append((999, c))
                scored.sort(key=lambda x: (x[0], x[1]["label"]))
                self._matches = [c for _, c in scored]

            for c in self._matches:
                line = f"  {c['label']:<48}  {c['key']}"
                self.listbox.insert("end", line)
            if self._matches:
                self.listbox.selection_set(0)

        var.trace_add("write", lambda *_: _populate(var.get()))
        _populate("")

        def _run(event=None):
            sel = self.listbox.curselection()
            if not sel or not self._matches:
                return
            idx = sel[0]
            if idx >= len(self._matches):
                return
            cmd = self._matches[idx]
            self._close()
            ui.root.after(50, cmd["cb"])

        def _close(_=None):
            self._close()

        def _down(_):
            sel = self.listbox.curselection()
            i = (sel[0] + 1) if sel else 0
            i = min(i, self.listbox.size() - 1)
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(i)
            self.listbox.see(i)

        def _up(_):
            sel = self.listbox.curselection()
            i = (sel[0] - 1) if sel else 0
            i = max(i, 0)
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(i)
            self.listbox.see(i)

        self.entry.bind("<Return>", _run)
        self.entry.bind("<Escape>", _close)
        self.entry.bind("<Down>", _down)
        self.entry.bind("<Up>", _up)
        self.listbox.bind("<Double-Button-1>", _run)
        self.listbox.bind("<Return>", _run)

        self.entry.focus_set()
        # click-outside to close
        win.bind("<FocusOut>", lambda _e: self._close())

    def _close(self):
        if self.win:
            try:
                self.win.destroy()
            except Exception:
                pass
            self.win = None


# ─────────────────────────────────────────────────────────────────────────────
#  PREFERENCES DIALOG
# ─────────────────────────────────────────────────────────────────────────────

def _open_preferences(ui):
    from UI.dialog_kit import (themed_toplevel, themed_button, themed_entry,
                               themed_check, section, field_row)

    win = themed_toplevel(ui.root, "Preferences", 520, 560,
                          resizable=(False, True))
    body = win.body

    # General
    g = section(body, "General")
    default_thumb = tk.IntVar(value=int(ui.thumb_size_var.get()))
    thumb_entry = themed_entry(g, textvariable=default_thumb, width=6)
    field_row(g, "Default thumb size", thumb_entry, "pixels (60-180)")

    auto_save = tk.BooleanVar(value=True)
    field_row(g, "Auto-save session",
              themed_check(g, "Restore last session on launch", auto_save))

    animate_drag = tk.BooleanVar(value=True)
    field_row(g, "Drag animation",
              themed_check(g, "Animated reorder transitions", animate_drag))

    # Output
    o = section(body, "Output Defaults")
    compress = ui.__dict__.get("compress_output") or tk.BooleanVar()
    field_row(o, "Compression",
              themed_check(o, "Compress output by default", compress))
    linearize = ui.__dict__.get("linearize") or tk.BooleanVar()
    field_row(o, "Fast web view",
              themed_check(o, "Linearize for web", linearize))

    # Appearance
    a = section(body, "Appearance")
    dark = tk.BooleanVar(value=bool(ui._dark_var.get()))
    field_row(a, "Theme",
              themed_check(a, "Dark theme", dark))

    grid_default = tk.BooleanVar(value=False)
    field_row(a, "Layout",
              themed_check(a, "Start in grid view", grid_default))

    # Save / cancel
    btns = tk.Frame(body, bg=C["panel"])
    btns.pack(fill="x", pady=(16, 0))
    tk.Frame(btns, bg=C["panel"]).pack(side="left", fill="x", expand=True)

    def _save():
        try:
            ui.thumb_size_var.set(int(default_thumb.get()))
            if hasattr(ui, "_on_thumb_size_change"):
                ui._on_thumb_size_change(str(default_thumb.get()))
        except Exception:
            pass
        if bool(dark.get()) != bool(ui._dark_var.get()):
            ui._invoke_toggle_theme()
        if grid_default.get() and not getattr(ui, "_grid_view_on", False):
            ui._toggle_grid_view()
        tx = _get_toaster(ui)
        if tx:
            tx.show("Preferences saved", kind="success")
        win.destroy()

    themed_button(btns, text="Cancel", style="ghost",
                  command=win.destroy).pack(side="left", padx=4)
    themed_button(btns, text="Save", style="accent",
                  command=_save).pack(side="left", padx=4)


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN UI MIXIN
# ─────────────────────────────────────────────────────────────────────────────

class PDFStudioUI:
    # commands for palette are collected here
    _commands: list = None

    # ══════════════════ TITLEBAR ════════════════════════════════════════════
    def _build_titlebar(self):
        ui_font, mono_font, display_font = _fonts()
        self._f_ui = ui_font
        self._f_mono = mono_font
        self._f_display = display_font

        self._commands = []
        self._register_cmd = self._register_cmd_impl

        # Set window icon (task bar / alt-tab) — optional
        self._apply_window_icon()

        bar = tk.Frame(self.root, bg=C["panel"], height=48,
                       highlightthickness=0)
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_propagate(False)
        bar.columnconfigure(1, weight=1)
        self._titlebar = bar

        left = tk.Frame(bar, bg=C["panel"])
        left.grid(row=0, column=0, sticky="w", padx=14)

        # Real brand logo — falls back to a vector draw if asset missing
        logo_img = load_brand_image("pdf_studio_icon_64_t.png",
                                    max_w=30, max_h=30)
        if logo_img is not None:
            logo = tk.Label(left, image=logo_img, bg=C["panel"],
                            bd=0, highlightthickness=0)
            logo._img_ref = logo_img  # prevent GC
            logo.pack(side="left", pady=9, padx=(0, 6))
        else:
            logo = tk.Canvas(left, width=28, height=28, bg=C["panel"],
                             highlightthickness=0, bd=0)
            logo.create_rectangle(0, 0, 28, 28, fill=C["accent"], outline="")
            logo.create_polygon(6, 6, 22, 6, 22, 22, 14, 22, 14, 14, 6, 14,
                                fill=C["fg_on_accent"], outline="")
            logo.pack(side="left", pady=10)

        brand = tk.Frame(left, bg=C["panel"])
        brand.pack(side="left", padx=(8, 0))
        # Wordmark: large, bright "PDF" (brand red) + " Studio" (fg)
        wm_row = tk.Frame(brand, bg=C["panel"])
        wm_row.pack(anchor="w", pady=(6, 6))
        tk.Label(wm_row, text="PDF", bg=C["panel"], fg=C["brand_red"],
                 font=(display_font, 20, "bold")).pack(side="left")
        tk.Label(wm_row, text=" Studio", bg=C["panel"], fg=C["fg"],
                 font=(display_font, 20, "bold")).pack(side="left")

        # Center: breadcrumb
        center = tk.Frame(bar, bg=C["panel"])
        center.grid(row=0, column=1, sticky="")
        self._breadcrumb = tk.Frame(center, bg=C["panel_alt"],
                                    highlightthickness=1,
                                    highlightbackground=C["border"])
        self._breadcrumb.pack(pady=10)
        self._breadcrumb_lbl = tk.Label(
            self._breadcrumb, text="◦  No document opened",
            bg=C["panel_alt"], fg=C["fg_muted"],
            font=(ui_font, 10), padx=16, pady=6)
        self._breadcrumb_lbl.pack(side="left")

        right = tk.Frame(bar, bg=C["panel"])
        right.grid(row=0, column=2, sticky="e", padx=10)

        self._dark_var = tk.BooleanVar(value=True)
        _set_palette(self._dark_var.get())

        _HoverButton(right, glyph="⌕", label="Cmd",
                     command=self._open_command_palette,
                     tooltip="Command palette  (Ctrl+K)",
                     compact=True).pack(side="left", padx=2)
        _HoverButton(right, glyph="☰",
                     command=self._toggle_sidebar,
                     tooltip="Toggle sidebar  (Ctrl+B)",
                     compact=True).pack(side="left", padx=2)
        _HoverButton(right, glyph="▦",
                     command=self._toggle_grid_view,
                     tooltip="Toggle grid view  (Ctrl+G)",
                     compact=True).pack(side="left", padx=2)
        _HoverButton(right, glyph="◐",
                     command=self._invoke_toggle_theme,
                     tooltip="Toggle theme  (Ctrl+T)",
                     compact=True).pack(side="left", padx=2)
        _HoverButton(right, glyph="?",
                     command=self._safe("show_shortcuts"),
                     tooltip="Keyboard shortcuts  (F1)",
                     compact=True).pack(side="left", padx=2)

        tk.Frame(self.root, bg=C["border"], height=1).grid(
            row=0, column=0, sticky="sew")

        # Command palette instance
        self._cmd_palette = _CommandPalette(self)

    def update_titlebar(self, path):
        if not path:
            self._breadcrumb_lbl.config(text="◦  No document opened",
                                        fg=C["fg_muted"])
            return
        parts = []
        p = path
        while True:
            head, tail = os.path.split(p)
            if tail:
                parts.insert(0, tail)
                p = head
            else:
                if head:
                    parts.insert(0, head)
                break
        # Show last 3 segments
        shown = parts[-3:] if len(parts) > 3 else parts
        sep = "  ›  "
        prefix = "… " if len(parts) > 3 else ""
        text = "●  " + prefix + sep.join(shown)
        self._breadcrumb_lbl.config(text=text, fg=C["fg"])
        # Double-click → open containing folder
        def _open_folder(_e, folder=os.path.dirname(path)):
            try:
                if sys.platform == "win32":
                    os.startfile(folder)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", folder])
                else:
                    subprocess.Popen(["xdg-open", folder])
            except Exception:
                pass
        self._breadcrumb_lbl.bind("<Double-Button-1>", _open_folder)

    def _register_cmd_impl(self, label, key, cb, group="misc"):
        self._commands.append(
            {"label": label, "key": key, "cb": cb or (lambda: None),
             "group": group})

    def _apply_window_icon(self):
        """Set the OS window icon (task bar / alt-tab preview)."""
        try:
            if sys.platform == "win32":
                ico = asset_path("pdf_studio.ico")
                if os.path.isfile(ico):
                    self.root.iconbitmap(default=ico)
                    return
            # Cross-platform PhotoImage icon
            png = asset_path("pdf_studio_icon_64.png")
            if os.path.isfile(png):
                img = tk.PhotoImage(file=png)
                self.root.iconphoto(True, img)
                self._root_icon = img   # keep reference
        except Exception:
            pass

    def _open_command_palette(self):
        if not getattr(self._cmd_palette, "_initialized", False):
            self._cmd_palette.register_defaults()
            self._cmd_palette._initialized = True
        self._cmd_palette.open()

    # ══════════════════ MENUBAR ═════════════════════════════════════════════
    def _build_menubar(self):
        menubar = tk.Menu(self.root, tearoff=0,
                          bg=C["panel"], fg=C["fg"],
                          activebackground=C["accent"],
                          activeforeground=C["fg_on_accent"],
                          borderwidth=0)
        self.root.config(menu=menubar)
        self._menubar = menubar

        def mk(label):
            m = tk.Menu(menubar, tearoff=0,
                        bg=C["panel"], fg=C["fg"],
                        activebackground=C["accent"],
                        activeforeground=C["fg_on_accent"],
                        borderwidth=0,
                        font=(self._f_ui, 10))
            menubar.add_cascade(label=label, menu=m)
            return m

        # File
        mf = mk("File")
        mf.add_command(label="Open PDF…", accelerator="Ctrl+O",
                       command=self._safe("browse_file"))
        mf.add_command(label="Merge PDF…",
                       command=self._safe("merge_pdf"))
        mf.add_command(label="Import Images…",
                       command=self._safe("import_images"))
        self._recent_menu = tk.Menu(mf, tearoff=0, bg=C["panel"], fg=C["fg"],
                                    activebackground=C["accent"],
                                    activeforeground=C["fg_on_accent"])
        mf.add_cascade(label="Open Recent", menu=self._recent_menu)
        mf.add_separator()
        mf.add_command(label="Save PDF…", accelerator="Ctrl+S",
                       command=self._safe("save_pdf"))
        mf.add_command(label="Export as Images…",
                       command=self._safe("export_as_images"))
        mf.add_command(label="Extract Included Pages…",
                       command=self._safe("extract_pages"))
        mf.add_separator()
        mf.add_command(label="Batch Process Folder…",
                       command=self._safe("batch_process_dialog"))
        mf.add_command(label="Save Preset…",
                       command=self._safe("save_preset"))
        mf.add_command(label="Load Preset…",
                       command=self._safe("load_preset"))
        mf.add_separator()
        mf.add_command(label="Preferences…", accelerator="Ctrl+,",
                       command=self.show_preferences)
        mf.add_command(label="Exit", command=self.root.destroy)

        # Edit
        me = mk("Edit")
        me.add_command(label="Undo", accelerator="Ctrl+Z",
                       command=self._safe("do_undo"))
        me.add_command(label="Redo", accelerator="Ctrl+Y",
                       command=self._safe("do_redo"))
        me.add_command(label="Undo History…",
                       command=self._show_undo_history)
        me.add_separator()
        me.add_command(label="Select All", accelerator="Ctrl+A",
                       command=self._safe("select_all_pages"))
        me.add_command(label="Deselect All",
                       command=self._safe("deselect_all_pages"))
        me.add_separator()
        me.add_command(label="Duplicate Selected",
                       command=self._safe("duplicate_selected"))
        me.add_command(label="Delete Selected", accelerator="Del",
                       command=self._safe("delete_selected"))
        me.add_command(label="Find & Replace Text…",
                       command=self._safe("find_replace_dialog"))

        # Page
        mp = mk("Page")
        mp.add_command(label="Insert Blank Page",
                       command=self._safe("insert_blank"))
        mp.add_command(label="Reverse Page Order",
                       command=self._safe("reverse_pages"))
        mp.add_separator()
        mp.add_command(label="Rotate All CW",
                       command=lambda: self._safe("rotate_all_pages")(90))
        mp.add_command(label="Rotate All CCW",
                       command=lambda: self._safe("rotate_all_pages")(-90))
        mp.add_command(label="Reset Orientations",
                       command=self._safe("reset_all_orient"))
        mp.add_separator()
        mp.add_command(label="Auto-Crop Whitespace",
                       command=self._safe("auto_crop_dialog"))
        mp.add_command(label="Resize Pages…",
                       command=self._safe("resize_pages_dialog"))
        mp.add_command(label="Crop Margins…",
                       command=self._safe("crop_margins_dialog"))
        mp.add_separator()
        mp.add_command(label="Include All",
                       command=lambda: self._safe("set_all_include")(True))
        mp.add_command(label="Exclude All",
                       command=lambda: self._safe("set_all_include")(False))
        mp.add_command(label="Select Odd Pages",
                       command=lambda: self._safe("select_odd_even")("odd"))
        mp.add_command(label="Select Even Pages",
                       command=lambda: self._safe("select_odd_even")("even"))

        # Tools
        mt = mk("Tools")
        mt.add_command(label="Add Text Annotation…",
                       command=self._safe("add_text_annotation"))
        mt.add_command(label="Add Image Stamp…",
                       command=self._safe("add_stamp_dialog"))
        mt.add_command(label="Signature Tool…",
                       command=self._safe("signature_dialog"))
        mt.add_separator()
        mkup = tk.Menu(mt, tearoff=0, bg=C["panel"], fg=C["fg"],
                       activebackground=C["accent"],
                       activeforeground=C["fg_on_accent"])
        mkup.add_command(label="Highlight Text…",
                         command=lambda: self._safe("markup_dialog")(
                             "highlight"))
        mkup.add_command(label="Underline Text…",
                         command=lambda: self._safe("markup_dialog")(
                             "underline"))
        mkup.add_command(label="Strike-through Text…",
                         command=lambda: self._safe("markup_dialog")(
                             "strikeout"))
        mkup.add_command(label="Sticky Note…",
                         command=lambda: self._safe("markup_dialog")(
                             "note"))
        mt.add_cascade(label="Markups", menu=mkup)
        mt.add_separator()
        mt.add_command(label="Redact Region…",
                       command=self._safe("redact_dialog"))
        mt.add_command(label="Keyword Bulk Redaction…",
                       command=self._safe("keyword_redact_dialog"))
        mt.add_separator()
        mt.add_command(label="Bates Numbering…",
                       command=self._safe("bates_dialog"))
        mt.add_command(label="Header / Footer…",
                       command=self._safe("header_footer_dialog"))
        mt.add_separator()
        mt.add_command(label="Run OCR…",
                       command=self._safe("ocr_dialog"))
        mt.add_command(label="Compare Pages…",
                       command=self._safe("compare_pages_dialog"))
        mt.add_command(label="Measuring Tool…",
                       command=self._safe("measure_dialog"))
        mt.add_command(label="Page Inspector…",
                       command=self._safe("page_inspector_dialog"))
        mt.add_separator()
        mt.add_command(label="Encrypt PDF…",
                       command=self._safe("encryption_dialog"))
        mt.add_command(label="Unlock Password PDF…",
                       command=self._safe("unlock_pdf_dialog"))

        # Pro (new features)
        mpro = mk("Pro")
        mpro.add_command(label="Hyperlink Editor…",
                         command=self._safe("hyperlinks_dialog"))
        mpro.add_command(label="Attachment Extractor…",
                         command=self._safe("attachments_dialog"))
        mpro.add_command(label="Form Fields (Fill / Flatten)…",
                         command=self._safe("form_fields_dialog"))
        mpro.add_command(label="Auto-generate TOC…",
                         command=self._safe("toc_auto_dialog"))
        mpro.add_separator()
        mpro.add_command(label="Add Bookmark…",
                         command=self._safe("add_bookmark_dialog"))
        mpro.add_command(label="Manage Bookmarks…",
                         command=self._safe("bookmarks_dialog"))
        mpro.add_separator()
        mpro.add_command(label="Toggle Split View",
                         command=self.toggle_split_view)

        # Output
        mo = mk("Output")
        mo.add_command(label="Output Options…",
                       command=self._safe("show_output_options"))
        mo.add_command(label="Document Metadata…",
                       command=self._safe("show_metadata_dialog"))

        # View
        mv = mk("View")
        mv.add_command(label="Toggle Theme", accelerator="Ctrl+T",
                       command=self._invoke_toggle_theme)
        mv.add_command(label="Toggle Sidebar", accelerator="Ctrl+B",
                       command=self._toggle_sidebar)
        mv.add_command(label="Toggle Grid View", accelerator="Ctrl+G",
                       command=self._toggle_grid_view)
        mv.add_separator()
        mv.add_command(label="Command Palette", accelerator="Ctrl+K",
                       command=self._open_command_palette)
        mv.add_separator()
        mv.add_command(label="Zoom In", accelerator="Ctrl+=",
                       command=self._safe("_zoom_in"))
        mv.add_command(label="Zoom Out", accelerator="Ctrl+-",
                       command=self._safe("_zoom_out"))
        mv.add_command(label="Fit Preview", accelerator="Ctrl+0",
                       command=self._safe("_zoom_fit"))

        # Help
        mh = mk("Help")
        mh.add_command(label="Keyboard Shortcuts", accelerator="F1",
                       command=self._safe("show_shortcuts"))

    def refresh_recent_menu(self, recent):
        self._recent_menu.delete(0, "end")
        if not recent:
            self._recent_menu.add_command(label="(no recent files)",
                                          state="disabled")
            return
        for path in recent:
            label = os.path.basename(path)
            if len(label) > 50:
                label = label[:47] + "…"
            self._recent_menu.add_command(
                label=f"  {label}",
                command=lambda p=path: self._safe("_open_path")(p))
        self._recent_menu.add_separator()
        self._recent_menu.add_command(
            label="Clear list",
            command=lambda: self.refresh_recent_menu([]))
        # update empty-state panel too
        if hasattr(self, "_update_recent_panel"):
            self._update_recent_panel(recent)

    # ══════════════════ MAIN TOOLBAR ═══════════════════════════════════════
    def _build_toolbar(self):
        tb = tk.Frame(self.root, bg=C["toolbar"])
        tb.grid(row=1, column=0, sticky="ew")
        tb.columnconfigure(0, weight=1)
        self._toolbar = tb

        inner = tk.Frame(tb, bg=C["toolbar"])
        inner.grid(row=0, column=0, sticky="w", padx=10, pady=8)

        self._tb_group_label(inner, "FILE")
        _HoverButton(inner, glyph="◱", label="Open",
                     command=self._safe("browse_file"),
                     tooltip="Open PDF  (Ctrl+O)"
                     ).pack(side="left", padx=2)
        _HoverButton(inner, glyph="+", label="Merge",
                     command=self._safe("merge_pdf"),
                     tooltip="Merge PDF"
                     ).pack(side="left", padx=2)
        _HoverButton(inner, glyph="⌸", label="Images",
                     command=self._safe("import_images"),
                     tooltip="Images as pages"
                     ).pack(side="left", padx=2)
        _HoverButton(inner, glyph="▼", label="Save",
                     command=self._safe("save_pdf"), style="accent",
                     tooltip="Save PDF  (Ctrl+S)"
                     ).pack(side="left", padx=2)
        _divider(inner)

        self._tb_group_label(inner, "HISTORY")
        self._undo_btn = _HoverButton(
            inner, glyph="↶", label="Undo",
            command=self._safe("do_undo"),
            tooltip="Undo  (Ctrl+Z)")
        self._undo_btn.pack(side="left", padx=2)
        self._undo_btn.set_enabled(False)
        self._redo_btn = _HoverButton(
            inner, glyph="↷", label="Redo",
            command=self._safe("do_redo"),
            tooltip="Redo  (Ctrl+Y)")
        self._redo_btn.pack(side="left", padx=2)
        self._redo_btn.set_enabled(False)
        _HoverButton(inner, glyph="⧖",
                     command=self._show_undo_history,
                     tooltip="Undo history",
                     compact=True).pack(side="left", padx=2)
        _divider(inner)

        self._tb_group_label(inner, "PAGES")
        _HoverButton(inner, glyph="◻", label="Blank",
                     command=self._safe("insert_blank"),
                     tooltip="Insert blank page").pack(side="left", padx=2)
        _HoverButton(inner, glyph="⎘", label="Duplicate",
                     command=self._safe("duplicate_selected"),
                     tooltip="Duplicate selected").pack(side="left", padx=2)
        _HoverButton(inner, glyph="⌫", label="Delete",
                     command=self._safe("delete_selected"), style="danger",
                     tooltip="Delete selected  (Del)"
                     ).pack(side="left", padx=2)
        _HoverButton(inner, glyph="⇅", label="Reverse",
                     command=self._safe("reverse_pages"),
                     tooltip="Reverse order").pack(side="left", padx=2)
        _divider(inner)

        self._tb_group_label(inner, "ROTATE")
        _HoverButton(inner, glyph="↺",
                     command=lambda: self._safe("rotate_all_pages")(-90),
                     tooltip="Rotate all CCW",
                     compact=True).pack(side="left", padx=2)
        _HoverButton(inner, glyph="↻",
                     command=lambda: self._safe("rotate_all_pages")(90),
                     tooltip="Rotate all CW",
                     compact=True).pack(side="left", padx=2)
        _HoverButton(inner, glyph="⟲", label="Reset",
                     command=self._safe("reset_all_orient"),
                     tooltip="Reset rotations",
                     compact=True).pack(side="left", padx=2)
        _divider(inner)

        self._tb_group_label(inner, "TOOLS")
        _HoverButton(inner, glyph="✎", label="Annotate",
                     command=self._safe("add_text_annotation"),
                     tooltip="Add annotation"
                     ).pack(side="left", padx=2)
        _HoverButton(inner, glyph="▧", label="Redact",
                     command=self._safe("redact_dialog"),
                     tooltip="Redact region").pack(side="left", padx=2)
        _HoverButton(inner, glyph="✒", label="Sign",
                     command=self._safe("signature_dialog"),
                     tooltip="Signature tool").pack(side="left", padx=2)
        _HoverButton(inner, glyph="❖", label="Watermark",
                     command=self._safe("show_output_options"),
                     tooltip="Watermark / output"
                     ).pack(side="left", padx=2)
        _HoverButton(inner, glyph="◉", label="OCR",
                     command=self._safe("ocr_dialog"),
                     tooltip="Run OCR").pack(side="left", padx=2)
        _HoverButton(inner, glyph="⚿", label="Encrypt",
                     command=self._safe("encryption_dialog"),
                     tooltip="Password protect").pack(side="left", padx=2)
        _HoverButton(inner, glyph="⇆", label="Compare",
                     command=self._safe("compare_pages_dialog"),
                     tooltip="Compare pages").pack(side="left", padx=2)
        _divider(inner)

        self._tb_group_label(inner, "PRO")
        _HoverButton(inner, glyph="№", label="Bates",
                     command=self._safe("bates_dialog"),
                     tooltip="Bates numbering"
                     ).pack(side="left", padx=2)
        _HoverButton(inner, glyph="∞", label="Links",
                     command=self._safe("hyperlinks_dialog"),
                     tooltip="Hyperlink editor"
                     ).pack(side="left", padx=2)
        _HoverButton(inner, glyph="⏚", label="Forms",
                     command=self._safe("form_fields_dialog"),
                     tooltip="Form fields").pack(side="left", padx=2)
        _divider(inner)

        self._tb_group_label(inner, "BATCH")
        _HoverButton(inner, glyph="⚙",
                     command=self._safe("show_output_options"),
                     tooltip="Output options",
                     compact=True).pack(side="left", padx=2)
        _HoverButton(inner, glyph="▶", label="Batch",
                     command=self._safe("batch_process_dialog"),
                     tooltip="Batch process folder"
                     ).pack(side="left", padx=2)

        tk.Frame(tb, bg=C["border"], height=1).grid(
            row=1, column=0, sticky="ew")

    def _tb_group_label(self, parent, text):
        # Group labels removed for a cleaner, more modern toolbar.
        # Dividers alone separate logical groups.
        return None

    # ══════════════════ SUB-TOOLBAR ═════════════════════════════════════════
    def _build_sub_toolbar_into(self, parent):
        bar = tk.Frame(parent, bg=C["panel_alt"], height=52)
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_propagate(False)
        bar.columnconfigure(3, weight=1)

        sf = tk.Frame(bar, bg=C["input_bg"],
                      highlightthickness=1,
                      highlightbackground=C["input_border"])
        sf.grid(row=0, column=0, padx=(14, 6), pady=10, sticky="w")
        tk.Label(sf, text="⌕", bg=C["input_bg"], fg=C["fg_muted"],
                 font=(self._f_ui, 12), padx=8).pack(side="left")
        e = tk.Entry(sf, textvariable=self.search_var, bd=0, bg=C["input_bg"],
                     fg=C["fg"], insertbackground=C["accent"],
                     font=(self._f_ui, 10), width=22,
                     highlightthickness=0, relief="flat")
        e.pack(side="left", ipady=6, padx=(0, 10))
        _Tooltip(e, "Filter pages — Ctrl+F")

        rngf = tk.Frame(bar, bg=C["panel_alt"])
        rngf.grid(row=0, column=1, padx=(8, 6), pady=10, sticky="w")
        tk.Label(rngf, text="RANGE", bg=C["panel_alt"], fg=C["fg_muted"],
                 font=(self._f_ui, 8, "bold")).pack(side="left", padx=(0, 6))
        rf = tk.Frame(rngf, bg=C["input_bg"],
                      highlightthickness=1,
                      highlightbackground=C["input_border"])
        rf.pack(side="left")
        self.range_entry = tk.Entry(
            rf, textvariable=self.range_var, bd=0, bg=C["input_bg"],
            fg=C["fg"], insertbackground=C["accent"],
            font=(self._f_mono, 10), width=14,
            highlightthickness=0, relief="flat")
        self.range_entry.pack(side="left", ipady=6, padx=8)
        _Tooltip(self.range_entry, "e.g.  1-5, 7, 10-12")
        _HoverButton(rngf, glyph="✓",
                     command=lambda: self._safe("_apply_range")(True),
                     tooltip="Include range", style="success",
                     compact=True).pack(side="left", padx=2)
        _HoverButton(rngf, glyph="✕",
                     command=lambda: self._safe("_apply_range")(False),
                     tooltip="Exclude range", style="danger",
                     compact=True).pack(side="left", padx=2)
        _HoverButton(rngf, glyph="⎘",
                     command=self._safe("duplicate_range"),
                     tooltip="Duplicate range",
                     compact=True).pack(side="left", padx=2)
        _HoverButton(rngf, glyph="⌫",
                     command=self._safe("delete_range"),
                     tooltip="Delete range",
                     compact=True).pack(side="left", padx=2)
        _HoverButton(rngf, glyph="↻",
                     command=self._safe("orient_range_dialog"),
                     tooltip="Rotate range",
                     compact=True).pack(side="left", padx=2)

        oe = tk.Frame(bar, bg=C["panel_alt"])
        oe.grid(row=0, column=2, padx=(6, 6), pady=10, sticky="w")
        for label, cmd in [
            ("Odd", lambda: self._safe("select_odd_even")("odd")),
            ("Even", lambda: self._safe("select_odd_even")("even")),
            ("All", lambda: self._safe("set_all_include")(True)),
            ("None", lambda: self._safe("set_all_include")(False)),
        ]:
            _HoverButton(oe, label=label, command=cmd,
                         compact=True).pack(side="left", padx=2)

        tk.Frame(bar, bg=C["panel_alt"]).grid(row=0, column=3, sticky="ew")

        right = tk.Frame(bar, bg=C["panel_alt"])
        right.grid(row=0, column=4, padx=(6, 14), pady=10, sticky="e")
        tk.Label(right, text="GO TO", bg=C["panel_alt"], fg=C["fg_muted"],
                 font=(self._f_ui, 8, "bold")).pack(side="left", padx=(0, 6))
        gf = tk.Frame(right, bg=C["input_bg"],
                      highlightthickness=1,
                      highlightbackground=C["input_border"])
        gf.pack(side="left", padx=(0, 10))
        ge = tk.Entry(gf, textvariable=self.goto_var, bd=0,
                      bg=C["input_bg"], fg=C["fg"],
                      insertbackground=C["accent"],
                      font=(self._f_mono, 10), width=5,
                      highlightthickness=0, relief="flat", justify="center")
        ge.pack(side="left", ipady=6, padx=6)
        ge.bind("<Return>", lambda _e: self._safe("_goto_page")())
        _HoverButton(gf, glyph="→",
                     command=self._safe("_goto_page"),
                     tooltip="Jump to page",
                     compact=True).pack(side="left", padx=(0, 2))

        tk.Label(right, text="SIZE", bg=C["panel_alt"], fg=C["fg_muted"],
                 font=(self._f_ui, 8, "bold")).pack(side="left", padx=(6, 6))
        self._thumb_scale = tk.Scale(
            right, from_=60, to=180, orient="horizontal",
            variable=self.thumb_size_var, showvalue=False, length=90,
            bg=C["panel_alt"], troughcolor=C["input_bg"],
            fg=C["fg"], activebackground=C["accent"],
            highlightthickness=0, bd=0, sliderlength=14, sliderrelief="flat",
            command=lambda v: self._safe("_on_thumb_size_change")(v))
        self._thumb_scale.pack(side="left")

        tk.Frame(parent, bg=C["border"], height=1).grid(
            row=0, column=0, sticky="sew")

    # ══════════════════ TTK STYLE ═══════════════════════════════════════════
    def _apply_ttk_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TCombobox", fieldbackground=C["elevated"],
                        background=C["elevated"], foreground=C["fg"],
                        borderwidth=0, arrowsize=12,
                        selectbackground=C["accent"],
                        selectforeground=C["fg_on_accent"])
        style.map("TCombobox",
                  fieldbackground=[("readonly", C["elevated"])],
                  background=[("readonly", C["elevated"])],
                  foreground=[("readonly", C["fg"])])
        style.configure("Studio.Horizontal.TProgressbar",
                        troughcolor=C["panel_alt"],
                        background=C["accent"],
                        bordercolor=C["panel_alt"],
                        lightcolor=C["accent"],
                        darkcolor=C["accent_hover"])
        style.configure("TSeparator", background=C["border"])

    # ══════════════════ LIST PANEL ═════════════════════════════════════════
    def _build_list_panel(self):
        # Outer = sidebar + list
        outer = tk.Frame(self.pane, bg=C["panel"])
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)
        self.pane.add(outer, stretch="always", minsize=420, width=620)

        # Sidebar (bookmarks / outline)
        self._sidebar = tk.Frame(outer, bg=C["panel_alt"], width=220)
        self._sidebar.grid(row=0, column=0, sticky="ns")
        self._sidebar.grid_propagate(False)
        self._sidebar_open = True
        self._build_sidebar(self._sidebar)

        # Divider
        tk.Frame(outer, bg=C["border"], width=1).grid(
            row=0, column=0, sticky="nse")

        # Body
        wrap = tk.Frame(outer, bg=C["panel"])
        wrap.grid(row=0, column=1, sticky="nsew")
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(2, weight=1)

        head = tk.Frame(wrap, bg=C["panel"], height=38)
        head.grid(row=0, column=0, sticky="ew")
        head.grid_propagate(False)
        tk.Label(head, text="PAGES", bg=C["panel"], fg=C["fg_dim"],
                 font=(self._f_display, 9, "bold")
                 ).pack(side="left", padx=16, pady=10)
        self._count_lbl = tk.Label(head, text="0 pages", bg=C["panel"],
                                   fg=C["fg_muted"], font=(self._f_mono, 9))
        self._count_lbl.pack(side="left", pady=10)

        right_hdr = tk.Frame(head, bg=C["panel"])
        right_hdr.pack(side="right", padx=10)
        _HoverButton(right_hdr, glyph="▤",
                     command=lambda: self._set_grid_view(False),
                     tooltip="List view",
                     compact=True).pack(side="left", padx=1)
        _HoverButton(right_hdr, glyph="▦",
                     command=lambda: self._set_grid_view(True),
                     tooltip="Grid view  (Ctrl+G)",
                     compact=True).pack(side="left", padx=1)
        tk.Frame(right_hdr, bg=C["border"], width=1
                 ).pack(side="left", fill="y", padx=4, pady=6)
        _HoverButton(right_hdr, glyph="☑",
                     command=self._safe("select_all_pages"),
                     tooltip="Select all  (Ctrl+A)",
                     compact=True).pack(side="left", padx=1)
        _HoverButton(right_hdr, glyph="☐",
                     command=self._safe("deselect_all_pages"),
                     tooltip="Deselect all",
                     compact=True).pack(side="left", padx=1)

        tk.Frame(wrap, bg=C["border"], height=1).grid(
            row=1, column=0, sticky="ew")

        # Scrollable body
        body = tk.Frame(wrap, bg=C["panel"])
        body.grid(row=2, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        self.list_canvas = tk.Canvas(
            body, bg=C["panel"], highlightthickness=0, bd=0)
        self.list_canvas.grid(row=0, column=0, sticky="nsew")

        # Custom scrollbar
        self._list_scrollbar = _CanvasScrollbar(body, self.list_canvas,
                                                width=10)
        self._list_scrollbar.grid(row=0, column=1, sticky="ns")
        self.list_canvas.configure(yscrollcommand=self._list_scrollbar.set)

        self.rows_frame = tk.Frame(self.list_canvas, bg=C["panel"])
        self._rows_win = self.list_canvas.create_window(
            (0, 0), window=self.rows_frame, anchor="nw")

        def _resize_rows(event):
            self.list_canvas.itemconfigure(self._rows_win, width=event.width)
        self.list_canvas.bind("<Configure>", _resize_rows)

        def _wheel(e):
            delta = -1 if (getattr(e, "delta", 0) > 0 or
                           getattr(e, "num", 0) == 4) else 1
            self.list_canvas.yview_scroll(delta, "units")

        self.list_canvas.bind("<MouseWheel>", _wheel)
        self.list_canvas.bind("<Button-4>", _wheel)
        self.list_canvas.bind("<Button-5>", _wheel)

        # Empty state
        self._empty_hint = tk.Frame(self.rows_frame, bg=C["panel"])
        icon = tk.Canvas(self._empty_hint, width=96, height=96,
                         bg=C["panel"], highlightthickness=0)
        icon.pack(pady=(40, 10))
        icon.create_rectangle(20, 16, 76, 86, fill=C["elevated"],
                              outline=C["border_strong"], width=2)
        icon.create_polygon(56, 16, 76, 36, 76, 36, 56, 36,
                            fill=C["accent_dim"], outline="")
        for ln in range(5):
            icon.create_line(30, 46 + ln * 8, 66, 46 + ln * 8,
                             fill=C["border_strong"], width=1)
        tk.Label(self._empty_hint, text="Drop a PDF to begin",
                 bg=C["panel"], fg=C["fg"],
                 font=(self._f_display, 15, "bold")).pack()
        tk.Label(self._empty_hint, text="or press  Ctrl+O  to open one",
                 bg=C["panel"], fg=C["fg_muted"],
                 font=(self._f_ui, 10)).pack(pady=(4, 2))
        btn_row = tk.Frame(self._empty_hint, bg=C["panel"])
        btn_row.pack(pady=18)
        _HoverButton(btn_row, label="Open PDF", glyph="◱",
                     command=self._safe("browse_file"),
                     style="accent").pack(side="left", padx=4)
        _HoverButton(btn_row, label="Merge PDFs", glyph="+",
                     command=self._safe("merge_pdf"),
                     style="solid").pack(side="left", padx=4)
        _HoverButton(btn_row, label="Command palette  Ctrl+K", glyph="⌕",
                     command=self._open_command_palette,
                     style="ghost").pack(side="left", padx=4)

        # Recent-files cards
        self._recent_panel = tk.Frame(self._empty_hint, bg=C["panel"])
        self._recent_panel.pack(pady=(12, 0), fill="x", padx=28)
        self._empty_hint.pack(fill="x", pady=40)

        # Drag-and-drop support
        self._init_drag_drop()

        # Drag manager
        self._drag_mgr = _DragManager(self)

        # Keyboard focus row
        self._focus_row = -1

    def _update_recent_panel(self, recent):
        if not hasattr(self, "_recent_panel"):
            return
        for w in list(self._recent_panel.winfo_children()):
            w.destroy()
        if not recent:
            return
        tk.Label(self._recent_panel, text="RECENT",
                 bg=C["panel"], fg=C["fg_dim"],
                 font=(self._f_ui, 8, "bold")
                 ).pack(anchor="w", pady=(0, 6))
        for path in recent[:5]:
            card = tk.Frame(
                self._recent_panel, bg=C["elevated"],
                highlightthickness=1, highlightbackground=C["border"],
                cursor="hand2")
            card.pack(fill="x", pady=2)
            tk.Label(card, text="◱", bg=C["elevated"], fg=C["accent"],
                     font=(self._f_ui, 14), padx=12, pady=8).pack(side="left")
            col = tk.Frame(card, bg=C["elevated"])
            col.pack(side="left", fill="x", expand=True, padx=(0, 12))
            tk.Label(col, text=os.path.basename(path), bg=C["elevated"],
                     fg=C["fg"], font=(self._f_ui, 10, "bold"), anchor="w"
                     ).pack(fill="x")
            tk.Label(col, text=os.path.dirname(path)[-50:], bg=C["elevated"],
                     fg=C["fg_dim"], font=(self._f_ui, 8), anchor="w"
                     ).pack(fill="x")
            for w in (card, col) + tuple(col.winfo_children()):
                w.bind("<Button-1>",
                       lambda _e, p=path: self._safe("_open_path")(p))

    # ── drag-and-drop ──────────────────────────────────────────────────
    def _init_drag_drop(self):
        try:
            # tkinterdnd2 if available
            from tkinterdnd2 import DND_FILES  # noqa: F401
            self.root.drop_target_register("DND_Files")

            def _on_drop(event):
                path = event.data.strip().strip("{}").strip('"')
                if path.lower().endswith(".pdf"):
                    self._safe("_open_path")(path)
            self.root.dnd_bind("<<Drop>>", _on_drop)
        except Exception:
            # graceful fallback — nothing breaks without the library
            pass

    # ── sidebar ────────────────────────────────────────────────────────
    def _build_sidebar(self, host):
        head = tk.Frame(host, bg=C["panel_alt"])
        head.pack(fill="x", padx=12, pady=(12, 4))
        tk.Label(head, text="OUTLINE", bg=C["panel_alt"], fg=C["fg_dim"],
                 font=(self._f_display, 9, "bold")).pack(side="left")
        _HoverButton(head, glyph="+",
                     command=self._safe("add_bookmark_dialog"),
                     tooltip="Add bookmark",
                     compact=True).pack(side="right")

        self._bookmark_list_frame = tk.Frame(host, bg=C["panel_alt"])
        self._bookmark_list_frame.pack(fill="both", expand=True, padx=8,
                                       pady=(4, 8))
        self._bookmark_empty = tk.Label(
            self._bookmark_list_frame,
            text="No bookmarks yet.\nAdd one from the Pro menu.",
            bg=C["panel_alt"], fg=C["fg_dim"],
            font=(self._f_ui, 9), justify="center")
        self._bookmark_empty.pack(pady=(20, 0))

    def refresh_bookmarks_sidebar(self):
        bms = getattr(self, "_bookmarks", [])
        for w in list(self._bookmark_list_frame.winfo_children()):
            if w is self._bookmark_empty:
                continue
            w.destroy()
        if not bms:
            self._bookmark_empty.pack(pady=(20, 0))
            return
        self._bookmark_empty.pack_forget()
        for bm in bms:
            card = tk.Frame(self._bookmark_list_frame, bg=C["elevated"],
                            highlightthickness=1,
                            highlightbackground=C["border"], cursor="hand2")
            card.pack(fill="x", pady=2)
            tk.Label(card, text=f"  p.{bm['page']+1:<4}",
                     bg=C["elevated"], fg=C["accent2"],
                     font=(self._f_mono, 9, "bold"),
                     padx=6, pady=6).pack(side="left")
            tk.Label(card, text=bm.get("title", "(untitled)"),
                     bg=C["elevated"], fg=C["fg"], anchor="w",
                     font=(self._f_ui, 10)).pack(side="left", fill="x",
                                                 expand=True)
            for w in (card,) + tuple(card.winfo_children()):
                w.bind("<Button-1>",
                       lambda _e, p=bm["page"]: self._goto_bookmark(p))

    def _goto_bookmark(self, idx):
        if hasattr(self, "pages") and 0 <= idx < len(self.pages):
            self._preview_index = idx
            if hasattr(self, "_render_preview"):
                self._render_preview()
            if hasattr(self, "_scroll_to_row"):
                self._scroll_to_row(idx)

    def _toggle_sidebar(self):
        if not hasattr(self, "_sidebar"):
            return
        self._sidebar_open = not getattr(self, "_sidebar_open", True)
        if self._sidebar_open:
            self._sidebar.grid()
        else:
            self._sidebar.grid_remove()

    # ── grid view ──────────────────────────────────────────────────────
    def _toggle_grid_view(self):
        self._set_grid_view(not getattr(self, "_grid_view_on", False))

    def _set_grid_view(self, on):
        self._grid_view_on = on
        if hasattr(self, "_rebuild_rows"):
            self._rebuild_rows()

    # ══════════════════ PREVIEW PANEL ══════════════════════════════════════
    def _build_preview_panel(self):
        wrap = tk.Frame(self.pane, bg=C["preview_bg"])
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(1, weight=1)
        self.pane.add(wrap, stretch="always", minsize=360, width=720)

        ptb = tk.Frame(wrap, bg=C["panel_alt"], height=40)
        ptb.grid(row=0, column=0, sticky="ew")
        ptb.grid_propagate(False)
        tk.Label(ptb, text="PREVIEW", bg=C["panel_alt"], fg=C["fg_dim"],
                 font=(self._f_display, 9, "bold")
                 ).pack(side="left", padx=16, pady=10)
        tk.Label(ptb, textvariable=self.preview_info_var,
                 bg=C["panel_alt"], fg=C["fg"],
                 font=(self._f_ui, 10)).pack(side="left", pady=10)

        right = tk.Frame(ptb, bg=C["panel_alt"])
        right.pack(side="right", padx=10)
        _HoverButton(right, glyph="◀", command=self._safe("_preview_prev"),
                     tooltip="Previous  (←)",
                     compact=True).pack(side="left", padx=2)
        _HoverButton(right, glyph="▶", command=self._safe("_preview_next"),
                     tooltip="Next  (→)",
                     compact=True).pack(side="left", padx=2)
        _divider(right, "vertical", 6)
        _HoverButton(right, glyph="−", command=self._safe("_zoom_out"),
                     tooltip="Zoom out",
                     compact=True).pack(side="left", padx=2)
        self.zoom_lbl = tk.Label(
            right, textvariable=self.zoom_var, bg=C["elevated"], fg=C["fg"],
            font=(self._f_mono, 9, "bold"), padx=10, pady=4,
            highlightthickness=1, highlightbackground=C["border"])
        self.zoom_lbl.pack(side="left", padx=2)
        _HoverButton(right, glyph="+", command=self._safe("_zoom_in"),
                     tooltip="Zoom in",
                     compact=True).pack(side="left", padx=2)
        _HoverButton(right, glyph="⊡", command=self._safe("_zoom_fit"),
                     tooltip="Fit",
                     compact=True).pack(side="left", padx=2)
        _divider(right, "vertical", 6)
        _HoverButton(right, glyph="⎹⎸",
                     command=self.toggle_split_view,
                     tooltip="Split view",
                     compact=True).pack(side="left", padx=2)

        tk.Frame(wrap, bg=C["border"], height=1).grid(
            row=0, column=0, sticky="sew")

        # Canvas (split container)
        self._preview_container = tk.Frame(wrap, bg=C["preview_bg"])
        self._preview_container.grid(row=1, column=0, sticky="nsew")
        self._preview_container.columnconfigure(0, weight=1)
        self._preview_container.rowconfigure(0, weight=1)

        self.preview_canvas = tk.Canvas(
            self._preview_container, bg=C["preview_bg"],
            highlightthickness=0, bd=0)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")

        # Second canvas hidden until split
        self._preview_canvas_b = None
        self._split_on = False

        self.preview_canvas.bind("<Configure>",
                                 self._safe("_on_preview_resize"))
        self.preview_canvas.bind("<Button-1>",
                                 self._safe("_on_preview_click"))
        self.preview_canvas.bind("<B1-Motion>",
                                 self._safe("_on_preview_drag"))
        self.preview_canvas.bind("<ButtonRelease-1>",
                                 self._safe("_on_preview_release"))
        self.preview_canvas.bind("<MouseWheel>",
                                 self._safe("_on_preview_scroll"))
        self.preview_canvas.bind("<Button-4>",
                                 lambda e: self._safe("_preview_prev")())
        self.preview_canvas.bind("<Button-5>",
                                 lambda e: self._safe("_preview_next")())
        self.preview_canvas.bind("<Control-MouseWheel>",
                                 self._safe("_on_preview_ctrl_scroll"))

        foot = tk.Frame(wrap, bg=C["panel_alt"], height=28)
        foot.grid(row=2, column=0, sticky="ew")
        foot.grid_propagate(False)
        self.prev_foot_lbl = tk.Label(
            foot, text="Click a thumbnail to preview",
            bg=C["panel_alt"], fg=C["fg_muted"], font=(self._f_ui, 9))
        self.prev_foot_lbl.pack(side="left", padx=16, pady=6)

    def toggle_split_view(self):
        if not hasattr(self, "_preview_container"):
            return
        self._split_on = not self._split_on
        if self._split_on:
            self._preview_container.columnconfigure(1, weight=1)
            divider = tk.Frame(self._preview_container, bg=C["border"],
                               width=1)
            divider.grid(row=0, column=1, sticky="ns")
            self._split_divider = divider
            self._preview_canvas_b = tk.Canvas(
                self._preview_container, bg=C["preview_bg"],
                highlightthickness=0, bd=0)
            self._preview_canvas_b.grid(row=0, column=2, sticky="nsew")
            self._preview_container.columnconfigure(2, weight=1)
            # Render a dummy secondary preview
            self._render_split_secondary()
            tx = _get_toaster(self)
            if tx:
                tx.show("Split view enabled — next page on right",
                        kind="info")
        else:
            for c in (getattr(self, "_split_divider", None),
                      self._preview_canvas_b):
                if c:
                    c.destroy()
            self._preview_canvas_b = None
            self._preview_container.columnconfigure(1, weight=0)
            self._preview_container.columnconfigure(2, weight=0)

    def _render_split_secondary(self):
        c = self._preview_canvas_b
        if not c:
            return
        c.delete("all")
        c.update_idletasks()
        cw, ch = c.winfo_width(), c.winfo_height()
        c.create_rectangle(0, 0, cw, ch, fill=C["preview_bg"], outline="")
        c.create_text(cw // 2, ch // 2 - 10,
                      text="SPLIT PREVIEW",
                      fill=C["fg_dim"],
                      font=(self._f_display, 14, "bold"))
        c.create_text(cw // 2, ch // 2 + 14,
                      text="(shows next page of primary preview)",
                      fill=C["fg_dim"],
                      font=(self._f_ui, 9))

    # ══════════════════ STATUS BAR ══════════════════════════════════════════
    def _build_statusbar(self):
        bar = tk.Frame(self.root, bg=C["statusbar"], height=28)
        bar.grid(row=3, column=0, sticky="ew")
        bar.grid_propagate(False)
        bar.columnconfigure(1, weight=1)
        self._statusbar = bar
        tk.Frame(bar, bg=C["accent"], width=3).grid(row=0, column=0,
                                                    sticky="ns")
        tk.Label(bar, textvariable=self.status_var, bg=C["statusbar"],
                 fg=C["fg"], font=(self._f_ui, 9), anchor="w", padx=12
                 ).grid(row=0, column=1, sticky="ew")
        self.progress = ttk.Progressbar(
            bar, mode="indeterminate", length=130,
            style="Studio.Horizontal.TProgressbar")
        self.progress.grid(row=0, column=2, padx=6, pady=6)
        self.progress.grid_remove()
        tk.Label(bar, textvariable=self.autosave_var, bg=C["statusbar"],
                 fg=C["accent2"], font=(self._f_mono, 9), padx=12
                 ).grid(row=0, column=3)
        tk.Label(bar, text="PDF STUDIO", bg=C["statusbar"],
                 fg=C["fg_dim"], font=(self._f_mono, 8, "bold"), padx=14
                 ).grid(row=0, column=4)

    # ══════════════════ KEY BINDINGS ════════════════════════════════════════
    def _bind_global_keys(self):
        r = self.root
        r.bind("<Control-o>", lambda _e: self._safe("browse_file")())
        r.bind("<Control-s>", lambda _e: self._safe("save_pdf")())
        r.bind("<Control-z>", lambda _e: self._safe("do_undo")())
        r.bind("<Control-y>", lambda _e: self._safe("do_redo")())
        r.bind("<Control-a>", lambda _e: self._safe("select_all_pages")())
        r.bind("<Control-t>", lambda _e: self._invoke_toggle_theme())
        r.bind("<Control-b>", lambda _e: self._toggle_sidebar())
        r.bind("<Control-g>", lambda _e: self._toggle_grid_view())
        r.bind("<Control-k>", lambda _e: self._open_command_palette())
        r.bind("<Control-K>",
               lambda _e: self._open_command_palette())  # shift too
        r.bind("<Control-p>",
               lambda _e: self._open_command_palette())  # some users use Ctrl+P
        r.bind("<Control-comma>", lambda _e: self.show_preferences())
        r.bind("<Delete>",    lambda _e: self._safe("delete_selected")())
        r.bind("<Control-equal>", lambda _e: self._safe("_zoom_in")())
        r.bind("<Control-plus>",  lambda _e: self._safe("_zoom_in")())
        r.bind("<Control-minus>", lambda _e: self._safe("_zoom_out")())
        r.bind("<Control-0>",     lambda _e: self._safe("_zoom_fit")())
        r.bind("<F1>",    lambda _e: self._safe("show_shortcuts")())

        # Keyboard navigation of rows
        r.bind("<Up>",    lambda _e: self._kb_nav(-1))
        r.bind("<Down>",  lambda _e: self._kb_nav(+1))
        r.bind("<Home>",  lambda _e: self._kb_nav_to(0))
        r.bind("<End>",   lambda _e: self._kb_nav_to(-1))
        r.bind("<Prior>", lambda _e: self._kb_nav(-5))
        r.bind("<Next>",  lambda _e: self._kb_nav(+5))
        r.bind("<Left>",  lambda _e: self._safe("_preview_prev")())
        r.bind("<Right>", lambda _e: self._safe("_preview_next")())
        r.bind("<space>", lambda _e: self._kb_toggle_include())
        r.bind("<Return>", lambda _e: self._kb_preview())

    def _kb_nav(self, delta):
        if not getattr(self, "pages", None):
            return
        cur = getattr(self, "_preview_index", -1)
        ni = max(0, min(len(self.pages) - 1, cur + delta))
        self._preview_index = ni
        if hasattr(self, "_render_preview"):
            self._render_preview()
        if hasattr(self, "_scroll_to_row"):
            self._scroll_to_row(ni)
        if hasattr(self, "_rebuild_rows"):
            self._rebuild_rows()

    def _kb_nav_to(self, idx):
        if not getattr(self, "pages", None):
            return
        if idx < 0:
            idx = len(self.pages) - 1
        self._kb_nav(idx - self._preview_index)

    def _kb_toggle_include(self):
        idx = getattr(self, "_preview_index", -1)
        if 0 <= idx < len(getattr(self, "pages", [])):
            rec = self.pages[idx]
            rec.included.set(not rec.included.get())
            if hasattr(self, "_rebuild_rows"):
                self._rebuild_rows()
            tx = _get_toaster(self)
            if tx:
                state = "included" if rec.included.get() else "excluded"
                tx.show(f"Page {idx + 1} {state}", kind="info",
                        duration=1800)

    def _kb_preview(self):
        idx = getattr(self, "_preview_index", -1)
        if 0 <= idx < len(getattr(self, "pages", [])):
            if hasattr(self, "_render_preview"):
                self._render_preview()

    # ══════════════════ UNDO/REDO LABELS ═══════════════════════════════════
    def update_undo_redo(self, can_undo, can_redo, undo_desc, redo_desc):
        self._undo_btn.set_enabled(can_undo)
        self._redo_btn.set_enabled(can_redo)

    def _show_undo_history(self):
        stack = getattr(self, "undo_stack", None)
        if not stack or (not stack._undo and not stack._redo):
            tx = _get_toaster(self)
            if tx:
                tx.show("Nothing to show yet", kind="info")
            return
        from UI.dialog_kit import themed_toplevel
        win = themed_toplevel(self.root, "Undo history", 380, 360,
                              resizable=(False, True))
        body = win.body
        tk.Label(body, text="Past actions (newest on top)",
                 bg=C["panel"], fg=C["fg_muted"],
                 font=(self._f_ui, 9)).pack(anchor="w")
        lb = tk.Listbox(body, bd=0, bg=C["elevated"], fg=C["fg"],
                        selectbackground=C["accent"],
                        selectforeground=C["fg_on_accent"],
                        activestyle="none", font=(self._f_ui, 10),
                        highlightthickness=1,
                        highlightbackground=C["border"], relief="flat")
        lb.pack(fill="both", expand=True, pady=8)
        for d, _ in reversed(stack._undo):
            lb.insert("end", f"  ↶ {d}")
        if stack._redo:
            lb.insert("end", "  ────")
        for d, _ in stack._redo:
            lb.insert("end", f"  ↷ {d}")

    # ══════════════════ PREFERENCES ═════════════════════════════════════════
    def show_preferences(self):
        _open_preferences(self)

    # ══════════════════ PAGE ROW RENDER ════════════════════════════════════
    def clear_page_rows(self):
        for w in list(self.rows_frame.winfo_children()):
            if w is self._empty_hint:
                continue
            w.destroy()
        if hasattr(self, "_empty_hint"):
            self._empty_hint.pack_forget()
        if hasattr(self, "_count_lbl") and getattr(self, "pages", None):
            try:
                n_total = len(self.pages)
                n_in = sum(1 for r in self.pages if r.included.get())
                self._count_lbl.config(text=f"{n_in}/{n_total} included")
            except Exception:
                pass

    def _show_empty_if_needed(self):
        if not getattr(self, "pages", None):
            self._empty_hint.pack(fill="x", pady=40)

    def add_page_row(self, *, index, page_num, is_included, orig_orient,
                     rotation_deg, is_previewed, is_selected, thumb_img,
                     on_thumb_click, on_rotate_cw, on_rotate_ccw,
                     on_duplicate, on_delete, on_move_up, on_move_down,
                     on_annotate, on_redact, on_include_toggle,
                     on_right_click, on_row_click, on_row_ctrl_click,
                     on_row_shift_click, on_drag_start, on_drag_motion,
                     on_drag_release):
        if getattr(self, "_grid_view_on", False):
            return self._add_grid_tile(
                index=index, page_num=page_num, is_included=is_included,
                orig_orient=orig_orient, rotation_deg=rotation_deg,
                is_previewed=is_previewed, is_selected=is_selected,
                thumb_img=thumb_img,
                on_thumb_click=on_thumb_click, on_rotate_cw=on_rotate_cw,
                on_rotate_ccw=on_rotate_ccw, on_duplicate=on_duplicate,
                on_delete=on_delete, on_include_toggle=on_include_toggle,
                on_right_click=on_right_click, on_row_click=on_row_click,
                on_row_ctrl_click=on_row_ctrl_click,
                on_row_shift_click=on_row_shift_click,
                on_drag_start=on_drag_start, on_drag_motion=on_drag_motion,
                on_drag_release=on_drag_release)

        return self._add_list_row(
            index=index, page_num=page_num, is_included=is_included,
            orig_orient=orig_orient, rotation_deg=rotation_deg,
            is_previewed=is_previewed, is_selected=is_selected,
            thumb_img=thumb_img,
            on_thumb_click=on_thumb_click, on_rotate_cw=on_rotate_cw,
            on_rotate_ccw=on_rotate_ccw, on_duplicate=on_duplicate,
            on_delete=on_delete, on_move_up=on_move_up,
            on_move_down=on_move_down, on_annotate=on_annotate,
            on_redact=on_redact, on_include_toggle=on_include_toggle,
            on_right_click=on_right_click, on_row_click=on_row_click,
            on_row_ctrl_click=on_row_ctrl_click,
            on_row_shift_click=on_row_shift_click)

    def _add_list_row(self, *, index, page_num, is_included, orig_orient,
                      rotation_deg, is_previewed, is_selected, thumb_img,
                      on_thumb_click, on_rotate_cw, on_rotate_ccw,
                      on_duplicate, on_delete, on_move_up, on_move_down,
                      on_annotate, on_redact, on_include_toggle,
                      on_right_click, on_row_click, on_row_ctrl_click,
                      on_row_shift_click):

        base_bg = C["row_even"] if index % 2 == 0 else C["row_odd"]
        if not is_included:
            base_bg = C["excluded"]
        hover_bg = C["elevated_hover"]
        sel_bg = C["elevated_sel"]
        current_bg = sel_bg if (is_selected or is_previewed) else base_bg

        row = tk.Frame(self.rows_frame, bg=current_bg,
                       highlightthickness=0, bd=0)
        row.pack(fill="x", padx=10, pady=4)

        strip_color = (C["accent"] if is_previewed
                       else C["accent2"] if is_selected else current_bg)
        strip = tk.Frame(row, bg=strip_color, width=3)
        strip.pack(side="left", fill="y")

        card = tk.Frame(row, bg=current_bg, bd=0,
                        highlightthickness=1, highlightbackground=C["border"])
        card.pack(side="left", fill="both", expand=True)

        # Drag handle — uses DragManager instead of backend handlers
        handle = tk.Label(card, text="⋮⋮", bg=current_bg, fg=C["fg_dim"],
                          font=(self._f_mono, 12), cursor="fleur", padx=6)
        handle.pack(side="left", padx=(6, 4), pady=6)

        def _drag_start(e, i=index):
            self._drag_mgr.start(e, i)
        handle.bind("<Button-1>", _drag_start)

        cb_val = "●" if is_included else "○"
        cb_fg = C["accent"] if is_included else C["fg_dim"]
        cb = tk.Label(card, text=cb_val, bg=current_bg, fg=cb_fg,
                      font=(self._f_mono, 14), cursor="hand2", padx=4)
        cb.pack(side="left")
        cb.bind("<Button-1>", lambda _e: on_include_toggle())
        _Tooltip(cb, "Include / exclude")

        thumb_wrap = tk.Frame(card, bg=C["shadow"],
                              highlightthickness=1,
                              highlightbackground=C["border_strong"])
        thumb_wrap.pack(side="left", padx=(8, 14), pady=8)

        thumb_lbl = tk.Label(thumb_wrap, bg="#FFFFFF", bd=0,
                             highlightthickness=0, cursor="hand2")
        if thumb_img is not None:
            thumb_lbl.configure(image=thumb_img)
        else:
            thumb_lbl.configure(text="…", fg=C["fg_dim"], bg=C["elevated"],
                                font=(self._f_ui, 14), width=8, height=6)
        thumb_lbl.pack()
        thumb_lbl.bind("<Button-1>", lambda _e: on_thumb_click())
        thumb_lbl.bind("<Double-Button-1>", lambda _e: on_thumb_click())

        # Hover popover on thumbnail
        self._attach_hover_popover(thumb_lbl, index)

        info = tk.Frame(card, bg=current_bg)
        info.pack(side="left", fill="y", pady=8)

        page_row = tk.Frame(info, bg=current_bg)
        page_row.pack(anchor="w")
        tk.Label(page_row, text=f"{page_num:02d}", bg=current_bg, fg=C["fg"],
                 font=(self._f_mono, 22, "bold")).pack(side="left")
        tk.Label(page_row, text="  /  page", bg=current_bg,
                 fg=C["fg_dim"], font=(self._f_ui, 9)
                 ).pack(side="left", padx=(2, 0), pady=(10, 0))

        badge_row = tk.Frame(info, bg=current_bg)
        badge_row.pack(anchor="w", pady=(4, 0))
        # Effective orientation considers original orientation + rotation
        # (e.g. a portrait page rotated 90° should display as LANDSCAPE).
        try:
            from pdf_studio_common import effective_orientation as _eff
            eff = _eff(orig_orient, rotation_deg)
        except Exception:
            eff = orig_orient
        self._badge(badge_row, eff.upper(),
                    C["info"] if eff == "Landscape" else C["accent2"])

        rb_frame = tk.Frame(badge_row, bg=current_bg)
        rb_frame.pack(side="left", padx=(6, 0))
        rot_chip = tk.Frame(rb_frame, bg=C["elevated"],
                            highlightthickness=1,
                            highlightbackground=C["border_strong"])
        rot_chip.pack(side="left")
        tk.Label(rot_chip, text="↻", bg=C["elevated"], fg=C["accent"],
                 font=(self._f_ui, 9)).pack(side="left", padx=(8, 2))
        rot_value_lbl = tk.Label(
            rot_chip, text=self._format_rotation(rotation_deg),
            bg=C["elevated"], fg=C["fg"],
            font=(self._f_mono, 9, "bold"), pady=3)
        rot_value_lbl.pack(side="left", padx=(0, 10))

        if not is_included:
            tk.Label(badge_row, text="EXCLUDED",
                     bg=C["excluded_tint"], fg=C["danger"],
                     font=(self._f_ui, 8, "bold"), padx=8, pady=2
                     ).pack(side="left", padx=(6, 0))
        if is_previewed:
            tk.Label(badge_row, text="▶ PREVIEWING",
                     bg=C["accent"], fg=C["fg_on_accent"],
                     font=(self._f_ui, 8, "bold"), padx=8, pady=2
                     ).pack(side="left", padx=(6, 0))

        actions = tk.Frame(card, bg=current_bg)
        actions.pack(side="right", padx=10, pady=8)
        r1 = tk.Frame(actions, bg=current_bg)
        r1.pack(anchor="e")
        for g, cmd, tip, stl in [
            ("↺", on_rotate_ccw, "Rotate CCW", "ghost"),
            ("↻", on_rotate_cw, "Rotate CW", "ghost"),
            ("⎘", on_duplicate, "Duplicate", "ghost"),
            ("⌫", on_delete, "Delete", "danger"),
        ]:
            _HoverButton(r1, glyph=g, command=cmd,
                         tooltip=tip, style=stl,
                         compact=True).pack(side="left", padx=1)
        r2 = tk.Frame(actions, bg=current_bg)
        r2.pack(anchor="e", pady=(4, 0))
        for g, cmd, tip in [
            ("▲", on_move_up, "Move up"),
            ("▼", on_move_down, "Move down"),
            ("✎", on_annotate, "Annotate"),
            ("▧", on_redact, "Redact"),
        ]:
            _HoverButton(r2, glyph=g, command=cmd, tooltip=tip,
                         compact=True).pack(side="left", padx=1)

        for w in (row, card, info, badge_row, page_row):
            w.bind("<Button-1>", on_row_click)
            w.bind("<Control-Button-1>", on_row_ctrl_click)
            w.bind("<Shift-Button-1>", on_row_shift_click)
            w.bind("<Button-3>", on_right_click)
            w.bind("<Button-2>", on_right_click)

        def _hover_in(_=None):
            if not is_previewed and not is_selected:
                for w in (card, handle, cb, info, page_row, badge_row,
                          actions):
                    w.configure(bg=hover_bg)
                for child in info.winfo_children():
                    if isinstance(child, tk.Label):
                        child.configure(bg=hover_bg)

        def _hover_out(_=None):
            if not is_previewed and not is_selected:
                for w in (card, handle, cb, info, page_row, badge_row,
                          actions):
                    w.configure(bg=base_bg)
                for child in info.winfo_children():
                    if isinstance(child, tk.Label):
                        child.configure(bg=base_bg)

        card.bind("<Enter>", _hover_in)
        card.bind("<Leave>", _hover_out)

        row._thumb_label = thumb_lbl
        row._rb_frame = rb_frame
        row._rot_value_lbl = rot_value_lbl
        return row

    def _add_grid_tile(self, *, index, page_num, is_included, orig_orient,
                       rotation_deg, is_previewed, is_selected, thumb_img,
                       on_thumb_click, on_rotate_cw, on_rotate_ccw,
                       on_duplicate, on_delete, on_include_toggle,
                       on_right_click, on_row_click, on_row_ctrl_click,
                       on_row_shift_click, on_drag_start, on_drag_motion,
                       on_drag_release):
        # lay out tiles in a grid using pack+flow hack
        if not hasattr(self, "_grid_wrap") or not self._grid_wrap.winfo_exists():
            self._grid_wrap = tk.Frame(self.rows_frame, bg=C["panel"])
            self._grid_wrap.pack(fill="both", expand=True, padx=10, pady=8)
            self._grid_row = None
            self._grid_col = 0

        cols = 4
        canvas_w = 760
        try:
            canvas_w = self.list_canvas.winfo_width()
            # Keep a 4-up grid on normal widths; drop only when narrow.
            cols = 4 if canvas_w >= 760 else 3
        except Exception:
            pass
        if self._grid_col == 0 or self._grid_col >= cols:
            self._grid_row = tk.Frame(self._grid_wrap, bg=C["panel"])
            self._grid_row.pack(fill="x", pady=6)
            self._grid_col = 0

        tile_bg = (C["elevated_sel"] if (is_selected or is_previewed)
                   else C["elevated"])
        border = C["accent"] if is_previewed else (
            C["accent2"] if is_selected else C["border"])

        cell_w = max(160, int((canvas_w - 24 - (cols * 12)) / max(1, cols)))
        tile = tk.Frame(self._grid_row, bg=tile_bg,
                        highlightthickness=2, highlightbackground=border)
        tile.grid(row=0, column=self._grid_col, padx=6, pady=6, sticky="nsew")
        tile.configure(width=cell_w, height=220)
        tile.grid_propagate(False)
        self._grid_row.grid_columnconfigure(self._grid_col, weight=1, uniform="gridcol")
        tile.configure(cursor="hand2")

        thumb = tk.Label(tile, bg="#FFFFFF", bd=0, highlightthickness=0,
                         cursor="hand2")
        if thumb_img is not None:
            # In grid view, enlarge the *thumbnail image itself* (not card spacing).
            grid_img = None
            try:
                rec = self.pages[index]
                pil_img = getattr(rec, "thumb_img", None)
                if pil_img is not None:
                    tw = min(int(cell_w - 24), int(pil_img.width * 1.35))
                    th = int((tw / max(1, pil_img.width)) * pil_img.height)
                    resized = pil_img.resize((max(60, tw), max(80, th)))
                    grid_img = ImageTk.PhotoImage(resized)
            except Exception:
                grid_img = None
            if grid_img is not None:
                thumb.configure(image=grid_img)
                tile._grid_thumb_tk = grid_img
            else:
                thumb.configure(image=thumb_img)
        else:
            thumb.configure(text="…", fg=C["fg_dim"], bg=C["elevated"],
                            font=(self._f_ui, 14), width=10, height=8)
        thumb.pack(padx=8, pady=(10, 8))
        # Keep direct click free for drag start; use double-click for quick preview.
        thumb.bind("<Double-Button-1>", lambda _e: on_thumb_click())
        self._attach_hover_popover(thumb, index)

        ftr = tk.Frame(tile, bg=tile_bg)
        ftr.pack(fill="x", side="bottom", padx=8, pady=(0, 10))
        ftr.configure(cursor="hand2")

        tk.Label(ftr, text=f"{page_num:02d}", bg=tile_bg, fg=C["fg"],
                 font=(self._f_mono, 11, "bold")).pack(side="left")
        if not is_included:
            tk.Label(ftr, text="✕", bg=tile_bg, fg=C["danger"],
                     font=(self._f_ui, 10, "bold")).pack(side="right")

        for w in (tile, thumb, ftr):
            w.bind("<Control-Button-1>", on_row_ctrl_click)
            w.bind("<Shift-Button-1>", on_row_shift_click)
            w.bind("<Button-3>", on_right_click)
            w.bind("<Button-2>", on_right_click)
            # Enable backend drag-reorder in grid view.
            w.bind("<ButtonPress-1>", on_drag_start, add="+")
            w.bind("<B1-Motion>", on_drag_motion, add="+")
            w.bind("<ButtonRelease-1>", on_drag_release, add="+")

        tile._page_index = index
        thumb._page_index = index
        ftr._page_index = index

        tile._thumb_label = thumb
        tile._rb_frame = tile
        tile._rot_value_lbl = tk.Label(tile, text="",
                                       bg=tile_bg)  # placeholder

        self._grid_col += 1
        return tile

    # ── hover popover ──────────────────────────────────────────────────
    def _attach_hover_popover(self, widget, index):
        pop = {"tip": None, "after": None}

        def show():
            try:
                rec = self.pages[index]
            except Exception:
                return
            snippet = "(no text on this page)"
            try:
                import fitz
                if not rec.is_blank:
                    doc = fitz.open(rec.source_path)
                    text = doc[rec.source_index].get_text().strip()
                    doc.close()
                    if text:
                        snippet = text[:180] + ("…" if len(text) > 180 else "")
            except Exception:
                pass
            x = widget.winfo_rootx() + widget.winfo_width() + 8
            y = widget.winfo_rooty()
            tip = tk.Toplevel(widget)
            tip.wm_overrideredirect(True)
            tip.wm_geometry(f"+{x}+{y}")
            tip.configure(bg=C["border_strong"])
            inner = tk.Frame(tip, bg=C["popover_bg"])
            inner.pack(padx=1, pady=1)
            tk.Label(inner, text=f"PAGE {index + 1}  ·  {rec.orig_orient}",
                     bg=C["popover_bg"], fg=C["fg_dim"],
                     font=(self._f_ui, 8, "bold"),
                     padx=12, pady=4, anchor="w"
                     ).pack(fill="x", pady=(10, 4))
            tk.Label(inner, text=snippet, bg=C["popover_bg"], fg=C["fg"],
                     wraplength=260, justify="left", padx=12, pady=2,
                     font=(self._f_ui, 9), anchor="w").pack(fill="x", pady=(2, 8))
            extras = []
            if getattr(rec, "annotations", None):
                extras.append(f"{len(rec.annotations)} annotations")
            if getattr(rec, "redactions", None):
                extras.append(f"{len(rec.redactions)} redactions")
            if extras:
                tk.Label(inner, text="  •  ".join(extras),
                         bg=C["popover_bg"], fg=C["accent"],
                         font=(self._f_ui, 8, "bold"),
                         padx=12, pady=2).pack(fill="x", pady=(0, 8))
            pop["tip"] = tip

        def enter(_=None):
            if pop["after"]:
                try:
                    widget.after_cancel(pop["after"])
                except Exception:
                    pass
            pop["after"] = widget.after(600, show)

        def leave(_=None):
            if pop["after"]:
                try:
                    widget.after_cancel(pop["after"])
                except Exception:
                    pass
                pop["after"] = None
            if pop["tip"]:
                try:
                    pop["tip"].destroy()
                except Exception:
                    pass
                pop["tip"] = None

        widget.bind("<Enter>", enter, add="+")
        widget.bind("<Leave>", leave, add="+")
        widget.bind("<Button-1>", leave, add="+")

    def _badge(self, parent, text, color):
        f = tk.Frame(parent, bg=parent.cget("bg"))
        f.pack(side="left")
        tk.Label(f, text=text, bg=parent.cget("bg"), fg=color,
                 font=(self._f_ui, 8, "bold"),
                 highlightthickness=1, highlightbackground=color,
                 padx=6, pady=2).pack()
        return f

    @staticmethod
    def _format_rotation(deg):
        deg = int(deg) % 360
        return {0: "  0°", 90: " 90° CW", 180: "180°",
                270: " 90° CCW"}.get(deg, f"{deg}°")

    # ══════════════════ THEME / UTILITIES ═══════════════════════════════════
    def _invoke_toggle_theme(self):
        new_dark = not self._dark_var.get()
        self._dark_var.set(new_dark)
        _set_palette(new_dark)
        if hasattr(self, "_toggle_theme"):
            try:
                self._toggle_theme()
            except Exception:
                pass
        self._restyle_static_chrome()
        tx = _get_toaster(self)
        if tx:
            tx.show(f"Theme switched to {'dark' if new_dark else 'light'}",
                    kind="info", duration=1500)

    def _restyle_static_chrome(self):
        try:
            self.root.configure(bg=C["bg"])
            for attr in ("_titlebar", "_toolbar", "_statusbar",
                         "_breadcrumb"):
                w = getattr(self, attr, None)
                if w:
                    w.configure(bg=C["panel"] if "bar" in attr else
                                C["panel_alt"])
            self._apply_ttk_style()
        except Exception:
            pass

    def _safe(self, name):
        def caller(*a, **kw):
            fn = getattr(self, name, None)
            if callable(fn):
                return fn(*a, **kw)
        return caller


# ═════════════════════════════════════════════════════════════════════════════
#  SMOKE-TEST
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    class _Dummy(PDFStudioUI):
        def __init__(self, root):
            self.root = root
            root.title("PDF Studio v4 – UI preview")
            root.geometry("1360x820")
            self.search_var = tk.StringVar()
            self.range_var = tk.StringVar()
            self.goto_var = tk.StringVar()
            self.autosave_var = tk.StringVar(value="")
            self.preview_info_var = tk.StringVar(value="No page selected")
            self.zoom_var = tk.StringVar(value="100%")
            self.thumb_size_var = tk.IntVar(value=90)
            self.status_var = tk.StringVar(value="UI preview — no backend.")
            self.pages = []

            root.configure(bg=C["bg"])
            root.columnconfigure(0, weight=1)
            root.rowconfigure(2, weight=1)
            self._build_titlebar()
            self._build_menubar()
            self._build_toolbar()
            self._apply_ttk_style()
            container = tk.Frame(root, bg=C["bg"])
            container.grid(row=2, column=0, sticky="nsew")
            container.columnconfigure(0, weight=1)
            container.rowconfigure(1, weight=1)
            self._build_sub_toolbar_into(container)
            self.pane = tk.PanedWindow(container, orient="horizontal",
                                       bg=C["border"], sashwidth=4,
                                       sashpad=0, relief="flat")
            self.pane.pack(fill="both", expand=True)
            self._build_list_panel()
            self._build_preview_panel()
            self._build_statusbar()
            self._bind_global_keys()
    root = tk.Tk()
    _Dummy(root)
    root.mainloop()
