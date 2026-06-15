"""Service layer: network calls + payload parsing, returning clean dataclasses.

Services are called from the App's worker threads (never the Textual event
loop), so they keep the AGENTS.md "no network on the main thread" rule. They
own the fragile ``raw.get(...) or default`` parsing that used to be scattered
through ``tui.py``, so a malformed NapBot payload degrades to a safe default
here instead of crashing the UI.
"""

from ui.services import chat_service, message_service

__all__ = ["chat_service", "message_service"]
