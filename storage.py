"""Local JSON-based cache storage for member info, recent chats, and messages."""

import json
import os
import threading
import time
from typing import Dict, List, Optional
from models import MemberInfo, MessageData


class Storage:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self._lock = threading.RLock()
        self.data = {
            'members': {},
            'recent_chats': [],
            'pinned_chats': [],
            'last_activity': {},
            'messages': {},
        }

    def load(self):
        if not os.path.exists(self.filepath):
            return
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            with self._lock:
                self.data = data
        except (json.JSONDecodeError, IOError):
            pass

    def save(self):
        with self._lock:
            os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
            tmp = f"{self.filepath}.{os.getpid()}.{threading.get_ident()}.tmp"
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.filepath)

    @staticmethod
    def chat_key(chat_type: str, chat_id: int) -> str:
        return f"{chat_type}_{chat_id}"

    def get_member(self, group_id: int, user_id: int) -> Optional[MemberInfo]:
        gk = str(group_id)
        with self._lock:
            if gk not in self.data.get('members', {}):
                return None
            uk = str(user_id)
            if uk not in self.data['members'][gk]:
                return None
            info = dict(self.data['members'][gk][uk])
        return MemberInfo(
            user_id=info['user_id'],
            nickname=info.get('nickname', ''),
            card=info.get('card', ''),
            title=info.get('title', ''),
            role=info.get('role', 'member'),
        )

    def set_member(self, group_id: int, member: MemberInfo):
        with self._lock:
            gk = str(group_id)
            if 'members' not in self.data:
                self.data['members'] = {}
            if gk not in self.data['members']:
                self.data['members'][gk] = {}
            self.data['members'][gk][str(member.user_id)] = {
                'user_id': member.user_id,
                'nickname': member.nickname,
                'card': member.card,
                'title': member.title,
                'role': member.role,
            }
        self.save()

    def set_members(self, group_id: int, members: List[MemberInfo]):
        with self._lock:
            gk = str(group_id)
            if 'members' not in self.data:
                self.data['members'] = {}
            if gk not in self.data['members']:
                self.data['members'][gk] = {}
            for member in members:
                self.data['members'][gk][str(member.user_id)] = {
                    'user_id': member.user_id,
                    'nickname': member.nickname,
                    'card': member.card,
                    'title': member.title,
                    'role': member.role,
                }
        self.save()

    def add_recent_chat(self, chat_type: str, chat_id: int, save: bool = True):
        with self._lock:
            key = self.chat_key(chat_type, chat_id)
            recent = self.data.get('recent_chats', [])
            if key in recent:
                recent.remove(key)
            recent.insert(0, key)
            self.data['recent_chats'] = recent[:20]
        if save:
            self.save()

    def get_recent_chats(self) -> List[str]:
        with self._lock:
            return self.data.get('recent_chats', [])[:5]

    def get_pinned_chats(self) -> List[str]:
        with self._lock:
            return list(self.data.get('pinned_chats', []))

    def is_pinned_chat(self, chat_type: str, chat_id: int) -> bool:
        key = self.chat_key(chat_type, chat_id)
        with self._lock:
            return key in self.data.get('pinned_chats', [])

    def set_chat_pinned(self, chat_type: str, chat_id: int, pinned: bool, save: bool = True):
        with self._lock:
            key = self.chat_key(chat_type, chat_id)
            pins = list(self.data.get('pinned_chats', []))
            if pinned:
                if key not in pins:
                    pins.insert(0, key)
            elif key in pins:
                pins.remove(key)
            self.data['pinned_chats'] = pins
        if save:
            self.save()

    def toggle_chat_pinned(self, chat_type: str, chat_id: int, save: bool = True) -> bool:
        pinned = not self.is_pinned_chat(chat_type, chat_id)
        self.set_chat_pinned(chat_type, chat_id, pinned, save=save)
        return pinned

    def update_last_activity(self, chat_type: str, chat_id: int, ts: float = None):
        if ts is None:
            ts = time.time()
        with self._lock:
            key = self.chat_key(chat_type, chat_id)
            if 'last_activity' not in self.data:
                self.data['last_activity'] = {}
            self.data['last_activity'][key] = ts

    def get_last_activity(self, chat_type: str, chat_id: int) -> float:
        key = self.chat_key(chat_type, chat_id)
        with self._lock:
            return self.data.get('last_activity', {}).get(key, 0)

    def get_messages(self, chat_type: str, chat_id: int) -> List[MessageData]:
        key = self.chat_key(chat_type, chat_id)
        with self._lock:
            msgs = list(self.data.get('messages', {}).get(key, []))
        return [MessageData(**m) for m in msgs]

    def get_last_message(self, chat_type: str, chat_id: int) -> Optional[MessageData]:
        key = self.chat_key(chat_type, chat_id)
        with self._lock:
            msgs = self.data.get('messages', {}).get(key, [])
            if not msgs:
                return None
            return MessageData(**msgs[-1])

    def add_message(self, chat_type: str, chat_id: int, msg: MessageData):
        with self._lock:
            key = self.chat_key(chat_type, chat_id)
            if 'messages' not in self.data:
                self.data['messages'] = {}
            if key not in self.data['messages']:
                self.data['messages'][key] = []
            self.data['messages'][key].append({
                'message_id': msg.message_id,
                'chat_id': msg.chat_id,
                'chat_type': msg.chat_type,
                'user_id': msg.user_id,
                'content': msg.content,
                'time': msg.time,
                'sender_name': msg.sender_name,
                'sender_title': msg.sender_title,
                'sender_role': msg.sender_role,
                'reply_to': msg.reply_to,
                'reply_preview': msg.reply_preview,
            })
            if len(self.data['messages'][key]) > 200:
                self.data['messages'][key] = self.data['messages'][key][-200:]
