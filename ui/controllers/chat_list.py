"""Chat-list rendering, search selection and navigation.

Extracted from ``QQChatApp`` so the App class can focus on coordination.
The controller takes an ``app`` reference (duck-typed to what it needs) and
delegates widget queries / state mutations back to the App.
"""

from __future__ import annotations

from typing import Optional

from rich.text import Text
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.widgets import Input, ListItem, ListView, Static

import config
from models import ChatInfo
from ui.logic import chat_logic
from ui.theme import CHAT_LIST_TEXT_WIDTH


class ChatListController:
    """Manages the sidebar chat list: rendering, search, selection sync.

    Usage::

        self._chat_list = ChatListController(self)
    """

    def __init__(self, app) -> None:
        self._app = app

    # -- helpers (kept here to reduce noise in app.py) ----------------- #

    def set_search_nav_selected(self, selected: bool) -> None:
        try:
            search = self._app.query_one("#search", Input)
        except NoMatches:
            return
        if selected:
            search.add_class("nav_selected")
        else:
            search.remove_class("nav_selected")

    def search_has_focus(self) -> bool:
        focused = self._app.screen.focused
        return isinstance(focused, Input) and focused.id == "search"

    def chat_preview(self, chat: ChatInfo) -> str:
        last = self._app.storage.get_last_message(
            chat.chat_type, chat.chat_id
        )
        if last is None:
            return "暂无消息"
        return last.content or "[空消息]"

    def chat_list_text(self, chat: ChatInfo, is_pinned: bool) -> tuple[str, str]:
        return chat_logic.chat_list_texts(
            chat, is_pinned, self.chat_preview(chat), CHAT_LIST_TEXT_WIDTH
        )

    @staticmethod
    def chat_item_texts(name: str, preview: str) -> tuple[Text, Text, Text]:
        return (
            Text(name, no_wrap=True, overflow="ellipsis"),
            Text(preview, no_wrap=True, overflow="ellipsis"),
            Text("", no_wrap=True, overflow="ellipsis"),
        )

    @staticmethod
    def separator_item(label: str) -> ListItem:
        return ListItem(
            Static(
                Text(f"──────── {label} ────────"),
                classes="chat_separator",
            ),
            classes="chat_separator_item",
            disabled=True,
        )

    # -- main rendering ------------------------------------------------- #

    def render_chat_list(self) -> None:
        app = self._app
        search = app.query_one("#search", Input).value
        with app._state_lock:
            chats_snapshot = list(app.state.chats)
            search_cache = app.state.search_cache
        filtered = chat_logic.filter_chats(
            chats_snapshot, search, app.storage, search_cache
        )
        render_limit = max(0, int(config.CHAT_LIST_RENDER_LIMIT))
        visible = filtered[:render_limit] if render_limit else filtered
        with app._state_lock:
            app.state.filtered_chats = visible

        list_view = app.query_one("#chat_list", ListView)
        list_view.clear()
        pinned = set(app.storage.get_pinned_chats())
        rendered: list[Optional[ChatInfo]] = []
        pending_order = {
            key: index for index, key in enumerate(app.state.pending_chat_keys)
        }
        pending_chats = [
            chat
            for chat in visible
            if app.storage.chat_key(chat.chat_type, chat.chat_id) in pending_order
        ]
        pending_chats.sort(
            key=lambda chat: pending_order[
                app.storage.chat_key(chat.chat_type, chat.chat_id)
            ]
        )
        regular_chats = [
            chat
            for chat in visible
            if app.storage.chat_key(chat.chat_type, chat.chat_id)
            not in pending_order
        ]
        if pending_chats:
            list_view.append(self.separator_item("未读会话"))
            rendered.append(None)
            for chat in pending_chats:
                key = app.storage.chat_key(chat.chat_type, chat.chat_id)
                is_pinned = key in pinned
                name, preview = self.chat_list_text(chat, is_pinned)
                name_text, preview_text, gap_text = self.chat_item_texts(
                    name, preview
                )
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
            if regular_chats:
                list_view.append(self.separator_item("置顶会话"))
                rendered.append(None)
        has_pinned = any(
            app.storage.chat_key(chat.chat_type, chat.chat_id) in pinned
            for chat in regular_chats
        )
        separator_added = False
        for chat in regular_chats:
            key = app.storage.chat_key(chat.chat_type, chat.chat_id)
            is_pinned = key in pinned
            if has_pinned and not is_pinned and not separator_added:
                list_view.append(self.separator_item("其它会话"))
                rendered.append(None)
                separator_added = True
            name, preview = self.chat_list_text(chat, is_pinned)
            name_text, preview_text, gap_text = self.chat_item_texts(
                name, preview
            )
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

        with app._state_lock:
            app.state.rendered_chats = rendered

        self.schedule_chat_list_selection_sync(scroll=False)

    # -- selection sync ------------------------------------------------- #

    def sync_chat_list_selection(self, scroll: bool = True) -> None:
        app = self._app
        with app._state_lock:
            rendered = list(app.state.rendered_chats)
        if not rendered:
            return
        target = app._preview_chat or app._selected_chat
        target_index = chat_logic.rendered_chat_index(rendered, target)
        if target_index is None:
            target_index = 0

        list_view = app.query_one("#chat_list", ListView)
        if target_index >= len(list_view.children):
            return
        old_index = list_view.index
        list_view.index = target_index
        if old_index == target_index:
            list_view.watch_index(target_index, target_index)
        if scroll:
            list_view.children[target_index].scroll_visible()

    def schedule_chat_list_selection_sync(self, scroll: bool = True) -> None:
        self.sync_chat_list_selection(scroll=scroll)
        self._app.call_after_refresh(
            lambda: self.sync_chat_list_selection(scroll=scroll)
        )
        self._app.set_timer(
            0.05, lambda: self.sync_chat_list_selection(scroll=scroll)
        )
        self._app.set_timer(
            0.15, lambda: self.sync_chat_list_selection(scroll=scroll)
        )

    # -- show empty state ----------------------------------------------- #

    def show_empty_chats(self, message: str) -> None:
        app = self._app
        with app._state_lock:
            app.state.chats = []
            app.state.filtered_chats = []
            app.state.rendered_chats = []
        app.query_one("#chat_list", ListView).clear()
        from rich.markup import escape as rich_escape
        for pane in app._panes:
            log = app._msg_ctrl.message_log_or_none(pane)
            if log is not None:
                log.clear()
                log.write(f"[dim]{rich_escape(message)}[/]")

    # -- search / navigation -------------------------------------------- #

    def move_chat_list_layer_selection(self, direction: int) -> None:
        app = self._app
        if app.state.navigation.chat_list_on_search:
            if direction > 0:
                app.state.navigation.chat_list_on_search = False
                self.set_search_nav_selected(False)
                self.schedule_chat_list_selection_sync(scroll=True)
                try:
                    app.query_one("#chat_list", ListView).focus()
                except NoMatches:
                    pass
            return

        with app._state_lock:
            rendered = list(app.state.rendered_chats)
        if direction < 0:
            list_view = app.query_one("#chat_list", ListView)
            index = list_view.index
            first_chat_index = next(
                (i for i, chat in enumerate(rendered) if chat is not None),
                None,
            )
            if first_chat_index is None or index == first_chat_index:
                app.state.navigation.chat_list_on_search = True
                self.set_search_nav_selected(True)
                return

        self.move_search_selection(direction)
        app.state.navigation.chat_list_on_search = False
        self.set_search_nav_selected(False)
        try:
            app.query_one("#chat_list", ListView).focus()
        except NoMatches:
            pass

    def move_search_selection(self, direction: int) -> None:
        app = self._app
        with app._state_lock:
            rendered = list(app.state.rendered_chats)
        if not rendered:
            return
        list_view = app.query_one("#chat_list", ListView)
        current = list_view.index
        if current is None or current < 0 or current >= len(rendered):
            current = -1 if direction > 0 else 0

        for offset in range(1, len(rendered) + 1):
            index = (current + direction * offset) % len(rendered)
            chat = rendered[index]
            if chat is None:
                continue
            pane = app._active_pane()
            pane.preview_chat = chat
            old_index = list_view.index
            list_view.index = index
            if old_index == index:
                list_view.watch_index(index, index)
            if index < len(list_view.children):
                list_view.children[index].scroll_visible()
            return

    def selected_search_chat(self) -> Optional[ChatInfo]:
        app = self._app
        with app._state_lock:
            rendered = list(app.state.rendered_chats)
        if not rendered:
            return None
        list_view = app.query_one("#chat_list", ListView)
        index = list_view.index
        if index is not None and 0 <= index < len(rendered):
            chat = rendered[index]
            if chat is not None:
                return chat
        pane = app._active_pane()
        if chat_logic.rendered_chat_index(rendered, pane.preview_chat) is not None:
            return pane.preview_chat
        return next((chat for chat in rendered if chat is not None), None)

    def clear_search_text(self) -> None:
        app = self._app
        search = app.query_one("#search", Input)
        if not search.value:
            return
        search.clear()
        self.render_chat_list()

    # -- single item refresh -------------------------------------------- #

    def refresh_chat_list_item(self, chat_type: str, chat_id: int) -> None:
        app = self._app
        with app._state_lock:
            rendered = list(app.state.rendered_chats)
        target_index = -1
        target_chat: Optional[ChatInfo] = None
        for index, chat in enumerate(rendered):
            if chat and chat.chat_type == chat_type and chat.chat_id == chat_id:
                target_index = index
                target_chat = chat
                break
        if target_chat is None:
            return

        key = app.storage.chat_key(chat_type, chat_id)
        is_pending = key in app.state.pending_chat_keys
        pinned = set(app.storage.get_pinned_chats())
        is_pinned = key in pinned
        name, preview = self.chat_list_text(target_chat, is_pinned)
        list_view = app.query_one("#chat_list", ListView)
        if target_index >= len(list_view.children):
            return
        item = list_view.children[target_index]
        if not item.children:
            return
        container = item.children[0]
        if len(container.children) < 3:
            return
        name_text, preview_text, gap_text = self.chat_item_texts(name, preview)
        container.children[0].update(name_text)
        container.children[1].update(preview_text)
        container.children[2].update(gap_text)

        # -- Surgical reorder: move DOM element to correct sorted position --
        if is_pending:
            return

        # Don't reorder when user is navigating the list or search box
        focused = app.screen.focused
        if focused is not None:
            focused_id = getattr(focused, "id", None)
            if focused_id == "search":
                return
            for ancestor in focused.ancestors:
                if getattr(ancestor, "id", None) == "chat_list":
                    return

        pinned_order = {
            k: idx for idx, k in enumerate(app.storage.get_pinned_chats())
        }

        def _sort_key(c: ChatInfo) -> tuple:
            return chat_logic.chat_sort_key(c, app.storage, pinned_order)

        my_sk = _sort_key(target_chat)

        # Find section boundaries (delimited by None separators / pending chats)
        section_start = target_index
        while section_start > 0:
            prev = rendered[section_start - 1]
            if prev is None:
                break
            pk = app.storage.chat_key(prev.chat_type, prev.chat_id)
            if pk in app.state.pending_chat_keys:
                break
            section_start -= 1

        section_end = target_index
        while section_end < len(rendered) - 1:
            nxt = rendered[section_end + 1]
            if nxt is None:
                break
            section_end += 1

        # Find the correct position: first index where sort_key > my_sk
        new_pos = section_end + 1  # default: end of section
        for i in range(section_start, section_end + 1):
            c = rendered[i]
            if c is None:
                continue
            if c.chat_type == chat_type and c.chat_id == chat_id:
                continue
            if _sort_key(c) > my_sk:
                new_pos = i
                break

        # Compute insert position in rendered_chats after pop
        insert_at = new_pos - 1 if new_pos > target_index else new_pos
        if insert_at == target_index:
            return  # No position change

        # Update rendered_chats
        with app._state_lock:
            r = app.state.rendered_chats
            chat_obj = r.pop(target_index)
            r.insert(insert_at, chat_obj)

        # Move DOM element surgically (no full rebuild → no flicker)
        if new_pos >= len(list_view.children):
            list_view.move_child(target_index, after=len(list_view.children) - 1)
        else:
            list_view.move_child(target_index, before=new_pos)
