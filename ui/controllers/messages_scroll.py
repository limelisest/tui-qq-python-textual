"""Message scroll detection and button visibility mixin."""

from __future__ import annotations

from typing import Optional

from textual.widgets import Button

from ui.state import ChatPaneState


class MessageScrollMixin:
    """Mixin providing scroll detection and scroll-bottom button methods.

    Requires ``self._app`` set by the concrete class, and methods from
    ``MessageRendererMixin`` (``message_log_or_none``).
    """

    def _scroll_button_or_none(
        self, pane: Optional[ChatPaneState] = None
    ) -> Optional[Button]:
        pane = pane or self._app.state.active_pane()
        try:
            return self._pane_widget(pane, "scroll_bottom_btn", Button)
        except Exception:
            return None

    def show_scroll_bottom_btn(
        self, pane: Optional[ChatPaneState] = None
    ) -> None:
        btn = self._scroll_button_or_none(pane)
        if btn is not None and btn.visible is False:
            btn.visible = True

    def hide_scroll_bottom_btn(
        self, pane: Optional[ChatPaneState] = None
    ) -> None:
        btn = self._scroll_button_or_none(pane)
        if btn is not None and btn.visible is not False:
            btn.visible = False

    def force_scroll_end(self, pane_uid: Optional[int] = None) -> None:
        pane = self._app._pane_by_uid(pane_uid) if pane_uid is not None else self._app.state.active_pane()
        if pane is None:
            return
        log = self.message_log_or_none(pane)
        if log is not None:
            log.scroll_end_when_ready()

    def check_scroll(self) -> None:
        for pane in list(self._app.state.panes):
            log = self.message_log_or_none(pane)
            if log is None:
                continue
            cur_y = log.scroll_y
            max_y = log.max_scroll_y
            if max_y <= 0:
                pane.prev_scroll_y = 0
                continue

            if cur_y < pane.prev_scroll_y and pane.auto_scroll:
                pane.auto_scroll = False
                self.show_scroll_bottom_btn(pane)
            at_bottom = cur_y >= max_y - 1
            if at_bottom and not pane.auto_scroll:
                pane.auto_scroll = True
                self.hide_scroll_bottom_btn(pane)
            elif at_bottom:
                self.hide_scroll_bottom_btn(pane)

            pane.prev_scroll_y = cur_y
