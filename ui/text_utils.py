"""Pure, dependency-free text helpers used by both logic and UI layers.

Nothing here imports Textual or touches widget state, so these functions can be
unit-tested in isolation and reused by future rendering paths (image previews,
export, etc.).
"""

from __future__ import annotations

import datetime
import unicodedata
from typing import Callable, List, Optional, Union

# A OneBot message is either a plain string or a list of segment dicts.
MessageLike = Union[str, List[dict], object]
#: Resolver that turns an ``@`` target qq string into a display name.
AtResolver = Callable[[str], str]


def format_time(timestamp: "int | float") -> str:
    """Render a unix timestamp as ``HH:MM``, or ``''`` on falsy input."""
    if not timestamp:
        return ""
    try:
        return datetime.datetime.fromtimestamp(timestamp).strftime("%H:%M")
    except (OSError, OverflowError, ValueError):
        return ""


def display_width(text: str) -> int:
    """Return the visible column width of ``text``.

    East-Asian full/wide characters count as 2; combining marks are ignored so
    they do not inflate the width of composed characters.
    """
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in ("F", "W") else 1
    return width


def ellipsize(text: str, max_width: int) -> str:
    """Collapse whitespace and truncate ``text`` to ``max_width`` columns.

    Truncation appends an ellipsis and never splits in the middle of a wide
    character. If ``max_width`` is too small to fit anything but the ellipsis,
    the ellipsis itself is returned.
    """
    text = " ".join((text or "").split())
    if display_width(text) <= max_width:
        return text
    suffix = "…"
    target = max_width - display_width(suffix)
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


def _default_at_resolver(qq: str) -> str:
    return qq


def extract_text(
    message: MessageLike,
    at_resolver: Optional[AtResolver] = None,
) -> str:
    """Convert OneBot message segments into compact terminal-friendly text.

    Behaviour mirrors the original inline implementation in ``tui.py``. The
    per-segment rendering lives in :mod:`ui.logic.message_logic` via a
    registry, but this helper keeps the simple, dependency-free fallback used
    by previews and search indexing where no resolver context is needed.
    """
    if isinstance(message, str):
        return message
    if not isinstance(message, list):
        return str(message)

    resolver = at_resolver or _default_at_resolver
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
            name = resolver(qq)
            parts.append(f"@{name or qq}")
        elif msg_type == "image":
            parts.append("[图片]")
        elif msg_type == "video":
            parts.append("[视频]")
        elif msg_type == "forward":
            parts.append("[转发消息]")
        elif msg_type in ("face", "mface", "sface"):
            parts.append("[表情]")
        elif msg_type == "reply":
            continue
        elif msg_type == "file":
            parts.append("[文件]")
        else:
            parts.append(f"[{msg_type or '消息'}]")
    return "".join(parts)
