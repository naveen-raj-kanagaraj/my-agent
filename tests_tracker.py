import asyncio, os, types, time, io
os.environ.update(OWNER_TELEGRAM_ID="77", FAST_SEC="10")
ns = types.SimpleNamespace
R = []
def check(n, c): R.append(bool(c)); print(("PASS " if c else "FAIL ") + n)
import tracker as T
cfg = T.config()
check("BMSD config created", cfg["name"] == "BMSD 2026" and os.path.exists(T.CONFIG_PATH))
def st(vid, title, ch, v): return {"vid": vid, "title": title, "channel": ch, "channel_id": "", "viewers": v}
SEARCH = {"BMSD": [st("off1", "BMSD 2026 Semi Finals Day 3", "KRAFTON INDIA ESPORTS", 50000),
                   st("wp1", "BMSD Watch Party", "MortaL", 20000), st("x", "Free Fire Showdown", "FF", 9999)]}
T.search_live = lambda q: [dict(s) for s in SEARCH.get(q, [])]
T.check_channel = lambda h: None
COUNTS = {}
calls = []
def fake_inner(v):
    calls.append(v)
    if v in COUNTS and COUNTS[v] == "err": raise RuntimeError("blocked")
    return COUNTS.get(v)
T.count_innertube = fake_inner
T.count_ytdlp = lambda v: (_ for _ in ()).throw(RuntimeError("no"))
check("discovery finds BMSD streams only", T.discover() == 2 and set(T._live) == {"off1", "wp1"})
t0 = 1_760_000_000.0
seq = [(50000, 20000), (51000, 20500), (90000, 21000), (60000, 21000), (60000, None)]   # spike at 3rd check
for i, (a, b) in enumerate(seq):
    COUNTS["off1"] = a; COUNTS["wp1"] = b
    T.count_tick(t0 + 10 * i)
s = T.stats()
check("short spike caught by 10s counting", s["peak"] == 111000 and s["peak_at"] == t0 + 20)
check("counts every known stream each tick", calls.count("off1") == 5)
check("ended stream isn't zero-counted, removed after 3 misses", "wp1" in T._live)
COUNTS["wp1"] = None; T.count_tick(t0 + 50); T.count_tick(t0 + 60)
check("ended after 3 'not live' answers", "wp1" not in T._live)
COUNTS["off1"] = "err"
r = T.count_tick(t0 + 70)
check("network error: keeps last number briefly instead of zero", r["total"] == 60000)
r = T.count_tick(t0 + 200)
check("...but drops it if it can't be checked for a while", r["total"] == 0)
s = T.stats()
exp_hw = ((70000 + 71500 + 111000 + 81000 + 60000 + 60000 + 60000) * 10 + 60000 * 30) / 3600
check("hours watched from 10s ticks", abs(s["hw"] - exp_hw) < 0.01)
ch = {c["channel"]: c for c in s["channels"]}
check("per-channel peak and link", ch["KRAFTON INDIA ESPORTS"]["peak"] == 90000 and ch["KRAFTON INDIA ESPORTS"]["url"] == "https://youtu.be/off1"
      and ch["MortaL"]["peak"] == 21000)
check("kinds", ch["MortaL"]["kind"] == "watch party" and ch["KRAFTON INDIA ESPORTS"]["kind"] == "official")
txt = T.summary()
check("summary: event peak with seconds, Esports Charts; stale stream not listed as live", "Event so far: peak 111.0K at" in txt and "https://youtu.be/off1" not in txt
      and "escharts.com" in txt and "every 10s" in txt)
import page
h = page.build_html(refresh=30)
check("dashboard renders with refresh and links", 'http-equiv="refresh" content="30"' in h and "href='https://youtu.be/off1'" in h)
check("chart png", (page.chart_png() or b"")[:4] == b"\x89PNG")
# bot handlers
import main as M
class Msg:
    def __init__(s, text=""): s.text, s.sent, s.photos, s.docs = text, [], [], []
    async def reply_text(s, t, **k): s.sent.append((t, k))
    async def reply_photo(s, photo, caption=None): s.photos.append(photo.read())
    async def reply_document(s, document, filename=None, caption=None): s.docs.append(filename)
