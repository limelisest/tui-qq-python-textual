"""Pure sidebar visibility calculations.

Extracted from ``ui/app.py`` to reduce coupling between sidebar visibility
logic and the App's widget glue. All threshold calculations are side-effect-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ui.state import ChatPaneState
from ui.theme import (
    SIDEBAR_AUTO_HIDE_COLUMNS,
    SIDEBAR_AUTO_HIDE_COLUMNS_2H,
    SIDEBAR_AUTO_HIDE_COLUMNS_3H,
    SIDEBAR_AUTO_HIDE_COLUMNS_4,
    SIDEBAR_AUTO_HIDE_COLUMNS_SINGLE,
    SIDEBAR_AUTO_HIDE_PIXELS,
    SIDEBAR_AUTO_HIDE_PIXELS_2H,
    SIDEBAR_AUTO_HIDE_PIXELS_3H,
    SIDEBAR_AUTO_HIDE_PIXELS_4,
    SIDEBAR_AUTO_HIDE_PIXELS_SINGLE,
)


@dataclass
class SidebarState:
    """Visibility and temporary-restore state for the chat sidebar."""

    hidden_by: Optional[str] = None
    auto_paused: bool = False
    tab_restore_reason: Optional[str] = None
    tab_restore_auto_paused: bool = False


def sidebar_auto_hide_pixel_threshold(
    pane_count: int,
    split_layout_horizontal: bool = False,
) -> int:
    if pane_count == 1:
        return SIDEBAR_AUTO_HIDE_PIXELS_SINGLE
    if pane_count == 4:
        return SIDEBAR_AUTO_HIDE_PIXELS_4
    if pane_count == 2 and split_layout_horizontal:
        return SIDEBAR_AUTO_HIDE_PIXELS_2H
    if pane_count == 3 and split_layout_horizontal:
        return SIDEBAR_AUTO_HIDE_PIXELS_3H
    return SIDEBAR_AUTO_HIDE_PIXELS


def sidebar_auto_hide_column_threshold(
    pane_count: int,
    split_layout_horizontal: bool = False,
) -> int:
    if pane_count == 1:
        return SIDEBAR_AUTO_HIDE_COLUMNS_SINGLE
    if pane_count == 4:
        return SIDEBAR_AUTO_HIDE_COLUMNS_4
    if pane_count == 2 and split_layout_horizontal:
        return SIDEBAR_AUTO_HIDE_COLUMNS_2H
    if pane_count == 3 and split_layout_horizontal:
        return SIDEBAR_AUTO_HIDE_COLUMNS_3H
    return SIDEBAR_AUTO_HIDE_COLUMNS


def has_empty_pane(panes: list[ChatPaneState]) -> bool:
    return any(pane.selected_chat is None for pane in panes)


def is_sidebar_narrow(
    size,
    pixel_size,
    pane_count: int,
    split_layout_horizontal: bool = False,
) -> bool:
    if pixel_size is not None:
        pixel_width = getattr(pixel_size, "width", 0)
        if pixel_width > 0:
            return pixel_width < sidebar_auto_hide_pixel_threshold(
                pane_count,
                split_layout_horizontal,
            )
    if size is None:
        return False
    cell_width = getattr(size, "width", 0)
    if cell_width <= 0:
        return False
    return cell_width < sidebar_auto_hide_column_threshold(
        pane_count,
        split_layout_horizontal,
    )


def widget_inside(widget, parent) -> bool:
    node = widget
    while node is not None:
        if node is parent:
            return True
        node = getattr(node, "parent", None)
    return False
