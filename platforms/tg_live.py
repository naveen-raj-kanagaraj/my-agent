"""Live replies, group safety and inline mode for the Telegram bot.

LiveReply   while the agent works: private chats see a streaming draft (progress, then the answer as it's
            written, via sendMessageDraft); groups see one status line that updates and is deleted at the end.
Group guard per-person cooldown, per-group hourly and daily caps, /botoff for admins, ignores other bots.
Inline mode @bot <question> in any chat: posts a placeholder, then edits in the answer.
"""
import asyncio
import html
import os
import random
import time
from datetime import datetime

from core import store, tg_format

TICK = 0.8                 # seconds between UI updates
GROUP_STATUS_AFTER = 2.5   # only show a status line in groups if the answer takes longer than this

GROUP_COOLDOWN_SEC = int(os.getenv("GROUP_COOLDOWN_SEC", "15"))
GROUP_MAX_PER_HOUR = int(os.getenv("GROUP_MAX_PER_HOUR", "40"))
GROUP_MAX_PER_DAY = int(os.getenv("GROUP_MAX_PER_DAY", "150"))
GROUP_MAX_CHARS = 2000
INLINE_COOLDOWN_SEC = int(os.getenv("INLINE_COOLDOWN_SEC", "5"))


# ---------- live replies ----------

class LiveReply:
    def __init__(self, bot, chat_id, ctx, private: bool, reply_to=None, rich: bool = False):
        self.bot, self.chat_id, self.ctx, self.private = bot, chat_id, ctx, private
        self.reply_to, self.rich = reply_to, rich
        self.draft_id = random.randint(1, 2 ** 31 - 1)
        self.drafts_ok = private
        self.status_msg = None
        self.shown = None
        self.started = time.time()
        self._task = None

    def view(self) -> str:
        if self.ctx.partial.strip():
            text = self.ctx.partial
            return text if len(text) < 3800 else text[:3800] + " …"
        return (self.ctx.progress or "Thinking") + "…"

    async def _draft(self, text: str):
        if self.rich and self.ctx.partial:
            try:
                await self.bot.send_message_draft(chat_id=self.chat_id, draft_id=self.draft_id,
                                                  text=tg_format.to_html(text), parse_mode="HTML")
                return
            except Exception:
                pass
        await self.bot.send_message_draft(chat_id=self.chat_id, draft_id=self.draft_id, text=text)

    async def _tick(self):
        text = self.view()
        if text == self.shown:
            return
        if self.drafts_ok:
            try:
                await self._draft(text)
                self.shown = text
                return
            except Exception as e:
                print(f"Drafts unavailable, using a status message: {str(e)[:100]}")
                self.drafts_ok = False
        # Status line (groups, or private chats where drafts fail): progress only, no partial text.
        status = (self.ctx.progress or "Thinking") + "…"
        if time.time() - self.started < GROUP_STATUS_AFTER or status == self.shown:
            return
        try:
            if self.status_msg is None:
                self.status_msg = await self.bot.send_message(
                    chat_id=self.chat_id, text=status,
                    reply_to_message_id=getattr(self.reply_to, "message_id", None))
            else:
                await self.status_msg.edit_text(status)
            self.shown = status
        except Exception:
            pass

    async def _loop(self):
        while True:
            await asyncio.sleep(TICK)
            await self._tick()

    def start(self):
        self.ctx.stream = self.private  # drafts can show the answer as it's written
        self._task = asyncio.create_task(self._loop())
        return self

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        if self.status_msg is not None:
            try:
                await self.status_msg.delete()
            except Exception:
                pass


# ---------- group safety ----------

_last_ask = {}     # (group, user) -> time of last answered message
_warned = {}       # (group, user or 'group', window) -> True


def group_off(chat_id) -> bool:
    return bool(store.kv_get(f"group_off:{chat_id}"))


def set_group_off(chat_id, off: bool):
    store.kv_set(f"group_off:{chat_id}", bool(off))


def check_group(chat_id, user_id) -> tuple:
    """(allowed, message_to_show_or_empty). Shows each warning once, then stays quiet."""
    now = time.time()
    key = (str(chat_id), str(user_id))
    wait = GROUP_COOLDOWN_SEC - (now - _last_ask.get(key, 0))
    if wait > 0:
        w = (key, "cool", int(_last_ask[key]))
        if w in _warned:
            return False, ""
        _warned[w] = True
        return False, f"One at a time please. Ask again in {int(wait) + 1}s."
    hour = datetime.now().strftime("%Y%m%d%H")
    day = hour[:8]
    h_count = store.kv_get(f"gcount:{chat_id}:{hour}", 0)
    d_count = store.kv_get(f"gcount:{chat_id}:{day}", 0)
    if d_count >= GROUP_MAX_PER_DAY:
        w = (str(chat_id), "day", day)
        if w in _warned:
            return False, ""
        _warned[w] = True
        return False, "This group has used today's questions. I'll be back tomorrow."
    if h_count >= GROUP_MAX_PER_HOUR:
        w = (str(chat_id), "hour", hour)
        if w in _warned:
            return False, ""
        _warned[w] = True
        return False, "This group has asked a lot this hour. I'll be back at the top of the hour."
    _last_ask[key] = now
    store.kv_set(f"gcount:{chat_id}:{hour}", h_count + 1)
    store.kv_set(f"gcount:{chat_id}:{day}", d_count + 1)
    if len(_warned) > 5000:
        _warned.clear()
    return True, ""


async def is_group_admin(bot, chat_id, user_id) -> bool:
    if store.is_owner("telegram", str(user_id)):
        return True
    try:
        m = await bot.get_chat_member(chat_id, user_id)
        return m.status in ("administrator", "creator")
    except Exception:
        return False


# ---------- inline mode ----------

_inline_last = {}


def inline_cooldown(user_id) -> int:
    wait = INLINE_COOLDOWN_SEC - (time.time() - _inline_last.get(str(user_id), 0))
    if wait > 0:
        return int(wait) + 1
    _inline_last[str(user_id)] = time.time()
    return 0


def inline_text(question: str, body_html: str) -> str:
    q = html.escape(question if len(question) < 300 else question[:300] + "…")
    out = f"<b>Q:</b> {q}\n\n{body_html}"
    if len(out) > 4000:
        out = out[:3950].rsplit("\n", 1)[0] + "\n\n<i>(cut short; ask me in private for the full answer)</i>"
    return out
