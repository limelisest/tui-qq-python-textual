"""Application and pane state dataclasses.

Kept free of Textual imports so state can be constructed and tested without a
running TUI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from models import ChatInfo, MessageData

if TYPE_CHECKING:
    from ui.navigation import NavigationState
    from ui.sidebar import SidebarState


MAX_SPLIT_PANES = 4


def _new_navigation_state() -> "NavigationState":
    from ui.navigation import NavigationState

    return NavigationState()


def _new_sidebar_state() -> "SidebarState":
    from ui.sidebar import SidebarState

    return SidebarState()


@dataclass
class ChatPaneState:
    """State for one chat split pane."""

    uid: int
    selected_chat: Optional[ChatInfo] = None
    messages: list[MessageData] = field(default_factory=list)
    message_line_spans: list[tuple[int, int]] = field(default_factory=list)
    reply_index: int = -1
    message_action_index: int = 0
    auto_scroll: bool = True
    prev_scroll_y: int = 0
    preview_chat: Optional[ChatInfo] = None
    preview_token: int = 0


@dataclass
class AppState:
    """Mutable application state shared by the App and UI controllers."""

    chats: list[ChatInfo] = field(default_factory=list)
    filtered_chats: list[ChatInfo] = field(default_factory=list)
    rendered_chats: list[Optional[ChatInfo]] = field(default_factory=list)
    search_cache: dict[tuple[str, int], str] = field(default_factory=dict)
    connected: bool = False
    toast_token: int = 0
    storage_dirty: bool = False
    panes: list[ChatPaneState] = field(
        default_factory=lambda: [ChatPaneState(uid=1)]
    )
    active_pane_uid: int = 1
    input_owner_pane_uid: Optional[int] = None
    navigation: "NavigationState" = field(default_factory=_new_navigation_state)
    next_pane_uid: int = 2
    split_layout_horizontal: bool = False
    pending_pane_focus_uid: Optional[int] = None
    friend_remarks: dict[int, str] = field(default_factory=dict)
    right_click_selected_text: str = ""
    sidebar_state: "SidebarState" = field(default_factory=_new_sidebar_state)

    def pane_by_uid(self, uid: Optional[int]) -> Optional[ChatPaneState]:
        return next((pane for pane in self.panes if pane.uid == uid), None)

    def active_pane(self) -> ChatPaneState:
        if not self.panes:
            self.panes.append(ChatPaneState(uid=1))
            self.active_pane_uid = 1
            self.next_pane_uid = max(self.next_pane_uid, 2)
            return self.panes[0]
        pane = self.pane_by_uid(self.active_pane_uid)
        if pane is not None:
            return pane
        self.active_pane_uid = self.panes[0].uid
        return self.panes[0]


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
