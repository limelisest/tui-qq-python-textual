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
        self._app._chat_list_ctrl.refresh_chat_list_item(
            message.chat_type, message.chat_id
        )
        if updated:
            self._app._msg_ctrl.update_reply_info(
                self._app._active_pane()
            )
