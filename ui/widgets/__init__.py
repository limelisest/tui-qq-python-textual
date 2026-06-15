"""Custom Textual widgets.

Importing from this package re-exports the public widget classes so callers
can do ``from ui.widgets import MessageLog`` regardless of where a widget
lives internally.
"""

from ui.widgets.message_log import MessageLog

__all__ = ["MessageLog"]
