"""Scrollable message log widget.

A vertical scroll area whose children are ``Static`` line widgets. Tracking the
line widgets ourselves (instead of letting RichLog own them) lets us:

* Cap the number of retained lines and drop the oldest cheaply.
* Map a logical message index to the widget that starts it (used for
  "scroll to the currently selected reply target").
* Preserve text selection on the underlying screen.

Behaviour is unchanged from the original inline class in ``tui.py``.
"""

from __future__ import annotations

from typing import Optional

from textual.containers import VerticalScroll
from textual.widgets import Static


class MessageLog(VerticalScroll):
    """Scrollable message area rendered with Static children."""

    ALLOW_SELECT = True

    def __init__(self, *children, max_lines: "int | None" = None, **kwargs) -> None:
        super().__init__(*children, can_focus=False, **kwargs)
        self.max_lines = max_lines
        self._line_widgets: list[Static] = []

    @property
    def line_count(self) -> int:
        return len(self._line_widgets)

    def clear(self) -> "MessageLog":
        self._line_widgets = []
        for child in self.children:
            child.display = False
        self.remove_children()
        self.refresh(layout=True)
        return self

    def write(
        self,
        content,
        *,
        classes: str = "",
        message_index: int | None = None,
        action_ranges: dict[str, tuple[int, int]] | None = None,
    ) -> "MessageLog":
        # A purely empty string would collapse to zero height, so render it as
        # a single space to keep the blank separator line visible.
        line_content = " " if content == "" else content
        line_classes = "message_log_line"
        if classes:
            line_classes = f"{line_classes} {classes}"
        line = Static(line_content, classes=line_classes)
        line.message_index = message_index
        line.message_action_ranges = action_ranges or {}
        self._line_widgets.append(line)
        self.mount(line)
        if self.max_lines is not None and len(self._line_widgets) > self.max_lines:
            stale = self._line_widgets[: -self.max_lines]
            self._line_widgets = self._line_widgets[-self.max_lines:]
            for widget in stale:
                widget.display = False
            self.remove_children(stale)
        return self

    def line_widget(self, index: int) -> Optional[Static]:
        if 0 <= index < len(self._line_widgets):
            return self._line_widgets[index]
        return None

    def set_line_selected(self, index: int, selected: bool) -> None:
        widget = self.line_widget(index)
        if widget is None:
            return
        if selected:
            widget.add_class("message_log_line_selected")
        else:
            widget.remove_class("message_log_line_selected")

    def scroll_end_when_ready(self) -> None:
        """Best-effort scroll to the bottom, robust to layout not being ready.

        Tries immediately, again after the next refresh, and once more on a
        short timer; each attempt is guarded by ``is_attached`` so it is safe
        to call during teardown.
        """
        target = self._line_widgets[-1] if self._line_widgets else None

        def scroll() -> None:
            if not self.is_attached:
                return
            if target is not None and target.is_attached:
                target.scroll_visible(immediate=True)
            self.scroll_end(immediate=True)

        scroll()
        self.call_after_refresh(scroll)
        self.set_timer(0.02, scroll)
