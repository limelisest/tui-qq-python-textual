"""Pure helpers for message parsing and rendering.

Two responsibilities live here:

1. **OneBot message-segment rendering** via a registry (``register_segment``).
   This is the primary extension point: to support a new segment type (image
   preview, forward message, file download, ...) you register a handler
   instead of editing a big ``if/elif`` chain. See ``_default_handlers`` at the
   bottom for the built-in set.

2. **MessageData construction & reply preview** helpers, factored out of the
   old ``tui.py`` so they can be reused by the services layer and unit-tested.

Robustness: every ``int(raw.get(...))`` is guarded so a malformed payload from
NapBot degrades to a safe default instead of crashing the whole render path.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, List, Optional, Sequence, Tuple

from rich.console import RenderableType
from rich.markup import escape as rich_escape
from rich.text import Text

from models import ChatInfo, MessageData
from ui.text_utils import format_time

if TYPE_CHECKING:
    from storage import Storage

#: Turns an ``@`` target qq string into a display name.
AtResolver = Callable[[str], str]


def _passthrough_at_resolver(qq: str) -> str:
    return qq


# --------------------------------------------------------------------------- #
# Segment registry
# --------------------------------------------------------------------------- #

MessageLike = object  # str | list[dict] | arbitrary


@dataclass(frozen=True)
class SegmentHandler:
    """Renders a single message segment to terminal-friendly text.

    Future handlers may grow extra slots (e.g. ``download_url`` for images,
    ``widget`` for rich cards) without breaking existing registrations.
    """

    render_text: Callable[[dict, AtResolver], str]


_SEGMENT_HANDLERS: dict[str, SegmentHandler] = {}


def register_segment(seg_type: str, handler: SegmentHandler) -> None:
    """Register (or replace) the handler for a OneBot segment type."""
    _SEGMENT_HANDLERS[seg_type] = handler


def segment_handler(seg_type: str) -> Optional[SegmentHandler]:
    return _SEGMENT_HANDLERS.get(seg_type)


def render_message(
    message: MessageLike, at_resolver: Optional[AtResolver] = None
) -> str:
    """Render a OneBot message (str or list of segments) to compact text.

    Mirrors the original ``extract_text`` behaviour, but dispatches through the
    registry so new segment types can be added without touching this function.
    """
    if isinstance(message, str):
        return message
    if not isinstance(message, list):
        return str(message)

    resolver = at_resolver or _passthrough_at_resolver
    parts: list[str] = []
    for segment in message:
        if not isinstance(segment, dict):
            parts.append(str(segment))
            continue
        msg_type = segment.get("type", "")
        handler = _SEGMENT_HANDLERS.get(msg_type)
        if handler is not None:
            parts.append(handler.render_text(segment, resolver))
        else:
            parts.append(f"[{msg_type or '消息'}]")
    return "".join(parts)


# --------------------------------------------------------------------------- #
# Reply context / preview
# --------------------------------------------------------------------------- #

def extract_reply_target(message: MessageLike) -> Optional[int]:
    """Return the replied-to message id in ``message``, or ``None``.

    Pure parsing only — preview text is resolved separately by the caller,
    where storage / current message context is available.
    """
    if not isinstance(message, list):
        return None
    for segment in message:
        if isinstance(segment, dict) and segment.get("type") == "reply":
            data = segment.get("data", {}) or {}
            try:
                reply_to = int(data.get("id") or 0)
            except (TypeError, ValueError):
                return None
            return reply_to or None
    return None


def _short_preview(content: str, limit: int = 42) -> str:
    """Collapse whitespace and truncate ``content`` for inline reply previews."""
    preview = (content or "").replace("\n", " ")
    preview = " ".join(preview.split())
    if len(preview) > limit:
        preview = preview[:limit] + "..."
    return preview


def resolve_reply_preview(
    reply_to: Optional[int],
    current_messages: Sequence[MessageData],
    storage: Optional["Storage"],
    chat_type: str,
    chat_id: int,
    sender_name: Callable[[MessageData], str],
) -> Optional[str]:
    """Build the ``[回复 名：预览]`` string for a reply target.

    Looks the target up first in ``current_messages`` (the open chat) and then
    in storage history. ``sender_name`` resolves the target's display name so
    this stays free of storage/ob wiring.
    """
    if reply_to is None:
        return None
    target: Optional[MessageData] = next(
        (item for item in current_messages if item.message_id == reply_to), None
    )
    if target is None and storage is not None:
        target = next(
            (
                item
                for item in storage.get_messages(chat_type, chat_id)
                if item.message_id == reply_to
            ),
            None,
        )
    if target is None:
        return None
    name = sender_name(target)
    return f"[回复 {name}：{_short_preview(target.content)}]"


def build_reply_preview(
    msg: MessageData,
    current_messages: Sequence[MessageData],
    sender_name: Callable[[MessageData], str],
) -> str:
    """Return ``msg.reply_preview`` or rebuild it from current messages.

    Returns ``''`` when there is nothing to show.
    """
    if msg.reply_preview:
        return msg.reply_preview
    if msg.reply_to is None:
        return ""
    target = next(
        (item for item in current_messages if item.message_id == msg.reply_to),
        None,
    )
    if target is None:
        return ""
    name = sender_name(target)
    return f"[回复 {name}：{_short_preview(target.content)}]"


# --------------------------------------------------------------------------- #
# MessageData construction (from history / from real-time event)
# --------------------------------------------------------------------------- #

def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def make_at_resolver(
    chat_type: str, chat_id: int, storage: Optional["Storage"]
) -> AtResolver:
    """Build a resolver that maps an ``@`` qq to a group member display name.

    Non-group chats always resolve to ``''`` (matching the original behaviour,
    where private-message ``@`` is meaningless).
    """

    def resolve(qq: str) -> str:
        if chat_type != "group" or storage is None:
            return ""
        try:
            user_id = int(qq)
        except (TypeError, ValueError):
            return ""
        member = storage.get_member(chat_id, user_id)
        return member.display_name if member else ""

    return resolve


def message_from_history(
    chat: ChatInfo, raw: dict, at_resolver: AtResolver
) -> MessageData:
    """Build a :class:`MessageData` from a get_*_msg_history item."""
    sender = raw.get("sender", {}) or {}
    reply_to = extract_reply_target(raw.get("message", ""))
    reply_preview = None
    if reply_to:
        # Preview resolution needs storage/context; the services layer fills it
        # in for live rendering. For history items we keep it None and let the
        # UI rebuild it lazily via build_reply_preview.
        reply_preview = None
    return MessageData(
        message_id=_safe_int(raw.get("message_id")),
        chat_id=chat.chat_id,
        chat_type=chat.chat_type,
        user_id=_safe_int(sender.get("user_id") or raw.get("user_id")),
        content=render_message(raw.get("message", ""), at_resolver),
        time=_safe_int(raw.get("time")),
        sender_name=sender.get("card") or sender.get("nickname", ""),
        sender_title=sender.get("title", ""),
        sender_role=sender.get("role", "member"),
        reply_to=reply_to,
        reply_preview=reply_preview,
    )


def message_from_event(event: dict, at_resolver: AtResolver) -> MessageData:
    """Build a :class:`MessageData` from a real-time OneBot message event."""
    msg_type = event.get("message_type")
    chat_type = "group" if msg_type == "group" else "private"
    chat_id = event.get("group_id") if chat_type == "group" else event.get("user_id")
    chat_id = _safe_int(chat_id)
    sender = event.get("sender", {}) or {}
    reply_to = extract_reply_target(event.get("message", ""))
    return MessageData(
        message_id=_safe_int(event.get("message_id")),
        chat_id=chat_id,
        chat_type=chat_type,
        user_id=_safe_int(sender.get("user_id") or event.get("user_id")),
        content=render_message(event.get("message", ""), at_resolver),
        time=_safe_int(event.get("time") or time.time()),
        sender_name=sender.get("card") or sender.get("nickname", ""),
        sender_title=sender.get("title", ""),
        sender_role=sender.get("role", "member"),
        reply_to=reply_to,
        reply_preview=None,
    )


# --------------------------------------------------------------------------- #
# Sender resolution & rendering
# --------------------------------------------------------------------------- #

def resolve_sender(
    msg: MessageData,
    storage: Optional["Storage"],
    self_id: Optional[int],
    friend_remarks: dict,
) -> Tuple[str, str, str]:
    """Resolve (name, title, role) for ``msg``.

    Group members are looked up in storage; if a member is also a friend (and
    not us) their friend remark is appended. Messages from ``self_id`` get the
    ``self`` role so the UI can colour them distinctly.
    """
    name = msg.sender_name or str(msg.user_id)
    title = msg.sender_title
    role = msg.sender_role or "member"
    if msg.chat_type == "group" and storage is not None:
        member = storage.get_member(msg.chat_id, msg.user_id)
        if member:
            name = member.display_name or name
            title = member.title or title
            role = member.role or role
        # If the group member is also a friend (and not us), append the remark.
        if msg.user_id != self_id:
            remark = friend_remarks.get(msg.user_id)
            if remark and remark != name:
                name = f"{name} ({remark})"
    if msg.user_id and msg.user_id == self_id:
        role = "self"
    return name, title, role


@dataclass
class MessageRenderables:
    """The renderable lines that make up one message bubble.

    ``preview`` is optional (present only when the message is a reply).
    """

    header: Text
    preview: Optional[RenderableType]
    content: RenderableType


def build_message_renderables(
    msg: MessageData,
    name: str,
    title: str,
    role: str,
    role_styles: dict,
    reply_preview: str,
    selected: bool = False,
) -> MessageRenderables:
    """Compute the Text renderables for a single message.

    Split out of the old ``_write_message`` so the App only has to call
    ``log.write(...)`` with the result. ``reply_preview`` must already be
    resolved by the caller (see :func:`build_reply_preview`).
    """
    style = role_styles.get(role, role_styles.get("member", "white"))
    title_text = f"[{title}]" if title else ""
    timestamp = format_time(msg.time)
    time_text = f" [dim]{timestamp}[/]" if timestamp else ""
    content = rich_escape(msg.content or "")
    escaped_name = rich_escape(title_text + name)

    header = Text.from_markup(f"[{style}]{escaped_name}[/]{time_text}")

    preview: Optional[RenderableType] = None
    if reply_preview:
        preview = Text.from_markup(f"[dim]{rich_escape(reply_preview)}[/]")

    content_renderable = Text.from_markup(content)
    return MessageRenderables(header=header, preview=preview, content=content_renderable)


# --------------------------------------------------------------------------- #
# Built-in segment handlers (behaviour-equivalent to the original extract_text)
# --------------------------------------------------------------------------- #

def _text_handler(segment: dict, resolver: AtResolver) -> str:
    return (segment.get("data", {}) or {}).get("text", "")


def _at_handler(segment: dict, resolver: AtResolver) -> str:
    data = segment.get("data", {}) or {}
    qq = str(data.get("qq", ""))
    if qq == "all":
        return "@全体成员"
    name = resolver(qq)
    return f"@{name or qq}"


def _image_handler(segment: dict, resolver: AtResolver) -> str:
    return "[图片]"


def _video_handler(segment: dict, resolver: AtResolver) -> str:
    return "[视频]"


def _face_handler(segment: dict, resolver: AtResolver) -> str:
    return "[表情]"


def _reply_handler(segment: dict, resolver: AtResolver) -> str:
    # Reply targets are rendered as their own preview line, not inline.
    return ""


def _file_handler(segment: dict, resolver: AtResolver) -> str:
    return "[文件]"


def _register_default_handlers() -> None:
    register_segment("text", SegmentHandler(_text_handler))
    register_segment("at", SegmentHandler(_at_handler))
    register_segment("image", SegmentHandler(_image_handler))
    register_segment("video", SegmentHandler(_video_handler))
    for face_type in ("face", "mface", "sface"):
        register_segment(face_type, SegmentHandler(_face_handler))
    register_segment("reply", SegmentHandler(_reply_handler))
    register_segment("file", SegmentHandler(_file_handler))


_register_default_handlers()


# --------------------------------------------------------------------------- #
# Realtime event parsing (pure)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RealtimeEventUpdate:
    """Pure parsed result from a OneBot message event.

    Returned by :func:`parse_realtime_event`; the caller (typically
    ``RealtimeController``) applies the side-effects to storage and UI.
    """

    chat_type: str
    chat_id: int
    message: MessageData


def parse_realtime_event(
    event: dict,
    at_resolver: Optional[AtResolver] = None,
) -> Optional[RealtimeEventUpdate]:
    """Convert a raw OneBot message event dict into a structured update.

    This is a **pure function** — no I/O, no side effects.  Returns ``None``
    when the event is not a message event or cannot be parsed.

    Parameters
    ----------
    event:
        Raw OneBot event dict.
    at_resolver:
        Optional resolver for ``@`` mentions.  Defaults to passthrough
        (leaves ``@qq`` as-is).
    """
    if event.get("post_type") != "message":
        return None
    chat_type = "group" if event.get("message_type") == "group" else "private"
    chat_id = event.get("group_id") if chat_type == "group" else event.get("user_id")
    try:
        chat_id = int(chat_id or 0)
    except (TypeError, ValueError):
        return None
    if not chat_id:
        return None
    resolver = at_resolver or _passthrough_at_resolver
    try:
        message = message_from_event(event, resolver)
    except Exception:
        return None
    if not message.chat_id:
        return None
    return RealtimeEventUpdate(
        chat_type=message.chat_type,
        chat_id=message.chat_id,
        message=message,
    )
