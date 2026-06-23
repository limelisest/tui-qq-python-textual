from unittest import TestCase

from ui.controllers.sidebar import SidebarController
from ui.sidebar import SidebarState


class _FakeSidebar:
    def __init__(self) -> None:
        self.display = True


class _FakeButton:
    def __init__(self) -> None:
        self.label = ""
        self.tooltip = ""
        self.focused = False

    def focus(self) -> None:
        self.focused = True


class _FakePaneController:
    def __init__(self) -> None:
        self.scroll_calls = 0

    def scroll_auto_panes(self) -> None:
        self.scroll_calls += 1


class _FakeApp:
    def __init__(self) -> None:
        self.sidebar = _FakeSidebar()
        self.button = _FakeButton()
        self.state = type("State", (), {"sidebar_state": SidebarState()})()
        self._pane_ctrl = _FakePaneController()
        self.focused = None

    def query_one(self, selector: str, widget_type=None):
        if selector == "#sidebar":
            return self.sidebar
        if selector == "#sidebar_toggle_btn":
            return self.button
        raise AssertionError(f"unexpected query: {selector}")


class SidebarControllerTests(TestCase):
    def test_show_sidebar_triggers_auto_scroll_once(self) -> None:
        app = _FakeApp()
        controller = SidebarController(app)

        controller.set_sidebar_visible(True)

        self.assertTrue(app.sidebar.display)
        self.assertIsNone(app.state.sidebar_state.hidden_by)
        self.assertEqual(app.button.label, "<")
        self.assertEqual(app._pane_ctrl.scroll_calls, 1)

    def test_hide_sidebar_does_not_trigger_auto_scroll(self) -> None:
        app = _FakeApp()
        controller = SidebarController(app)

        controller.set_sidebar_visible(False, "manual")

        self.assertFalse(app.sidebar.display)
        self.assertEqual(app.state.sidebar_state.hidden_by, "manual")
        self.assertEqual(app.button.label, ">")
        self.assertEqual(app._pane_ctrl.scroll_calls, 0)
