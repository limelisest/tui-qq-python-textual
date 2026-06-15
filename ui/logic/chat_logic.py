"""Pure helpers for the chat list: filtering, sorting, search and rendering.

Nothing here imports Textual or touches widget state. The App owns the mutable
state (the chat list, the search cache) and passes plain data in. Keeping
these pure means filtering/sorting can be unit-tested and reused by any future
view (a search overlay, a separate window, etc.).

State ownership contract
------------------------
- ``chats``: a snapshot ``list[ChatInfo]``. The caller is responsible for any
  locking when producing the snapshot; this module never mutates it.
- ``search_cache``: ``dict[tuple[str,int], str]`` owned by the App. Functions
  here may write fresh entries into it (lazy full-text build), mirroring the
  original ``basic\0`` / ``full\0`` prefix scheme.
- ``storage``: passed in read-only for ``get_pinned_chats`` / ``chat_key``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from models import ChatInfo
from pinyin import text_to_abbreviation, text_to_xiao_e
from ui.text_utils import display_width, ellipsize

if TYPE_CHECKING:
    from storage import Storage

#: Cache value prefix for the cheap (name + id) search blob.
BASIC_PREFIX = "basic\0"
#: Cache value prefix for the full (name + id + pinyin) search blob.
FULL_PREFIX = "full\0"


def chat_cache_key(chat: ChatInfo) -> tuple[str, int]:
    """Stable cache key for a chat (type + id)."""
    return chat.chat_type, chat.chat_id


def build_search_text(chat: ChatInfo) -> str:
    """Build the full search blob: name, id, double-pinyin and abbreviation.

    Pinyin conversion is best-effort: if pypinyin chokes on a name we simply
    skip that token rather than failing the whole search.
    """
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


def search_text_for_chat(chat: ChatInfo, search_cache: dict) -> str:
    """Return the full search blob for ``chat``, computing + caching on demand.

    Cache layout mirrors the original implementation: a value starting with
    ``full\0`` holds the already-built blob; the suffix after the prefix is the
    blob itself.
    """
    key = chat_cache_key(chat)
    cached = search_cache.get(key)
    if cached and cached.startswith(FULL_PREFIX):
        return cached[len(FULL_PREFIX):]
    text = build_search_text(chat)
    search_cache[key] = FULL_PREFIX + text
    return text


def chat_matches_query(chat: ChatInfo, query: str, search_cache: dict) -> bool:
    """True if ``query`` matches the basic blob or the full search blob."""
    key = chat_cache_key(chat)
    cached = search_cache.get(key, "")
    basic = cached[len(BASIC_PREFIX):] if cached.startswith(BASIC_PREFIX) else cached
    if query in basic:
        return True
    return query in search_text_for_chat(chat, search_cache)


def chat_sort_key(
    chat: ChatInfo, storage: "Storage", pinned_order: Optional[dict] = None
) -> tuple:
    """Sort tuple: pinned first (by pin order), then by recency, then name.

    ``pinned_order`` maps ``storage.chat_key`` -> position; when ``None`` it is
    rebuilt from storage (kept for parity with the original signature).
    """
    if pinned_order is None:
        pinned_order = {
            key: index for index, key in enumerate(storage.get_pinned_chats())
        }
    key = storage.chat_key(chat.chat_type, chat.chat_id)
    if key in pinned_order:
        return (0, float(pinned_order[key]), chat.name)
    return (1, -chat.last_time, chat.name)


def filter_chats(
    chats: list[ChatInfo],
    query: str,
    storage: "Storage",
    search_cache: dict,
) -> list[ChatInfo]:
    """Filter and sort ``chats`` according to the search box ``query``.

    Supports ``g:`` / ``f:`` (and full-width ``g：`` / ``f：``) prefixes to
    restrict to groups / friends. With an empty query, chats that have never
    seen activity (``last_time <= 0``) are hidden to keep the list tidy.
    """
    query = query.strip().lower()
    only_group = False
    only_private = False
    if query.startswith(("g:", "g：")):
        only_group = True
        query = query[2:].strip()
    elif query.startswith(("f:", "f：")):
        only_private = True
        query = query[2:].strip()

    filtered: list[ChatInfo] = []
    for chat in chats:
        if only_group and chat.chat_type != "group":
            continue
        if only_private and chat.chat_type != "private":
            continue
        if not query and chat.last_time <= 0:
            continue
        if not query or chat_matches_query(chat, query, search_cache):
            filtered.append(chat)
    pinned_order = {
        key: index for index, key in enumerate(storage.get_pinned_chats())
    }
    filtered.sort(key=lambda chat: chat_sort_key(chat, storage, pinned_order))
    return filtered


def rendered_chat_index(
    rendered: list[Optional[ChatInfo]], target: Optional[ChatInfo]
) -> Optional[int]:
    """Index in ``rendered`` of the chat matching ``target``, or ``None``.

    ``rendered`` may contain ``None`` placeholders (e.g. separator rows); those
    are skipped. Identity is by (chat_type, chat_id), not object identity.
    """
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


def chat_list_texts(
    chat: ChatInfo,
    is_pinned: bool,
    preview: str,
    width: int,
) -> tuple[str, str]:
    """Render the two text lines for a chat list item: name and preview.

    ``preview`` is supplied by the caller (the App reads it from
    ``Storage.get_last_message``) so this helper stays free of storage access,
    preserving the AGENTS.md rule that previews must use ``get_last_message``.
    """
    kind = "群" if chat.chat_type == "group" else "友"
    pin = "*" if is_pinned else " "
    prefix = f"{pin} [{kind}] "
    name = prefix + ellipsize(chat.name, width - display_width(prefix))
    preview_prefix = "  "
    preview_line = preview_prefix + ellipsize(preview, width - display_width(preview_prefix))
    return name, preview_line


def navigate_index(
    filtered: list[ChatInfo],
    base: Optional[ChatInfo],
    direction: int,
) -> Optional[int]:
    """Compute the next list index when navigating with up/down.

    Returns ``None`` when ``filtered`` is empty. Wraps around the list edges.
    """
    if not filtered:
        return None
    if base is None:
        return 0
    current = next(
        (
            i
            for i, c in enumerate(filtered)
            if c.chat_type == base.chat_type and c.chat_id == base.chat_id
        ),
        -1,
    )
    if current < 0:
        return 0
    return (current + direction) % len(filtered)
