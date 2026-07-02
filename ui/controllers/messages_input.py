"""Message input visibility and submission mixin."""

from __future__ import annotations

from typing import Optional

from textual.containers import Horizontal
from textual.widgets import TextArea

from ui.logic import message_logic
from ui.state import ChatPaneState


class MessageInputMixin:
    """Mixin providing message input visibility and submit methods.

    Requires ``self._app`` set by the concrete class, and methods from
    ``MessageRendererMixin`` (``message_input_or_none``, ``_pane_widget``).
    """

    def pane_input_visible(self, pane: ChatPaneState) -> bool:
        msg_input = self.message_input_or_none(pane)
        return (
            self._app.state.input_owner_pane_uid == pane.uid
            and pane.selected_chat is not None
            and msg_input is not None
        )

    def refresh_message_input_visibility(
        self, pane: Optional[ChatPaneState] = None
    ) -> None:
        panes = [pane] if pane is not None else list(self._app.state.panes)
        for target in panes:
            try:
                input_row = self._pane_widget(target, "input_row", Horizontal)
            except Exception:
                continue
            input_row.display = self.pane_input_visible(target)

    def start_message_input(self, pane: ChatPaneState, text: str) -> None:
        msg_input = self.message_input_or_none(pane)
        if msg_input is None or msg_input.disabled:
            return
        msg_input.text += text
        last_line_idx = len(msg_input.document.lines) - 1
        msg_input.move_cursor((last_line_idx, len(msg_input.document.lines[last_line_idx])))
        self._app.state.input_owner_pane_uid = pane.uid
        self.refresh_message_input_visibility(pane)
        msg_input.focus()

    def submit_message_input(self, input_widget: TextArea) -> None:
        app = self._app
        pane = app._pane_from_widget(input_widget)
        if pane is None:
            return
        app._activate_pane(pane, focus_input=True)
        text = input_widget.text.strip()
        input_widget.clear()
        self.refresh_message_input_visibility(pane)
        if not text:
            return
        chat = pane.selected_chat
        if chat is None:
            app._show_toast("请先选择会话")
            return
        if not app.ob.running:
            app._show_toast("NapBot 未连接", "无法发送消息")
            return

        reply_to = None
        reply_preview = None
        if 0 <= pane.reply_index < len(pane.messages):
            reply_target = pane.messages[pane.reply_index]
            reply_to = reply_target.message_id
            reply_preview = message_logic.build_reply_preview(
                reply_target, pane.messages, self._sender_name
            )
        self.clear_message_selection(pane)
        app._run_thread(
            app._send_worker, chat, text, reply_to, reply_preview
        )
