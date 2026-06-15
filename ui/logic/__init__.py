"""Pure, widget-free application logic.

Functions here never touch Textual widgets (no ``query_one``, no ``mount``,
no ``self``), so they are easy to unit-test and reuse. They take plain data
(chat lists, storage handles, search caches) and return plain data.
"""

from ui.logic import chat_logic, message_logic

__all__ = ["chat_logic", "message_logic"]
