"""Run once before relying on the tracker:  python check.py
Checks YouTube live search and each way of counting viewers from this computer's network."""
import os
import time

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
import tracker as T  # noqa: E402

print("1. Live search (finds streams)...")
t0 = time.time()
try:
    found = T.search_live("BGMI")
    print(f"   OK: {len(found)} live BGMI streams in {time.time() - t0:.1f}s")
    for s in found[:3]:
        print(f"   {s['viewers']:>8,}  {s['channel']} | {s['title'][:60]}")
except Exception as e:
    found = []
    print(f"   FAILED: {e}")
if not found:
    raise SystemExit("No live streams to test counting with. Try again when BGMI streams are live.")
vid = found[0]["vid"]
print(f"\n2. Counting one stream ({vid}) every way:")
if os.getenv("YOUTUBE_API_KEY"):
    try:
        print(f"   YouTube Data API: {T.count_api([vid])[vid]}")
    except Exception as e:
        print(f"   YouTube Data API FAILED: {e}")
else:
    print("   YouTube Data API: no YOUTUBE_API_KEY (optional)")
for name, fn in (("Live counter (fast, no key)", T.count_innertube), ("Page read (slow)", T.count_ytdlp)):
    t0 = time.time()
    try:
        print(f"   {name}: {fn(vid)} in {time.time() - t0:.1f}s")
    except Exception as e:
        print(f"   {name} FAILED: {str(e)[:120]}")
print("\n3. BMSD streams live right now:")
cfg = T.config()
seen = set()
for q in cfg["queries"]:
    try:
        for s in T.search_live(q):
            if T.relevant(cfg, s) and s["vid"] not in seen:
                seen.add(s["vid"])
                print(f"   {s['viewers']:>8,}  {s['channel']} ({T.kind_of(cfg, s)}) | https://youtu.be/{s['vid']}")
    except Exception as e:
        print(f"   search '{q}' failed: {e}")
if not seen:
    print("   none right now (normal before matches start)")
