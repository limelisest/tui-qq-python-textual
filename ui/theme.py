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

from config import (
    SIDEBAR_AUTO_HIDE_COLUMN_1,
    SIDEBAR_AUTO_HIDE_COLUMN_2H,
    SIDEBAR_AUTO_HIDE_COLUMN_2V,
    SIDEBAR_AUTO_HIDE_COLUMN_3H,
    SIDEBAR_AUTO_HIDE_COLUMN_3V,
    SIDEBAR_AUTO_HIDE_COLUMN_4,
    SIDEBAR_AUTO_HIDE_PIXEL_1,
    SIDEBAR_AUTO_HIDE_PIXEL_2H,
    SIDEBAR_AUTO_HIDE_PIXEL_2V,
    SIDEBAR_AUTO_HIDE_PIXEL_3H,
    SIDEBAR_AUTO_HIDE_PIXEL_3V,
    SIDEBAR_AUTO_HIDE_PIXEL_4,
)

#: Sidebar auto-hide pixel thresholds per pane_count+layout.
SIDEBAR_AUTO_HIDE_PIXELS_SINGLE = SIDEBAR_AUTO_HIDE_PIXEL_1
SIDEBAR_AUTO_HIDE_PIXELS_2H = SIDEBAR_AUTO_HIDE_PIXEL_2H
SIDEBAR_AUTO_HIDE_PIXELS_2V = SIDEBAR_AUTO_HIDE_PIXEL_2V
SIDEBAR_AUTO_HIDE_PIXELS_3H = SIDEBAR_AUTO_HIDE_PIXEL_3H
SIDEBAR_AUTO_HIDE_PIXELS_3V = SIDEBAR_AUTO_HIDE_PIXEL_3V
SIDEBAR_AUTO_HIDE_PIXELS_4 = SIDEBAR_AUTO_HIDE_PIXEL_4

#: Corresponding terminal-column fallback thresholds.
SIDEBAR_AUTO_HIDE_COLUMNS_SINGLE = SIDEBAR_AUTO_HIDE_COLUMN_1
SIDEBAR_AUTO_HIDE_COLUMNS_2H = SIDEBAR_AUTO_HIDE_COLUMN_2H
SIDEBAR_AUTO_HIDE_COLUMNS_2V = SIDEBAR_AUTO_HIDE_COLUMN_2V
SIDEBAR_AUTO_HIDE_COLUMNS_3H = SIDEBAR_AUTO_HIDE_COLUMN_3H
SIDEBAR_AUTO_HIDE_COLUMNS_3V = SIDEBAR_AUTO_HIDE_COLUMN_3V
SIDEBAR_AUTO_HIDE_COLUMNS_4 = SIDEBAR_AUTO_HIDE_COLUMN_4