def U(uid, text=""): m = Msg(text); return ns(effective_user=ns(id=uid), message=m), m
u, m = U(77, "peak so far?"); asyncio.run(M.on_text(u, ns(args=[])))
check("plain question 'peak so far?' answers with stats, no link previews", "peak" in m.sent[0][0] and m.sent[0][1].get("disable_web_page_preview"))
u, m = U(5, "/stats"); asyncio.run(M.cmd_stats(u, ns(args=[])))
check("owner only", m.sent == [])
T._live["abcdefghijk"] = {"vid": "abcdefghijk", "channel": "Spam", "title": "x", "channel_id": "", "kind": "community", "viewers": 5, "misses": 0, "last_ok": time.time()}
u, m = U(77, "/exclude https://youtu.be/abcdefghijk"); asyncio.run(M.cmd_edit(u, ns(args=["https://youtu.be/abcdefghijk"])))
check("/exclude by link drops a live stream immediately", "abcdefghijk" in T.config()["excluded"] and "abcdefghijk" not in T._live)
u, m = U(77, "/exclude KRAFTON INDIA ESPORTS"); asyncio.run(M.cmd_edit(u, ns(args=["KRAFTON", "INDIA", "ESPORTS"])))
check("/exclude by channel name", "off1" not in T._live)
u, m = U(77, "/add @Jonathan"); asyncio.run(M.cmd_edit(u, ns(args=["@Jonathan"])))
check("/add channel", "@Jonathan" in T.config()["channels"])
u, m = U(77); asyncio.run(M.cmd_chart(u, ns(args=[]))); check("/chart image", m.photos and m.photos[0][:4] == b"\x89PNG")
u, m = U(77); asyncio.run(M.cmd_page(u, ns(args=[]))); check("/page file", m.docs == ["bmsd-viewership.html"])
u, m = U(77, "/pause"); asyncio.run(M.cmd_edit(u, ns(args=[]))); check("/pause", T.config()["paused"] and T.discover() == 0)
# live-only views
T.update_config(paused=False, excluded=[])
with T._lock: T._live.clear()
T._live["livevid0001"] = {"vid": "livevid0001", "channel": "NowLive", "title": "BMSD live", "channel_id": "", "kind": "community", "viewers": 777, "misses": 0, "last_ok": time.time()}
txt = T.summary()
check("summary lists only streams live right now", "NowLive" in txt and "MortaL" not in txt and "KRAFTON" not in txt.split("Event so far")[0])
h = page.build_html()
live_part = h.split("Live now:")[1].split("Viewers over time")[0]
check("dashboard live table = live streams only; ended ones collapsed", "NowLive" in live_part and "MortaL" not in live_part
      and "<details" in h and "Ended streams" in h)
import yt_dlp
class FakeYDL:
    def __init__(s, o): pass
    def __enter__(s): return s
    def __exit__(s, *a): pass
    def extract_info(s, url, download=False):
        return {"entries": [{"id": "a", "title": "BMSD live", "live_status": "is_live", "concurrent_view_count": 5000, "channel": "X"},
                            {"id": "b", "title": "BMSD day 2 (ended)", "live_status": "was_live", "view_count": 900000, "channel": "Y"},
                            {"id": "c", "title": "BMSD VOD", "live_status": None, "view_count": 2000000, "channel": "Z"},
                            {"id": "d", "title": "BMSD no count", "live_status": "is_live", "channel": "W"}]}
yt_dlp.YoutubeDL = FakeYDL
import importlib; importlib.reload(T) if False else None
res = T.__dict__["search_live"].__wrapped__("BMSD") if hasattr(T.search_live, "__wrapped__") else None
print(f"\n{sum(R)}/{len(R)} passed")
