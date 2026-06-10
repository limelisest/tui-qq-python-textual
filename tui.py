#!/usr/bin/env python3
"""Textual QQ chat client for a NapBot/OneBot v11 WebSocket backend."""

import datetime
import json
import os
import platform
import subprocess
import threading
import time
import unicodedata
from typing import Callable, Optional

from rich.markup import escape as rich_escape
from rich.text import Text
from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.widgets import (
    Button,
    Input,
    ListItem,
    ListView,
    Static,
)

import config
from models import ChatInfo, MemberInfo, MessageData
from onebot import OneBotClient
from pinyin import text_to_abbreviation, text_to_xiao_e
from storage import Storage


ROLE_STYLES = {
    "owner": "bold orange1",
    "admin": "bold green",
    "member": "white",
    "self": "bold dodger_blue1",
    "system": "dim",
}
CHAT_LIST_TEXT_WIDTH = 24
RIGHT_MOUSE_BUTTON = 3
CLIPBOARD_TIMEOUT = 1.0
SIDEBAR_AUTO_HIDE_PIXELS = 700
SIDEBAR_AUTO_HIDE_COLUMNS = 88


def _run_powershell_clipboard(command: str, input_text: Optional[str] = None):
    if platform.system() != "Windows":
        return None
    try:
        return subprocess.run(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
            ],
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CLIPBOARD_TIMEOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _set_system_clipboard(text: str) -> bool:
    command = (
        "[Console]::InputEncoding=[Text.Encoding]::UTF8; "
        "$text=[Console]::In.ReadToEnd(); Set-Clipboard -Value $text"
    )
    result = _run_powershell_clipboard(command, text)
    return result is not None and result.returncode == 0


def _get_system_clipboard() -> str:
    command = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
        "Get-Clipboard -Raw"
    )
    result = _run_powershell_clipboard(command)
    if result is None or result.returncode != 0:
        return ""
    return result.stdout


class MessageLog(VerticalScroll):
    """Scrollable message area rendered with Static children like the chat list."""

    ALLOW_SELECT = True

    def __init__(self, *children, max_lines: int | None = None, **kwargs) -> None:
        super().__init__(*children, can_focus=False, **kwargs)
        self.max_lines = max_lines
        self._line_widgets: list[Static] = []

    @property
    def line_count(self) -> int:
        return len(self._line_widgets)

    def clear(self) -> "MessageLog":
        self._line_widgets = []
        for child in self.children:
            child.display = False
        self.remove_children()
        self.refresh(layout=True)
        return self

    def write(self, content) -> "MessageLog":
        line_content = " " if content == "" else content
        line = Static(line_content, classes="message_log_line")
        self._line_widgets.append(line)
        self.mount(line)
        if self.max_lines is not None and len(self._line_widgets) > self.max_lines:
            stale = self._line_widgets[: -self.max_lines]
            self._line_widgets = self._line_widgets[-self.max_lines :]
            for widget in stale:
                widget.display = False
            self.remove_children(stale)
        return self

    def line_widget(self, index: int) -> Optional[Static]:
        if 0 <= index < len(self._line_widgets):
            return self._line_widgets[index]
        return None

    def scroll_end_when_ready(self) -> None:
        target = self._line_widgets[-1] if self._line_widgets else None

        def scroll() -> None:
            if not self.is_attached:
                return
            if target is not None and target.is_attached:
                target.scroll_visible(immediate=True)
            self.scroll_end(immediate=True)

        scroll()
        self.call_after_refresh(scroll)
        self.set_timer(0.02, scroll)


def _format_time(timestamp: int | float) -> str:
    if not timestamp:
        return ""
    try:
        return datetime.datetime.fromtimestamp(timestamp).strftime("%H:%M")
    except (OSError, OverflowError, ValueError):
        return ""


