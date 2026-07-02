"""Custom TextArea widget — Enter submits, no shortcut for newline."""

from __future__ import annotations

from textual import events
from textual.message import Message
from textual.widgets import TextArea


class MessageTextArea(TextArea):
    """TextArea that submits on Enter, no shortcut for manual newline."""

    class Submitted(Message):
        """Posted when Enter is pressed to submit the text."""
        def __init__(self, text_area: MessageTextArea, value: str) -> None:
            self.text_area = text_area
            self.value = value
            super().__init__()

    def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            self.post_message(self.Submitted(self, self.text))
            return
        if event.key == "ctrl+a":
            event.stop()
            event.prevent_default()
            lines = self.document.lines
            if lines:
                self.selection = ((0, 0), (len(lines) - 1, len(lines[-1])))
            return
        super()._on_key(event)
