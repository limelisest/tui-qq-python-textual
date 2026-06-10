from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class ChatInfo:
    chat_id: int
    name: str
    chat_type: str  # 'private' or 'group'
    last_time: float = 0.0


@dataclass
class MemberInfo:
    user_id: int
    nickname: str = ''
    card: str = ''
    title: str = ''
    role: str = 'member'  # owner, admin, member

    @property
    def display_name(self) -> str:
        return self.card or self.nickname


@dataclass
class MessageData:
    message_id: int
    chat_id: int
    chat_type: str
    user_id: int
    content: str
    time: int
    sender_name: str = ''
    sender_title: str = ''
    sender_role: str = 'member'
