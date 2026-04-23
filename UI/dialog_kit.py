"""
PDF Studio – dialog_kit
─────────────────────────────────────────────────────────────────────────────
Shared themed primitives used by the UI shell and feature dialogs:

    themed_toplevel(root, title, w, h)     → tk.Toplevel pre-styled
    themed_button(parent, text, ...)       → flat accent/ghost/success button
    themed_entry(parent, textvariable, ...)→ entry with border chip
    themed_spin(parent, var, from_, to)    → spinbox styled
    themed_check(parent, text, var)        → checkbutton with coloured dot
    themed_radio(parent, text, var, value) → radio pill
    themed_scale(parent, var, fr, to)      → horizontal scale in accent color
    field_row(parent, label, widget)       → two-column "label: widget" row
    section(parent, title)                 → labeled section wrapper
    Toast(root)                            → corner toast notifications
    Splash(root)                           → splash screen for .exe launch

All widgets read colors from UI.pdf_studio_ui.C dict so they respect the
currently active theme.
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from UI.pdf_studio_ui import C


# ─────────────────────────────────────────────────────────────────────────────
def themed_toplevel(root, title, w=420, h=300, resizable=(False, False)):
    """Create a Toplevel dialog styled to match the current theme."""
    win = tk.Toplevel(root)
    win.title(title)
    win.configure(bg=C["panel"])
    win.resizable(*resizable)
    try:
        win.transient(root)
    except Exception:
        pass

    try:
        rx = root.winfo_rootx()
        ry = root.winfo_rooty()
        rw = root.winfo_width() or 1280
        rh = root.winfo_height() or 760
        x = rx + (rw - w) // 2
        y = ry + (rh - h) // 3
        win.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
    except Exception:
        win.geometry(f"{w}x{h}")

    # Header strip
    head = tk.Frame(win, bg=C["accent"], height=4)
    head.pack(fill="x")
    title_row = tk.Frame(win, bg=C["panel"])
    title_row.pack(fill="x", padx=20, pady=(16, 6))
    tk.Label(title_row, text=title, bg=C["panel"], fg=C["fg"],
             font=("TkDefaultFont", 13, "bold")).pack(side="left")

    # Content area the caller fills
    body = tk.Frame(win, bg=C["panel"])
    body.pack(fill="both", expand=True, padx=20, pady=(4, 16))

    win.body = body
    try:
        win.grab_set()
    except Exception:
        pass
    return win


# ─────────────────────────────────────────────────────────────────────────────
def themed_button(parent, text="", command=None, style="accent",
                  glyph="", width=None):
    """Flat themed button. style ∈ {accent, ghost, success, danger, solid}."""
    if style == "accent":
        bg, fg, hbg = C["accent"], C["fg_on_accent"], C["accent_hover"]
    elif style == "success":
        bg, fg, hbg = C["success"], "#FFFFFF", C["success"]
    elif style == "danger":
        bg, fg, hbg = C["danger"], "#FFFFFF", C["danger"]
    elif style == "solid":
        bg, fg, hbg = C["elevated"], C["fg"], C["elevated_hover"]
    else:
        bg, fg, hbg = C["panel"], C["fg_muted"], C["elevated_hover"]

    frame = tk.Frame(parent, bg=bg, highlightthickness=1,
                     highlightbackground=C["border_strong"] if style == "ghost"
                     else bg)
    label = " ".join(x for x in (glyph, text) if x)
    btn = tk.Label(frame, text=label, bg=bg, fg=fg,
                   font=("TkDefaultFont", 10, "bold"),
                   padx=18, pady=8, cursor="hand2")
    btn.pack(fill="both", expand=True)
    if width:
        btn.configure(width=width)

    def enter(_=None):
        btn.configure(bg=hbg)
        frame.configure(bg=hbg, highlightbackground=hbg)

    def leave(_=None):
        btn.configure(bg=bg)
        frame.configure(bg=bg,
                        highlightbackground=C["border_strong"]
                        if style == "ghost" else bg)

    btn.bind("<Enter>", enter)
    btn.bind("<Leave>", leave)
    btn.bind("<Button-1>", lambda _e: command() if command else None)
    return frame


# ─────────────────────────────────────────────────────────────────────────────
def themed_entry(parent, textvariable=None, width=30, placeholder="",
                 mono=False, show=None):
    """Entry with soft border chip."""
    wrap = tk.Frame(parent, bg=C["elevated"],
                    highlightthickness=1, highlightbackground=C["border"])
    font = ("TkFixedFont",) if mono else ("TkDefaultFont",)
    e = tk.Entry(wrap, textvariable=textvariable, bd=0, bg=C["elevated"],
                 fg=C["fg"], insertbackground=C["accent"],
                 font=(*font, 10), width=width,
                 highlightthickness=0, relief="flat", show=show)
    e.pack(ipady=6, padx=8, fill="x")

    def _focus_in(_=None):
        wrap.configure(highlightbackground=C["accent"])

    def _focus_out(_=None):
        wrap.configure(highlightbackground=C["border"])

    e.bind("<FocusIn>", _focus_in)
    e.bind("<FocusOut>", _focus_out)

    if placeholder and not (textvariable and textvariable.get()):
        e.insert(0, placeholder)
        e.configure(fg=C["fg_dim"])

        def _clear(_):
            if e.get() == placeholder:
                e.delete(0, "end")
                e.configure(fg=C["fg"])

        def _restore(_):
            if not e.get():
                e.insert(0, placeholder)
                e.configure(fg=C["fg_dim"])

        e.bind("<FocusIn>", _clear, add="+")
        e.bind("<FocusOut>", _restore, add="+")

    wrap.entry = e
    return wrap


# ─────────────────────────────────────────────────────────────────────────────
def themed_check(parent, text, variable):
    f = tk.Frame(parent, bg=parent.cget("bg"))
    lbl_dot = tk.Label(f, text="●" if variable.get() else "○",
                       bg=parent.cget("bg"),
                       fg=C["accent"] if variable.get() else C["fg_dim"],
                       font=("TkFixedFont", 13), cursor="hand2", padx=2)
    lbl_dot.pack(side="left")
    lbl = tk.Label(f, text=text, bg=parent.cget("bg"), fg=C["fg"],
                   font=("TkDefaultFont", 10), cursor="hand2", padx=4)
    lbl.pack(side="left")

    def toggle(_=None):
        variable.set(not variable.get())
        refresh()

    def refresh(*_):
        on = bool(variable.get())
        lbl_dot.configure(text="●" if on else "○",
                          fg=C["accent"] if on else C["fg_dim"])

    variable.trace_add("write", refresh)
    lbl_dot.bind("<Button-1>", toggle)
    lbl.bind("<Button-1>", toggle)
    return f


def themed_radio(parent, text, variable, value):
    f = tk.Frame(parent, bg=parent.cget("bg"))
    dot = tk.Label(f, text="◉" if variable.get() == value else "○",
                   bg=parent.cget("bg"),
                   fg=C["accent"] if variable.get() == value else C["fg_dim"],
                   font=("TkFixedFont", 13), cursor="hand2", padx=2)
    dot.pack(side="left")
    lbl = tk.Label(f, text=text, bg=parent.cget("bg"), fg=C["fg"],
                   font=("TkDefaultFont", 10), cursor="hand2", padx=4)
    lbl.pack(side="left")

    def select(_=None):
        variable.set(value)

    def refresh(*_):
        sel = variable.get() == value
        dot.configure(text="◉" if sel else "○",
                      fg=C["accent"] if sel else C["fg_dim"])

    variable.trace_add("write", refresh)
    dot.bind("<Button-1>", select)
    lbl.bind("<Button-1>", select)
    return f


def field_row(parent, label, widget, hint=None):
    f = tk.Frame(parent, bg=parent.cget("bg"))
    f.pack(fill="x", pady=6)
    lbl = tk.Label(f, text=label, bg=parent.cget("bg"), fg=C["fg_muted"],
                   font=("TkDefaultFont", 9, "bold"), width=14, anchor="w")
    lbl.pack(side="left", padx=(0, 10))
    widget.pack(side="left", fill="x", expand=True)
    if hint:
        tk.Label(f, text=hint, bg=parent.cget("bg"), fg=C["fg_dim"],
                 font=("TkDefaultFont", 8)).pack(side="left", padx=8)
    return f


def section(parent, title):
    f = tk.Frame(parent, bg=parent.cget("bg"))
    f.pack(fill="x", pady=(10, 4))
    tk.Label(f, text=title.upper(), bg=parent.cget("bg"), fg=C["fg_dim"],
             font=("TkDefaultFont", 9, "bold")).pack(side="left")
    line = tk.Frame(f, bg=C["border"], height=1)
    line.pack(side="left", fill="x", expand=True, padx=10, pady=6)
    body = tk.Frame(parent, bg=parent.cget("bg"))
    body.pack(fill="x", pady=(0, 8))
    return body


# ─────────────────────────────────────────────────────────────────────────────
class Toast:
    """Corner toast manager. Call Toast(root).show(text, kind)."""
    _KINDS = {
        "info":    ("info",    "ℹ"),
        "success": ("success", "✓"),
        "warn":    ("warning", "⚠"),
        "error":   ("danger",  "✕"),
    }

    def __init__(self, root):
        self.root = root
        self._active = []

    def show(self, text, kind="info", duration=3000):
        color_key, glyph = self._KINDS.get(kind, self._KINDS["info"])
        try:
            rx = self.root.winfo_rootx()
            ry = self.root.winfo_rooty()
            rw = self.root.winfo_width()
            rh = self.root.winfo_height()
        except Exception:
            return
        toast = tk.Toplevel(self.root)
        toast.wm_overrideredirect(True)
        toast.configure(bg=C["border_strong"])
        toast.attributes("-topmost", True)

        inner = tk.Frame(toast, bg=C["panel"], highlightthickness=0)
        inner.pack(padx=1, pady=1)
        stripe = tk.Frame(inner, bg=C[color_key], width=3)
        stripe.pack(side="left", fill="y")
        content = tk.Frame(inner, bg=C["panel"])
        content.pack(side="left", padx=(12, 16), pady=10)
        tk.Label(content, text=glyph, bg=C["panel"], fg=C[color_key],
                 font=("TkDefaultFont", 13, "bold")
                 ).pack(side="left", padx=(0, 8))
        tk.Label(content, text=text, bg=C["panel"], fg=C["fg"],
                 font=("TkDefaultFont", 10), anchor="w",
                 justify="left", wraplength=280).pack(side="left")

        toast.update_idletasks()
        tw = toast.winfo_reqwidth()
        th = toast.winfo_reqheight()

        # Stack above previous toasts
        self._active = [t for t in self._active if t.winfo_exists()]
        offset_y = sum(t.winfo_height() + 8 for t in self._active)

        tx = rx + rw - tw - 24
        ty_target = ry + rh - th - 56 - offset_y

        # Slide-in from below
        ty_start = ty_target + 40
        toast.geometry(f"+{tx}+{ty_start}")
        self._active.append(toast)

        steps = 8

        def animate(step=0):
            if not toast.winfo_exists():
                return
            if step <= steps:
                t = step / steps
                eased = 1 - (1 - t) ** 3
                y = int(ty_start + (ty_target - ty_start) * eased)
                toast.geometry(f"+{tx}+{y}")
                toast.after(14, lambda: animate(step + 1))

        animate()
        toast.after(duration, lambda: self._dismiss(toast))
        return toast

    def _dismiss(self, toast):
        try:
            if not toast.winfo_exists():
                return
            x, y = toast.winfo_x(), toast.winfo_y()
            steps = 6
            for i in range(steps):
                ny = y + (i + 1) * 8
                toast.after(i * 14, lambda nx=x, ny=ny: toast.geometry(
                    f"+{nx}+{ny}"))
            toast.after(steps * 14 + 20, toast.destroy)
        except Exception:
            try:
                toast.destroy()
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
class Splash:
    """Splash screen for .exe cold-start."""

    def __init__(self, root, duration_ms=1500):
        self.root = root
        root.withdraw()
        self.win = tk.Toplevel(root)
        self.win.wm_overrideredirect(True)
        self.win.configure(bg=C["panel"])
        self.win.attributes("-topmost", True)

        w, h = 480, 300
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        self.win.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

        # Thin accent border
        tk.Frame(self.win, bg=C["accent"], height=3).pack(fill="x")

        # Real wordmark — falls back to text if asset missing
        try:
            from UI.pdf_studio_ui import load_brand_image
            img = load_brand_image("pdf_studio_wordmark_transparent.png",
                                   max_w=380, max_h=130)
        except Exception:
            img = None

        if img is not None:
            lbl = tk.Label(self.win, image=img, bg=C["panel"],
                           bd=0, highlightthickness=0)
            lbl._img_ref = img
            lbl.pack(pady=(50, 10))
        else:
            # Fallback text wordmark
            row = tk.Frame(self.win, bg=C["panel"])
            row.pack(pady=(60, 8))
            tk.Label(row, text="PDF", bg=C["panel"],
                     fg=C.get("brand_red", "#DC2626"),
                     font=("TkDefaultFont", 30, "bold")).pack(side="left")
            tk.Label(row, text=" Studio", bg=C["panel"], fg=C["fg"],
                     font=("TkDefaultFont", 30, "bold")).pack(side="left")

        tk.Label(self.win, text="v4  ·  document workbench",
                 bg=C["panel"], fg=C["fg_muted"],
                 font=("TkDefaultFont", 10)).pack(pady=(0, 4))

        # progress
        self.bar_bg = tk.Frame(self.win, bg=C["elevated"], height=3, width=220)
        self.bar_bg.pack(pady=30)
        self.bar_bg.pack_propagate(False)
        self.bar = tk.Frame(self.bar_bg, bg=C["accent"], width=0, height=3)
        self.bar.place(x=0, y=0)

        self.win.after(30, self._tick, 0, duration_ms)

    def _tick(self, elapsed, total):
        if elapsed >= total:
            try:
                self.win.destroy()
            except Exception:
                pass
            self.root.deiconify()
            return
        frac = elapsed / total
        self.bar.place(x=0, y=0, width=int(220 * frac))
        self.win.after(20, self._tick, elapsed + 20, total)


__all__ = [
    "themed_toplevel", "themed_button", "themed_entry",
    "themed_check", "themed_radio",
    "field_row", "section", "Toast", "Splash",
]
