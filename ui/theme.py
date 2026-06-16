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

#: Right mouse button identifier as reported by Textual mouse events.
RIGHT_MOUSE_BUTTON = 3

#: Per-call timeout (seconds) for PowerShell clipboard invocations.
CLIPBOARD_TIMEOUT = 1.0

#: Sidebar auto-hides below this pixel width.
SIDEBAR_AUTO_HIDE_PIXELS = 700

#: Sidebar auto-hide threshold when all four split panes are visible.
SIDEBAR_AUTO_HIDE_FOUR_PANE_PIXELS = 1000

#: Sidebar auto-hides below this terminal column count (fallback when pixel
#: width is unavailable, e.g. on some Windows consoles).
SIDEBAR_AUTO_HIDE_COLUMNS = 88

#: Approximate terminal-column equivalent of the four-pane pixel threshold.
SIDEBAR_AUTO_HIDE_FOUR_PANE_COLUMNS = 126
