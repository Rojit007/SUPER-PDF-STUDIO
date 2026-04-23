"""Launch the demo UI, optionally toggle theme after N ms, screenshot, exit."""
import sys
import tkinter as tk
from preview_ui import DemoApp

root = tk.Tk()
app = DemoApp(root)

toggle_ms = int(sys.argv[1]) if len(sys.argv) > 1 else 0
quit_ms = int(sys.argv[2]) if len(sys.argv) > 2 else 4000

if toggle_ms:
    root.after(toggle_ms, app._invoke_toggle_theme)
    # re-render rows with new palette
    root.after(toggle_ms + 50, app.populate_demo_rows)

root.after(quit_ms, root.destroy)
root.mainloop()
