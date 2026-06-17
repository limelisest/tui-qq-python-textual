"""Tests for ui.sidebar — pure threshold and visibility logic."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase

from ui.sidebar import (
    SidebarState,
    has_empty_pane,
    is_sidebar_narrow,
    sidebar_auto_hide_column_threshold,
    sidebar_auto_hide_pixel_threshold,
)
from ui.state import ChatPaneState


def _pane(selected: bool = True) -> ChatPaneState:
    from models import ChatInfo
    if selected:
        return ChatPaneState(uid=1, selected_chat=ChatInfo(chat_id=1, name="test", chat_type="private"))
    return ChatPaneState(uid=1)


class SidebarStateTests(TestCase):
    def test_defaults(self) -> None:
        ss = SidebarState()
        self.assertIsNone(ss.hidden_by)
        self.assertFalse(ss.auto_paused)
        self.assertIsNone(ss.tab_restore_reason)
        self.assertFalse(ss.tab_restore_auto_paused)


class PixelThresholdTests(TestCase):
    def test_single_pane(self) -> None:
        self.assertEqual(sidebar_auto_hide_pixel_threshold(1), 600)

    def test_two_panes_vertical(self) -> None:
        self.assertEqual(sidebar_auto_hide_pixel_threshold(2, split_layout_horizontal=False), 700)

    def test_two_panes_horizontal(self) -> None:
        self.assertEqual(sidebar_auto_hide_pixel_threshold(2, split_layout_horizontal=True), 800)

    def test_three_panes_vertical(self) -> None:
        self.assertEqual(sidebar_auto_hide_pixel_threshold(3, split_layout_horizontal=False), 700)

    def test_three_panes_horizontal(self) -> None:
        self.assertEqual(sidebar_auto_hide_pixel_threshold(3, split_layout_horizontal=True), 1000)

    def test_four_panes(self) -> None:
        self.assertEqual(sidebar_auto_hide_pixel_threshold(4), 800)
        self.assertEqual(sidebar_auto_hide_pixel_threshold(4, split_layout_horizontal=True), 800)

    def test_above_max_count_default(self) -> None:
        self.assertEqual(sidebar_auto_hide_pixel_threshold(8), 700)


class ColumnThresholdTests(TestCase):
    def test_single_pane(self) -> None:
        self.assertEqual(sidebar_auto_hide_column_threshold(1), 76)

    def test_two_panes_vertical(self) -> None:
        self.assertEqual(sidebar_auto_hide_column_threshold(2, split_layout_horizontal=False), 88)

    def test_two_panes_horizontal(self) -> None:
        self.assertEqual(sidebar_auto_hide_column_threshold(2, split_layout_horizontal=True), 101)

    def test_three_panes_vertical(self) -> None:
        self.assertEqual(sidebar_auto_hide_column_threshold(3, split_layout_horizontal=False), 88)

    def test_three_panes_horizontal(self) -> None:
        self.assertEqual(sidebar_auto_hide_column_threshold(3, split_layout_horizontal=True), 126)

    def test_four_panes(self) -> None:
        self.assertEqual(sidebar_auto_hide_column_threshold(4), 101)
        self.assertEqual(sidebar_auto_hide_column_threshold(4, split_layout_horizontal=True), 101)

    def test_above_max_count_default(self) -> None:
        self.assertEqual(sidebar_auto_hide_column_threshold(8), 88)


class IsSidebarNarrowTests(TestCase):
    """is_sidebar_narrow uses pixel_size first, falls back to cell size."""

    # --- Two panes vertical (default threshold 700) ---

    def test_pixel_below_threshold(self) -> None:
        pixel = SimpleNamespace(width=600)
        self.assertTrue(is_sidebar_narrow(None, pixel, 2))

    def test_pixel_above_threshold(self) -> None:
        pixel = SimpleNamespace(width=800)
        self.assertFalse(is_sidebar_narrow(None, pixel, 2))

    def test_pixel_at_threshold_returns_false(self) -> None:
        pixel = SimpleNamespace(width=700)
        self.assertFalse(is_sidebar_narrow(None, pixel, 2))

    # --- Single pane (threshold 600) ---

    def test_single_pane_pixel_narrow(self) -> None:
        pixel = SimpleNamespace(width=550)
        self.assertTrue(is_sidebar_narrow(None, pixel, 1))

    def test_single_pane_pixel_not_narrow(self) -> None:
        pixel = SimpleNamespace(width=650)
        self.assertFalse(is_sidebar_narrow(None, pixel, 1))

    # --- Two panes horizontal (threshold 800) ---

    def test_two_horizontal_pixel_narrow(self) -> None:
        pixel = SimpleNamespace(width=750)
        self.assertTrue(is_sidebar_narrow(None, pixel, 2, split_layout_horizontal=True))

    def test_two_horizontal_pixel_not_narrow(self) -> None:
        pixel = SimpleNamespace(width=850)
        self.assertFalse(is_sidebar_narrow(None, pixel, 2, split_layout_horizontal=True))

    # --- Three panes horizontal (threshold 1000) ---

    def test_three_horizontal_pixel_narrow(self) -> None:
        pixel = SimpleNamespace(width=900)
        self.assertTrue(is_sidebar_narrow(None, pixel, 3, split_layout_horizontal=True))

    def test_three_horizontal_pixel_not_narrow(self) -> None:
        pixel = SimpleNamespace(width=1050)
        self.assertFalse(is_sidebar_narrow(None, pixel, 3, split_layout_horizontal=True))

    # --- Four panes (threshold 800) ---

    def test_four_pane_pixel_narrow(self) -> None:
        pixel = SimpleNamespace(width=750)
        self.assertTrue(is_sidebar_narrow(None, pixel, 4))

    def test_four_pane_pixel_not_narrow(self) -> None:
        pixel = SimpleNamespace(width=850)
        self.assertFalse(is_sidebar_narrow(None, pixel, 4))

    # --- Fallback to cell columns ---

    def test_pixel_zero_uses_fallback(self) -> None:
        pixel = SimpleNamespace(width=0)
        cell = SimpleNamespace(width=100)
        self.assertFalse(is_sidebar_narrow(cell, pixel, 2))

    def test_cell_fallback(self) -> None:
        cell = SimpleNamespace(width=70)
        self.assertTrue(is_sidebar_narrow(cell, None, 2))

    def test_cell_not_narrow(self) -> None:
        cell = SimpleNamespace(width=100)
        self.assertFalse(is_sidebar_narrow(cell, None, 2))

    def test_both_none_returns_false(self) -> None:
        self.assertFalse(is_sidebar_narrow(None, None, 2))

    # --- Cell fallback with non-default thresholds ---

    def test_single_pane_cell_narrow(self) -> None:
        cell = SimpleNamespace(width=70)
        self.assertTrue(is_sidebar_narrow(cell, None, 1))

    def test_two_horizontal_cell_narrow(self) -> None:
        cell = SimpleNamespace(width=95)
        self.assertTrue(is_sidebar_narrow(cell, None, 2, split_layout_horizontal=True))

    def test_three_horizontal_cell_narrow(self) -> None:
        cell = SimpleNamespace(width=120)
        self.assertTrue(is_sidebar_narrow(cell, None, 3, split_layout_horizontal=True))

    def test_four_pane_cell_threshold(self) -> None:
        cell = SimpleNamespace(width=95)
        self.assertTrue(is_sidebar_narrow(cell, None, 4))

    def test_four_pane_cell_not_narrow(self) -> None:
        cell = SimpleNamespace(width=110)
        self.assertFalse(is_sidebar_narrow(cell, None, 4))


class HasEmptyPaneTests(TestCase):
    def test_all_selected_returns_false(self) -> None:
        panes = [_pane(True), _pane(True)]
        self.assertFalse(has_empty_pane(panes))

    def test_one_empty_returns_true(self) -> None:
        panes = [_pane(True), _pane(False)]
        self.assertTrue(has_empty_pane(panes))

    def test_all_empty_returns_true(self) -> None:
        panes = [_pane(False), _pane(False)]
        self.assertTrue(has_empty_pane(panes))

    def test_empty_list_returns_false(self) -> None:
        self.assertFalse(has_empty_pane([]))
