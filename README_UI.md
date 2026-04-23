# PDF Studio v4 — Redesigned UI + Acrobat Pro feature pack

A complete, drop-in UI re-skin plus a **feature mixin** that brings your
existing PDFStudio desktop app (Tkinter + pypdf + PyMuPDF) to Adobe
Acrobat Pro parity — no AI, no cloud, no backend rewrites.

## File layout

```
your_project/
├── pdf_studio.py                   # your Part-1 + Part-2 script
└── UI/
    ├── __init__.py
    ├── pdf_studio_ui.py            # redesigned UI shell
    ├── pdf_features.py             # new feature mixin
    ├── dialog_kit.py               # themed modal primitives
    └── assets/                     # brand assets
        ├── pdf_studio_icon_64.png
        ├── pdf_studio_icon_64_t.png       (transparent)
        ├── pdf_studio_icon_32.png / 128 / 256
        ├── pdf_studio_wordmark.png
        ├── pdf_studio_wordmark_transparent.png
        └── pdf_studio.ico                 (Windows)
```

### Brand

- **Accent red** `#DC2626` (sampled from the logo)
- **Navy** `#1E2431` (wordmark text)
- Logo auto-loaded in the titlebar and splash screen
- Window icon (task bar / alt-tab) set from `pdf_studio.ico` on Windows,
  PNG elsewhere
- Graceful fallback: if assets are missing the UI uses a vector-drawn
  logo and text wordmark, so the app never breaks

### PyInstaller bundling

Add the assets folder to the build so they ship inside the .exe:

**Windows**
```
pyinstaller --onefile --noconsole ^
    --icon UI/assets/pdf_studio.ico ^
    --add-data "UI/assets;UI/assets" ^
    pdf_studio.py
```

**macOS / Linux**
```
pyinstaller --onefile --windowed \
    --icon UI/assets/pdf_studio.ico \
    --add-data "UI/assets:UI/assets" \
    pdf_studio.py
```

The `asset_path()` helper in `pdf_studio_ui.py` automatically resolves
`sys._MEIPASS` when frozen.

## Wiring

Change just one line in `pdf_studio.py`:

```python
# before
from UI.pdf_studio_ui import PDFStudioUI, C as UI_C

class PDFStudio(PDFStudioUI):
    ...

# after
from UI.pdf_studio_ui import PDFStudioUI, C as UI_C
from UI.pdf_features import PDFFeatures

class PDFStudio(PDFStudioUI, PDFFeatures):
    ...
```

That's it. Every new menu item, toolbar button, and command-palette entry
is automatically wired because the UI shell resolves actions by method
name at call time.

Optionally splash-screen the .exe cold-start:

```python
from UI.dialog_kit import Splash
root = tk.Tk()
Splash(root, duration_ms=1500)
app = PDFStudio(root)
root.mainloop()
```

## What's new in the UI shell

| Feature | Trigger |
| --- | --- |
| **Animated drag-to-reorder** | Grab the `⋮⋮` handle and drop — other rows slide smoothly into place (ease-out, ~60 fps) |
| Command palette | `Ctrl+K`  (also `Ctrl+P`) |
| Drag-and-drop open | Drop a PDF onto the window (needs `pip install tkinterdnd2`; falls back gracefully) |
| Grid view | `Ctrl+G` — 3-to-8 column adaptive thumbnail grid |
| Bookmarks sidebar | `Ctrl+B` — click any to jump |
| Keyboard navigation | `↑ ↓ Home End PgUp PgDn`, `Space` toggles include, `Enter` previews |
| Toast notifications | slide-in bottom-right, stackable |
| Breadcrumb titlebar | Shows the path; double-click to reveal in OS file manager |
| Recent-files cards | Appear on the empty state |
| Hover popover | 600 ms dwell over a thumbnail shows the page's text snippet + annotation counts |
| Undo history dropdown | Edit → Undo History… |
| Preferences | `Ctrl+,` |
| Splash screen | Optional, for `.exe` cold-start |
| Custom canvas scrollbars | Thin, theme-aware |
| Themed dialogs | Everything new uses `UI.dialog_kit.themed_toplevel` |

## What's new in features (Adobe Pro parity, no AI)

1. **Bates numbering** — sequential `EXHIBIT-0001`, `EXHIBIT-0002`, …
   with configurable prefix, suffix, digits, position, scope
2. **Keyword bulk redaction** — list of terms (regex optional), scope all or
   included-only, redaction bars applied via PyMuPDF
3. **Signature tool** — draw on a canvas, pen size + color, places a stamp
   annotation on any chosen page at normalized (x, y, w)
4. **Hyperlink editor** — list, edit, remove every link annotation
5. **Attachment extractor** — list + extract embedded files
6. **TOC auto-generator** — heuristic scan for headings by font size, adds
   selected items to bookmark list (which syncs with the sidebar)
7. **Measuring tool** — click two points, see points / inches / custom unit
8. **Auto-crop** — whitespace detection via PIL bounding box
9. **Form fields** — list / fill / flatten AcroForms
10. **Markups** — highlight, underline, strikeout, sticky note
    (PyMuPDF text-markup annotations)
11. **Split view** — secondary preview pane

## Dependencies

No new required dependencies. Optional:

```
pip install tkinterdnd2       # drag-and-drop to open
```

The feature mixin uses libraries you already have:
`pypdf`, `PyMuPDF (fitz)`, `Pillow`.

## Run the preview

```bash
python preview_ui.py
```

You'll see:
- Splash screen
- 8 fake pages loaded in the list
- Bookmarks in the sidebar
- A welcome toast
- Fully working theme toggle, command palette, grid view

## Smooth animated drag-reorder — details

- Snapshots every row's `(y, height)` on grab
- Switches rows to `place()` geometry at captured positions
- Dragged row lifts (`raise_`) and follows the cursor
- Every other row animates toward a target y with 28%-per-tick ease-out
  at 16 ms intervals (~60 fps)
- On release, order is committed to `self.pages`, an undo is pushed, and
  rows return to pack geometry

Variable row heights (portrait vs landscape thumbnails) are handled via
per-row cached heights.

## Keyboard reference

| Key | Action |
| --- | --- |
| Ctrl + O / S / Z / Y / A | Open / Save / Undo / Redo / Select all |
| Ctrl + K  /  Ctrl + P | Command palette |
| Ctrl + T / B / G | Theme / Sidebar / Grid view |
| Ctrl + = / − / 0 | Zoom in / out / fit |
| Ctrl + , | Preferences |
| ↑ / ↓ / Home / End | Navigate rows |
| PgUp / PgDn | Jump 5 rows |
| Space | Toggle include on previewed page |
| Enter | Preview current focus |
| ← / → | Previous / next preview |
| Del | Delete selected |
| F1 | Shortcuts help |
