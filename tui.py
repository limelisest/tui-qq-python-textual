#!/usr/bin/env python3
"""Textual QQ chat client for a NapBot/OneBot v11 WebSocket backend."""

import datetime
import threading
import time
from typing import Optional

from rich.markup import escape as rich_escape
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, ListItem, ListView, RichLog, Static

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


def _format_time(timestamp: int | float) -> str:
    if not timestamp:
        return ""
    try:
        return datetime.datetime.fromtimestamp(timestamp).strftime("%H:%M")
    except (OSError, OverflowError, ValueError):
        return ""


def _extract_text(message) -> str:
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
            parts.append(f"@{data.get('qq', '')}")
        elif msg_type == "image":
            parts.append("[图片]")
        elif msg_type == "face":
            parts.append("[表情]")
        elif msg_type == "reply":
            parts.append("[回复]")
        elif msg_type == "file":
            parts.append("[文件]")
        else:
            parts.append(f"[{msg_type or '消息'}]")
    return "".join(parts)


def _message_from_event(event: dict) -> MessageData:
    msg_type = event.get("message_type")
    chat_type = "group" if msg_type == "group" else "private"
    chat_id = event.get("group_id") if chat_type == "group" else event.get("user_id")
    sender = event.get("sender", {}) or {}
    return MessageData(
        message_id=event.get("message_id", 0),
        chat_id=int(chat_id or 0),
        chat_type=chat_type,
        user_id=int(sender.get("user_id") or event.get("user_id") or 0),
        content=_extract_text(event.get("message", "")),
        time=int(event.get("time") or time.time()),
        sender_name=sender.get("card") or sender.get("nickname", ""),
        sender_title=sender.get("title", ""),
        sender_role=sender.get("role", "member"),
    )


