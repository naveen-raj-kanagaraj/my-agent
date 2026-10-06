"""The models users can pick from.

Claude models use ANTHROPIC_API_KEY. ChatGPT uses OPENAI_API_KEY and Gemini uses
GEMINI_API_KEY (through Google's OpenAI-compatible endpoint); each only appears once its
key is in .env. Model IDs and prices for ChatGPT and Gemini are settings, because those
providers rename models often:

    OPENAI_MODEL=gpt-5.6-terra      OPENAI_PRICE=2,12        (USD per 1M input,output tokens)
    GEMINI_MODEL=gemini-3.7-flash   GEMINI_PRICE=0.75,3.75
"""
import math
import os

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
HAIKU_OUT_PRICE = 5.0  # cost weights are relative to Haiku's output price


def _price(env: str, default: str) -> tuple:
    try:
        a, b = (float(x) for x in os.getenv(env, default).split(","))
        return a, b
    except ValueError:
        return tuple(float(x) for x in default.split(","))


def registry() -> dict:
    return {
        "haiku": {"label": "Claude Haiku 4.5", "short": "Haiku", "provider": "anthropic",
                  "id": "claude-haiku-4-5-20251001", "price": (1.0, 5.0)},
        "sonnet": {"label": "Claude Sonnet 5.5", "short": "Sonnet", "provider": "anthropic",
                   "id": "claude-sonnet-5-5", "price": (2.0, 10.0)},
        "opus": {"label": "Claude Opus 5.5", "short": "Opus", "provider": "anthropic",
                 "id": "claude-opus-5-5", "price": (4.0, 20.0)},
        "gpt": {"label": f"ChatGPT ({os.getenv('OPENAI_MODEL', 'gpt-5.6-terra')})", "short": "ChatGPT",
                "provider": "openai", "id": os.getenv("OPENAI_MODEL", "gpt-5.6-terra"),
                "price": _price("OPENAI_PRICE", "2,12")},
        "gemini": {"label": f"Gemini ({os.getenv('GEMINI_MODEL', 'gemini-3.7-flash')})", "short": "Gemini",
                   "provider": "gemini", "id": os.getenv("GEMINI_MODEL", "gemini-3.7-flash"),
                   "price": _price("GEMINI_PRICE", "0.75,3.75")},
    }


def available() -> dict:
    """Models whose provider key is configured, in display order."""
    keys = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}
    out = {}
    for k, m in registry().items():
        if os.getenv(keys[m["provider"]]):
            if m["provider"] != "anthropic":
                try:
                    import openai  # noqa: F401
                except ImportError:
                    continue
            out[k] = m
    return out


def weight(key: str) -> int:
    """How many daily requests one message on this model uses (Haiku = 1)."""
    m = registry().get(key)
    if not m:
        return 1
    return max(1, math.ceil(m["price"][1] / HAIKU_OUT_PRICE - 0.25))


def price_for_id(model_id: str):
    for m in registry().values():
        if model_id == m["id"] or model_id.startswith(m["id"]):
            return m["price"]
    return None


def key_for_id(model_id: str) -> str:
    for k, m in registry().items():
        if model_id == m["id"]:
            return k
    return ""
