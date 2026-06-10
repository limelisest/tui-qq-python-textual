import json
import os


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

DEFAULT_CONFIG = {
    "ws_url": "ws://127.0.0.1:3001",
    "ws_token": "",
    "cache_dir": "data",
    "cache_file": "cache.json",
    "settings_file": "settings.json",
    "recent_chats_count": 5,
    "history_message_count": 50,
    "chat_list_render_limit": 300,
    "cache_group_members_on_open": False,
}


def _load_config() -> dict:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {**DEFAULT_CONFIG, **data}


def _resolve_path(path: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.join(BASE_DIR, path)


APP_CONFIG = _load_config()

WS_URL = str(APP_CONFIG["ws_url"])
WS_TOKEN = str(APP_CONFIG["ws_token"])
CACHE_DIR = _resolve_path(str(APP_CONFIG["cache_dir"]))
CACHE_FILE = _resolve_path(
    os.path.join(str(APP_CONFIG["cache_dir"]), str(APP_CONFIG["cache_file"]))
)
SETTINGS_FILE = _resolve_path(
    os.path.join(str(APP_CONFIG["cache_dir"]), str(APP_CONFIG["settings_file"]))
)
RECENT_CHATS_COUNT = int(APP_CONFIG["recent_chats_count"])
HISTORY_MESSAGE_COUNT = int(APP_CONFIG["history_message_count"])
CHAT_LIST_RENDER_LIMIT = int(APP_CONFIG["chat_list_render_limit"])
CACHE_GROUP_MEMBERS_ON_OPEN = bool(APP_CONFIG["cache_group_members_on_open"])
