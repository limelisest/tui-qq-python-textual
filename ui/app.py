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
from dataclasses import dataclass, field
from typing import Callable, Optional

from rich.markup import escape as rich_escape
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
from ui.logic import chat_logic, message_logic
from ui.logic.message_logic import AtResolver
from ui.services import chat_service, message_service
from ui.styles import APP_CSS
from ui.theme import (
    CHAT_LIST_TEXT_WIDTH,
    RIGHT_MOUSE_BUTTON,
    ROLE_STYLES,
    SIDEBAR_AUTO_HIDE_COLUMNS,
    SIDEBAR_AUTO_HIDE_FOUR_PANE_COLUMNS,
    SIDEBAR_AUTO_HIDE_FOUR_PANE_PIXELS,
    SIDEBAR_AUTO_HIDE_PIXELS,
)
from ui.text_utils import ellipsize
from ui.widgets import MessageLog


MAX_SPLIT_PANES = 4
LEFT_MOUSE_BUTTON = 1


@dataclass
class ChatPaneState:
    """State for one chat split pane."""

    uid: int
    selected_chat: Optional[ChatInfo] = None
    messages: list[MessageData] = field(default_factory=list)
    message_line_spans: list[tuple[int, int]] = field(default_factory=list)
    reply_index: int = -1
    auto_scroll: bool = True
    prev_scroll_y: int = 0
    preview_chat: Optional[ChatInfo] = None
    preview_token: int = 0


