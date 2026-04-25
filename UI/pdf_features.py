"""
UI/pdf_features.py  –  PySide6 port
─────────────────────────────────────────────────────────────────────────────
Adobe Acrobat-Pro-parity features.  Mix into the PDFStudio hierarchy:

    class PDFStudio(PDFStudioUI, PDFFeatures, PDFStudioBase): ...

All dialogs now use PySide6 / QDialog.  No tkinter dependency.
"""
from __future__ import annotations
import math
import os
import re
import tempfile

import fitz
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QListWidget,
    QScrollArea, QSizePolicy, QTextEdit, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget, QPushButton,
)

from pdf_studio_common import _Var
from UI.pdf_studio_ui_qt import C
from UI.qt_compat import colorchooser, filedialog, messagebox, simpledialog
from UI.dialog_kit_qt import (
    field_row, section, themed_button, themed_check, themed_dialog,
    themed_entry, themed_radio, themed_scale, themed_spin,
)


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _toast(ui, msg: str, kind: str = "info") -> None:
    if hasattr(ui, "_show_toast"):
        ui._show_toast(msg, kind)
    try:
        ui.status_var.set(msg)
    except Exception:
        pass


def _current_pdf_path(ui):
    return getattr(ui, "primary_path", None)


def _fitz_pixmap_to_qpixmap(pix) -> QPixmap:
    qimg = QImage(pix.samples, pix.width, pix.height,
                  pix.stride, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg)


# ─────────────────────────────────────────────────────────────────────────────
#  Custom widgets used by feature dialogs
# ─────────────────────────────────────────────────────────────────────────────

