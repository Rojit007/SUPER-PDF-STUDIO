# PDF Studio v4 — UI Redesign + Acrobat Pro Feature Pack

## Problem statement
Desktop Tkinter PDF tool (Part 1 + Part 2). User wants UI redesign plus all
recommended shell improvements, animated drag-to-reorder, every Acrobat
Pro feature (except AI). Ships as .exe via PyInstaller.

## User choices
- Desktop Tkinter only (no web)
- Design agent's call on styling — "modern IDE-inspired" accepted
- ALL features from the recommendation list, plus buttery-smooth drag
  reorder with animation
- Adobe Acrobat Pro parity (no AI features)

## Deliverables (Feb 2026, Iteration 2)
- `/app/UI/pdf_studio_ui.py` (v2, ~1900 lines) — redesigned UI shell:
  - Warm coral/amber palette, dark + light theme
  - Custom titlebar with breadcrumb path (click → reveal in OS)
  - Native menubar (File / Edit / Page / Tools / Pro / Output / View / Help)
  - Grouped pill-button toolbar with tooltips
  - Sub-toolbar (search, range, odd/even, go-to, thumb size)
  - Bookmarks sidebar (Ctrl+B) with click-to-jump
  - List + grid view toggle (Ctrl+G, 3-8 adaptive columns)
  - Page rows: drag handle, custom include dot, shadow thumb, mono page
    numbers, orientation + rotation chips, EXCLUDED/PREVIEWING badges,
    2-row hover action cluster
  - Preview panel: zoom ±/fit, prev/next, split-view toggle
  - Status bar: stripe + text + autosave + version
  - Empty state: big Open button + Merge + Cmd palette + recent-files cards
  - Custom canvas scrollbars
  - Hover popover (600 ms dwell) on thumbnails showing text snippet +
    annotation counts
  - Animated drag-to-reorder (60 fps eased transitions, variable height
    aware, commits to self.pages + pushes undo)
  - Command palette (Ctrl+K / Ctrl+P) — fuzzy search over 50+ commands
  - Toast notifications — slide-in corner, stackable
  - Undo history dropdown (Edit → Undo History)
  - Preferences dialog (Ctrl+,)
  - Drag-and-drop file open (tkinterdnd2 optional)
  - Keyboard navigation (↑↓ Home End PgUp PgDn, Space, Enter, ← →)
- `/app/UI/pdf_features.py` (~1100 lines) — PDFFeatures mixin:
  1. Bates numbering (configurable prefix/suffix/digits/position/scope)
  2. Keyword bulk redaction (regex + case-sens options)
  3. Signature tool (canvas draw → PNG → stamp annotation)
  4. Hyperlink editor (list / edit / remove via PyMuPDF)
  5. Attachment extractor (embedded files listing + extract)
  6. TOC auto-generator (heuristic heading scan → bookmarks)
  7. Measuring tool (click 2 points, pt/in/custom units)
  8. Auto-crop (whitespace detection via PIL bbox)
  9. Form fields (fill + flatten AcroForms via pypdf)
  10. Markups (highlight / underline / strikeout / sticky note)
- `/app/UI/dialog_kit.py` — themed modal primitives + Toast + Splash
- `/app/preview_ui.py` — stand-alone demo with splash + fake pages
- `/app/integration_example.py` — 1-line integration instructions
- `/app/README_UI.md` — full docs

## Integration (user does this in their pdf_studio.py)
```python
from UI.pdf_features import PDFFeatures
class PDFStudio(PDFStudioUI, PDFFeatures):  # ← add mixin
    ...
```

## Validation
- Ruff lint: clean across all files
- py_compile: all files compile
- AST audit: 42 required UI methods + 14 required feature methods present

## Notes / known deferred
- tkinterdnd2 drag-drop is optional; gracefully falls back to menu-open
- Export to Word/Excel/PowerPoint (Acrobat has this) — skipped: needs
  python-docx + extra formatting libraries, user can add later
- Cryptographic PDF signing (Acrobat Sign) — skipped: needs PKCS#7 X.509
- Accessibility tagger — skipped: complex and niche

## Next potential polish items
- Plugin API (drop .py into plugins/ for auto menu registration)
- Custom title bar with native window drag (overrideredirect workflow)
- Mini-preview on hover in the command palette
- Per-page thumbnail caching across sessions
