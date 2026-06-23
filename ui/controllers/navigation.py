"""Keyboard/focus navigation actions and layer management for QQChatApp.

Extracted from ``ui/app.py`` to keep the App class focused on lifecycle and
widget glue.  The controller takes an ``app`` reference (duck-typed) and
delegates widget queries / state mutations back to the App or its sibling
controllers (``_chat_list_ctrl``, ``_msg_ctrl``, ``_pane_ctrl``,
``_sidebar_ctrl``).
"""

from __future__ import annotations

from typing import Optional

from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.widgets import Input, ListView

from models import ChatInfo
from ui.logic import chat_logic
from ui.navigation import compute_pane_index_in_direction
from ui.state import ChatPaneState, same_chat


class NavigationController:
    """Owns keyboard navigation state-machine: layer switching, action
    methods, preview navigation, pane selection, and message reply cycling."""

    def __init__(self, app) -> None:
        self._app = app

    # ------------------------------------------------------------------ #
    # Layer switching
    # ------------------------------------------------------------------ #

    def enter_top_layer(self) -> None:
        self._app.state.navigation.layer = "top"
        self._app._pane_ctrl.hide_all_message_inputs()
        self._app._chat_list_ctrl.set_search_nav_selected(False)
        self._app._pane_ctrl.refresh_pane_active_classes()

    def enter_chat_list_layer(self) -> None:
        self._app.state.navigation.layer = "chat_list"
        self._app._pane_ctrl.hide_all_message_inputs()
        self._app.state.navigation.chat_list_on_search = False
        self._app._chat_list_ctrl.set_search_nav_selected(False)
        try:
            self._app.query_one("#sidebar", Vertical).remove_class("top_selected")
        except NoMatches:
            pass
        self._app._pane_ctrl.refresh_pane_active_classes()
        self._app._chat_list_ctrl.schedule_chat_list_selection_sync(scroll=True)
        try:
            self._app.query_one("#chat_list", ListView).focus()
        except NoMatches:
            pass

    def enter_search_layer(self) -> None:
        self._app.state.navigation.layer = "search"
        self._app._pane_ctrl.hide_all_message_inputs()
        self._app.state.navigation.chat_list_on_search = True
        self._app._chat_list_ctrl.set_search_nav_selected(False)
        try:
            self._app.query_one("#sidebar", Vertical).remove_class("top_selected")
        except NoMatches:
            pass
        self._app._pane_ctrl.refresh_pane_active_classes()
        self._app.query_one("#search", Input).focus()

    def enter_pane_layer(
        self, pane: Optional[ChatPaneState] = None, focus_input: bool = False
    ) -> None:
        pane = pane or self._app._active_pane()
        self._app.state.navigation.layer = "pane"
        self._app.state.navigation.top_target_pane_uid = pane.uid
        try:
            self._app.query_one("#sidebar", Vertical).remove_class("top_selected")
        except NoMatches:
            pass
        self._app._pane_ctrl.refresh_pane_active_classes()
        self.activate_pane(
            pane, focus_input=focus_input and pane.selected_chat is not None
        )
        self._app._chat_list_ctrl.schedule_chat_list_selection_sync(scroll=True)

    def enter_pane_layer_after_refresh(self, pane: ChatPaneState) -> None:
        self._app.state.pending_pane_focus_uid = pane.uid

        def enter() -> None:
            target = self._app._pane_by_uid(pane.uid)
            if target is not None:
                self.enter_pane_layer(target, focus_input=True)

        self._app.call_after_refresh(enter)
        self._app.set_timer(0.02, enter)
        self._app.set_timer(0.08, enter)
        self._app.set_timer(
            0.16, lambda uid=pane.uid: self.clear_pending_pane_focus(uid)
        )

    def clear_pending_pane_focus(self, pane_uid: int) -> None:
        if self._app.state.pending_pane_focus_uid == pane_uid:
            self._app.state.pending_pane_focus_uid = None

    # ------------------------------------------------------------------ #
    # Focus area helpers
    # ------------------------------------------------------------------ #

    def focus_chat_list_area(self) -> None:
        ss = self._app.state.sidebar_state
        if ss.hidden_by is not None:
            ss.tab_restore_reason = ss.hidden_by
            ss.tab_restore_auto_paused = ss.auto_paused
        else:
            ss.tab_restore_reason = None
        ss.auto_paused = False
        self._app._sidebar_ctrl.set_sidebar_visible(True)
        self._app.state.navigation.top_target_pane_uid = None
        self.enter_search_layer()

    def focus_pane_selection_area(self) -> None:
        pane = self._app._pane_by_uid(
            self._app.state.navigation.top_target_pane_uid or self._app.state.active_pane_uid
        )
        if pane is None:
            pane = self._app._active_pane()
        self.set_top_target_index(self._app.state.panes.index(pane) + 1)
        self._app.screen.set_focus(None)
        ss = self._app.state.sidebar_state
        if ss.tab_restore_reason is not None:
            reason = ss.tab_restore_reason
            auto_paused = ss.tab_restore_auto_paused
            ss.tab_restore_reason = None
            ss.tab_restore_auto_paused = False
            ss.auto_paused = auto_paused
            self._app._sidebar_ctrl.set_sidebar_visible(False, reason)

    # ------------------------------------------------------------------ #
    # Top-target selection helpers
    # ------------------------------------------------------------------ #

    def top_target_index(self) -> int:
        if self._app.state.navigation.top_target_pane_uid is None:
            return 0
        for index, pane in enumerate(self._app.state.panes, start=1):
            if pane.uid == self._app.state.navigation.top_target_pane_uid:
                return index
        return 0

    def set_top_target_index(self, index: int) -> None:
        count = len(self._app.state.panes) + 1
        index %= count
        self._app.state.navigation.layer = "top"
        self._app._pane_ctrl.hide_all_message_inputs()
        self._app._chat_list_ctrl.set_search_nav_selected(False)
        try:
            sidebar = self._app.query_one("#sidebar", Vertical)
        except NoMatches:
            sidebar = None
        if index == 0:
            self._app.state.navigation.top_target_pane_uid = None
            if sidebar is not None:
                sidebar.add_class("top_selected")
            self._app._pane_ctrl.refresh_pane_active_classes()
            return
        if sidebar is not None:
            sidebar.remove_class("top_selected")
        pane = self._app.state.panes[index - 1]
        self._app.state.navigation.top_target_pane_uid = pane.uid
        self._app.state.active_pane_uid = pane.uid
        self._app._pane_ctrl.refresh_pane_active_classes()
        self._app._chat_list_ctrl.schedule_chat_list_selection_sync(scroll=True)

    def move_pane_selection_in_direction(self, direction: str) -> None:
        index = compute_pane_index_in_direction(
            self._app.state.panes,
            self._app.state.navigation.top_target_pane_uid or self._app.state.active_pane_uid,
            self._app.state.split_layout_horizontal,
            direction,
        )
        if index is not None:
            self.set_top_target_index(index)

    # ------------------------------------------------------------------ #
    # Pane activation
    # ------------------------------------------------------------------ #

    def activate_pane(
        self, pane: Optional[ChatPaneState], focus_input: bool = False
    ) -> None:
        if pane is None:
            return
        changed = pane.uid != self._app.state.active_pane_uid
        if changed:
            self._app.state.active_pane_uid = pane.uid
            self._app.state.navigation.top_target_pane_uid = pane.uid
            self._app._pane_ctrl.refresh_pane_active_classes()
            self._app._set_app_title_text("")
            self._app._chat_list_ctrl.schedule_chat_list_selection_sync(scroll=True)
            self._app._sidebar_ctrl.apply_sidebar_auto_visibility()
        if focus_input and pane.selected_chat is not None:
            self._app._pane_ctrl.set_input_owner_pane(pane)
            msg_input = self._app._msg_ctrl.message_input_or_none(pane)
            if msg_input is not None and not msg_input.disabled:
                msg_input.focus()
            return
        self._app._pane_ctrl.hide_all_message_inputs()
        self._app.screen.set_focus(None)

    # ------------------------------------------------------------------ #
    # Input helpers
    # ------------------------------------------------------------------ #

    def focused_input(self) -> Optional[Input]:
        focused = self._app.screen.focused
        return focused if isinstance(focused, Input) else None

    def cursor_target_input(self) -> Optional[Input]:
        focused = self.focused_input()
        if focused is not None:
            return focused
        pane = self._app._pane_by_uid(self._app.state.input_owner_pane_uid or 0)
        if pane is None or not self._app._msg_ctrl.pane_input_visible(pane):
            return None
        return self._app._msg_ctrl.message_input_or_none(pane)

    # ------------------------------------------------------------------ #
    # Message focus sync (called from Focus/Blur event handlers)
    # ------------------------------------------------------------------ #

    def sync_message_input_focus(self) -> None:
        if self._app.state.pending_pane_focus_uid is not None:
            target = self._app._pane_by_uid(
                self._app.state.pending_pane_focus_uid
            )
            if target is not None and target.selected_chat is not None:
                self._app.call_after_refresh(
                    lambda target=target: self.enter_pane_layer(target)
                )
                return
        focused = self._app.screen.focused
        if focused is None:
            self._app._pane_ctrl.hide_all_message_inputs()
            self._app._pane_ctrl.refresh_pane_active_classes()
            return
        if self._app._chat_list_ctrl.search_has_focus():
            self._app.state.navigation.layer = "search"
            self._app._pane_ctrl.hide_all_message_inputs()
            self._app._pane_ctrl.refresh_pane_active_classes()
            return
        if isinstance(focused, ListView) and focused.id == "chat_list":
            self._app.state.navigation.layer = "chat_list"
            self._app._pane_ctrl.hide_all_message_inputs()
            self._app._pane_ctrl.refresh_pane_active_classes()
            return
        pane = self._app._pane_from_widget(focused)
        if pane is None:
            self._app._pane_ctrl.hide_all_message_inputs()
            self._app._pane_ctrl.refresh_pane_active_classes()
            return
        self._app.state.navigation.layer = "pane"
        self._app.state.active_pane_uid = pane.uid
        self._app.state.navigation.top_target_pane_uid = pane.uid
        if isinstance(focused, Input) and focused.has_class("msg_input"):
            self._app._pane_ctrl.set_input_owner_pane(
                pane, scroll_if_auto=True
            )
        else:
            self._app._pane_ctrl.hide_all_message_inputs()
            self._app.screen.set_focus(None)
            self._app._pane_ctrl.refresh_pane_active_classes()

    # ------------------------------------------------------------------ #
    # Chat / preview navigation
    # ------------------------------------------------------------------ #

    def navigate_chat(self, direction: int) -> None:
        pane = self._app._active_pane()
        with self._app._state_lock:
            chats = list(self._app.state.filtered_chats)
        base = pane.preview_chat or pane.selected_chat
        index = chat_logic.navigate_index(chats, base, direction)
        if index is None:
            return
        chat = chats[index]
        if pane.selected_chat is not None and same_chat(
            chat, pane.selected_chat
        ):
            pane.preview_chat = None
        else:
            pane.preview_chat = chat
        with self._app._state_lock:
            rendered = list(self._app.state.rendered_chats)

        target_index = chat_logic.rendered_chat_index(rendered, chat)
        if target_index is None:
            self._app._chat_list_ctrl.render_chat_list()
            self._app._chat_list_ctrl.schedule_chat_list_selection_sync(scroll=True)
        else:
            self._app._chat_list_ctrl.schedule_chat_list_selection_sync(scroll=True)

        self.cancel_preview_timer(pane)
        if pane.preview_chat is not None:
            token = pane.preview_token
            self._app.set_timer(
                1.0,
                lambda uid=pane.uid, token=token: self.commit_preview_if_current(
                    uid, token
                ),
            )

    def cancel_preview_timer(
        self, pane: Optional[ChatPaneState] = None
    ) -> None:
        pane = pane or self._app._active_pane()
        pane.preview_token += 1

    def commit_preview_if_current(
        self, pane_uid: int, token: int
    ) -> None:
        pane = self._app._pane_by_uid(pane_uid)
        if pane is not None and token == pane.preview_token:
            self.commit_preview(pane)

    def commit_preview(
        self, pane: Optional[ChatPaneState] = None
    ) -> None:
        pane = pane or self._app._active_pane()
        self.cancel_preview_timer(pane)
        chat = pane.preview_chat
        if chat is None:
            return
        pane.preview_chat = None
        if pane.selected_chat is not None and same_chat(
            chat, pane.selected_chat
        ):
            self._app._chat_list_ctrl.render_chat_list()
            self._app._chat_list_ctrl.schedule_chat_list_selection_sync(scroll=True)
            return
        self._app._open_chat(chat, pane)
        self._app._sidebar_ctrl.hide_sidebar_after_narrow_chat_selection()

    # ------------------------------------------------------------------ #
    # Open / close chat helpers
    # ------------------------------------------------------------------ #

    def open_chat_from_list_selection(
        self, chat: ChatInfo, focus_pane: bool = True
    ) -> None:
        pane = self._app._active_pane()
        if not same_chat(chat, pane.selected_chat):
            self._app._open_chat(chat, pane)
        self._app._chat_list_ctrl.clear_search_text()
        self._app._sidebar_ctrl.hide_sidebar_after_narrow_chat_selection()
        if focus_pane:
            self.enter_pane_layer_after_refresh(pane)

    def open_selected_search_chat(self) -> None:
        chat = self._app._chat_list_ctrl.selected_search_chat()
        if chat is None:
            return
        self.open_chat_from_list_selection(chat, focus_pane=True)

    def close_search_mode(self) -> None:
        pane = self._app._active_pane()
        self.cancel_preview_timer(pane)
        pane.preview_chat = None
        search = self._app.query_one("#search", Input)
        if search.value:
            search.clear()
            self._app._chat_list_ctrl.render_chat_list()
        else:
            self._app._chat_list_ctrl.schedule_chat_list_selection_sync(scroll=True)
        self.enter_chat_list_layer()

    # ------------------------------------------------------------------ #
    # Actions (bound to keyboard shortcuts via thin proxies in app.py)
    # ------------------------------------------------------------------ #

    def action_refresh_chats(self) -> None:
        self._app._show_toast("正在刷新会话...")
        self._app._run_thread(self._app._load_chats_worker)

    def action_add_pane(self) -> None:
        self._app._add_pane()

    def action_close_current_pane(self) -> None:
        self._app._close_pane(self._app._active_pane())

    def action_toggle_split_layout(self) -> None:
        self._app._toggle_split_layout()

    def action_scroll_bottom(self) -> None:
        if self._app.state.navigation.layer != "pane":
            return
        pane = self._app._active_pane()
        if pane.selected_chat is None:
            return
        pane.auto_scroll = True
        self._app._msg_ctrl.hide_scroll_bottom_btn(pane)
        self._app._msg_ctrl.force_scroll_end(pane.uid)

    def action_prev_chat(self) -> None:
        self._app._sidebar_ctrl.show_sidebar_for_narrow_navigation()
        self.navigate_chat(-1)

    def action_next_chat(self) -> None:
        self._app._sidebar_ctrl.show_sidebar_for_narrow_navigation()
        self.navigate_chat(1)

    def action_toggle_focus_area(self) -> None:
        nav = self._app.state.navigation
        if nav.layer == "top" and nav.top_target_pane_uid is not None:
            self.focus_chat_list_area()
            return
        if nav.layer == "pane":
            self.focus_chat_list_area()
            return
        self.focus_pane_selection_area()

    def action_nav_left(self) -> None:
        nav = self._app.state.navigation
        if nav.layer == "pane":
            pane = self._app._active_pane()
            if pane.reply_index >= 0:
                self._app._msg_ctrl.move_message_action(pane, -1)
                return
        focused = self.cursor_target_input()
        if focused is not None:
            focused.action_cursor_left()
            return
        if nav.layer == "top" and nav.top_target_pane_uid is not None:
            self.move_pane_selection_in_direction("left")

    def action_nav_right(self) -> None:
        nav = self._app.state.navigation
        if nav.layer == "pane":
            pane = self._app._active_pane()
            if pane.reply_index >= 0:
                self._app._msg_ctrl.move_message_action(pane, 1)
                return
        focused = self.cursor_target_input()
        if focused is not None:
            focused.action_cursor_right()
            return
        if nav.layer == "top" and nav.top_target_pane_uid is not None:
            self.move_pane_selection_in_direction("right")

    def action_nav_enter(self) -> None:
        nav = self._app.state.navigation
        if nav.layer == "top":
            if nav.top_target_pane_uid is None:
                if nav.chat_list_on_search:
                    self.enter_search_layer()
                else:
                    self.open_selected_search_chat()
                return
            pane = self._app._pane_by_uid(nav.top_target_pane_uid)
            if pane is not None:
                self.enter_pane_layer(pane, focus_input=True)
            return
        if nav.layer == "chat_list":
            if nav.chat_list_on_search:
                self.enter_search_layer()
            else:
                self.open_selected_search_chat()
            return
        if nav.layer == "search":
            self.open_selected_search_chat()
            return
        if nav.layer == "pane":
            focused = self._app.screen.focused
            pane = self._app._active_pane()
            if pane.reply_index >= 0:
                if (
                    isinstance(focused, Input)
                    and focused.has_class("msg_input")
                    and focused.value.strip()
                ):
                    self._app._msg_ctrl.submit_message_input(focused)
                    return
                if self._app._msg_ctrl.execute_selected_message_action(pane):
                    return
            if isinstance(focused, Input) and focused.has_class("msg_input"):
                self._app._msg_ctrl.submit_message_input(focused)
                return
            self.action_focus_message()

    def action_focus_search(self) -> None:
        self._app.state.sidebar_state.auto_paused = False
        self._app._sidebar_ctrl.set_sidebar_visible(True)
        self.enter_search_layer()

    def action_focus_message(self) -> None:
        pane = self._app._active_pane()
        if pane.selected_chat:
            msg_input = self._app._msg_ctrl.message_input_or_none(pane)
            if msg_input is not None and not msg_input.disabled:
                self._app._pane_ctrl.set_input_owner_pane(pane)
                msg_input.focus()

    def action_reply_previous(self) -> None:
        nav = self._app.state.navigation
        if nav.layer == "top":
            if nav.top_target_pane_uid is None:
                self._app._chat_list_ctrl.move_chat_list_layer_selection(-1)
            else:
                self.move_pane_selection_in_direction("up")
            return
        if nav.layer == "chat_list":
            self._app._chat_list_ctrl.move_chat_list_layer_selection(-1)
            return
        if nav.layer == "search":
            self._app._chat_list_ctrl.move_search_selection(-1)
            return
        if nav.layer != "pane":
            return
        pane = self._app._active_pane()
        if not pane.messages:
            return
        old_index = pane.reply_index
        if pane.reply_index < 0:
            pane.reply_index = len(pane.messages) - 1
        elif pane.reply_index > 0:
            pane.reply_index -= 1
        self._app._msg_ctrl.refresh_message_selection(
            pane, old_index, pane.reply_index
        )

    def action_reply_next(self) -> None:
        nav = self._app.state.navigation
        if nav.layer == "top":
            if nav.top_target_pane_uid is None:
                self._app._chat_list_ctrl.move_chat_list_layer_selection(1)
            else:
                self.move_pane_selection_in_direction("down")
            return
        if nav.layer == "chat_list":
            self._app._chat_list_ctrl.move_chat_list_layer_selection(1)
            return
        if nav.layer == "search":
            self._app._chat_list_ctrl.move_search_selection(1)
            return
        if nav.layer != "pane":
            return
        pane = self._app._active_pane()
        if not pane.messages:
            return
        old_index = pane.reply_index
        if pane.reply_index < 0:
            pane.reply_index = 0
            self._app._msg_ctrl.refresh_message_selection(
                pane, old_index, pane.reply_index
            )
            return
        pane.reply_index += 1
        if pane.reply_index >= len(pane.messages):
            pane.reply_index = -1
        self._app._msg_ctrl.refresh_message_selection(
            pane, old_index, pane.reply_index
        )

    def action_clear_reply(self) -> None:
        nav = self._app.state.navigation
        if nav.layer == "search":
            self.close_search_mode()
            return
        if nav.layer == "chat_list":
            self.enter_top_layer()
            return
        if nav.layer == "pane":
            pane = self._app._active_pane()
            if pane.preview_chat is None and pane.reply_index < 0:
                self.enter_top_layer()
                return
        elif nav.layer == "top":
            self._app._pane_ctrl.hide_all_message_inputs()
            return
        pane = self._app._active_pane()
        if pane.preview_chat is not None:
            self.cancel_preview_timer(pane)
            pane.preview_chat = None
            self._app._chat_list_ctrl.render_chat_list()
            self._app._chat_list_ctrl.schedule_chat_list_selection_sync(scroll=True)
        elif pane.reply_index >= 0:
            self._app._msg_ctrl.clear_message_selection(pane)
        elif pane.selected_chat:
            msg_input = self._app._msg_ctrl.message_input_or_none(pane)
            if msg_input is not None:
                msg_input.focus()
        else:
            self._app.query_one("#search", Input).focus()
