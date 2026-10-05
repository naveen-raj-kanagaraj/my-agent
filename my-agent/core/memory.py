import json
import os

MEMORY_FILE = "memory.json"

class Memory:
    def __init__(self):
        self.data = {}
        self._load()

    def _load(self):
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "r") as f:
                self.data = json.load(f)

    def _save(self):
        with open(MEMORY_FILE, "w") as f:
            json.dump(self.data, f, indent=2)

    def get(self, user_id: str, platform: str) -> list:
        key = f"{platform}:{user_id}"
        return list(self.data.get(key, []))

    def save(self, user_id: str, platform: str, history: list):
        key = f"{platform}:{user_id}"
        self.data[key] = history[-30:]
        self._save()

    def clear(self, user_id: str, platform: str):
        key = f"{platform}:{user_id}"
        self.data.pop(key, None)
        self._save()