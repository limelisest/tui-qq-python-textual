import threading
from types import SimpleNamespace
from unittest import TestCase

from models import ChatInfo
from ui.controllers.chat_list import ChatListController
from ui.state import AppState


class _FakeStorage:
    @staticmethod
    def chat_key(chat_type: str, chat_id: int) -> str:
        return f"{chat_type}_{chat_id}"

    def get_last_message(self, chat_type: str, chat_id: int):
        return None

    def get_pinned_chats(self):
        return []

    def get_recent_chats(self):
        return []

    def get_last_activity(self, chat_type: str, chat_id: int) -> float:
        return 0


class _FakeListView:
    def __init__(self) -> None:
        self.children = []
        self.index = 0

    def clear(self) -> None:
        self.children = []

    def append(self, item) -> None:
        self.children.append(item)

    def watch_index(self, old, new) -> None:
        pass


class _FakeApp:
    def __init__(self) -> None:
        self.state = AppState()
        self.state.chats = [
            ChatInfo(chat_id=1, name="normal", chat_type="private", last_time=1),
            ChatInfo(chat_id=2, name="pending", chat_type="private", last_time=2),
        ]
        self.state.pending_chat_keys = ["private_2"]
        self.storage = _FakeStorage()
        self._state_lock = threading.RLock()
        self.search = SimpleNamespace(value="")
        self.list_view = _FakeListView()
        self._preview_chat = None
        self._selected_chat = None
        self.after_refresh = []
        self.timers = []

    def query_one(self, selector: str, widget_type=None):
        if selector == "#search":
            return self.search
        if selector == "#chat_list":
            return self.list_view
        raise AssertionError(f"unexpected query: {selector}")

    def call_after_refresh(self, callback) -> None:
        self.after_refresh.append(callback)

    def set_timer(self, delay: float, callback) -> None:
        self.timers.append((delay, callback))


class ChatListControllerPendingTests(TestCase):
    def test_pending_chats_render_at_top(self) -> None:
        app = _FakeApp()
        controller = ChatListController(app)

        controller.render_chat_list()

        self.assertEqual(
            [
                None if chat is None else (chat.chat_type, chat.chat_id)
                for chat in app.state.rendered_chats
            ],
            [None, ("private", 2), None, ("private", 1)],
        )
        self.assertEqual(len(app.list_view.children), 4)
