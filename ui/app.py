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

from rich.markup import escape as rich_escape
from rich.text import Text
from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
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
    SIDEBAR_AUTO_HIDE_PIXELS,
)
from ui.text_utils import ellipsize
from ui.widgets import MessageLog


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
        Binding("ctrl+left", "prev_chat", "上一个会话", priority=True),
        Binding("ctrl+right", "next_chat", "下一个会话", priority=True),
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
        self._selected_chat: Optional[ChatInfo] = None
        self._messages: list[MessageData] = []
        self._message_line_spans: list[tuple[int, int]] = []
        self._reply_index = -1
        self._connected = False
        self._toast_token = 0
        self._storage_dirty = False
        self._auto_scroll = True
        self._prev_scroll_y = 0
        self._preview_chat: Optional[ChatInfo] = None
        self._preview_token = 0
        self._friend_remarks: dict[int, str] = {}
        self._right_click_selected_text = ""
        self._sidebar_hidden_by: Optional[str] = None
        self._sidebar_auto_paused = False

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
            yield Static("未选择会话", id="app_title")
            yield Static("", id="top_bar_spacer")
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Input(
                    placeholder="搜索: 支持名称 / 简拼 / 小鹤, g:群 f:好友",
                    id="search",
                )
                yield ListView(id="chat_list")
            with Vertical(id="main"):
                with Vertical(id="chat_area"):
                    yield MessageLog(id="msg_log", max_lines=5000)
                yield Static("", id="reply_info")
                with Horizontal(id="toast_row"):
                    yield Static("", id="toast_spacer")
                    yield Static("", id="toast")
                with Horizontal(id="input_row"):
                    yield Input(
                        placeholder="选择会话后输入消息，Enter 发送",
                        id="msg_input",
                    )
                    yield Button("↓", id="scroll_bottom_btn", variant="default")

    def on_mount(self) -> None:
        self.query_one("#msg_input", Input).disabled = True
        self.query_one("#search", Input).focus()
        menu_btn = self.query_one("#header_menu_btn", Button)
        menu_btn.disabled = not self.ENABLE_COMMAND_PALETTE
        menu_btn.tooltip = (
            "打开命令面板" if self.ENABLE_COMMAND_PALETTE else "命令面板不可用"
        )
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

    def _load_messages_worker(self, chat: ChatInfo) -> None:
        messages, error = message_service.load_history(
            self.ob,
            self.storage,
            chat,
            config.HISTORY_MESSAGE_COUNT,
            config.CACHE_GROUP_MEMBERS_ON_OPEN,
        )
        self.call_from_thread(self._show_messages, chat, messages, error or "")

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

    def _is_sidebar_narrow(self, size=None, pixel_size=None) -> bool:
        if pixel_size is not None:
            pixel_width = getattr(pixel_size, "width", 0)
            if pixel_width > 0:
                return pixel_width < SIDEBAR_AUTO_HIDE_PIXELS

        if size is None:
            size = self.size
        cell_width = getattr(size, "width", 0)
        if cell_width <= 0:
            return False
        return cell_width < SIDEBAR_AUTO_HIDE_COLUMNS

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
        if self._selected_chat is not None:
            msg_input = self.query_one("#msg_input", Input)
            if not msg_input.disabled:
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
        self._set_sidebar_visible(False, "auto")

    # ------------------------------------------------------------------ #
    # Mouse handling (right-click copy / paste / pin)
    # ------------------------------------------------------------------ #

    @on(events.MouseDown)
    def _on_app_mouse_down(self, event: events.MouseDown) -> None:
        if event.button == RIGHT_MOUSE_BUTTON:
            if self._mouse_event_in_chat_list(event):
                self._right_click_selected_text = ""
                return
            self._right_click_selected_text = self.screen.get_selected_text() or ""

    @on(events.MouseUp)
    def _on_app_mouse_up(self, event: events.MouseUp) -> None:
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
        message_input = self.query_one("#msg_input", Input)
        if not message_input.disabled:
            return message_input
        search = self.query_one("#search", Input)
        return search if not search.disabled else None

    # ------------------------------------------------------------------ #
    # Scroll management
    # ------------------------------------------------------------------ #

    def _message_log_or_none(self) -> Optional[MessageLog]:
        try:
            return self.query_one("#msg_log", MessageLog)
        except NoMatches:
            return None

    def _check_scroll(self) -> None:
        log = self._message_log_or_none()
        if log is None:
            return
        cur_y = log.scroll_y
        max_y = log.max_scroll_y
        if max_y <= 0:
            self._prev_scroll_y = 0
            return

        # scroll_y decreasing = the user scrolled up manually -> stop auto-stick.
        if cur_y < self._prev_scroll_y and self._auto_scroll:
            self._auto_scroll = False
            self._show_scroll_bottom_btn()
        at_bottom = cur_y >= max_y - 1
        if at_bottom and not self._auto_scroll:
            self._auto_scroll = True
            self._hide_scroll_bottom_btn()
        elif at_bottom:
            self._hide_scroll_bottom_btn()

        self._prev_scroll_y = cur_y

    def _show_scroll_bottom_btn(self) -> None:
        btn = self.query_one("#scroll_bottom_btn", Button)
        if btn.display is False:
            btn.display = True

    def _hide_scroll_bottom_btn(self) -> None:
        btn = self.query_one("#scroll_bottom_btn", Button)
        if btn.display is not False:
            btn.display = False

    def _force_scroll_end(self) -> None:
        log = self._message_log_or_none()
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
            self._set_sidebar_visible(False, "auto" if narrow else "manual")
            return

        self._sidebar_auto_paused = False
        self._set_sidebar_visible(True)

    @on(Button.Pressed, "#header_menu_btn")
    async def _on_header_menu(self) -> None:
        if self.ENABLE_COMMAND_PALETTE:
            await self.run_action("app.command_palette")

    @on(Button.Pressed, "#scroll_bottom_btn")
    def _on_scroll_bottom(self) -> None:
        self._auto_scroll = True
        self._hide_scroll_bottom_btn()
        self.query_one("#msg_log", MessageLog).scroll_end_when_ready()

    # ------------------------------------------------------------------ #
    # Title bar
    # ------------------------------------------------------------------ #

    @staticmethod
    def _chat_title_text(chat: ChatInfo) -> str:
        kind = "群" if chat.chat_type == "group" else "好友"
        return f"{kind}: {chat.name} ({chat.chat_id})"

    def _set_app_title_text(self, text: str) -> None:
        self.query_one("#app_title", Static).update(text)

    # ------------------------------------------------------------------ #
    # Chat list rendering
    # ------------------------------------------------------------------ #

    def _show_empty_chats(self, message: str) -> None:
        with self._state_lock:
            self._chats = []
            self._filtered_chats = []
            self._rendered_chats = []
        self.query_one("#chat_list", ListView).clear()
        self.query_one("#msg_log", MessageLog).clear()
        self.query_one("#msg_log", MessageLog).write(f"[dim]{rich_escape(message)}[/]")

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

    @on(Input.Changed, "#search")
    def _on_search_changed(self, _: Input.Changed) -> None:
        self._render_chat_list()

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
        self._open_chat(chat)
        self._hide_sidebar_after_narrow_chat_selection()

    # ------------------------------------------------------------------ #
    # Opening / loading a chat
    # ------------------------------------------------------------------ #

    def _open_chat(self, chat: ChatInfo) -> None:
        self._selected_chat = chat
        self._reply_index = -1
        self._messages = []
        self._message_line_spans = []
        self._render_chat_list()
        self._schedule_chat_list_selection_sync(scroll=True)
        self._set_app_title_text(self._chat_title_text(chat))
        self.query_one("#msg_input", Input).disabled = False
        self.query_one("#msg_input", Input).focus()
        log = self.query_one("#msg_log", MessageLog)
        log.clear()
        log.write("[dim]正在加载聊天记录...[/]")
        self._run_thread(self._load_messages_worker, chat)

    def _show_messages(
        self, chat: ChatInfo, messages: list[MessageData], error: str = ""
    ) -> None:
        if self._selected_chat != chat:
            return
        self._messages = messages
        self._auto_scroll = True
        self._hide_scroll_bottom_btn()
        log = self.query_one("#msg_log", MessageLog)
        log.clear()
        if error:
            log.write(f"[yellow]{rich_escape(error)}[/]")
            log.write("")
        if not messages:
            log.write("[dim]暂无消息[/]")
            log.scroll_home(immediate=True)
        else:
            self._render_messages()
            self._auto_scroll = True
            self._hide_scroll_bottom_btn()
            log.scroll_end_when_ready()
            # Re-assert stick-to-bottom once layout has settled.
            self.set_timer(0.05, self._force_scroll_end)
        self._update_reply_info()

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

    def _build_reply_preview(self, msg: MessageData) -> str:
        return message_logic.build_reply_preview(msg, self._messages, self._sender_name)

    def _write_message(
        self, log: MessageLog, msg: MessageData, selected: bool = False
    ) -> tuple[int, int]:
        start_line = log.line_count
        name, title, role = self._resolve_sender(msg)
        renderables = message_logic.build_message_renderables(
            msg,
            name=name,
            title=title,
            role=role,
            role_styles=ROLE_STYLES,
            reply_preview=self._build_reply_preview(msg),
            selected=selected,
        )
        log.write(renderables.header)
        if renderables.preview is not None:
            log.write(renderables.preview)
        log.write(renderables.content)
        log.write("")
        return start_line, log.line_count

    def _render_messages(self) -> None:
        log = self.query_one("#msg_log", MessageLog)
        log.clear()
        self._message_line_spans = []
        for index, msg in enumerate(self._messages):
            self._message_line_spans.append(
                self._write_message(log, msg, selected=index == self._reply_index)
            )
        self._update_reply_info()

    def _message_start_line(self, index: int) -> Optional[int]:
        if 0 <= index < len(self._message_line_spans):
            return self._message_line_spans[index][0]
        return None

    def _scroll_to_message(self, index: int) -> None:
        target_y = self._message_start_line(index)
        if target_y is None:
            return
        log = self.query_one("#msg_log", MessageLog)
        target = log.line_widget(target_y)
        if target is None:
            return

        def scroll_target() -> None:
            if target.is_attached:
                target.scroll_visible(top=True, immediate=True)

        scroll_target()
        self.call_after_refresh(scroll_target)

    def _update_reply_info(self) -> None:
        widget = self.query_one("#reply_info", Static)
        if self._reply_index < 0 or self._reply_index >= len(self._messages):
            widget.update("")
            return
        msg = self._messages[self._reply_index]
        name = self._sender_name(msg)
        preview = msg.content.replace("\n", " ")[:42]
        if len(msg.content) > 42:
            preview += "..."
        widget.update(f"回复 {name}: {preview}")

    def _append_message_if_current(self, chat: ChatInfo, message: MessageData) -> None:
        if self._selected_chat != chat:
            return
        self._messages.append(message)
        line_span = self._write_message(self.query_one("#msg_log", MessageLog), message)
        self._message_line_spans.append(line_span)
        self._refresh_chat_list_item(chat.chat_type, chat.chat_id)
        self._auto_scroll = True
        self._hide_scroll_bottom_btn()
        self.query_one("#msg_log", MessageLog).scroll_end_when_ready()

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

        chat = self._selected_chat
        if chat and chat.chat_type == message.chat_type and chat.chat_id == message.chat_id:
            self._messages.append(message)
            line_span = self._write_message(
                self.query_one("#msg_log", MessageLog), message
            )
            self._message_line_spans.append(line_span)
            self._refresh_chat_list_item(message.chat_type, message.chat_id)
            if self._auto_scroll:
                self.query_one("#msg_log", MessageLog).scroll_end_when_ready()
        else:
            self._refresh_chat_list_item(message.chat_type, message.chat_id)

    # ------------------------------------------------------------------ #
    # Sending messages
    # ------------------------------------------------------------------ #

    @on(Input.Submitted, "#msg_input")
    def _on_message_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.clear()
        if not text:
            return
        chat = self._selected_chat
        if chat is None:
            self._show_toast("请先选择会话")
            return
        if not self.ob.running:
            self._show_toast("NapBot 未连接", "无法发送消息")
            return

        reply_to = None
        reply_preview = None
        if 0 <= self._reply_index < len(self._messages):
            reply_target = self._messages[self._reply_index]
            reply_to = reply_target.message_id
            reply_preview = message_logic.build_reply_preview(
                reply_target, self._messages, self._sender_name
            )
        self._reply_index = -1
        self._update_reply_info()
        self._run_thread(self._send_worker, chat, text, reply_to, reply_preview)

    # ------------------------------------------------------------------ #
    # Actions (bound keys)
    # ------------------------------------------------------------------ #

    def action_refresh_chats(self) -> None:
        self._show_toast("正在刷新会话...")
        self._run_thread(self._load_chats_worker)

    def _navigate_chat(self, direction: int) -> None:
        with self._state_lock:
            chats = list(self._filtered_chats)
        base = self._preview_chat or self._selected_chat
        index = chat_logic.navigate_index(chats, base, direction)
        if index is None:
            return
        chat = chats[index]
        if self._selected_chat is not None and chat is self._selected_chat:
            self._preview_chat = None
        else:
            self._preview_chat = chat
        with self._state_lock:
            rendered = list(self._rendered_chats)

        target_index = chat_logic.rendered_chat_index(rendered, chat)
        if target_index is None:
            self._render_chat_list()
            self._schedule_chat_list_selection_sync(scroll=True)
        else:
            self._schedule_chat_list_selection_sync(scroll=True)

        # Reset the deferred-commit timer.
        self._cancel_preview_timer()
        if self._preview_chat is not None:
            token = self._preview_token
            self.set_timer(1.0, lambda: self._commit_preview_if_current(token))

    def _cancel_preview_timer(self) -> None:
        self._preview_token += 1

    def _commit_preview_if_current(self, token: int) -> None:
        if token == self._preview_token:
            self._commit_preview()

    def _commit_preview(self) -> None:
        self._cancel_preview_timer()
        chat = self._preview_chat
        if chat is None:
            return
        self._preview_chat = None
        if self._selected_chat is not None and chat is self._selected_chat:
            self._render_chat_list()
            self._schedule_chat_list_selection_sync(scroll=True)
            return
        self._selected_chat = chat
        self._reply_index = -1
        self._messages = []
        self._message_line_spans = []
        self._set_app_title_text(self._chat_title_text(chat))
        self.query_one("#msg_input", Input).disabled = False
        self.query_one("#msg_input", Input).focus()
        log = self.query_one("#msg_log", MessageLog)
        log.clear()
        log.write("[dim]正在加载聊天记录...[/]")
        self._render_chat_list()
        self._schedule_chat_list_selection_sync(scroll=True)
        self._run_thread(self._load_messages_worker, chat)
        self._hide_sidebar_after_narrow_chat_selection()

    def action_prev_chat(self) -> None:
        self._show_sidebar_for_narrow_navigation()
        self._navigate_chat(-1)

    def action_next_chat(self) -> None:
        self._show_sidebar_for_narrow_navigation()
        self._navigate_chat(1)

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_focus_message(self) -> None:
        if self._selected_chat:
            self.query_one("#msg_input", Input).focus()

    def action_reply_previous(self) -> None:
        if not self._messages:
            return
        if self._reply_index < 0:
            self._reply_index = len(self._messages) - 1
        elif self._reply_index > 0:
            self._reply_index -= 1
        self._render_messages()
        self._scroll_to_message(self._reply_index)

    def action_reply_next(self) -> None:
        if self._reply_index < 0:
            return
        self._reply_index += 1
        if self._reply_index >= len(self._messages):
            self._reply_index = -1
        self._render_messages()
        if self._reply_index >= 0:
            self._scroll_to_message(self._reply_index)

    def action_clear_reply(self) -> None:
        if self._preview_chat is not None:
            self._cancel_preview_timer()
            self._preview_chat = None
            self._render_chat_list()
            self._schedule_chat_list_selection_sync(scroll=True)
        elif self._reply_index >= 0:
            self._reply_index = -1
            self._render_messages()
        elif self._selected_chat:
            self.query_one("#msg_input", Input).focus()
        else:
            self.query_one("#search", Input).focus()
