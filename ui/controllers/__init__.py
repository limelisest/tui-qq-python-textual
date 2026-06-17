"""Controller classes that coordinate logic with widget operations.

Each controller takes a "host" ``QQChatApp`` reference and encapsulates a
focused slice of the App's widget-glue responsibilities.  Controllers are not
pure (they call ``query_one`` / ``focus`` etc.) but they keep the App class
from ballooning past 1000 lines.
"""
