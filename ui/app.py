"""Single-screen Textual frontend for QQ chats.

``QQChatApp`` owns the Textual widgets and the app state, and delegates the
pure logic to :mod:`ui.logic` and the network/parsing to :mod:`ui.services`.
This keeps the file focused on "state machine + widget glue" so new features
land in focused modules instead of a 1600-line monolith.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Callable, Optional

from rich.text import Text
from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Button, Input, ListItem, ListView, Static

import config
from models import ChatInfo, MessageData
from onebot import OneBotClient
from storage import Storage
from ui.clipboard import get_system_clipboard, set_system_clipboard
from ui.controllers.chat_list import ChatListController
from ui.controllers.messages import MessageController
from ui.controllers.panes import PaneController
from ui.logic import chat_logic, message_logic

from ui.navigation import NavigationState, compute_pane_index_in_direction
from ui.services import chat_service, message_service
from ui.sidebar import SidebarState, has_empty_pane, is_sidebar_narrow, widget_inside
from ui.state import (
    ChatPaneState,
    same_chat,
)
from ui.styles import APP_CSS
from ui.theme import (
    LEFT_MOUSE_BUTTON,
    RIGHT_MOUSE_BUTTON,
)
from ui.text_utils import ellipsize
from ui.widgets.chat_pane import build_pane_container


class QQChatApp(App):
    """Single-screen Textual frontend for QQ chats."""

    TITLE = "TUI-QQ"
    SUB_TITLE = "NapCat / OneBot v11"
    CSS = APP_CSS

    BINDINGS = [
        Binding("ctrl+r", "refresh_chats", "刷新"),
        Binding("ctrl+s", "focus_search", "搜索", priority=True),
        Binding("ctrl+t", "change_theme", "主题"),
        Binding("up", "reply_previous", "上一个回复", priority=True),
        Binding("down", "reply_next", "下一个回复", priority=True),
        Binding("left", "nav_left", "左", priority=True),
        Binding("right", "nav_right", "右", priority=True),
        Binding("tab", "toggle_focus_area", "切换区域", priority=True),
        Binding("enter", "nav_enter", "进入", priority=True),
        Binding("ctrl+w", "close_current_pane", "关闭分屏", priority=True),
        Binding("ctrl+d", "add_pane", "分屏", priority=True),
        Binding("ctrl+e", "toggle_split_layout", "切换分屏布局", priority=True),
        Binding("escape", "clear_reply", "取消"),
    ]

    def __init__(self):
        super().__init__()
        self._settings_ready = False
        self._settings = self._load_settings()
        saved_theme = self._settings.get("theme")
        if isinstance(saved_theme, str) and saved_theme:
            try:
                self.theme = saved_theme
            except Exception:
                pass
        self._settings_ready = True

        self.storage = Storage(config.CACHE_FILE)
        self.storage.load()
        self.ob = OneBotClient()

        self._state_lock = threading.Lock()
        self._chats: list[ChatInfo] = []
        self._filtered_chats: list[ChatInfo] = []
        self._rendered_chats: list[Optional[ChatInfo]] = []
        self._search_cache: dict[tuple[str, int], str] = {}
        self._connected = False
        self._toast_token = 0
        self._storage_dirty = False
        self._panes: list[ChatPaneState] = [ChatPaneState(uid=1)]
        self._active_pane_uid = 1
        self._input_owner_pane_uid: Optional[int] = None
        self._navigation = NavigationState()
        self._next_pane_uid = 2
        self._split_layout_horizontal = False
        self._pending_pane_focus_uid: Optional[int] = None
        self._friend_remarks: dict[int, str] = {}
        self._right_click_selected_text = ""
        self._sidebar_state = SidebarState()
        self._chat_list_ctrl = ChatListController(self)
        self._msg_ctrl = MessageController(self)
        self._pane_ctrl = PaneController(self)

    @property
    def _selected_chat(self) -> Optional[ChatInfo]:
        return self._active_pane().selected_chat

    @_selected_chat.setter
    def _selected_chat(self, value: Optional[ChatInfo]) -> None:
        self._active_pane().selected_chat = value

    @property
    def _messages(self) -> list[MessageData]:
        return self._active_pane().messages

    @_messages.setter
    def _messages(self, value: list[MessageData]) -> None:
        self._active_pane().messages = value

    @property
    def _message_line_spans(self) -> list[tuple[int, int]]:
        return self._active_pane().message_line_spans

    @_message_line_spans.setter
    def _message_line_spans(self, value: list[tuple[int, int]]) -> None:
        self._active_pane().message_line_spans = value

    @property
    def _reply_index(self) -> int:
        return self._active_pane().reply_index

    @_reply_index.setter
    def _reply_index(self, value: int) -> None:
        self._active_pane().reply_index = value

    @property
    def _auto_scroll(self) -> bool:
        return self._active_pane().auto_scroll

    @_auto_scroll.setter
    def _auto_scroll(self, value: bool) -> None:
        self._active_pane().auto_scroll = value

    @property
    def _prev_scroll_y(self) -> int:
        return self._active_pane().prev_scroll_y

    @_prev_scroll_y.setter
    def _prev_scroll_y(self, value: int) -> None:
        self._active_pane().prev_scroll_y = value

    @property
    def _preview_chat(self) -> Optional[ChatInfo]:
        return self._active_pane().preview_chat

    @_preview_chat.setter
    def _preview_chat(self, value: Optional[ChatInfo]) -> None:
        self._active_pane().preview_chat = value

    @property
    def _preview_token(self) -> int:
        return self._active_pane().preview_token

    @_preview_token.setter
    def _preview_token(self, value: int) -> None:
        self._active_pane().preview_token = value

    # ------------------------------------------------------------------ #
    # Pane helpers (delegated to PaneController)
    # ------------------------------------------------------------------ #

    def _active_pane(self) -> ChatPaneState:
        return self._pane_ctrl.active_pane()

    def _pane_by_uid(self, uid: int) -> Optional[ChatPaneState]:
        return self._pane_ctrl.pane_by_uid(uid)

    def _pane_widget(self, pane, name, widget_type):
        return self._pane_ctrl.pane_widget(pane, name, widget_type)

    def _pane_from_widget(self, widget) -> Optional[ChatPaneState]:
        return self._pane_ctrl.pane_from_widget(widget)

    def _pane_from_mouse_event(
        self, event: events.MouseEvent
    ) -> Optional[ChatPaneState]:
        return self._pane_ctrl.pane_from_mouse_event(event)

    def _set_input_owner_pane(
        self, pane: Optional[ChatPaneState], scroll_if_auto: bool = True
    ) -> None:
        self._pane_ctrl.set_input_owner_pane(pane, scroll_if_auto)

    def _hide_all_message_inputs(self) -> None:
        self._pane_ctrl.hide_all_message_inputs()

    def _enter_top_layer(self) -> None:
        self._navigation.layer = "top"
        self._hide_all_message_inputs()
        self._chat_list_ctrl.set_search_nav_selected(False)
        self._refresh_pane_active_classes()

    def _enter_chat_list_layer(self) -> None:
        self._navigation.layer = "chat_list"
        self._hide_all_message_inputs()
        self._navigation.chat_list_on_search = False
        self._chat_list_ctrl.set_search_nav_selected(False)
        try:
            self.query_one("#sidebar", Vertical).remove_class("top_selected")
        except NoMatches:
            pass
        self._refresh_pane_active_classes()
        self._chat_list_ctrl.schedule_chat_list_selection_sync(scroll=True)
        try:
            self.query_one("#chat_list", ListView).focus()
        except NoMatches:
            pass

    def _enter_search_layer(self) -> None:
        self._navigation.layer = "search"
        self._hide_all_message_inputs()
        self._navigation.chat_list_on_search = True
        self._chat_list_ctrl.set_search_nav_selected(False)
        try:
            self.query_one("#sidebar", Vertical).remove_class("top_selected")
        except NoMatches:
            pass
        self._refresh_pane_active_classes()
        self.query_one("#search", Input).focus()

    def _enter_pane_layer(self, pane: Optional[ChatPaneState] = None) -> None:
        pane = pane or self._active_pane()
        self._navigation.layer = "pane"
        self._navigation.top_target_pane_uid = pane.uid
        try:
            self.query_one("#sidebar", Vertical).remove_class("top_selected")
        except NoMatches:
            pass
        self._refresh_pane_active_classes()
        self._activate_pane(pane, focus_input=pane.selected_chat is not None)

    def _enter_pane_layer_after_refresh(self, pane: ChatPaneState) -> None:
        self._pending_pane_focus_uid = pane.uid

        def enter() -> None:
            target = self._pane_by_uid(pane.uid)
            if target is not None:
                self._enter_pane_layer(target)

        self.call_after_refresh(enter)
        self.set_timer(0.02, enter)
        self.set_timer(0.08, enter)
        self.set_timer(
            0.16, lambda uid=pane.uid: self._clear_pending_pane_focus(uid)
        )

    def _clear_pending_pane_focus(self, pane_uid: int) -> None:
        if self._pending_pane_focus_uid == pane_uid:
            self._pending_pane_focus_uid = None

    def _top_target_index(self) -> int:
        if self._navigation.top_target_pane_uid is None:
            return 0
        for index, pane in enumerate(self._panes, start=1):
            if pane.uid == self._navigation.top_target_pane_uid:
                return index
        return 0

    def _set_top_target_index(self, index: int) -> None:
        count = len(self._panes) + 1
        index %= count
        self._navigation.layer = "top"
        self._hide_all_message_inputs()
        self._chat_list_ctrl.set_search_nav_selected(False)
        try:
            sidebar = self.query_one("#sidebar", Vertical)
        except NoMatches:
            sidebar = None
        if index == 0:
            self._navigation.top_target_pane_uid = None
            if sidebar is not None:
                sidebar.add_class("top_selected")
            self._refresh_pane_active_classes()
            return
        if sidebar is not None:
            sidebar.remove_class("top_selected")
        pane = self._panes[index - 1]
        self._navigation.top_target_pane_uid = pane.uid
        self._active_pane_uid = pane.uid
        self._refresh_pane_active_classes()
        self._chat_list_ctrl.schedule_chat_list_selection_sync(scroll=True)

    def _move_pane_selection_in_direction(self, direction: str) -> None:
        index = compute_pane_index_in_direction(
            self._panes,
            self._navigation.top_target_pane_uid or self._active_pane_uid,
            self._split_layout_horizontal,
            direction,
        )
        if index is not None:
            self._set_top_target_index(index)

    def _focus_chat_list_area(self) -> None:
        if self._sidebar_state.hidden_by is not None:
            self._sidebar_state.tab_restore_reason = self._sidebar_state.hidden_by
            self._sidebar_state.tab_restore_auto_paused = self._sidebar_state.auto_paused
        else:
            self._sidebar_state.tab_restore_reason = None
        self._sidebar_state.auto_paused = False
        self._set_sidebar_visible(True)
        self._set_top_target_index(0)

        def focus_list() -> None:
            try:
                self.query_one("#chat_list", ListView).focus()
            except NoMatches:
                pass

        focus_list()
        self.call_after_refresh(focus_list)

    def _focus_pane_selection_area(self) -> None:
        pane = self._pane_by_uid(
            self._navigation.top_target_pane_uid or self._active_pane_uid
        )
        if pane is None:
            pane = self._active_pane()
        self._set_top_target_index(self._panes.index(pane) + 1)
        self.screen.set_focus(None)
        if self._sidebar_state.tab_restore_reason is not None:
            reason = self._sidebar_state.tab_restore_reason
            auto_paused = self._sidebar_state.tab_restore_auto_paused
            self._sidebar_state.tab_restore_reason = None
            self._sidebar_state.tab_restore_auto_paused = False
            self._sidebar_state.auto_paused = auto_paused
            self._set_sidebar_visible(False, reason)

    def _focused_input(self) -> Optional[Input]:
        focused = self.screen.focused
        return focused if isinstance(focused, Input) else None

    def _cursor_target_input(self) -> Optional[Input]:
        focused = self._focused_input()
        if focused is not None:
            return focused
        pane = self._pane_by_uid(self._input_owner_pane_uid or 0)
        if pane is None or not self._msg_ctrl.pane_input_visible(pane):
            return None
        return self._msg_ctrl.message_input_or_none(pane)

    def _activate_pane(
        self, pane: Optional[ChatPaneState], focus_input: bool = False
    ) -> None:
        if pane is None:
            return
        changed = pane.uid != self._active_pane_uid
        if changed:
            self._active_pane_uid = pane.uid
            self._navigation.top_target_pane_uid = pane.uid
            self._refresh_pane_active_classes()
            self._set_app_title_text("")
            self._chat_list_ctrl.schedule_chat_list_selection_sync(scroll=True)
            self._apply_sidebar_auto_visibility()
        self._set_input_owner_pane(pane)
        if focus_input and pane.selected_chat is not None:
            msg_input = self._msg_ctrl.message_input_or_none(pane)
            if msg_input is not None and not msg_input.disabled:
                msg_input.focus()

    def _refresh_pane_active_classes(self) -> None:
        self._pane_ctrl.refresh_pane_active_classes()

    def _update_pane_titles(self) -> None:
        self._pane_ctrl.update_pane_titles()

    def _update_pane_grid_class(self) -> None:
        self._pane_ctrl.update_pane_grid_class()

    def _update_split_buttons(self) -> None:
        self._pane_ctrl.update_split_buttons()

    # ------------------------------------------------------------------ #
    # Settings / theme
    # ------------------------------------------------------------------ #

    def _load_settings(self) -> dict:
        try:
            with open(config.SETTINGS_FILE, "r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_settings(self) -> None:
        try:
            os.makedirs(config.CACHE_DIR, exist_ok=True)
            with open(config.SETTINGS_FILE, "w", encoding="utf-8") as file:
                json.dump(self._settings, file, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def watch_theme(self, theme: str) -> None:
        if not getattr(self, "_settings_ready", False):
            return
        self._settings["theme"] = theme
        self._save_settings()

    # ------------------------------------------------------------------ #
    # Layout / lifecycle
    # ------------------------------------------------------------------ #

    def compose(self) -> ComposeResult:
        with Horizontal(id="top_bar"):
            yield Button("<", id="sidebar_toggle_btn", compact=True)
            yield Button("⭘", id="header_menu_btn", compact=True)
            yield Static("", id="top_bar_spacer")
            yield Button("#", id="split_layout_btn", compact=True)
            yield Button("+", id="split_add_btn", compact=True)
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Input(
                    placeholder="搜索: 支持名称 / 简拼 / 小鹤, g:群 f:好友",
                    id="search",
                )
                yield ListView(id="chat_list")
            with Vertical(id="main"):
                with Container(id="pane_grid", classes="pane_count_1"):
                    yield build_pane_container(
                        self._panes[0], self._navigation.layer, self._active_pane_uid,
                        self._navigation.top_target_pane_uid, self._msg_ctrl.pane_input_visible(self._panes[0])
                    )
                with Horizontal(id="toast_row"):
                    yield Static("", id="toast_spacer")
                    yield Static("", id="toast")

    def on_mount(self) -> None:
        menu_btn = self.query_one("#header_menu_btn", Button)
        menu_btn.disabled = not self.ENABLE_COMMAND_PALETTE
        menu_btn.tooltip = (
            "打开命令面板" if self.ENABLE_COMMAND_PALETTE else "命令面板不可用"
        )
        self._update_split_buttons()
        self._update_pane_titles()
        self._set_top_target_index(0)
        self._apply_sidebar_auto_visibility()
        self.set_interval(0.1, self._drain_events)
        self.set_interval(0.1, self._msg_ctrl.check_scroll)
        self.set_interval(2.0, self._flush_storage_if_dirty)
        self._run_thread(self._connect_and_load)

    def on_unmount(self) -> None:
        self.storage.save()
        self.ob.disconnect()

    def on_resize(self, event: events.Resize) -> None:
        self._apply_sidebar_auto_visibility(event.size, event.pixel_size)
        self._scroll_auto_panes()

    # ------------------------------------------------------------------ #
    # Threads (worker entry points; all network stays off the main thread)
    # ------------------------------------------------------------------ #

    def _run_thread(self, target, *args) -> None:
        """Run ``target(*args)`` on a daemon thread with a safety net.

        Any uncaught exception is surfaced as a toast instead of silently
        killing the thread, so failures are visible rather than mysterious.
        """

        def runner():
            try:
                target(*args)
            except Exception as exc:
                try:
                    self.call_from_thread(self._show_toast, "后台任务出错", str(exc))
                except Exception:
                    pass

        threading.Thread(target=runner, daemon=True).start()

    def _connect_and_load(self) -> None:
        try:
            self.ob.connect()
            info = self.ob.get_login_info()
            self.ob.self_id = info.get("user_id")
            self._connected = True
            self.call_from_thread(
                self._show_toast, "已连接", str(self.ob.self_id or "")
            )
        except Exception:
            self._connected = False
        self._load_chats_worker()

    def _load_chats_worker(self) -> None:
        chats, remarks, cache, error = chat_service.load_chats(self.ob, self.storage)
        if error:
            self.call_from_thread(self._chat_list_ctrl.show_empty_chats, error)
            return
        with self._state_lock:
            self._chats = chats
            self._friend_remarks.update(remarks)
            self._search_cache = cache
        self.call_from_thread(self._chat_list_ctrl.render_chat_list)

    def _load_messages_worker(self, pane_uid: int, chat: ChatInfo) -> None:
        messages, error = message_service.load_history(
            self.ob,
            self.storage,
            chat,
            config.HISTORY_MESSAGE_COUNT,
            config.CACHE_GROUP_MEMBERS_ON_OPEN,
        )
        self.call_from_thread(
            self._msg_ctrl.show_messages, pane_uid, chat, messages, error or ""
        )

    def _send_worker(
        self, chat: ChatInfo, text: str, reply_to: Optional[int], reply_preview: Optional[str]
    ) -> None:
        try:
            message = message_service.send(
                self.ob, chat, text, reply_to, reply_preview
            )
        except Exception as exc:
            self.call_from_thread(self._show_toast, "发送失败", str(exc))
            return

        self.storage.add_message(chat.chat_type, chat.chat_id, message)
        self.storage.update_last_activity(chat.chat_type, chat.chat_id)
        self._touch_chat(chat.chat_type, chat.chat_id, message.time)
        self.call_from_thread(self._mark_storage_dirty)
        self.call_from_thread(self._msg_ctrl.append_message_if_current, chat, message)

    # ------------------------------------------------------------------ #
    # Storage flushing (dirty-flag batching, per AGENTS.md)
    # ------------------------------------------------------------------ #

    def _mark_storage_dirty(self) -> None:
        self._storage_dirty = True

    def _flush_storage_if_dirty(self) -> None:
        if not self._storage_dirty:
            return
        self._storage_dirty = False
        try:
            self.storage.save()
        except OSError as exc:
            self._storage_dirty = True
            self._show_toast("缓存保存失败", str(exc))

    # ------------------------------------------------------------------ #
    # Toast
    # ------------------------------------------------------------------ #

    def _show_toast(self, title: str, body: str = "") -> None:
        self._toast_token += 1
        token = self._toast_token
        title = ellipsize(title, 34)
        body = ellipsize(body, 34) if body else ""
        text = title if not body else f"{title}\n{body}"
        row = self.query_one("#toast_row", Horizontal)
        toast = self.query_one("#toast", Static)
        toast.update(Text(text))
        row.add_class("visible")
        row.refresh(layout=True)
        self.set_timer(4, lambda: self._hide_toast(token))

    def _hide_toast(self, token: int) -> None:
        if token != self._toast_token:
            return
        row = self.query_one("#toast_row", Horizontal)
        self.query_one("#toast", Static).update("")
        row.remove_class("visible")
        row.refresh(layout=True)

    # ------------------------------------------------------------------ #
    # Sidebar visibility
    # ------------------------------------------------------------------ #

    def _focus_after_sidebar_hidden(self, sidebar: Vertical, button: Button) -> None:
        focused = self.focused
        if focused is None or not widget_inside(focused, sidebar):
            return
        pane = self._active_pane()
        if pane.selected_chat is not None:
            msg_input = self._msg_ctrl.message_input_or_none(pane)
            if msg_input is not None and not msg_input.disabled:
                msg_input.focus()
                return
        button.focus()

    def _set_sidebar_visible(self, visible: bool, reason: Optional[str] = None) -> None:
        try:
            sidebar = self.query_one("#sidebar", Vertical)
            button = self.query_one("#sidebar_toggle_btn", Button)
        except NoMatches:
            return

        sidebar.display = visible
        self._sidebar_state.hidden_by = None if visible else reason
        button.label = "<" if visible else ">"
        button.tooltip = "隐藏群组列表" if visible else "显示群组列表"
        if not visible:
            self._focus_after_sidebar_hidden(sidebar, button)

    def _apply_sidebar_auto_visibility(self, size=None, pixel_size=None) -> None:
        if size is None and pixel_size is None:
            size = self.size
        narrow = is_sidebar_narrow(
            size,
            pixel_size,
            len(self._panes),
            self._split_layout_horizontal,
        )
        if narrow:
            self._sidebar_state.auto_paused = False
            if has_empty_pane(self._panes):
                self._set_sidebar_visible(True)
            else:
                self._set_sidebar_visible(False, "auto")
            return

        if self._sidebar_state.auto_paused:
            return
        if self._sidebar_state.hidden_by == "auto":
            self._set_sidebar_visible(True)

    def _show_sidebar_for_narrow_navigation(self) -> None:
        if not is_sidebar_narrow(
            self.size,
            None,
            len(self._panes),
            self._split_layout_horizontal,
        ):
            return
        self._sidebar_state.auto_paused = False
        self._set_sidebar_visible(True)

    def _hide_sidebar_after_narrow_chat_selection(self) -> None:
        if not is_sidebar_narrow(
            self.size,
            None,
            len(self._panes),
            self._split_layout_horizontal,
        ):
            return
        self._sidebar_state.auto_paused = False
        if has_empty_pane(self._panes):
            self._set_sidebar_visible(True)
        else:
            self._set_sidebar_visible(False, "auto")

    # ------------------------------------------------------------------ #
    # Mouse handling (right-click copy / paste / pin)
    # ------------------------------------------------------------------ #

    @on(events.MouseDown)
    def _on_app_mouse_down(self, event: events.MouseDown) -> None:
        pane = self._pane_from_mouse_event(event)
        if pane is not None:
            self._navigation.layer = "pane"
            self._activate_pane(pane, focus_input=pane.selected_chat is not None)
        else:
            self._navigation.layer = "top"
            self._hide_all_message_inputs()
        if event.button == RIGHT_MOUSE_BUTTON:
            if self._mouse_event_in_chat_list(event):
                self._right_click_selected_text = ""
                return
            self._right_click_selected_text = self.screen.get_selected_text() or ""

    @on(events.Focus)
    def _on_app_focus(self, _: events.Focus) -> None:
        self.call_after_refresh(self._sync_message_input_focus)

    @on(events.Blur)
    def _on_app_blur(self, _: events.Blur) -> None:
        self.call_after_refresh(self._sync_message_input_focus)

    @on(events.AppBlur)
    def _on_app_blurred(self, _: events.AppBlur) -> None:
        self._hide_all_message_inputs()

    @on(events.AppFocus)
    def _on_app_focused(self, _: events.AppFocus) -> None:
        self.call_after_refresh(self._sync_message_input_focus)

    @on(events.Key)
    def _on_app_key(self, event: events.Key) -> None:
        if event.character is None or not event.is_printable:
            return
        if self._focused_input() is not None:
            return
        pane: Optional[ChatPaneState] = None
        if self._navigation.layer == "pane":
            pane = self._active_pane()
        elif self._navigation.layer == "top" and self._navigation.top_target_pane_uid is not None:
            pane = self._pane_by_uid(self._navigation.top_target_pane_uid)
        if pane is None or pane.selected_chat is None:
            return
        event.prevent_default()
        event.stop()
        self._enter_pane_layer(pane)
        self._msg_ctrl.start_message_input(pane, event.character)

    def _sync_message_input_focus(self) -> None:
        if self._pending_pane_focus_uid is not None:
            target = self._pane_by_uid(self._pending_pane_focus_uid)
            if target is not None and target.selected_chat is not None:
                self.call_after_refresh(
                    lambda target=target: self._enter_pane_layer(target)
                )
                return
        focused = self.screen.focused
        if focused is None:
            self._hide_all_message_inputs()
            self._refresh_pane_active_classes()
            return
        if self._chat_list_ctrl.search_has_focus():
            self._navigation.layer = "search"
            self._hide_all_message_inputs()
            self._refresh_pane_active_classes()
            return
        if isinstance(focused, ListView) and focused.id == "chat_list":
            self._navigation.layer = "chat_list"
            self._hide_all_message_inputs()
            self._refresh_pane_active_classes()
            return
        pane = self._pane_from_widget(focused)
        if pane is None:
            self._hide_all_message_inputs()
            self._refresh_pane_active_classes()
            return
        self._navigation.layer = "pane"
        self._set_input_owner_pane(pane, scroll_if_auto=True)

    @on(events.MouseUp)
    def _on_app_mouse_up(self, event: events.MouseUp) -> None:
        if event.button == LEFT_MOUSE_BUTTON and self._mouse_event_in_chat_list(event):
            chat = self._chat_from_mouse_event(event)
            if chat is not None:
                event.stop()
                self._open_chat_from_list_selection(chat, focus_pane=True)
            return
        if event.button != RIGHT_MOUSE_BUTTON:
            return
        event.stop()
        if self._mouse_event_in_chat_list(event):
            chat = self._chat_from_mouse_event(event)
            if chat is not None:
                self._toggle_chat_pin(chat)
            self._right_click_selected_text = ""
            return
        selected_text = (
            self._right_click_selected_text or self.screen.get_selected_text() or ""
        )
        self._right_click_selected_text = ""
        if selected_text:
            self._copy_text_to_clipboard(selected_text)
            self.screen.clear_selection()
            return
        self._paste_clipboard_to_input()

    def _mouse_event_in_chat_list(self, event: events.MouseEvent) -> bool:
        try:
            widget, _ = self.screen.get_widget_at(event.screen_x, event.screen_y)
            list_view = self.query_one("#chat_list", ListView)
        except Exception:
            return False

        node = widget
        while node is not None:
            if node is list_view:
                return True
            node = getattr(node, "parent", None)
        return False

    def _chat_from_mouse_event(self, event: events.MouseEvent) -> Optional[ChatInfo]:
        try:
            widget, _ = self.screen.get_widget_at(event.screen_x, event.screen_y)
            list_view = self.query_one("#chat_list", ListView)
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

        with self._state_lock:
            rendered = list(self._rendered_chats)
        if index < 0 or index >= len(rendered):
            return None
        return rendered[index]

    def _toggle_chat_pin(self, chat: ChatInfo) -> None:
        pinned = self.storage.toggle_chat_pinned(
            chat.chat_type, chat.chat_id, save=False
        )
        self._mark_storage_dirty()
        self._chat_list_ctrl.render_chat_list()
        self._chat_list_ctrl.schedule_chat_list_selection_sync(scroll=True)
        self._show_toast("已置顶" if pinned else "已取消置顶", chat.name)

    def _copy_text_to_clipboard(self, text: str) -> None:
        self.copy_to_clipboard(text)
        set_system_clipboard(text)

    def _paste_clipboard_to_input(self) -> None:
        text = get_system_clipboard() or self.clipboard
        if not text:
            self._show_toast("剪贴板为空")
            return
        target = self._paste_target_input()
        if target is None:
            self._show_toast("没有可粘贴的输入框")
            return
        line = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")[0]
        if not line:
            return
        target.focus()
        selection = target.selection
        if selection.is_empty:
            target.insert_text_at_cursor(line)
        else:
            target.replace(line, *selection)

    def _paste_target_input(self) -> Optional[Input]:
        focused = self.screen.focused
        if isinstance(focused, Input) and not focused.disabled:
            return focused
        pane = self._active_pane()
        message_input = self._msg_ctrl.message_input_or_none(pane)
        if message_input is not None and not message_input.disabled:
            if self._msg_ctrl.pane_input_visible(pane):
                return message_input
        search = self.query_one("#search", Input)
        return search if not search.disabled else None

    # ------------------------------------------------------------------ #
    # Button handlers
    # ------------------------------------------------------------------ #

    @on(Button.Pressed, "#sidebar_toggle_btn")
    def _on_sidebar_toggle(self) -> None:
        if self._sidebar_state.hidden_by is None:
            narrow = is_sidebar_narrow(
                self.size,
                None,
                len(self._panes),
                self._split_layout_horizontal,
            )
            self._sidebar_state.auto_paused = not narrow
            reason = (
                "manual"
                if len(self._panes) > 1
                else ("auto" if narrow else "manual")
            )
            self._set_sidebar_visible(False, reason)
            return

        self._sidebar_state.auto_paused = False
        self._set_sidebar_visible(True)

    @on(Button.Pressed, "#header_menu_btn")
    async def _on_header_menu(self) -> None:
        if self.ENABLE_COMMAND_PALETTE:
            await self.run_action("app.command_palette")

    @on(Button.Pressed, "#split_add_btn")
    def _on_split_add(self) -> None:
        self.action_add_pane()

    @on(Button.Pressed, "#split_layout_btn")
    def _on_split_layout(self) -> None:
        self.action_toggle_split_layout()

    def _add_pane(self) -> None:
        self._pane_ctrl.add_pane()

    def _scroll_auto_panes(self) -> None:
        self._pane_ctrl.scroll_auto_panes()

    def _toggle_split_layout(self) -> None:
        self._pane_ctrl.toggle_split_layout()

    def _close_pane(self, pane: ChatPaneState) -> None:
        self._pane_ctrl.close_pane(pane)

    @on(Button.Pressed, ".pane_close_btn")
    def _on_split_close(self, event: Button.Pressed) -> None:
        pane = self._pane_from_widget(event.button)
        if pane is None:
            return
        event.stop()
        self._close_pane(pane)

    @on(Button.Pressed, ".scroll_bottom_btn")
    def _on_scroll_bottom(self, event: Button.Pressed) -> None:
        pane = self._pane_from_widget(event.button)
        if pane is None:
            return
        self._activate_pane(pane)
        pane.auto_scroll = True
        self._msg_ctrl.hide_scroll_bottom_btn(pane)
        log = self._msg_ctrl.message_log_or_none(pane)
        if log is not None:
            log.scroll_end_when_ready()

    # ------------------------------------------------------------------ #
    # Title bar
    # ------------------------------------------------------------------ #

    def _set_app_title_text(self, text: str) -> None:
        try:
            self.query_one("#app_title", Static).update(text)
        except NoMatches:
            pass

    # ------------------------------------------------------------------ #
    # Chat list rendering
    # ------------------------------------------------------------------ #

    def _open_chat_from_list_selection(
        self, chat: ChatInfo, focus_pane: bool = True
    ) -> None:
        pane = self._active_pane()
        if not same_chat(chat, pane.selected_chat):
            self._open_chat(chat, pane)
        self._chat_list_ctrl.clear_search_text()
        self._hide_sidebar_after_narrow_chat_selection()
        if focus_pane:
            self._enter_pane_layer_after_refresh(pane)

    def _open_selected_search_chat(self) -> None:
        chat = self._chat_list_ctrl.selected_search_chat()
        if chat is None:
            return
        self._open_chat_from_list_selection(chat, focus_pane=True)

    def _close_search_mode(self) -> None:
        pane = self._active_pane()
        self._cancel_preview_timer(pane)
        pane.preview_chat = None
        search = self.query_one("#search", Input)
        if search.value:
            search.clear()
            self._chat_list_ctrl.render_chat_list()
        else:
            self._chat_list_ctrl.schedule_chat_list_selection_sync(scroll=True)
        self._enter_chat_list_layer()

    @on(Input.Changed, "#search")
    def _on_search_changed(self, _: Input.Changed) -> None:
        if self._chat_list_ctrl.search_has_focus():
            self._hide_all_message_inputs()
        self._chat_list_ctrl.render_chat_list()

    @on(Input.Changed, ".msg_input")
    def _on_message_input_changed(self, event: Input.Changed) -> None:
        pane = self._pane_from_widget(event.input)
        if pane is None:
            return
        if event.input.value:
            self._input_owner_pane_uid = pane.uid
        self._msg_ctrl.refresh_message_input_visibility(pane)

    @on(Input.Submitted, "#search")
    def _on_search_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._open_selected_search_chat()

    @on(ListView.Selected, "#chat_list")
    def _on_chat_selected(self, event: ListView.Selected) -> None:
        index = event.list_view.index
        with self._state_lock:
            if (
                index is None
                or index < 0
                or index >= len(self._rendered_chats)
            ):
                return
            chat = self._rendered_chats[index]
            if chat is None:
                return
        event.stop()
        self._open_chat_from_list_selection(chat, focus_pane=True)

    # ------------------------------------------------------------------ #
    # Opening / loading a chat
    # ------------------------------------------------------------------ #

    def _open_chat(
        self, chat: ChatInfo, pane: Optional[ChatPaneState] = None
    ) -> None:
        pane = pane or self._active_pane()
        pane.selected_chat = chat
        self._activate_pane(pane)
        pane.reply_index = -1
        pane.messages = []
        pane.message_line_spans = []
        pane.auto_scroll = True
        pane.prev_scroll_y = 0
        pane.preview_chat = None
        self._chat_list_ctrl.render_chat_list()
        self._chat_list_ctrl.schedule_chat_list_selection_sync(scroll=True)
        self._update_pane_titles()
        msg_input = self._msg_ctrl.message_input_or_none(pane)
        if msg_input is not None:
            msg_input.disabled = False
            self._msg_ctrl.refresh_message_input_visibility(pane)
        log = self._msg_ctrl.message_log_or_none(pane)
        if log is not None:
            log.clear()
            log.write("[dim]正在加载聊天记录...[/]")
        self._run_thread(self._load_messages_worker, pane.uid, chat)

    def _touch_chat(self, chat_type: str, chat_id: int, timestamp: "int | float") -> None:
        with self._state_lock:
            for chat in self._chats:
                if chat.chat_type == chat_type and chat.chat_id == chat_id:
                    chat.last_time = float(timestamp or time.time())
                    break
            self._chats.sort(
                key=lambda c: chat_logic.chat_sort_key(c, self.storage)
            )

    # ------------------------------------------------------------------ #
    # Real-time event drain
    # ------------------------------------------------------------------ #

    def _drain_events(self) -> None:
        while True:
            try:
                event = self.ob.event_queue.get_nowait()
            except Exception:
                return
            self._handle_event(event)

    def _handle_event(self, event: dict) -> None:
        if event.get("post_type") != "message":
            return
        chat_type = "group" if event.get("message_type") == "group" else "private"
        chat_id = (
            event.get("group_id") if chat_type == "group" else event.get("user_id")
        )
        try:
            chat_id = int(chat_id or 0)
        except (TypeError, ValueError):
            return
        at_resolver = self._msg_ctrl._at_resolver(chat_type, chat_id)
        try:
            message = message_logic.message_from_event(event, at_resolver)
        except Exception:
            # A single malformed event must not wedge the drain loop.
            return
        if not message.chat_id:
            return
        self.storage.add_message(message.chat_type, message.chat_id, message)
        self.storage.update_last_activity(message.chat_type, message.chat_id)
        self._mark_storage_dirty()
        self._touch_chat(message.chat_type, message.chat_id, message.time)

        updated = False
        for pane in list(self._panes):
            chat = pane.selected_chat
            if not (
                chat
                and chat.chat_type == message.chat_type
                and chat.chat_id == message.chat_id
            ):
                continue
            updated = True
            pane.messages.append(message)
            log = self._msg_ctrl.message_log_or_none(pane)
            if log is None:
                continue
            line_span = self._msg_ctrl.write_message(log, message, pane)
            pane.message_line_spans.append(line_span)
            if pane.auto_scroll:
                log.scroll_end_when_ready()
        self._chat_list_ctrl.refresh_chat_list_item(message.chat_type, message.chat_id)
        if updated:
            self._msg_ctrl.update_reply_info(self._active_pane())

    # ------------------------------------------------------------------ #
    # Sending messages
    # ------------------------------------------------------------------ #

    @on(Input.Submitted, ".msg_input")
    def _on_message_submitted(self, event: Input.Submitted) -> None:
        self._msg_ctrl.submit_message_input(event.input)

    # ------------------------------------------------------------------ #
    # Actions (bound keys)
    # ------------------------------------------------------------------ #

    def action_refresh_chats(self) -> None:
        self._show_toast("正在刷新会话...")
        self._run_thread(self._load_chats_worker)

    def action_add_pane(self) -> None:
        self._add_pane()

    def action_close_current_pane(self) -> None:
        self._close_pane(self._active_pane())

    def action_toggle_split_layout(self) -> None:
        self._toggle_split_layout()

    def _navigate_chat(self, direction: int) -> None:
        pane = self._active_pane()
        with self._state_lock:
            chats = list(self._filtered_chats)
        base = pane.preview_chat or pane.selected_chat
        index = chat_logic.navigate_index(chats, base, direction)
        if index is None:
            return
        chat = chats[index]
        if pane.selected_chat is not None and same_chat(chat, pane.selected_chat):
            pane.preview_chat = None
        else:
            pane.preview_chat = chat
        with self._state_lock:
            rendered = list(self._rendered_chats)

        target_index = chat_logic.rendered_chat_index(rendered, chat)
        if target_index is None:
            self._chat_list_ctrl.render_chat_list()
            self._chat_list_ctrl.schedule_chat_list_selection_sync(scroll=True)
        else:
            self._chat_list_ctrl.schedule_chat_list_selection_sync(scroll=True)

        # Reset the deferred-commit timer.
        self._cancel_preview_timer(pane)
        if pane.preview_chat is not None:
            token = pane.preview_token
            self.set_timer(
                1.0,
                lambda uid=pane.uid, token=token: self._commit_preview_if_current(
                    uid, token
                ),
            )

    def _cancel_preview_timer(self, pane: Optional[ChatPaneState] = None) -> None:
        pane = pane or self._active_pane()
        pane.preview_token += 1

    def _commit_preview_if_current(self, pane_uid: int, token: int) -> None:
        pane = self._pane_by_uid(pane_uid)
        if pane is not None and token == pane.preview_token:
            self._commit_preview(pane)

    def _commit_preview(self, pane: Optional[ChatPaneState] = None) -> None:
        pane = pane or self._active_pane()
        self._cancel_preview_timer(pane)
        chat = pane.preview_chat
        if chat is None:
            return
        pane.preview_chat = None
        if pane.selected_chat is not None and same_chat(chat, pane.selected_chat):
            self._chat_list_ctrl.render_chat_list()
            self._chat_list_ctrl.schedule_chat_list_selection_sync(scroll=True)
            return
        self._open_chat(chat, pane)
        self._hide_sidebar_after_narrow_chat_selection()

    def action_prev_chat(self) -> None:
        self._show_sidebar_for_narrow_navigation()
        self._navigate_chat(-1)

    def action_next_chat(self) -> None:
        self._show_sidebar_for_narrow_navigation()
        self._navigate_chat(1)

    def action_toggle_focus_area(self) -> None:
        if self._navigation.layer == "top" and self._navigation.top_target_pane_uid is not None:
            self._focus_chat_list_area()
            return
        if self._navigation.layer == "pane":
            self._focus_chat_list_area()
            return
        self._focus_pane_selection_area()

    def action_nav_left(self) -> None:
        focused = self._cursor_target_input()
        if focused is not None:
            focused.action_cursor_left()
            return
        if self._navigation.layer == "top" and self._navigation.top_target_pane_uid is not None:
            self._move_pane_selection_in_direction("left")

    def action_nav_right(self) -> None:
        focused = self._cursor_target_input()
        if focused is not None:
            focused.action_cursor_right()
            return
        if self._navigation.layer == "top" and self._navigation.top_target_pane_uid is not None:
            self._move_pane_selection_in_direction("right")

    def action_nav_enter(self) -> None:
        if self._navigation.layer == "top":
            if self._navigation.top_target_pane_uid is None:
                if self._navigation.chat_list_on_search:
                    self._enter_search_layer()
                else:
                    self._open_selected_search_chat()
                return
            pane = self._pane_by_uid(self._navigation.top_target_pane_uid)
            if pane is not None:
                self._enter_pane_layer(pane)
            return
        if self._navigation.layer == "chat_list":
            if self._navigation.chat_list_on_search:
                self._enter_search_layer()
            else:
                self._open_selected_search_chat()
            return
        if self._navigation.layer == "search":
            self._open_selected_search_chat()
            return
        if self._navigation.layer == "pane":
            focused = self.screen.focused
            if isinstance(focused, Input) and focused.has_class("msg_input"):
                self._msg_ctrl.submit_message_input(focused)
                return
            self.action_focus_message()

    def action_focus_search(self) -> None:
        self._sidebar_state.auto_paused = False
        self._set_sidebar_visible(True)
        self._enter_search_layer()

    def action_focus_message(self) -> None:
        pane = self._active_pane()
        if pane.selected_chat:
            msg_input = self._msg_ctrl.message_input_or_none(pane)
            if msg_input is not None and not msg_input.disabled:
                self._set_input_owner_pane(pane)
                msg_input.focus()

    def action_reply_previous(self) -> None:
        if self._navigation.layer == "top":
            if self._navigation.top_target_pane_uid is None:
                self._chat_list_ctrl.move_chat_list_layer_selection(-1)
            else:
                self._move_pane_selection_in_direction("up")
            return
        if self._navigation.layer == "chat_list":
            self._chat_list_ctrl.move_chat_list_layer_selection(-1)
            return
        if self._navigation.layer == "search":
            self._chat_list_ctrl.move_search_selection(-1)
            return
        if self._navigation.layer != "pane":
            return
        pane = self._active_pane()
        if not pane.messages:
            return
        if pane.reply_index < 0:
            pane.reply_index = len(pane.messages) - 1
        elif pane.reply_index > 0:
            pane.reply_index -= 1
        self._msg_ctrl.render_messages(pane)
        self._msg_ctrl.scroll_to_message(pane, pane.reply_index)

    def action_reply_next(self) -> None:
        if self._navigation.layer == "top":
            if self._navigation.top_target_pane_uid is None:
                self._chat_list_ctrl.move_chat_list_layer_selection(1)
            else:
                self._move_pane_selection_in_direction("down")
            return
        if self._navigation.layer == "chat_list":
            self._chat_list_ctrl.move_chat_list_layer_selection(1)
            return
        if self._navigation.layer == "search":
            self._chat_list_ctrl.move_search_selection(1)
            return
        if self._navigation.layer != "pane":
            return
        pane = self._active_pane()
        if pane.reply_index < 0:
            return
        pane.reply_index += 1
        if pane.reply_index >= len(pane.messages):
            pane.reply_index = -1
        self._msg_ctrl.render_messages(pane)
        if pane.reply_index >= 0:
            self._msg_ctrl.scroll_to_message(pane, pane.reply_index)

    def action_clear_reply(self) -> None:
        if self._navigation.layer == "search":
            self._close_search_mode()
            return
        if self._navigation.layer == "chat_list":
            self._enter_top_layer()
            return
        if self._navigation.layer == "pane":
            pane = self._active_pane()
            if pane.preview_chat is None and pane.reply_index < 0:
                self._enter_top_layer()
                return
        elif self._navigation.layer == "top":
            self._hide_all_message_inputs()
            return
        pane = self._active_pane()
        if pane.preview_chat is not None:
            self._cancel_preview_timer(pane)
            pane.preview_chat = None
            self._chat_list_ctrl.render_chat_list()
            self._chat_list_ctrl.schedule_chat_list_selection_sync(scroll=True)
        elif pane.reply_index >= 0:
            pane.reply_index = -1
            self._msg_ctrl.render_messages(pane)
        elif pane.selected_chat:
            msg_input = self._msg_ctrl.message_input_or_none(pane)
            if msg_input is not None:
                msg_input.focus()
        else:
            self.query_one("#search", Input).focus()
