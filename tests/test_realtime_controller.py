from types import SimpleNamespace
from unittest import TestCase

from models import ChatInfo
from ui.controllers.realtime import RealtimeController
from ui.state import AppState


class _FakeStorage:
    @staticmethod
    def chat_key(chat_type: str, chat_id: int) -> str:
        return f"{chat_type}_{chat_id}"

    def __init__(self) -> None:
        self.messages = []
        self.activities = []

    def add_message(self, chat_type: str, chat_id: int, message) -> None:
        self.messages.append((chat_type, chat_id, message))

    def update_last_activity(self, chat_type: str, chat_id: int) -> None:
        self.activities.append((chat_type, chat_id))


class _FakeMessageController:
    def _at_resolver(self, chat_type: str, chat_id: int):
        return lambda qq: f"@{qq}"

    def trim_pane_messages(self, pane) -> int:
        return 0

    def message_log_or_none(self, pane=None):
        return None

    def update_reply_info(self, pane=None) -> None:
        pass


class _FakeChatListController:
    def __init__(self) -> None:
        self.render_calls = 0
        self.refresh_calls = []

    def render_chat_list(self) -> None:
        self.render_calls += 1

    def refresh_chat_list_item(self, chat_type: str, chat_id: int) -> None:
        self.refresh_calls.append((chat_type, chat_id))


class _FakeApp:
    def __init__(self) -> None:
        self.state = AppState()
        self.ob = SimpleNamespace(self_id=10000)
        self.storage = _FakeStorage()
        self._msg_ctrl = _FakeMessageController()
        self._chat_list_ctrl = _FakeChatListController()
        self.dirty_calls = 0
        self.touches = []

    def _mark_storage_dirty(self) -> None:
        self.dirty_calls += 1

    def _touch_chat(self, chat_type: str, chat_id: int, timestamp) -> None:
        self.touches.append((chat_type, chat_id, timestamp))

    def _active_pane(self):
        return self.state.active_pane()


def _private_event(user_id: int = 20000) -> dict:
    return {
        "post_type": "message",
        "message_type": "private",
        "user_id": user_id,
        "message": [{"type": "text", "data": {"text": "hello"}}],
        "message_id": 1,
        "time": 10,
    }


def _group_event(message=None) -> dict:
    return {
        "post_type": "message",
        "message_type": "group",
        "group_id": 30000,
        "user_id": 20000,
        "message": message
        if message is not None
        else [{"type": "text", "data": {"text": "hello"}}],
        "message_id": 2,
        "time": 11,
    }


class RealtimeControllerPendingTests(TestCase):
    def test_private_message_marks_pending_when_chat_not_open(self) -> None:
        app = _FakeApp()
        controller = RealtimeController(app)

        controller.handle_event(_private_event())

        self.assertEqual(app.state.pending_chat_keys, ["private_20000"])
        self.assertEqual(app._chat_list_ctrl.render_calls, 1)
        self.assertEqual(app._chat_list_ctrl.refresh_calls, [])

    def test_group_at_self_marks_pending_when_chat_not_open(self) -> None:
        app = _FakeApp()
        controller = RealtimeController(app)

        controller.handle_event(
            _group_event(
                [
                    {"type": "at", "data": {"qq": "10000"}},
                    {"type": "text", "data": {"text": " ping"}},
                ]
            )
        )

        self.assertEqual(app.state.pending_chat_keys, ["group_30000"])
        self.assertEqual(app._chat_list_ctrl.render_calls, 1)

    def test_group_without_at_self_does_not_mark_pending(self) -> None:
        app = _FakeApp()
        controller = RealtimeController(app)

        controller.handle_event(_group_event())

        self.assertEqual(app.state.pending_chat_keys, [])
        self.assertEqual(app._chat_list_ctrl.render_calls, 0)
        self.assertEqual(app._chat_list_ctrl.refresh_calls, [("group", 30000)])

    def test_open_chat_does_not_mark_pending(self) -> None:
        app = _FakeApp()
        app.state.panes[0].selected_chat = ChatInfo(
            chat_id=20000, name="friend", chat_type="private"
        )
        controller = RealtimeController(app)

        controller.handle_event(_private_event())

        self.assertEqual(app.state.pending_chat_keys, [])
        self.assertEqual(app._chat_list_ctrl.render_calls, 0)
        self.assertEqual(app._chat_list_ctrl.refresh_calls, [("private", 20000)])
