"""Local JSON-based cache storage for member info, recent chats, and messages."""

import json
import os
import time
from typing import Dict, List, Optional
from models import MemberInfo, MessageData


class Storage:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.data = {
            'members': {},
            'recent_chats': [],
            'last_activity': {},
            'messages': {},
        }

    def load(self):
        if not os.path.exists(self.filepath):
            return
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    def save(self):
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        tmp = self.filepath + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.filepath)

    @staticmethod
    def chat_key(chat_type: str, chat_id: int) -> str:
        return f"{chat_type}_{chat_id}"

    def get_member(self, group_id: int, user_id: int) -> Optional[MemberInfo]:
        gk = str(group_id)
        if gk not in self.data.get('members', {}):
            return None
        uk = str(user_id)
        if uk not in self.data['members'][gk]:
            return None
        info = self.data['members'][gk][uk]
        return MemberInfo(
            user_id=info['user_id'],
            nickname=info.get('nickname', ''),
            card=info.get('card', ''),
            title=info.get('title', ''),
            role=info.get('role', 'member'),
        )

    def set_member(self, group_id: int, member: MemberInfo):
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

    def add_recent_chat(self, chat_type: str, chat_id: int):
        key = self.chat_key(chat_type, chat_id)
        recent = self.data.get('recent_chats', [])
        if key in recent:
            recent.remove(key)
        recent.insert(0, key)
        self.data['recent_chats'] = recent[:20]
        self.save()

    def get_recent_chats(self) -> List[str]:
        return self.data.get('recent_chats', [])[:5]

    def update_last_activity(self, chat_type: str, chat_id: int, ts: float = None):
        if ts is None:
            ts = time.time()
        key = self.chat_key(chat_type, chat_id)
        if 'last_activity' not in self.data:
            self.data['last_activity'] = {}
        self.data['last_activity'][key] = ts

    def get_last_activity(self, chat_type: str, chat_id: int) -> float:
        key = self.chat_key(chat_type, chat_id)
        return self.data.get('last_activity', {}).get(key, 0)

    def get_messages(self, chat_type: str, chat_id: int) -> List[MessageData]:
        key = self.chat_key(chat_type, chat_id)
        msgs = self.data.get('messages', {}).get(key, [])
        return [MessageData(**m) for m in msgs]

    def add_message(self, chat_type: str, chat_id: int, msg: MessageData):
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
        })
        if len(self.data['messages'][key]) > 200:
            self.data['messages'][key] = self.data['messages'][key][-200:]
