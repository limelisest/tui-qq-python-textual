"""Tests for split-pane controller state invariants."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase

from textual.css.query import NoMatches

from ui.controllers.panes import PaneController
from ui.navigation import NavigationState
from ui.sidebar import SidebarState
from ui.state import MAX_SPLIT_PANES, ChatPaneState


class _FakeButton:
    def __init__(self) -> None:
        self.disabled = False
        self.tooltip = ""


class _FakeGrid:
    def __init__(self) -> None:
        self.classes: set[str] = set()
        self.mounted: list[object] = []

    def add_class(self, name: str) -> None:
        self.classes.add(name)

    def remove_class(self, name: str) -> None:
        self.classes.discard(name)

    def mount(self, widget) -> None:
        self.mounted.append(widget)


class _FakeMessageController:
    def __init__(self) -> None:
        self.force_scroll_calls: list[int] = []

    def pane_input_visible(self, _pane: ChatPaneState) -> bool:
        return False

    def force_scroll_end(self, pane_uid: int) -> None:
        self.force_scroll_calls.append(pane_uid)


class _FakeChatListController:
    def __init__(self) -> None:
        self.sync_calls = 0
        self.render_calls = 0

    def schedule_chat_list_selection_sync(self, scroll: bool = True) -> None:
        self.sync_calls += 1

    def render_chat_list(self) -> None:
        self.render_calls += 1


class _FakeApp:
    def __init__(self) -> None:
        self.state = SimpleNamespace(
            panes=[ChatPaneState(uid=1)],
            active_pane_uid=1,
            input_owner_pane_uid=None,
            navigation=NavigationState(),
            next_pane_uid=2,
            split_layout_horizontal=False,
            sidebar_state=SidebarState(),
        )
        self._msg_ctrl = _FakeMessageController()
        self._chat_list_ctrl = _FakeChatListController()
        self.grid = _FakeGrid()
        self.add_btn = _FakeButton()
        self.layout_btn = _FakeButton()
        self.toasts: list[str] = []
        self.focus_chat_list_calls = 0
        self.sidebar_apply_calls = 0
        self.title_texts: list[str] = []
        self.after_refresh: list[object] = []
        self.timers: list[tuple[float, object]] = []

    def query_one(self, selector, _widget_type=None):
        if selector == "#pane_grid":
            return self.grid
        if selector == "#split_add_btn":
            return self.add_btn
        if selector == "#split_layout_btn":
            return self.layout_btn
        raise NoMatches()

    def call_after_refresh(self, callback) -> None:
        self.after_refresh.append(callback)

    def set_timer(self, delay: float, callback) -> None:
        self.timers.append((delay, callback))

    def _focus_chat_list_area(self) -> None:
        self.focus_chat_list_calls += 1

    def _apply_sidebar_auto_visibility(self) -> None:
        self.sidebar_apply_calls += 1

    def _show_toast(self, title: str, _body: str = "") -> None:
        self.toasts.append(title)

    def _set_app_title_text(self, text: str) -> None:
        self.title_texts.append(text)


class PaneControllerTests(TestCase):
    def test_add_pane_keeps_state_consistent(self) -> None:
        app = _FakeApp()
        controller = PaneController(app)

        controller.add_pane()

        self.assertEqual([pane.uid for pane in app.state.panes], [1, 2])
        self.assertEqual(app.state.active_pane_uid, 2)
        self.assertEqual(app.state.navigation.top_target_pane_uid, 2)
        self.assertEqual(app.state.next_pane_uid, 3)
        self.assertEqual(app.focus_chat_list_calls, 1)
        self.assertEqual(app.sidebar_apply_calls, 1)
        self.assertEqual(app._chat_list_ctrl.sync_calls, 1)
        self.assertIn("pane_count_2", app.grid.classes)
        self.assertEqual(len(app.grid.mounted), 1)

    def test_add_pane_stops_at_max(self) -> None:
        app = _FakeApp()
        app.state.panes = [ChatPaneState(uid=index) for index in range(1, 5)]
        app.state.active_pane_uid = 1
        app.state.next_pane_uid = 5
        controller = PaneController(app)

        controller.add_pane()

        self.assertEqual(len(app.state.panes), MAX_SPLIT_PANES)
        self.assertEqual(app.state.next_pane_uid, 5)
        self.assertEqual(app.toasts, ["最多 4 个分屏"])

    def test_close_pane_selects_neighbor_and_clears_input_owner(self) -> None:
        app = _FakeApp()
        app.state.panes = [
            ChatPaneState(uid=1),
            ChatPaneState(uid=2),
            ChatPaneState(uid=3),
        ]
        app.state.active_pane_uid = 2
        app.state.navigation.top_target_pane_uid = 2
        app.state.input_owner_pane_uid = 2
        controller = PaneController(app)

        controller.close_pane(app.state.panes[1])

        self.assertEqual([pane.uid for pane in app.state.panes], [1, 3])
        self.assertEqual(app.state.active_pane_uid, 3)
        self.assertEqual(app.state.navigation.top_target_pane_uid, 3)
        self.assertIsNone(app.state.input_owner_pane_uid)
        self.assertIn("pane_count_2", app.grid.classes)
        self.assertEqual(app.sidebar_apply_calls, 1)
        self.assertEqual(app._chat_list_ctrl.render_calls, 1)

    def test_close_last_pane_is_blocked(self) -> None:
        app = _FakeApp()
        controller = PaneController(app)

        controller.close_pane(app.state.panes[0])

        self.assertEqual([pane.uid for pane in app.state.panes], [1])
        self.assertEqual(app.toasts, ["至少保留 1 个分屏"])

    def test_toggle_layout_reapplies_sidebar_and_scrolls_auto_panes(self) -> None:
        app = _FakeApp()
        app.state.panes = [ChatPaneState(uid=1), ChatPaneState(uid=2)]
        app.state.panes[1].auto_scroll = False
        controller = PaneController(app)

        controller.toggle_split_layout()

        self.assertTrue(app.state.split_layout_horizontal)
        self.assertIn("pane_layout_horizontal", app.grid.classes)
        self.assertEqual(app.sidebar_apply_calls, 1)
        self.assertEqual(len(app.after_refresh), 1)
        self.assertEqual(len(app.timers), 2)
