from types import SimpleNamespace
from unittest import TestCase

from models import MessageData
from ui.controllers.messages import MessageController
from ui.state import ChatPaneState


def _message(index: int) -> MessageData:
    return MessageData(
        message_id=index,
        chat_id=1,
        chat_type="private",
        user_id=2,
        content=f"message {index}",
        time=index,
    )


class MessageControllerTrimTests(TestCase):
    def test_trim_pane_messages_keeps_latest_100(self) -> None:
        controller = MessageController(SimpleNamespace())
        pane = ChatPaneState(uid=1)
        pane.messages = [_message(index) for index in range(101)]

        removed = controller.trim_pane_messages(pane)

        self.assertEqual(removed, 1)
        self.assertEqual(len(pane.messages), 100)
        self.assertEqual(pane.messages[0].message_id, 1)
        self.assertEqual(pane.messages[-1].message_id, 100)
        self.assertEqual(pane.message_line_spans, [])

    def test_trim_pane_messages_adjusts_reply_index(self) -> None:
        controller = MessageController(SimpleNamespace())
        pane = ChatPaneState(uid=1)
        pane.messages = [_message(index) for index in range(105)]
        pane.reply_index = 10
        pane.message_action_index = 1

        controller.trim_pane_messages(pane)

        self.assertEqual(pane.reply_index, 5)
        self.assertEqual(pane.message_action_index, 1)

    def test_trim_pane_messages_clears_reply_when_target_removed(self) -> None:
        controller = MessageController(SimpleNamespace())
        pane = ChatPaneState(uid=1)
        pane.messages = [_message(index) for index in range(105)]
        pane.reply_index = 2
        pane.message_action_index = 1

        controller.trim_pane_messages(pane)

        self.assertEqual(pane.reply_index, -1)
        self.assertEqual(pane.message_action_index, 0)
