import os

WS_URL = "ws://127.0.0.1:3001"
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CACHE_FILE = os.path.join(CACHE_DIR, "cache.json")
RECENT_CHATS_COUNT = 5
HISTORY_MESSAGE_COUNT = 50
