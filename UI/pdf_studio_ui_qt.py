"""
PDF Studio – PySide6 UI Shell
──────────────────────────────────────────────────────────────────────────────
Drop-in replacement for UI/pdf_studio_ui.py using PySide6 / Qt6.

Public contract (same method names as the Tkinter shell):
  add_page_row(rec, idx)        – insert a page card into the list panel
  clear_page_rows()             – remove all page cards
  update_titlebar(title=None)   – set window title
  refresh_recent_menu()         – rebuild the recent-files menu
  update_undo_redo()            – sync undo/redo action enabled state
  _render_preview(idx)          – render the right-panel preview
  _show_toast(msg, kind, ms)    – corner slide-in notification

Usage (replace Tkinter entry point):
  app = QApplication(sys.argv)
  win = PDFStudio()          # PDFStudio(PDFStudioUI, PDFFeatures, PDFStudioBase)
  win.show()
  sys.exit(app.exec())
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QApplication,
    QVBoxLayout, QHBoxLayout, QSplitter,
    QScrollArea, QLabel, QFrame, QAbstractScrollArea,
    QToolBar, QStatusBar, QMenuBar, QMenu, QSizePolicy,
    QDockWidget, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QDialog, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QCheckBox, QSpacerItem,
    QMessageBox, QFileDialog, QColorDialog, QInputDialog,
)
from PySide6.QtCore import (
    Qt, Signal, QSize, QTimer, QPropertyAnimation,
    QEasingCurve, QRect, QPoint, QThread, QObject,
    QMimeData, QByteArray, QSortFilterProxyModel,
    QAbstractListModel, QModelIndex,
)
from PySide6.QtGui import (
    QPixmap, QImage, QColor, QPalette, QFont,
    QFontDatabase, QIcon, QKeySequence,
    QPainter, QPen, QBrush, QAction, QCursor,
)

from PIL import Image

# ──────────────────────────────────────────────────────────────────────────────
#  DESIGN TOKENS
# ──────────────────────────────────────────────────────────────────────────────

_DARK = {
    "bg":             "#0E0E17",
    "panel":          "#141423",
    "panel_alt":      "#1A1A2C",
    "elevated":       "#1F1F33",
    "elevated_hover": "#272742",
    "elevated_sel":   "#3A2330",
    "border":         "#262638",
    "border_strong":  "#35354F",
    "divider":        "#1F1F33",
    "fg":             "#E6E6F0",
    "fg_muted":       "#9A9AB8",
    "fg_dim":         "#5E5E78",
    "fg_on_accent":   "#FFFFFF",
    "accent":         "#DC2626",
    "accent_hover":   "#EF4444",
    "accent_dim":     "#7A1515",
    "accent2":        "#60A5FA",
    "success":        "#4ADE80",
    "warning":        "#FBBF24",
    "danger":         "#F87171",
    "info":           "#60A5FA",
    "row_even":       "#141423",
    "row_odd":        "#181828",
    "excluded":       "#2A1A20",
    "selected_bar":   "#DC2626",
    "preview_bg":     "#07070D",
    "scroll_trough":  "#141423",
    "scroll_thumb":   "#2F2F47",
    "scroll_hover":   "#DC2626",
    "toolbar":        "#141423",
    "statusbar":      "#0B0B13",
    "popover_bg":     "#1F1F33",
    "input_bg":       "#2C2C44",
    "input_border":   "#4A4A6A",
    "kbd_bg":         "#1F1F33",
    "kbd_fg":         "#FCA5A5",
}

_LIGHT = {
    "bg":             "#F7F5F0",
    "panel":          "#FFFFFF",
    "panel_alt":      "#FBF8F1",
    "elevated":       "#FFFFFF",
    "elevated_hover": "#FEE2E2",
    "elevated_sel":   "#FECACA",
    "border":         "#E6E0D4",
    "border_strong":  "#D4CCBB",
    "divider":        "#EDE7D9",
    "fg":             "#1E2431",
    "fg_muted":       "#475569",
    "fg_dim":         "#94909E",
    "fg_on_accent":   "#FFFFFF",
    "accent":         "#DC2626",
    "accent_hover":   "#B91C1C",
    "accent_dim":     "#FCA5A5",
    "accent2":        "#1E2431",
    "success":        "#16A34A",
    "warning":        "#D97706",
    "danger":         "#DC2626",
    "info":           "#2563EB",
    "row_even":       "#FFFFFF",
    "row_odd":        "#FBF8F1",
    "excluded":       "#FDECE7",
    "selected_bar":   "#DC2626",
    "preview_bg":     "#1E2431",
    "scroll_trough":  "#EDE7D9",
    "scroll_thumb":   "#C9C0AE",
    "scroll_hover":   "#DC2626",
    "toolbar":        "#FFFFFF",
    "statusbar":      "#FBF8F1",
    "popover_bg":     "#FFFFFF",
    "input_bg":       "#F1EDE3",
    "input_border":   "#C9C0AE",
    "kbd_bg":         "#FEE2E2",
    "kbd_fg":         "#7A1515",
}

C: dict = dict(_DARK)


def _set_palette(dark: bool) -> None:
    src = _DARK if dark else _LIGHT
    C.clear()
    C.update(src)


# ──────────────────────────────────────────────────────────────────────────────
#  ASSETS HELPER
# ──────────────────────────────────────────────────────────────────────────────

def _assets_dir() -> str:
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        for sub in ("UI/assets", "assets"):
            p = os.path.join(base, sub)
            if os.path.isdir(p):
                return p
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def _load_icon(name: str, size: int = 20) -> QIcon:
    p = os.path.join(_assets_dir(), name)
    if os.path.isfile(p):
        return QIcon(p)
    return QIcon()


def _pil_to_qpixmap(img: Image.Image) -> QPixmap:
    """Convert a PIL Image to a QPixmap."""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg)


# ──────────────────────────────────────────────────────────────────────────────
#  QSS THEME GENERATOR
# ──────────────────────────────────────────────────────────────────────────────

def _build_qss(c: dict) -> str:
    return f"""
