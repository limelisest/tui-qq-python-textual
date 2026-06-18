"""Controller classes that coordinate logic with widget operations.

Each controller takes a "host" ``QQChatApp`` reference and encapsulates a
focused slice of the App's widget-glue responsibilities. Controllers are not
pure (they call ``query_one`` / ``focus`` etc.), but they keep lifecycle,
navigation, sidebar visibility, realtime dispatch, panes, mouse handling,
chat-list rendering, and message rendering from collapsing into one App class.
``MessageController`` is a facade over focused message mixins.
"""
