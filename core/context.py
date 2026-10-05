"""Who the agent is talking to right now.

Uses contextvars, so each request (each thread started by asyncio.to_thread) sees its
own user. Tools read this instead of globals, so two users chatting at the same time
can never see each other's notes, reminders or files.
"""
import contextvars
from dataclasses import dataclass, field


@dataclass
class Ctx:
    uid: str = ""            # 'owner' or 'telegram:<id>'
    platform: str = ""
    chat_id: str = ""        # where files/reminders go
    is_owner: bool = False
    outbox: list = field(default_factory=list)  # files queued by tools: {"kind": "video"|"photo", ...}


_current = contextvars.ContextVar("agent_ctx", default=None)


def set_ctx(ctx: Ctx):
    _current.set(ctx)


def get() -> Ctx:
    c = _current.get()
    if c is None:
        c = Ctx()
        _current.set(c)
    return c
