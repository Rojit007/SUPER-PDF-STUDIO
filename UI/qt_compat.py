"""
UI/qt_compat.py
──────────────────────────────────────────────────────────────────────────────
Drop-in replacements for the tkinter dialog namespaces used throughout the
backend and features.  Calling conventions match tkinter so callsites need
minimal changes:

    from UI.qt_compat import filedialog, messagebox, simpledialog, colorchooser

    path = filedialog.askopenfilename(title="Open", filetypes=[("PDF","*.pdf")])
    ok   = messagebox.askyesno("Confirm", "Really delete?")
    text = simpledialog.askstring("Input", "Name:")
    col  = colorchooser.askcolor(color="#FF0000")  # → ((r,g,b), "#rrggbb")
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QApplication, QFileDialog, QMessageBox,
    QInputDialog, QColorDialog,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor


# ──────────────────────────────────────────────────────────────────────────────
#  Helper: resolve the active main window as parent
# ──────────────────────────────────────────────────────────────────────────────

def _parent(hint=None):
    if hint is not None:
        return hint
    app = QApplication.instance()
    if app:
        return app.activeWindow()
    return None


def _build_filter(filetypes):
    """Convert tkinter [(label, pattern), …] to Qt filter string."""
    if not filetypes:
        return "All files (*.*)"
    parts = []
    for label, pattern in filetypes:
        if isinstance(pattern, (list, tuple)):
            pat = " ".join(pattern)
        else:
            pat = pattern
        parts.append(f"{label} ({pat})")
    return ";;".join(parts)


# ──────────────────────────────────────────────────────────────────────────────
#  filedialog
# ──────────────────────────────────────────────────────────────────────────────

class _FileDialog:
    @staticmethod
    def askopenfilename(title="Open", filetypes=None, parent=None,
                        initialdir=None, **_kw):
        flt = _build_filter(filetypes or [])
        path, _ = QFileDialog.getOpenFileName(_parent(parent), title,
                                              initialdir or "", flt)
        return path  # "" if cancelled

    @staticmethod
    def askopenfilenames(title="Open", filetypes=None, parent=None,
                         initialdir=None, **_kw):
        flt = _build_filter(filetypes or [])
        paths, _ = QFileDialog.getOpenFileNames(_parent(parent), title,
                                                initialdir or "", flt)
        return paths  # [] if cancelled

    @staticmethod
    def asksaveasfilename(title="Save", defaultextension="", filetypes=None,
                          initialfile="", parent=None, initialdir=None, **_kw):
        flt = _build_filter(filetypes or [])
        path, _ = QFileDialog.getSaveFileName(_parent(parent), title,
                                              initialfile or "", flt)
        if path and defaultextension and not path.endswith(defaultextension):
            path += defaultextension
        return path  # "" if cancelled

    @staticmethod
    def askdirectory(title="Select folder", parent=None, **_kw):
        return QFileDialog.getExistingDirectory(_parent(parent), title)


filedialog = _FileDialog()


# ──────────────────────────────────────────────────────────────────────────────
#  messagebox
# ──────────────────────────────────────────────────────────────────────────────

class _MessageBox:
    @staticmethod
    def showinfo(title="", message="", parent=None, **_kw):
        QMessageBox.information(_parent(parent), title, message)

    @staticmethod
    def showerror(title="", message="", parent=None, **_kw):
        QMessageBox.critical(_parent(parent), title, message)

    @staticmethod
    def showwarning(title="", message="", parent=None, **_kw):
        QMessageBox.warning(_parent(parent), title, message)

    @staticmethod
    def askyesno(title="", message="", parent=None, **_kw):
        result = QMessageBox.question(
            _parent(parent), title, message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return result == QMessageBox.StandardButton.Yes

    @staticmethod
    def askokcancel(title="", message="", parent=None, **_kw):
        result = QMessageBox.question(
            _parent(parent), title, message,
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return result == QMessageBox.StandardButton.Ok


messagebox = _MessageBox()


# ──────────────────────────────────────────────────────────────────────────────
#  simpledialog
# ──────────────────────────────────────────────────────────────────────────────

class _SimpleDialog:
    @staticmethod
    def askstring(title="", prompt="", show=None, initialvalue="",
                  parent=None, **_kw):
        text, ok = QInputDialog.getText(
            _parent(parent), title, prompt,
            text=initialvalue or "",
        )
        if show == "*":
            dlg = QInputDialog(_parent(parent))
            dlg.setWindowTitle(title)
            dlg.setLabelText(prompt)
            dlg.setTextEchoMode(__import__('PySide6.QtWidgets',
                                           fromlist=['QLineEdit']).QLineEdit.EchoMode.Password)
            if dlg.exec():
                return dlg.textValue()
            return None
        return text if ok else None

    @staticmethod
    def askinteger(title="", prompt="", minvalue=0, maxvalue=100,
                   initialvalue=0, parent=None, **_kw):
        val, ok = QInputDialog.getInt(
            _parent(parent), title, prompt,
            value=initialvalue, min=minvalue, max=maxvalue,
        )
        return val if ok else None

    @staticmethod
    def askfloat(title="", prompt="", minvalue=None, maxvalue=None,
                 initialvalue=0.0, parent=None, **_kw):
        val, ok = QInputDialog.getDouble(
            _parent(parent), title, prompt, value=initialvalue,
        )
        return val if ok else None


simpledialog = _SimpleDialog()


# ──────────────────────────────────────────────────────────────────────────────
#  colorchooser
# ──────────────────────────────────────────────────────────────────────────────

class _ColorChooser:
    @staticmethod
    def askcolor(color=None, parent=None, title="Choose color", **_kw):
        initial = QColor(color) if color else QColor("#AAAAAA")
        chosen = QColorDialog.getColor(initial, _parent(parent), title)
        if chosen.isValid():
            r, g, b = chosen.red(), chosen.green(), chosen.blue()
            hexcol = chosen.name()          # "#rrggbb"
            return (r, g, b), hexcol
        return None, None


colorchooser = _ColorChooser()
