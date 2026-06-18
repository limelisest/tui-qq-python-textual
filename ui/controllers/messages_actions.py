"""Message action mixin: reply, plus-one, append, show."""

from __future__ import annotations

from models import ChatInfo, MessageData
from ui.logic import message_logic
from ui.state import ChatPaneState, same_chat


class MessageActionsMixin:
    """Mixin providing message action methods (reply, plus-one, append).

    Requires ``self._app`` set by the concrete class, and methods from
    ``MessageRendererMixin`` (``message_log_or_none``, ``write_message``,
    ``clear_message_selection``, ``update_reply_info``, ``refresh_message_selection``,
    ``message_input_or_none``, ``pane_input_visible``).
    """

    def append_message_if_current(
        self, chat: ChatInfo, message: MessageData
    ) -> None:
        for pane in list(self._app.state.panes):
            if not same_chat(pane.selected_chat, chat):
                continue
            pane.messages.append(message)
            log = self.message_log_or_none(pane)
            if log is None:
                continue
            line_span = self.write_message(
                log, message, pane, message_index=len(pane.messages) - 1
            )
            pane.message_line_spans.append(line_span)
            pane.auto_scroll = True
            self.hide_scroll_bottom_btn(pane)
            log.scroll_end_when_ready()
        self._app._chat_list_ctrl.refresh_chat_list_item(
            chat.chat_type, chat.chat_id
        )

    def reply_to_message(self, pane: ChatPaneState, index: int) -> None:
        if index < 0 or index >= len(pane.messages):
            return
        pane.message_action_index = 0
        old_index = pane.reply_index
        pane.reply_index = index
        self.refresh_message_selection(pane, old_index, index, scroll=False)
        self._focus_message_input(pane)

    def plus_one_message(self, pane: ChatPaneState, index: int) -> None:
        if index < 0 or index >= len(pane.messages):
            return
        chat = pane.selected_chat
        if chat is None:
            return
        text = pane.messages[index].content.strip()
        if not text:
            self._app._show_toast("该消息没有可发送的文本")
            return
        if not self._app.ob.running:
            self._app._show_toast("NapBot 未连接", "无法发送消息")
            return
        self.clear_message_selection(pane)
        self._focus_message_input(pane)
        self._app._run_thread(self._app._send_worker, chat, text, None, None)

    def _focus_message_input(self, pane: ChatPaneState) -> None:
        self._app._activate_pane(pane, focus_input=True)
        self.refresh_message_input_visibility(pane)
        msg_input = self.message_input_or_none(pane)
        if msg_input is None or msg_input.disabled:
            return

        def focus() -> None:
            if msg_input.is_attached:
                msg_input.focus()

        focus()
        self._app.call_after_refresh(focus)

    def show_messages(
        self,
        pane_uid: int,
        chat: ChatInfo,
        messages: list[MessageData],
        error: str = "",
    ) -> None:
        pane = self._app._pane_by_uid(pane_uid)
        if pane is None or not same_chat(pane.selected_chat, chat):
            return
        pane.messages = messages
        pane.message_line_spans = []
        pane.auto_scroll = True
        self.hide_scroll_bottom_btn(pane)
        log = self.message_log_or_none(pane)
        if log is None:
            return
        log.clear()
        if error:
            from rich.markup import escape as rich_escape
            log.write(f"[yellow]{rich_escape(error)}[/]")
            log.write("")
        if not messages:
            log.write("[dim]暂无消息[/]")
            log.scroll_home(immediate=True)
        else:
            self.render_messages(pane)
            pane.auto_scroll = True
            self.hide_scroll_bottom_btn(pane)
            log.scroll_end_when_ready()
            self._app.set_timer(
                0.05, lambda uid=pane.uid: self.force_scroll_end(uid)
            )
        self.update_reply_info(pane)