class QQChatApp(App):
    """Single-screen Textual frontend for QQ chats."""

    TITLE = "QQ Chat TUI"
    SUB_TITLE = "NapBot / OneBot v11"

    CSS = """
    Screen {
        layout: vertical;
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

    #sidebar_title {
        height: 1;
        padding: 0 1;
        text-style: bold;
        color: $accent;
    }

    #status {
        height: 3;
        padding: 0 1;
        color: $text-muted;
    }

    #search {
        height: 3;
        margin: 0 1 1 1;
    }

    #chat_list {
        height: 1fr;
    }

    #main {
        width: 1fr;
    }

    #chat_title {
        height: 1;
        padding: 0 1;
        text-style: bold;
        background: $boost;
    }

    #msg_log {
        height: 1fr;
        padding: 0 1;
    }

    #reply_info {
        height: 1;
        padding: 0 1;
        color: $warning;
    }

    #msg_input {
        height: 3;
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "退出", priority=True),
        Binding("ctrl+r", "refresh_chats", "刷新"),
        Binding("ctrl+f", "focus_search", "搜索"),
        Binding("ctrl+e", "focus_message", "输入"),
        Binding("alt+up", "reply_previous", "上条回复"),
        Binding("alt+down", "reply_next", "下条回复"),
        Binding("escape", "clear_reply", "取消回复"),
    ]

    def __init__(self):
        super().__init__()
        self.storage = Storage(config.CACHE_FILE)
        self.storage.load()
        self.ob = OneBotClient()

        self._state_lock = threading.Lock()
        self._chats: list[ChatInfo] = []
        self._filtered_chats: list[ChatInfo] = []
        self._search_cache: dict[tuple[str, int], str] = {}
        self._selected_chat: Optional[ChatInfo] = None
        self._messages: list[MessageData] = []
        self._reply_index = -1
        self._connected = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Static("会话", id="sidebar_title")
                yield Static("正在连接 NapBot...", id="status")
                yield Input(
                    placeholder="搜索: 支持名称 / 简拼 / 小鹤, g:群 f:好友",
                    id="search",
                )
                yield ListView(id="chat_list")
            with Vertical(id="main"):
                yield Static("未选择会话", id="chat_title")
                yield RichLog(
                    id="msg_log",
                    wrap=True,
                    markup=True,
                    highlight=False,
                    max_lines=5000,
                    min_width=20,
                )
                yield Static("", id="reply_info")
                yield Input(placeholder="选择会话后输入消息，Enter 发送", id="msg_input")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#msg_input", Input).disabled = True
        self.query_one("#search", Input).focus()
        self.set_interval(0.1, self._drain_events)
        self._run_thread(self._connect_and_load)

    def on_unmount(self) -> None:
        self.storage.save()
        self.ob.disconnect()

    def _run_thread(self, target, *args) -> None:
        thread = threading.Thread(target=target, args=args, daemon=True)
        thread.start()

    def _set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    def _connect_and_load(self) -> None:
        try:
            self.ob.connect()
            info = self.ob.get_login_info()
            self.ob.self_id = info.get("user_id")
            self._connected = True
            self.call_from_thread(
                self._set_status,
                f"已连接: {self.ob.self_id or '未知账号'}\n{config.WS_URL}",
            )
        except Exception as exc:
            self._connected = False
            self.call_from_thread(
                self._set_status,
                f"未连接 NapBot\n{exc}",
            )
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
            chats.append(
                ChatInfo(
                    chat_id=user_id,
                    name=friend.get("remark") or friend.get("nickname") or str(user_id),
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

        recent_order = {
            key: index for index, key in enumerate(self.storage.get_recent_chats())
        }

        def sort_key(chat: ChatInfo) -> tuple[int, float, str]:
            key = self.storage.chat_key(chat.chat_type, chat.chat_id)
            if key in recent_order:
                return (0, float(recent_order[key]), chat.name)
            return (1, -chat.last_time, chat.name)

        chats.sort(key=sort_key)
        cache = {self._chat_cache_key(chat): self._build_search_text(chat) for chat in chats}

        with self._state_lock:
            self._chats = chats
            self._search_cache = cache
        self.call_from_thread(self._render_chat_list)

    def _show_empty_chats(self, message: str) -> None:
        with self._state_lock:
            self._chats = []
            self._filtered_chats = []
        self.query_one("#chat_list", ListView).clear()
        self.query_one("#msg_log", RichLog).clear()
        self.query_one("#msg_log", RichLog).write(f"[dim]{rich_escape(message)}[/]")

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
            cache = dict(self._search_cache)

        filtered: list[ChatInfo] = []
        for chat in chats:
            if only_group and chat.chat_type != "group":
                continue
            if only_private and chat.chat_type != "private":
                continue
            if not query or query in cache.get(self._chat_cache_key(chat), chat.name.lower()):
                filtered.append(chat)
        return filtered

    def _render_chat_list(self) -> None:
        search = self.query_one("#search", Input).value
        filtered = self._filter_chats(search)
        with self._state_lock:
            self._filtered_chats = filtered

        list_view = self.query_one("#chat_list", ListView)
        list_view.clear()
        recent = set(self.storage.get_recent_chats())
        for chat in filtered:
            kind = "群" if chat.chat_type == "group" else "友"
            key = self.storage.chat_key(chat.chat_type, chat.chat_id)
            pin = "*" if key in recent else " "
            label = f"{pin} [{kind}] {chat.name}"
            list_view.append(ListItem(Static(label)))

        if filtered:
            list_view.index = 0
            count = len(filtered)
            self._set_status(
                f"{'已连接' if self.ob.running else '未连接'} | {count} 个会话\n{config.WS_URL}"
            )
        else:
            self._set_status(f"{'已连接' if self.ob.running else '未连接'} | 无匹配会话\n{config.WS_URL}")

    @on(Input.Changed, "#search")
    def _on_search_changed(self, _: Input.Changed) -> None:
        self._render_chat_list()

    @on(ListView.Selected, "#chat_list")
    def _on_chat_selected(self, event: ListView.Selected) -> None:
        index = event.list_view.index
        with self._state_lock:
            if index is None or index < 0 or index >= len(self._filtered_chats):
                return
            chat = self._filtered_chats[index]
        self._open_chat(chat)

    def _open_chat(self, chat: ChatInfo) -> None:
        self._selected_chat = chat
        self._reply_index = -1
        self._messages = []
        self.storage.add_recent_chat(chat.chat_type, chat.chat_id)
        title = f"{'群' if chat.chat_type == 'group' else '好友'}: {chat.name} ({chat.chat_id})"
        self.query_one("#chat_title", Static).update(title)
        self.query_one("#msg_input", Input).disabled = False
        self.query_one("#msg_input", Input).focus()
        log = self.query_one("#msg_log", RichLog)
        log.clear()
        log.write("[dim]正在加载聊天记录...[/]")
        self._run_thread(self._load_messages_worker, chat)

    def _load_messages_worker(self, chat: ChatInfo) -> None:
        if chat.chat_type == "group" and self.ob.running:
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
        return MessageData(
            message_id=int(raw.get("message_id") or 0),
            chat_id=chat.chat_id,
            chat_type=chat.chat_type,
            user_id=int(sender.get("user_id") or raw.get("user_id") or 0),
            content=_extract_text(raw.get("message", "")),
            time=int(raw.get("time") or 0),
            sender_name=sender.get("card") or sender.get("nickname", ""),
            sender_title=sender.get("title", ""),
            sender_role=sender.get("role", "member"),
        )

    def _show_messages(
        self, chat: ChatInfo, messages: list[MessageData], error: str = ""
    ) -> None:
        if self._selected_chat != chat:
            return
        self._messages = messages
        log = self.query_one("#msg_log", RichLog)
        log.clear()
        if error:
            log.write(f"[yellow]{rich_escape(error)}[/]")
            log.write("")
        if not messages:
            log.write("[dim]暂无消息[/]")
        else:
            self._render_messages()
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
        if msg.user_id and msg.user_id == self.ob.self_id:
            role = "self"
        return name, title, role

    def _render_messages(self) -> None:
        log = self.query_one("#msg_log", RichLog)
        log.clear()
        for index, msg in enumerate(self._messages):
            self._write_message(log, msg, selected=index == self._reply_index)
        self._update_reply_info()

    def _write_message(self, log: RichLog, msg: MessageData, selected: bool = False) -> None:
        name, title, role = self._resolve_sender(msg)
        style = "reverse" if selected else ROLE_STYLES.get(role, ROLE_STYLES["member"])
        title_text = f"[{title}]" if title else ""
        timestamp = _format_time(msg.time)
        time_text = f" [dim]{timestamp}[/]" if timestamp else ""
        header = f"[{style}]{rich_escape(title_text + name)}[/]{time_text}"
        content = rich_escape(msg.content or "")
        if selected:
            selected_name = rich_escape(title_text + name)
            log.write(Text.from_markup(f"[reverse]{selected_name} {timestamp}[/]"))
            log.write(Text.from_markup(f"[reverse]  {content}[/]"))
        else:
            log.write(header)
            log.write(f"  {content}")
        log.write("")

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
            self.notify("请先选择会话", severity="warning")
            return
        if not self.ob.running:
            self.notify("NapBot 未连接，无法发送", severity="error")
            return

        reply_to = None
        if 0 <= self._reply_index < len(self._messages):
            reply_to = self._messages[self._reply_index].message_id
        self._reply_index = -1
        self._update_reply_info()
        self._run_thread(self._send_worker, chat, text, reply_to)

    def _send_worker(self, chat: ChatInfo, text: str, reply_to: Optional[int]) -> None:
        try:
            if chat.chat_type == "group":
                result = self.ob.send_group_msg(chat.chat_id, text, reply_to)
            else:
                result = self.ob.send_private_msg(chat.chat_id, text, reply_to)
        except Exception as exc:
            self.call_from_thread(self.notify, f"发送失败: {exc}", severity="error")
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
        )
        self.storage.add_message(chat.chat_type, chat.chat_id, message)
        self.storage.update_last_activity(chat.chat_type, chat.chat_id)
        self.storage.save()
        self.call_from_thread(self._append_message_if_current, chat, message)

    def _append_message_if_current(self, chat: ChatInfo, message: MessageData) -> None:
        if self._selected_chat != chat:
            return
        self._messages.append(message)
        self._write_message(self.query_one("#msg_log", RichLog), message)

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
        message = _message_from_event(event)
        if not message.chat_id:
            return
        self.storage.add_message(message.chat_type, message.chat_id, message)
        self.storage.update_last_activity(message.chat_type, message.chat_id)
        self.storage.save()

        chat = self._selected_chat
        if chat and chat.chat_type == message.chat_type and chat.chat_id == message.chat_id:
            self._messages.append(message)
            self._write_message(self.query_one("#msg_log", RichLog), message)
        else:
            self.notify("收到新消息", title=f"{message.chat_type}:{message.chat_id}")

    def action_refresh_chats(self) -> None:
        self._set_status("正在刷新会话...")
        self._run_thread(self._load_chats_worker)

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

    def action_reply_next(self) -> None:
        if self._reply_index < 0:
            return
        self._reply_index += 1
        if self._reply_index >= len(self._messages):
            self._reply_index = -1
        self._render_messages()

    def action_clear_reply(self) -> None:
        if self._reply_index >= 0:
            self._reply_index = -1
            self._render_messages()
        elif self._selected_chat:
            self.query_one("#msg_input", Input).focus()
        else:
            self.query_one("#search", Input).focus()
