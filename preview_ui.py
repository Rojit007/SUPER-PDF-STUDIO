"""
preview_ui.py — preview the redesigned PDF Studio UI with all features.

    python preview_ui.py

Showcases: command palette (Ctrl+K), drag-and-drop file opens, grid view
toggle (Ctrl+G), sidebar toggle (Ctrl+B), toasts, splash screen,
animated drag-to-reorder on the demo rows, keyboard navigation
(↑ ↓ Home End PgUp PgDn Space Enter), preferences (Ctrl+,), and theme
toggle (Ctrl+T).
"""
import tkinter as tk
from PIL import Image, ImageTk, ImageDraw  # pip install Pillow

from UI.pdf_studio_ui import PDFStudioUI, C, _get_toaster
from UI.dialog_kit import Splash


class _FakeVar:
    def __init__(self, v):
        self._v = v

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


class _FakeRec:
    def __init__(self, i):
        self.included = _FakeVar(True)
        self.orig_orient = "Landscape" if i % 3 == 0 else "Portrait"
        self.orientation = _FakeVar(0 if i % 2 == 0 else 90)
        self.is_blank = (i == 3)
        self.source_path = "/demo/annual-report-2025.pdf"
        self.source_index = i
        self.annotations = []
        self.redactions = []


class _FakeUndoStack:
    def __init__(self):
        self._undo = []
        self._redo = []

    def push(self, *a, **k):
        self._undo.append(("demo action", []))


class DemoApp(PDFStudioUI):
    def __init__(self, root):
        self.root = root
        root.title("PDF Studio v4 – UI Preview")
        root.geometry("1360x820")
        root.minsize(1100, 660)

        self.search_var = tk.StringVar()
        self.range_var = tk.StringVar(value="1-3, 5")
        self.goto_var = tk.StringVar()
        self.autosave_var = tk.StringVar(value="💾 auto")
        self.preview_info_var = tk.StringVar(
            value="Page 2 of 8  •  90° CW  •  A4")
        self.zoom_var = tk.StringVar(value="125%")
        self.thumb_size_var = tk.IntVar(value=100)
        self.status_var = tk.StringVar(
            value="3/8 pages included  •  page 2 previewed")

        self.pages = [_FakeRec(i) for i in range(8)]
        self._preview_index = 1
        self.selected_pages = {1, 2}
        self._bookmarks = [
            {"title": "Executive Summary", "page": 0},
            {"title": "Financial Highlights", "page": 2},
            {"title": "Operations", "page": 4},
            {"title": "Appendix", "page": 6},
        ]
        self.undo_stack = _FakeUndoStack()

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

        self.update_titlebar("/demo/annual-report-2025.pdf")
        self.refresh_recent_menu([
            "/demo/annual-report-2025.pdf",
            "/demo/contract_v2.pdf",
            "/demo/slide-deck.pdf",
        ])
        self.refresh_bookmarks_sidebar()
        self.populate_demo_rows()

        # Welcome toast
        self.root.after(1200, lambda: _get_toaster(self).show(
            "Welcome! Press Ctrl+K for the command palette",
            kind="info", duration=4000))

    # ── stubs for backend hooks the UI might call ───────────────────────
    def _render_preview(self, *a, **k):
        pass

    def _scroll_to_row(self, idx):
        pass

    def _rebuild_rows(self):
        self.clear_page_rows()
        self.populate_demo_rows()

    def _update_status(self):
        if self.pages:
            n_in = sum(1 for r in self.pages if r.included.get())
            self.status_var.set(
                f"{n_in}/{len(self.pages)} included  •  page "
                f"{self._preview_index + 1} previewed")

    def _push_undo(self, _=None):
        self.undo_stack.push()

    # ── demo helpers ────────────────────────────────────────────────────
    def _make_thumb(self, page_num, orient):
        w, h = (140, 100) if orient == "Landscape" else (90, 120)
        img = Image.new("RGB", (w, h), "#FFFFFF")
        d = ImageDraw.Draw(img)
        d.rectangle([2, 2, w - 3, h - 3], outline="#C4BFAE", width=1)
        d.text((8, 8), "Page", fill="#94909E")
        d.text((8, 20), f"{page_num:02d}", fill="#1F1F2E")
        for ln in range(4):
            d.line([(10, 48 + ln * 12), (w - 12, 48 + ln * 12)],
                   fill="#E6E0D4", width=1)
        return ImageTk.PhotoImage(img)

    def populate_demo_rows(self):
        self.clear_page_rows()
        self._thumbs = []
        for i, rec in enumerate(self.pages):
            thumb = self._make_thumb(i + 1, rec.orig_orient)
            self._thumbs.append(thumb)
            self.add_page_row(
                index=i, page_num=i + 1,
                is_included=rec.included.get(),
                orig_orient=rec.orig_orient,
                rotation_deg=rec.orientation.get(),
                is_previewed=(i == self._preview_index),
                is_selected=(i in self.selected_pages),
                thumb_img=thumb,
                on_thumb_click=lambda i=i: self._preview(i),
                on_rotate_cw=lambda i=i: self._toast_demo(
                    f"Rotate CW {i+1}"),
                on_rotate_ccw=lambda i=i: self._toast_demo(
                    f"Rotate CCW {i+1}"),
                on_duplicate=lambda i=i: self._toast_demo(
                    f"Duplicate {i+1}"),
                on_delete=lambda i=i: self._toast_demo(f"Delete {i+1}"),
                on_move_up=lambda i=i: self._toast_demo(f"Move up {i+1}"),
                on_move_down=lambda i=i: self._toast_demo(
                    f"Move down {i+1}"),
                on_annotate=lambda i=i: self._toast_demo(f"Annotate {i+1}"),
                on_redact=lambda i=i: self._toast_demo(f"Redact {i+1}"),
                on_include_toggle=lambda i=i: (
                    self.pages[i].included.set(
                        not self.pages[i].included.get()),
                    self._rebuild_rows()),
                on_right_click=lambda e, i=i: self._toast_demo(
                    f"Context menu {i+1}"),
                on_row_click=lambda e, i=i: self._preview(i),
                on_row_ctrl_click=lambda e, i=i: None,
                on_row_shift_click=lambda e, i=i: None,
                on_drag_start=lambda e, i=i: None,
                on_drag_motion=lambda e, i=i: None,
                on_drag_release=lambda e, i=i: None,
            )
        self.update_undo_redo(True, False, "rotate page", "")

    def _preview(self, i):
        self._preview_index = i
        self.selected_pages = {i}
        self._rebuild_rows()
        self._update_status()

    def _toast_demo(self, msg):
        _get_toaster(self).show(msg, kind="info", duration=1500)


if __name__ == "__main__":
    root = tk.Tk()
    Splash(root, duration_ms=1200)  # comment out to skip splash
    DemoApp(root)
    root.mainloop()
