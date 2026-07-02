"""Message rendering mixin: renderables, write, selection, reply info."""

from __future__ import annotations

from typing import Optional

from rich.console import RenderableType
from rich.markup import escape as rich_escape
from rich.text import Text
from textual.widgets import Static, TextArea

import config
from models import ChatInfo, MessageData
from ui.logic import message_logic
from ui.logic.message_logic import AtResolver
from ui.state import ChatPaneState
from ui.text_utils import display_width
from ui.theme import ROLE_STYLES
from ui.widgets import MessageLog


MESSAGE_ACTIONS = ("reply", "plus_one")
MESSAGE_ACTION_LABELS = {
    "reply": "回复",
    "plus_one": "+1",
}


class MessageRendererMixin:
    """Mixin providing message rendering, selection and reply info methods.

    Requires ``self._app`` set by the concrete class.
    """

    # ── widget accessors ───────────────────────────────────────────── #

    def _pane_widget(self, pane, name: str, widget_type):
        from ui.state import pane_selector
        return self._app.query_one(pane_selector(pane, name), widget_type)

    def message_log_or_none(
        self, pane: Optional[ChatPaneState] = None
    ) -> Optional[MessageLog]:
        pane = pane or self._app.state.active_pane()
        try:
            return self._pane_widget(pane, "msg_log", MessageLog)
        except Exception:
            return None

    def message_input_or_none(
        self, pane: Optional[ChatPaneState] = None
    ) -> Optional[TextArea]:
        pane = pane or self._app.state.active_pane()
        try:
            return self._pane_widget(pane, "msg_input", TextArea)
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
            self._app.ob.self_id, self._app.state.friend_remarks
        )
        return name

    def _resolve_sender(self, msg: MessageData) -> tuple[str, str, str]:
        return message_logic.resolve_sender(
            msg, self._app.storage,
            self._app.ob.self_id, self._app.state.friend_remarks
        )

    def _build_reply_preview(
        self, msg: MessageData, pane: Optional[ChatPaneState] = None
    ) -> str:
        pane = pane or self._app.state.active_pane()
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
        message_index: Optional[int] = None,
    ) -> tuple[int, int]:
        pane = pane or self._app.state.active_pane()
        start_line = log.line_count
        renderables = self._message_renderables(msg, pane, selected)
        action_ranges = self._append_header_actions(renderables.header)
        content, content_action_ranges = self._content_with_actions(msg)
        log.write(
            renderables.header,
            classes="message_header_line",
            message_index=message_index,
            action_ranges=action_ranges,
        )
        if renderables.preview is not None:
            log.write(renderables.preview, classes="message_preview_line")
        log.write(
            content,
            classes="message_content_line",
            message_index=message_index,
            action_ranges=content_action_ranges,
        )
        log.write("")
        for line_index in range(start_line, log.line_count):
            log.set_line_selected(line_index, selected)
        return start_line, log.line_count

    def _message_renderables(
        self, msg: MessageData, pane: ChatPaneState, selected: bool
    ) -> message_logic.MessageRenderables:
        name, title, role = self._resolve_sender(msg)
        return message_logic.build_message_renderables(
            msg,
            name=name,
            title=title,
            role=role,
            role_styles=ROLE_STYLES,
            reply_preview=self._build_reply_preview(msg, pane),
            selected=selected,
        )

    def _append_header_actions(
        self, header: Text
    ) -> dict[str, tuple[int, int]]:
        if not config.ENABLE_MESSAGE_REPLY_ACTION:
            return {}
        base_width = display_width(header.plain)
        spacer = "  "
        reply_label = "[回复]"
        reply_start = base_width + display_width(spacer)
        reply_end = reply_start + display_width(reply_label)
        header.append(spacer)
        header.append(reply_label, style="dim")
        return {
            "reply": (reply_start, reply_end),
        }

    def _content_with_actions(
        self, msg: MessageData
    ) -> tuple[RenderableType, dict[str, tuple[int, int]]]:
        content = Text.from_markup(rich_escape(msg.content or ""))
        if (
            not config.ENABLE_MESSAGE_PLUS_ONE_ACTION
            or not (msg.content or "").strip()
        ):
            return content, {}

        spacer = " "
        plus_one_label = "[+1]"
        plus_one_start = 2 + display_width(content.plain) + display_width(spacer)
        plus_one_end = plus_one_start + display_width(plus_one_label)
        content.append(spacer)
        content.append(plus_one_label, style="dim")
        return content, {
            "plus_one": (plus_one_start, plus_one_end),
        }

    def render_messages(self, pane: Optional[ChatPaneState] = None) -> None:
        pane = pane or self._app.state.active_pane()
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
                    message_index=index,
                )
            )
        self.update_reply_info(pane)

    def refresh_message_selection(
        self,
        pane: ChatPaneState,
        old_index: int,
        new_index: int,
        scroll: bool = True,
    ) -> None:
        if old_index == new_index:
            if scroll and new_index >= 0:
                self.scroll_to_message(pane, new_index)
            self.update_reply_info(pane)
            return
        if new_index >= 0:
            pane.message_action_index = 0
        self._rewrite_message_selection(pane, old_index, selected=False)
        self._rewrite_message_selection(pane, new_index, selected=True)
        self.update_reply_info(pane)
        if scroll and new_index >= 0:
            self.scroll_to_message(pane, new_index)

    def clear_message_selection(self, pane: ChatPaneState) -> None:
        old_index = pane.reply_index
        if old_index < 0:
            return
        pane.reply_index = -1
        pane.message_action_index = 0
        self.refresh_message_selection(pane, old_index, -1, scroll=False)

    def _rewrite_message_selection(
        self, pane: ChatPaneState, index: int, selected: bool
    ) -> None:
        if index < 0 or index >= len(pane.messages):
            return
        if index >= len(pane.message_line_spans):
            return
        log = self.message_log_or_none(pane)
        if log is None:
            return
        start, end = pane.message_line_spans[index]
        renderables = self._message_renderables(
            pane.messages[index], pane, selected
        )
        action_ranges = self._append_header_actions(renderables.header)
        content, content_action_ranges = self._content_with_actions(
            pane.messages[index]
        )
        line = start
        widget = log.line_widget(line)
        if widget is not None:
            widget.update(renderables.header)
            widget.message_index = index
            widget.message_action_ranges = action_ranges
        line += 1
        if renderables.preview is not None:
            widget = log.line_widget(line)
            if widget is not None:
                widget.update(renderables.preview)
            line += 1
        widget = log.line_widget(line)
        if widget is not None:
            widget.update(content)
            widget.message_index = index
            widget.message_action_ranges = content_action_ranges
        for line_index in range(start, end):
            log.set_line_selected(line_index, selected)

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
        pane = pane or self._app.state.active_pane()
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
        action = self.selected_message_action(pane)
        label = MESSAGE_ACTION_LABELS[action]
        widget.update(f"{label} {name}: {preview}")

    def selected_message_action(self, pane: ChatPaneState) -> str:
        index = pane.message_action_index % len(MESSAGE_ACTIONS)
        pane.message_action_index = index
        return MESSAGE_ACTIONS[index]

    def move_message_action(self, pane: ChatPaneState, direction: int) -> None:
        if pane.reply_index < 0 or pane.reply_index >= len(pane.messages):
            return
        pane.message_action_index = (
            pane.message_action_index + direction
        ) % len(MESSAGE_ACTIONS)
        self.update_reply_info(pane)

    def execute_selected_message_action(self, pane: ChatPaneState) -> bool:
        if pane.reply_index < 0 or pane.reply_index >= len(pane.messages):
            return False
        action = self.selected_message_action(pane)
        if action == "reply":
            self.reply_to_message(pane, pane.reply_index)
            return True
        if action == "plus_one":
            self.plus_one_message(pane, pane.reply_index)
            return True
        return False
