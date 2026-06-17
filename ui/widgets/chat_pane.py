"""Pane widget builder — creates the ``Vertical`` widget tree for one chat pane.

Extracted from ``QQChatApp._build_pane_container``.
"""

from __future__ import annotations

from typing import Optional

from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Static

from ui.state import ChatPaneState, pane_dom_id, pane_has_active_border, pane_title_text
from ui.widgets import MessageLog


def build_pane_container(
    pane: ChatPaneState,
    nav_layer: str,
    active_pane_uid: int,
    top_target_pane_uid: Optional[int],
    input_visible: bool = False,
) -> Vertical:
    """Build the full widget tree for a single chat split pane."""
    title = Static(
        pane_title_text(pane),
        id=pane_dom_id(pane, "title"),
        classes="pane_title",
    )
    close_btn = Button(
        "-",
        id=pane_dom_id(pane, "close_btn"),
        classes="pane_close_btn",
        compact=True,
    )
    msg_log = MessageLog(
        id=pane_dom_id(pane, "msg_log"),
        classes="msg_log",
        max_lines=5000,
    )
    msg_input = Input(
        placeholder="选择会话后输入消息，Enter 发送",
        id=pane_dom_id(pane, "msg_input"),
        classes="msg_input",
    )
    msg_input.disabled = pane.selected_chat is None
    scroll_btn = Button(
        "↓",
        id=pane_dom_id(pane, "scroll_bottom_btn"),
        classes="scroll_bottom_btn",
        variant="default",
    )
    scroll_btn.visible = not pane.auto_scroll
    input_row = Horizontal(
        msg_input,
        id=pane_dom_id(pane, "input_row"),
        classes="input_row",
    )
    input_row.display = input_visible
    pane_classes = "chat_pane"
    if pane_has_active_border(
        pane, nav_layer, active_pane_uid, top_target_pane_uid
    ):
        pane_classes += " active_pane"
    return Vertical(
        Horizontal(
            Static("", classes="pane_title_pad"),
            title,
            scroll_btn,
            close_btn,
            id=pane_dom_id(pane, "header"),
            classes="pane_header",
        ),
        Vertical(
            msg_log,
            id=pane_dom_id(pane, "chat_area"),
            classes="chat_area",
        ),
        Static(
            "",
            id=pane_dom_id(pane, "reply_info"),
            classes="reply_info",
        ),
        input_row,
        id=f"chat_pane_{pane.uid}",
        classes=pane_classes,
    )
