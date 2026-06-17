"""Visual style constants shared across the UI.

Centralising role colours and layout widths here keeps ``app.py`` free of magic
numbers and lets future themes be swapped in one place.
"""

# Rich markup style per sender role. ``self`` is rendered with a distinct colour
# rather than right-aligned so the whole log stays a single left-aligned column.
ROLE_STYLES = {
    "owner": "bold orange1",
    "admin": "bold green",
    "member": "white",
    "self": "bold dodger_blue1",
    "system": "dim",
}

#: Display width budget for chat list item text (name + preview line).
CHAT_LIST_TEXT_WIDTH = 24

#: Left mouse button identifier as reported by Textual mouse events.
LEFT_MOUSE_BUTTON = 1

#: Right mouse button identifier as reported by Textual mouse events.
RIGHT_MOUSE_BUTTON = 3

#: Per-call timeout (seconds) for PowerShell clipboard invocations.
CLIPBOARD_TIMEOUT = 1.0

#: Sidebar auto-hide pixel thresholds per pane_count+layout.
#: Default (2/3 vertical panes).
SIDEBAR_AUTO_HIDE_PIXELS = 700
#: Single pane (pane_count=1).
SIDEBAR_AUTO_HIDE_PIXELS_SINGLE = 600
#: Two horizontal panes.
SIDEBAR_AUTO_HIDE_PIXELS_2H = 800
#: Three horizontal panes.
SIDEBAR_AUTO_HIDE_PIXELS_3H = 1000
#: Four panes (any layout).
SIDEBAR_AUTO_HIDE_PIXELS_4 = 800

#: Corresponding terminal-column fallback thresholds.
SIDEBAR_AUTO_HIDE_COLUMNS = 88
SIDEBAR_AUTO_HIDE_COLUMNS_SINGLE = 76
SIDEBAR_AUTO_HIDE_COLUMNS_2H = 101
SIDEBAR_AUTO_HIDE_COLUMNS_3H = 126
SIDEBAR_AUTO_HIDE_COLUMNS_4 = 101
