"""BMSD viewership tracker: tracking loops + Telegram bot (owner only) + local dashboard.

Run:  python main.py      (or bash scripts/autostart.sh install to run in the background)
"""
import asyncio
import fcntl
import io
import os
import re
import threading

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import page  # noqa: E402
import tracker as T  # noqa: E402

OWNER = {i.strip() for i in os.getenv("OWNER_TELEGRAM_ID", "").split(",") if i.strip()}
PORT = int(os.getenv("DASHBOARD_PORT", "8091"))
HELP = ("/stats - live now, peak, average, hours watched, top channels (or just type 'peak?')\n"
        "/live - every stream live right now, with links\n"
        "/top - all channels ranked, with links\n"
        "/chart - viewers over time\n"
        "/page - full dashboard file to open in your browser\n"
        "/add <YouTube link or @channel> - always track it\n"
        "/exclude <link, video id or channel name> - drop it\n"
        "/official <@channel or name> - mark as official\n"
        "/phrase <words> - also count streams with these words in the title\n"
        "/pause, /resume\n/health - which counting method works")


def dashboard():
    from flask import Flask, Response
    app = Flask(__name__)

    @app.route("/")
    def index():
        return Response(page.build_html(refresh=30), mimetype="text/html")
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False)


def owner_only(fn):
    async def wrapped(update, context):
        if str(update.effective_user.id) not in OWNER:
            return
        return await fn(update, context)
    return wrapped


async def reply(update, text):
    for i in range(0, len(text), 4000):
        await update.message.reply_text(text[i:i + 4000], disable_web_page_preview=True)


@owner_only
async def cmd_stats(update, context):
    await reply(update, await asyncio.to_thread(T.summary))


@owner_only
async def cmd_help(update, context):
    await reply(update, f"{T.config()['name']} tracker.\n\n{HELP}\n\nDashboard on this computer: http://localhost:{PORT}")


@owner_only
async def cmd_live(update, context):
    st = await asyncio.to_thread(T.stats)
    live = st.get("live") or []
    if not live:
        await reply(update, "Nothing live right now.")
        return
    lines = [f"LIVE: {T.fmt_n(sum(s['viewers'] for s in live))} across {len(live)} streams"]
    lines += [f"{T.fmt_n(s['viewers'])}  {s['channel']} ({s['kind']})\n   {s['title'][:80]}\n   {T.yt(s['vid'])}" for s in live]
    await reply(update, "\n".join(lines))


@owner_only
async def cmd_top(update, context):
    st = await asyncio.to_thread(T.stats)
    rows = [f"{i}. {c['channel']} ({c['kind']}): {T.fmt_n(c['hw'])} h, peak {T.fmt_n(c['peak'])}, avg {T.fmt_n(c['avg'])}"
            f"\n   {c['url']}" for i, c in enumerate(st.get("channels", [])[:80], 1)]
    await reply(update, "\n".join(rows) or "No channels yet.")


@owner_only
async def cmd_chart(update, context):
    png = await asyncio.to_thread(page.chart_png)
    if not png:
        await reply(update, "No chart yet (no data, or run: pip install matplotlib).")
        return
    await update.message.reply_photo(photo=io.BytesIO(png), caption=f"{T.config()['name']}: YouTube viewers over time")


@owner_only
async def cmd_page(update, context):
    html = await asyncio.to_thread(page.build_html)
    await update.message.reply_document(document=io.BytesIO(html.encode()), filename="bmsd-viewership.html",
                                        caption="Open in your browser. Send /page again for fresh numbers.")


VID = re.compile(r"(?:v=|youtu\.be/|/live/)([A-Za-z0-9_-]{11})")


@owner_only
async def cmd_edit(update, context):
    cmd = update.message.text.split()[0].lstrip("/").split("@")[0].lower()
    arg = " ".join(context.args or []).strip()
    cfg = T.config()
    if cmd in ("pause", "resume"):
        T.update_config(paused=cmd == "pause")
        await reply(update, "Paused (data kept)." if cmd == "pause" else "Tracking again.")
        return
    if not arg:
        await reply(update, f"Usage: /{cmd} <value>")
        return
    m = VID.search(arg)
    if cmd == "add":
        if m:
            T.update_config(videos=list(dict.fromkeys(cfg["videos"] + [m.group(1)])))
            await reply(update, f"Tracking stream {m.group(1)}.")
        else:
            T.update_config(channels=list(dict.fromkeys(cfg["channels"] + [arg.split()[0]])))
            await reply(update, f"Tracking {arg.split()[0]}'s live streams.")
    elif cmd == "exclude":
        item = m.group(1) if m else arg.lower()
        T.update_config(excluded=list(dict.fromkeys(cfg["excluded"] + [item])))
        with T._lock:
            for v in [v for v, s in T._live.items() if v.lower() == item.lower() or s.get("channel", "").lower() == item]:
                T._live.pop(v, None)
        await reply(update, f"Excluded '{item}'.")
    elif cmd == "official":
        T.update_config(official=list(dict.fromkeys(cfg["official"] + [arg.lower().lstrip("@")])))
        await reply(update, f"'{arg}' counts as official.")
    elif cmd == "phrase":
        T.update_config(match=list(dict.fromkeys(cfg["match"] + [arg.lower()])),
                        queries=list(dict.fromkeys(cfg["queries"] + [arg]))[:8])
        await reply(update, f"Also counting streams with '{arg}' in the title.")


@owner_only
async def cmd_health(update, context):
    with T._lock:
        n = len(T._live)
    await reply(update, f"Counting method: {T._method['value'] or 'not used yet (nothing live)'}\n"
                        f"Streams being counted: {n}\nLast check errors: {T._method['errors']}\n"
                        f"Counts every {T.FAST_SEC}s, searches every {T.DISCOVER_SEC}s.")


@owner_only
async def on_text(update, context):
    t = (update.message.text or "").lower()
    if any(w in t for w in ("peak", "average", "avg", "hours", "viewer", "stats", "how many", "numbers")):
        return await cmd_stats(update, context)
    if "live" in t:
        return await cmd_live(update, context)
    if "chart" in t or "graph" in t:
        return await cmd_chart(update, context)
    await cmd_help(update, context)


def main():
    os.makedirs(T.DATA, exist_ok=True)
    lock = open(os.path.join(T.DATA, "tracker.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("The tracker is already running.")
        raise SystemExit(1)
    T.config()
    T.run_forever()
    threading.Thread(target=dashboard, daemon=True).start()
    import tunnel
    tunnel.start(PORT)
    print(f"Tracking {T.config()['name']}: counts every {T.FAST_SEC}s, searches every {T.DISCOVER_SEC}s. "
          f"Dashboard http://localhost:{PORT}")
    token = os.getenv("TRACKER_BOT_TOKEN")
    if not token:
        print("Dashboard-only mode (no TRACKER_BOT_TOKEN): tracking + dashboard running.")
        threading.Event().wait()
    from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
    app = ApplicationBuilder().token(token).concurrent_updates(True).build()
    app.add_handler(CommandHandler(["start", "help"], cmd_help))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("live", cmd_live))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("chart", cmd_chart))
    app.add_handler(CommandHandler("page", cmd_page))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(CommandHandler(["add", "exclude", "official", "phrase", "pause", "resume"], cmd_edit))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()


if __name__ == "__main__":
    main()