class QQChatApp(App):
    """Single-screen Textual frontend for QQ chats."""

    TITLE = "TUI-QQ"
    SUB_TITLE = "NapCat / OneBot v11"
    CSS = APP_CSS

    BINDINGS = [
        Binding("ctrl+r", "refresh_chats", "刷新"),
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
        self._nav_layer = "top"
        self._top_target_pane_uid: Optional[int] = None
        self._chat_list_on_search = False
        self._next_pane_uid = 2
        self._split_layout_horizontal = False
        self._pending_pane_focus_uid: Optional[int] = None
        self._friend_remarks: dict[int, str] = {}
        self._right_click_selected_text = ""
        self._sidebar_hidden_by: Optional[str] = None
        self._sidebar_auto_paused = False
        self._sidebar_tab_restore_reason: Optional[str] = None
        self._sidebar_tab_restore_auto_paused = False

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
    # Split pane helpers
    # ------------------------------------------------------------------ #

    def _active_pane(self) -> ChatPaneState:
        pane = self._pane_by_uid(self._active_pane_uid)
        if pane is not None:
            return pane
        self._active_pane_uid = self._panes[0].uid
        return self._panes[0]

    def _pane_by_uid(self, uid: int) -> Optional[ChatPaneState]:
        return next((pane for pane in self._panes if pane.uid == uid), None)

    @staticmethod
    def _same_chat(left: Optional[ChatInfo], right: Optional[ChatInfo]) -> bool:
        return (
            left is not None
            and right is not None
            and left.chat_type == right.chat_type
            and left.chat_id == right.chat_id
        )

    def _pane_index(self, pane: ChatPaneState) -> int:
        try:
            return self._panes.index(pane) + 1
        except ValueError:
            return 1

    @staticmethod
    def _pane_dom_id(pane: ChatPaneState, name: str) -> str:
        return f"pane_{pane.uid}_{name}"

    def _pane_selector(self, pane: ChatPaneState, name: str) -> str:
        return f"#{self._pane_dom_id(pane, name)}"

    def _pane_widget(self, pane: ChatPaneState, name: str, widget_type):
        return self.query_one(self._pane_selector(pane, name), widget_type)

    def _pane_from_widget(self, widget) -> Optional[ChatPaneState]:
        node = widget
        while node is not None:
            widget_id = getattr(node, "id", "") or ""
            if widget_id.startswith("chat_pane_"):
                try:
                    uid = int(widget_id.removeprefix("chat_pane_"))
                except ValueError:
                    return None
                return self._pane_by_uid(uid)
            node = getattr(node, "parent", None)
        return None

    def _pane_from_mouse_event(self, event: events.MouseEvent) -> Optional[ChatPaneState]:
        try:
            widget, _ = self.screen.get_widget_at(event.screen_x, event.screen_y)
        except Exception:
            return None
        return self._pane_from_widget(widget)

    def _pane_title_text(self, pane: ChatPaneState) -> str:
        if pane.selected_chat is None:
            return "未选择会话"
        return pane.selected_chat.name

    def _pane_input_visible(self, pane: ChatPaneState) -> bool:
        msg_input = self._message_input_or_none(pane)
        return (
            self._input_owner_pane_uid == pane.uid
            and pane.selected_chat is not None
            and msg_input is not None
        )

    def _set_input_owner_pane(
        self, pane: Optional[ChatPaneState], scroll_if_auto: bool = True
    ) -> None:
        old_uid = self._input_owner_pane_uid
        self._input_owner_pane_uid = pane.uid if pane is not None else None
        self._refresh_pane_active_classes()
        if (
            pane is not None
            and old_uid != pane.uid
            and scroll_if_auto
            and pane.auto_scroll
        ):
            self.call_after_refresh(lambda uid=pane.uid: self._force_scroll_end(uid))
            self.set_timer(0.02, lambda uid=pane.uid: self._force_scroll_end(uid))

    def _hide_all_message_inputs(self) -> None:
        if self._input_owner_pane_uid is None:
            return
        self._set_input_owner_pane(None, scroll_if_auto=False)

    def _refresh_message_input_visibility(
        self, pane: Optional[ChatPaneState] = None
    ) -> None:
        panes = [pane] if pane is not None else list(self._panes)
        for target in panes:
            try:
                input_row = self._pane_widget(target, "input_row", Horizontal)
            except NoMatches:
                continue
            input_row.display = self._pane_input_visible(target)

    def _start_message_input(self, pane: ChatPaneState, text: str) -> None:
        msg_input = self._message_input_or_none(pane)
        if msg_input is None or msg_input.disabled:
            return
        msg_input.cursor_position = len(msg_input.value)
        msg_input.insert_text_at_cursor(text)
        self._input_owner_pane_uid = pane.uid
        self._refresh_message_input_visibility(pane)
        msg_input.focus()

    def _set_search_nav_selected(self, selected: bool) -> None:
        try:
            search = self.query_one("#search", Input)
        except NoMatches:
            return
        if selected:
            search.add_class("nav_selected")
        else:
            search.remove_class("nav_selected")

    def _enter_top_layer(self) -> None:
        self._nav_layer = "top"
        self._hide_all_message_inputs()
        self._set_search_nav_selected(False)
        self._refresh_pane_active_classes()

    def _enter_chat_list_layer(self) -> None:
        self._nav_layer = "chat_list"
        self._hide_all_message_inputs()
        self._chat_list_on_search = False
        self._set_search_nav_selected(False)
        try:
            self.query_one("#sidebar", Vertical).remove_class("top_selected")
        except NoMatches:
            pass
        self._refresh_pane_active_classes()
        self._schedule_chat_list_selection_sync(scroll=True)
        try:
            self.query_one("#chat_list", ListView).focus()
        except NoMatches:
            pass

    def _enter_search_layer(self) -> None:
        self._nav_layer = "search"
        self._hide_all_message_inputs()
        self._chat_list_on_search = True
        self._set_search_nav_selected(False)
        try:
            self.query_one("#sidebar", Vertical).remove_class("top_selected")
        except NoMatches:
            pass
        self._refresh_pane_active_classes()
        self.query_one("#search", Input).focus()

    def _enter_pane_layer(self, pane: Optional[ChatPaneState] = None) -> None:
        pane = pane or self._active_pane()
        self._nav_layer = "pane"
        self._top_target_pane_uid = pane.uid
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
        if self._top_target_pane_uid is None:
            return 0
        for index, pane in enumerate(self._panes, start=1):
            if pane.uid == self._top_target_pane_uid:
                return index
        return 0

    def _set_top_target_index(self, index: int) -> None:
        count = len(self._panes) + 1
        index %= count
        self._nav_layer = "top"
        self._hide_all_message_inputs()
        self._set_search_nav_selected(False)
        try:
            sidebar = self.query_one("#sidebar", Vertical)
        except NoMatches:
            sidebar = None
        if index == 0:
            self._top_target_pane_uid = None
            if sidebar is not None:
                sidebar.add_class("top_selected")
            self._refresh_pane_active_classes()
            return
        if sidebar is not None:
            sidebar.remove_class("top_selected")
        pane = self._panes[index - 1]
        self._top_target_pane_uid = pane.uid
        self._active_pane_uid = pane.uid
        self._refresh_pane_active_classes()
        self._schedule_chat_list_selection_sync(scroll=True)

    def _move_top_target(self, direction: int) -> None:
        self._set_top_target_index(self._top_target_index() + direction)

    def _move_pane_selection_in_direction(self, direction: str) -> bool:
        if len(self._panes) <= 1:
            return False
        current = self._pane_by_uid(self._top_target_pane_uid or self._active_pane_uid)
        try:
            index = self._panes.index(current) if current is not None else 0
        except ValueError:
            index = 0

        if len(self._panes) == 4:
            row, col = divmod(index, 2)
            if direction == "left":
                col = (col - 1) % 2
            elif direction == "right":
                col = (col + 1) % 2
            elif direction == "up":
                row = (row - 1) % 2
            elif direction == "down":
                row = (row + 1) % 2
            else:
                return False
            self._set_top_target_index(row * 2 + col + 1)
            return True

        if self._split_layout_horizontal:
            if direction not in ("left", "right"):
                return False
            delta = -1 if direction == "left" else 1
        else:
            if direction not in ("up", "down"):
                return False
            delta = -1 if direction == "up" else 1
        pane = self._panes[(index + delta) % len(self._panes)]
        self._set_top_target_index(self._panes.index(pane) + 1)
        return True

    def _focus_chat_list_area(self) -> None:
        if self._sidebar_hidden_by is not None:
            self._sidebar_tab_restore_reason = self._sidebar_hidden_by
            self._sidebar_tab_restore_auto_paused = self._sidebar_auto_paused
        else:
            self._sidebar_tab_restore_reason = None
        self._sidebar_auto_paused = False
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
        pane = self._pane_by_uid(self._top_target_pane_uid or self._active_pane_uid)
        if pane is None:
            pane = self._active_pane()
        self._set_top_target_index(self._panes.index(pane) + 1)
        self.screen.set_focus(None)
        if self._sidebar_tab_restore_reason is not None:
            reason = self._sidebar_tab_restore_reason
            auto_paused = self._sidebar_tab_restore_auto_paused
            self._sidebar_tab_restore_reason = None
            self._sidebar_tab_restore_auto_paused = False
            self._sidebar_auto_paused = auto_paused
            self._set_sidebar_visible(False, reason)

    def _pane_has_active_border(self, pane: ChatPaneState) -> bool:
        if self._nav_layer == "pane":
            return pane.uid == self._active_pane_uid
        return self._nav_layer == "top" and pane.uid == self._top_target_pane_uid

    def _focused_input(self) -> Optional[Input]:
        focused = self.screen.focused
        return focused if isinstance(focused, Input) else None

    def _cursor_target_input(self) -> Optional[Input]:
        focused = self._focused_input()
        if focused is not None:
            return focused
        pane = self._pane_by_uid(self._input_owner_pane_uid or 0)
        if pane is None or not self._pane_input_visible(pane):
            return None
        return self._message_input_or_none(pane)

    def _build_pane_container(self, pane: ChatPaneState) -> Vertical:
        title = Static(
            self._pane_title_text(pane),
            id=self._pane_dom_id(pane, "title"),
            classes="pane_title",
        )
        close_btn = Button(
            "-",
            id=self._pane_dom_id(pane, "close_btn"),
            classes="pane_close_btn",
            compact=True,
        )
        msg_log = MessageLog(
            id=self._pane_dom_id(pane, "msg_log"),
            classes="msg_log",
            max_lines=5000,
        )
        msg_input = Input(
            placeholder="选择会话后输入消息，Enter 发送",
            id=self._pane_dom_id(pane, "msg_input"),
            classes="msg_input",
        )
        msg_input.disabled = pane.selected_chat is None
        scroll_btn = Button(
            "↓",
            id=self._pane_dom_id(pane, "scroll_bottom_btn"),
            classes="scroll_bottom_btn",
            variant="default",
        )
        scroll_btn.visible = not pane.auto_scroll
        input_row = Horizontal(
            msg_input,
            id=self._pane_dom_id(pane, "input_row"),
            classes="input_row",
        )
        input_row.display = self._pane_input_visible(pane)
        pane_classes = "chat_pane"
        if self._pane_has_active_border(pane):
            pane_classes += " active_pane"
        return Vertical(
            Horizontal(
                Static("", classes="pane_title_pad"),
                title,
                scroll_btn,
                close_btn,
                id=self._pane_dom_id(pane, "header"),
                classes="pane_header",
            ),
            Vertical(
                msg_log,
                id=self._pane_dom_id(pane, "chat_area"),
                classes="chat_area",
            ),
            Static(
                "",
                id=self._pane_dom_id(pane, "reply_info"),
                classes="reply_info",
            ),
            input_row,
            id=f"chat_pane_{pane.uid}",
            classes=pane_classes,
        )

    def _activate_pane(
        self, pane: Optional[ChatPaneState], focus_input: bool = False
    ) -> None:
        if pane is None:
            return
        changed = pane.uid != self._active_pane_uid
        if changed:
            self._active_pane_uid = pane.uid
            self._top_target_pane_uid = pane.uid
            self._refresh_pane_active_classes()
            self._set_app_title_text("")
            self._schedule_chat_list_selection_sync(scroll=True)
            self._apply_sidebar_auto_visibility()
        self._set_input_owner_pane(pane)
        if focus_input and pane.selected_chat is not None:
            msg_input = self._message_input_or_none(pane)
            if msg_input is not None and not msg_input.disabled:
                msg_input.focus()

    def _refresh_pane_active_classes(self) -> None:
        for pane in self._panes:
            try:
                widget = self.query_one(f"#chat_pane_{pane.uid}", Vertical)
            except NoMatches:
                continue
            if self._pane_has_active_border(pane):
                widget.add_class("active_pane")
            else:
                widget.remove_class("active_pane")
            try:
                input_row = self._pane_widget(pane, "input_row", Horizontal)
                input_row.display = self._pane_input_visible(pane)
            except NoMatches:
                pass

    def _update_pane_titles(self) -> None:
        for pane in self._panes:
            try:
                self._pane_widget(pane, "title", Static).update(
                    self._pane_title_text(pane)
                )
            except NoMatches:
                pass
        self._set_app_title_text("")

    def _update_pane_grid_class(self) -> None:
        try:
            grid = self.query_one("#pane_grid", Container)
        except NoMatches:
            return
        for count in range(1, MAX_SPLIT_PANES + 1):
            grid.remove_class(f"pane_count_{count}")
        grid.remove_class("pane_layout_horizontal")
        grid.add_class(f"pane_count_{len(self._panes)}")
        if self._split_layout_horizontal and len(self._panes) in (2, 3):
            grid.add_class("pane_layout_horizontal")

    def _update_split_buttons(self) -> None:
        try:
            add_btn = self.query_one("#split_add_btn", Button)
        except NoMatches:
            return
        add_btn.disabled = len(self._panes) >= MAX_SPLIT_PANES
        add_btn.tooltip = "新增分屏" if not add_btn.disabled else "最多 4 个分屏"
        try:
            layout_btn = self.query_one("#split_layout_btn", Button)
            layout_btn.tooltip = (
                "纵向分屏布局"
                if self._split_layout_horizontal
                else "横向分屏布局"
            )
        except NoMatches:
            pass
        close_disabled = len(self._panes) <= 1
        for pane in self._panes:
            try:
                close_btn = self._pane_widget(pane, "close_btn", Button)
            except NoMatches:
                continue
            close_btn.disabled = close_disabled
            close_btn.tooltip = (
                "关闭当前分屏" if not close_disabled else "至少保留 1 个分屏"
            )

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
                    yield self._build_pane_container(self._panes[0])
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
        self.set_interval(0.1, self._check_scroll)
        self.set_interval(2.0, self._flush_storage_if_dirty)
        self._run_thread(self._connect_and_load)

    def on_unmount(self) -> None:
        self.storage.save()
        self.ob.disconnect()

    def on_resize(self, event: events.Resize) -> None:
        self._apply_sidebar_auto_visibility(event.size, event.pixel_size)

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
            self.call_from_thread(self._show_empty_chats, error)
            return
        with self._state_lock:
            self._chats = chats
            self._friend_remarks.update(remarks)
            self._search_cache = cache
        self.call_from_thread(self._render_chat_list)

    def _load_messages_worker(self, pane_uid: int, chat: ChatInfo) -> None:
        messages, error = message_service.load_history(
            self.ob,
            self.storage,
            chat,
            config.HISTORY_MESSAGE_COUNT,
            config.CACHE_GROUP_MEMBERS_ON_OPEN,
        )
        self.call_from_thread(
            self._show_messages, pane_uid, chat, messages, error or ""
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
        self.call_from_thread(self._append_message_if_current, chat, message)

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

    def _sidebar_auto_hide_pixel_threshold(self) -> int:
        if len(self._panes) == MAX_SPLIT_PANES:
            return SIDEBAR_AUTO_HIDE_FOUR_PANE_PIXELS
        return SIDEBAR_AUTO_HIDE_PIXELS

    def _sidebar_auto_hide_column_threshold(self) -> int:
        if len(self._panes) == MAX_SPLIT_PANES:
            return SIDEBAR_AUTO_HIDE_FOUR_PANE_COLUMNS
        return SIDEBAR_AUTO_HIDE_COLUMNS

    def _has_empty_pane(self) -> bool:
        return any(pane.selected_chat is None for pane in self._panes)

    def _is_sidebar_narrow(self, size=None, pixel_size=None) -> bool:
        if pixel_size is not None:
            pixel_width = getattr(pixel_size, "width", 0)
            if pixel_width > 0:
                return pixel_width < self._sidebar_auto_hide_pixel_threshold()

        if size is None:
            size = self.size
        cell_width = getattr(size, "width", 0)
        if cell_width <= 0:
            return False
        return cell_width < self._sidebar_auto_hide_column_threshold()

    @staticmethod
    def _widget_inside(widget, parent) -> bool:
        node = widget
        while node is not None:
            if node is parent:
                return True
            node = getattr(node, "parent", None)
        return False

    def _focus_after_sidebar_hidden(self, sidebar: Vertical, button: Button) -> None:
        focused = self.focused
        if focused is None or not self._widget_inside(focused, sidebar):
            return
        pane = self._active_pane()
        if pane.selected_chat is not None:
            msg_input = self._message_input_or_none(pane)
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
        self._sidebar_hidden_by = None if visible else reason
        button.label = "<" if visible else ">"
        button.tooltip = "隐藏群组列表" if visible else "显示群组列表"
        if not visible:
            self._focus_after_sidebar_hidden(sidebar, button)

    def _apply_sidebar_auto_visibility(self, size=None, pixel_size=None) -> None:
        narrow = self._is_sidebar_narrow(size, pixel_size)
        if narrow:
            self._sidebar_auto_paused = False
            if self._has_empty_pane():
                self._set_sidebar_visible(True)
            else:
                self._set_sidebar_visible(False, "auto")
            return

        if self._sidebar_auto_paused:
            return
        if self._sidebar_hidden_by == "auto":
            self._set_sidebar_visible(True)

    def _show_sidebar_for_narrow_navigation(self) -> None:
        if not self._is_sidebar_narrow():
            return
        self._sidebar_auto_paused = False
        self._set_sidebar_visible(True)

    def _hide_sidebar_after_narrow_chat_selection(self) -> None:
        if not self._is_sidebar_narrow():
            return
        self._sidebar_auto_paused = False
        if self._has_empty_pane():
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
            self._nav_layer = "pane"
            self._activate_pane(pane, focus_input=pane.selected_chat is not None)
        else:
            self._nav_layer = "top"
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
        if self._nav_layer == "pane":
            pane = self._active_pane()
        elif self._nav_layer == "top" and self._top_target_pane_uid is not None:
            pane = self._pane_by_uid(self._top_target_pane_uid)
        if pane is None or pane.selected_chat is None:
            return
        event.prevent_default()
        event.stop()
        self._enter_pane_layer(pane)
        self._start_message_input(pane, event.character)

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
        if self._search_has_focus():
            self._nav_layer = "search"
            self._hide_all_message_inputs()
            self._refresh_pane_active_classes()
            return
        if isinstance(focused, ListView) and focused.id == "chat_list":
            self._nav_layer = "chat_list"
            self._hide_all_message_inputs()
            self._refresh_pane_active_classes()
            return
        pane = self._pane_from_widget(focused)
        if pane is None:
            self._hide_all_message_inputs()
            self._refresh_pane_active_classes()
            return
        self._nav_layer = "pane"
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
        self._render_chat_list()
        self._schedule_chat_list_selection_sync(scroll=True)
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
        message_input = self._message_input_or_none(pane)
        if message_input is not None and not message_input.disabled:
            if self._pane_input_visible(pane):
                return message_input
        search = self.query_one("#search", Input)
        return search if not search.disabled else None

    # ------------------------------------------------------------------ #
    # Scroll management
    # ------------------------------------------------------------------ #

    def _message_log_or_none(
        self, pane: Optional[ChatPaneState] = None
    ) -> Optional[MessageLog]:
        pane = pane or self._active_pane()
        try:
            return self._pane_widget(pane, "msg_log", MessageLog)
        except NoMatches:
            return None

    def _message_input_or_none(
        self, pane: Optional[ChatPaneState] = None
    ) -> Optional[Input]:
        pane = pane or self._active_pane()
        try:
            return self._pane_widget(pane, "msg_input", Input)
        except NoMatches:
            return None

    def _scroll_button_or_none(
        self, pane: Optional[ChatPaneState] = None
    ) -> Optional[Button]:
        pane = pane or self._active_pane()
        try:
            return self._pane_widget(pane, "scroll_bottom_btn", Button)
        except NoMatches:
            return None

    def _check_scroll(self) -> None:
        for pane in list(self._panes):
            log = self._message_log_or_none(pane)
            if log is None:
                continue
            cur_y = log.scroll_y
            max_y = log.max_scroll_y
            if max_y <= 0:
                pane.prev_scroll_y = 0
                continue

            # scroll_y decreasing = manual scroll up -> stop auto-stick.
            if cur_y < pane.prev_scroll_y and pane.auto_scroll:
                pane.auto_scroll = False
                self._show_scroll_bottom_btn(pane)
            at_bottom = cur_y >= max_y - 1
            if at_bottom and not pane.auto_scroll:
                pane.auto_scroll = True
                self._hide_scroll_bottom_btn(pane)
            elif at_bottom:
                self._hide_scroll_bottom_btn(pane)

            pane.prev_scroll_y = cur_y

    def _show_scroll_bottom_btn(self, pane: Optional[ChatPaneState] = None) -> None:
        btn = self._scroll_button_or_none(pane)
        if btn is not None and btn.visible is False:
            btn.visible = True

    def _hide_scroll_bottom_btn(self, pane: Optional[ChatPaneState] = None) -> None:
        btn = self._scroll_button_or_none(pane)
        if btn is not None and btn.visible is not False:
            btn.visible = False

    def _force_scroll_end(self, pane_uid: Optional[int] = None) -> None:
        pane = self._pane_by_uid(pane_uid) if pane_uid is not None else self._active_pane()
        if pane is None:
            return
        log = self._message_log_or_none(pane)
        if log is not None:
            log.scroll_end_when_ready()

    # ------------------------------------------------------------------ #
    # Button handlers
    # ------------------------------------------------------------------ #

    @on(Button.Pressed, "#sidebar_toggle_btn")
    def _on_sidebar_toggle(self) -> None:
        if self._sidebar_hidden_by is None:
            narrow = self._is_sidebar_narrow()
            self._sidebar_auto_paused = not narrow
            reason = (
                "manual"
                if len(self._panes) > 1
                else ("auto" if narrow else "manual")
            )
            self._set_sidebar_visible(False, reason)
            return

        self._sidebar_auto_paused = False
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
        if len(self._panes) >= MAX_SPLIT_PANES:
            self._show_toast("最多 4 个分屏")
            return
        pane = ChatPaneState(uid=self._next_pane_uid)
        self._next_pane_uid += 1
        self._panes.append(pane)
        self._active_pane_uid = pane.uid
        self._top_target_pane_uid = pane.uid
        self.query_one("#pane_grid", Container).mount(self._build_pane_container(pane))
        self._update_pane_grid_class()
        self._focus_chat_list_area()
        self._update_pane_titles()
        self._update_split_buttons()
        self._apply_sidebar_auto_visibility()
        self._schedule_chat_list_selection_sync(scroll=True)

    def _toggle_split_layout(self) -> None:
        self._split_layout_horizontal = not self._split_layout_horizontal
        self._update_pane_grid_class()
        self._update_split_buttons()

    def _close_pane(self, pane: ChatPaneState) -> None:
        if len(self._panes) <= 1:
            self._show_toast("至少保留 1 个分屏")
            return
        if pane not in self._panes:
            return
        pane_index = self._panes.index(pane)
        self._panes.remove(pane)
        try:
            self.query_one(f"#chat_pane_{pane.uid}", Vertical).remove()
        except NoMatches:
            pass
        next_index = min(pane_index, len(self._panes) - 1)
        self._active_pane_uid = self._panes[next_index].uid
        if self._top_target_pane_uid == pane.uid:
            self._top_target_pane_uid = self._active_pane_uid
        if self._input_owner_pane_uid == pane.uid:
            self._input_owner_pane_uid = None
        self._update_pane_grid_class()
        self._refresh_pane_active_classes()
        self._update_pane_titles()
        self._update_split_buttons()
        self._apply_sidebar_auto_visibility()
        self._schedule_chat_list_selection_sync(scroll=True)

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
        self._hide_scroll_bottom_btn(pane)
        log = self._message_log_or_none(pane)
        if log is not None:
            log.scroll_end_when_ready()

    # ------------------------------------------------------------------ #
    # Title bar
    # ------------------------------------------------------------------ #

    @staticmethod
    def _chat_title_text(chat: ChatInfo) -> str:
        kind = "群" if chat.chat_type == "group" else "好友"
        return f"{kind}: {chat.name} ({chat.chat_id})"

    def _set_app_title_text(self, text: str) -> None:
        try:
            self.query_one("#app_title", Static).update(text)
        except NoMatches:
            pass

    # ------------------------------------------------------------------ #
    # Chat list rendering
    # ------------------------------------------------------------------ #

    def _show_empty_chats(self, message: str) -> None:
        with self._state_lock:
            self._chats = []
            self._filtered_chats = []
            self._rendered_chats = []
        self.query_one("#chat_list", ListView).clear()
        for pane in self._panes:
            log = self._message_log_or_none(pane)
            if log is not None:
                log.clear()
                log.write(f"[dim]{rich_escape(message)}[/]")

    def _chat_preview(self, chat: ChatInfo) -> str:
        # Previews deliberately use get_last_message (AGENTS.md) rather than
        # deserialising the whole history.
        last = self.storage.get_last_message(chat.chat_type, chat.chat_id)
        if last is None:
            return "暂无消息"
        return last.content or "[空消息]"

    def _chat_list_text(self, chat: ChatInfo, is_pinned: bool) -> tuple[str, str]:
        return chat_logic.chat_list_texts(
            chat, is_pinned, self._chat_preview(chat), CHAT_LIST_TEXT_WIDTH
        )

    @staticmethod
    def _chat_item_texts(name: str, preview: str) -> tuple[Text, Text, Text]:
        return (
            Text(name, no_wrap=True, overflow="ellipsis"),
            Text(preview, no_wrap=True, overflow="ellipsis"),
            Text("", no_wrap=True, overflow="ellipsis"),
        )

    def _render_chat_list(self) -> None:
        search = self.query_one("#search", Input).value
        with self._state_lock:
            chats_snapshot = list(self._chats)
            search_cache = self._search_cache
        filtered = chat_logic.filter_chats(
            chats_snapshot, search, self.storage, search_cache
        )
        render_limit = max(0, int(config.CHAT_LIST_RENDER_LIMIT))
        visible = filtered[:render_limit] if render_limit else filtered
        with self._state_lock:
            self._filtered_chats = visible

        list_view = self.query_one("#chat_list", ListView)
        list_view.clear()
        pinned = set(self.storage.get_pinned_chats())
        rendered: list[Optional[ChatInfo]] = []
        has_pinned = any(
            self.storage.chat_key(chat.chat_type, chat.chat_id) in pinned
            for chat in visible
        )
        separator_added = False
        for chat in visible:
            key = self.storage.chat_key(chat.chat_type, chat.chat_id)
            is_pinned = key in pinned
            if has_pinned and not is_pinned and not separator_added:
                list_view.append(
                    ListItem(
                        Static(
                            Text("──────── 其它会话 ────────"),
                            classes="chat_separator",
                        ),
                        classes="chat_separator_item",
                        disabled=True,
                    )
                )
                rendered.append(None)
                separator_added = True
            name, preview = self._chat_list_text(chat, is_pinned)
            name_text, preview_text, gap_text = self._chat_item_texts(name, preview)
            list_view.append(
                ListItem(
                    Vertical(
                        Static(name_text, classes="chat_name"),
                        Static(preview_text, classes="chat_preview"),
                        Static(gap_text, classes="chat_gap"),
                        classes="chat_item",
                    ),
                    classes="chat_list_item",
                )
            )
            rendered.append(chat)

        with self._state_lock:
            self._rendered_chats = rendered

        self._schedule_chat_list_selection_sync(scroll=False)

    def _sync_chat_list_selection(self, scroll: bool = True) -> None:
        with self._state_lock:
            rendered = list(self._rendered_chats)
        if not rendered:
            return
        target = self._preview_chat or self._selected_chat
        target_index = chat_logic.rendered_chat_index(rendered, target)
        if target_index is None:
            target_index = 0

        list_view = self.query_one("#chat_list", ListView)
        if target_index >= len(list_view.children):
            return
        old_index = list_view.index
        list_view.index = target_index
        if old_index == target_index:
            list_view.watch_index(target_index, target_index)
        if scroll:
            list_view.children[target_index].scroll_visible()

    def _schedule_chat_list_selection_sync(self, scroll: bool = True) -> None:
        self._sync_chat_list_selection(scroll=scroll)
        self.call_after_refresh(lambda: self._sync_chat_list_selection(scroll=scroll))
        self.set_timer(0.05, lambda: self._sync_chat_list_selection(scroll=scroll))
        self.set_timer(0.15, lambda: self._sync_chat_list_selection(scroll=scroll))

    def _refresh_chat_list_item(self, chat_type: str, chat_id: int) -> None:
        with self._state_lock:
            rendered = list(self._rendered_chats)
        target_index = -1
        target_chat: Optional[ChatInfo] = None
        for index, chat in enumerate(rendered):
            if chat and chat.chat_type == chat_type and chat.chat_id == chat_id:
                target_index = index
                target_chat = chat
                break
        if target_chat is None:
            return

        pinned = set(self.storage.get_pinned_chats())
        is_pinned = self.storage.chat_key(chat_type, chat_id) in pinned
        name, preview = self._chat_list_text(target_chat, is_pinned)
        list_view = self.query_one("#chat_list", ListView)
        if target_index >= len(list_view.children):
            return
        item = list_view.children[target_index]
        if not item.children:
            return
        container = item.children[0]
        if len(container.children) < 3:
            return
        name_text, preview_text, gap_text = self._chat_item_texts(name, preview)
        container.children[0].update(name_text)
        container.children[1].update(preview_text)
        container.children[2].update(gap_text)

    def _search_has_focus(self) -> bool:
        focused = self.screen.focused
        return isinstance(focused, Input) and focused.id == "search"

    def _move_chat_list_layer_selection(self, direction: int) -> None:
        if self._chat_list_on_search:
            if direction > 0:
                self._chat_list_on_search = False
                self._set_search_nav_selected(False)
                self._schedule_chat_list_selection_sync(scroll=True)
                try:
                    self.query_one("#chat_list", ListView).focus()
                except NoMatches:
                    pass
            return

        with self._state_lock:
            rendered = list(self._rendered_chats)
        if direction < 0:
            list_view = self.query_one("#chat_list", ListView)
            index = list_view.index
            first_chat_index = next(
                (i for i, chat in enumerate(rendered) if chat is not None),
                None,
            )
            if first_chat_index is None or index == first_chat_index:
                self._chat_list_on_search = True
                self._set_search_nav_selected(True)
                return

        self._move_search_selection(direction)
        self._chat_list_on_search = False
        self._set_search_nav_selected(False)
        try:
            self.query_one("#chat_list", ListView).focus()
        except NoMatches:
            pass

    def _move_search_selection(self, direction: int) -> None:
        with self._state_lock:
            rendered = list(self._rendered_chats)
        if not rendered:
            return
        list_view = self.query_one("#chat_list", ListView)
        current = list_view.index
        if current is None or current < 0 or current >= len(rendered):
            current = -1 if direction > 0 else 0

        for offset in range(1, len(rendered) + 1):
            index = (current + direction * offset) % len(rendered)
            chat = rendered[index]
            if chat is None:
                continue
            pane = self._active_pane()
            pane.preview_chat = chat
            old_index = list_view.index
            list_view.index = index
            if old_index == index:
                list_view.watch_index(index, index)
            if index < len(list_view.children):
                list_view.children[index].scroll_visible()
            return

    def _selected_search_chat(self) -> Optional[ChatInfo]:
        with self._state_lock:
            rendered = list(self._rendered_chats)
        if not rendered:
            return None
        list_view = self.query_one("#chat_list", ListView)
        index = list_view.index
        if index is not None and 0 <= index < len(rendered):
            chat = rendered[index]
            if chat is not None:
                return chat
        pane = self._active_pane()
        if chat_logic.rendered_chat_index(rendered, pane.preview_chat) is not None:
            return pane.preview_chat
        return next((chat for chat in rendered if chat is not None), None)

    def _clear_search_text(self) -> None:
        search = self.query_one("#search", Input)
        if not search.value:
            return
        search.clear()
        self._render_chat_list()

    def _open_chat_from_list_selection(
        self, chat: ChatInfo, focus_pane: bool = True
    ) -> None:
        pane = self._active_pane()
        if not self._same_chat(chat, pane.selected_chat):
            self._open_chat(chat, pane)
        self._clear_search_text()
        self._hide_sidebar_after_narrow_chat_selection()
        if focus_pane:
            self._enter_pane_layer_after_refresh(pane)

    def _open_selected_search_chat(self) -> None:
        chat = self._selected_search_chat()
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
            self._render_chat_list()
        else:
            self._schedule_chat_list_selection_sync(scroll=True)
        self._enter_chat_list_layer()

    @on(Input.Changed, "#search")
    def _on_search_changed(self, _: Input.Changed) -> None:
        if self._search_has_focus():
            self._hide_all_message_inputs()
        self._render_chat_list()

    @on(Input.Changed, ".msg_input")
    def _on_message_input_changed(self, event: Input.Changed) -> None:
        pane = self._pane_from_widget(event.input)
        if pane is None:
            return
        if event.input.value:
            self._input_owner_pane_uid = pane.uid
        self._refresh_message_input_visibility(pane)

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
        self._render_chat_list()
        self._schedule_chat_list_selection_sync(scroll=True)
        self._update_pane_titles()
        msg_input = self._message_input_or_none(pane)
        if msg_input is not None:
            msg_input.disabled = False
            self._refresh_message_input_visibility(pane)
        log = self._message_log_or_none(pane)
        if log is not None:
            log.clear()
            log.write("[dim]正在加载聊天记录...[/]")
        self._run_thread(self._load_messages_worker, pane.uid, chat)

    def _show_messages(
        self,
        pane_uid: int,
        chat: ChatInfo,
        messages: list[MessageData],
        error: str = "",
    ) -> None:
        pane = self._pane_by_uid(pane_uid)
        if pane is None or not self._same_chat(pane.selected_chat, chat):
            return
        pane.messages = messages
        pane.message_line_spans = []
        pane.auto_scroll = True
        self._hide_scroll_bottom_btn(pane)
        log = self._message_log_or_none(pane)
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
            self._render_messages(pane)
            pane.auto_scroll = True
            self._hide_scroll_bottom_btn(pane)
            log.scroll_end_when_ready()
            # Re-assert stick-to-bottom once layout has settled.
            self.set_timer(0.05, lambda uid=pane.uid: self._force_scroll_end(uid))
        self._update_reply_info(pane)

    # ------------------------------------------------------------------ #
    # Message rendering
    # ------------------------------------------------------------------ #

    def _at_resolver(self, chat_type: str, chat_id: int) -> AtResolver:
        return message_logic.make_at_resolver(chat_type, chat_id, self.storage)

    def _sender_name(self, msg: MessageData) -> str:
        name, _, _ = message_logic.resolve_sender(
            msg, self.storage, self.ob.self_id, self._friend_remarks
        )
        return name

    def _resolve_sender(self, msg: MessageData) -> tuple[str, str, str]:
        return message_logic.resolve_sender(
            msg, self.storage, self.ob.self_id, self._friend_remarks
        )

    def _build_reply_preview(
        self, msg: MessageData, pane: Optional[ChatPaneState] = None
    ) -> str:
        pane = pane or self._active_pane()
        return message_logic.build_reply_preview(
            msg, pane.messages, self._sender_name
        )

    def _write_message(
        self,
        log: MessageLog,
        msg: MessageData,
        pane: Optional[ChatPaneState] = None,
        selected: bool = False,
    ) -> tuple[int, int]:
        pane = pane or self._active_pane()
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

    def _render_messages(self, pane: Optional[ChatPaneState] = None) -> None:
        pane = pane or self._active_pane()
        log = self._message_log_or_none(pane)
        if log is None:
            return
        log.clear()
        pane.message_line_spans = []
        for index, msg in enumerate(pane.messages):
            pane.message_line_spans.append(
                self._write_message(
                    log,
                    msg,
                    pane,
                    selected=index == pane.reply_index,
                )
            )
        self._update_reply_info(pane)

    def _message_start_line(
        self, pane: ChatPaneState, index: int
    ) -> Optional[int]:
        if 0 <= index < len(pane.message_line_spans):
            return pane.message_line_spans[index][0]
        return None

    def _scroll_to_message(
        self, pane: ChatPaneState, index: int
    ) -> None:
        target_y = self._message_start_line(pane, index)
        if target_y is None:
            return
        log = self._message_log_or_none(pane)
        if log is None:
            return
        target = log.line_widget(target_y)
        if target is None:
            return

        def scroll_target() -> None:
            if target.is_attached:
                target.scroll_visible(top=True, immediate=True)

        scroll_target()
        self.call_after_refresh(scroll_target)

    def _update_reply_info(self, pane: Optional[ChatPaneState] = None) -> None:
        pane = pane or self._active_pane()
        try:
            widget = self._pane_widget(pane, "reply_info", Static)
        except NoMatches:
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

    def _append_message_if_current(self, chat: ChatInfo, message: MessageData) -> None:
        for pane in list(self._panes):
            if not self._same_chat(pane.selected_chat, chat):
                continue
            pane.messages.append(message)
            log = self._message_log_or_none(pane)
            if log is None:
                continue
            line_span = self._write_message(log, message, pane)
            pane.message_line_spans.append(line_span)
            pane.auto_scroll = True
            self._hide_scroll_bottom_btn(pane)
            log.scroll_end_when_ready()
        self._refresh_chat_list_item(chat.chat_type, chat.chat_id)

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
        at_resolver = self._at_resolver(chat_type, chat_id)
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
            log = self._message_log_or_none(pane)
            if log is None:
                continue
            line_span = self._write_message(log, message, pane)
            pane.message_line_spans.append(line_span)
            if pane.auto_scroll:
                log.scroll_end_when_ready()
        self._refresh_chat_list_item(message.chat_type, message.chat_id)
        if updated:
            self._update_reply_info(self._active_pane())

    # ------------------------------------------------------------------ #
    # Sending messages
    # ------------------------------------------------------------------ #

    @on(Input.Submitted, ".msg_input")
    def _on_message_submitted(self, event: Input.Submitted) -> None:
        self._submit_message_input(event.input)

    def _submit_message_input(self, input_widget: Input) -> None:
        pane = self._pane_from_widget(input_widget)
        if pane is None:
            return
        self._activate_pane(pane)
        text = input_widget.value.strip()
        input_widget.clear()
        self._refresh_message_input_visibility(pane)
        if not text:
            return
        chat = pane.selected_chat
        if chat is None:
            self._show_toast("请先选择会话")
            return
        if not self.ob.running:
            self._show_toast("NapBot 未连接", "无法发送消息")
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
        self._update_reply_info(pane)
        self._run_thread(self._send_worker, chat, text, reply_to, reply_preview)

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
        if pane.selected_chat is not None and self._same_chat(chat, pane.selected_chat):
            pane.preview_chat = None
        else:
            pane.preview_chat = chat
        with self._state_lock:
            rendered = list(self._rendered_chats)

        target_index = chat_logic.rendered_chat_index(rendered, chat)
        if target_index is None:
            self._render_chat_list()
            self._schedule_chat_list_selection_sync(scroll=True)
        else:
            self._schedule_chat_list_selection_sync(scroll=True)

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
        if pane.selected_chat is not None and self._same_chat(chat, pane.selected_chat):
            self._render_chat_list()
            self._schedule_chat_list_selection_sync(scroll=True)
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
        if self._nav_layer == "top" and self._top_target_pane_uid is not None:
            self._focus_chat_list_area()
            return
        if self._nav_layer == "pane":
            self._focus_chat_list_area()
            return
        self._focus_pane_selection_area()

    def action_nav_left(self) -> None:
        focused = self._cursor_target_input()
        if focused is not None:
            focused.action_cursor_left()
            return
        if self._nav_layer == "top" and self._top_target_pane_uid is not None:
            self._move_pane_selection_in_direction("left")

    def action_nav_right(self) -> None:
        focused = self._cursor_target_input()
        if focused is not None:
            focused.action_cursor_right()
            return
        if self._nav_layer == "top" and self._top_target_pane_uid is not None:
            self._move_pane_selection_in_direction("right")

    def action_nav_enter(self) -> None:
        if self._nav_layer == "top":
            if self._top_target_pane_uid is None:
                if self._chat_list_on_search:
                    self._enter_search_layer()
                else:
                    self._open_selected_search_chat()
                return
            pane = self._pane_by_uid(self._top_target_pane_uid)
            if pane is not None:
                self._enter_pane_layer(pane)
            return
        if self._nav_layer == "chat_list":
            if self._chat_list_on_search:
                self._enter_search_layer()
            else:
                self._open_selected_search_chat()
            return
        if self._nav_layer == "search":
            self._open_selected_search_chat()
            return
        if self._nav_layer == "pane":
            focused = self.screen.focused
            if isinstance(focused, Input) and focused.has_class("msg_input"):
                self._submit_message_input(focused)
                return
            self.action_focus_message()

    def action_focus_search(self) -> None:
        self._enter_search_layer()

    def action_focus_message(self) -> None:
        pane = self._active_pane()
        if pane.selected_chat:
            msg_input = self._message_input_or_none(pane)
            if msg_input is not None and not msg_input.disabled:
                self._set_input_owner_pane(pane)
                msg_input.focus()

    def action_reply_previous(self) -> None:
        if self._nav_layer == "top":
            if self._top_target_pane_uid is None:
                self._move_chat_list_layer_selection(-1)
            else:
                self._move_pane_selection_in_direction("up")
            return
        if self._nav_layer == "chat_list":
            self._move_chat_list_layer_selection(-1)
            return
        if self._nav_layer == "search":
            self._move_search_selection(-1)
            return
        if self._nav_layer != "pane":
            return
        pane = self._active_pane()
        if not pane.messages:
            return
        if pane.reply_index < 0:
            pane.reply_index = len(pane.messages) - 1
        elif pane.reply_index > 0:
            pane.reply_index -= 1
        self._render_messages(pane)
        self._scroll_to_message(pane, pane.reply_index)

    def action_reply_next(self) -> None:
        if self._nav_layer == "top":
            if self._top_target_pane_uid is None:
                self._move_chat_list_layer_selection(1)
            else:
                self._move_pane_selection_in_direction("down")
            return
        if self._nav_layer == "chat_list":
            self._move_chat_list_layer_selection(1)
            return
        if self._nav_layer == "search":
            self._move_search_selection(1)
            return
        if self._nav_layer != "pane":
            return
        pane = self._active_pane()
        if pane.reply_index < 0:
            return
        pane.reply_index += 1
        if pane.reply_index >= len(pane.messages):
            pane.reply_index = -1
        self._render_messages(pane)
        if pane.reply_index >= 0:
            self._scroll_to_message(pane, pane.reply_index)

    def action_clear_reply(self) -> None:
        if self._nav_layer == "search":
            self._close_search_mode()
            return
        if self._nav_layer == "chat_list":
            self._enter_top_layer()
            return
        if self._nav_layer == "pane":
            pane = self._active_pane()
            if pane.preview_chat is None and pane.reply_index < 0:
                self._enter_top_layer()
                return
        elif self._nav_layer == "top":
            self._hide_all_message_inputs()
            return
        pane = self._active_pane()
        if pane.preview_chat is not None:
            self._cancel_preview_timer(pane)
            pane.preview_chat = None
            self._render_chat_list()
            self._schedule_chat_list_selection_sync(scroll=True)
        elif pane.reply_index >= 0:
            pane.reply_index = -1
            self._render_messages(pane)
        elif pane.selected_chat:
            msg_input = self._message_input_or_none(pane)
            if msg_input is not None:
                msg_input.focus()
        else:
            self.query_one("#search", Input).focus()