/* ── Base ── */
QMainWindow, QWidget {{
    background: {c['bg']};
    color: {c['fg']};
    font-family: "Segoe UI Variable", "Segoe UI", "Inter", "SF Pro Text", Arial, sans-serif;
    font-size: 13px;
}}

/* ── Menu Bar ── */
QMenuBar {{
    background: {c['toolbar']};
    color: {c['fg']};
    border-bottom: 1px solid {c['border']};
    padding: 2px 0;
}}
QMenuBar::item {{
    padding: 4px 12px;
    border-radius: 4px;
}}
QMenuBar::item:selected {{
    background: {c['elevated_hover']};
}}
QMenu {{
    background: {c['popover_bg']};
    color: {c['fg']};
    border: 1px solid {c['border_strong']};
    border-radius: 6px;
    padding: 4px 0;
}}
QMenu::item {{
    padding: 7px 28px 7px 14px;
    border-radius: 4px;
    margin: 1px 4px;
}}
QMenu::item:selected {{
    background: {c['elevated_hover']};
    color: {c['fg']};
}}
QMenu::separator {{
    height: 1px;
    background: {c['border']};
    margin: 4px 8px;
}}

/* ── Toolbar ── */
QToolBar {{
    background: {c['toolbar']};
    border-bottom: 1px solid {c['border']};
    spacing: 2px;
    padding: 4px 8px;
}}
QToolBar::separator {{
    background: {c['border']};
    width: 1px;
    margin: 6px 4px;
}}
QToolButton {{
    background: transparent;
    color: {c['fg_muted']};
    border: none;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}}
QToolButton:hover {{
    background: {c['elevated_hover']};
    color: {c['fg']};
}}
QToolButton:pressed {{
    background: {c['elevated']};
}}
QToolButton:disabled {{
    color: {c['fg_dim']};
}}
QToolButton[accent="true"] {{
    background: {c['accent']};
    color: {c['fg_on_accent']};
    border-radius: 6px;
    font-weight: 600;
    padding: 6px 14px;
}}
QToolButton[accent="true"]:hover {{
    background: {c['accent_hover']};
}}

