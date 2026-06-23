from types import SimpleNamespace
from unittest import TestCase

from models import ChatInfo
from ui.controllers.navigation import NavigationController
from ui.navigation import NavigationState
from ui.sidebar import SidebarState
from ui.state import ChatPaneState


class _FakeSidebar:
    def __init__(self) -> None:
        self.removed: list[str] = []

    def remove_class(self, name: str) -> None:
        self.removed.append(name)


class _FakeInput:
    disabled = False

    def __init__(self, widget_id: str | None = None) -> None:
        self.id = widget_id
        self.focused = False

    def focus(self) -> None:
        self.focused = True


class _FakePaneController:
    def __init__(self) -> None:
        self.input_owner = None
        self.refresh_calls = 0
        self.hide_calls = 0

    def hide_all_message_inputs(self) -> None:
        self.hide_calls += 1

    def refresh_pane_active_classes(self) -> None:
        self.refresh_calls += 1

    def set_input_owner_pane(self, pane, scroll_if_auto: bool = True) -> None:
        self.input_owner = pane


class _FakeChatListController:
    def __init__(self) -> None:
        self.search_selected: list[bool] = []
        self.sync_calls = 0

    def set_search_nav_selected(self, selected: bool) -> None:
        self.search_selected.append(selected)

    def schedule_chat_list_selection_sync(self, scroll: bool = True) -> None:
        self.sync_calls += 1


class _FakeMessageController:
    def __init__(self) -> None:
        self.input = _FakeInput()
        self.hidden = []
        self.force_scrolls = []

    def message_input_or_none(self, pane=None):
        return self.input

    def pane_input_visible(self, pane) -> bool:
        return True

    def hide_scroll_bottom_btn(self, pane=None) -> None:
        self.hidden.append(pane)

    def force_scroll_end(self, pane_uid=None) -> None:
        self.force_scrolls.append(pane_uid)


class _FakeSidebarController:
    def __init__(self) -> None:
        self.apply_calls = 0
        self.visible_calls = []

    def apply_sidebar_auto_visibility(self) -> None:
        self.apply_calls += 1

    def set_sidebar_visible(self, visible: bool, reason=None) -> None:
        self.visible_calls.append((visible, reason))


class _FakeScreen:
    def __init__(self) -> None:
        self.focus = None

    def set_focus(self, value) -> None:
        self.focus = value


class _FakeApp:
    def __init__(self) -> None:
        chat = ChatInfo(chat_id=1001, name="chat", chat_type="private")
        self.pane = ChatPaneState(uid=1, selected_chat=chat)
        self.state = SimpleNamespace(
            panes=[self.pane],
            active_pane_uid=1,
            input_owner_pane_uid=None,
            navigation=NavigationState(),
            pending_pane_focus_uid=None,
            sidebar_state=SidebarState(),
        )
        self._pane_ctrl = _FakePaneController()
        self._chat_list_ctrl = _FakeChatListController()
        self._msg_ctrl = _FakeMessageController()
        self._sidebar_ctrl = _FakeSidebarController()
        self.screen = _FakeScreen()
        self.sidebar = _FakeSidebar()
        self.search = _FakeInput("search")
        self.after_refresh = []
        self.timers = []
        self.title_texts: list[str] = []

    def _active_pane(self):
        return self.pane

    def _pane_by_uid(self, uid: int):
        return self.pane if uid == self.pane.uid else None

    def _set_app_title_text(self, text: str) -> None:
        self.title_texts.append(text)

    def query_one(self, selector: str, widget_type=None):
        if selector == "#sidebar":
            return self.sidebar
        if selector == "#search":
            return self.search
        raise AssertionError(f"unexpected query: {selector}")

    def call_after_refresh(self, callback) -> None:
        self.after_refresh.append(callback)

    def set_timer(self, delay: float, callback) -> None:
        self.timers.append((delay, callback))


class NavigationControllerTests(TestCase):
    def test_enter_pane_after_refresh_switches_to_pane_layer(self) -> None:
        app = _FakeApp()
        controller = NavigationController(app)

        controller.enter_pane_layer_after_refresh(app.pane)
        self.assertEqual(app.state.pending_pane_focus_uid, app.pane.uid)

        app.after_refresh[0]()

        self.assertEqual(app.state.navigation.layer, "pane")
        self.assertEqual(app.state.navigation.top_target_pane_uid, app.pane.uid)
        self.assertIs(app._pane_ctrl.input_owner, app.pane)
        self.assertTrue(app._msg_ctrl.input.focused)
        self.assertIn("top_selected", app.sidebar.removed)

    def test_enter_pane_layer_syncs_chat_list_selection(self) -> None:
        app = _FakeApp()
        controller = NavigationController(app)

        controller.enter_pane_layer(app.pane, focus_input=False)

        self.assertEqual(app.state.navigation.layer, "pane")
        self.assertEqual(app._chat_list_ctrl.sync_calls, 1)

    def test_scroll_bottom_only_runs_in_pane_layer(self) -> None:
        app = _FakeApp()
        controller = NavigationController(app)

        app.state.navigation.layer = "chat_list"
        controller.action_scroll_bottom()
        self.assertEqual(app._msg_ctrl.force_scrolls, [])

        app.state.navigation.layer = "pane"
        app.pane.auto_scroll = False
        controller.action_scroll_bottom()

        self.assertTrue(app.pane.auto_scroll)
        self.assertEqual(app._msg_ctrl.hidden, [app.pane])
        self.assertEqual(app._msg_ctrl.force_scrolls, [app.pane.uid])

    def test_scroll_bottom_ignores_empty_pane(self) -> None:
        app = _FakeApp()
        app.pane.selected_chat = None
        app.state.navigation.layer = "pane"
        controller = NavigationController(app)

        controller.action_scroll_bottom()

        self.assertEqual(app._msg_ctrl.force_scrolls, [])

    def test_focus_chat_list_area_focuses_search_for_keyboard_filtering(self) -> None:
        app = _FakeApp()
        app.state.navigation.layer = "pane"
        app.state.navigation.top_target_pane_uid = app.pane.uid
        controller = NavigationController(app)

        controller.focus_chat_list_area()

        self.assertEqual(app._sidebar_ctrl.visible_calls, [(True, None)])
        self.assertEqual(app.state.navigation.layer, "search")
        self.assertIsNone(app.state.navigation.top_target_pane_uid)
        self.assertTrue(app.state.navigation.chat_list_on_search)
        self.assertTrue(app.search.focused)