def _extract_text(message, at_resolver: Optional[Callable[[str], str]] = None) -> str:
    """Convert OneBot message segments into compact terminal-friendly text."""
    if isinstance(message, str):
        return message
    if not isinstance(message, list):
        return str(message)

    parts: list[str] = []
    for segment in message:
        if not isinstance(segment, dict):
            parts.append(str(segment))
            continue
        msg_type = segment.get("type", "")
        data = segment.get("data", {}) or {}
        if msg_type == "text":
            parts.append(data.get("text", ""))
        elif msg_type == "at":
            qq = str(data.get("qq", ""))
            if qq == "all":
                parts.append("@全体成员")
                continue
            name = at_resolver(qq) if at_resolver else ""
            parts.append(f"@{name or qq}")
        elif msg_type == "image":
            parts.append("[图片]")
        elif msg_type == "video":
            parts.append("[视频]")
        elif msg_type == "face" or msg_type == "mface" or msg_type == "sface":
            parts.append("[表情]")
        elif msg_type == "reply":
            continue
        elif msg_type == "file":
            parts.append("[文件]")
        else:
            parts.append(f"[{msg_type or '消息'}]")
    return "".join(parts)


def _display_width(text: str) -> int:
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in ("F", "W") else 1
    return width


def _ellipsize(text: str, max_width: int) -> str:
    text = " ".join((text or "").split())
    if _display_width(text) <= max_width:
        return text
    suffix = "…"
    target = max_width - _display_width(suffix)
    if target <= 0:
        return suffix
    result: list[str] = []
    width = 0
    for char in text:
        char_width = 2 if ord(char) > 0x7F else 1
        if width + char_width > target:
            break
        result.append(char)
        width += char_width
    return "".join(result).rstrip() + suffix


