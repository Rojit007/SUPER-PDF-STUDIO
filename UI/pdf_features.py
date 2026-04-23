"""
PDF Studio – Feature Mixin
─────────────────────────────────────────────────────────────────────────────
Adobe Acrobat-Pro-parity features added on top of the existing PDFStudio
backend. Mix this class into your PDFStudio hierarchy:

    from UI.pdf_studio_ui import PDFStudioUI
    from UI.pdf_features import PDFFeatures

    class PDFStudio(PDFStudioUI, PDFFeatures):
        ...

Every feature:
    • Opens a themed dialog
    • Does real work with pypdf / PyMuPDF / Pillow (libraries you already
      ship in requirements)
    • Shows toast + status-bar confirmation
    • Pushes undo if it mutates `self.pages`
"""
from __future__ import annotations
import os
import io
import re
import math
import copy
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox, colorchooser

import fitz
from PIL import Image, ImageDraw, ImageTk, ImageFont
from pypdf import PdfReader, PdfWriter

from UI.pdf_studio_ui import C, _get_toaster
from UI.dialog_kit import (
    themed_toplevel, themed_button, themed_entry, themed_check, themed_radio,
    section, field_row,
)


def _toast(ui, msg, kind="info"):
    tx = _get_toaster(ui)
    if tx:
        tx.show(msg, kind=kind)
    try:
        ui.status_var.set(msg)
    except Exception:
        pass


def _current_pdf_path(ui):
    """Primary open PDF or empty."""
    return getattr(ui, "primary_path", None)


