from types import SimpleNamespace
from unittest import TestCase

from ui.controllers.mouse import MouseController
from ui.state import ChatPaneState


class _FakeMessageController:
    def __init__(self) -> None:
        self.cleared = []

    def clear_message_selection(self, pane: ChatPaneState) -> None:
        self.cleared.append(pane)
        pane.reply_index = -1


class _FakeApp:
    def __init__(self) -> None:
        self.panes = [ChatPaneState(uid=1), ChatPaneState(uid=2)]
        self.panes[0].reply_index = 0
        self.panes[1].reply_index = 1
        self.state = SimpleNamespace(panes=self.panes)
        self._msg_ctrl = _FakeMessageController()


class MouseControllerSelectionTests(TestCase):
    def test_non_action_click_clears_message_selection(self) -> None:
        app = _FakeApp()
        controller = MouseController(app)
        controller.message_action_from_mouse_event = lambda event: None

        controller.clear_message_selection_unless_action(SimpleNamespace())

        self.assertEqual(app._msg_ctrl.cleared, app.panes)
        self.assertEqual([pane.reply_index for pane in app.panes], [-1, -1])

    def test_message_action_click_keeps_message_selection(self) -> None:
        app = _FakeApp()
        controller = MouseController(app)
        controller.message_action_from_mouse_event = (
            lambda event: (app.panes[0], 0, "reply")
        )

        controller.clear_message_selection_unless_action(SimpleNamespace())

        self.assertEqual(app._msg_ctrl.cleared, [])
        self.assertEqual([pane.reply_index for pane in app.panes], [0, 1])
