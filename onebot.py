"""Synchronous OneBot v11 WebSocket client using threading."""

import json
import threading
import queue
import time
from typing import Optional, Dict, List, Any, Callable
from websockets.sync.client import connect as ws_connect
from config import WS_TOKEN, WS_URL


class PendingCall:
    def __init__(self):
        self.event = threading.Event()
        self.result: Optional[dict] = None


class OneBotClient:
    def __init__(self, url: str = None, token: str = None):
        self.url = url or WS_URL
        self.token = token if token is not None else WS_TOKEN
        self._ws = None
        self._pending: Dict[str, PendingCall] = {}
        self._lock = threading.Lock()
        self.event_queue: queue.Queue = queue.Queue()
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self.self_id: Optional[int] = None
        self._counter = 0

    def connect(self):
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        self._ws = ws_connect(self.url, additional_headers=headers, max_size=2 ** 23)
        self.running = True
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def disconnect(self):
        self.running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _reader(self):
        while self.running:
            try:
                raw = self._ws.recv()
            except Exception:
                break
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            echo = data.get('echo')
            if echo:
                with self._lock:
                    pending = self._pending.pop(echo, None)
                if pending:
                    pending.result = data
                    pending.event.set()
            elif data.get('post_type') == 'message':
                self.event_queue.put(data)
            elif data.get('post_type') == 'meta_event':
                if data.get('meta_event_type') == 'lifecycle':
                    self.self_id = data.get('self_id')
        self.running = False

    def call(self, action: str, params: dict = None, timeout: float = 10) -> dict:
        if not self._ws or not self.running:
            raise RuntimeError("WebSocket not connected")
        self._counter += 1
        echo = f"q-{self._counter}"
        pending = PendingCall()
        with self._lock:
            self._pending[echo] = pending
        payload = json.dumps({
            "action": action,
            "params": params or {},
            "echo": echo,
        }, ensure_ascii=False)
        self._ws.send(payload)
        if not pending.event.wait(timeout=timeout):
            with self._lock:
                self._pending.pop(echo, None)
            raise TimeoutError(f"API '{action}' timed out")
        data = pending.result
        if data.get('status') == 'failed' or data.get('retcode', 0) != 0:
            detail = (data.get('wording') or data.get('message')
                      or data.get('msg') or str(data)[:300])
            raise RuntimeError(f"API '{action}' failed: {detail}")
        return data.get('data', {})

    def get_login_info(self) -> dict:
        return self.call('get_login_info')

    def get_friend_list(self) -> list:
        return self.call('get_friend_list')

    def get_group_list(self) -> list:
        return self.call('get_group_list')

    def get_group_member_list(self, group_id: int) -> list:
        return self.call('get_group_member_list', {'group_id': group_id})

    def get_group_member_info(self, group_id: int, user_id: int) -> dict:
        return self.call('get_group_member_info',
                         {'group_id': group_id, 'user_id': user_id})

    def get_group_msg_history(self, group_id: int, count: int = 50) -> List[dict]:
        data = self.call('get_group_msg_history',
                         {'group_id': group_id, 'count': count})
        return data.get('messages', [])

    def get_friend_msg_history(self, user_id: int, count: int = 50) -> List[dict]:
        data = self.call('get_friend_msg_history',
                         {'user_id': user_id, 'count': count})
        return data.get('messages', [])

    def send_group_msg(self, group_id: int, message: str,
                       reply_to: int = None) -> dict:
        return self.send_msg('group', group_id, message, reply_to)

    def send_private_msg(self, user_id: int, message: str,
                         reply_to: int = None) -> dict:
        return self.send_msg('private', user_id, message, reply_to)

    def send_msg(self, message_type: str, target_id: int,
                 message: str, reply_to: int = None) -> dict:
        params: Dict[str, Any] = {'message_type': message_type}
        if message_type == 'group':
            params['group_id'] = target_id
        else:
            params['user_id'] = target_id
        if reply_to:
            params['message'] = [
                {"type": "reply", "data": {"id": str(reply_to)}},
                {"type": "text", "data": {"text": message}},
            ]
        else:
            params['message'] = [
                {"type": "text", "data": {"text": message}},
            ]
        return self.call('send_msg', params)