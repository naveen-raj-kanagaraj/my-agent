"""The models users can pick from.

Claude models use ANTHROPIC_API_KEY. ChatGPT models use OPENAI_API_KEY and Gemini models use
GEMINI_API_KEY (through Google's OpenAI-compatible endpoint). Every model is always shown in
the picker; ones whose key isn't set explain what's needed when tapped.

Each model's ID and price can be changed in .env, because providers rename models often:
    <KEY>_MODEL_ID=...      e.g. GPT_SOL_MODEL_ID=gpt-5.6-sol
    <KEY>_PRICE=in,out      USD per 1M tokens, e.g. GPT_SOL_PRICE=4,20
(KEY is the model key below in capitals with '-' as '_'.) OPENAI_MODEL / GEMINI_MODEL still
override the default ChatGPT / Gemini entries.
"""
import math
import os

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
HAIKU_OUT_PRICE = 5.0  # cost weights are relative to Haiku's output price
PROVIDER_KEYS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}
PROVIDER_NAMES = {"anthropic": "Claude", "openai": "ChatGPT", "gemini": "Gemini"}

# key, button label (with version), provider, default model ID, default price (in, out)
_MODELS = [
    ("haiku", "Haiku 4.5", "anthropic", "claude-haiku-4-5-20251001", (1.0, 5.0)),
    ("sonnet", "Sonnet 5.5", "anthropic", "claude-sonnet-5-5", (2.0, 10.0)),
    ("opus", "Opus 5.5", "anthropic", "claude-opus-5-5", (4.0, 20.0)),
    ("fable", "Fable 5.1", "anthropic", "claude-fable-5-1", (10.0, 50.0)),
    ("gpt-luna", "GPT-5.6 Luna", "openai", "gpt-5.6-luna", (0.2, 1.2)),
    ("gpt", "GPT-5.6 Terra", "openai", "gpt-5.6-terra", (2.0, 12.0)),
    ("gpt-sol", "GPT-5.6 Sol", "openai", "gpt-5.6-sol", (4.0, 20.0)),
    ("gemini-lite", "Gemini 3.1 Flash-Lite", "gemini", "gemini-3.1-flash-lite", (0.25, 1.5)),
    ("gemini", "Gemini 3.7 Flash", "gemini", "gemini-3.7-flash", (0.75, 3.75)),
    ("gemini-pro", "Gemini 3.1 Pro", "gemini", "gemini-3.1-pro-preview", (2.0, 12.0)),
]


def _env_name(key: str, suffix: str) -> str:
    return f"{key.upper().replace('-', '_')}_{suffix}"


def _price(key: str, default: tuple) -> tuple:
    raw = os.getenv(_env_name(key, "PRICE")) or {"gpt": os.getenv("OPENAI_PRICE"),
                                                "gemini": os.getenv("GEMINI_PRICE")}.get(key)
    if raw:
        try:
            a, b = (float(x) for x in raw.split(","))
            return a, b
        except ValueError:
            pass
    return default


def registry() -> dict:
    out = {}
    for key, label, provider, default_id, price in _MODELS:
        mid = os.getenv(_env_name(key, "MODEL_ID")) or {"gpt": os.getenv("OPENAI_MODEL"),
                                                       "gemini": os.getenv("GEMINI_MODEL")}.get(key) or default_id
        out[key] = {"key": key, "short": label, "label": f"Claude {label}" if provider == "anthropic" else label,
                    "provider": provider, "id": mid, "price": _price(key, price)}
    return out


def is_ready(key: str) -> bool:
    m = registry().get(key)
    if not m or not os.getenv(PROVIDER_KEYS[m["provider"]]):
        return False
    if m["provider"] != "anthropic":
        try:
            import openai  # noqa: F401
        except ImportError:
            return False
    return True


def available() -> dict:
    """Models that can answer right now (their provider's key is set)."""
    return {k: m for k, m in registry().items() if is_ready(k)}


def setup_hint(key: str) -> str:
    m = registry()[key]
    env = PROVIDER_KEYS[m["provider"]]
    where = {"openai": "platform.openai.com > API keys", "gemini": "aistudio.google.com > Get API key"}.get(m["provider"], "")
    return f"{m['short']} isn't connected yet. The bot owner needs to add {env} to .env ({where}) and restart."


def weight(key: str) -> int:
    """How many daily requests one message on this model uses (Haiku = 1)."""
    m = registry().get(key)
    if not m:
        return 1
    return max(1, math.ceil(m["price"][1] / HAIKU_OUT_PRICE - 0.25))


def price_for_id(model_id: str):
    for m in registry().values():
        if model_id == m["id"]:
            return m["price"]
    return None


def key_for_id(model_id: str) -> str:
    for k, m in registry().items():
        if model_id == m["id"]:
            return k
    return ""
