"""Tests for ui.navigation — pure pane-index computation."""

from __future__ import annotations

from typing import Optional
from unittest import TestCase

from ui.navigation import NavigationState, compute_pane_index_in_direction
from ui.state import ChatPaneState


def _panes(count: int) -> list[ChatPaneState]:
    return [ChatPaneState(uid=i + 1) for i in range(count)]


class NavigationStateTests(TestCase):
    def test_default_layer_is_top(self) -> None:
        ns = NavigationState()
        self.assertEqual(ns.layer, "top")

    def test_default_top_target_is_none(self) -> None:
        ns = NavigationState()
        self.assertIsNone(ns.top_target_pane_uid)

    def test_default_chat_list_on_search_is_false(self) -> None:
        ns = NavigationState()
        self.assertFalse(ns.chat_list_on_search)


class ComputePaneIndex2PaneVertical(TestCase):
    """Vertical layout (up/down) with 2 panes: index 1 → 2 → 1."""

    def setUp(self) -> None:
        self.panes = _panes(2)

    def test_single_pane_returns_none(self) -> None:
        result = compute_pane_index_in_direction(
            _panes(1), 1, split_layout_horizontal=False, direction="down"
        )
        self.assertIsNone(result)

    def test_vertical_down_from_1(self) -> None:
        result = compute_pane_index_in_direction(
            self.panes, 1, split_layout_horizontal=False, direction="down"
        )
        self.assertEqual(result, 2)

    def test_vertical_up_from_2(self) -> None:
        result = compute_pane_index_in_direction(
            self.panes, 2, split_layout_horizontal=False, direction="up"
        )
        self.assertEqual(result, 1)

    def test_vertical_down_wraps(self) -> None:
        result = compute_pane_index_in_direction(
            self.panes, 2, split_layout_horizontal=False, direction="down"
        )
        self.assertEqual(result, 1)

    def test_vertical_left_returns_none(self) -> None:
        result = compute_pane_index_in_direction(
            self.panes, 1, split_layout_horizontal=False, direction="left"
        )
        self.assertIsNone(result)

    def test_vertical_right_returns_none(self) -> None:
        result = compute_pane_index_in_direction(
            self.panes, 1, split_layout_horizontal=False, direction="right"
        )
        self.assertIsNone(result)


class ComputePaneIndex2PaneHorizontal(TestCase):
    """Horizontal layout (left/right) with 2 panes: index 1 → 2 → 1."""

    def setUp(self) -> None:
        self.panes = _panes(2)

    def test_horizontal_right(self) -> None:
        result = compute_pane_index_in_direction(
            self.panes, 1, split_layout_horizontal=True, direction="right"
        )
        self.assertEqual(result, 2)

    def test_horizontal_left(self) -> None:
        result = compute_pane_index_in_direction(
            self.panes, 2, split_layout_horizontal=True, direction="left"
        )
        self.assertEqual(result, 1)

    def test_horizontal_up_returns_none(self) -> None:
        result = compute_pane_index_in_direction(
            self.panes, 1, split_layout_horizontal=True, direction="up"
        )
        self.assertIsNone(result)

    def test_horizontal_down_returns_none(self) -> None:
        result = compute_pane_index_in_direction(
            self.panes, 1, split_layout_horizontal=True, direction="down"
        )
        self.assertIsNone(result)


class ComputePaneIndex3PaneVertical(TestCase):
    def setUp(self) -> None:
        self.panes = _panes(3)

    def test_vertical_down_1_to_2(self) -> None:
        result = compute_pane_index_in_direction(
            self.panes, 1, split_layout_horizontal=False, direction="down"
        )
        self.assertEqual(result, 2)

    def test_vertical_down_3_wraps_to_1(self) -> None:
        result = compute_pane_index_in_direction(
            self.panes, 3, split_layout_horizontal=False, direction="down"
        )
        self.assertEqual(result, 1)

    def test_vertical_up_2_to_1(self) -> None:
        result = compute_pane_index_in_direction(
            self.panes, 2, split_layout_horizontal=False, direction="up"
        )
        self.assertEqual(result, 1)

    def test_vertical_left_returns_none(self) -> None:
        result = compute_pane_index_in_direction(
            self.panes, 2, split_layout_horizontal=False, direction="left"
        )
        self.assertIsNone(result)


class ComputePaneIndex4Pane(TestCase):
    """4-pane grid (2×2) — arrow keys move in a 2D grid."""

    def setUp(self) -> None:
        self.panes = _panes(4)

    def _result(self, current_uid: int, direction: str) -> Optional[int]:
        return compute_pane_index_in_direction(
            self.panes, current_uid, split_layout_horizontal=False, direction=direction
        )

    def test_left_from_top_left(self) -> None:
        self.assertEqual(self._result(1, "left"), 2)

    def test_right_from_top_left(self) -> None:
        self.assertEqual(self._result(1, "right"), 2)

    def test_up_from_top_left(self) -> None:
        self.assertEqual(self._result(1, "up"), 3)

    def test_down_from_top_left(self) -> None:
        self.assertEqual(self._result(1, "down"), 3)

    def test_left_from_top_right(self) -> None:
        self.assertEqual(self._result(2, "left"), 1)

    def test_right_from_top_right(self) -> None:
        self.assertEqual(self._result(2, "right"), 1)

    def test_down_from_top_right_to_bottom_right(self) -> None:
        self.assertEqual(self._result(2, "down"), 4)

    def test_up_from_bottom_left_to_top_left(self) -> None:
        self.assertEqual(self._result(3, "up"), 1)

    def test_left_from_bottom_left(self) -> None:
        self.assertEqual(self._result(3, "left"), 4)

    def test_down_from_bottom_right_wraps_to_top_right(self) -> None:
        self.assertEqual(self._result(4, "down"), 2)

    def test_right_from_bottom_right_wraps_to_bottom_left(self) -> None:
        self.assertEqual(self._result(4, "right"), 3)

    def test_unknown_direction_returns_none(self) -> None:
        self.assertIsNone(self._result(1, "diagonal"))


class ComputePaneIndexUnmatchedUid(TestCase):
    """When the given UID is not in the pane list, default to index 0."""

    def test_unmatched_uid_uses_index_0(self) -> None:
        panes = _panes(2)
        result = compute_pane_index_in_direction(
            panes, 99, split_layout_horizontal=False, direction="down"
        )
        self.assertEqual(result, 2)

    def test_none_uid_uses_index_0(self) -> None:
        panes = _panes(2)
        result = compute_pane_index_in_direction(
            panes, None, split_layout_horizontal=False, direction="down"
        )
        self.assertEqual(result, 2)
