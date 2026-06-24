"""Realtime OneBot event drain and dispatch for QQChatApp.

Extracted from ``ui/app.py`` so the App class stays focused on lifecycle
coordination.  This controller owns the periodic ``_drain_events`` tick and
the per-event dispatch to storage + pane widgets.

Pure event parsing has been extracted to
:func:`ui.logic.message_logic.parse_realtime_event`.
"""

from __future__ import annotations

from ui.logic import message_logic


class RealtimeController:
    """Periodically drains the OneBot event queue and dispatches incoming
    messages to storage and visible panes."""

    def __init__(self, app) -> None:
        self._app = app

    def _chat_key(self, chat_type: str, chat_id: int) -> str:
        return self._app.storage.chat_key(chat_type, chat_id)

    def _chat_is_open(self, chat_type: str, chat_id: int) -> bool:
        return any(
            pane.selected_chat is not None
            and pane.selected_chat.chat_type == chat_type
            and pane.selected_chat.chat_id == chat_id
            for pane in self._app.state.panes
        )

    def _event_mentions_self(self, event: dict) -> bool:
        self_id = getattr(self._app.ob, "self_id", None)
        if self_id is None:
            return False
        message = event.get("message", "")
        if not isinstance(message, list):
            return False
        self_id_text = str(self_id)
        for segment in message:
            if not isinstance(segment, dict) or segment.get("type") != "at":
                continue
            data = segment.get("data", {}) or {}
            qq = str(data.get("qq", ""))
            if qq == self_id_text or qq.lower() == "all":
                return True
        return False

    def _should_mark_pending(self, event: dict, chat_type: str, chat_id: int) -> bool:
        if self._chat_is_open(chat_type, chat_id):
            return False
        user_id = event.get("user_id")
        try:
            sender_id = int(user_id or 0)
        except (TypeError, ValueError):
            sender_id = 0
        self_id = getattr(self._app.ob, "self_id", None)
        if self_id is not None and sender_id == self_id:
            return False
        if chat_type == "private":
            return True
        return chat_type == "group" and self._event_mentions_self(event)

    # ------------------------------------------------------------------ #
    # Event drain (called from ``on_mount`` interval)
    # ------------------------------------------------------------------ #

    def drain_events(self) -> None:
        while True:
            try:
                event = self._app.ob.event_queue.get_nowait()
            except Exception:
                return
            self.handle_event(event)

    # ------------------------------------------------------------------ #
    # Single event dispatch (uses pure parse_realtime_event internally)
    # ------------------------------------------------------------------ #

    def handle_event(self, event: dict) -> None:
        chat_type = (
            "group" if event.get("message_type") == "group" else "private"
        )
        chat_id = (
            event.get("group_id")
            if chat_type == "group"
            else event.get("user_id")
        )
        try:
            chat_id = int(chat_id or 0)
        except (TypeError, ValueError):
            return
        if not chat_id:
            return
        at_resolver = self._app._msg_ctrl._at_resolver(chat_type, chat_id)
        parsed = message_logic.parse_realtime_event(event, at_resolver)
        if parsed is None:
            return
        message = parsed.message
        self._app.storage.add_message(
            message.chat_type, message.chat_id, message
        )
        self._app.storage.update_last_activity(
            message.chat_type, message.chat_id
        )
        self._app._mark_storage_dirty()
        self._app._touch_chat(
            message.chat_type, message.chat_id, message.time
        )

        updated = False
        for pane in list(self._app.state.panes):
            chat = pane.selected_chat
            if not (
                chat
                and chat.chat_type == message.chat_type
                and chat.chat_id == message.chat_id
            ):
                continue
            updated = True
            pane.messages.append(message)
            trimmed = self._app._msg_ctrl.trim_pane_messages(pane)
            log = self._app._msg_ctrl.message_log_or_none(pane)
            if log is None:
                continue
            if trimmed:
                self._app._msg_ctrl.render_messages(pane)
                if pane.auto_scroll:
                    log.scroll_end_when_ready()
                continue
            line_span = self._app._msg_ctrl.write_message(
                log,
                message,
                pane,
                message_index=len(pane.messages) - 1,
            )
            pane.message_line_spans.append(line_span)
            if pane.auto_scroll:
                log.scroll_end_when_ready()
        if self._should_mark_pending(event, message.chat_type, message.chat_id):
            self._app.state.add_pending_chat(
                self._chat_key(message.chat_type, message.chat_id)
            )
            self._app._chat_list_ctrl.render_chat_list()
        else:
            self._app._chat_list_ctrl.refresh_chat_list_item(
                message.chat_type, message.chat_id
            )
        if updated:
            self._app._msg_ctrl.update_reply_info(
                self._app._active_pane()
            )
