"""Pane and split-layout management for ``QQChatApp``.

Extracted from ``ui/app.py`` so the App class focuses on coordination.
The controller takes an ``app`` reference (duck-typed to what it needs) and
delegates widget queries / state mutations back to the App.
"""

from __future__ import annotations

from typing import Optional

from textual import events
from textual.containers import Container, Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Button, Static

from ui.state import (
    MAX_SPLIT_PANES,
    ChatPaneState,
    pane_has_active_border,
    pane_selector,
    pane_title_text,
)
from ui.widgets.chat_pane import build_pane_container


class PaneController:
    """Manages split-pane widgets: lookup, lifecycle, layout classes."""

    def __init__(self, app) -> None:
        self._app = app

    # ── pane lookup ────────────────────────────────────────────────── #

    def pane_by_uid(self, uid: int) -> Optional[ChatPaneState]:
        return next((pane for pane in self._app._panes if pane.uid == uid), None)

    def active_pane(self) -> ChatPaneState:
        pane = self.pane_by_uid(self._app._active_pane_uid)
        if pane is not None:
            return pane
        self._app._active_pane_uid = self._app._panes[0].uid
        return self._app._panes[0]

    def pane_widget(self, pane: ChatPaneState, name: str, widget_type):
        return self._app.query_one(pane_selector(pane, name), widget_type)

    def pane_from_widget(self, widget) -> Optional[ChatPaneState]:
        node = widget
        while node is not None:
            widget_id = getattr(node, "id", "") or ""
            if widget_id.startswith("chat_pane_"):
                try:
                    uid = int(widget_id.removeprefix("chat_pane_"))
                except ValueError:
                    return None
                return self.pane_by_uid(uid)
            node = getattr(node, "parent", None)
        return None

    def pane_from_mouse_event(self, event: events.MouseEvent) -> Optional[ChatPaneState]:
        try:
            widget, _ = self._app.screen.get_widget_at(event.screen_x, event.screen_y)
        except Exception:
            return None
        return self.pane_from_widget(widget)

    # ── input owner ────────────────────────────────────────────────── #

    def set_input_owner_pane(
        self, pane: Optional[ChatPaneState], scroll_if_auto: bool = True
    ) -> None:
        old_uid = self._app._input_owner_pane_uid
        self._app._input_owner_pane_uid = pane.uid if pane is not None else None
        self.refresh_pane_active_classes()
        if (
            pane is not None
            and old_uid != pane.uid
            and scroll_if_auto
            and pane.auto_scroll
        ):
            self._app.call_after_refresh(
                lambda uid=pane.uid: self._app._msg_ctrl.force_scroll_end(uid)
            )
            self._app.set_timer(
                0.02, lambda uid=pane.uid: self._app._msg_ctrl.force_scroll_end(uid)
            )

    def hide_all_message_inputs(self) -> None:
        if self._app._input_owner_pane_uid is None:
            return
        self.set_input_owner_pane(None, scroll_if_auto=False)

    # ── active / display classes ───────────────────────────────────── #

    def refresh_pane_active_classes(self) -> None:
        for pane in self._app._panes:
            try:
                widget = self._app.query_one(f"#chat_pane_{pane.uid}", Vertical)
            except NoMatches:
                continue
            if pane_has_active_border(
                pane,
                self._app._navigation.layer,
                self._app._active_pane_uid,
                self._app._navigation.top_target_pane_uid,
            ):
                widget.add_class("active_pane")
            else:
                widget.remove_class("active_pane")
            try:
                input_row = self.pane_widget(pane, "input_row", Horizontal)
                input_row.display = self._app._msg_ctrl.pane_input_visible(pane)
            except NoMatches:
                pass

    def update_pane_titles(self) -> None:
        for pane in self._app._panes:
            try:
                self.pane_widget(pane, "title", Static).update(
                    pane_title_text(pane)
                )
            except NoMatches:
                pass
        self._app._set_app_title_text("")

    def update_pane_grid_class(self) -> None:
        try:
            grid = self._app.query_one("#pane_grid", Container)
        except NoMatches:
            return
        for count in range(1, MAX_SPLIT_PANES + 1):
            grid.remove_class(f"pane_count_{count}")
        grid.remove_class("pane_layout_horizontal")
        grid.add_class(f"pane_count_{len(self._app._panes)}")
        if self._app._split_layout_horizontal and len(self._app._panes) in (2, 3):
            grid.add_class("pane_layout_horizontal")

    def update_split_buttons(self) -> None:
        try:
            add_btn = self._app.query_one("#split_add_btn", Button)
        except NoMatches:
            return
        add_btn.disabled = len(self._app._panes) >= MAX_SPLIT_PANES
        add_btn.tooltip = "新增分屏" if not add_btn.disabled else "最多 4 个分屏"
        try:
            layout_btn = self._app.query_one("#split_layout_btn", Button)
            layout_btn.tooltip = (
                "纵向分屏布局"
                if self._app._split_layout_horizontal
                else "横向分屏布局"
            )
        except NoMatches:
            pass
        close_disabled = len(self._app._panes) <= 1
        for pane in self._app._panes:
            try:
                close_btn = self.pane_widget(pane, "close_btn", Button)
            except NoMatches:
                continue
            close_btn.disabled = close_disabled
            close_btn.tooltip = (
                "关闭当前分屏" if not close_disabled else "至少保留 1 个分屏"
            )

    # ── add / close / toggle ───────────────────────────────────────── #

    def add_pane(self) -> None:
        if len(self._app._panes) >= MAX_SPLIT_PANES:
            self._app._show_toast("最多 4 个分屏")
            return
        pane = ChatPaneState(uid=self._app._next_pane_uid)
        self._app._next_pane_uid += 1
        self._app._panes.append(pane)
        self._app._active_pane_uid = pane.uid
        self._app._navigation.top_target_pane_uid = pane.uid
        self._app.query_one("#pane_grid", Container).mount(
            build_pane_container(
                pane,
                self._app._navigation.layer,
                self._app._active_pane_uid,
                self._app._navigation.top_target_pane_uid,
                self._app._msg_ctrl.pane_input_visible(pane),
            )
        )
        self.update_pane_grid_class()
        self._app._focus_chat_list_area()
        self.update_pane_titles()
        self.update_split_buttons()
        self._app._apply_sidebar_auto_visibility()
        self._app._chat_list_ctrl.schedule_chat_list_selection_sync(scroll=True)

    def close_pane(self, pane: ChatPaneState) -> None:
        if len(self._app._panes) <= 1:
            self._app._show_toast("至少保留 1 个分屏")
            return
        if pane not in self._app._panes:
            return
        pane_index = self._app._panes.index(pane)
        self._app._panes.remove(pane)
        try:
            self._app.query_one(f"#chat_pane_{pane.uid}", Vertical).remove()
        except NoMatches:
            pass
        next_index = min(pane_index, len(self._app._panes) - 1)
        self._app._active_pane_uid = self._app._panes[next_index].uid
        if self._app._navigation.top_target_pane_uid == pane.uid:
            self._app._navigation.top_target_pane_uid = self._app._active_pane_uid
        if self._app._input_owner_pane_uid == pane.uid:
            self._app._input_owner_pane_uid = None
        self.update_pane_grid_class()
        self.refresh_pane_active_classes()
        self.update_pane_titles()
        self.update_split_buttons()
        self._app._apply_sidebar_auto_visibility()
        self._app._chat_list_ctrl.schedule_chat_list_selection_sync(scroll=True)

    def toggle_split_layout(self) -> None:
        self._app._split_layout_horizontal = not self._app._split_layout_horizontal
        self.update_pane_grid_class()
        self.update_split_buttons()
        self._app._apply_sidebar_auto_visibility()
        self.scroll_auto_panes()

    def scroll_auto_panes(self) -> None:
        for pane in self._app._panes:
            if pane.auto_scroll:
                self._app.call_after_refresh(
                    lambda uid=pane.uid: self._app._msg_ctrl.force_scroll_end(uid)
                )
                self._app.set_timer(
                    0.02, lambda uid=pane.uid: self._app._msg_ctrl.force_scroll_end(uid)
                )
                self._app.set_timer(
                    0.05, lambda uid=pane.uid: self._app._msg_ctrl.force_scroll_end(uid)
                )
