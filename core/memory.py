import json
import os
import threading

MEMORY_FILE = "memory.json"
MAX_MESSAGES = 30


class Memory:
    """Conversation memory shared by every platform.

    All Memory() instances share one in-memory store and one lock, so Telegram,
    Discord and the agent can no longer overwrite each other's copy of memory.json.
    """

    _data = None
    _lock = threading.RLock()

    def __init__(self):
        with Memory._lock:
            if Memory._data is None:
                Memory._data = {}
                if os.path.exists(MEMORY_FILE):
                    try:
                        with open(MEMORY_FILE, "r") as f:
                            Memory._data = json.load(f)
                    except (json.JSONDecodeError, OSError):
                        os.replace(MEMORY_FILE, MEMORY_FILE + ".corrupt")
        self.data = Memory._data

    def _save(self):
        tmp = MEMORY_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(Memory._data, f, indent=2)
        os.replace(tmp, MEMORY_FILE)  # atomic: a crash mid-write can't corrupt memory

    def get(self, user_id: str, platform: str) -> list:
        with Memory._lock:
            return list(Memory._data.get(f"{platform}:{user_id}", []))

    def save(self, user_id: str, platform: str, history: list):
        with Memory._lock:
            trimmed = history[-MAX_MESSAGES:]
            # History must start with a user turn for the API to accept it.
            while trimmed and trimmed[0].get("role") != "user":
                trimmed = trimmed[1:]
            Memory._data[f"{platform}:{user_id}"] = trimmed
            self._save()

    def clear(self, user_id: str, platform: str):
        with Memory._lock:
            Memory._data.pop(f"{platform}:{user_id}", None)
            self._save()
