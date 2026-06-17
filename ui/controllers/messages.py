"""Message rendering, input visibility and sending coordination.

Extracted from ``QQChatApp``.  The controller owns per-pane message display
(log writing, scroll, reply-info), input visibility, and message submission.
"""

from __future__ import annotations

from typing import Optional

from rich.markup import escape as rich_escape
from textual.widgets import Button, Input, Static

from models import ChatInfo, MessageData
from ui.logic import message_logic
from ui.logic.message_logic import AtResolver
from ui.state import ChatPaneState, same_chat
from ui.theme import ROLE_STYLES
from ui.widgets import MessageLog


class MessageController:
    """Owns message rendering, input management and sending glue."""

    def __init__(self, app) -> None:
        self._app = app

    # ── widget accessors ───────────────────────────────────────────── #

    def _pane_widget(self, pane, name: str, widget_type):
        from ui.state import pane_selector
        return self._app.query_one(pane_selector(pane, name), widget_type)

    def message_log_or_none(
        self, pane: Optional[ChatPaneState] = None
    ) -> Optional[MessageLog]:
        pane = pane or self._app._active_pane()
        try:
            return self._pane_widget(pane, "msg_log", MessageLog)
        except Exception:
            return None

    def message_input_or_none(
        self, pane: Optional[ChatPaneState] = None
    ) -> Optional[Input]:
        pane = pane or self._app._active_pane()
        try:
            return self._pane_widget(pane, "msg_input", Input)
        except Exception:
            return None

    def _scroll_button_or_none(
        self, pane: Optional[ChatPaneState] = None
    ) -> Optional[Button]:
        pane = pane or self._app._active_pane()
        try:
            return self._pane_widget(pane, "scroll_bottom_btn", Button)
        except Exception:
            return None

    # ── sender resolution ──────────────────────────────────────────── #

    def _at_resolver(self, chat_type: str, chat_id: int) -> AtResolver:
        return message_logic.make_at_resolver(
            chat_type, chat_id, self._app.storage
        )

    def _sender_name(self, msg: MessageData) -> str:
        name, _, _ = message_logic.resolve_sender(
            msg, self._app.storage,
            self._app.ob.self_id, self._app._friend_remarks
        )
        return name

    def _resolve_sender(self, msg: MessageData) -> tuple[str, str, str]:
        return message_logic.resolve_sender(
            msg, self._app.storage,
            self._app.ob.self_id, self._app._friend_remarks
        )

    def _build_reply_preview(
        self, msg: MessageData, pane: Optional[ChatPaneState] = None
    ) -> str:
        pane = pane or self._app._active_pane()
        return message_logic.build_reply_preview(
            msg, pane.messages, self._sender_name
        )

    # ── message rendering ──────────────────────────────────────────── #

    def write_message(
        self,
        log: MessageLog,
        msg: MessageData,
        pane: Optional[ChatPaneState] = None,
        selected: bool = False,
    ) -> tuple[int, int]:
        pane = pane or self._app._active_pane()
        start_line = log.line_count
        name, title, role = self._resolve_sender(msg)
        renderables = message_logic.build_message_renderables(
            msg,
            name=name,
            title=title,
            role=role,
            role_styles=ROLE_STYLES,
            reply_preview=self._build_reply_preview(msg, pane),
            selected=selected,
        )
        log.write(renderables.header)
        if renderables.preview is not None:
            log.write(renderables.preview)
        log.write(renderables.content)
        log.write("")
        return start_line, log.line_count

    def render_messages(self, pane: Optional[ChatPaneState] = None) -> None:
        pane = pane or self._app._active_pane()
        log = self.message_log_or_none(pane)
        if log is None:
            return
        log.clear()
        pane.message_line_spans = []
        for index, msg in enumerate(pane.messages):
            pane.message_line_spans.append(
                self.write_message(
                    log, msg, pane,
                    selected=index == pane.reply_index,
                )
            )
        self.update_reply_info(pane)

    def message_start_line(
        self, pane: ChatPaneState, index: int
    ) -> Optional[int]:
        if 0 <= index < len(pane.message_line_spans):
            return pane.message_line_spans[index][0]
        return None

    def scroll_to_message(self, pane: ChatPaneState, index: int) -> None:
        target_y = self.message_start_line(pane, index)
        if target_y is None:
            return
        log = self.message_log_or_none(pane)
        if log is None:
            return
        target = log.line_widget(target_y)
        if target is None:
            return

        def scroll_target() -> None:
            if target.is_attached:
                target.scroll_visible(top=True, immediate=True)

        scroll_target()
        self._app.call_after_refresh(scroll_target)

    def update_reply_info(self, pane: Optional[ChatPaneState] = None) -> None:
        pane = pane or self._app._active_pane()
        try:
            widget = self._pane_widget(pane, "reply_info", Static)
        except Exception:
            return
        if pane.reply_index < 0 or pane.reply_index >= len(pane.messages):
            widget.update("")
            return
        msg = pane.messages[pane.reply_index]
        name = self._sender_name(msg)
        preview = msg.content.replace("\n", " ")[:42]
        if len(msg.content) > 42:
            preview += "..."
        widget.update(f"回复 {name}: {preview}")

    def append_message_if_current(
        self, chat: ChatInfo, message: MessageData
    ) -> None:
        for pane in list(self._app._panes):
            if not same_chat(pane.selected_chat, chat):
                continue
            pane.messages.append(message)
            log = self.message_log_or_none(pane)
            if log is None:
                continue
            line_span = self.write_message(log, message, pane)
            pane.message_line_spans.append(line_span)
            pane.auto_scroll = True
            self.hide_scroll_bottom_btn(pane)
            log.scroll_end_when_ready()
        self._app._chat_list_ctrl.refresh_chat_list_item(
            chat.chat_type, chat.chat_id
        )

    # ── scroll helpers ─────────────────────────────────────────────── #

    def show_scroll_bottom_btn(
        self, pane: Optional[ChatPaneState] = None
    ) -> None:
        btn = self._scroll_button_or_none(pane)
        if btn is not None and btn.visible is False:
            btn.visible = True

    def hide_scroll_bottom_btn(
        self, pane: Optional[ChatPaneState] = None
    ) -> None:
        btn = self._scroll_button_or_none(pane)
        if btn is not None and btn.visible is not False:
            btn.visible = False

    def force_scroll_end(self, pane_uid: Optional[int] = None) -> None:
        pane = self._app._pane_by_uid(pane_uid) if pane_uid is not None else self._app._active_pane()
        if pane is None:
            return
        log = self.message_log_or_none(pane)
        if log is not None:
            log.scroll_end_when_ready()

    def check_scroll(self) -> None:
        for pane in list(self._app._panes):
            log = self.message_log_or_none(pane)
            if log is None:
                continue
            cur_y = log.scroll_y
            max_y = log.max_scroll_y
            if max_y <= 0:
                pane.prev_scroll_y = 0
                continue

            if cur_y < pane.prev_scroll_y and pane.auto_scroll:
                pane.auto_scroll = False
                self.show_scroll_bottom_btn(pane)
            at_bottom = cur_y >= max_y - 1
            if at_bottom and not pane.auto_scroll:
                pane.auto_scroll = True
                self.hide_scroll_bottom_btn(pane)
            elif at_bottom:
                self.hide_scroll_bottom_btn(pane)

            pane.prev_scroll_y = cur_y

    # ── input visibility ───────────────────────────────────────────── #

    def pane_input_visible(self, pane: ChatPaneState) -> bool:
        msg_input = self.message_input_or_none(pane)
        return (
            self._app._input_owner_pane_uid == pane.uid
            and pane.selected_chat is not None
            and msg_input is not None
        )

    def refresh_message_input_visibility(
        self, pane: Optional[ChatPaneState] = None
    ) -> None:
        panes = [pane] if pane is not None else list(self._app._panes)
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
        msg_input.cursor_position = len(msg_input.value)
        msg_input.insert_text_at_cursor(text)
        self._app._input_owner_pane_uid = pane.uid
        self.refresh_message_input_visibility(pane)
        msg_input.focus()

    # ── show messages (called from worker callback) ─────────────────── #

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

    # ── submit / send ───────────────────────────────────────────────── #

    def submit_message_input(self, input_widget: Input) -> None:
        app = self._app
        pane = app._pane_from_widget(input_widget)
        if pane is None:
            return
        app._activate_pane(pane)
        text = input_widget.value.strip()
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
        pane.reply_index = -1
        self.update_reply_info(pane)
        app._run_thread(
            app._send_worker, chat, text, reply_to, reply_preview
        )


# Avoid circular import at module level ── only needed inside methods.
from textual.containers import Horizontal  # noqa: E402
