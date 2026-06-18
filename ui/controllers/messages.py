"""Message rendering, input visibility and sending coordination (facade).

Extracted from ``QQChatApp``.  The controller owns per-pane message display
(log writing, scroll, reply-info), input visibility, and message submission.

This module is now a **facade** that inherits from focused sub-modules:

* :mod:`messages_renderer` — renderables, write, selection, reply info
* :mod:`messages_actions` — reply, plus-one, append, show
* :mod:`messages_input` — input visibility, start, submit
* :mod:`messages_scroll` — scroll checks, buttons

Public method names remain stable so existing ``app.py`` call sites still work.
"""

from __future__ import annotations

from ui.controllers.messages_actions import MessageActionsMixin
from ui.controllers.messages_input import MessageInputMixin
from ui.controllers.messages_renderer import MessageRendererMixin
from ui.controllers.messages_scroll import MessageScrollMixin


class MessageController(
    MessageRendererMixin,
    MessageActionsMixin,
    MessageInputMixin,
    MessageScrollMixin,
):
    """Facade that inherits message rendering, actions, input and scroll methods
    from the focused sub-modules.  All public methods from the original monolithic
    controller are preserved."""

    def __init__(self, app) -> None:
        self._app = app
