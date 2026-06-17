"""Pane state dataclass and pure helper functions for split panes.

Extracted from ``ui/app.py`` to keep the App class focused on widget glue.
All functions here are side-effect-free (no Textual imports).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from models import ChatInfo, MessageData


MAX_SPLIT_PANES = 4


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


def same_chat(left: Optional[ChatInfo], right: Optional[ChatInfo]) -> bool:
    return (
        left is not None
        and right is not None
        and left.chat_type == right.chat_type
        and left.chat_id == right.chat_id
    )


def pane_dom_id(pane: ChatPaneState, name: str) -> str:
    return f"pane_{pane.uid}_{name}"


def pane_selector(pane: ChatPaneState, name: str) -> str:
    return f"#{pane_dom_id(pane, name)}"


def pane_title_text(pane: ChatPaneState) -> str:
    if pane.selected_chat is None:
        return "未选择会话"
    return pane.selected_chat.name


def pane_has_active_border(
    pane: ChatPaneState,
    nav_layer: str,
    active_pane_uid: int,
    top_target_pane_uid: Optional[int],
) -> bool:
    if nav_layer == "pane":
        return pane.uid == active_pane_uid
    return nav_layer == "top" and pane.uid == top_target_pane_uid
