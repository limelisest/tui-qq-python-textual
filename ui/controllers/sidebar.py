"""Widget-level sidebar visibility management for QQChatApp.

Extracted from ``ui/app.py``.  Pure side-effect-free calculations remain in
``ui/sidebar.py``; this controller owns the widget query and mutation calls
(``query_one``, ``.display``, ``.label``, ``.focus()``, etc.).
"""

from __future__ import annotations

from typing import Optional

from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.widgets import Button

from ui.sidebar import (
    has_empty_pane,
    is_sidebar_narrow,
    widget_inside,
)


class SidebarController:
    """Owns sidebar visibility changes and auto-hide behaviour."""

    def __init__(self, app) -> None:
        self._app = app

    # ------------------------------------------------------------------ #
    # Core visibility toggle
    # ------------------------------------------------------------------ #

    def set_sidebar_visible(
        self, visible: bool, reason: Optional[str] = None,
        move_focus: bool = True,
    ) -> None:
        try:
            sidebar = self._app.query_one("#sidebar", Vertical)
            button = self._app.query_one("#sidebar_toggle_btn", Button)
        except NoMatches:
            return

        sidebar.display = visible
        self._app.state.sidebar_state.hidden_by = None if visible else reason
        button.label = "<" if visible else ">"
        button.tooltip = "隐藏群组列表" if visible else "显示群组列表"
        if not visible:
            if move_focus:
                self.focus_after_sidebar_hidden(sidebar, button)
            return
        self._app._pane_ctrl.scroll_auto_panes()

    # ------------------------------------------------------------------ #
    # Auto-visibility (based on terminal width / pane count)
    # ------------------------------------------------------------------ #

    def apply_sidebar_auto_visibility(
        self, size=None, pixel_size=None
    ) -> None:
        if size is None and pixel_size is None:
            size = self._app.size
        narrow = is_sidebar_narrow(
            size,
            pixel_size,
            len(self._app.state.panes),
            self._app.state.split_layout_horizontal,
        )
        if narrow:
            self._app.state.sidebar_state.auto_paused = False
            if has_empty_pane(self._app.state.panes):
                self.set_sidebar_visible(True)
            else:
                self.set_sidebar_visible(False, "auto")
            return

        if self._app.state.sidebar_state.auto_paused:
            return
        if self._app.state.sidebar_state.hidden_by == "auto":
            self.set_sidebar_visible(True)

    def show_sidebar_for_narrow_navigation(self) -> None:
        if not is_sidebar_narrow(
            self._app.size,
            None,
            len(self._app.state.panes),
            self._app.state.split_layout_horizontal,
        ):
            return
        self._app.state.sidebar_state.auto_paused = False
        self.set_sidebar_visible(True)

    def hide_sidebar_after_narrow_chat_selection(self) -> None:
        if not is_sidebar_narrow(
            self._app.size,
            None,
            len(self._app.state.panes),
            self._app.state.split_layout_horizontal,
        ):
            return
        self._app.state.sidebar_state.auto_paused = False
        if has_empty_pane(self._app.state.panes):
            self.set_sidebar_visible(True)
        else:
            self.set_sidebar_visible(False, "auto")

    # ------------------------------------------------------------------ #
    # Focus re-routing after hide
    # ------------------------------------------------------------------ #

    def focus_after_sidebar_hidden(
        self, sidebar: Vertical, button: Button
    ) -> None:
        focused = self._app.focused
        if focused is None or not widget_inside(focused, sidebar):
            return
        pane = self._app._active_pane()
        if pane.selected_chat is not None:
            msg_input = self._app._msg_ctrl.message_input_or_none(pane)
            if msg_input is not None and not msg_input.disabled:
                msg_input.focus()
                return
        button.focus()
