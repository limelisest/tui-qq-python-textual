from unittest import TestCase

from models import ChatInfo
from ui.navigation import NavigationState
from ui.sidebar import SidebarState
from ui.state import AppState, ChatPaneState


class AppStateTests(TestCase):
    def test_defaults_create_single_empty_pane(self) -> None:
        state = AppState()

        self.assertEqual(len(state.panes), 1)
        self.assertIsInstance(state.panes[0], ChatPaneState)
        self.assertEqual(state.active_pane_uid, 1)
        self.assertEqual(state.next_pane_uid, 2)

    def test_default_nested_state_types(self) -> None:
        state = AppState()

        self.assertIsInstance(state.navigation, NavigationState)
        self.assertIsInstance(state.sidebar_state, SidebarState)

    def test_mutable_defaults_are_not_shared(self) -> None:
        first = AppState()
        second = AppState()

        first.chats.append(ChatInfo(chat_id=1, name="chat", chat_type="private"))
        first.panes.append(ChatPaneState(uid=2))
        first.friend_remarks[1] = "remark"

        self.assertEqual(second.chats, [])
        self.assertEqual([pane.uid for pane in second.panes], [1])
        self.assertEqual(second.friend_remarks, {})

    def test_active_pane_returns_matching_pane(self) -> None:
        state = AppState()
        state.panes.append(ChatPaneState(uid=2))
        state.active_pane_uid = 2

        self.assertIs(state.active_pane(), state.panes[1])

    def test_active_pane_falls_back_to_first_pane(self) -> None:
        state = AppState()
        state.panes.append(ChatPaneState(uid=2))
        state.active_pane_uid = 99

        self.assertIs(state.active_pane(), state.panes[0])
        self.assertEqual(state.active_pane_uid, state.panes[0].uid)

    def test_active_pane_recovers_empty_pane_list(self) -> None:
        state = AppState(panes=[])

        pane = state.active_pane()

        self.assertEqual(pane.uid, 1)
        self.assertEqual(state.active_pane_uid, 1)
        self.assertEqual([pane.uid for pane in state.panes], [1])
