"""Loading the chat list (friends + groups) from the backend.

Absorbs the payload parsing that used to live inline in
``QQChatApp._load_chats_worker``. Returns plain data so the App only has to
publish it to the UI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from models import ChatInfo
from ui.logic.chat_logic import BASIC_PREFIX, chat_cache_key, chat_sort_key

if TYPE_CHECKING:
    from onebot import OneBotClient
    from storage import Storage


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_chats(
    ob: "OneBotClient", storage: "Storage"
) -> Tuple[List[ChatInfo], Dict[int, str], Dict[Tuple[str, int], str], Optional[str]]:
    """Fetch friends + groups and build the chat list.

    Returns
    -------
    (chats, friend_remarks, search_cache, error)
        ``chats`` is sorted (pinned first, then by recency). ``friend_remarks``
        maps ``user_id -> remark`` so the UI can append remarks to group
        messages from friends. ``search_cache`` is the initial ``basic\0``
        search blob per chat. ``error`` is a user-facing message, or ``None``
        on success.
    """
    if not ob.running:
        return [], {}, {}, "NapBot 未连接，无法加载会话列表"

    try:
        friends = ob.get_friend_list()
        groups = ob.get_group_list()
    except Exception as exc:  # network / backend error
        return [], {}, {}, f"加载会话失败: {exc}"

    chats: list[ChatInfo] = []
    friend_remarks: dict[int, str] = {}

    for friend in friends:
        if not isinstance(friend, dict):
            continue
        user_id = _safe_int(friend.get("user_id"))
        if not user_id:
            continue
        remark = friend.get("remark") or friend.get("nickname") or str(user_id)
        friend_remarks[user_id] = remark
        chats.append(
            ChatInfo(
                chat_id=user_id,
                name=remark,
                chat_type="private",
                last_time=storage.get_last_activity("private", user_id),
            )
        )

    for group in groups:
        if not isinstance(group, dict):
            continue
        group_id = _safe_int(group.get("group_id"))
        if not group_id:
            continue
        chats.append(
            ChatInfo(
                chat_id=group_id,
                name=group.get("group_name") or str(group_id),
                chat_type="group",
                last_time=storage.get_last_activity("group", group_id),
            )
        )

    pinned_order = {
        key: index for index, key in enumerate(storage.get_pinned_chats())
    }
    chats.sort(key=lambda chat: chat_sort_key(chat, storage, pinned_order))

    search_cache = {
        chat_cache_key(chat): BASIC_PREFIX + f"{chat.name.lower()}|{chat.chat_id}"
        for chat in chats
    }
    return chats, friend_remarks, search_cache, None
