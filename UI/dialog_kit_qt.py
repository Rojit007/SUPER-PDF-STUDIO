"""
UI/dialog_kit_qt.py
──────────────────────────────────────────────────────────────────────────────
PySide6 equivalents of the Tkinter helpers in UI/dialog_kit.py.

Drop-in API:
    themed_dialog(parent, title, w, h)  → QDialog pre-styled
    themed_button(parent, text, ...)    → QPushButton
    themed_entry(parent, var, ...)      → QLineEdit bound to _Var
    themed_check(parent, text, var)     → QCheckBox bound to _Var
    themed_radio(parent, text, var, v)  → QRadioButton bound to _Var
    section(parent, title)              → QGroupBox (returns its body widget)
    field_row(parent, label, widget)    → QHBoxLayout (added to parent)

All widgets inherit colours from UI.pdf_studio_ui_qt.C so theme swaps work.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QLineEdit, QTextEdit,
    QCheckBox, QRadioButton, QGroupBox, QFrame,
    QSlider, QColorDialog, QWidget, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor

from UI.pdf_studio_ui_qt import C


# ──────────────────────────────────────────────────────────────────────────────
#  themed_dialog
# ──────────────────────────────────────────────────────────────────────────────

def themed_dialog(parent, title: str, w: int = 480, h: int = 360):
    """
    Create a modal QDialog styled to match the current theme.
    Returned object has:
        dlg.body  – QWidget caller adds widgets into
        dlg.exec() – show modal
    """
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.resize(w, h)
    dlg.setModal(True)
    dlg.setStyleSheet(f"""
        QDialog {{
            background: {C['panel']};
            color: {C['fg']};
        }}
        QLabel {{
            color: {C['fg']};
            background: transparent;
        }}
        QLineEdit {{
            background: {C['input_bg']};
            color: {C['fg']};
            border: 1px solid {C['input_border']};
            border-radius: 4px;
            padding: 5px 8px;
        }}
        QLineEdit:focus {{
            border-color: {C['accent']};
        }}
        QPushButton {{
            background: {C['elevated']};
            color: {C['fg']};
            border: 1px solid {C['border']};
            border-radius: 5px;
            padding: 6px 14px;
        }}
        QPushButton:hover {{
            background: {C['elevated_hover']};
        }}
        QPushButton[role="accent"] {{
            background: {C['accent']};
            color: {C['fg_on_accent']};
            border: none;
            font-weight: 600;
        }}
        QPushButton[role="accent"]:hover {{
            background: {C['accent_hover']};
        }}
        QCheckBox {{
            color: {C['fg']};
        }}
        QRadioButton {{
            color: {C['fg']};
        }}
        QGroupBox {{
            color: {C['accent']};
            font-weight: 600;
            border: 1px solid {C['border']};
            border-radius: 6px;
            margin-top: 8px;
            padding-top: 8px;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 4px;
        }}
    """)

    root_layout = QVBoxLayout(dlg)
    root_layout.setContentsMargins(0, 0, 0, 0)
    root_layout.setSpacing(0)

    # Accent header strip
    strip = QFrame(dlg)
    strip.setFixedHeight(4)
    strip.setStyleSheet(f"background: {C['accent']}; border: none;")
    root_layout.addWidget(strip)

    # Title label
    title_frame = QFrame(dlg)
    title_frame.setStyleSheet(f"background: {C['panel']}; border: none;")
    tfl = QHBoxLayout(title_frame)
    tfl.setContentsMargins(20, 14, 20, 6)
    title_lbl = QLabel(title, title_frame)
    title_lbl.setStyleSheet(
        f"font-size: 14px; font-weight: 700; color: {C['fg']}; background: transparent;"
    )
    tfl.addWidget(title_lbl)
    root_layout.addWidget(title_frame)

    # Body area (caller adds widgets here)
    body = QWidget(dlg)
    body.setStyleSheet(f"background: {C['panel']}; border: none;")
    body_layout = QVBoxLayout(body)
    body_layout.setContentsMargins(20, 4, 20, 16)
    body_layout.setSpacing(8)
    root_layout.addWidget(body, stretch=1)

    dlg.body = body
    dlg.body_layout = body_layout
    return dlg


# ──────────────────────────────────────────────────────────────────────────────
#  themed_button
# ──────────────────────────────────────────────────────────────────────────────

def themed_button(parent, text: str = "", command=None,
                  style: str = "accent", glyph: str = "", width=None):
    """
    Flat themed button.  style ∈ {accent, ghost, success, danger, solid}.
    """
    label = " ".join(x for x in (glyph, text) if x)
    btn = QPushButton(label, parent)
    if width:
        btn.setFixedWidth(width * 8)  # rough em-to-px

    if style == "accent":
        btn.setProperty("role", "accent")
        btn.setStyleSheet(
            f"QPushButton {{ background: {C['accent']}; color: {C['fg_on_accent']};"
            f" border: none; border-radius: 5px; padding: 7px 16px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {C['accent_hover']}; }}"
        )
    elif style == "success":
        btn.setStyleSheet(
            f"QPushButton {{ background: {C['success']}; color: #fff; border: none;"
            f" border-radius: 5px; padding: 7px 16px; font-weight: 600; }}"
        )
    elif style == "danger":
        btn.setStyleSheet(
            f"QPushButton {{ background: {C['danger']}; color: #fff; border: none;"
            f" border-radius: 5px; padding: 7px 16px; font-weight: 600; }}"
        )
    elif style == "solid":
        btn.setStyleSheet(
            f"QPushButton {{ background: {C['elevated']}; color: {C['fg']};"
            f" border: 1px solid {C['border']}; border-radius: 5px; padding: 7px 16px; }}"
            f"QPushButton:hover {{ background: {C['elevated_hover']}; }}"
        )
    else:  # ghost
        btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {C['fg_muted']};"
            f" border: 1px solid {C['border_strong']}; border-radius: 5px; padding: 7px 14px; }}"
            f"QPushButton:hover {{ background: {C['elevated_hover']}; color: {C['fg']}; }}"
        )

    if callable(command):
        btn.clicked.connect(command)
    return btn


# ──────────────────────────────────────────────────────────────────────────────
#  themed_entry  (bound to a _Var proxy)
# ──────────────────────────────────────────────────────────────────────────────

def themed_entry(parent, var=None, width: int = 30, placeholder: str = "",
                 mono: bool = False, show: str = None):
    """
    QLineEdit bound to a _Var proxy.  Reading/writing var.get()/set() stays in sync.
    """
    edit = QLineEdit(parent)
    if mono:
        edit.setFont(__import__('PySide6.QtGui', fromlist=['QFont']).QFont("Consolas", 10))
    if show == "*":
        from PySide6.QtWidgets import QLineEdit as _QLE
        edit.setEchoMode(_QLE.EchoMode.Password)
    if placeholder:
        edit.setPlaceholderText(placeholder)
    if var is not None:
        v = var.get()
        edit.setText(str(v) if v is not None else "")
        edit.textChanged.connect(lambda t, v=var: v.set(t))

    edit.setStyleSheet(
        f"QLineEdit {{ background: {C['input_bg']}; color: {C['fg']};"
        f" border: 1px solid {C['input_border']}; border-radius: 4px;"
        f" padding: 5px 8px; }}"
        f"QLineEdit:focus {{ border-color: {C['accent']}; }}"
    )
    return edit


# ──────────────────────────────────────────────────────────────────────────────
#  themed_check  (bound to a _Var proxy)
# ──────────────────────────────────────────────────────────────────────────────

def themed_check(parent, text: str, var):
    chk = QCheckBox(text, parent)
    chk.setChecked(bool(var.get()))
    chk.stateChanged.connect(lambda s, v=var: v.set(bool(s)))
    chk.setStyleSheet(f"QCheckBox {{ color: {C['fg']}; }}")
    return chk


# ──────────────────────────────────────────────────────────────────────────────
#  themed_radio  (bound to a _Var proxy)
# ──────────────────────────────────────────────────────────────────────────────

def themed_radio(parent, text: str, var, value):
    btn = QRadioButton(text, parent)
    btn.setChecked(var.get() == value)
    btn.toggled.connect(lambda checked, v=var, val=value:
                        v.set(val) if checked else None)
    btn.setStyleSheet(f"QRadioButton {{ color: {C['fg']}; }}")
    return btn


# ──────────────────────────────────────────────────────────────────────────────
#  themed_spin
# ──────────────────────────────────────────────────────────────────────────────

def themed_spin(parent, var, from_: int = 0, to: int = 100):
    from PySide6.QtWidgets import QSpinBox
    sb = QSpinBox(parent)
    sb.setMinimum(from_)
    sb.setMaximum(to)
    sb.setValue(int(var.get() or 0))
    sb.valueChanged.connect(lambda v, var=var: var.set(v))
    sb.setStyleSheet(
        f"QSpinBox {{ background: {C['input_bg']}; color: {C['fg']};"
        f" border: 1px solid {C['input_border']}; border-radius: 4px; padding: 4px; }}"
    )
    return sb


# ──────────────────────────────────────────────────────────────────────────────
#  themed_scale  (QSlider bound to a _Var proxy)
# ──────────────────────────────────────────────────────────────────────────────

def themed_scale(parent, var, from_: int = 0, to: int = 100,
                 orient="horizontal"):
    slider = QSlider(
        Qt.Orientation.Horizontal if orient == "horizontal"
        else Qt.Orientation.Vertical,
        parent,
    )
    slider.setMinimum(from_)
    slider.setMaximum(to)
    slider.setValue(int(var.get() or 0))
    slider.valueChanged.connect(lambda v, var=var: var.set(v))
    slider.setStyleSheet(
        f"QSlider::groove:horizontal {{ background: {C['input_bg']}; height: 4px; border-radius: 2px; }}"
        f"QSlider::handle:horizontal {{ background: {C['accent']}; width: 14px; height: 14px;"
        f" border-radius: 7px; margin: -5px 0; }}"
    )
    return slider


# ──────────────────────────────────────────────────────────────────────────────
#  section  (labelled section wrapper → returns its body widget)
# ──────────────────────────────────────────────────────────────────────────────

def section(parent_layout_or_widget, title: str):
    """
    Creates a QGroupBox labelled *title* and adds it to *parent_layout_or_widget*.
    Returns the QGroupBox itself (caller packs widgets into it using a layout).
    """
    gb = QGroupBox(title)
    gb.setStyleSheet(
        f"QGroupBox {{ color: {C['accent']}; font-weight: 700;"
        f" border: 1px solid {C['border']}; border-radius: 6px;"
        f" margin-top: 8px; padding: 8px 4px 4px 4px; }}"
        f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}"
    )
    inner = QVBoxLayout(gb)
    inner.setContentsMargins(8, 4, 8, 8)
    inner.setSpacing(4)
    gb._inner = inner

    if hasattr(parent_layout_or_widget, "addWidget"):
        parent_layout_or_widget.addWidget(gb)
    elif hasattr(parent_layout_or_widget, "body_layout"):
        parent_layout_or_widget.body_layout.addWidget(gb)

    return gb


# ──────────────────────────────────────────────────────────────────────────────
#  field_row  (two-column label: widget row)
# ──────────────────────────────────────────────────────────────────────────────

def field_row(parent, label: str, widget, hint: str = ""):
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    lbl = QLabel(label + ":")
    lbl.setStyleSheet(f"color: {C['fg_muted']}; min-width: 90px;")
    lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    row.addWidget(lbl)
    row.addWidget(widget)
    if hint:
        hint_lbl = QLabel(hint)
        hint_lbl.setStyleSheet(f"color: {C['fg_dim']}; font-size: 11px;")
        row.addWidget(hint_lbl)
    row.addStretch()

    layout = None
    if hasattr(parent, "_inner"):
        layout = parent._inner
    elif hasattr(parent, "body_layout"):
        layout = parent.body_layout
    elif hasattr(parent, "layout") and parent.layout():
        layout = parent.layout()
    if layout:
        layout.addLayout(row)
    return row