/* ── Scroll Bars ── */
QScrollBar:vertical {{
    background: {c['scroll_trough']};
    width: 8px;
    margin: 0;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {c['scroll_thumb']};
    min-height: 24px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{
    background: {c['scroll_hover']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: {c['scroll_trough']};
    height: 8px;
    margin: 0;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal {{
    background: {c['scroll_thumb']};
    min-width: 24px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {c['scroll_hover']};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ── Splitter ── */
QSplitter::handle {{
    background: {c['border']};
}}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical   {{ height: 1px; }}

/* ── Status Bar ── */
QStatusBar {{
    background: {c['statusbar']};
    color: {c['fg_muted']};
    border-top: 1px solid {c['border']};
    font-size: 11px;
    padding: 0 8px;
}}

/* ── Line Edits ── */
QLineEdit {{
    background: {c['input_bg']};
    color: {c['fg']};
    border: 1px solid {c['input_border']};
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: {c['accent']};
}}
QLineEdit:focus {{
    border-color: {c['accent']};
}}

/* ── Push Buttons ── */
QPushButton {{
    background: {c['elevated']};
    color: {c['fg']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 500;
}}
QPushButton:hover {{
    background: {c['elevated_hover']};
    border-color: {c['border_strong']};
}}
QPushButton:pressed {{
    background: {c['elevated']};
}}
QPushButton[role="accent"] {{
    background: {c['accent']};
    color: {c['fg_on_accent']};
    border: none;
    font-weight: 600;
}}
QPushButton[role="accent"]:hover {{
    background: {c['accent_hover']};
}}

/* ── List Widget (command palette / sidebar) ── */
QListWidget {{
    background: {c['popover_bg']};
    color: {c['fg']};
    border: none;
    border-radius: 6px;
    outline: none;
}}
QListWidget::item {{
    padding: 8px 12px;
    border-radius: 4px;
    margin: 1px 4px;
}}
QListWidget::item:selected {{
    background: {c['elevated_sel']};
    color: {c['fg']};
}}
QListWidget::item:hover {{
    background: {c['elevated_hover']};
}}

/* ── Dock Widget ── */
QDockWidget {{
    color: {c['fg']};
    font-weight: 600;
    font-size: 12px;
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}}
QDockWidget::title {{
    background: {c['panel']};
    padding: 8px 12px;
    border-bottom: 1px solid {c['border']};
}}

/* ── Graphics View (preview) ── */
QGraphicsView {{
    background: {c['preview_bg']};
    border: none;
    outline: none;
}}

/* ── Checkbox ── */
QCheckBox {{
    color: {c['fg_muted']};
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 3px;
    border: 1px solid {c['input_border']};
    background: {c['input_bg']};
}}
QCheckBox::indicator:checked {{
    background: {c['accent']};
    border-color: {c['accent']};
    image: url(none);
}}

/* ── Dialog ── */
QDialog {{
    background: {c['bg']};
    color: {c['fg']};
    border: 1px solid {c['border_strong']};
    border-radius: 10px;
}}
"""


# ──────────────────────────────────────────────────────────────────────────────
#  PAGE CARD  (single page entry in the list panel)
# ──────────────────────────────────────────────────────────────────────────────

CARD_W = 110
CARD_H = 148
THUMB_W = 90
THUMB_H = 120


class _PageCard(QFrame):
    """Visual card for one PageRecord in the page-list panel."""

    clicked = Signal(int)        # emits the card's list index
    include_toggled = Signal(int, bool)

    def __init__(self, rec, idx: int, selected: bool = False, parent=None):
        super().__init__(parent)
        self.rec = rec
        self.idx = idx
        self._selected = selected
        self.setFixedSize(CARD_W, CARD_H)
        self.setContentsMargins(0, 0, 0, 0)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build()
        self._refresh_style()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # ── checkbox (include/exclude) ──
        self._chk = QCheckBox()
        self._chk.setChecked(self.rec.included.get())
        self._chk.setFixedSize(16, 16)
        self._chk.stateChanged.connect(self._on_check)

        # page number badge
        self._num_lbl = QLabel(str(self.idx + 1))
        self._num_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._num_lbl.setStyleSheet(f"color: {C['fg_dim']}; font-size: 10px;")

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.addWidget(self._chk)
        top_row.addStretch()
        top_row.addWidget(self._num_lbl)
        layout.addLayout(top_row)

        # ── thumbnail ──
        self._thumb = QLabel()
        self._thumb.setFixedSize(THUMB_W, THUMB_H)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setScaledContents(True)
        self._thumb.setStyleSheet(
            f"background: {C['elevated']}; border-radius: 3px;"
        )
        layout.addWidget(self._thumb, alignment=Qt.AlignmentFlag.AlignHCenter)

        # ── rotation badge ──
        rot = self.rec.orientation.get()
        rot_text = "" if rot == 0 else f"{rot}°"
        self._rot_lbl = QLabel(rot_text)
        self._rot_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._rot_lbl.setStyleSheet(
            f"color: {C['fg_dim']}; font-size: 9px; background: transparent;"
        )
        layout.addWidget(self._rot_lbl)

    def set_thumbnail(self, pixmap: QPixmap):
        self._thumb.setPixmap(pixmap)

    def set_selected(self, selected: bool):
        self._selected = selected
        self._refresh_style()

    def _refresh_style(self):
        included = self.rec.included.get()
        if self._selected:
            bg = C["elevated_sel"]
            border = C["accent"]
        elif not included:
            bg = C["excluded"]
            border = "transparent"
        else:
            bg = "transparent"
            border = "transparent"
        self.setStyleSheet(
            f"_PageCard {{ background: {bg}; border: 2px solid {border};"
            f" border-radius: 6px; }}"
        )

    def _on_check(self, state):
        self.rec.included.set(bool(state))
        self._refresh_style()
        self.include_toggled.emit(self.idx, bool(state))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.idx)
        super().mousePressEvent(event)

    def update_number(self, idx: int):
        self.idx = idx
        self._num_lbl.setText(str(idx + 1))

    def update_rotation(self):
        rot = self.rec.orientation.get()
        self._rot_lbl.setText("" if rot == 0 else f"{rot}°")


# ──────────────────────────────────────────────────────────────────────────────
#  TOAST NOTIFICATION
# ──────────────────────────────────────────────────────────────────────────────

class _Toast(QFrame):
    _KIND_COLORS = {
        "info":    ("#60A5FA", "#1E3A5F"),
        "success": ("#4ADE80", "#14432A"),
        "warning": ("#FBBF24", "#4A3A10"),
        "error":   ("#F87171", "#4A1515"),
    }

    def __init__(self, parent: QWidget, message: str,
                 kind: str = "info", duration_ms: int = 3000):
        super().__init__(parent)
        fg, bg = self._KIND_COLORS.get(kind, self._KIND_COLORS["info"])
        self.setStyleSheet(
            f"_Toast {{ background: {bg}; border: 1px solid {fg};"
            f" border-radius: 8px; padding: 0; }}"
        )
        lbl = QLabel(message, self)
        lbl.setStyleSheet(f"color: {fg}; padding: 10px 16px; font-size: 13px;")
        lbl.setWordWrap(True)
        lbl.adjustSize()

        self.resize(max(260, lbl.width() + 32), lbl.height() + 20)
        lbl.resize(self.width() - 32, self.height() - 20)
        lbl.move(16, 10)

        self._slide_in(parent, duration_ms)

    def _slide_in(self, parent: QWidget, duration_ms: int):
        pw, ph = parent.width(), parent.height()
        x = pw - self.width() - 20
        y_hidden = ph + 10
        y_show = ph - self.height() - 60
        self.move(x, y_hidden)
        self.show()
        self.raise_()

        anim_in = QPropertyAnimation(self, b"pos", self)
        anim_in.setDuration(280)
        anim_in.setStartValue(QPoint(x, y_hidden))
        anim_in.setEndValue(QPoint(x, y_show))
        anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim_in.start(QPropertyAnimation.DeletionPolicy.KeepWhenStopped)

        QTimer.singleShot(duration_ms, self._slide_out)

    def _slide_out(self):
        pw = self.parent().width()
        ph = self.parent().height()
        x = pw - self.width() - 20
        y_show = self.y()
        y_hidden = ph + 10

        anim_out = QPropertyAnimation(self, b"pos", self)
        anim_out.setDuration(240)
        anim_out.setStartValue(QPoint(x, y_show))
        anim_out.setEndValue(QPoint(x, y_hidden))
        anim_out.setEasingCurve(QEasingCurve.Type.InCubic)
        anim_out.finished.connect(self.deleteLater)
        anim_out.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)


# ──────────────────────────────────────────────────────────────────────────────
#  COMMAND PALETTE
# ──────────────────────────────────────────────────────────────────────────────

class _CommandPalette(QDialog):
    command_triggered = Signal(str)

    def __init__(self, commands: list[tuple[str, str]], parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.Popup)
        self.setMinimumWidth(480)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._commands = commands

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        container = QFrame(self)
        container.setObjectName("palette_container")
        container.setStyleSheet(
            f"#palette_container {{ background: {C['popover_bg']};"
            f" border: 1px solid {C['border_strong']}; border-radius: 10px; }}"
        )
        cl = QVBoxLayout(container)
        cl.setContentsMargins(8, 8, 8, 8)
        cl.setSpacing(6)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Type a command…")
        self._search.setFixedHeight(38)
        self._search.textChanged.connect(self._filter)
        cl.addWidget(self._search)

        self._list = QListWidget()
        self._list.setMaximumHeight(320)
        self._list.itemActivated.connect(self._accept)
        cl.addWidget(self._list)

        layout.addWidget(container)
        self._populate(commands)

        # keyboard navigation
        self._search.installEventFilter(self)

    def _populate(self, commands):
        self._list.clear()
        for key, label in commands:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self._list.addItem(item)
        if self._list.count():
            self._list.setCurrentRow(0)

    def _filter(self, text: str):
        q = text.lower()
        filtered = [(k, l) for k, l in self._commands
                    if not q or q in l.lower()]
        self._populate(filtered)

    def _accept(self, item: QListWidgetItem):
        key = item.data(Qt.ItemDataRole.UserRole)
        self.command_triggered.emit(key)
        self.accept()

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj is self._search and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Down:
                row = self._list.currentRow()
                self._list.setCurrentRow(min(row + 1, self._list.count() - 1))
                return True
            if key == Qt.Key.Key_Up:
                row = self._list.currentRow()
                self._list.setCurrentRow(max(row - 1, 0))
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                item = self._list.currentItem()
                if item:
                    self._accept(item)
                return True
            if key == Qt.Key.Key_Escape:
                self.reject()
                return True
        return super().eventFilter(obj, event)


# ──────────────────────────────────────────────────────────────────────────────
#  MAIN UI SHELL
# ──────────────────────────────────────────────────────────────────────────────

class PDFStudioUI(QMainWindow):
    """
    PySide6 UI shell.  Subclassed by the concrete PDFStudio class which
    also inherits PDFFeatures and PDFStudioBase via MRO:
        PDFStudio(PDFStudioUI, PDFFeatures, PDFStudioBase)
    """

    # ── Signals (Qt replacement for Tkinter callbacks) ──────────────────────
    page_clicked      = Signal(int)           # user clicked a page card
    pages_reordered   = Signal()              # drag-reorder completed
    include_changed   = Signal(int, bool)     # checkbox toggled on card idx
    theme_changed     = Signal(bool)          # True = dark

    def __init__(self, root=None):
        # `root` accepted for API compat with Tkinter version; ignored here.
        super().__init__()
        self._cards: list[_PageCard] = []
        self._selected_idx: int = -1
        self._dark_mode = True

        self.setWindowTitle("PDF Studio")
        self.setMinimumSize(1100, 660)
        self.resize(1360, 820)
        self._center_on_screen()

        self._apply_theme(dark=True)
        self._build_menubar()
        self._build_toolbar()
        self._build_statusbar()
        self._build_main()
        self._build_sidebar()

        # Placeholder: backend will populate this after __init__ via MRO
        # self.pages, self.undo_stack, etc. live in PDFStudioBase

    # ── Window helpers ───────────────────────────────────────────────────────

    def _center_on_screen(self):
        screen = QApplication.primaryScreen().availableGeometry()
        fg = self.frameGeometry()
        fg.moveCenter(screen.center())
        self.move(fg.topLeft())

    # ── Theme ────────────────────────────────────────────────────────────────

    def _apply_theme(self, dark: bool = True):
        self._dark_mode = dark
        _set_palette(dark)
        self.setStyleSheet(_build_qss(C))
        self.theme_changed.emit(dark)

    def toggle_theme(self):
        self._apply_theme(not self._dark_mode)
        # Re-build card styles
        for card in self._cards:
            card._refresh_style()
        # Refresh preview background
        if hasattr(self, "_scene"):
            self._scene.setBackgroundBrush(QColor(C["preview_bg"]))

    # ── Menu Bar ─────────────────────────────────────────────────────────────

    def _build_menubar(self):
        mb = self.menuBar()

        # File
        file_menu = mb.addMenu("File")
        self._act_open      = file_menu.addAction("Open PDF…")
        self._act_open.setShortcut(QKeySequence("Ctrl+O"))
        self._act_open.triggered.connect(lambda: self._safe("open_files"))

        self._act_save      = file_menu.addAction("Save…")
        self._act_save.setShortcut(QKeySequence("Ctrl+S"))
        self._act_save.triggered.connect(lambda: self._safe("save_pdf"))

        self._act_save_as   = file_menu.addAction("Save As…")
        self._act_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self._act_save_as.triggered.connect(lambda: self._safe("save_as"))

        file_menu.addSeparator()
        self._recent_menu   = file_menu.addMenu("Recent Files")
        file_menu.addSeparator()

        self._act_add_blank = file_menu.addAction("Add Blank Page")
        self._act_add_blank.triggered.connect(lambda: self._safe("add_blank_page"))

        file_menu.addSeparator()
        act_quit = file_menu.addAction("Quit")
        act_quit.setShortcut(QKeySequence("Ctrl+Q"))
        act_quit.triggered.connect(self.close)

        # Edit
        edit_menu = mb.addMenu("Edit")
        self._act_undo = edit_menu.addAction("Undo")
        self._act_undo.setShortcut(QKeySequence("Ctrl+Z"))
        self._act_undo.triggered.connect(lambda: self._safe("undo"))

        self._act_redo = edit_menu.addAction("Redo")
        self._act_redo.setShortcut(QKeySequence("Ctrl+Y"))
        self._act_redo.triggered.connect(lambda: self._safe("redo"))

        edit_menu.addSeparator()
        act_select_all = edit_menu.addAction("Select All")
        act_select_all.setShortcut(QKeySequence("Ctrl+A"))
        act_select_all.triggered.connect(lambda: self._safe("select_all"))

        act_deselect = edit_menu.addAction("Deselect All")
        act_deselect.triggered.connect(lambda: self._safe("deselect_all"))

        edit_menu.addSeparator()
        act_delete = edit_menu.addAction("Delete Selected")
        act_delete.setShortcut(QKeySequence("Delete"))
        act_delete.triggered.connect(lambda: self._safe("delete_selected"))

        # Pages
        pages_menu = mb.addMenu("Pages")
        pages_menu.addAction("Rotate CW").triggered.connect(
            lambda: self._safe("rotate_selected_cw"))
        pages_menu.addAction("Rotate CCW").triggered.connect(
            lambda: self._safe("rotate_selected_ccw"))
        pages_menu.addSeparator()
        pages_menu.addAction("Move Up").triggered.connect(
            lambda: self._safe("move_selected_up"))
        pages_menu.addAction("Move Down").triggered.connect(
            lambda: self._safe("move_selected_down"))
        pages_menu.addSeparator()
        pages_menu.addAction("Extract Selected").triggered.connect(
            lambda: self._safe("extract_selected"))
        pages_menu.addAction("Split PDF…").triggered.connect(
            lambda: self._safe("split_pdf"))

        # Tools
        tools_menu = mb.addMenu("Tools")
        tools_menu.addAction("OCR Page…").triggered.connect(
            lambda: self._safe("ocr_page"))
        tools_menu.addAction("Add Watermark…").triggered.connect(
            lambda: self._safe("add_watermark"))
        tools_menu.addAction("Add Bates Numbers…").triggered.connect(
            lambda: self._safe("bates_number"))
        tools_menu.addAction("Redact…").triggered.connect(
            lambda: self._safe("redact"))
        tools_menu.addAction("Add Signature…").triggered.connect(
            lambda: self._safe("add_signature"))
        tools_menu.addSeparator()
        tools_menu.addAction("Command Palette").setShortcut(QKeySequence("Ctrl+K"))

        # View
        view_menu = mb.addMenu("View")
        act_dark = view_menu.addAction("Toggle Dark / Light Mode")
        act_dark.setShortcut(QKeySequence("Ctrl+T"))
        act_dark.triggered.connect(self.toggle_theme)

        act_palette = view_menu.addAction("Command Palette")
        act_palette.setShortcut(QKeySequence("Ctrl+K"))
        act_palette.triggered.connect(self._show_command_palette)

        view_menu.addSeparator()
        act_grid = view_menu.addAction("Grid View")
        act_grid.setShortcut(QKeySequence("Ctrl+G"))
        act_grid.triggered.connect(lambda: self._safe("toggle_grid_view"))

        # Help
        help_menu = mb.addMenu("Help")
        help_menu.addAction("About PDF Studio").triggered.connect(
            self._show_about)

    # ── Toolbar ──────────────────────────────────────────────────────────────

    def _build_toolbar(self):
        tb = QToolBar("Main Toolbar", self)
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)
        self._toolbar = tb

        def _btn(label, glyph, cmd, tooltip="", accent=False):
            act = QAction(f"  {glyph}  {label}", self)
            act.setToolTip(tooltip or label)
            act.triggered.connect(lambda: self._safe(cmd))
            btn = tb.widgetForAction(tb.addAction(act))
            if btn and accent:
                btn.setProperty("accent", "true")
                btn.style().unpolish(btn)
                btn.style().polish(btn)
            return act

        self._act_tb_open  = _btn("Open",  "📂", "open_files",  "Open PDF files (Ctrl+O)")
        self._act_tb_save  = _btn("Save",  "💾", "save_pdf",    "Save merged PDF (Ctrl+S)", accent=True)
        tb.addSeparator()

        self._act_tb_undo  = _btn("Undo",  "↩", "undo",        "Undo last action (Ctrl+Z)")
        self._act_tb_redo  = _btn("Redo",  "↪", "redo",        "Redo (Ctrl+Y)")
        tb.addSeparator()

        _btn("Rotate ↻",  "↻",  "rotate_selected_cw",  "Rotate selected pages CW")
        _btn("Rotate ↺",  "↺",  "rotate_selected_ccw", "Rotate selected pages CCW")
        tb.addSeparator()

        _btn("Delete",    "✕",  "delete_selected",     "Delete selected pages")
        _btn("Extract",   "⎘",  "extract_selected",    "Extract selected to new PDF")
        tb.addSeparator()

        _btn("OCR",       "🔍", "ocr_page",            "Run OCR on selected page")
        _btn("Watermark", "🖊", "add_watermark",       "Add watermark")
        _btn("Redact",    "▓",  "redact",              "Redact selected region")
        tb.addSeparator()

        # Spacer to push theme toggle right
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding,
                             QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        act_theme = QAction("☀ / ☾", self)
        act_theme.setToolTip("Toggle dark / light theme (Ctrl+T)")
        act_theme.triggered.connect(self.toggle_theme)
        tb.addAction(act_theme)

        act_cmd = QAction("⌘ Commands", self)
        act_cmd.setToolTip("Command palette (Ctrl+K)")
        act_cmd.triggered.connect(self._show_command_palette)
        tb.addAction(act_cmd)

    # ── Status Bar ───────────────────────────────────────────────────────────

    def _build_statusbar(self):
        sb = QStatusBar(self)
        self.setStatusBar(sb)
        self._status_label = QLabel("Ready")
        self._status_label.setStyleSheet(f"color: {C['fg_muted']}; font-size: 11px;")
        sb.addWidget(self._status_label)

        self._page_count_label = QLabel("")
        self._page_count_label.setStyleSheet(f"color: {C['fg_dim']}; font-size: 11px;")
        sb.addPermanentWidget(self._page_count_label)

    def _set_status(self, msg: str):
        self._status_label.setText(msg)

    def _update_page_count(self):
        n = len(self._cards)
        included = sum(1 for c in self._cards if c.rec.included.get())
        self._page_count_label.setText(
            f"{included} / {n} page{'s' if n != 1 else ''}"
        )

    # ── Main Layout ──────────────────────────────────────────────────────────

    def _build_main(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(1)
        root_layout.addWidget(self._splitter)

        self._build_list_panel()
        self._build_preview()

        self._splitter.setSizes([260, 1100])
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)

    # ── Page List Panel ──────────────────────────────────────────────────────

    def _build_list_panel(self):
        panel = QFrame()
        panel.setMinimumWidth(160)
        panel.setMaximumWidth(380)
        panel.setObjectName("list_panel")
        panel.setStyleSheet(
            f"#list_panel {{ background: {C['panel']};"
            f" border-right: 1px solid {C['border']}; }}"
        )

        vl = QVBoxLayout(panel)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # ── search bar ──
        search_frame = QFrame()
        search_frame.setStyleSheet(
            f"background: {C['panel']}; border-bottom: 1px solid {C['border']};"
        )
        sf_layout = QHBoxLayout(search_frame)
        sf_layout.setContentsMargins(8, 6, 8, 6)
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("🔍 Filter pages…")
        self._search_edit.setFixedHeight(30)
        self._search_edit.textChanged.connect(self._filter_cards)
        sf_layout.addWidget(self._search_edit)
        vl.addWidget(search_frame)

        # ── scroll area containing card flow ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {C['panel']}; border: none; }}"
        )

        self._cards_container = QWidget()
        self._cards_container.setStyleSheet(
            f"background: {C['panel']};"
        )
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(8, 8, 8, 8)
        self._cards_layout.setSpacing(4)
        self._cards_layout.addStretch()

        scroll.setWidget(self._cards_container)
        vl.addWidget(scroll, stretch=1)

        self._list_scroll = scroll
        self._splitter.addWidget(panel)

    # ── Preview Panel ────────────────────────────────────────────────────────

    def _build_preview(self):
        preview_frame = QFrame()
        preview_frame.setObjectName("preview_frame")
        preview_frame.setStyleSheet(
            f"#preview_frame {{ background: {C['preview_bg']}; border: none; }}"
        )
        pl = QVBoxLayout(preview_frame)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)

        # ── preview toolbar (zoom controls) ──
        pvtb = QFrame()
        pvtb.setFixedHeight(36)
        pvtb.setStyleSheet(
            f"background: {C['panel']}; border-bottom: 1px solid {C['border']};"
        )
        pvtb_l = QHBoxLayout(pvtb)
        pvtb_l.setContentsMargins(8, 4, 8, 4)

        self._preview_label = QLabel("Preview")
        self._preview_label.setStyleSheet(
            f"color: {C['fg_muted']}; font-size: 11px;"
        )
        pvtb_l.addWidget(self._preview_label)
        pvtb_l.addStretch()

        for glyph, tip, cb in [
            ("−", "Zoom out", self._zoom_out),
            ("⊙", "Fit page", self._zoom_fit),
            ("+", "Zoom in",  self._zoom_in),
        ]:
            btn = QPushButton(glyph)
            btn.setFixedSize(26, 26)
            btn.setToolTip(tip)
            btn.clicked.connect(cb)
            btn.setStyleSheet(
                f"QPushButton {{ background: {C['elevated']}; color: {C['fg']};"
                f" border: 1px solid {C['border']}; border-radius: 4px;"
                f" font-size: 14px; }}"
                f"QPushButton:hover {{ background: {C['elevated_hover']}; }}"
            )
            pvtb_l.addWidget(btn)

        pl.addWidget(pvtb)

        # ── QGraphicsView for page rendering ──
        self._scene = QGraphicsScene(self)
        self._scene.setBackgroundBrush(QColor(C["preview_bg"]))

        self._preview_view = QGraphicsView(self._scene)
        self._preview_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._preview_view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self._preview_view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._preview_view.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._preview_view.setResizeAnchor(
            QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self._preview_view.setStyleSheet("border: none; background: transparent;")
        pl.addWidget(self._preview_view, stretch=1)

        self._preview_item: Optional[QGraphicsPixmapItem] = None
        self._preview_zoom_level = 1.0

        self._splitter.addWidget(preview_frame)

    # ── Bookmark Sidebar (Dock) ───────────────────────────────────────────────

    def _build_sidebar(self):
        dock = QDockWidget("Bookmarks", self)
        dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea |
                              Qt.DockWidgetArea.LeftDockWidgetArea)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable |
                         QDockWidget.DockWidgetFeature.DockWidgetMovable)

        sidebar_widget = QWidget()
        sl = QVBoxLayout(sidebar_widget)
        sl.setContentsMargins(6, 6, 6, 6)

        self._bookmark_list = QListWidget()
        self._bookmark_list.setStyleSheet(
            f"QListWidget {{ background: {C['panel']}; color: {C['fg_muted']};"
            f" border: none; font-size: 12px; }}"
        )
        sl.addWidget(self._bookmark_list)

        dock.setWidget(sidebar_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        dock.hide()
        self._sidebar_dock = dock

    # ── Zoom controls ────────────────────────────────────────────────────────

    def _zoom_in(self):
        self._preview_view.scale(1.2, 1.2)

    def _zoom_out(self):
        self._preview_view.scale(1 / 1.2, 1 / 1.2)

    def _zoom_fit(self):
        if self._preview_item:
            self._preview_view.fitInView(
                self._preview_item, Qt.AspectRatioMode.KeepAspectRatio)

    # ─────────────────────────────────────────────────────────────────────────
    #  CONTRACT METHODS  (same public surface as the Tkinter shell)
    # ─────────────────────────────────────────────────────────────────────────

    def add_page_row(self, rec, idx: int):
        """Insert a page card at position *idx* in the list panel."""
        card = _PageCard(rec, idx, parent=self._cards_container)
        card.clicked.connect(self._on_card_clicked)
        card.include_toggled.connect(self._on_include_toggled)

        # Insert before the trailing stretch
        self._cards_layout.insertWidget(idx, card)
        self._cards.insert(idx, card)

        # Load thumbnail asynchronously
        self._load_thumbnail(card)

        self._update_page_count()
        self._renumber_cards()

    def clear_page_rows(self):
        """Remove all page cards from the list panel."""
        for card in self._cards:
            self._cards_layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()
        self._selected_idx = -1
        self._update_page_count()

    def update_titlebar(self, title: Optional[str] = None):
        """Set window title to *title* (or reset to 'PDF Studio')."""
        self.setWindowTitle(title or "PDF Studio")

    def refresh_recent_menu(self):
        """Rebuild the Recent Files submenu from load_recent_files()."""
        self._recent_menu.clear()
        try:
            from pdf_studio_common import load_recent_files
            recent = load_recent_files()
        except Exception:
            recent = []
        if not recent:
            act = self._recent_menu.addAction("(none)")
            act.setEnabled(False)
            return
        for path in recent:
            act = self._recent_menu.addAction(Path(path).name)
            act.setToolTip(path)
            act.triggered.connect(
                lambda checked=False, p=path: self._safe("open_recent", p))

    def update_undo_redo(self):
        """Sync undo/redo enabled state from the undo stack."""
        can_undo = (hasattr(self, "undo_stack") and
                    self.undo_stack.can_undo())
        can_redo = (hasattr(self, "undo_stack") and
                    self.undo_stack.can_redo())
        self._act_undo.setEnabled(can_undo)
        self._act_redo.setEnabled(can_redo)
        self._act_tb_undo.setEnabled(can_undo)
        self._act_tb_redo.setEnabled(can_redo)

    def refresh_rows(self):
        """Rebuild all page cards from self.pages (called after bulk ops)."""
        self.clear_page_rows()
        if not hasattr(self, "pages"):
            return
        for idx, rec in enumerate(self.pages):
            self.add_page_row(rec, idx)

    def refresh_bookmarks_sidebar(self):
        """Populate the bookmark dock from the current PDF outline."""
        self._bookmark_list.clear()
        if not hasattr(self, "primary_path") or not self.primary_path:
            return
        try:
            import fitz
            doc = fitz.open(self.primary_path)
            toc = doc.get_toc()
            doc.close()
            for level, title, page in toc:
                indent = "  " * (level - 1)
                item = QListWidgetItem(f"{indent}{title}  (p.{page})")
                self._bookmark_list.addItem(item)
            if toc:
                self._sidebar_dock.show()
        except Exception:
            pass

    # ── Preview rendering ────────────────────────────────────────────────────

    def _render_preview(self, idx: int = -1):
        """Render page *idx* in the preview panel."""
        if idx < 0 or not hasattr(self, "pages") or idx >= len(self.pages):
            self._scene.clear()
            self._preview_item = None
            self._preview_label.setText("Preview")
            return

        rec = self.pages[idx]
        self._selected_idx = idx
        self._preview_label.setText(f"Page {idx + 1}")

        try:
            from pdf_studio_common import render_page_image_fitz
            vw = self._preview_view.viewport().width() or 700
            img = render_page_image_fitz(
                rec.source_path, rec.source_index,
                rec.orientation.get(), rec.orig_orient,
                target_w=max(vw - 40, 400))
            pix = _pil_to_qpixmap(img)
        except Exception:
            pix = QPixmap(400, 565)
            pix.fill(QColor(C["elevated"]))

        self._scene.clear()
        self._preview_item = QGraphicsPixmapItem(pix)
        self._preview_item.setTransformationMode(
            Qt.TransformationMode.SmoothTransformation)
        self._scene.addItem(self._preview_item)
        self._scene.setSceneRect(self._preview_item.boundingRect())
        self._zoom_fit()

        # Update card selection highlight
        for i, card in enumerate(self._cards):
            card.set_selected(i == idx)

    # ── Card event handlers ──────────────────────────────────────────────────

    def _on_card_clicked(self, idx: int):
        self._render_preview(idx)
        self.page_clicked.emit(idx)

    def _on_include_toggled(self, idx: int, state: bool):
        self._update_page_count()
        self.include_changed.emit(idx, state)

    def _filter_cards(self, text: str):
        q = text.lower().strip()
        for i, card in enumerate(self._cards):
            card.setVisible(not q or q in str(i + 1))

    def _renumber_cards(self):
        for i, card in enumerate(self._cards):
            card.update_number(i)

    # ── Thumbnail loading ────────────────────────────────────────────────────

    def _load_thumbnail(self, card: _PageCard):
        """Load thumbnail in a thread and update the card when done."""
        rec = card.rec

        class _ThumbWorker(QThread):
            done = Signal(QPixmap)

            def run(self_):
                try:
                    from pdf_studio_common import render_page_image_fitz, THUMB_W, THUMB_H
                    img = render_page_image_fitz(
                        rec.source_path, rec.source_index,
                        rec.orientation.get(), rec.orig_orient,
                        target_w=THUMB_W, target_h=THUMB_H, for_thumb=True)
                    pix = _pil_to_qpixmap(img)
                    self_.done.emit(pix)
                except Exception:
                    pass

        worker = _ThumbWorker(self)
        worker.done.connect(card.set_thumbnail)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    # ── Toast notifications ──────────────────────────────────────────────────

    def _show_toast(self, msg: str, kind: str = "info", duration_ms: int = 3000):
        _Toast(self, msg, kind=kind, duration_ms=duration_ms)

    # ── Command palette ──────────────────────────────────────────────────────

    _COMMANDS: list[tuple[str, str]] = [
        ("open_files",           "📂  Open PDF files"),
        ("save_pdf",             "💾  Save merged PDF"),
        ("save_as",              "💾  Save As…"),
        ("add_blank_page",       "📄  Add blank page"),
        ("undo",                 "↩  Undo"),
        ("redo",                 "↪  Redo"),
        ("rotate_selected_cw",   "↻  Rotate selected CW"),
        ("rotate_selected_ccw",  "↺  Rotate selected CCW"),
        ("delete_selected",      "✕  Delete selected pages"),
        ("extract_selected",     "⎘  Extract selected pages"),
        ("select_all",           "⬛  Select all pages"),
        ("deselect_all",         "⬜  Deselect all"),
        ("ocr_page",             "🔍  Run OCR on page"),
        ("add_watermark",        "🖊  Add watermark"),
        ("redact",               "▓  Redact region"),
        ("add_signature",        "✍  Add signature"),
        ("bates_number",         "#  Add Bates numbers"),
        ("split_pdf",            "✂  Split PDF"),
        ("toggle_grid_view",     "⊞  Toggle grid / list view"),
        ("toggle_theme",         "☀  Toggle dark / light theme"),
        ("refresh_bookmarks_sidebar", "🔖  Refresh bookmarks"),
    ]

    def _show_command_palette(self):
        pal = _CommandPalette(self._COMMANDS, parent=self)
        pal.command_triggered.connect(self._safe)
        # Center over the window
        pw, ph = self.width(), self.height()
        pw2, ph2 = pal.sizeHint().width(), pal.sizeHint().height()
        pal.move(
            self.x() + (pw - pw2) // 2,
            self.y() + max(60, ph // 5),
        )
        pal.exec()

    # ── Safe dispatcher (mirrors Tkinter _safe) ──────────────────────────────

    def _safe(self, method_name: str, *args):
        """Call self.<method_name>(*args) if it exists; show toast on error."""
        fn = getattr(self, method_name, None)
        if callable(fn):
            try:
                fn(*args)
            except Exception as exc:
                self._show_toast(f"Error in {method_name}: {exc}", "error")

    # ── About dialog ─────────────────────────────────────────────────────────

    def _show_about(self):
        QMessageBox.about(
            self, "About PDF Studio",
            "<b>PDF Studio</b><br>"
            "Professional PDF editor built with PySide6 / Qt6.<br><br>"
            "© 2026 — All rights reserved."
        )

    # ── File drag & drop ─────────────────────────────────────────────────────

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls()
                 if u.toLocalFile().lower().endswith(".pdf")]
        if paths:
            self._safe("open_files", paths)

    # ── Keyboard shortcuts ───────────────────────────────────────────────────

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()

        if key == Qt.Key.Key_K and mods & Qt.KeyboardModifier.ControlModifier:
            self._show_command_palette()
            return

        if key == Qt.Key.Key_Delete:
            self._safe("delete_selected")
            return

        if key in (Qt.Key.Key_Up, Qt.Key.Key_Left):
            new_idx = max(0, self._selected_idx - 1)
            self._render_preview(new_idx)
            return

        if key in (Qt.Key.Key_Down, Qt.Key.Key_Right):
            n = len(self._cards)
            if n:
                new_idx = min(n - 1, self._selected_idx + 1)
                self._render_preview(new_idx)
            return

        super().keyPressEvent(event)

    # ── Close ────────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        self._safe("_on_close")
        event.accept()


# ──────────────────────────────────────────────────────────────────────────────
#  STANDALONE DEMO  (python UI/pdf_studio_ui_qt.py)
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys as _sys

    app = QApplication(_sys.argv)
    app.setApplicationName("PDF Studio")

    win = PDFStudioUI()
    win.show()
    win._show_toast("PySide6 shell is running! Open a PDF to get started.", "success", 4000)

    _sys.exit(app.exec())