class _SignatureCanvas(QWidget):
    """Free-draw signature surface backed by QPainter."""

    def __init__(self, width: int = 560, height: int = 180, parent=None):
        super().__init__(parent)
        self._strokes: list[list] = []
        self._pen_color = QColor("#0A1F3D")
        self._pen_size = 3
        self.setFixedSize(width, height)
        self.setStyleSheet(
            f"background: white; border: 1px solid {C['border']};"
        )
        self.setCursor(Qt.CursorShape.CrossCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._strokes.append([event.position().toPoint()])

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and self._strokes:
            self._strokes[-1].append(event.position().toPoint())
            self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), Qt.GlobalColor.white)
        pen = QPen(self._pen_color, self._pen_size,
                   Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap,
                   Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        for stroke in self._strokes:
            for i in range(1, len(stroke)):
                painter.drawLine(stroke[i - 1], stroke[i])

    def clear(self):
        self._strokes.clear()
        self.update()

    def set_pen_color(self, hex_color: str):
        self._pen_color = QColor(hex_color)

    def set_pen_size(self, size: int):
        self._pen_size = size
        self.update()

    def has_strokes(self) -> bool:
        return bool(self._strokes)

    def render_to_pil(self) -> Image.Image:
        img = Image.new("RGBA", (self.width(), self.height()), (255, 255, 255, 0))
        d = ImageDraw.Draw(img)
        col = self._pen_color.name().lstrip("#")
        rgb = tuple(int(col[i:i + 2], 16) for i in (0, 2, 4))
        for stroke in self._strokes:
            pts = [(p.x(), p.y()) for p in stroke]
            if len(pts) < 2:
                continue
            d.line(pts, fill=(*rgb, 255), width=self._pen_size, joint="curve")
        return img


class _MeasureCanvas(QLabel):
    """Page image that lets the user click two points and reports distance."""

    def __init__(self, pixmap: QPixmap, page_width: float, parent=None):
        super().__init__(parent)
        self._orig = pixmap
        self._ratio = pixmap.width() / max(page_width, 1)
        self._points: list = []
        self._result_cb = None
        self.setPixmap(pixmap)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

    def set_result_callback(self, cb):
        self._result_cb = cb

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._points.append(event.position().toPoint())
        self._redraw()
        if len(self._points) == 2:
            (x1, y1), (x2, y2) = [(p.x(), p.y()) for p in self._points]
            dx = (x2 - x1) / self._ratio
            dy = (y2 - y1) / self._ratio
            if self._result_cb:
                self._result_cb(math.hypot(dx, dy))
            self._points.clear()

    def _redraw(self):
        pm = self._orig.copy()
        painter = QPainter(pm)
        pen = QPen(QColor(C["accent"]), 2)
        painter.setPen(pen)
        for p in self._points:
            painter.drawEllipse(p, 4, 4)
        if len(self._points) == 2:
            painter.drawLine(self._points[0], self._points[1])
        painter.end()
        self.setPixmap(pm)

    def reset(self):
        self._points.clear()
        self.setPixmap(self._orig)


# ─────────────────────────────────────────────────────────────────────────────
#  Shared layout helpers
# ─────────────────────────────────────────────────────────────────────────────

def _muted_label(text: str, parent=None) -> QLabel:
    lbl = QLabel(text, parent)
    lbl.setStyleSheet(f"color: {C['fg_muted']}; font-size: 10px;")
    return lbl


def _btn_row(parent_widget, cancel_fn, ok_btn_text, ok_fn,
             ok_style: str = "accent") -> QHBoxLayout:
    row = QHBoxLayout()
    row.addStretch()
    row.addWidget(themed_button(parent_widget, "Cancel", cancel_fn, style="ghost"))
    row.addWidget(themed_button(parent_widget, ok_btn_text, ok_fn, style=ok_style))
    return row


# ─────────────────────────────────────────────────────────────────────────────
#  PDFFeatures mixin
# ─────────────────────────────────────────────────────────────────────────────

class PDFFeatures:
    """Mixin of all Acrobat-Pro-parity features."""

    # ══════════════════════════════════════════════════════════════════════
    # 1. BATES NUMBERING
    # ══════════════════════════════════════════════════════════════════════
    def bates_dialog(self):
        if not getattr(self, "pages", None):
            _toast(self, "Open a PDF first", "warn")
            return

        dlg = themed_dialog(self, "Bates Numbering", 460, 500)
        bl = dlg.body_layout

        prefix_v = _Var(value="EXHIBIT-")
        suffix_v = _Var(value="")
        start_v  = _Var(value=1)
        digits_v = _Var(value=4)
        pos_v    = _Var(value="bottom-right")
        scope_v  = _Var(value="all")

        s1 = section(bl, "Format")
        prefix_e = themed_entry(s1, var=prefix_v, width=18)
        field_row(s1, "Prefix", prefix_e)
        suffix_e = themed_entry(s1, var=suffix_v, width=18)
        field_row(s1, "Suffix", suffix_e)
        start_e  = themed_entry(s1, var=start_v,  width=8)
        field_row(s1, "Start #", start_e)
        digits_e = themed_entry(s1, var=digits_v, width=6)
        field_row(s1, "Digits", digits_e, "zero-pad width")

        s2 = section(bl, "Position")
        pos_row = QHBoxLayout()
        for val, lbl in [
            ("top-left", "TL"), ("top-center", "TC"), ("top-right", "TR"),
            ("bottom-left", "BL"), ("bottom-center", "BC"), ("bottom-right", "BR"),
        ]:
            pos_row.addWidget(themed_radio(s2, lbl, pos_v, val))
        s2._inner.addLayout(pos_row)

        s3 = section(bl, "Scope")
        scope_row = QHBoxLayout()
        for val, label in [("all", "All pages"), ("included", "Included only")]:
            scope_row.addWidget(themed_radio(s3, label, scope_v, val))
        s3._inner.addLayout(scope_row)

        s4 = section(bl, "Preview")
        preview_lbl = QLabel("EXHIBIT-0001", s4)
        preview_lbl.setStyleSheet(
            f"background: {C['elevated']}; color: {C['fg']};"
            f" font-family: Consolas,monospace; font-size: 14px; font-weight: bold;"
            f" padding: 10px 14px;"
        )
        s4._inner.addWidget(preview_lbl)

        def _upd(_=None):
            try:
                n = int(start_v.get())
            except Exception:
                n = 1
            d = max(1, int(digits_v.get() or 4))
            preview_lbl.setText(f"{prefix_v.get()}{n:0{d}d}{suffix_v.get()}")

        prefix_e.textChanged.connect(_upd)
        suffix_e.textChanged.connect(_upd)
        start_e.textChanged.connect(_upd)
        digits_e.textChanged.connect(_upd)

        bl.addLayout(_btn_row(
            dlg.body, dlg.reject, "Apply & Save",
            lambda: self._run_bates(
                dlg, prefix_v.get(), suffix_v.get(),
                int(start_v.get()), int(digits_v.get() or 4),
                pos_v.get(), scope_v.get()),
        ))
        dlg.exec()

    def _run_bates(self, dlg, prefix, suffix, start, digits, pos, scope):
        out = filedialog.asksaveasfilename(
            title="Save stamped PDF", defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")])
        if not out:
            return
        dlg.accept()
        path = _current_pdf_path(self)
        if not path:
            _toast(self, "No source PDF", "error")
            return
        try:
            doc = fitz.open(path)
            n = start
            for i, page in enumerate(doc):
                rec = self.pages[i] if i < len(self.pages) else None
                if scope == "included" and rec and not rec.included.get():
                    continue
                text = f"{prefix}{n:0{digits}d}{suffix}"
                r = page.rect
                margin = 24
                y = margin if "top" in pos else r.height - margin
                if "left" in pos:
                    x = margin
                elif "right" in pos:
                    x = r.width - margin - 8 * len(text)
                else:
                    x = r.width / 2 - 4 * len(text)
                page.insert_text(fitz.Point(x, y), text,
                                 fontsize=11, color=(0.85, 0.35, 0.15),
                                 fontname="helv")
                n += 1
            doc.save(out)
            doc.close()
            _toast(self, f"Bates-stamped PDF saved → {os.path.basename(out)}", "success")
        except Exception as e:
            messagebox.showerror("Bates error", str(e))

    # ══════════════════════════════════════════════════════════════════════
    # 2. KEYWORD BULK REDACTION
    # ══════════════════════════════════════════════════════════════════════
    def keyword_redact_dialog(self):
        if not _current_pdf_path(self):
            _toast(self, "Open a PDF first", "warn")
            return

        dlg = themed_dialog(self, "Keyword Bulk Redaction", 500, 520)
        bl = dlg.body_layout

        bl.addWidget(_muted_label(
            "Enter one term per line. Regex supported when enabled.", dlg.body))

        txt = QTextEdit(dlg.body)
        txt.setFont(QFont("Consolas", 10))
        txt.setStyleSheet(
            f"background: {C['elevated']}; color: {C['fg']};"
            f" border: 1px solid {C['border']}; border-radius: 4px; padding: 6px;"
        )
        txt.setPlainText("Confidential\nSocial Security\n\\b\\d{3}-\\d{2}-\\d{4}\\b\n")
        bl.addWidget(txt)

        use_regex_v = _Var(value=True)
        case_v      = _Var(value=False)
        scope_v     = _Var(value="all")

        s = section(bl, "Options")
        s._inner.addWidget(themed_check(s, "Use regex patterns", use_regex_v))
        s._inner.addWidget(themed_check(s, "Case sensitive", case_v))

        s2 = section(bl, "Scope")
        sc_row = QHBoxLayout()
        for v, label in [("all", "All pages"), ("included", "Included only")]:
            sc_row.addWidget(themed_radio(s2, label, scope_v, v))
        s2._inner.addLayout(sc_row)

        def _run():
            terms = [t for t in txt.toPlainText().splitlines() if t.strip()]
            if not terms:
                _toast(self, "Add at least one term", "warn")
                return
            out = filedialog.asksaveasfilename(
                title="Save redacted PDF", defaultextension=".pdf",
                filetypes=[("PDF files", "*.pdf")])
            if not out:
                return
            dlg.accept()
            self._run_keyword_redact(terms, bool(use_regex_v.get()),
                                     bool(case_v.get()), scope_v.get(), out)

        bl.addLayout(_btn_row(dlg.body, dlg.reject, "Redact & Save", _run))
        dlg.exec()

    def _run_keyword_redact(self, terms, use_regex, case_sens, scope, out):
        path = _current_pdf_path(self)
        if not path:
            return
        try:
            doc = fitz.open(path)
            total = 0
            flags = 0 if case_sens else re.IGNORECASE
            for i, page in enumerate(doc):
                rec = self.pages[i] if i < len(self.pages) else None
                if scope == "included" and rec and not rec.included.get():
                    continue
                page_text = page.get_text()
                rects = []
                for term in terms:
                    if use_regex:
                        try:
                            pat = re.compile(term, flags)
                        except re.error:
                            continue
                        for m in pat.finditer(page_text):
                            rects.extend(page.search_for(m.group(0), quads=False))
                    else:
                        rects.extend(page.search_for(term))
                for r in rects:
                    page.add_redact_annot(r, fill=(0, 0, 0))
                    total += 1
                if rects:
                    page.apply_redactions()
            doc.save(out)
            doc.close()
            _toast(self, f"Redacted {total} matches → {os.path.basename(out)}", "success")
        except Exception as e:
            messagebox.showerror("Redaction error", str(e))

    # ══════════════════════════════════════════════════════════════════════
    # 3. SIGNATURE TOOL
    # ══════════════════════════════════════════════════════════════════════
    def signature_dialog(self):
        if not getattr(self, "pages", None):
            _toast(self, "Open a PDF first", "warn")
            return

        dlg = themed_dialog(self, "Signature Tool", 640, 500)
        bl = dlg.body_layout

        bl.addWidget(_muted_label("Draw your signature below:", dlg.body))

        canvas = _SignatureCanvas(560, 180, dlg.body)
        bl.addWidget(canvas)

        pen_v   = _Var(value=3)
        color_v = _Var(value="#0A1F3D")

        ctrl = QHBoxLayout()
        ctrl.addWidget(_muted_label("Pen size:", dlg.body))
        slider = themed_scale(dlg.body, pen_v, from_=1, to=10)
        slider.valueChanged.connect(canvas.set_pen_size)
        ctrl.addWidget(slider)

        def pick_color():
            c = colorchooser.askcolor(color=color_v.get(), parent=dlg)
            if c and c[1]:
                color_v.set(c[1])
                canvas.set_pen_color(c[1])

        ctrl.addWidget(themed_button(dlg.body, "Color", pick_color, style="solid"))
        ctrl.addWidget(themed_button(dlg.body, "Clear", canvas.clear, style="ghost"))
        ctrl.addStretch()
        bl.addLayout(ctrl)

        page_v = _Var(value=max(1, self._preview_index + 1
                                if self._preview_index >= 0 else 1))
        x_v = _Var(value=0.65)
        y_v = _Var(value=0.82)
        w_v = _Var(value=0.25)

        s = section(bl, "Placement")
        pr = QHBoxLayout()
        pr.addWidget(_muted_label("Page:", s))
        pr.addWidget(themed_spin(s, page_v, from_=1, to=max(1, len(self.pages))))
        for lbl, v in [("X:", x_v), ("Y:", y_v), ("W:", w_v)]:
            pr.addWidget(_muted_label(lbl, s))
            pr.addWidget(themed_entry(s, var=v, width=5))
        pr.addStretch()
        s._inner.addLayout(pr)

        def apply_sig():
            if not canvas.has_strokes():
                _toast(self, "Please draw a signature first", "warn")
                return
            img = canvas.render_to_pil()
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp.close()
            img.save(tmp.name)
            idx = page_v.get() - 1
            if 0 <= idx < len(self.pages):
                if hasattr(self, "_push_undo"):
                    self._push_undo("apply signature")
                aspect = 180 / 560
                self.pages[idx].annotations.append({
                    "type": "stamp", "image_path": tmp.name,
                    "x": x_v.get(), "y": y_v.get(),
                    "w": w_v.get(), "h": w_v.get() * aspect,
                })
                _toast(self,
                       f"Signature placed on page {idx + 1}  —  save PDF to commit",
                       "success")
            dlg.accept()

        bl.addLayout(_btn_row(dlg.body, dlg.reject, "Apply to page", apply_sig))
        dlg.exec()

    # ══════════════════════════════════════════════════════════════════════
    # 4. HYPERLINK EDITOR
    # ══════════════════════════════════════════════════════════════════════
    def hyperlinks_dialog(self):
        path = _current_pdf_path(self)
        if not path:
            _toast(self, "Open a PDF first", "warn")
            return

        dlg = themed_dialog(self, "Hyperlink Editor", 720, 500)
        bl = dlg.body_layout

        doc = fitz.open(path)
        links = []
        for i, page in enumerate(doc):
            for ln in page.get_links():
                links.append({
                    "page_index": i,
                    "uri": ln.get("uri", ""),
                    "kind": ln.get("kind", 0),
                    "from": ln.get("from"),
                    "original": ln,
                })

        bl.addWidget(_muted_label(
            f"Found {len(links)} hyperlinks across {len(doc)} pages.", dlg.body))

        tree = QTreeWidget(dlg.body)
        tree.setHeaderLabels(["Page", "Type", "Target / URI"])
        tree.setColumnWidth(0, 60)
        tree.setColumnWidth(1, 90)
        tree.setColumnWidth(2, 480)
        tree.setStyleSheet(
            f"QTreeWidget {{ background: {C['elevated']}; color: {C['fg']};"
            f" border: 1px solid {C['border']}; }}"
            f"QTreeWidget::item:selected {{ background: {C['accent']}; color: {C['fg_on_accent']}; }}"
        )
        kinds = {1: "GOTO", 2: "URI", 3: "LAUNCH", 4: "GOTOR", 5: "NAMED"}
        for ln in links:
            target = ln["uri"] if ln["uri"] else f"page {ln['original'].get('page', '?')}"
            QTreeWidgetItem(tree, [
                str(ln["page_index"] + 1),
                kinds.get(ln["kind"], "?"),
                target,
            ])
        bl.addWidget(tree)

        def _sel_link():
            items = tree.selectedItems()
            if not items:
                return None
            return links[tree.indexOfTopLevelItem(items[0])]

        def edit_link():
            ln = _sel_link()
            if not ln:
                return
            ask = simpledialog.askstring(
                "Edit Hyperlink", "New URI / page target:",
                initialvalue=ln["uri"], parent=dlg)
            if ask is None:
                return
            try:
                page = doc[ln["page_index"]]
                page.delete_link(ln["original"])
                page.insert_link({"kind": 2, "from": ln["from"], "uri": ask})
                items = tree.selectedItems()
                if items:
                    items[0].setText(2, ask)
                    items[0].setText(1, "URI")
                _toast(self, "Link updated", "success")
            except Exception as e:
                messagebox.showerror("Error", str(e))

        def remove_link():
            ln = _sel_link()
            if not ln:
                return
            try:
                doc[ln["page_index"]].delete_link(ln["original"])
                items = tree.selectedItems()
                if items:
                    tree.takeTopLevelItem(tree.indexOfTopLevelItem(items[0]))
                _toast(self, "Link removed", "info")
            except Exception as e:
                messagebox.showerror("Error", str(e))

        def save_pdf():
            out = filedialog.asksaveasfilename(
                title="Save linked PDF", defaultextension=".pdf",
                filetypes=[("PDF files", "*.pdf")])
            if not out:
                return
            try:
                doc.save(out)
                _toast(self, f"Saved → {os.path.basename(out)}", "success")
                dlg.accept()
            except Exception as e:
                messagebox.showerror("Save error", str(e))

        btn_row = QHBoxLayout()
        btn_row.addWidget(themed_button(dlg.body, "Edit",   edit_link,   style="solid"))
        btn_row.addWidget(themed_button(dlg.body, "Remove", remove_link, style="danger"))
        btn_row.addStretch()
        btn_row.addWidget(themed_button(dlg.body, "Save PDF", save_pdf,  style="accent"))
        bl.addLayout(btn_row)

        dlg.finished.connect(lambda _: doc.close())
        dlg.exec()

    # ══════════════════════════════════════════════════════════════════════
    # 5. ATTACHMENT EXTRACTOR
    # ══════════════════════════════════════════════════════════════════════
    def attachments_dialog(self):
        path = _current_pdf_path(self)
        if not path:
            _toast(self, "Open a PDF first", "warn")
            return

        dlg = themed_dialog(self, "Attachment Extractor", 520, 420)
        bl = dlg.body_layout

        doc = fitz.open(path)
        n = doc.embfile_count()
        bl.addWidget(_muted_label(f"{n} embedded attachment(s) found.", dlg.body))

        lb = QListWidget(dlg.body)
        lb.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        lb.setStyleSheet(
            f"QListWidget {{ background: {C['elevated']}; color: {C['fg']};"
            f" border: 1px solid {C['border']}; }}"
            f"QListWidget::item:selected {{ background: {C['accent']}; color: {C['fg_on_accent']}; }}"
        )
        names = []
        for i in range(n):
            info = doc.embfile_info(i)
            names.append(info["filename"])
            lb.addItem(f"  {info['filename']:<40}  {info.get('size', 0) / 1024:.1f} KB")
        bl.addWidget(lb)

        def extract_selected():
            sel = [lb.row(item) for item in lb.selectedItems()]
            if not sel:
                return
            out_dir = filedialog.askdirectory(title="Extract to folder")
            if not out_dir:
                return
            for idx in sel:
                data = doc.embfile_get(idx)
                with open(os.path.join(out_dir, names[idx]), "wb") as f:
                    f.write(data)
            _toast(self, f"Extracted {len(sel)} file(s) to {out_dir}", "success")

        def extract_all():
            if n == 0:
                return
            out_dir = filedialog.askdirectory(title="Extract all to folder")
            if not out_dir:
                return
            for i in range(n):
                data = doc.embfile_get(i)
                with open(os.path.join(out_dir, names[i]), "wb") as f:
                    f.write(data)
            _toast(self, f"Extracted {n} file(s)", "success")

        btn_row = QHBoxLayout()
        btn_row.addWidget(themed_button(dlg.body, "Extract selected",
                                        extract_selected, style="solid"))
        btn_row.addWidget(themed_button(dlg.body, "Extract all",
                                        extract_all, style="accent"))
        btn_row.addStretch()
        btn_row.addWidget(themed_button(dlg.body, "Close", dlg.accept, style="ghost"))
        bl.addLayout(btn_row)

        dlg.finished.connect(lambda _: doc.close())
        dlg.exec()

    # ══════════════════════════════════════════════════════════════════════
    # 6. TOC AUTO-GENERATOR
    # ══════════════════════════════════════════════════════════════════════
    def toc_auto_dialog(self):
        path = _current_pdf_path(self)
        if not path:
            _toast(self, "Open a PDF first", "warn")
            return

        dlg = themed_dialog(self, "Auto-generate TOC", 520, 540)
        bl = dlg.body_layout

        bl.addWidget(_muted_label(
            "Scan the PDF for headings and propose bookmarks.", dlg.body))

        min_size_v = _Var(value=14.0)
        max_len_v  = _Var(value=80)

        s = section(bl, "Heuristic")
        field_row(s, "Min font size",
                  themed_entry(s, var=min_size_v, width=6),
                  "points (larger = fewer candidates)")
        field_row(s, "Max length",
                  themed_entry(s, var=max_len_v, width=6),
                  "chars (filters long paragraphs)")

        lb = QListWidget(dlg.body)
        lb.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        lb.setFont(QFont("Consolas", 9))
        lb.setStyleSheet(
            f"QListWidget {{ background: {C['elevated']}; color: {C['fg']};"
            f" border: 1px solid {C['border']}; }}"
            f"QListWidget::item:selected {{ background: {C['accent']}; color: {C['fg_on_accent']}; }}"
        )
        bl.addWidget(lb)

        candidates: list[dict] = []

        def scan():
            candidates.clear()
            lb.clear()
            try:
                doc = fitz.open(path)
                for i, page in enumerate(doc):
                    d = page.get_text("dict")
                    for block in d.get("blocks", []):
                        for line in block.get("lines", []):
                            for sp in line.get("spans", []):
                                text = sp["text"].strip()
                                try:
                                    sz = float(min_size_v.get())
                                    mx = int(max_len_v.get())
                                except Exception:
                                    sz, mx = 14.0, 80
                                if (sp["size"] >= sz and
                                        3 <= len(text) <= mx and
                                        not text.endswith(".")):
                                    candidates.append({
                                        "title": text, "page": i,
                                        "size": sp["size"],
                                    })
                                    lb.addItem(
                                        f"  p.{i+1:<4}  {sp['size']:.0f}pt   {text[:60]}")
                                    break
                            else:
                                continue
                            break
                doc.close()
                _toast(self, f"Found {len(candidates)} headings", "info")
            except Exception as e:
                messagebox.showerror("Scan error", str(e))

        def add_bookmarks():
            sel_items = lb.selectedItems()
            indices = ([lb.row(it) for it in sel_items]
                       if sel_items else list(range(lb.count())))
            count = 0
            for i in indices:
                if i < len(candidates):
                    c = candidates[i]
                    self._bookmarks.append({"title": c["title"], "page": c["page"]})
                    count += 1
            if hasattr(self, "refresh_bookmarks_sidebar"):
                self.refresh_bookmarks_sidebar()
            _toast(self, f"Added {count} bookmarks", "success")
            dlg.accept()

        btn_row = QHBoxLayout()
        btn_row.addWidget(themed_button(dlg.body, "Scan", scan, style="solid"))
        btn_row.addStretch()
        btn_row.addWidget(themed_button(dlg.body, "Add selected as bookmarks",
                                        add_bookmarks, style="accent"))
        bl.addLayout(btn_row)
        dlg.exec()

    # ══════════════════════════════════════════════════════════════════════
    # 7. MEASURING TOOL
    # ══════════════════════════════════════════════════════════════════════
    def measure_dialog(self):
        if not getattr(self, "pages", None):
            _toast(self, "Open a PDF first", "warn")
            return

        dlg = themed_dialog(self, "Measuring Tool", 720, 540)
        bl = dlg.body_layout

        bl.addWidget(_muted_label(
            "Click two points to measure distance. 1 unit = 1 point (72 pts = 1 inch).",
            dlg.body))

        scale_v = _Var(value=1.0)
        unit_v  = _Var(value="pt")

        ctl = QHBoxLayout()
        ctl.addWidget(_muted_label("Scale: 1 pt =", dlg.body))
        ctl.addWidget(themed_entry(dlg.body, var=scale_v, width=6))
        ctl.addWidget(_muted_label("units", dlg.body))
        ctl.addWidget(themed_entry(dlg.body, var=unit_v, width=8))
        ctl.addStretch()
        bl.addLayout(ctl)

        # Render current page
        idx = max(0, self._preview_index)
        rec = self.pages[idx]
        doc = fitz.open(rec.source_path)
        page = doc[rec.source_index]
        pix = page.get_pixmap(matrix=fitz.Matrix(1.3, 1.3), alpha=False)
        page_w = page.rect.width
        doc.close()
        qpix = _fitz_pixmap_to_qpixmap(pix)

        canvas = _MeasureCanvas(qpix, page_w, dlg.body)
        scroll = QScrollArea(dlg.body)
        scroll.setWidget(canvas)
        scroll.setWidgetResizable(False)
        scroll.setStyleSheet(f"background: {C['preview_bg']}; border: none;")
        bl.addWidget(scroll)

        result_lbl = QLabel("—", dlg.body)
        result_lbl.setStyleSheet(
            f"color: {C['accent']}; font-family: Consolas,monospace;"
            f" font-size: 11px; font-weight: bold;")
        bl.addWidget(result_lbl)

        def on_measure(dist_pt: float):
            try:
                s = float(scale_v.get())
            except Exception:
                s = 1.0
            unit = unit_v.get() or "pt"
            result_lbl.setText(
                f"Distance: {dist_pt:.1f} pt   "
                f"({dist_pt / 72:.2f} in   ·   "
                f"{dist_pt * s:.2f} {unit})"
            )

        canvas.set_result_callback(on_measure)

        btn_row = QHBoxLayout()
        btn_row.addWidget(themed_button(
            dlg.body, "Reset",
            lambda: (canvas.reset(), result_lbl.setText("—")),
            style="solid"))
        btn_row.addStretch()
        btn_row.addWidget(themed_button(dlg.body, "Close", dlg.accept, style="ghost"))
        bl.addLayout(btn_row)
        dlg.exec()

    # ══════════════════════════════════════════════════════════════════════
    # 8. AUTO-CROP (whitespace detection)
    # ══════════════════════════════════════════════════════════════════════
    def auto_crop_dialog(self):
        if not getattr(self, "pages", None):
            _toast(self, "Open a PDF first", "warn")
            return

        dlg = themed_dialog(self, "Auto-Crop Whitespace", 420, 320)
        bl = dlg.body_layout

        threshold_v = _Var(value=240)
        padding_v   = _Var(value=8)
        scope_v     = _Var(value="all")

        s = section(bl, "Settings")
        field_row(s, "Brightness threshold",
                  themed_entry(s, var=threshold_v, width=6),
                  "0-255 (240 = near-white)")
        field_row(s, "Padding (points)",
                  themed_entry(s, var=padding_v, width=6),
                  "margin to preserve")

        s2 = section(bl, "Scope")
        sc_row = QHBoxLayout()
        for v, label in [("all", "All pages"), ("included", "Included only")]:
            sc_row.addWidget(themed_radio(s2, label, scope_v, v))
        s2._inner.addLayout(sc_row)

        def _run():
            dlg.accept()
            self._run_auto_crop(
                int(threshold_v.get()), int(padding_v.get()), scope_v.get())

        bl.addLayout(_btn_row(dlg.body, dlg.reject, "Detect & Apply", _run))
        dlg.exec()

    def _run_auto_crop(self, threshold, padding, scope):
        if hasattr(self, "_push_undo"):
            self._push_undo("auto-crop")
        applied = 0
        target = ([r for r in self.pages if r.included.get()]
                  if scope == "included" else self.pages)
        for rec in target:
            if rec.is_blank:
                continue
            try:
                doc = fitz.open(rec.source_path)
                page = doc[rec.source_index]
                pix = page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2), alpha=False)
                img = Image.frombytes("RGB", [pix.width, pix.height],
                                      pix.samples).convert("L")
                doc.close()
                bw  = img.point(lambda p: 0 if p < threshold else 255)
                inv = Image.eval(bw, lambda p: 255 - p)
                bbox = inv.getbbox()
                if not bbox:
                    continue
                left_px, t, right_px, b = bbox
                sx = page.rect.width  / pix.width
                sy = page.rect.height / pix.height
                rec.annotations.append({
                    "type":   "crop",
                    "left":   max(0, left_px * sx - padding),
                    "top":    max(0, t * sy - padding),
                    "right":  max(0, (pix.width  - right_px) * sx - padding),
                    "bottom": max(0, (pix.height - b)        * sy - padding),
                })
                applied += 1
            except Exception:
                continue
        _toast(self, f"Auto-crop queued on {applied} page(s). Save PDF to apply.",
               "success")

    # ══════════════════════════════════════════════════════════════════════
    # 9. FORM FIELDS EDITOR (fill + flatten)
    # ══════════════════════════════════════════════════════════════════════
    def form_fields_dialog(self):
        path = _current_pdf_path(self)
        if not path:
            _toast(self, "Open a PDF first", "warn")
            return
        try:
            reader = PdfReader(path)
            fields     = reader.get_form_text_fields() or {}
            all_fields = reader.get_fields() or {}
        except Exception as e:
            messagebox.showerror("Error", f"Could not read form: {e}")
            return
        if not all_fields:
            _toast(self, "No AcroForm fields found", "warn")
            return

        dlg = themed_dialog(self, "Form Fields", 560, 580)
        bl = dlg.body_layout

        bl.addWidget(_muted_label(
            f"{len(all_fields)} form field(s). Edit values below:", dlg.body))

        scroll = QScrollArea(dlg.body)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {C['panel']}; border: none; }}"
        )
        inner = QWidget()
        inner.setStyleSheet(f"background: {C['panel']};")
        inner_layout = QVBoxLayout(inner)
        inner_layout.setSpacing(4)
        inner_layout.setContentsMargins(8, 8, 8, 8)
        scroll.setWidget(inner)
        bl.addWidget(scroll)

        vars_map: dict[str, _Var] = {}
        for name, _info in all_fields.items():
            row_w = QWidget(inner)
            row_w.setStyleSheet(f"background: {C['panel']};")
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(0, 0, 0, 0)
            name_lbl = QLabel(name[:30], row_w)
            name_lbl.setStyleSheet(f"color: {C['fg_muted']}; min-width: 180px;")
            v = _Var(value=str(fields.get(name) or ""))
            edit = themed_entry(row_w, var=v, width=36)
            row_l.addWidget(name_lbl)
            row_l.addWidget(edit)
            inner_layout.addWidget(row_w)
            vars_map[name] = v

        flatten_v = _Var(value=True)
        bl.addWidget(themed_check(
            dlg.body, "Flatten fields into content (read-only)", flatten_v))

        def save():
            out = filedialog.asksaveasfilename(
                title="Save filled PDF", defaultextension=".pdf",
                filetypes=[("PDF files", "*.pdf")])
            if not out:
                return
            try:
                writer = PdfWriter(clone_from=reader)
                values = {k: v.get() for k, v in vars_map.items()}
                for page in writer.pages:
                    writer.update_page_form_field_values(page, values)
                if flatten_v.get():
                    try:
                        from pypdf.generic import BooleanObject, NumberObject
                        if "/AcroForm" in writer._root_object:
                            writer._root_object["/AcroForm"].update(
                                {"/NeedAppearances": BooleanObject(True)})
                        for page in writer.pages:
                            if "/Annots" in page:
                                for annot in page["/Annots"]:
                                    a = annot.get_object()
                                    a.update({"/Ff": NumberObject(1)})
                    except Exception:
                        pass
                with open(out, "wb") as f:
                    writer.write(f)
                _toast(self, f"Saved → {os.path.basename(out)}", "success")
                dlg.accept()
            except Exception as e:
                messagebox.showerror("Save error", str(e))

        bl.addLayout(_btn_row(dlg.body, dlg.reject, "Save", save))
        dlg.exec()

    # ══════════════════════════════════════════════════════════════════════
    # 10. MARKUPS (highlight / underline / strikeout / sticky note)
    # ══════════════════════════════════════════════════════════════════════
    def markup_dialog(self, kind: str = "highlight"):
        path = _current_pdf_path(self)
        if not path:
            _toast(self, "Open a PDF first", "warn")
            return

        label_map = {
            "highlight": "Highlight Text",
            "underline":  "Underline Text",
            "strikeout":  "Strike-through Text",
            "note":       "Sticky Note",
        }
        default_colors = {
            "highlight": "#FFEA00",
            "underline":  "#2563EB",
            "strikeout":  "#DC2626",
            "note":       "#F59E0B",
        }

        dlg = themed_dialog(self, label_map.get(kind, "Markup"), 460, 380)
        bl = dlg.body_layout

        text_v    = _Var(value="")
        content_v = _Var(value="")
        scope_v   = _Var(value="all")
        color_v   = _Var(value=default_colors.get(kind, "#FFEA00"))

        field_row(dlg.body, "Search term",
                  themed_entry(dlg.body, var=text_v, width=28))
        if kind == "note":
            field_row(dlg.body, "Note content",
                      themed_entry(dlg.body, var=content_v, width=28))

        s = section(bl, "Scope")
        sc_row = QHBoxLayout()
        for v, label in [("all", "All pages"), ("included", "Included only")]:
            sc_row.addWidget(themed_radio(s, label, scope_v, v))
        s._inner.addLayout(sc_row)

        s2 = section(bl, "Color")
        col_row = QHBoxLayout()
        col_btn = QPushButton(s2)
        col_btn.setFixedSize(50, 28)
        col_btn.setStyleSheet(
            f"background: {color_v.get()}; border: 1px solid {C['border']};"
            f" border-radius: 4px;"
        )

        def pick():
            c = colorchooser.askcolor(color=color_v.get(), parent=dlg)
            if c and c[1]:
                color_v.set(c[1])
                col_btn.setStyleSheet(
                    f"background: {c[1]}; border: 1px solid {C['border']};"
                    f" border-radius: 4px;")

        col_btn.clicked.connect(pick)
        col_row.addWidget(col_btn)
        col_row.addWidget(themed_button(s2, "Pick color", pick, style="solid"))
        col_row.addStretch()
        s2._inner.addLayout(col_row)

        def _run():
            term = text_v.get().strip()
            if not term and kind != "note":
                _toast(self, "Enter a search term", "warn")
                return
            out = filedialog.asksaveasfilename(
                title="Save marked-up PDF", defaultextension=".pdf",
                filetypes=[("PDF files", "*.pdf")])
            if not out:
                return
            dlg.accept()
            self._run_markup(kind, term, content_v.get(),
                             color_v.get(), scope_v.get(), out)

        bl.addLayout(_btn_row(dlg.body, dlg.reject, "Apply & Save", _run))
        dlg.exec()

    def _run_markup(self, kind, term, note_content, color_hex, scope, out):
        path = _current_pdf_path(self)
        try:
            doc = fitz.open(path)
            col_hex = color_hex.lstrip("#")
            rgb = tuple(int(col_hex[i:i + 2], 16) / 255 for i in (0, 2, 4))
            added = 0
            for i, page in enumerate(doc):
                rec = self.pages[i] if i < len(self.pages) else None
                if scope == "included" and rec and not rec.included.get():
                    continue
                if kind == "note":
                    page.add_text_annot(fitz.Point(40, 40), note_content or "Note")
                    added += 1
                else:
                    for rect in (page.search_for(term) if term else []):
                        if kind == "highlight":
                            a = page.add_highlight_annot(rect)
                        elif kind == "underline":
                            a = page.add_underline_annot(rect)
                        else:
                            a = page.add_strikeout_annot(rect)
                        try:
                            a.set_colors(stroke=rgb)
                            a.update()
                        except Exception:
                            pass
                        added += 1
            doc.save(out)
            doc.close()
            _toast(self, f"Added {added} markup(s) → {os.path.basename(out)}", "success")
        except Exception as e:
            messagebox.showerror("Markup error", str(e))


__all__ = ["PDFFeatures"]
