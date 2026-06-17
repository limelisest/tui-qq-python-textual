"""Pure navigation logic for split panes.

Extracted from ``ui/app.py``.  These functions compute the next pane to
navigate to based on the current layout and direction; the App still owns
state mutation and widget focus calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ui.state import ChatPaneState


@dataclass
class NavigationState:
    """Keyboard navigation state shared across list/search/pane focus modes."""

    layer: str = "top"
    top_target_pane_uid: Optional[int] = None
    chat_list_on_search: bool = False


def compute_pane_index_in_direction(
    panes: list[ChatPaneState],
    current_uid: Optional[int],
    split_layout_horizontal: bool,
    direction: str,
) -> Optional[int]:
    """Compute 1-based pane index to navigate to.

    Returns ``None`` when there is only one pane (nothing to navigate).
    Handles 2-, 3- and 4-pane layouts with the correct row/column wrapping.
    """
    if len(panes) <= 1:
        return None

    current = 0
    for i, pane in enumerate(panes):
        if pane.uid == current_uid:
            current = i
            break

    if len(panes) == 4:
        row, col = divmod(current, 2)
        if direction == "left":
            col = (col - 1) % 2
        elif direction == "right":
            col = (col + 1) % 2
        elif direction == "up":
            row = (row - 1) % 2
        elif direction == "down":
            row = (row + 1) % 2
        else:
            return None
        return row * 2 + col + 1

    if split_layout_horizontal:
        if direction not in ("left", "right"):
            return None
        delta = -1 if direction == "left" else 1
    else:
        if direction not in ("up", "down"):
            return None
        delta = -1 if direction == "up" else 1

    return ((current + delta) % len(panes)) + 1
