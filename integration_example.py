"""
Integration example — how to plug the new UI + feature mixin into your
existing PDFStudio class (Part 1 + Part 2).

In your main script, replace:

    from UI.pdf_studio_ui import PDFStudioUI, C as UI_C

    class PDFStudio(PDFStudioUI):
        ...

with:

    from UI.pdf_studio_ui import PDFStudioUI, C as UI_C
    from UI.pdf_features import PDFFeatures

    class PDFStudio(PDFStudioUI, PDFFeatures):
        ...

That's it — every new menu item / toolbar button / command-palette entry
is automatically wired because the UI shell looks for methods by name on
`self`, and those methods are now provided by the mixin.

Optionally, call the splash before building your root:

    from UI.dialog_kit import Splash
    root = tk.Tk()
    Splash(root, duration_ms=1500)
    app = PDFStudio(root)
    root.mainloop()

Also, when you add a bookmark in your existing `add_bookmark_dialog`,
after the append call, refresh the sidebar:

    if hasattr(self, "refresh_bookmarks_sidebar"):
        self.refresh_bookmarks_sidebar()

That keeps the left-rail outline in sync with your bookmark data.
"""
