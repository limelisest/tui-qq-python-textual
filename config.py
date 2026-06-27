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
    "message_record_limit": 100,
    "chat_list_render_limit": 300,
    "cache_group_members_on_open": False,
    "enable_message_reply_action": True,
    "enable_message_plus_one_action": True,
    "sidebar_auto_hide_pixel_1": 800,
    "sidebar_auto_hide_pixel_2h": 1000,
    "sidebar_auto_hide_pixel_2v": 800,
    "sidebar_auto_hide_pixel_3h": 1200,
    "sidebar_auto_hide_pixel_3v": 800,
    "sidebar_auto_hide_pixel_4": 1000,
    "sidebar_auto_hide_column_1": 101,
    "sidebar_auto_hide_column_2h": 126,
    "sidebar_auto_hide_column_2v": 101,
    "sidebar_auto_hide_column_3h": 151,
    "sidebar_auto_hide_column_3v": 101,
    "sidebar_auto_hide_column_4": 126,
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
MESSAGE_RECORD_LIMIT = int(APP_CONFIG["message_record_limit"])
CHAT_LIST_RENDER_LIMIT = int(APP_CONFIG["chat_list_render_limit"])
CACHE_GROUP_MEMBERS_ON_OPEN = bool(APP_CONFIG["cache_group_members_on_open"])
ENABLE_MESSAGE_REPLY_ACTION = bool(APP_CONFIG["enable_message_reply_action"])
ENABLE_MESSAGE_PLUS_ONE_ACTION = bool(APP_CONFIG["enable_message_plus_one_action"])
SIDEBAR_AUTO_HIDE_PIXEL_1 = int(APP_CONFIG["sidebar_auto_hide_pixel_1"])
SIDEBAR_AUTO_HIDE_PIXEL_2H = int(APP_CONFIG["sidebar_auto_hide_pixel_2h"])
SIDEBAR_AUTO_HIDE_PIXEL_2V = int(APP_CONFIG["sidebar_auto_hide_pixel_2v"])
SIDEBAR_AUTO_HIDE_PIXEL_3H = int(APP_CONFIG["sidebar_auto_hide_pixel_3h"])
SIDEBAR_AUTO_HIDE_PIXEL_3V = int(APP_CONFIG["sidebar_auto_hide_pixel_3v"])
SIDEBAR_AUTO_HIDE_PIXEL_4 = int(APP_CONFIG["sidebar_auto_hide_pixel_4"])
SIDEBAR_AUTO_HIDE_COLUMN_1 = int(APP_CONFIG["sidebar_auto_hide_column_1"])
SIDEBAR_AUTO_HIDE_COLUMN_2H = int(APP_CONFIG["sidebar_auto_hide_column_2h"])
SIDEBAR_AUTO_HIDE_COLUMN_2V = int(APP_CONFIG["sidebar_auto_hide_column_2v"])
SIDEBAR_AUTO_HIDE_COLUMN_3H = int(APP_CONFIG["sidebar_auto_hide_column_3h"])
SIDEBAR_AUTO_HIDE_COLUMN_3V = int(APP_CONFIG["sidebar_auto_hide_column_3v"])
SIDEBAR_AUTO_HIDE_COLUMN_4 = int(APP_CONFIG["sidebar_auto_hide_column_4"])