class QQChatApp(App):
    """Single-screen Textual frontend for QQ chats."""

    TITLE = "TUI-QQ"
    SUB_TITLE = "NapCat / OneBot v11"

    CSS = """
    Screen {
        layout: vertical;
    }

    #top_bar {
        height: 1;
        background: $panel;
        color: $foreground;
    }

    #sidebar_toggle_btn,
    #header_menu_btn {
        width: 3;
        min-width: 3;
        height: 1;
        min-height: 1;
        margin: 0 0;
        padding: 0 0;
        border: none;
        line-pad: 1;
        background: $panel;
        color: $foreground;
        text-style: bold;
        content-align: center middle;
    }

    #sidebar_toggle_btn:hover,
    #header_menu_btn:hover {
        background: $boost;
    }

    #app_title {
        width: 1fr;
        height: 1;
        padding: 0 1;
        background: $panel;
        color: $foreground;
        text-style: bold;
        content-align: center middle;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }

    #top_bar_spacer {
        width: 6;
        min-width: 6;
        height: 1;
        background: $panel;
    }

    #body {
        height: 1fr;
    }

    #sidebar {
        width: 34;
        min-width: 24;
        border-right: solid $primary;
        background: $surface;
    }

    #search {
        height: 3;
        margin: 0 1 1 1;
    }

    #chat_list {
        height: 1fr;
    }

    #chat_list > ListItem.-highlight {
        color: $block-cursor-foreground;
        background: $block-cursor-background;
        text-style: $block-cursor-text-style;
    }

    .chat_list_item {
        height: 3;
    }

    .chat_item {
        height: 3;
    }

    .chat_name {
        height: 1;
        padding: 0 0;
    }

    .chat_preview {
        height: 1;
        padding: 0 0;
        color: $text-muted;
    }

    .chat_gap {
        height: 1;
    }

    .chat_separator_item {
        height: 1;
    }

    .chat_separator {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }

    #main {
        width: 1fr;
    }

    #chat_area {
        height: 1fr;
    }

    #msg_log {
        height: 1fr;
        padding: 0 1;
    }

    .message_log_line {
        height: auto;
        padding: 0 0;
    }

    #reply_info {
        height: 1;
        padding: 0 1;
        color: $warning;
    }

    #input_row {
        height: 3;
        margin: 1 0 1 0;
    }

    #msg_input {
        width: 1fr;
        height: 3;
    }

    #scroll_bottom_btn {
        width: 3;
        min-width: 3;
        height: 3;
        display: none;
    }

    #toast_row {
        height: 0;
    }

    #toast_row.visible {
        height: 3;
    }

    #toast_spacer {
        width: 1fr;
    }

    #toast {
        width: 38;
        height: 3;
        margin: 0 1 0 0;
        padding: 0 1;
        border: solid $accent;
        background: $boost;
        color: $text;
    }
    """

    BINDINGS = [
        # Binding("ctrl+c", "quit", "退出", priority=True),
        Binding("ctrl+r", "refresh_chats", "刷新"),
        Binding("ctrl+t", "change_theme", "主题"),
        # Binding("ctrl+f", "focus_search", "搜索"),
        # Binding("ctrl+e", "focus_message", "输入"),
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

    @staticmethod
    def _chat_title_text(chat: ChatInfo) -> str:
        kind = "群" if chat.chat_type == "group" else "好友"
        return f"{kind}: {chat.name} ({chat.chat_id})"

    def _set_app_title_text(self, text: str) -> None:
        self.query_one("#app_title", Static).update(text)

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
                    yield MessageLog(
                        id="msg_log",
                        max_lines=5000,
                    )
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
        selected_text = self._right_click_selected_text or self.screen.get_selected_text() or ""
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
        _set_system_clipboard(text)

    def _paste_clipboard_to_input(self) -> None:
        text = _get_system_clipboard() or self.clipboard
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

    def _run_thread(self, target, *args) -> None:
        thread = threading.Thread(target=target, args=args, daemon=True)
        thread.start()

    def _show_toast(self, title: str, body: str = "") -> None:
        self._toast_token += 1
        token = self._toast_token
        title = _ellipsize(title, 34)
        body = _ellipsize(body, 34) if body else ""
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

        # scroll_y 减小 = 用户手动向上滚动 → 关闭自动置底
        if cur_y < self._prev_scroll_y and self._auto_scroll:
            self._auto_scroll = False
            self._show_scroll_bottom_btn()
        # 判断是否到达底部（自动置底或手动滚回底部）
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

    def _force_scroll_end(self) -> None:
        log = self._message_log_or_none()
        if log is not None:
            log.scroll_end_when_ready()

    def _connect_and_load(self) -> None:
        try:
            self.ob.connect()
            info = self.ob.get_login_info()
            self.ob.self_id = info.get("user_id")
            self._connected = True
            self.call_from_thread(
                self._show_toast, "已连接", str(self.ob.self_id or "")
            )
        except Exception as exc:
            self._connected = False
        self._load_chats_worker()

    def _load_chats_worker(self) -> None:
        if not self.ob.running:
            self.call_from_thread(self._show_empty_chats, "NapBot 未连接，无法加载会话列表")
            return

        try:
            friends = self.ob.get_friend_list()
            groups = self.ob.get_group_list()
        except Exception as exc:
            self.call_from_thread(self._show_empty_chats, f"加载会话失败: {exc}")
            return

        chats: list[ChatInfo] = []
        for friend in friends:
            user_id = int(friend.get("user_id") or 0)
            if not user_id:
                continue
            remark = friend.get("remark") or friend.get("nickname") or str(user_id)
            self._friend_remarks[user_id] = remark
            chats.append(
                ChatInfo(
                    chat_id=user_id,
                    name=remark,
                    chat_type="private",
                    last_time=self.storage.get_last_activity("private", user_id),
                )
            )

        for group in groups:
            group_id = int(group.get("group_id") or 0)
            if not group_id:
                continue
            chats.append(
                ChatInfo(
                    chat_id=group_id,
                    name=group.get("group_name") or str(group_id),
                    chat_type="group",
                    last_time=self.storage.get_last_activity("group", group_id),
                )
            )

        pinned_order = {
            key: index for index, key in enumerate(self.storage.get_pinned_chats())
        }

        def sort_key(chat: ChatInfo) -> tuple[int, float, str]:
            key = self.storage.chat_key(chat.chat_type, chat.chat_id)
            if key in pinned_order:
                return (0, float(pinned_order[key]), chat.name)
            return (1, -chat.last_time, chat.name)

        chats.sort(key=sort_key)
        cache = {
            self._chat_cache_key(chat): f"basic\0{chat.name.lower()}|{chat.chat_id}"
            for chat in chats
        }

        with self._state_lock:
            self._chats = chats
            self._search_cache = cache
        self.call_from_thread(self._render_chat_list)

    def _show_empty_chats(self, message: str) -> None:
        with self._state_lock:
            self._chats = []
            self._filtered_chats = []
            self._rendered_chats = []
        self.query_one("#chat_list", ListView).clear()
        self.query_one("#msg_log", MessageLog).clear()
        self.query_one("#msg_log", MessageLog).write(f"[dim]{rich_escape(message)}[/]")

    @staticmethod
    def _chat_cache_key(chat: ChatInfo) -> tuple[str, int]:
        return chat.chat_type, chat.chat_id

    def _build_search_text(self, chat: ChatInfo) -> str:
        tokens = [chat.name.lower(), str(chat.chat_id)]
        try:
            tokens.append(text_to_xiao_e(chat.name).lower())
        except Exception:
            pass
        try:
            tokens.append(text_to_abbreviation(chat.name).lower())
        except Exception:
            pass
        return "|".join(tokens)

    def _search_text_for_chat(self, chat: ChatInfo) -> str:
        key = self._chat_cache_key(chat)
        cached = self._search_cache.get(key)
        if cached and cached.startswith("full\0"):
            return cached[5:]
        text = self._build_search_text(chat)
        self._search_cache[key] = f"full\0{text}"
        return text

    def _chat_matches_query(self, chat: ChatInfo, query: str) -> bool:
        key = self._chat_cache_key(chat)
        cached = self._search_cache.get(key, "")
        basic = cached[6:] if cached.startswith("basic\0") else cached
        if query in basic:
            return True
        return query in self._search_text_for_chat(chat)

    def _filter_chats(self, query: str) -> list[ChatInfo]:
        query = query.strip().lower()
        only_group = False
        only_private = False
        if query.startswith(("g:", "g：")):
            only_group = True
            query = query[2:].strip()
        elif query.startswith(("f:", "f：")):
            only_private = True
            query = query[2:].strip()

        with self._state_lock:
            chats = list(self._chats)

        filtered: list[ChatInfo] = []
        for chat in chats:
            if only_group and chat.chat_type != "group":
                continue
            if only_private and chat.chat_type != "private":
                continue
            if not query and chat.last_time <= 0:
                continue
            if not query or self._chat_matches_query(chat, query):
                filtered.append(chat)
        pinned_order = {
            key: index for index, key in enumerate(self.storage.get_pinned_chats())
        }
        filtered.sort(key=lambda chat: self._chat_sort_key(chat, pinned_order))
        return filtered

    def _chat_sort_key(
        self, chat: ChatInfo, pinned_order: Optional[dict[str, int]] = None
    ) -> tuple[int, float, str]:
        if pinned_order is None:
            pinned_order = {
                key: index for index, key in enumerate(self.storage.get_pinned_chats())
            }
        key = self.storage.chat_key(chat.chat_type, chat.chat_id)
        if key in pinned_order:
            return (0, float(pinned_order[key]), chat.name)
        return (1, -chat.last_time, chat.name)

    def _render_chat_list(self) -> None:
        search = self.query_one("#search", Input).value
        filtered = self._filter_chats(search)
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
                        Static(Text("──────── 其它会话 ────────"), classes="chat_separator"),
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

    def _chat_preview(self, chat: ChatInfo) -> str:
        last = self.storage.get_last_message(chat.chat_type, chat.chat_id)
        if last is None:
            return "暂无消息"
        return last.content or "[空消息]"

    def _chat_list_text(self, chat: ChatInfo, is_pinned: bool) -> tuple[str, str]:
        kind = "群" if chat.chat_type == "group" else "友"
        pin = "*" if is_pinned else " "
        prefix = f"{pin} [{kind}] "
        name = prefix + _ellipsize(
            chat.name,
            CHAT_LIST_TEXT_WIDTH - _display_width(prefix),
        )
        preview_prefix = "  "
        preview = preview_prefix + _ellipsize(
            self._chat_preview(chat),
            CHAT_LIST_TEXT_WIDTH - _display_width(preview_prefix),
        )
        return name, preview

    @staticmethod
    def _rendered_chat_index(
        rendered: list[Optional[ChatInfo]], target: Optional[ChatInfo]
    ) -> Optional[int]:
        if target is None:
            return None
        return next(
            (
                index
                for index, chat in enumerate(rendered)
                if chat is not None
                and chat.chat_type == target.chat_type
                and chat.chat_id == target.chat_id
            ),
            None,
        )

    def _chat_item_texts(self, name: str, preview: str) -> tuple[Text, Text, Text]:
        return (
            Text(name, no_wrap=True, overflow="ellipsis"),
            Text(preview, no_wrap=True, overflow="ellipsis"),
            Text("", no_wrap=True, overflow="ellipsis"),
        )

    def _sync_chat_list_selection(self, scroll: bool = True) -> None:
        with self._state_lock:
            rendered = list(self._rendered_chats)
        if not rendered:
            return
        target = self._preview_chat or self._selected_chat
        target_index = self._rendered_chat_index(rendered, target)
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
            if index is None or index < 0 or index >= len(self._rendered_chats):
                return
            chat = self._rendered_chats[index]
            if chat is None:
                return
        self._open_chat(chat)
        self._hide_sidebar_after_narrow_chat_selection()

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

    def _load_messages_worker(self, chat: ChatInfo) -> None:
        if (
            chat.chat_type == "group"
            and self.ob.running
            and config.CACHE_GROUP_MEMBERS_ON_OPEN
        ):
            self._cache_group_members(chat.chat_id)

        messages: list[MessageData] = []
        error = ""
        if self.ob.running:
            try:
                if chat.chat_type == "group":
                    raw_messages = self.ob.get_group_msg_history(
                        chat.chat_id, config.HISTORY_MESSAGE_COUNT
                    )
                else:
                    raw_messages = self.ob.get_friend_msg_history(
                        chat.chat_id, config.HISTORY_MESSAGE_COUNT
                    )
                messages = [self._message_from_history(chat, item) for item in raw_messages]
            except Exception as exc:
                error = f"在线记录加载失败，显示本地缓存: {exc}"

        if not messages:
            messages = self.storage.get_messages(chat.chat_type, chat.chat_id)
            if not messages and not error and not self.ob.running:
                error = "NapBot 未连接，且本地没有这个会话的缓存"

        self.call_from_thread(self._show_messages, chat, messages, error)

    def _cache_group_members(self, group_id: int) -> None:
        try:
            members = self.ob.get_group_member_list(group_id)
        except Exception:
            return
        self.storage.set_members(
            group_id,
            [
                MemberInfo(
                    user_id=int(raw.get("user_id") or 0),
                    nickname=raw.get("nickname", ""),
                    card=raw.get("card", ""),
                    title=raw.get("title", ""),
                    role=raw.get("role", "member"),
                )
                for raw in members
            ],
        )

    def _message_from_history(self, chat: ChatInfo, raw: dict) -> MessageData:
        sender = raw.get("sender", {}) or {}
        reply_to, reply_preview = self._extract_reply_context(chat, raw.get("message", ""))
        return MessageData(
            message_id=int(raw.get("message_id") or 0),
            chat_id=chat.chat_id,
            chat_type=chat.chat_type,
            user_id=int(sender.get("user_id") or raw.get("user_id") or 0),
            content=_extract_text(
                raw.get("message", ""),
                self._at_resolver(chat.chat_type, chat.chat_id),
            ),
            time=int(raw.get("time") or 0),
            sender_name=sender.get("card") or sender.get("nickname", ""),
            sender_title=sender.get("title", ""),
            sender_role=sender.get("role", "member"),
            reply_to=reply_to,
            reply_preview=reply_preview,
        )

    def _message_from_event(self, event: dict) -> MessageData:
        msg_type = event.get("message_type")
        chat_type = "group" if msg_type == "group" else "private"
        chat_id = event.get("group_id") if chat_type == "group" else event.get("user_id")
        chat_id = int(chat_id or 0)
        chat_info = ChatInfo(chat_id=chat_id, name="", chat_type=chat_type)
        sender = event.get("sender", {}) or {}
        reply_to, reply_preview = self._extract_reply_context(chat_info, event.get("message", ""))
        return MessageData(
            message_id=int(event.get("message_id") or 0),
            chat_id=chat_id,
            chat_type=chat_type,
            user_id=int(sender.get("user_id") or event.get("user_id") or 0),
            content=_extract_text(
                event.get("message", ""),
                self._at_resolver(chat_type, chat_id),
            ),
            time=int(event.get("time") or time.time()),
            sender_name=sender.get("card") or sender.get("nickname", ""),
            sender_title=sender.get("title", ""),
            sender_role=sender.get("role", "member"),
            reply_to=reply_to,
            reply_preview=reply_preview,
        )

    def _at_resolver(self, chat_type: str, chat_id: int) -> Callable[[str], str]:
        def resolve(qq: str) -> str:
            if chat_type != "group":
                return ""
            try:
                user_id = int(qq)
            except (TypeError, ValueError):
                return ""
            member = self.storage.get_member(chat_id, user_id)
            return member.display_name if member else ""

        return resolve

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
            # 等布局完成后再次确保置底
            self.set_timer(0.05, self._force_scroll_end)
        self._update_reply_info()

    def _resolve_sender(self, msg: MessageData) -> tuple[str, str, str]:
        name = msg.sender_name or str(msg.user_id)
        title = msg.sender_title
        role = msg.sender_role or "member"
        if msg.chat_type == "group":
            member = self.storage.get_member(msg.chat_id, msg.user_id)
            if member:
                name = member.display_name or name
                title = member.title or title
                role = member.role or role
            # 如果群成员也是好友且不是自己，追加备注
            if msg.user_id != self.ob.self_id:
                remark = self._friend_remarks.get(msg.user_id)
                if remark and remark != name:
                    name = f"{name} ({remark})"
        if msg.user_id and msg.user_id == self.ob.self_id:
            role = "self"
        return name, title, role

    def _render_messages(self) -> None:
        log = self.query_one("#msg_log", MessageLog)
        log.clear()
        self._message_line_spans = []
        for index, msg in enumerate(self._messages):
            self._message_line_spans.append(
                self._write_message(log, msg, selected=index == self._reply_index)
            )
        self._update_reply_info()

    def _resolve_reply_preview(self, chat: ChatInfo, reply_to: Optional[int]) -> Optional[str]:
        if reply_to is None:
            return None
        target = next((item for item in self._messages if item.message_id == reply_to), None)
        if target is None:
            target = next((item for item in self.storage.get_messages(chat.chat_type, chat.chat_id)
                           if item.message_id == reply_to), None)
        if target is None:
            return None
        name, _, _ = self._resolve_sender(target)
        preview = (target.content or "").replace("\n", " ")
        preview = " ".join(preview.split())
        if len(preview) > 42:
            preview = preview[:42] + "..."
        return f"[回复 {name}：{preview}]"

    def _extract_reply_context(self, chat: ChatInfo, message) -> tuple[Optional[int], Optional[str]]:
        if isinstance(message, list):
            for segment in message:
                if isinstance(segment, dict) and segment.get("type") == "reply":
                    data = segment.get("data", {}) or {}
                    try:
                        reply_to = int(data.get("id") or 0)
                    except (TypeError, ValueError):
                        reply_to = None
                    if reply_to:
                        return reply_to, self._resolve_reply_preview(chat, reply_to)
        return None, None

    def _build_reply_preview(self, msg: MessageData) -> str:
        if msg.reply_preview:
            return msg.reply_preview
        if msg.reply_to is None:
            return ""
        target = next((item for item in self._messages if item.message_id == msg.reply_to), None)
        if target is None:
            return ""
        name, _, _ = self._resolve_sender(target)
        preview = (target.content or "").replace("\n", " ")
        preview = " ".join(preview.split())
        if len(preview) > 42:
            preview = preview[:42] + "..."
        return f"[回复 {name}：{preview}]"

    def _write_message(
        self, log: MessageLog, msg: MessageData, selected: bool = False
    ) -> tuple[int, int]:
        start_line = log.line_count
        name, title, role = self._resolve_sender(msg)
        style = ROLE_STYLES.get(role, ROLE_STYLES["member"])
        title_text = f"[{title}]" if title else ""
        timestamp = _format_time(msg.time)
        time_text = f" [dim]{timestamp}[/]" if timestamp else ""
        content = rich_escape(msg.content or "")
        escaped_name = rich_escape(title_text + name)
        reply_preview = self._build_reply_preview(msg)
        if selected:
            header_text = f"{escaped_name} {timestamp}" if timestamp else escaped_name
            header_renderable = Text.from_markup(f"[reverse]{header_text}[/]")
        else:
            header = f"[{style}]{escaped_name}[/]{time_text}"
            header_renderable = Text.from_markup(header)
        log.write(header_renderable)
        if reply_preview:
            preview_style = "reverse" if selected else "dim"
            preview_renderable = Text.from_markup(
                f"[{preview_style}]  {rich_escape(reply_preview)}[/]"
            )
            log.write(preview_renderable)
        content_markup = f"[reverse]  {content}[/]" if selected else f"  {content}"
        log.write(Text.from_markup(content_markup))
        log.write("")
        return start_line, log.line_count

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
        name, _, _ = self._resolve_sender(msg)
        preview = msg.content.replace("\n", " ")[:42]
        if len(msg.content) > 42:
            preview += "..."
        widget.update(f"回复 {name}: {preview}")

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
            name, _, _ = self._resolve_sender(reply_target)
            preview = (reply_target.content or "").replace("\n", " ")
            preview = " ".join(preview.split())
            if len(preview) > 42:
                preview = preview[:42] + "..."
            reply_preview = f"[回复 {name}：{preview}]"
        self._reply_index = -1
        self._update_reply_info()
        self._run_thread(self._send_worker, chat, text, reply_to, reply_preview)

    def _send_worker(self, chat: ChatInfo, text: str, reply_to: Optional[int], reply_preview: Optional[str]) -> None:
        try:
            if chat.chat_type == "group":
                result = self.ob.send_group_msg(chat.chat_id, text, reply_to)
            else:
                result = self.ob.send_private_msg(chat.chat_id, text, reply_to)
        except Exception as exc:
            self.call_from_thread(self._show_toast, "发送失败", str(exc))
            return

        message = MessageData(
            message_id=int(result.get("message_id") or 0),
            chat_id=chat.chat_id,
            chat_type=chat.chat_type,
            user_id=int(self.ob.self_id or 0),
            content=text,
            time=int(time.time()),
            sender_name="我",
            sender_role="self",
            reply_to=reply_to,
            reply_preview=reply_preview,
        )
        self.storage.add_message(chat.chat_type, chat.chat_id, message)
        self.storage.update_last_activity(chat.chat_type, chat.chat_id)
        self._touch_chat(chat.chat_type, chat.chat_id, message.time)
        self.call_from_thread(self._mark_storage_dirty)
        self.call_from_thread(self._append_message_if_current, chat, message)

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

    def _touch_chat(self, chat_type: str, chat_id: int, timestamp: int | float) -> None:
        with self._state_lock:
            for chat in self._chats:
                if chat.chat_type == chat_type and chat.chat_id == chat_id:
                    chat.last_time = float(timestamp or time.time())
                    break
            self._chats.sort(key=self._chat_sort_key)

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
        message = self._message_from_event(event)
        if not message.chat_id:
            return
        self.storage.add_message(message.chat_type, message.chat_id, message)
        self.storage.update_last_activity(message.chat_type, message.chat_id)
        self._mark_storage_dirty()
        self._touch_chat(message.chat_type, message.chat_id, message.time)

        chat = self._selected_chat
        if chat and chat.chat_type == message.chat_type and chat.chat_id == message.chat_id:
            self._messages.append(message)
            line_span = self._write_message(self.query_one("#msg_log", MessageLog), message)
            self._message_line_spans.append(line_span)
            self._refresh_chat_list_item(message.chat_type, message.chat_id)
            if self._auto_scroll:
                self.query_one("#msg_log", MessageLog).scroll_end_when_ready()
        else:
            self._refresh_chat_list_item(message.chat_type, message.chat_id)

    def action_refresh_chats(self) -> None:
        self._show_toast("正在刷新会话...")
        self._run_thread(self._load_chats_worker)

    def _navigate_chat(self, direction: int) -> None:
        chats = self._filtered_chats
        if not chats:
            return
        base = self._preview_chat or self._selected_chat
        if base is None:
            index = 0
        else:
            current = next(
                (i for i, c in enumerate(chats)
                 if c.chat_type == base.chat_type
                 and c.chat_id == base.chat_id),
                -1,
            )
            if current < 0:
                index = 0
            else:
                index = (current + direction) % len(chats)

        chat = chats[index]
        if self._selected_chat is not None and chat is self._selected_chat:
            self._preview_chat = None
        else:
            self._preview_chat = chat
        with self._state_lock:
            rendered = list(self._rendered_chats)

        target_index = self._rendered_chat_index(rendered, chat)
        if target_index is None:
            self._render_chat_list()
            self._schedule_chat_list_selection_sync(scroll=True)
        else:
            self._schedule_chat_list_selection_sync(scroll=True)

        # 重置延迟提交定时器
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
