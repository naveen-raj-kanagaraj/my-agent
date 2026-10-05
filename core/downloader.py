"""Video downloading for the agent (ported from telegram-video-bot).

Two ways in:
  1. Fast path: the Telegram handler sees a bare link and calls download_video() directly.
  2. Agent tool: Claude calls the download_video tool; the file is queued in OUTBOX and the
     Telegram handler sends it after the reply.
"""
import os
import re
import shutil
import tempfile
from pathlib import Path

import yt_dlp

# Telegram's standard bot API rejects uploads over 50 MB.
MAX_MB = int(os.getenv("VIDEO_MAX_MB", "50"))
MAX_FILE_SIZE = MAX_MB * 1024 * 1024

# Optional: cookies.txt exported from a logged-in browser fixes most Instagram blocks.
COOKIES_FILE = Path(__file__).resolve().parent.parent / "cookies.txt"

URL_PATTERN = re.compile(
    r"https?://(?:www\.|m\.|vm\.|vt\.)?"
    r"(?:twitter\.com|x\.com|instagram\.com|instagr\.am|tiktok\.com|"
    r"youtube\.com/shorts|youtu\.be|youtube\.com/watch|reddit\.com|v\.redd\.it|"
    r"facebook\.com|fb\.watch|threads\.net)"
    r"/\S*",
    re.IGNORECASE,
)

# Files waiting to be sent, keyed by (platform, user_id). Filled by the agent tool.
OUTBOX: dict = {}
# Set by core.agent.chat() before each run so the tool knows who asked.
CURRENT = {"platform": None, "user_id": None}


def find_url(text: str):
    m = URL_PATTERN.search(text or "")
    return m.group(0) if m else None


def is_bare_link(text: str) -> bool:
    """True when the message is just a supported link (maybe with a word or two)."""
    url = find_url(text)
    if not url:
        return False
    rest = (text or "").replace(url, "").strip()
    return len(rest.split()) <= 2


class DownloadFailed(Exception):
    pass


def download_video(url: str) -> dict:
    """Blocking download. Returns {path, dir, title, duration, width, height, size_mb}.
    Caller must delete result['dir'] when done."""
    out_dir = tempfile.mkdtemp(prefix="agentvid_")
    limit = f"{MAX_MB - 2}M"
    opts = {
        "outtmpl": os.path.join(out_dir, "%(id)s.%(ext)s"),
        "format": (
            f"best[ext=mp4][filesize<{limit}]/"
            f"best[filesize<{limit}]/"
            f"best[filesize_approx<{limit}]/"
            "best"
        ),
        "max_filesize": MAX_FILE_SIZE,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "concurrent_fragment_downloads": 8,
        "retries": 3,
    }
    if COOKIES_FILE.exists():
        opts["cookiefile"] = str(COOKIES_FILE)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if "entries" in info:
                info = info["entries"][0]
            path = Path(ydl.prepare_filename(info))
    except yt_dlp.utils.DownloadError as e:
        shutil.rmtree(out_dir, ignore_errors=True)
        msg = str(e).lower()
        if "login" in msg or "rate" in msg:
            raise DownloadFailed(
                "The site blocked this download (login or rate limit). "
                "Adding a cookies.txt file to the my-agent folder usually fixes Instagram."
            )
        if "no video" in msg:
            raise DownloadFailed("No video found in that post.")
        raise DownloadFailed(f"Download failed: {str(e)[:250]}")

    if not path.exists():
        files = [p for p in Path(out_dir).iterdir() if p.is_file()]
        if not files:
            shutil.rmtree(out_dir, ignore_errors=True)
            raise DownloadFailed(
                f"No file was saved. The video is probably over the {MAX_MB} MB limit."
            )
        path = max(files, key=lambda p: p.stat().st_size)

    size = path.stat().st_size
    if size > MAX_FILE_SIZE:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise DownloadFailed(
            f"Video is {size / 1048576:.0f} MB, over the {MAX_MB} MB Telegram bot limit. "
            "Use @pesvideodownloader_bot for big files."
        )

    return {
        "path": str(path),
        "dir": out_dir,
        "title": (info.get("title") or "")[:200],
        "duration": int(info.get("duration") or 0),
        "width": int(info.get("width") or 0),
        "height": int(info.get("height") or 0),
        "size_mb": round(size / 1048576, 1),
        "description": (info.get("description") or "")[:1500],
        "uploader": info.get("uploader") or "",
    }


def tool_download_video(url: str) -> str:
    """Agent tool entry point: downloads and queues the file for the current chat."""
    key = (CURRENT["platform"], CURRENT["user_id"])
    if CURRENT["platform"] != "telegram":
        return "Video downloading only works on Telegram right now. Tell the user to send the link there."
    try:
        result = download_video(url)
    except DownloadFailed as e:
        return str(e)
    OUTBOX.setdefault(key, []).append(result)
    parts = [
        f"Downloaded ({result['size_mb']} MB, {result['duration']}s). "
        "It will be sent to the user automatically right after your reply; do not say you cannot send files.",
    ]
    if result["title"]:
        parts.append(f"Title: {result['title']}")
    if result["uploader"]:
        parts.append(f"Uploader: {result['uploader']}")
    if result["description"]:
        parts.append(f"Caption/description: {result['description']}")
    return "\n".join(parts)


def take_outbox(platform: str, user_id: str) -> list:
    return OUTBOX.pop((platform, user_id), [])


def cleanup(result: dict):
    shutil.rmtree(result.get("dir", ""), ignore_errors=True)
