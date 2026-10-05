import json
import os
import requests
from core.downloader import tool_download_video
from datetime import datetime

NOTES_FILE = "notes.json"


def _load_notes():
    if os.path.exists(NOTES_FILE):
        with open(NOTES_FILE, "r") as f:
            return json.load(f)
    return []


def _save_notes(notes):
    with open(NOTES_FILE, "w") as f:
        json.dump(notes, f, indent=2)


def web_search(query: str) -> str:
    try:
        url = "https://google.serper.dev/search"
        headers = {
            "X-API-KEY": os.getenv("SERPER_API_KEY"),
            "Content-Type": "application/json"
        }
        payload = {"q": query, "num": 5}
        response = requests.post(url, headers=headers, json=payload)
        data = response.json()

        output = ""
        if "answerBox" in data:
            output += f"Answer: {data['answerBox'].get('answer', '')}\n\n"

        for r in data.get("organic", [])[:5]:
            output += f"Title: {r.get('title', '')}\n"
            output += f"Summary: {r.get('snippet', '')}\n"
            output += f"URL: {r.get('link', '')}\n\n"

        return output.strip() if output else "No results found."
    except Exception as e:
        return f"Search failed: {str(e)}"


def save_note(content: str, tag: str = "general") -> str:
    notes = _load_notes()
    note = {
        "id": len(notes) + 1,
        "content": content,
        "tag": tag,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    notes.append(note)
    _save_notes(notes)
    return f"Note saved. ID: {note['id']}, Tag: '{tag}'."


def get_notes(tag: str = None) -> str:
    notes = _load_notes()
    if not notes:
        return "No notes saved yet."
    if tag:
        notes = [n for n in notes if n.get("tag") == tag]
    if not notes:
        return f"No notes found under tag '{tag}'."
    output = ""
    for n in notes[-10:]:
        output += f"[{n['id']}] [{n['tag']}] {n['created_at']}\n{n['content']}\n\n"
    return output.strip()


def get_datetime() -> str:
    return datetime.now().strftime("Date: %A, %B %d %Y | Time: %I:%M %p")


def calculate(expression: str) -> str:
    try:
        safe_builtins = {
            "abs": abs, "round": round, "min": min,
            "max": max, "sum": sum, "pow": pow
        }
        result = eval(expression, {"__builtins__": safe_builtins})
        return f"{expression} = {result}"
    except Exception as e:
        return f"Error: {str(e)}"


TOOLS = [
    {
        "name": "web_search",
        "description": "Search the web for current news, prices, facts, people, events. Use this whenever you need real-time or recent information.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query. Be specific."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "save_note",
        "description": "Save a note, task, idea, or information for later retrieval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The content of the note."
                },
                "tag": {
                    "type": "string",
                    "description": "Category: task, idea, research, meeting, general"
                }
            },
            "required": ["content"]
        }
    },
    {
        "name": "get_notes",
        "description": "Retrieve saved notes. Can filter by tag.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tag": {
                    "type": "string",
                    "description": "Optional tag to filter by."
                }
            }
        }
    },
    {
        "name": "get_datetime",
        "description": "Get the current date and time.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "download_video",
        "description": "Download a video from a Twitter/X, Instagram, TikTok, YouTube Shorts, Reddit, Facebook or Threads link and send the video file to the user in this chat. Also returns the post's title and caption so you can describe it. Use whenever the user wants a video saved, downloaded, sent, or asks about a video link.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The full video post URL."}
            },
            "required": ["url"]
        }
    },
    {
        "name": "calculate",
        "description": "Perform math calculations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Math expression like '250 * 12 / 100'"
                }
            },
            "required": ["expression"]
        }
    }
]


def execute_tool(name: str, inputs: dict) -> str:
    if name == "web_search":
        return web_search(inputs["query"])
    elif name == "save_note":
        return save_note(inputs["content"], inputs.get("tag", "general"))
    elif name == "get_notes":
        return get_notes(inputs.get("tag"))
    elif name == "get_datetime":
        return get_datetime()
    elif name == "calculate":
        return calculate(inputs["expression"])
    elif name == "download_video":
        return tool_download_video(inputs["url"])
    return "Unknown tool."