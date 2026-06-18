from types import SimpleNamespace
from unittest import TestCase

from models import ChatInfo
from ui.controllers.navigation import NavigationController
from ui.navigation import NavigationState
from ui.state import ChatPaneState


class _FakeSidebar:
    def __init__(self) -> None:
        self.removed: list[str] = []

    def remove_class(self, name: str) -> None:
        self.removed.append(name)


class _FakeInput:
    disabled = False

    def __init__(self) -> None:
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

    def message_input_or_none(self, pane=None):
        return self.input

    def pane_input_visible(self, pane) -> bool:
        return True


class _FakeSidebarController:
    def __init__(self) -> None:
        self.apply_calls = 0

    def apply_sidebar_auto_visibility(self) -> None:
        self.apply_calls += 1


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
        )
        self._pane_ctrl = _FakePaneController()
        self._chat_list_ctrl = _FakeChatListController()
        self._msg_ctrl = _FakeMessageController()
        self._sidebar_ctrl = _FakeSidebarController()
        self.screen = _FakeScreen()
        self.sidebar = _FakeSidebar()
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
