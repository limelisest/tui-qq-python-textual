"""Mouse-event hit-testing and right-click actions for QQChatApp.

Extracted from ``ui/app.py`` so the App class can focus on lifecycle and event
forwarding.  This controller owns hit-testing (``_mouse_event_in_chat_list``,
``_chat_from_mouse_event``, ``_message_action_from_mouse_event``,
``_input_from_mouse_event``) and action execution (copy, paste, pin toggle).
"""

from __future__ import annotations

from typing import Optional

from textual import events
from textual.widgets import Input, ListItem, ListView, TextArea

from models import ChatInfo
from ui.clipboard import get_system_clipboard, set_system_clipboard
from ui.state import ChatPaneState
from ui.theme import LEFT_MOUSE_BUTTON, RIGHT_MOUSE_BUTTON


class MouseController:
    """Owns mouse hit-testing and right-click actions."""

    def __init__(self, app) -> None:
        self._app = app

    # ------------------------------------------------------------------ #
    # Hit-testing helpers
    # ------------------------------------------------------------------ #

    def mouse_event_in_chat_list(self, event: events.MouseEvent) -> bool:
        try:
            widget, _ = self._app.screen.get_widget_at(event.screen_x, event.screen_y)
            list_view = self._app.query_one("#chat_list", ListView)
        except Exception:
            return False

        node = widget
        while node is not None:
            if node is list_view:
                return True
            node = getattr(node, "parent", None)
        return False

    def chat_from_mouse_event(self, event: events.MouseEvent) -> Optional[ChatInfo]:
        try:
            widget, _ = self._app.screen.get_widget_at(event.screen_x, event.screen_y)
            list_view = self._app.query_one("#chat_list", ListView)
        except Exception:
            return None

        item = None
        node = widget
        while node is not None:
            if isinstance(node, ListItem):
                item = node
                break
            node = getattr(node, "parent", None)
        if item is None:
            return None

        try:
            index = list(list_view.children).index(item)
        except ValueError:
            return None

        with self._app._state_lock:
            rendered = list(self._app.state.rendered_chats)
        if index < 0 or index >= len(rendered):
            return None
        return rendered[index]

    def message_action_from_mouse_event(
        self, event: events.MouseEvent
    ) -> Optional[tuple[ChatPaneState, int, str]]:
        try:
            widget, region = self._app.screen.get_widget_at(
                event.screen_x, event.screen_y
            )
        except Exception:
            return None

        node = widget
        target = None
        while node is not None:
            ranges = getattr(node, "message_action_ranges", None)
            if ranges:
                target = node
                break
            node = getattr(node, "parent", None)
        if target is None:
            return None

        pane = self._app._pane_from_widget(target)
        if pane is None:
            return None
        message_index = getattr(target, "message_index", None)
        if not isinstance(message_index, int):
            return None
        if message_index < 0 or message_index >= len(pane.messages):
            return None

        try:
            target_region = target.region
        except Exception:
            target_region = region
        local_x = event.screen_x - target_region.x
        local_y = event.screen_y - target_region.y
        logical_x = local_y * max(1, target_region.width) + local_x
        for action_name, (start, end) in getattr(
            target, "message_action_ranges", {}
        ).items():
            if start <= local_x < end or start <= logical_x < end:
                return pane, message_index, action_name
        return None

    def input_from_mouse_event(
        self, event: events.MouseEvent
    ) -> Optional[Input | TextArea]:
        try:
            widget, _ = self._app.screen.get_widget_at(event.screen_x, event.screen_y)
        except Exception:
            return None
        node = widget
        while node is not None:
            if isinstance(node, (Input, TextArea)) and not node.disabled:
                return node
            node = getattr(node, "parent", None)
        return None

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #

    def toggle_chat_pin(self, chat: ChatInfo) -> None:
        pinned = self._app.storage.toggle_chat_pinned(
            chat.chat_type, chat.chat_id, save=False
        )
        self._app._mark_storage_dirty()
        self._app._chat_list_ctrl.render_chat_list()
        self._app._chat_list_ctrl.schedule_chat_list_selection_sync(scroll=True)
        self._app._show_toast("已置顶" if pinned else "已取消置顶", chat.name)

    def copy_text_to_clipboard(self, text: str) -> None:
        self._app.copy_to_clipboard(text)
        set_system_clipboard(text)

    def paste_clipboard_to_input(self, target: TextArea) -> None:
        text = get_system_clipboard() or self._app.clipboard
        if not text:
            self._app._show_toast("剪贴板为空")
            return
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if not text:
            return
        target.focus()
        target.insert(text)

    def clear_message_selection_unless_action(self, event: events.MouseEvent) -> None:
        if self.message_action_from_mouse_event(event) is not None:
            return
        for pane in list(self._app.state.panes):
            if pane.reply_index >= 0:
                self._app._msg_ctrl.clear_message_selection(pane)

    # ------------------------------------------------------------------ #
    # Composite event handlers (called from app.py)
    # ------------------------------------------------------------------ #

    def handle_mouse_down(self, event: events.MouseDown) -> None:
        app = self._app
        if event.button == LEFT_MOUSE_BUTTON:
            self.clear_message_selection_unless_action(event)
        pane = app._pane_from_mouse_event(event)
        if pane is not None:
            app.state.navigation.layer = "pane"
            target_input = self.input_from_mouse_event(event)
            app._activate_pane(
                pane,
                focus_input=(
                    (
                        event.button == LEFT_MOUSE_BUTTON
                        or (
                            event.button == RIGHT_MOUSE_BUTTON
                            and target_input is not None
                            and target_input.has_class("msg_input")
                        )
                    )
                    and pane.selected_chat is not None
                ),
            )
        else:
            app.state.navigation.layer = "top"
            app._hide_all_message_inputs()
        if event.button == RIGHT_MOUSE_BUTTON:
            if self.mouse_event_in_chat_list(event):
                app.state.right_click_selected_text = ""
                return
            app.state.right_click_selected_text = (
                app.screen.get_selected_text() or ""
            )

    def handle_mouse_up(self, event: events.MouseUp) -> None:
        app = self._app
        if event.button == LEFT_MOUSE_BUTTON and self.mouse_event_in_chat_list(event):
            chat = self.chat_from_mouse_event(event)
            if chat is not None:
                event.stop()
                app._nav_ctrl.open_chat_from_list_selection(chat, focus_pane=True)
            return
        if event.button == LEFT_MOUSE_BUTTON:
            action = self.message_action_from_mouse_event(event)
            if action is not None:
                pane, message_index, action_name = action
                event.stop()
                if action_name == "reply":
                    app._msg_ctrl.reply_to_message(pane, message_index)
                elif action_name == "plus_one":
                    app._msg_ctrl.plus_one_message(pane, message_index)
                return
        if event.button != RIGHT_MOUSE_BUTTON:
            return
        event.stop()
        if self.mouse_event_in_chat_list(event):
            chat = self.chat_from_mouse_event(event)
            if chat is not None:
                self.toggle_chat_pin(chat)
            app.state.right_click_selected_text = ""
            return
        target_input = self.input_from_mouse_event(event)
        if target_input is not None:
            app.state.right_click_selected_text = ""
            self.paste_clipboard_to_input(target_input)
            return
        selected_text = (
            app.state.right_click_selected_text
            or app.screen.get_selected_text()
            or ""
        )
        app.state.right_click_selected_text = ""
        if selected_text:
            self.copy_text_to_clipboard(selected_text)
            app.screen.clear_selection()
            return
        app.state.right_click_selected_text = ""