class PDFFeatures:
    """Mixin of all Acrobat-Pro-parity features."""

    # ══════════════════════════════════════════════════════════════════════
    # 1. BATES NUMBERING
    # ══════════════════════════════════════════════════════════════════════
    def bates_dialog(self):
        if not getattr(self, "pages", None):
            _toast(self, "Open a PDF first", "warn")
            return
        win = themed_toplevel(self.root, "Bates Numbering", 460, 460)
        body = win.body

        prefix = tk.StringVar(value="EXHIBIT-")
        suffix = tk.StringVar(value="")
        start = tk.IntVar(value=1)
        digits = tk.IntVar(value=4)
        pos = tk.StringVar(value="bottom-right")
        include = tk.StringVar(value="all")

        s1 = section(body, "Format")
        field_row(s1, "Prefix", themed_entry(s1, textvariable=prefix,
                                             width=18))
        field_row(s1, "Suffix", themed_entry(s1, textvariable=suffix,
                                             width=18))
        field_row(s1, "Start #", themed_entry(s1, textvariable=start,
                                              width=8))
        field_row(s1, "Digits", themed_entry(s1, textvariable=digits,
                                             width=6),
                  "zero-pad width")

        s2 = section(body, "Position")
        pr = tk.Frame(s2, bg=C["panel"])
        pr.pack(anchor="w")
        for val, lbl in [
            ("top-left", "TL"), ("top-center", "TC"), ("top-right", "TR"),
            ("bottom-left", "BL"), ("bottom-center", "BC"),
            ("bottom-right", "BR"),
        ]:
            themed_radio(pr, lbl, pos, val).pack(side="left", padx=4)

        s3 = section(body, "Scope")
        sc = tk.Frame(s3, bg=C["panel"])
        sc.pack(anchor="w")
        for val, label in [("all", "All pages"),
                           ("included", "Included only")]:
            themed_radio(sc, label, include, val).pack(side="left", padx=4)

        s4 = section(body, "Preview")
        preview = tk.Label(
            s4, text="EXHIBIT-0001",
            bg=C["elevated"], fg=C["fg"], padx=14, pady=10,
            font=("TkFixedFont", 14, "bold"))
        preview.pack(anchor="w")

        def _upd(*_):
            try:
                n = int(start.get())
            except Exception:
                n = 1
            d = max(1, int(digits.get() or 4))
            preview.config(text=f"{prefix.get()}{n:0{d}d}{suffix.get()}")
        for v in (prefix, suffix, start, digits):
            v.trace_add("write", _upd)

        btns = tk.Frame(body, bg=C["panel"])
        btns.pack(fill="x", pady=(14, 0))
        tk.Frame(btns, bg=C["panel"]).pack(side="left", fill="x", expand=True)
        themed_button(btns, "Cancel", win.destroy, style="ghost"
                      ).pack(side="left", padx=4)
        themed_button(btns, "Apply & Save", style="accent",
                      command=lambda: self._run_bates(
                          win, prefix.get(), suffix.get(), int(start.get()),
                          int(digits.get() or 4), pos.get(), include.get())
                      ).pack(side="left", padx=4)

    def _run_bates(self, win, prefix, suffix, start, digits, pos, scope):
        out = filedialog.asksaveasfilename(
            title="Save stamped PDF", defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")])
        if not out:
            return
        win.destroy()
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
                if "top" in pos:
                    y = margin
                else:
                    y = r.height - margin
                if "left" in pos:
                    x = margin
                elif "right" in pos:
                    x = r.width - margin - 8 * len(text)
                else:
                    x = r.width / 2 - 4 * len(text)
                page.insert_text(
                    fitz.Point(x, y), text,
                    fontsize=11, color=(0.85, 0.35, 0.15),
                    fontname="helv")
                n += 1
            doc.save(out)
            doc.close()
            _toast(self, f"Bates-stamped PDF saved → {os.path.basename(out)}",
                   "success")
        except Exception as e:
            messagebox.showerror("Bates error", str(e))

    # ══════════════════════════════════════════════════════════════════════
    # 2. KEYWORD BULK REDACTION
    # ══════════════════════════════════════════════════════════════════════
    def keyword_redact_dialog(self):
        if not _current_pdf_path(self):
            _toast(self, "Open a PDF first", "warn")
            return
        win = themed_toplevel(self.root, "Keyword Bulk Redaction", 500, 500)
        body = win.body

        tk.Label(body,
                 text="Enter one term per line. Regex supported when enabled.",
                 bg=C["panel"], fg=C["fg_muted"],
                 font=("TkDefaultFont", 9)).pack(anchor="w")

        txt_wrap = tk.Frame(body, bg=C["elevated"],
                            highlightthickness=1,
                            highlightbackground=C["border"])
        txt_wrap.pack(fill="both", expand=True, pady=6)
        txt = tk.Text(txt_wrap, bd=0, bg=C["elevated"], fg=C["fg"],
                      insertbackground=C["accent"],
                      font=("TkFixedFont", 10), relief="flat",
                      highlightthickness=0, height=10)
        txt.pack(fill="both", expand=True, padx=8, pady=6)
        txt.insert("1.0", "Confidential\nSocial Security\n\\b\\d{3}-\\d{2}-\\d{4}\\b\n")

        use_regex = tk.BooleanVar(value=True)
        case_sens = tk.BooleanVar(value=False)
        include_scope = tk.StringVar(value="all")

        s = section(body, "Options")
        themed_check(s, "Use regex patterns", use_regex).pack(anchor="w")
        themed_check(s, "Case sensitive", case_sens).pack(anchor="w")

        s2 = section(body, "Scope")
        sc = tk.Frame(s2, bg=C["panel"])
        sc.pack(anchor="w")
        for v, label in [("all", "All pages"), ("included", "Included only")]:
            themed_radio(sc, label, include_scope, v).pack(side="left", padx=4)

        btns = tk.Frame(body, bg=C["panel"])
        btns.pack(fill="x", pady=(10, 0))
        tk.Frame(btns, bg=C["panel"]).pack(side="left", fill="x", expand=True)
        themed_button(btns, "Cancel", win.destroy, style="ghost"
                      ).pack(side="left", padx=4)

        def _run():
            terms = [t for t in txt.get("1.0", "end").splitlines() if t.strip()]
            if not terms:
                _toast(self, "Add at least one term", "warn")
                return
            out = filedialog.asksaveasfilename(
                title="Save redacted PDF", defaultextension=".pdf",
                filetypes=[("PDF files", "*.pdf")])
            if not out:
                return
            win.destroy()
            self._run_keyword_redact(terms, bool(use_regex.get()),
                                     bool(case_sens.get()),
                                     include_scope.get(), out)

        themed_button(btns, "Redact & Save", style="accent",
                      command=_run).pack(side="left", padx=4)

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
                            for r in page.search_for(m.group(0),
                                                      quads=False):
                                rects.append(r)
                    else:
                        for r in page.search_for(term):
                            rects.append(r)
                for r in rects:
                    page.add_redact_annot(r, fill=(0, 0, 0))
                    total += 1
                if rects:
                    page.apply_redactions()
            doc.save(out)
            doc.close()
            _toast(self, f"Redacted {total} matches → {os.path.basename(out)}",
                   "success")
        except Exception as e:
            messagebox.showerror("Redaction error", str(e))

    # ══════════════════════════════════════════════════════════════════════
    # 3. SIGNATURE TOOL (draw → save → stamp)
    # ══════════════════════════════════════════════════════════════════════
    def signature_dialog(self):
        if not getattr(self, "pages", None):
            _toast(self, "Open a PDF first", "warn")
            return
        win = themed_toplevel(self.root, "Signature Tool", 640, 460,
                              resizable=(False, False))
        body = win.body

        tk.Label(body, text="Draw your signature below:",
                 bg=C["panel"], fg=C["fg_muted"],
                 font=("TkDefaultFont", 10)).pack(anchor="w")

        cv = tk.Canvas(body, width=560, height=180, bg="#FFFFFF",
                       highlightthickness=1, highlightbackground=C["border"],
                       cursor="pencil")
        cv.pack(pady=10)

        pen_size = tk.IntVar(value=3)
        color = tk.StringVar(value="#0A1F3D")

        strokes = []

        def on_down(e):
            strokes.append([(e.x, e.y)])

        def on_move(e):
            if not strokes:
                return
            strokes[-1].append((e.x, e.y))
            x0, y0 = strokes[-1][-2]
            cv.create_line(x0, y0, e.x, e.y, width=pen_size.get(),
                           fill=color.get(),
                           capstyle="round", smooth=True)

        cv.bind("<Button-1>", on_down)
        cv.bind("<B1-Motion>", on_move)

        ctrl = tk.Frame(body, bg=C["panel"])
        ctrl.pack(fill="x", pady=6)
        tk.Label(ctrl, text="Pen:", bg=C["panel"], fg=C["fg_muted"],
                 font=("TkDefaultFont", 9)).pack(side="left", padx=(0, 6))
        tk.Scale(ctrl, from_=1, to=10, variable=pen_size, orient="horizontal",
                 showvalue=False, length=120, bg=C["panel"],
                 troughcolor=C["elevated"], fg=C["fg"],
                 activebackground=C["accent"],
                 highlightthickness=0, bd=0).pack(side="left")

        def pick_color():
            c = colorchooser.askcolor(color=color.get(), parent=win)
            if c and c[1]:
                color.set(c[1])
        themed_button(ctrl, "Color", pick_color, style="solid"
                      ).pack(side="left", padx=8)

        def clear():
            cv.delete("all")
            strokes.clear()
        themed_button(ctrl, "Clear", clear, style="ghost"
                      ).pack(side="left", padx=8)

        page_var = tk.IntVar(value=max(1, self._preview_index + 1
                                       if self._preview_index >= 0 else 1))
        x_var = tk.DoubleVar(value=0.65)
        y_var = tk.DoubleVar(value=0.82)
        w_var = tk.DoubleVar(value=0.25)

        s = section(body, "Placement")
        pr = tk.Frame(s, bg=C["panel"])
        pr.pack(anchor="w")
        tk.Label(pr, text="Page:", bg=C["panel"], fg=C["fg_muted"]
                 ).pack(side="left")
        tk.Spinbox(pr, from_=1, to=max(1, len(self.pages)),
                   textvariable=page_var, width=5,
                   bg=C["elevated"], fg=C["fg"], bd=0).pack(side="left", padx=4)
        for lbl, v in [("X:", x_var), ("Y:", y_var), ("W:", w_var)]:
            tk.Label(pr, text=lbl, bg=C["panel"], fg=C["fg_muted"]
                     ).pack(side="left", padx=(8, 2))
            themed_entry(pr, textvariable=v, width=5).pack(side="left")

        btns = tk.Frame(body, bg=C["panel"])
        btns.pack(fill="x", pady=(10, 0))
        tk.Frame(btns, bg=C["panel"]).pack(side="left", fill="x", expand=True)

        def apply_sig():
            if not strokes:
                _toast(self, "Please draw a signature first", "warn")
                return
            # Render canvas strokes into a PIL image
            img = Image.new("RGBA", (560, 180), (255, 255, 255, 0))
            d = ImageDraw.Draw(img)
            col = color.get().lstrip("#")
            rgb = tuple(int(col[i:i+2], 16) for i in (0, 2, 4))
            for stroke in strokes:
                if len(stroke) < 2:
                    continue
                d.line(stroke, fill=(*rgb, 255), width=pen_size.get(),
                       joint="curve")
            # Save to temp file
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp.close()
            img.save(tmp.name)
            # Inject as an annotation on the selected page
            idx = page_var.get() - 1
            if 0 <= idx < len(self.pages):
                if hasattr(self, "_push_undo"):
                    self._push_undo("apply signature")
                aspect = 180 / 560
                self.pages[idx].annotations.append({
                    "type": "stamp", "image_path": tmp.name,
                    "x": x_var.get(), "y": y_var.get(),
                    "w": w_var.get(), "h": w_var.get() * aspect,
                })
                _toast(self,
                       f"Signature placed on page {idx + 1}  —  save PDF to commit",
                       "success")
            win.destroy()

        themed_button(btns, "Cancel", win.destroy, style="ghost"
                      ).pack(side="left", padx=4)
        themed_button(btns, "Apply to page", apply_sig, style="accent"
                      ).pack(side="left", padx=4)

    # ══════════════════════════════════════════════════════════════════════
    # 4. HYPERLINK EDITOR
    # ══════════════════════════════════════════════════════════════════════
    def hyperlinks_dialog(self):
        path = _current_pdf_path(self)
        if not path:
            _toast(self, "Open a PDF first", "warn")
            return
        win = themed_toplevel(self.root, "Hyperlink Editor", 720, 480,
                              resizable=(True, True))
        body = win.body

        # Build link list
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

        tk.Label(body,
                 text=f"Found {len(links)} hyperlinks across {len(doc)} pages.",
                 bg=C["panel"], fg=C["fg_muted"],
                 font=("TkDefaultFont", 10)).pack(anchor="w", pady=(0, 6))

        cols = ("page", "type", "target")
        tv = tk.ttk.Treeview(body, columns=cols, show="headings", height=12)
        tv.heading("page", text="Page")
        tv.heading("type", text="Type")
        tv.heading("target", text="Target / URI")
        tv.column("page", width=60, anchor="center")
        tv.column("type", width=90)
        tv.column("target", width=480)
        tv.pack(fill="both", expand=True, pady=6)

        kinds = {1: "GOTO", 2: "URI", 3: "LAUNCH", 4: "GOTOR", 5: "NAMED"}
        for i, ln in enumerate(links):
            target = ln["uri"] if ln["uri"] else f"page {ln['original'].get('page', '?')}"
            tv.insert("", "end", iid=str(i),
                      values=(ln["page_index"] + 1,
                              kinds.get(ln["kind"], "?"), target))

        btns = tk.Frame(body, bg=C["panel"])
        btns.pack(fill="x", pady=6)

        def _sel():
            s = tv.selection()
            if not s:
                return None
            return links[int(s[0])]

        def edit_link():
            ln = _sel()
            if not ln:
                return
            ask = simpledialog_string(
                self.root, "Edit Hyperlink",
                "New URI / page target:", ln["uri"])
            if ask is None:
                return
            try:
                page = doc[ln["page_index"]]
                page.delete_link(ln["original"])
                page.insert_link({
                    "kind": 2, "from": ln["from"], "uri": ask,
                })
                tv.item(tv.selection()[0], values=(ln["page_index"] + 1,
                                                   "URI", ask))
                _toast(self, "Link updated", "success")
            except Exception as e:
                messagebox.showerror("Error", str(e))

        def remove_link():
            ln = _sel()
            if not ln:
                return
            try:
                doc[ln["page_index"]].delete_link(ln["original"])
                tv.delete(tv.selection()[0])
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
                win.destroy()
            except Exception as e:
                messagebox.showerror("Save error", str(e))

        themed_button(btns, "Edit", edit_link, style="solid"
                      ).pack(side="left", padx=4)
        themed_button(btns, "Remove", remove_link, style="danger"
                      ).pack(side="left", padx=4)
        tk.Frame(btns, bg=C["panel"]).pack(side="left", fill="x", expand=True)
        themed_button(btns, "Save PDF", save_pdf, style="accent"
                      ).pack(side="left", padx=4)

        win.protocol("WM_DELETE_WINDOW", lambda: (doc.close(), win.destroy()))

    # ══════════════════════════════════════════════════════════════════════
    # 5. ATTACHMENT EXTRACTOR
    # ══════════════════════════════════════════════════════════════════════
    def attachments_dialog(self):
        path = _current_pdf_path(self)
        if not path:
            _toast(self, "Open a PDF first", "warn")
            return
        win = themed_toplevel(self.root, "Attachment Extractor", 520, 400,
                              resizable=(True, True))
        body = win.body

        doc = fitz.open(path)
        n = doc.embfile_count()
        tk.Label(body, text=f"{n} embedded attachment(s) found.",
                 bg=C["panel"], fg=C["fg_muted"],
                 font=("TkDefaultFont", 10)).pack(anchor="w")

        lb = tk.Listbox(body, bg=C["elevated"], fg=C["fg"], bd=0,
                        highlightthickness=1,
                        highlightbackground=C["border"],
                        selectbackground=C["accent"],
                        selectforeground=C["fg_on_accent"],
                        activestyle="none", font=("TkDefaultFont", 10),
                        relief="flat", height=14)
        lb.pack(fill="both", expand=True, pady=8)

        names = []
        for i in range(n):
            info = doc.embfile_info(i)
            names.append(info["filename"])
            size = info.get("size", 0)
            lb.insert("end",
                      f"  {info['filename']:<40}  {size/1024:.1f} KB")

        btns = tk.Frame(body, bg=C["panel"])
        btns.pack(fill="x", pady=6)

        def extract_selected():
            sel = lb.curselection()
            if not sel:
                return
            out_dir = filedialog.askdirectory(title="Extract to folder")
            if not out_dir:
                return
            for idx in sel:
                name = names[idx]
                data = doc.embfile_get(idx)
                dest = os.path.join(out_dir, name)
                with open(dest, "wb") as f:
                    f.write(data)
            _toast(self,
                   f"Extracted {len(sel)} file(s) to {out_dir}", "success")

        def extract_all():
            if n == 0:
                return
            out_dir = filedialog.askdirectory(title="Extract all to folder")
            if not out_dir:
                return
            for i in range(n):
                data = doc.embfile_get(i)
                dest = os.path.join(out_dir, names[i])
                with open(dest, "wb") as f:
                    f.write(data)
            _toast(self, f"Extracted {n} file(s)", "success")

        themed_button(btns, "Extract selected", extract_selected,
                      style="solid").pack(side="left", padx=4)
        themed_button(btns, "Extract all", extract_all, style="accent"
                      ).pack(side="left", padx=4)
        tk.Frame(btns, bg=C["panel"]).pack(side="left", fill="x", expand=True)
        themed_button(btns, "Close", win.destroy, style="ghost"
                      ).pack(side="left", padx=4)

        win.protocol("WM_DELETE_WINDOW", lambda: (doc.close(), win.destroy()))

    # ══════════════════════════════════════════════════════════════════════
    # 6. TOC AUTO-GENERATOR
    # ══════════════════════════════════════════════════════════════════════
    def toc_auto_dialog(self):
        path = _current_pdf_path(self)
        if not path:
            _toast(self, "Open a PDF first", "warn")
            return
        win = themed_toplevel(self.root, "Auto-generate TOC", 520, 520,
                              resizable=(False, True))
        body = win.body

        tk.Label(body,
                 text="Scan the PDF for headings and propose bookmarks.",
                 bg=C["panel"], fg=C["fg_muted"],
                 font=("TkDefaultFont", 10)).pack(anchor="w")

        min_size = tk.DoubleVar(value=14.0)
        max_len = tk.IntVar(value=80)

        s = section(body, "Heuristic")
        field_row(s, "Min font size",
                  themed_entry(s, textvariable=min_size, width=6),
                  "points (larger = fewer candidates)")
        field_row(s, "Max length",
                  themed_entry(s, textvariable=max_len, width=6),
                  "chars (filters long paragraphs)")

        # Scan
        candidates = []

        def scan():
            candidates.clear()
            lb.delete(0, "end")
            try:
                doc = fitz.open(path)
                for i, page in enumerate(doc):
                    d = page.get_text("dict")
                    for block in d.get("blocks", []):
                        for line in block.get("lines", []):
                            for sp in line.get("spans", []):
                                text = sp["text"].strip()
                                if (sp["size"] >= float(min_size.get()) and
                                        3 <= len(text) <= int(max_len.get())
                                        and not text.endswith(".")):
                                    candidates.append({
                                        "title": text, "page": i,
                                        "size": sp["size"],
                                    })
                                    lb.insert(
                                        "end",
                                        f"  p.{i+1:<4}  {sp['size']:.0f}pt   {text[:60]}")
                                    break  # one heading per line
                            else:
                                continue
                            break
                doc.close()
                _toast(self, f"Found {len(candidates)} headings", "info")
            except Exception as e:
                messagebox.showerror("Scan error", str(e))

        lb_wrap = tk.Frame(body, bg=C["elevated"],
                           highlightthickness=1,
                           highlightbackground=C["border"])
        lb_wrap.pack(fill="both", expand=True, pady=8)
        lb = tk.Listbox(lb_wrap, bg=C["elevated"], fg=C["fg"],
                        bd=0, relief="flat", selectmode="extended",
                        font=("TkFixedFont", 9),
                        highlightthickness=0,
                        selectbackground=C["accent"],
                        selectforeground=C["fg_on_accent"])
        lb.pack(fill="both", expand=True, padx=8, pady=8)

        btns = tk.Frame(body, bg=C["panel"])
        btns.pack(fill="x", pady=6)
        themed_button(btns, "Scan", scan, style="solid"
                      ).pack(side="left", padx=4)

        def add_bookmarks():
            sel = lb.curselection() or list(range(lb.size()))
            count = 0
            for i in sel:
                if i < len(candidates):
                    c = candidates[i]
                    self._bookmarks.append(
                        {"title": c["title"], "page": c["page"]})
                    count += 1
            if hasattr(self, "refresh_bookmarks_sidebar"):
                self.refresh_bookmarks_sidebar()
            _toast(self, f"Added {count} bookmarks", "success")
            win.destroy()

        tk.Frame(btns, bg=C["panel"]).pack(side="left", fill="x", expand=True)
        themed_button(btns, "Add selected as bookmarks", add_bookmarks,
                      style="accent").pack(side="left", padx=4)

    # ══════════════════════════════════════════════════════════════════════
    # 7. MEASURING TOOL
    # ══════════════════════════════════════════════════════════════════════
    def measure_dialog(self):
        if not getattr(self, "pages", None):
            _toast(self, "Open a PDF first", "warn")
            return
        win = themed_toplevel(self.root, "Measuring Tool", 720, 520,
                              resizable=(True, True))
        body = win.body

        tk.Label(body,
                 text="Click two points to measure distance. 1 unit = 1 point (72 pts = 1 inch).",
                 bg=C["panel"], fg=C["fg_muted"],
                 font=("TkDefaultFont", 10)).pack(anchor="w")

        scale = tk.DoubleVar(value=1.0)
        unit = tk.StringVar(value="pt")

        ctl = tk.Frame(body, bg=C["panel"])
        ctl.pack(fill="x", pady=4)
        tk.Label(ctl, text="Scale: 1 pt =",
                 bg=C["panel"], fg=C["fg_muted"]).pack(side="left")
        themed_entry(ctl, textvariable=scale, width=6).pack(side="left", padx=4)
        tk.Label(ctl, text="units", bg=C["panel"], fg=C["fg_muted"]
                 ).pack(side="left", padx=(0, 8))
        themed_entry(ctl, textvariable=unit, width=8).pack(side="left")

        cv = tk.Canvas(body, bg=C["preview_bg"], highlightthickness=0, bd=0)
        cv.pack(fill="both", expand=True, pady=8)

        results = tk.Label(body, text="—",
                           bg=C["panel"], fg=C["accent"],
                           font=("TkFixedFont", 11, "bold"))
        results.pack(anchor="w")

        # Render current page into canvas
        idx = max(0, self._preview_index)
        rec = self.pages[idx]
        doc = fitz.open(rec.source_path)
        page = doc[rec.source_index]
        pix = page.get_pixmap(matrix=fitz.Matrix(1.3, 1.3), alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        tkimg = ImageTk.PhotoImage(img)
        doc.close()

        cv._img = tkimg
        cv._pw = page.rect.width
        cv._ph = page.rect.height
        cv._ratio = pix.width / page.rect.width

        def redraw():
            cv.delete("measure")
            cv.delete("img")
            cv.create_image(0, 0, image=tkimg, anchor="nw", tags=("img",))

        redraw()

        points = []

        def on_click(e):
            points.append((e.x, e.y))
            cv.create_oval(e.x - 4, e.y - 4, e.x + 4, e.y + 4,
                           outline=C["accent"], width=2, tags=("measure",))
            if len(points) == 2:
                (x1, y1), (x2, y2) = points
                cv.create_line(x1, y1, x2, y2, fill=C["accent"], width=2,
                               tags=("measure",))
                dx = (x2 - x1) / cv._ratio
                dy = (y2 - y1) / cv._ratio
                dist_pt = math.hypot(dx, dy)
                try:
                    s = float(scale.get())
                except Exception:
                    s = 1.0
                results.config(
                    text=(f"Distance: {dist_pt:.1f} pt   "
                          f"({dist_pt / 72:.2f} in   ·   "
                          f"{dist_pt * s:.2f} {unit.get()})"))
                points.clear()

        cv.bind("<Button-1>", on_click)

        btns = tk.Frame(body, bg=C["panel"])
        btns.pack(fill="x", pady=6)
        themed_button(btns, "Reset", lambda: (redraw(), points.clear()),
                      style="solid").pack(side="left", padx=4)
        tk.Frame(btns, bg=C["panel"]).pack(side="left", fill="x", expand=True)
        themed_button(btns, "Close", win.destroy, style="ghost"
                      ).pack(side="left", padx=4)

    # ══════════════════════════════════════════════════════════════════════
    # 8. AUTO-CROP (whitespace detection)
    # ══════════════════════════════════════════════════════════════════════
    def auto_crop_dialog(self):
        if not getattr(self, "pages", None):
            _toast(self, "Open a PDF first", "warn")
            return
        win = themed_toplevel(self.root, "Auto-Crop Whitespace", 420, 300)
        body = win.body

        threshold = tk.IntVar(value=240)
        padding = tk.IntVar(value=8)
        scope = tk.StringVar(value="all")

        s = section(body, "Settings")
        field_row(s, "Brightness threshold",
                  themed_entry(s, textvariable=threshold, width=6),
                  "0-255 (240 = near-white)")
        field_row(s, "Padding (points)",
                  themed_entry(s, textvariable=padding, width=6),
                  "margin to preserve")

        s2 = section(body, "Scope")
        sc = tk.Frame(s2, bg=C["panel"])
        sc.pack(anchor="w")
        for v, label in [("all", "All pages"), ("included", "Included only")]:
            themed_radio(sc, label, scope, v).pack(side="left", padx=4)

        btns = tk.Frame(body, bg=C["panel"])
        btns.pack(fill="x", pady=(16, 0))
        tk.Frame(btns, bg=C["panel"]).pack(side="left", fill="x", expand=True)
        themed_button(btns, "Cancel", win.destroy, style="ghost"
                      ).pack(side="left", padx=4)

        def _run():
            win.destroy()
            self._run_auto_crop(int(threshold.get()), int(padding.get()),
                                scope.get())

        themed_button(btns, "Detect & Apply", _run, style="accent"
                      ).pack(side="left", padx=4)

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
                pix = page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2),
                                      alpha=False)
                img = Image.frombytes("RGB", [pix.width, pix.height],
                                      pix.samples).convert("L")
                doc.close()
                # binarise
                bw = img.point(lambda p: 0 if p < threshold else 255)
                inv = Image.eval(bw, lambda p: 255 - p)
                bbox = inv.getbbox()
                if not bbox:
                    continue
                left_px, t, right_px, b = bbox
                sx = page.rect.width / pix.width
                sy = page.rect.height / pix.height
                rec.annotations.append({
                    "type": "crop",
                    "left": max(0, left_px * sx - padding),
                    "top": max(0, t * sy - padding),
                    "right": max(0, (pix.width - right_px) * sx - padding),
                    "bottom": max(0, (pix.height - b) * sy - padding),
                })
                applied += 1
            except Exception:
                continue
        _toast(self,
               f"Auto-crop queued on {applied} page(s). Save PDF to apply.",
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
            fields = reader.get_form_text_fields() or {}
            all_fields = reader.get_fields() or {}
        except Exception as e:
            messagebox.showerror("Error", f"Could not read form: {e}")
            return

        if not all_fields:
            _toast(self, "No AcroForm fields found", "warn")
            return

        win = themed_toplevel(self.root, "Form Fields", 560, 560,
                              resizable=(True, True))
        body = win.body
        tk.Label(body,
                 text=f"{len(all_fields)} form field(s). Edit values below:",
                 bg=C["panel"], fg=C["fg_muted"],
                 font=("TkDefaultFont", 10)).pack(anchor="w")

        scroll = tk.Canvas(body, bg=C["panel"], highlightthickness=0, bd=0)
        scroll.pack(fill="both", expand=True, pady=6)
        inner = tk.Frame(scroll, bg=C["panel"])
        scroll.create_window((0, 0), window=inner, anchor="nw")

        vars_map = {}
        for name, info in all_fields.items():
            row = tk.Frame(inner, bg=C["panel"])
            row.pack(fill="x", pady=3, padx=8)
            tk.Label(row, text=name[:30], bg=C["panel"], fg=C["fg_muted"],
                     font=("TkDefaultFont", 9), width=26, anchor="w"
                     ).pack(side="left")
            v = tk.StringVar(value=str(fields.get(name) or ""))
            themed_entry(row, textvariable=v, width=36).pack(side="left",
                                                             fill="x",
                                                             expand=True)
            vars_map[name] = v

        def _update_scroll(_=None):
            inner.update_idletasks()
            scroll.configure(scrollregion=scroll.bbox("all"))
        inner.bind("<Configure>", _update_scroll)

        flatten = tk.BooleanVar(value=True)
        themed_check(body, "Flatten fields into content (read-only)",
                     flatten).pack(anchor="w", pady=6)

        btns = tk.Frame(body, bg=C["panel"])
        btns.pack(fill="x", pady=6)
        tk.Frame(btns, bg=C["panel"]).pack(side="left", fill="x", expand=True)
        themed_button(btns, "Cancel", win.destroy, style="ghost"
                      ).pack(side="left", padx=4)

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
                if flatten.get():
                    # Flatten via re-writing readonly flags
                    try:
                        from pypdf.generic import BooleanObject, NumberObject
                        if "/AcroForm" in writer._root_object:
                            writer._root_object["/AcroForm"].update({
                                "/NeedAppearances": BooleanObject(True)})
                        for page in writer.pages:
                            if "/Annots" in page:
                                for annot in page["/Annots"]:
                                    a = annot.get_object()
                                    a.update({"/Ff": NumberObject(1)})
                    except Exception:
                        pass
                with open(out, "wb") as f:
                    writer.write(f)
                _toast(self,
                       f"Saved → {os.path.basename(out)}", "success")
                win.destroy()
            except Exception as e:
                messagebox.showerror("Save error", str(e))

        themed_button(btns, "Save", save, style="accent"
                      ).pack(side="left", padx=4)

    # ══════════════════════════════════════════════════════════════════════
    # 10. MARKUPS (highlight / underline / strikeout / sticky note)
    # ══════════════════════════════════════════════════════════════════════
    def markup_dialog(self, kind="highlight"):
        path = _current_pdf_path(self)
        if not path:
            _toast(self, "Open a PDF first", "warn")
            return
        label_map = {"highlight": "Highlight Text",
                     "underline": "Underline Text",
                     "strikeout": "Strike-through Text",
                     "note": "Sticky Note"}
        win = themed_toplevel(self.root, label_map.get(kind, "Markup"),
                              460, 360)
        body = win.body

        text_v = tk.StringVar()
        content_v = tk.StringVar()
        scope_v = tk.StringVar(value="all")
        color_v = tk.StringVar(
            value={"highlight": "#FFEA00",
                   "underline": "#2563EB",
                   "strikeout": "#DC2626",
                   "note": "#F59E0B"}[kind])

        field_row(body, "Search term",
                  themed_entry(body, textvariable=text_v, width=28))
        if kind == "note":
            field_row(body, "Note content",
                      themed_entry(body, textvariable=content_v, width=28))

        s = section(body, "Scope")
        sc = tk.Frame(s, bg=C["panel"])
        sc.pack(anchor="w")
        for v, label in [("all", "All pages"), ("included", "Included only")]:
            themed_radio(sc, label, scope_v, v).pack(side="left", padx=4)

        s2 = section(body, "Color")
        colorrow = tk.Frame(s2, bg=C["panel"])
        colorrow.pack(anchor="w")
        col_btn = tk.Label(colorrow, bg=color_v.get(), width=6, height=2,
                           cursor="hand2",
                           highlightthickness=1,
                           highlightbackground=C["border"])
        col_btn.pack(side="left", padx=(0, 10))

        def pick():
            c = colorchooser.askcolor(color=color_v.get(), parent=win)
            if c and c[1]:
                color_v.set(c[1])
                col_btn.configure(bg=c[1])
        col_btn.bind("<Button-1>", lambda _e: pick())
        themed_button(colorrow, "Pick color", pick,
                      style="solid").pack(side="left")

        btns = tk.Frame(body, bg=C["panel"])
        btns.pack(fill="x", pady=(16, 0))
        tk.Frame(btns, bg=C["panel"]).pack(side="left", fill="x", expand=True)
        themed_button(btns, "Cancel", win.destroy, style="ghost"
                      ).pack(side="left", padx=4)

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
            win.destroy()
            self._run_markup(kind, term, content_v.get(), color_v.get(),
                             scope_v.get(), out)

        themed_button(btns, "Apply & Save", _run, style="accent"
                      ).pack(side="left", padx=4)

    def _run_markup(self, kind, term, note_content, color_hex, scope, out):
        path = _current_pdf_path(self)
        try:
            doc = fitz.open(path)
            col_hex = color_hex.lstrip("#")
            rgb = tuple(int(col_hex[i:i+2], 16) / 255 for i in (0, 2, 4))
            added = 0
            for i, page in enumerate(doc):
                rec = self.pages[i] if i < len(self.pages) else None
                if scope == "included" and rec and not rec.included.get():
                    continue
                if kind == "note":
                    # place a sticky note in the top-left
                    page.add_text_annot(
                        fitz.Point(40, 40), note_content or "Note")
                    added += 1
                else:
                    rects = page.search_for(term) if term else []
                    for rect in rects:
                        if kind == "highlight":
                            a = page.add_highlight_annot(rect)
                        elif kind == "underline":
                            a = page.add_underline_annot(rect)
                        else:  # strikeout
                            a = page.add_strikeout_annot(rect)
                        try:
                            a.set_colors(stroke=rgb)
                            a.update()
                        except Exception:
                            pass
                        added += 1
            doc.save(out)
            doc.close()
            _toast(self,
                   f"Added {added} markup(s) → {os.path.basename(out)}",
                   "success")
        except Exception as e:
            messagebox.showerror("Markup error", str(e))


# ─────────────────────────────────────────────────────────────────────────────
#  themed string input (used by hyperlink editor)
# ─────────────────────────────────────────────────────────────────────────────
def simpledialog_string(root, title, prompt, initial=""):
    import queue
    q = queue.Queue()
    win = themed_toplevel(root, title, 400, 180)
    body = win.body
    tk.Label(body, text=prompt, bg=C["panel"], fg=C["fg"],
             font=("TkDefaultFont", 10)).pack(anchor="w", pady=(0, 6))
    var = tk.StringVar(value=initial)
    themed_entry(body, textvariable=var, width=40).pack(fill="x")
    btns = tk.Frame(body, bg=C["panel"])
    btns.pack(fill="x", pady=(14, 0))
    tk.Frame(btns, bg=C["panel"]).pack(side="left", fill="x", expand=True)

    def ok():
        q.put(var.get())
        win.destroy()

    def cancel():
        q.put(None)
        win.destroy()

    themed_button(btns, "Cancel", cancel, style="ghost"
                  ).pack(side="left", padx=4)
    themed_button(btns, "OK", ok, style="accent"
                  ).pack(side="left", padx=4)
    win.protocol("WM_DELETE_WINDOW", cancel)
    win.wait_window()
    try:
        return q.get_nowait()
    except Exception:
        return None


__all__ = ["PDFFeatures"]
