"""Single-screen Textual frontend for QQ chats.

``QQChatApp`` owns the Textual lifecycle and event bindings, and delegates
focused UI coordination to controllers. Pure logic lives in :mod:`ui.logic`;
network/parsing work stays in :mod:`ui.services`.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Optional

from rich.text import Text
from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Button, Input, ListView, Static

import config
from models import ChatInfo, MessageData
from onebot import OneBotClient
from storage import Storage
from ui.controllers.chat_list import ChatListController
from ui.controllers.messages import MessageController
from ui.controllers.mouse import MouseController
from ui.controllers.navigation import NavigationController
from ui.controllers.panes import PaneController
from ui.controllers.realtime import RealtimeController
from ui.controllers.sidebar import SidebarController
from ui.logic import chat_logic
from ui.services import chat_service, message_service
from ui.sidebar import is_sidebar_narrow
from ui.state import AppState, ChatPaneState
from ui.styles import APP_CSS

from ui.text_utils import ellipsize
from ui.widgets.chat_pane import build_pane_container


class QQChatApp(App):
    """Single-screen Textual frontend for QQ chats."""

    TITLE = "TUI-QQ"
    SUB_TITLE = "NapCat / OneBot v11"
    CSS = APP_CSS

    _TOP_TOOLTIP_BUTTON_IDS = (
        "sidebar_toggle_btn",
        "header_menu_btn",
        "split_layout_btn",
        "split_add_btn",
    )

    _STATE_COMPAT_FIELDS = {
        "_chats": "chats",
        "_filtered_chats": "filtered_chats",
        "_rendered_chats": "rendered_chats",
        "_search_cache": "search_cache",
        "_connected": "connected",
        "_toast_token": "toast_token",
        "_storage_dirty": "storage_dirty",
        "_panes": "panes",
        "_active_pane_uid": "active_pane_uid",
        "_input_owner_pane_uid": "input_owner_pane_uid",
        "_navigation": "navigation",
        "_next_pane_uid": "next_pane_uid",
        "_split_layout_horizontal": "split_layout_horizontal",
        "_pending_pane_focus_uid": "pending_pane_focus_uid",
        "_friend_remarks": "friend_remarks",
        "_right_click_selected_text": "right_click_selected_text",
        "_sidebar_state": "sidebar_state",
    }

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
        Binding("ctrl+b", "scroll_bottom", "置底", priority=True),
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
        self.state = AppState()
        self._chat_list_ctrl = ChatListController(self)
        self._msg_ctrl = MessageController(self)
        self._mouse_ctrl = MouseController(self)
        self._pane_ctrl = PaneController(self)
        self._nav_ctrl = NavigationController(self)
        self._sidebar_ctrl = SidebarController(self)
        self._realtime_ctrl = RealtimeController(self)

    def __getattr__(self, name: str):
        state_field = self._STATE_COMPAT_FIELDS.get(name)
        if state_field is not None and "state" in self.__dict__:
            return getattr(self.state, state_field)
        raise AttributeError(name)

    def __setattr__(self, name: str, value) -> None:
        state_field = self._STATE_COMPAT_FIELDS.get(name)
        if state_field is not None and "state" in self.__dict__:
            setattr(self.state, state_field, value)
            return
        super().__setattr__(name, value)

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
        self._nav_ctrl.enter_top_layer()

    def _enter_chat_list_layer(self) -> None:
        self._nav_ctrl.enter_chat_list_layer()

    def _enter_search_layer(self) -> None:
        self._nav_ctrl.enter_search_layer()

    def _enter_pane_layer(
        self, pane: Optional[ChatPaneState] = None, focus_input: bool = False
    ) -> None:
        self._nav_ctrl.enter_pane_layer(pane, focus_input)

    def _set_top_target_index(self, index: int) -> None:
        self._nav_ctrl.set_top_target_index(index)

    def _focus_chat_list_area(self) -> None:
        self._nav_ctrl.focus_chat_list_area()

    def _focused_input(self) -> Optional[Input]:
        return self._nav_ctrl.focused_input()

    def _activate_pane(
        self, pane: Optional[ChatPaneState], focus_input: bool = False
    ) -> None:
        self._nav_ctrl.activate_pane(pane, focus_input)

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
                        self.state.panes[0], self.state.navigation.layer, self.state.active_pane_uid,
                        self.state.navigation.top_target_pane_uid, self._msg_ctrl.pane_input_visible(self.state.panes[0])
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
        self.set_interval(0.1, self._realtime_ctrl.drain_events)
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
            self.state.connected = True
            self.call_from_thread(
                self._show_toast, "已连接", str(self.ob.self_id or "")
            )
        except Exception:
            self.state.connected = False
        self._load_chats_worker()

    def _load_chats_worker(self) -> None:
        chats, remarks, cache, error = chat_service.load_chats(self.ob, self.storage)
        if error:
            self.call_from_thread(self._chat_list_ctrl.show_empty_chats, error)
            return
        with self._state_lock:
            self.state.chats = chats
            self.state.friend_remarks.update(remarks)
            self.state.search_cache = cache
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
        self.state.storage_dirty = True

    def _flush_storage_if_dirty(self) -> None:
        if not self.state.storage_dirty:
            return
        self.state.storage_dirty = False
        try:
            self.storage.save()
        except OSError as exc:
            self.state.storage_dirty = True
            self._show_toast("缓存保存失败", str(exc))

    # ------------------------------------------------------------------ #
    # Toast
    # ------------------------------------------------------------------ #

    def _show_toast(self, title: str, body: str = "") -> None:
        self.state.toast_token += 1
        token = self.state.toast_token
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
        if token != self.state.toast_token:
            return
        row = self.query_one("#toast_row", Horizontal)
        self.query_one("#toast", Static).update("")
        row.remove_class("visible")
        row.refresh(layout=True)

    def _reset_top_button_tooltips(self) -> None:
        buttons: list[tuple[Button, object]] = []
        for button_id in self._TOP_TOOLTIP_BUTTON_IDS:
            try:
                button = self.query_one(f"#{button_id}", Button)
            except NoMatches:
                continue
            tooltip = button.tooltip
            if tooltip is None:
                continue
            button.tooltip = None
            buttons.append((button, tooltip))
        if not buttons:
            return

        def restore() -> None:
            for button, tooltip in buttons:
                if button.is_attached:
                    button.tooltip = tooltip

        self.call_after_refresh(restore)
        self.set_timer(0.05, restore)

    # ------------------------------------------------------------------ #
    # Sidebar visibility (delegated to SidebarController)
    # ------------------------------------------------------------------ #

    def _set_sidebar_visible(self, visible: bool, reason: Optional[str] = None) -> None:
        self._sidebar_ctrl.set_sidebar_visible(visible, reason)

    def _apply_sidebar_auto_visibility(self, size=None, pixel_size=None) -> None:
        self._sidebar_ctrl.apply_sidebar_auto_visibility(size, pixel_size)

    # ------------------------------------------------------------------ #
    # Mouse handling (delegated to MouseController)
    # ------------------------------------------------------------------ #

    @on(events.MouseDown)
    def _on_app_mouse_down(self, event: events.MouseDown) -> None:
        self._mouse_ctrl.handle_mouse_down(event)

    @on(events.MouseUp)
    def _on_app_mouse_up(self, event: events.MouseUp) -> None:
        self._mouse_ctrl.handle_mouse_up(event)

    @on(events.Focus)
    def _on_app_focus(self, _: events.Focus) -> None:
        self.call_after_refresh(self._sync_message_input_focus)

    @on(events.Blur)
    def _on_app_blur(self, _: events.Blur) -> None:
        self.call_after_refresh(self._sync_message_input_focus)

    @on(events.AppBlur)
    def _on_app_blurred(self, _: events.AppBlur) -> None:
        self._hide_all_message_inputs()
        self._reset_top_button_tooltips()

    @on(events.AppFocus)
    def _on_app_focused(self, _: events.AppFocus) -> None:
        self.call_after_refresh(self._sync_message_input_focus)

    @on(events.Leave)
    def _on_app_leave(self, event: events.Leave) -> None:
        node_id = getattr(getattr(event, "node", None), "id", None)
        if node_id == "top_bar" or node_id in self._TOP_TOOLTIP_BUTTON_IDS:
            self._reset_top_button_tooltips()

    @on(events.Key)
    def _on_app_key(self, event: events.Key) -> None:
        if event.character is None or not event.is_printable:
            return
        if self._focused_input() is not None:
            return
        pane: Optional[ChatPaneState] = None
        if self.state.navigation.layer == "pane":
            pane = self._active_pane()
        elif self.state.navigation.layer == "top" and self.state.navigation.top_target_pane_uid is not None:
            pane = self._pane_by_uid(self.state.navigation.top_target_pane_uid)
        if pane is None or pane.selected_chat is None:
            return
        event.prevent_default()
        event.stop()
        self._enter_pane_layer(pane, focus_input=True)
        self._msg_ctrl.start_message_input(pane, event.character)

    def _sync_message_input_focus(self) -> None:
        self._nav_ctrl.sync_message_input_focus()

    # ------------------------------------------------------------------ #
    # Button handlers
    # ------------------------------------------------------------------ #

    @on(Button.Pressed, "#sidebar_toggle_btn")
    def _on_sidebar_toggle(self) -> None:
        if self.state.sidebar_state.hidden_by is None:
            narrow = is_sidebar_narrow(
                self.size,
                None,
                len(self.state.panes),
                self.state.split_layout_horizontal,
            )
            self.state.sidebar_state.auto_paused = not narrow
            reason = (
                "manual"
                if len(self.state.panes) > 1
                else ("auto" if narrow else "manual")
            )
            self._set_sidebar_visible(False, reason)
            return

        self.state.sidebar_state.auto_paused = False
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
        self._nav_ctrl.open_chat_from_list_selection(chat, focus_pane)

    def _open_selected_search_chat(self) -> None:
        self._nav_ctrl.open_selected_search_chat()

    def _close_search_mode(self) -> None:
        self._nav_ctrl.close_search_mode()

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
            self.state.input_owner_pane_uid = pane.uid
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
                or index >= len(self.state.rendered_chats)
            ):
                return
            chat = self.state.rendered_chats[index]
            if chat is None:
                return
        event.stop()
        self._nav_ctrl.open_chat_from_list_selection(chat, focus_pane=True)

    # ------------------------------------------------------------------ #
    # Opening / loading a chat
    # ------------------------------------------------------------------ #

    def _open_chat(
        self, chat: ChatInfo, pane: Optional[ChatPaneState] = None
    ) -> None:
        pane = pane or self._active_pane()
        self.state.remove_pending_chat(
            self.storage.chat_key(chat.chat_type, chat.chat_id)
        )
        pane.selected_chat = chat
        self._activate_pane(pane)
        pane.reply_index = -1
        pane.message_action_index = 0
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
            for chat in self.state.chats:
                if chat.chat_type == chat_type and chat.chat_id == chat_id:
                    chat.last_time = float(timestamp or time.time())
                    break
            self.state.chats.sort(
                key=lambda c: chat_logic.chat_sort_key(c, self.storage)
            )

    # ------------------------------------------------------------------ #
    # Sending messages
    # ------------------------------------------------------------------ #

    @on(Input.Submitted, ".msg_input")
    def _on_message_submitted(self, event: Input.Submitted) -> None:
        self._msg_ctrl.submit_message_input(event.input)

    # ------------------------------------------------------------------ #
    # Actions (bound keys) - thin proxies to NavigationController
    # ------------------------------------------------------------------ #

    def action_refresh_chats(self) -> None:
        self._nav_ctrl.action_refresh_chats()

    def action_add_pane(self) -> None:
        self._nav_ctrl.action_add_pane()

    def action_close_current_pane(self) -> None:
        self._nav_ctrl.action_close_current_pane()

    def action_toggle_split_layout(self) -> None:
        self._nav_ctrl.action_toggle_split_layout()

    def action_scroll_bottom(self) -> None:
        self._nav_ctrl.action_scroll_bottom()

    def action_prev_chat(self) -> None:
        self._nav_ctrl.action_prev_chat()

    def action_next_chat(self) -> None:
        self._nav_ctrl.action_next_chat()

    def action_toggle_focus_area(self) -> None:
        self._nav_ctrl.action_toggle_focus_area()

    def action_nav_left(self) -> None:
        self._nav_ctrl.action_nav_left()

    def action_nav_right(self) -> None:
        self._nav_ctrl.action_nav_right()

    def action_nav_enter(self) -> None:
        self._nav_ctrl.action_nav_enter()

    def action_focus_search(self) -> None:
        self._nav_ctrl.action_focus_search()

    def action_focus_message(self) -> None:
        self._nav_ctrl.action_focus_message()

    def action_reply_previous(self) -> None:
        self._nav_ctrl.action_reply_previous()

    def action_reply_next(self) -> None:
        self._nav_ctrl.action_reply_next()

    def action_clear_reply(self) -> None:
        self._nav_ctrl.action_clear_reply()
