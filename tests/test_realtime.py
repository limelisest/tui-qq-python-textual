"""Tests for pure realtime event parsing helpers."""

from __future__ import annotations

from unittest import TestCase

from ui.logic.message_logic import RealtimeEventUpdate, parse_realtime_event


class ParseRealtimeEventTests(TestCase):
    def test_non_message_event_returns_none(self) -> None:
        event = {"post_type": "notice", "notice_type": "group_increase"}
        result = parse_realtime_event(event)
        self.assertIsNone(result)

    def test_group_message_parses(self) -> None:
        event = {
            "post_type": "message",
            "message_type": "group",
            "group_id": 123456,
            "user_id": 789012,
            "message": [{"type": "text", "data": {"text": "hello"}}],
            "message_id": 42,
            "time": 1000000,
        }
        result = parse_realtime_event(event)
        assert result is not None
        self.assertEqual(result.chat_type, "group")
        self.assertEqual(result.chat_id, 123456)
        self.assertEqual(result.message.content, "hello")

    def test_private_message_parses(self) -> None:
        event = {
            "post_type": "message",
            "message_type": "private",
            "user_id": 789012,
            "message": [{"type": "text", "data": {"text": "hi"}}],
            "message_id": 43,
            "time": 1000001,
        }
        result = parse_realtime_event(event)
        assert result is not None
        self.assertEqual(result.chat_type, "private")
        self.assertEqual(result.chat_id, 789012)
        self.assertEqual(result.message.content, "hi")

    def test_missing_chat_id_returns_none(self) -> None:
        event = {
            "post_type": "message",
            "message_type": "group",
            "group_id": 0,
            "user_id": 0,
            "message": [],
            "message_id": 44,
            "time": 1000002,
        }
        result = parse_realtime_event(event)
        self.assertIsNone(result)

    def test_empty_event_returns_none(self) -> None:
        result = parse_realtime_event({})
        self.assertIsNone(result)
