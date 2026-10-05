"""Conversation memory, stored in SQLite (data/agent.db).

`user_id` here is the agent identity from core.store.uid_for ('owner' or 'telegram:<id>').
Each platform keeps its own thread of conversation.
"""
from core import store

MAX_MESSAGES = 30


def _key(user_id: str, platform: str) -> str:
    return f"{platform}|{user_id}"


class Memory:
    def get(self, user_id: str, platform: str) -> list:
        return store.load_conversation(_key(user_id, platform))

    def save(self, user_id: str, platform: str, history: list):
        trimmed = history[-MAX_MESSAGES:]
        # The API needs the history to start with a user turn.
        while trimmed and trimmed[0].get("role") != "user":
            trimmed = trimmed[1:]
        store.save_conversation(_key(user_id, platform), trimmed)

    def add_exchange(self, user_id: str, platform: str, user_text: str, assistant_text: str):
        history = self.get(user_id, platform)
        history += [{"role": "user", "content": user_text}, {"role": "assistant", "content": assistant_text}]
        self.save(user_id, platform, history)

    def clear(self, user_id: str, platform: str):
        store.delete_conversation(_key(user_id, platform))
