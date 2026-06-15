"""Loading history, sending messages and caching group members.

Absorbs the data-fetch + parsing halves of the old
``_load_messages_worker`` / ``_send_worker`` / ``_cache_group_members``. UI
callbacks (``call_from_thread``) stay in the App; this module only talks to
the backend and storage and returns plain data.

Robustness: each parsed payload field degrades to a safe default on bad input,
so one malformed message never aborts a whole history load.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, List, Optional, Tuple

from models import MemberInfo, MessageData
from ui.logic.message_logic import make_at_resolver, message_from_history

if TYPE_CHECKING:
    import config
    from models import ChatInfo
    from onebot import OneBotClient
    from storage import Storage


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def cache_group_members(ob: "OneBotClient", storage: "Storage", group_id: int) -> None:
    """Pull the full member list for a group and persist it (best-effort)."""
    try:
        members = ob.get_group_member_list(group_id)
    except Exception:
        return
    if not isinstance(members, list):
        return
    parsed: list[MemberInfo] = []
    for raw in members:
        if not isinstance(raw, dict):
            continue
        parsed.append(
            MemberInfo(
                user_id=_safe_int(raw.get("user_id")),
                nickname=raw.get("nickname", ""),
                card=raw.get("card", ""),
                title=raw.get("title", ""),
                role=raw.get("role", "member"),
            )
        )
    storage.set_members(group_id, parsed)


def load_history(
    ob: "OneBotClient",
    storage: "Storage",
    chat: "ChatInfo",
    history_count: int,
    cache_members_on_open: bool,
) -> Tuple[List[MessageData], Optional[str]]:
    """Load messages for ``chat``: online history first, storage fallback.

    Returns ``(messages, error)``. ``error`` is a user-facing string when the
    online fetch fails (the local cache is still returned) or when there is no
    data at all; ``None`` on a clean online load.
    """
    if (
        chat.chat_type == "group"
        and ob.running
        and cache_members_on_open
    ):
        cache_group_members(ob, storage, chat.chat_id)

    at_resolver = make_at_resolver(chat.chat_type, chat.chat_id, storage)

    messages: list[MessageData] = []
    error: Optional[str] = None
    if ob.running:
        try:
            if chat.chat_type == "group":
                raw_messages = ob.get_group_msg_history(chat.chat_id, history_count)
            else:
                raw_messages = ob.get_friend_msg_history(chat.chat_id, history_count)
            messages = [
                message_from_history(chat, item, at_resolver)
                for item in raw_messages
                if isinstance(item, dict)
            ]
        except Exception as exc:
            error = f"在线记录加载失败，显示本地缓存: {exc}"

    if not messages:
        messages = storage.get_messages(chat.chat_type, chat.chat_id)
        if not messages and error is None and not ob.running:
            error = "NapBot 未连接，且本地没有这个会话的缓存"

    return messages, error


def send(
    ob: "OneBotClient",
    chat: "ChatInfo",
    text: str,
    reply_to: Optional[int],
    reply_preview: Optional[str],
) -> MessageData:
    """Send ``text`` (optionally replying to ``reply_to``) and return the echo.

    Raises on backend failure; the App surfaces the exception via a toast.
    """
    if chat.chat_type == "group":
        result = ob.send_group_msg(chat.chat_id, text, reply_to)
    else:
        result = ob.send_private_msg(chat.chat_id, text, reply_to)

    return MessageData(
        message_id=_safe_int(result.get("message_id")),
        chat_id=chat.chat_id,
        chat_type=chat.chat_type,
        user_id=_safe_int(ob.self_id),
        content=text,
        time=int(time.time()),
        sender_name="我",
        sender_role="self",
        reply_to=reply_to,
        reply_preview=reply_preview,
    )
