"""Event dashboard (Esports-Charts style): one self-contained page that updates itself, plus a PNG chart for Telegram.

Only streams that are live right now are listed; ended streams only count toward the historical totals (peak, by day).
"""
import html
import io
import json
import re
import os
import threading
import time
from datetime import datetime

from core import events

REFRESH_SEC = 2
_cache = {}
_cache_lock = threading.Lock()


def _fmt_ts(ts):
    return datetime.fromtimestamp(ts, events.REPORT_TZ).strftime("%d %b %H:%M")


def _thin(rows, limit):
    step = max(1, len(rows) // limit)
    out = rows[::step]
    if rows and out[-1] is not rows[-1]:
        out.append(rows[-1])
    return out


BRAND = os.getenv("EVENT_BRAND", "letsgrowesports")
BRAND_URL = os.getenv("EVENT_BRAND_URL", "https://letsgrowesports.com")
SOCIAL = [("X", "https://x.com/letsgrowesports", "@letsgrowesports"),
          ("Instagram", "https://www.instagram.com/letsgrowesports.igc/", "@letsgrowesports.igc")]


HEAVY = ("series_all", "series_recent", "wp_series")


def live_data(key: str = None) -> dict:
    """What the page polls every few seconds: numbers + live streams + the last ~3 minutes of every graph (a few KB)."""
    d = data(key)
    out = {k: v for k, v in d.items() if k not in HEAVY}
    out["tail"] = (d.get("series_recent") or [])[-90:]
    ev = events.get(key)
    out["wp_tail"] = events.stream_tail(ev["key"], [w["vid"] for w in d.get("wp", [])]) if ev and d.get("official_live") else {}
    return out


def series_data(key: str = None) -> dict:
    d = data(key)
    return {k: d.get(k) for k in HEAVY}


def data(key: str = None) -> dict:
    """Everything the page shows, as JSON. Cached ~1.5s so many open tabs don't recompute stats."""
    ev = events.get(key)
    if not ev:
        return {"name": "No event", "ticks": 0, "now": time.time()}
    with _cache_lock:
        hit = _cache.get(ev["key"])
        if hit and time.time() - hit[0] < 1.5:
            return {**hit[1], "now": time.time()}
    st = events.stats(ev["key"])
    out = {"name": ev["name"], "ticks": st.get("ticks", 0), "now": time.time(), "every": events.FAST_SEC,
           "next_start": events.next_start(ev["key"]),
           "links": ev.get("links") or {}}
    if st.get("ticks"):
        live = [{"vid": s["vid"], "channel": s.get("channel", ""), "title": s.get("title", ""), "kind": s["kind"],
                 "viewers": s["viewers"], "url": events.yt_link(s["vid"]), "logo": events.avatar(s.get("channel_id", ""))}
                for s in st["live_now"]]
        series = [list(t) for t in st["series"]]
        recent = [t for t in series if t[0] >= series[-1][0] - 6 * 3600]
        out.update(
            live=live, method=st.get("method", ""), updated=st["last"]["ts"],
            peak=st["peak"], peak_when=events._when(st["peak_at"]), avg=round(st["avg_broadcast"]),
            peak_official=st["peak_official"], peak_watch=st["peak_watch"],
            days=[{"day": d["day"], "peak": d["peak"], "avg": round(d["avg_broadcast"]),
                   "at": datetime.fromtimestamp(d["peak_at"], events.REPORT_TZ).strftime("%I:%M %p") if d.get("peak_at") else "",
                   "peak_ts": d.get("peak_at"), "split": d.get("split", {})}
                  for d in st["days"]],
            series_all=_thin(series, 1500),
            series_recent=_thin([t for t in recent if t[0] < series[-1][0] - 200], 2400) + [t for t in recent if t[0] >= series[-1][0] - 200], official_live=st.get("official_live", False))
        lb = st.get("last_broadcast")
        if lb:
            tf = lambda ts: datetime.fromtimestamp(ts, events.REPORT_TZ)
            today = datetime.now(events.REPORT_TZ).date()
            dd = (today - tf(lb["end"]).date()).days
            dayw = "Today" if dd == 0 else "Yesterday" if dd == 1 else tf(lb["start"]).strftime("%a %d %b")
            out["last_broadcast"] = {
                "day": dayw, "date": tf(lb["start"]).strftime("%a %d %b").upper(),
                "when": f"{dayw}, {tf(lb['start']).strftime('%I:%M %p')} to {tf(lb['end']).strftime('%I:%M %p')} IST",
                "start": lb["start"], "end": lb["end"],
                "peak": lb["peak"], "peak_when": tf(lb["peak_at"]).strftime("%I:%M %p IST"),
                "split": lb["split"], "avg": round(lb.get("avg", 0)),
                "peak_official": lb.get("peak_official", 0), "peak_watch": lb.get("peak_watch", 0),
                "streams": [{"vid": x["vid"], "channel": x["channel"], "title": x["title"], "kind": x["kind"],
                             "logo": events.avatar(x.get("channel_id", "")), "avg": x.get("avg", 0),
                             "viewers": x["peak"], "at": tf(x["peak_at"]).strftime("%I:%M %p"), "url": events.yt_link(x["vid"])}
                            for x in lb["streams"][:100]]}
    if out.get("ticks"):
        if out.get("official_live"):
            pool = [x for x in out["live"] if x["kind"] == "watch party"] or [x for x in out["live"] if x["kind"] != "official"]
            t1 = time.time() + 5
            t0 = datetime.now(events.REPORT_TZ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()  # today (IST)
        elif out.get("last_broadcast"):
            lb = out["last_broadcast"]
            pool = [x for x in lb["streams"] if x["kind"] == "watch party"] or [x for x in lb["streams"] if x["kind"] != "official"]
            t0, t1 = lb["start"] - 60, lb["end"] + 60
        else:
            pool, t0, t1 = [], 0, 0
        wp = sorted(pool, key=lambda x: -x["viewers"])[:8]
        ser = events.stream_series(ev["key"], [w["vid"] for w in wp], t0, t1)
        peaks = {v: max(p[1] for p in pts) for v, pts in ser.items()}
        out["wp"] = [{"vid": w["vid"], "channel": w["channel"], "viewers": w["viewers"], "url": w["url"], "logo": w.get("logo", ""),
                      "peak": max(peaks.get(w["vid"], 0), w["viewers"])} for w in wp]
        out["wp_series"] = ser
    if ev["key"] == "bmsd":
        out["roster"] = _roster(out)
    with _cache_lock:
        _cache[ev["key"]] = (time.time(), out)
    return out


def _roster(out: dict) -> list:
    """Every permitted watch-party streamer: live now / ended (peak this broadcast) / yet to start."""
    n = events._norm
    countdown = bool(out.get("next_start")) and not out.get("official_live")
    live = [x for x in out.get("live", []) if x["kind"] != "official"]
    lb = out.get("last_broadcast") or {}
    done = [] if countdown else [x for x in lb.get("streams", []) if x["kind"] != "official"]
    rows = []
    for token, name, handle in events.ROSTER:
        card = events.channel_card(handle)
        if card.get("name") and token not in n(card["name"]) and n(name)[:5] not in n(card["name"]):
            card = {}
        lv = [x for x in live if token in n(x["channel"])]
        pk = [x for x in done if token in n(x["channel"])]
        logo = card.get("logo") or next((x.get("logo") for x in lv + pk if x.get("logo")), "")
        url = (lv or pk)[0]["url"] if (lv or pk) else (f"https://www.youtube.com/{handle}" if handle else "")
        r = {"name": name, "logo": logo, "url": url, "vid": (lv or pk or [{}])[0].get("vid", "")}
        if lv:
            r.update(status="live", viewers=sum(x["viewers"] for x in lv), peak=max(x["viewers"] for x in pk) if pk else 0)
            r["peak"] = max(r["peak"], r["viewers"])
        elif pk:
            r.update(status="ended", viewers=0, peak=max(x["viewers"] for x in pk))
        else:
            r.update(status="upcoming", viewers=0, peak=0)
        rows.append(r)
    order = {"live": 0, "ended": 1, "upcoming": 2}
    rows.sort(key=lambda r: (order[r["status"]], -r["viewers"], -r["peak"], r["name"].lower()))
    return rows


def _social() -> str:
    return "".join(f'<a class="soc" href="{html.escape(u, quote=True)}" target="_blank" rel="noopener">'
                   f'<b>{html.escape(n.upper())}</b><span>{html.escape(h)}</span></a>' for n, u, h in SOCIAL)


def build_demo_html(style: str = "v1", logos: dict = None) -> str:
    """Self-contained page with generated data (no server), for testing the layout and graphs.
    logos: {channel handle: base64 webp} embedded so the demo shows real channel logos offline."""
    names = {h: n for _, n, h in events.ROSTER if h}
    dl = {names[h]: "data:image/webp;base64," + b for h, b in (logos or {}).items() if h in names}
    if (logos or {}).get("@KRAFTON"):
        dl["KRAFTON INDIA ESPORTS"] = "data:image/jpeg;base64," + logos["@KRAFTON"]
    html_ = build_html("bmsd", live=False, style=style).replace("const DEMO=false, DLOGO={}", "const DEMO=true, DLOGO=" + json.dumps(dl))
    return re.sub(r"TITLE='[^']*'", "TITLE='BMSD 2026'", html_, count=1).replace("No event", "BMSD 2026")


ELOGO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "eventlogos")


def _elogos(embed: bool = False) -> dict:
    """Event logos for the history section: served files on the live site, embedded for snapshots and demos."""
    import base64
    out = {}
    for f in sorted(os.listdir(ELOGO_DIR)) if os.path.isdir(ELOGO_DIR) else []:
        k = f.rsplit(".", 1)[0]
        if embed:
            out[k] = "data:image/webp;base64," + base64.b64encode(open(os.path.join(ELOGO_DIR, f), "rb").read()).decode()
        else:
            out[k] = f"elogo/{f}"
    return out


def build_html(key: str = None, live: bool = False, style: str = None) -> str:
    """live=True: the page re-reads ./data every REFRESH_SEC seconds. Otherwise a snapshot (e.g. a file sent on Telegram)."""
    d = data(key)
    payload = json.dumps({"name": d.get("name"), "ticks": d.get("ticks", 0), "now": d.get("now")} if live else d).replace("</", "<\\/")
    return (PAGE.replace("__TITLE__", html.escape(d.get("name", "Event")))
                .replace("__DATA__", payload)
                .replace("__LIVE__", "true" if live else "false")
                .replace("__ELOGO__", json.dumps(_elogos(embed=not live)))
                .replace("__V2__", "true" if (style or os.getenv("EVENT_STYLE", "v1")) == "v2" else "false")
                .replace("__ROSTERN__", json.dumps([n for _, n, _ in events.ROSTER]))
                .replace("__REFRESH__", str(REFRESH_SEC))
                .replace("__SOCIAL__", _social())
                .replace("__BRAND__", html.escape(BRAND)).replace("__BRANDURL__", html.escape(BRAND_URL, quote=True)))


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>__TITLE__ live viewership | __BRAND__</title>
<meta name="description" content="Live concurrent viewers across every __TITLE__ YouTube stream: official broadcast and watch parties, updated every few seconds.">
<meta property="og:title" content="__TITLE__ live viewership"><meta property="og:description" content="Official vs watch parties, live. Who is winning the watch party battle?">
<meta name="theme-color" content="#07051a">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@500;600;700&family=Share+Tech+Mono&display=swap" rel="stylesheet">
<style>
:root{color-scheme:dark;--bg:#0b0b12;--bg2:#121219;--card:#13131c;--card2:#1a1a26;--ink:#eeeef5;--muted:#8d8ca3;--line:#262636;
--lime:#b6f23a;--purple:#7c5cff;--cyan:#4cc9f0;--orange:#ff8a3d;--red:#ff4d5e;--up:#b6f23a;--down:#ff4d5e}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 "Chakra Petch",system-ui,sans-serif}
body{background:radial-gradient(800px 380px at 80% -15%,rgba(124,92,255,.12),transparent 60%),var(--bg);min-height:100vh}
body:before{content:"";position:fixed;inset:0;pointer-events:none;z-index:50;background:repeating-linear-gradient(0deg,rgba(255,255,255,.012) 0 1px,transparent 1px 3px)}
a{color:var(--cyan);text-decoration:none}a:hover{text-decoration:underline}
.mono{font-family:"Share Tech Mono",ui-monospace,monospace}
.wrap{max-width:1180px;margin:0 auto;padding:0 16px 40px}
.bar{position:sticky;top:0;z-index:20;background:rgba(11,11,18,.9);backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
.bar .in{max-width:1180px;margin:0 auto;padding:10px 16px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.title{margin-right:auto;line-height:1.1}
.brand{display:block;font-family:"Share Tech Mono",monospace;font-size:12px;color:var(--lime);letter-spacing:.04em}
.title h1{margin:2px 0 0;font-size:19px;font-weight:700;text-transform:uppercase;letter-spacing:.02em}
.title h1 span{color:var(--muted);font-weight:600}
.pill{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border:1px solid var(--line);background:var(--card);font:12px "Share Tech Mono",monospace;white-space:nowrap;clip-path:polygon(6px 0,100% 0,100% calc(100% - 6px),calc(100% - 6px) 100%,0 100%,0 6px)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--red);animation:pulse 1.4s infinite}
.pill.off .dot{background:var(--muted);animation:none}.pill.warn{color:var(--orange)}.pill.warn .dot{background:var(--orange)}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(255,77,94,.7)}70%{box-shadow:0 0 0 8px rgba(255,77,94,0)}100%{box-shadow:0 0 0 0 rgba(255,77,94,0)}}
.ring{width:14px;height:14px}.ring circle{fill:none;stroke:var(--line);stroke-width:3}.ring .p{stroke:var(--lime);stroke-linecap:round;transform:rotate(-90deg);transform-origin:50% 50%}
.follow{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:12px;font:12px "Share Tech Mono",monospace;color:var(--muted)}.follow>span{margin-right:auto}
.soc{display:inline-flex;gap:6px;padding:5px 11px;border:1px solid var(--line);background:var(--card);color:var(--ink);font:12px "Share Tech Mono",monospace}
.soc b{color:var(--lime);font-weight:400}.soc span{color:var(--muted)}.soc:hover{border-color:var(--lime);text-decoration:none}
@media(max-width:600px){.follow>span{width:100%}.soc span{display:none}}
.card{position:relative;background:var(--card);border:1px solid var(--line);padding:14px;min-width:0;backdrop-filter:blur(4px)}
.card:before,.card:after{content:"";position:absolute;width:12px;height:12px;border:2px solid var(--lime);pointer-events:none}
.card:before{top:-1px;left:-1px;border-right:0;border-bottom:0}.card:after{bottom:-1px;right:-1px;border-left:0;border-top:0}
.lbl{font:12px "Share Tech Mono",monospace;color:var(--red);letter-spacing:.08em;text-transform:uppercase}
.hero{display:grid;grid-template-columns:1.35fr 1fr;gap:12px;margin:12px 0}
@media(max-width:780px){.hero{grid-template-columns:1fr}}
.big .v{font:700 58px/1 "Chakra Petch",sans-serif;letter-spacing:-.01em;margin:8px 0 6px;font-variant-numeric:tabular-nums;text-shadow:0 0 18px rgba(124,92,255,.3)}
@media(max-width:600px){.big .v{font-size:44px}}
.delta{font:13px "Share Tech Mono",monospace}.delta.up{color:var(--up)}.delta.down{color:var(--down)}.delta.flat{color:var(--muted)}
.split{display:flex;height:10px;overflow:hidden;background:var(--line);margin:14px 0 8px}.split div{transition:width .6s}
.legend{display:flex;gap:14px;flex-wrap:wrap;font:12px "Share Tech Mono",monospace;color:var(--muted)}.legend b{color:var(--ink);font-weight:400}
.sw{display:inline-block;width:9px;height:9px;margin-right:5px;vertical-align:-1px}
.kpis{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.kpi .v{font:700 24px "Chakra Petch",sans-serif;margin-top:4px;font-variant-numeric:tabular-nums}.kpi .s{color:var(--muted);font-size:12px}
.head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px}.head>div:first-child{margin-right:auto}
h2{font:700 15px "Chakra Petch",sans-serif;text-transform:uppercase;letter-spacing:.04em;margin:0}
.tabs{display:flex;gap:0;margin-bottom:12px;border-bottom:1px solid var(--line);overflow-x:auto}
.tabs button{all:unset;cursor:pointer;padding:9px 14px;font:700 13px "Chakra Petch",sans-serif;text-transform:uppercase;color:var(--muted);border-bottom:3px solid transparent;white-space:nowrap}
.tabs button.on{color:var(--ink);border-color:var(--lime);background:linear-gradient(0deg,rgba(182,242,58,.10),transparent)}
.seg{display:inline-flex;border:1px solid var(--line)}
.seg button{all:unset;cursor:pointer;padding:5px 11px;font:12px "Share Tech Mono",monospace;color:var(--muted)}
.seg button.on{background:var(--lime);color:#0a0a14}.seg button:disabled{opacity:.35;cursor:default}
.cv{font:700 28px "Chakra Petch",sans-serif;font-variant-numeric:tabular-nums;margin-top:2px}.cv small{font:12px "Share Tech Mono",monospace;color:var(--muted);margin-left:8px}
.chart{position:relative;height:320px}.chart canvas{width:100%;height:100%;display:block;touch-action:pan-y}
@media(max-width:600px){.chart{height:240px}}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.chip{all:unset;cursor:pointer;display:inline-flex;align-items:center;gap:6px;padding:4px 9px;border:1px solid var(--line);font:12px "Share Tech Mono",monospace;background:var(--card2)}
.chip.offc{opacity:.35}.chip i{width:10px;height:3px;display:inline-block}
.btn{all:unset;cursor:pointer;display:inline-flex;align-items:center;gap:6px;padding:7px 14px;font:700 12px "Chakra Petch",sans-serif;text-transform:uppercase;letter-spacing:.04em;background:var(--lime);color:#0a0a14;clip-path:polygon(8px 0,100% 0,100% calc(100% - 8px),calc(100% - 8px) 100%,0 100%,0 8px)}
.btn.ghost{background:transparent;color:var(--ink);border:1px solid var(--line);clip-path:none}.btn.sm{padding:4px 9px;font-size:11px}
table{width:100%;border-collapse:separate;border-spacing:0 5px}
th{font:12px "Share Tech Mono",monospace;color:#0a0a14;background:var(--lime);text-transform:uppercase;padding:7px 8px;text-align:left;letter-spacing:.04em}
th.num,td.num{text-align:right}
td{padding:8px;background:var(--card2);border-top:1px solid var(--line);border-bottom:1px solid var(--line);white-space:nowrap}
td.t{white-space:normal;min-width:0}.lg{width:22px;height:22px;border-radius:50%;vertical-align:-6px;margin-right:7px;background:var(--line);object-fit:cover}td.num{font:700 15px "Chakra Petch",sans-serif;font-variant-numeric:tabular-nums}
.rk{font:700 14px "Chakra Petch",sans-serif;color:#0a0a14;text-align:center;width:34px}
.rk.official{background:var(--orange)}.rk.watch{background:var(--cyan)}.rk.community{background:var(--purple);color:#fff}
.ch{font-weight:700;text-transform:uppercase;letter-spacing:.02em}.st{color:var(--muted);font-size:12px;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:520px}
.lv{display:inline-flex;align-items:center;gap:5px;margin-left:8px;padding:1px 7px;font:700 11px "Share Tech Mono",monospace;color:#fff;background:rgba(255,77,94,.15);border:1px solid #ff4d5e;box-shadow:0 0 10px rgba(255,77,94,.55);animation:lvb 1.2s ease-in-out infinite;vertical-align:2px}
.lv i{width:7px;height:7px;border-radius:50%;background:#ff4d5e;box-shadow:0 0 8px #ff4d5e}
@keyframes lvb{50%{box-shadow:0 0 2px rgba(255,77,94,.2);opacity:.65}}
.tag{font:11px "Share Tech Mono",monospace;padding:1px 6px;margin-left:6px;border:1px solid currentColor}
.tag.official{color:var(--orange)}.tag.watch{color:var(--cyan)}.tag.community{color:#a78bfa}
.mini{height:3px;background:linear-gradient(90deg,var(--purple),var(--lime));margin-top:5px;transition:width .6s}
tr.fu td.num{animation:fu 1.2s}tr.fd td.num{animation:fd 1.2s}@keyframes fu{0%{color:var(--up)}}@keyframes fd{0%{color:var(--down)}}
.q{background:var(--card2);border:1px solid var(--line);padding:6px 10px;color:var(--ink);font:12px "Share Tech Mono",monospace;width:180px;max-width:100%}
.more{all:unset;cursor:pointer;display:block;margin:8px auto 0;padding:6px 14px;border:1px solid var(--line);font:12px "Share Tech Mono",monospace;color:var(--muted)}
.grid2{display:grid;grid-template-columns:1fr;gap:12px;margin-top:12px}
.muted{color:var(--muted)}.scroll{overflow-x:auto}
.cd{text-align:center;border-color:#ff4d5e}.cdv{font:700 54px "Chakra Petch",sans-serif;letter-spacing:.04em;color:#fff;text-shadow:0 0 18px rgba(255,77,94,.5);margin:6px 0}
@media(max-width:600px){.cdv{font-size:38px}}
.hgrid{display:grid;grid-template-columns:1.6fr 1fr;gap:12px;margin:8px 0}.hgrid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:8px}.tiles.t2{grid-template-columns:1fr 1fr}
.hchart{position:relative;height:340px;margin-top:12px}.hchart canvas{width:100%;height:100%;display:block}
.rank{display:grid;grid-template-columns:1fr 1fr;gap:4px 18px}.rrow{display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid var(--line)}
.rrow .rk{width:28px;height:26px;display:inline-flex;align-items:center;justify-content:center;background:var(--card2);color:var(--ink)}.rrow .rk.r1{background:var(--lime);color:#0a0a14}.rrow .rk.r2{background:var(--cyan);color:#0a0a14}.rrow .rk.r3{background:var(--orange);color:#0a0a14}
.rrow .rn{flex:1;font-weight:700;text-transform:uppercase;min-width:0}.rrow b{font:700 16px "Chakra Petch",sans-serif}
.tagx{font:11px "Share Tech Mono",monospace;padding:1px 6px;border:1px solid currentColor;margin-left:6px;white-space:nowrap}.tagx.lime{color:var(--lime)}.tagx.red{color:var(--red)}
@media(max-width:700px){.hgrid,.hgrid2,.rank{grid-template-columns:1fr}.hchart{height:300px}.tiles{grid-template-columns:repeat(2,1fr)}}
.demo{position:fixed;left:0;right:0;bottom:0;z-index:70;display:flex;gap:8px;align-items:center;justify-content:center;padding:8px max(16px,env(safe-area-inset-right,0px)) calc(8px + env(safe-area-inset-bottom,0px)) max(16px,env(safe-area-inset-left,0px));background:#ff4d5e;color:#fff;font:12px "Share Tech Mono",monospace}
.demo button{all:unset;cursor:pointer;padding:3px 10px;border:1px solid #fff}.demo button.on{background:#fff;color:#ff4d5e}
.race{position:relative;margin-top:4px;transition:height .4s}.rr{position:absolute;left:0;right:0;top:0;display:flex;align-items:center;gap:8px;transition:transform .7s cubic-bezier(.2,.8,.2,1)}
.rr .rp{width:22px;text-align:center;font:700 14px "Chakra Petch",sans-serif;color:var(--muted)}.rr .lg{width:28px;height:28px;margin:0;flex:none}.rr .lg.ini{display:inline-flex;align-items:center;justify-content:center;font-size:10px;font-weight:700}
.rr .rb{flex:1;height:100%;min-width:0}.rr .rbf{height:100%;display:flex;align-items:center;padding:0 10px;transition:width .7s cubic-bezier(.2,.8,.2,1);clip-path:polygon(0 0,100% 0,calc(100% - 8px) 100%,0 100%)}
.rr .rnm{font:700 13px "Chakra Petch",sans-serif;text-transform:uppercase;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-shadow:0 1px 2px rgba(0,0,0,.6)}
.rr .rv{width:84px;text-align:right;font:700 16px "Chakra Petch",sans-serif;font-variant-numeric:tabular-nums}.rr .rv.bump{animation:bump .5s}@keyframes bump{30%{color:var(--lime)}}
@media(max-width:600px){.rr .rv{width:64px;font-size:13px}.rr .lg{width:22px;height:22px}.rr .rnm{font-size:11px}}
@media(prefers-reduced-motion:reduce){.rr,.rr .rbf{transition:none}}
.foot{font-size:12px;color:var(--muted);margin-top:14px}.disc{font-size:11px;border-top:1px solid var(--line);margin-top:10px;padding-top:10px}
@media(max-width:600px){.hide-m{display:none}.st{max-width:52vw;font-size:11px}td{padding:6px 5px}th{padding:5px}.title h1{font-size:15px}
 .bar .in{gap:5px;padding:7px 12px}.title{width:100%}.pill{font-size:11px;padding:3px 7px}#nx{display:none!important}
 .wrap{padding:0 10px 30px}.follow{margin-top:8px;gap:6px}.follow>span{display:none}.soc{padding:4px 9px}
 .card{padding:10px}.hero{gap:8px;margin:8px 0}.kpis{gap:8px}.kpi .v{font-size:19px}.kpi .s{display:none}.lbl{font-size:11px}
 .big .v{font-size:40px;margin:4px 0}.split{margin:10px 0 6px}.legend{gap:8px;font-size:11px}
 .tabs button{padding:8px 9px;font-size:12px}.tabs{margin-bottom:8px}.cv{font-size:22px}.head{gap:6px;margin-bottom:6px}
 .seg button{padding:4px 8px;font-size:11px}.btn.sm{padding:4px 8px}.chips{gap:4px}.chip{font-size:11px;padding:3px 7px}
 td.num{font-size:14px}.rk{width:26px;font-size:13px}.lg{width:18px;height:18px;margin-right:5px}.ch{font-size:13px}.tag{display:none}
 .grid2{gap:8px;margin-top:8px}.q{width:100%}.foot{font-size:11px}}
.modal{position:fixed;inset:0;z-index:60;background:rgba(3,2,12,.82);display:none;align-items:center;justify-content:center;padding:16px}
.modal.on{display:flex}.mbox{background:var(--bg2);border:1px solid var(--line);padding:14px;max-width:440px;width:100%;max-height:94vh;overflow:auto}
.mbox img{width:100%;display:block;border:1px solid var(--line);margin:10px 0}.mrow{display:flex;gap:8px;flex-wrap:wrap}
</style></head><body>
<div class="bar"><div class="in">
 <div class="title"><a class="brand" href="__BRANDURL__" target="_blank" rel="noopener">__BRAND__</a><h1>__TITLE__ <span>live viewership</span></h1></div>
 <span id="st" class="pill"><span class="dot"></span><span id="stt">Live</span></span>
 <span class="pill" title="Time since the newest reading">UPDATED <span id="ago">-</span></span>
 <span class="pill" id="nx"><svg class="ring" viewBox="0 0 20 20"><circle cx="10" cy="10" r="7"/><circle class="p" id="rp" cx="10" cy="10" r="7" stroke-dasharray="44" stroke-dashoffset="0"/></svg>NEXT <span id="nxt">-</span></span>
</div></div>
<div class="wrap" style="padding-bottom:0"><div class="follow"><span>// FOLLOW FOR LIVE ESPORTS NUMBERS</span>__SOCIAL__</div></div>
<div class="wrap" id="app"></div>
<div class="modal" id="modal"><div class="mbox"><div class="head"><div><h2 id="mt">Share</h2></div><button class="btn ghost sm" id="mclose">Close</button></div>
 <img id="mimg" alt="Share card"><div class="mrow"><button class="btn" id="mig">Instagram</button><button class="btn" id="mxb">X</button><button class="btn ghost" id="mdl">Download</button></div>
 <p class="muted" id="mhint" style="font-size:12px;margin:10px 0 0">On your phone, Instagram and X open the share menu with the image attached: pick Instagram (Story or Post) or X.</p></div></div>
<script>
const DEMO=false, DLOGO={}, ELOGO=__ELOGO__, V2=__V2__, ROSTERN=__ROSTERN__;
const LIVE=__LIVE__||DEMO, EVERY=__REFRESH__*1000, URLX='https://live.letsgrowesports.com', BRAND='__BRAND__', TITLE='__TITLE__';
let D=__DATA__, prev={}, prevTotal=null, view='total', range='full', wpAll=false, kind='all', q='', skew=0, lastFetch=Date.now(), failing=false, mode=null, showAll=false, hover=null, hidden={};
const PAL=['#b6f23a','#4cc9f0','#ff8a3d','#ff5fa2','#a78bfa','#ffd23f','#2dd4bf','#ff6b6b'];
const fmt=n=>{n=+n||0;return n>=1e7?(n/1e7).toFixed(2)+' Cr':n>=1e5?(n/1e5).toFixed(2)+' L':n>=1e3?(n/1e3).toFixed(1)+'K':Math.round(n)+''};
const full=n=>Math.round(+n||0).toLocaleString('en-IN');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const K={official:'official','watch party':'watch',community:'community'};
const css=v=>getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const nowS=()=>Date.now()/1000-skew;
function tween(el,to){const from=+el.dataset.v||0;el.dataset.v=to;if(from===to){el.textContent=full(to);return}
 const t0=performance.now();const st=t=>{const k=Math.min(1,(t-t0)/600);el.textContent=full(from+(to-from)*(1-Math.pow(1-k,3)));if(k<1)requestAnimationFrame(st)};requestAnimationFrame(st)}
function isOff(){return !D.official_live&&D.last_broadcast}
const HIST=[['LAUNCH','21',540],['BGIS','21',460],['BMPS','22',305],['BMSD','22',315],['BGIS','23',235],['BMPS','23',201],['INKR','23',178],['BGIS','24',275],['BMPS','24',495],['BGIS','25',485],['BMPS','25',320],['BMSD','25',380],['BMIC','25',372],['BGIS','26',578],['BMPS','26',730],['BMSD','26',450]];
const HNAME={LAUNCH:'BGMI Launch Party',BGIS:'BGIS',BMPS:'BMPS',BMSD:'BMSD',INKR:'INKR Invitational',BMIC:'BMIC'};
function hist(){const h=HIST.map(x=>x.slice());const cur=Math.round((D.peak||0)/1000);if(cur>h[15][2])h[15][2]=cur;return h}
const EIMG={};function elogo(k){const u=ELOGO[k];if(!u)return null;let im=EIMG[k];if(!im){im=EIMG[k]=new Image();im.onload=()=>{drawHistCanvas()};im.src=u}return im.complete&&im.naturalWidth?im:null}
const ekey=x=>x[0]+x[1];
function drawHist(ctx,W,H,fs){fs=fs||1;const h=hist(),n=h.length,pl=34*fs,pr=34*fs,LS=Math.min(54*fs,(W-68*fs)/(n-1)*.86),pt=46*fs,pb=LS+30*fs,cw=W-pl-pr,ch=H-pt-pb,max=820;
 const X=i=>pl+i*cw/(n-1),Y=v=>pt+ch-v/max*ch,top=h.reduce((a,x,i)=>x[2]>h[a][2]?i:a,0);ctx.clearRect(0,0,W,H);
 ctx.strokeStyle=css('--line');ctx.lineWidth=1;ctx.fillStyle=css('--muted');ctx.font=`${11*fs}px "Share Tech Mono",monospace`;ctx.textAlign='left';ctx.textBaseline='bottom';
 [200,400,600,800].forEach(v=>{ctx.globalAlpha=.6;ctx.beginPath();ctx.moveTo(pl,Y(v));ctx.lineTo(W-pr,Y(v));ctx.stroke();ctx.globalAlpha=1;ctx.fillText(v+'K',pl+2,Y(v)-2)});
 ctx.beginPath();h.forEach((x,i)=>i?ctx.lineTo(X(i),Y(x[2])):ctx.moveTo(X(i),Y(x[2])));ctx.lineTo(X(n-1),pt+ch);ctx.lineTo(X(0),pt+ch);ctx.closePath();
 const g=ctx.createLinearGradient(0,pt,0,pt+ch);g.addColorStop(0,'rgba(124,92,255,.45)');g.addColorStop(1,'rgba(124,92,255,0)');ctx.fillStyle=g;ctx.fill();
 ctx.beginPath();h.forEach((x,i)=>i?ctx.lineTo(X(i),Y(x[2])):ctx.moveTo(X(i),Y(x[2])));ctx.strokeStyle='#b6f23a';ctx.lineWidth=3*fs;ctx.shadowColor='#b6f23a';ctx.shadowBlur=10*fs;ctx.stroke();ctx.shadowBlur=0;
 const small=W/fs<620;ctx.textAlign='center';
 h.forEach((x,i)=>{const last=i===n-1,hi=i===top;ctx.beginPath();ctx.arc(X(i),Y(x[2]),(hi||last?6:4)*fs,0,7);ctx.fillStyle=last?'#ff4d5e':'#b6f23a';ctx.fill();
  if(!small||hi||last||i%2===0){ctx.fillStyle=last?'#ff4d5e':hi?'#b6f23a':css('--ink');ctx.font=`700 ${(small?10:12)*fs}px "Chakra Petch",sans-serif`;ctx.textBaseline='bottom';ctx.fillText(x[2]+'K',X(i),Y(x[2])-8*fs)}
  const im=elogo(ekey(x)),ly=pt+ch+8*fs;
  if(im){const r=Math.min(LS/im.naturalWidth,LS/im.naturalHeight),w=im.naturalWidth*r,hh=im.naturalHeight*r;ctx.globalAlpha=last||hi?1:.85;ctx.drawImage(im,X(i)-w/2,ly+(LS-hh)/2,w,hh);ctx.globalAlpha=1}
  else{ctx.fillStyle=css('--muted');ctx.font=`700 ${(small?8:11)*fs}px "Chakra Petch",sans-serif`;ctx.textBaseline='middle';ctx.fillText(x[0]==='LAUNCH'?(small?'LP':'LAUNCH'):x[0],X(i),ly+LS/2)}
  ctx.textBaseline='top';ctx.fillStyle=last?'#ff4d5e':hi?'#b6f23a':css('--muted');ctx.font=`${(small?9:11)*fs}px "Share Tech Mono",monospace`;ctx.fillText((small?'':x[0]+' ')+`'${x[1]}`,X(i),ly+LS+4*fs)});
 ctx.textAlign='left';ctx.textBaseline='top';ctx.fillStyle='#b6f23a';ctx.font=`700 ${13*fs}px "Chakra Petch",sans-serif`;ctx.fillText(`ALL-TIME HIGH ${h[top][2]}K // ${HNAME[h[top][0]]} 20${h[top][1]}`,pl,6*fs)}
function historyHTML(){const h=hist(),top=[...h].sort((a,b)=>b[2]-a[2]),best={},yr={};
 h.forEach(x=>{if(!best[x[0]]||x[2]>best[x[0]][2])best[x[0]]=x;const y='20'+x[1];if(!yr[y]||x[2]>yr[y][2])yr[y]=x});
 const eimg=(k,sz)=>ELOGO[k]?`<img src="${ELOGO[k]}" alt="" style="height:${sz}px;width:${sz}px;object-fit:contain;flex:none">`:'';
 const tile=(l,v,s,c,k)=>`<div style="display:flex;gap:10px;align-items:center">${k?eimg(k,44):''}<div><div class="muted mono" style="font-size:12px">${l}</div><div style="font:700 26px 'Chakra Petch',sans-serif;color:${c||'var(--ink)'}">${v}</div><div class="muted" style="font-size:12px">${s}</div></div></div>`;
 const ath=top[0];
 return `<div class="card" style="margin-top:12px" id="histCard"><div class="head"><div><div class="lbl">// BGMI viewership till date</div><h2 style="font-size:22px;margin-top:4px">Peak concurrent viewers, every KRAFTON India event</h2></div><button class="btn sm" id="shareHist">Share</button></div>
 <div class="hchart"><canvas id="hc"></canvas></div>
 <div class="hgrid"><div><div class="lbl">// All-time high // ${HNAME[ath[0]]} 20${ath[1]}</div><div class="big"><div class="v">${ath[2]}K</div></div></div>
 <div><div class="lbl">// Events till date</div><div class="big"><div class="v" style="color:var(--lime)">${h.length}</div></div><div class="muted">2021 to 2026</div></div></div>
 <div class="hgrid2"><div class="card"><div class="lbl">// Year-wise peak</div><div class="tiles">${Object.entries(yr).map(([y,x])=>tile(y,x[2]+'K',HNAME[x[0]].toUpperCase(),y==='2026'?'var(--lime)':'')).join('')}</div></div>
 <div class="card"><div class="lbl">// Series best</div><div class="tiles t2">${['BMPS','BGIS','BMSD','BMIC'].map(k=>tile(k,best[k][2]+'K',(k==='BMSD'&&best[k][1]==='26'?'<span style="color:var(--red)">\u25CF ONGOING</span> ':'')+'20'+best[k][1],k==='BMSD'&&best[k][1]==='26'?'var(--red)':'',k+best[k][1])).join('')}</div></div></div>
 <div class="lbl" style="margin:10px 0 6px">// All-time ranking, peak concurrent viewers</div>
 <div class="rank">${top.map((x,i)=>`<div class="rrow"><span class="rk ${i===0?'r1':i===1?'r2':i===2?'r3':''}">${i+1}</span>${eimg(ekey(x),30)}<span class="rn">${HNAME[x[0]]} 20${x[1]}${i===0?' <span class="tagx lime">ALL-TIME HIGH</span>':''}${x[0]==='BMSD'&&x[1]==='26'?' <span class="tagx red">\u25CF ONGOING</span>':''}</span><b>${x[2]}K</b></div>`).join('')}</div>
 <div class="muted" style="font-size:11px;margin-top:8px">Earlier events: peak concurrent viewers as reported for each event. BMSD 2026 updates from this tracker.</div></div>`}
function cdMode(){return !!(D.next_start&&!D.official_live&&D.next_start-nowS()>0)}
function render(){
 const app=document.getElementById('app');
 if(cdMode()){
  if(mode!=='cd'){mode='cd';app.innerHTML=`<div class="card cd" id="cd" style="margin-top:12px"><div class="lbl">// Grand finals go live in</div><div class="cdv mono" id="cdv"></div><div class="muted" id="cdw"></div></div>${historyHTML()}
   <div class="card" id="wpCard" style="margin-top:12px"><div class="head"><div><h2 id="wph">Watch party streamers</h2><div class="muted" style="font-size:12px">Official watch parties for the grand finals.</div></div><button class="btn sm" id="shareBoard">Share</button></div>
   <div class="scroll"><table><thead><tr><th>#</th><th>Streamer</th><th class="num" id="wpth">Status</th><th class="num hide-m">Peak</th><th></th></tr></thead><tbody id="wprows"></tbody></table></div><button class="more" id="wpmore"></button></div>
   <div class="foot" id="foot"><div class="follow"><span>FOLLOW __BRAND__</span>__SOCIAL__</div><div class="disc">Unofficial viewership tracker by <a href="__BRANDURL__" target="_blank" rel="noopener">__BRAND__</a>. Not affiliated with or endorsed by KRAFTON.</div></div>`;
   document.getElementById('shareHist').onclick=()=>openShare('history');window.addEventListener('resize',drawHistCanvas)}
  wpRows();drawHistCanvas();return}
 if(mode==='cd'){mode=null;app.innerHTML=''}
 if(!D.ticks){app.innerHTML='<div class="card" style="margin-top:12px">No data yet. Numbers are recorded only while the official broadcast is live.</div>';return}
 const off=isOff(),LB=D.last_broadcast||{};
 const m=off?'off':'on';if(mode!==m){mode=m;app.innerHTML='';prev={};prevTotal=null;showAll=false;range='full'}
 const live=off?LB.streams:(D.live||[]),tot=off?LB.peak:live.reduce((a,s)=>a+s.viewers,0);
 const by=off?{official:LB.split.official,'watch party':LB.split.watch,community:LB.split.community}:{official:0,'watch party':0,community:0};
 if(!off)live.forEach(s=>by[s.kind]=(by[s.kind]||0)+s.viewers);
 if(!document.getElementById('big')){
  app.innerHTML=`<div class="card cd" id="cd" style="display:none;margin-top:12px"><div class="lbl">// Next broadcast goes live in</div><div class="cdv mono" id="cdv"></div><div class="muted" id="cdw"></div></div>
  <div class="hero"><div class="card big"><div class="head" style="margin:0"><div class="lbl" id="bk"></div><button class="btn sm" id="shareHero">Share</button></div><div class="v" id="big" data-v="0">0</div>
    <div><span id="dl" class="delta flat"></span> <span class="muted" id="nlive"></span></div>
    <div class="split" id="split"></div><div class="legend" id="leg"></div></div>
   <div class="kpis">
    <div class="card kpi"><div class="lbl" id="kpl">Peak concurrent</div><div class="v" id="kp"></div><div class="s" id="kpw"></div></div>
    <div class="card kpi"><div class="lbl">Average concurrent</div><div class="v" id="ka"></div><div class="s" id="kas">this broadcast</div></div>
    <div class="card kpi"><div class="lbl">Official peak</div><div class="v" id="ko"></div><div class="s">official streams combined</div></div>
    <div class="card kpi"><div class="lbl">Watch parties peak</div><div class="v" id="kw"></div><div class="s">all watch parties combined</div></div></div></div>
  <div class="card"><div class="tabs" id="tabs"><button data-v="total">Total viewers</button><button data-v="wp">Watch party battle</button><button data-v="split">Official vs watch parties</button></div>
   <div class="head"><div><div class="lbl" id="chh"></div><div class="cv" id="cv"></div></div>
    <div class="seg" id="rg" hidden></div>
    <button class="btn sm" id="shareChart">Share</button></div>
   <div class="chart" id="chartBox"><canvas id="c"></canvas></div><div class="race" id="race" hidden></div><div class="chips" id="chips"></div></div>
  <div class="grid2">
      <div class="card" id="stCard"><div class="head"><div><h2 id="lh">Live streams</h2></div><button class="btn sm" id="shareStreams">Share</button>
    <div class="seg" id="kf">${[['all','ALL'],['official','OFFICIAL'],['watch party','WATCH PARTIES']].map(([k,l])=>`<button data-k="${k}">${l}</button>`).join('')}</div>
    <input class="q" id="q" placeholder="Search channel or title"></div>
    <div class="scroll"><table><thead><tr><th>#</th><th>Channel / stream</th><th class="num" id="cth">Concurrent</th><th class="num hide-m" id="sth">Share</th></tr></thead><tbody id="rows"></tbody></table></div>
    <button class="more" id="more"></button></div>
   <div class="card" id="wpCard"><div class="head"><div><h2 id="wph">Watch party leaderboard</h2><div class="muted" style="font-size:12px">Streamers: share your rank card.</div></div><button class="btn sm" id="shareBoard">Share</button></div>
    <div class="scroll"><table><thead><tr><th>#</th><th>Streamer</th><th class="num" id="wpth">Live</th><th class="num hide-m">Peak</th><th></th></tr></thead><tbody id="wprows"></tbody></table></div><button class="more" id="wpmore"></button></div>
   <div class="card"><div class="head"><div><h2>By day</h2></div></div><div class="scroll"><table><thead><tr><th>Day (IST)</th><th class="num">Peak</th><th>At</th><th class="num">Average</th></tr></thead><tbody id="days"></tbody></table></div></div>
  </div><div class="foot" id="foot"></div>`;
  document.querySelectorAll('#tabs button').forEach(b=>b.onclick=()=>{view=b.dataset.v;hover=null;drawChart();mark()});
  document.querySelectorAll('#rg button').forEach(b=>b.onclick=()=>{if(b.disabled)return;range=b.dataset.r;hover=null;ys={};drawChart();mark()});
  document.querySelectorAll('#kf button').forEach(b=>b.onclick=()=>{kind=b.dataset.k;rows();mark()});
  document.getElementById('q').oninput=e=>{q=e.target.value.toLowerCase();rows()};
  document.getElementById('more').onclick=()=>{showAll=!showAll;rows()};
  document.getElementById('shareStreams').onclick=()=>openShare('streams');document.getElementById('shareHero').onclick=()=>openShare('total');
  document.getElementById('shareChart').onclick=()=>openShare(view==='wp'?'battle':view==='split'?'split':'total');
  const cv=document.getElementById('c');
  const mv=e=>{const r=cv.getBoundingClientRect(),p=e.touches?e.touches[0]:e;hover=p.clientX-r.left;if(range!=='live')drawChart()};
  cv.addEventListener('mousemove',mv);cv.addEventListener('touchstart',mv,{passive:true});cv.addEventListener('touchmove',mv,{passive:true});
  cv.addEventListener('mouseleave',()=>{hover=null;if(range!=='live')drawChart()});
 }
 const dw=LB.day==='Yesterday'?"Yesterday's":LB.day==='Today'?"Today's":'Last';
 document.getElementById('bk').textContent=off?`// Stream ended. ${dw} peak (${LB.when})`:'// Watching now, all live streams';
 document.getElementById('lh').textContent=off?`Streams, ${dw.toLowerCase()} broadcast`:'Live streams';
 document.getElementById('kpl').textContent=off?`${dw} peak`:'Peak today';document.getElementById('kas').textContent=off?`${dw.toLowerCase()} broadcast`:'this broadcast so far';
 document.getElementById('cth').textContent=off?'Peak':'Concurrent';document.getElementById('sth').textContent=off?'At (IST)':'Share';
 document.getElementById('wpth').textContent=off?'Final':'Live';
 tween(document.getElementById('big'),tot);
 const dl=document.getElementById('dl');
 if(off){dl.className='delta flat';dl.textContent='at '+LB.peak_when}
 else if(prevTotal!==null&&prevTotal!==tot){const d=tot-prevTotal;dl.className='delta '+(d>0?'up':'down');dl.textContent=(d>0?'▲ +':'▼ ')+full(d)+' since last reading'}
 prevTotal=tot;
 document.getElementById('nlive').textContent=off?`across ${live.length} streams`:live.length?`across ${live.length} live streams`:'Nothing live right now';
 const cols={official:css('--orange'),'watch party':css('--cyan'),community:css('--purple')};
 document.getElementById('split').innerHTML=Object.keys(by).map(k=>`<div style="width:${tot?100*by[k]/tot:0}%;background:${cols[k]}"></div>`).join('');
 document.getElementById('leg').innerHTML=Object.keys(by).filter(k=>k!=='community'||by[k]>0).map(k=>`<span><span class="sw" style="background:${cols[k]}"></span>${k==='watch party'?'WATCH PARTIES':k.toUpperCase()} <b>${fmt(by[k])}</b>${tot?` (${(100*by[k]/tot).toFixed(0)}%)`:''}</span>`).join('');
 const bc=LB.peak!=null;document.getElementById('kp').textContent=fmt(bc?LB.peak:D.peak);document.getElementById('kpw').textContent=bc?LB.peak_when:D.peak_when;
 document.getElementById('ka').textContent=fmt(bc&&LB.avg!=null?LB.avg:D.avg);document.getElementById('ko').textContent=fmt(bc&&LB.peak_official!=null?LB.peak_official:D.peak_official);document.getElementById('kw').textContent=fmt(bc&&LB.peak_watch!=null?LB.peak_watch:D.peak_watch);
 document.getElementById('days').innerHTML=(D.days||[]).map(d=>`<tr><td>${esc(d.day)}</td><td class="num">${fmt(d.peak)}</td><td>${esc(d.at)}</td><td class="num">${fmt(d.avg)}</td></tr>`).join('');
 document.getElementById('foot').innerHTML=`Concurrent viewers = people watching at the same moment, summed across every live YouTube stream (official, watch parties, community). Recorded only while the official broadcast is live. Counted from: ${esc(D.method)}.
  <div class="follow"><span>FOLLOW __BRAND__</span>__SOCIAL__</div>
  <div class="disc">Unofficial viewership tracker by <a href="__BRANDURL__" target="_blank" rel="noopener">__BRAND__</a>. Not affiliated with or endorsed by KRAFTON. YouTube only; other platforms are not included.</div>`;
 rows();wpRows();chips();drawChart();mark();
}
function wpRows(){const sb=document.getElementById('shareBoard');if(sb)sb.onclick=()=>openShare('board');
 const off=isOff(),R=D.roster||[],cd=!!(D.next_start&&!D.official_live);
 document.getElementById('wph').textContent=cd?'Watch party streamers, yet to start':off?'Watch party streamers, last broadcast':'Watch party streamers, live';
 document.getElementById('wpth').textContent='Status';
 let rank=0;const lim=D.official_live&&!wpAll?10:999,RR=R.slice(0,lim),mb=document.getElementById('wpmore');
 if(mb){mb.style.display=R.length>lim||wpAll&&D.official_live?'block':'none';mb.textContent=wpAll?'\u25B2 SHOW TOP 10':`\u25BC SHOW ALL ${R.length} STREAMERS`;mb.onclick=()=>{wpAll=!wpAll;wpRows()}}
 document.getElementById('wprows').innerHTML=RR.map(w=>{const has=w.status!=='upcoming';if(has)rank++;
  const st=w.status==='live'?`<span class="lv"><i></i>LIVE</span> <b>${full(w.viewers)}</b>`:w.status==='ended'?`<span class="muted">PEAK</span> <b>${full(w.peak||0)}</b>`:'<span class="muted">YET TO START</span>';
  const logo=w.logo?`<img class="lg" src="${esc(w.logo)}" alt="" loading="lazy" referrerpolicy="no-referrer">`:`<span class="lg" style="display:inline-flex;align-items:center;justify-content:center;font-size:10px;font-weight:700">${esc(w.name.slice(0,2).toUpperCase())}</span>`;
  const nm=w.url?`<a class="ch" href="${esc(w.url)}" target="_blank" rel="noopener" style="color:var(--ink)">${esc(w.name)}</a>`:`<span class="ch">${esc(w.name)}</span>`;
  return `<tr><td class="rk ${has?'watch':''}" style="${has?'':'background:var(--line);color:var(--muted)'}">${has?rank:'-'}</td><td class="t">${logo}${nm}</td>
  <td class="num" style="font-size:13px">${st}</td><td class="num hide-m muted">${w.peak?fmt(w.peak):'-'}</td>
  <td style="text-align:right">${w.vid&&has?`<button class="btn sm ghost" data-share="${esc(w.vid)}">Share</button>`:''}</td></tr>`}).join('')||'<tr><td colspan=5 class="muted">No watch parties yet</td></tr>';
 document.querySelectorAll('[data-share]').forEach(b=>b.onclick=()=>openShare('streamer',b.dataset.share));
}
function rows(){
 const off=isOff(),src=off?D.last_broadcast.streams:(D.live||[]);
 const all=src.filter(s=>(kind==='all'||s.kind===kind)&&(!q||(s.channel+' '+s.title).toLowerCase().includes(q)));
 const lim=window.innerWidth<600?8:15,list=showAll||q?all:all.slice(0,lim);
 const mb=document.getElementById('more');mb.style.display=all.length>lim&&!q?'block':'none';mb.textContent=showAll?'SHOW FEWER':`SHOW ALL ${all.length}`;
 const tot=src.reduce((a,s)=>a+s.viewers,0)||1,top=Math.max(1,...list.map(s=>s.viewers));
 document.getElementById('lh').textContent=off?`Last broadcast streams (${all.length})`:`Live streams (${all.length})`;
 document.getElementById('rows').innerHTML=list.map((s,i)=>{const p=prev[s.vid];const cl=p===undefined&&Object.keys(prev).length?'':p<s.viewers?'fu':p>s.viewers?'fd':'';
  return `<tr class="${cl}"><td class="rk ${K[s.kind]}">${i+1}</td><td class="t">${s.logo?`<img class="lg" src="${esc(s.logo)}" alt="" loading="lazy" referrerpolicy="no-referrer">`:''}<span class="ch">${esc(s.channel)}</span><span class="tag ${K[s.kind]}">${esc(s.kind)}</span>${off?'':'<span class="lv"><i></i>LIVE</span>'}
  <a class="st" href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title.slice(0,100))}</a><div class="mini" style="width:${100*s.viewers/top}%"></div></td>
  <td class="num">${full(s.viewers)}</td><td class="num muted hide-m">${off?esc(s.at):(100*s.viewers/tot).toFixed(1)+'%'}</td></tr>`}).join('')||'<tr><td colspan=4 class="muted">Nothing live right now</td></tr>';
 prev={};src.forEach(s=>prev[s.vid]=s.viewers);
}
function chips(){
 const el=document.getElementById('chips');
 if(view!=='wp'){el.innerHTML='';return}
 el.innerHTML=(D.wp||[]).slice(0,5).map((w,i)=>`<button class="chip ${hidden[w.vid]?'offc':''}" data-vid="${esc(w.vid)}"><i style="background:${PAL[i%8]}"></i>${w.logo?`<img class="lg" style="width:16px;height:16px;margin:0" src="${esc(w.logo)}" alt="" referrerpolicy="no-referrer">`:''}${esc(w.channel.slice(0,18))} <b>${fmt(w.viewers)}</b></button>`).join('');
 el.querySelectorAll('.chip').forEach(c=>c.onclick=()=>{hidden[c.dataset.vid]=!hidden[c.dataset.vid];chips();drawChart()});
}
// ---------- graphs ----------
function lines(){
 const sr=D.series_recent||[],LB=D.last_broadcast,off=isOff();
 let tot;
 if(range==='live')tot=sr;else{let src=D.series_all||[];if(LB&&off)src=src.filter(r=>r[0]>=LB.start-60&&r[0]<=LB.end+60);
  else if(sr.length){src=src.filter(r=>r[0]>=sr[0][0]);const last=src.length?src[src.length-1][0]:0;src=src.concat(sr.filter(r=>r[0]>last))}tot=src}
 if(view==='total')return[{label:'Total',color:css('--lime'),pts:tot.map(r=>[r[0],r[1]]),w:2.4,fill:true}];
 if(view==='split')return[{label:'Official',color:css('--orange'),pts:tot.map(r=>[r[0],r[2]]),w:2.2},{label:'Watch parties',color:css('--cyan'),pts:tot.map(r=>[r[0],r[3]]),w:2.2}];
 return(D.wp||[]).slice(0,5).map((w,i)=>({label:w.channel,color:PAL[i%8],pts:(D.wp_series||{})[w.vid]||[],w:2.4,vid:w.vid,logo:w.logo,ini:w.channel.slice(0,2).toUpperCase()})).filter(l=>!hidden[l.vid]);
}
const WIN=180,LAG=4;let ys={};const IMG={};
function headLogo(ctx,e,fs){const r=11*fs,x=Math.max(r,e.x-r-6*fs),y=e.y;ctx.save();ctx.beginPath();ctx.arc(x,y,r,0,7);ctx.fillStyle=css('--card2');ctx.fill();ctx.lineWidth=2;ctx.strokeStyle=e.c;ctx.stroke();ctx.clip();
 if(e.logo){let im=IMG[e.logo];if(!im){im=IMG[e.logo]=new Image();im.referrerPolicy='no-referrer';im.src=e.logo}if(im.complete&&im.naturalWidth)ctx.drawImage(im,x-r,y-r,2*r,2*r);else draw0()}else draw0();
 function draw0(){ctx.fillStyle=e.c;ctx.font=`700 ${9*fs}px "Chakra Petch",sans-serif`;ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(e.ini||'',x,y+1)}ctx.restore()}
function plot(ctx,W,H,L,o){
 ctx.clearRect(0,0,W,H);
 const live=o.live,now=nowS()-LAG;let t0,t1;
 const any=L.filter(l=>l.pts.length);
 if(live){t1=now;t0=now-WIN}else{t0=Math.min(...any.map(l=>l.pts[0][0]));t1=Math.max(...any.map(l=>l.pts[l.pts.length-1][0]));if(!(t1>t0))t1=t0+1}
 const vis=L.map(l=>{if(!live)return l.pts;const i=l.pts.findIndex(r=>r[0]>=t0);return i<0?[]:l.pts.slice(Math.max(0,i-1))});
 const padR=o.padR??62,padB=22*(o.fs||1),padT=o.padT??12,cw=W-padR,ch=H-padB-padT;
 const vals=vis.flat().filter(r=>r[0]>=t0-5).map(r=>r[1]);
 if(!vals.length){ctx.fillStyle=css('--muted');ctx.font=`${14*(o.fs||1)}px "Share Tech Mono",monospace`;ctx.textAlign='center';ctx.fillText(live?'WAITING FOR THE OFFICIAL BROADCAST':'NO READINGS YET',cw/2,H/2);return null}
 let lo=Math.min(...vals),hi=Math.max(...vals);const pad=Math.max((hi-lo)*.2,hi*.02,30);let tg=[Math.max(0,lo-pad),hi+pad];
 if(o.multi)tg[0]=0;
 const key=o.key;let y=ys[key];y=(!y||!live)?tg:[y[0]+(tg[0]-y[0])*.07,y[1]+(tg[1]-y[1])*.07];ys[key]=y;
 const X=t=>(t-t0)/(t1-t0)*cw,Y=v=>padT+ch-(v-y[0])/(y[1]-y[0])*ch;
 const fs=o.fs||1,F=(n,b)=>`${b?'700 ':''}${Math.round(n*fs)}px ${b?'"Chakra Petch",sans-serif':'"Share Tech Mono",monospace'}`;
 ctx.strokeStyle=css('--line');ctx.lineWidth=1;ctx.fillStyle=css('--muted');ctx.font=F(11);ctx.textBaseline='middle';ctx.textAlign='left';
 for(let k=0;k<=4;k++){const v=y[0]+(y[1]-y[0])*k/4,yy=Y(v);ctx.globalAlpha=.7;ctx.beginPath();ctx.moveTo(0,yy);ctx.lineTo(cw,yy);ctx.stroke();ctx.globalAlpha=1;if(o.multi||L.length>1){if(k>0)ctx.fillText(fmt(v),4,yy-8*fs);continue}if(live&&Math.abs(yy-Y(vis[0].length?vis[0][vis[0].length-1][1]:-1e9))<16)continue;ctx.fillText(fmt(v),cw+8,yy)}
 if(live){ctx.globalAlpha=.3;for(let t=Math.ceil(t0/10)*10;t<t1;t+=10){const x=X(t);ctx.beginPath();ctx.moveTo(x,padT);ctx.lineTo(x,padT+ch);ctx.stroke()}ctx.globalAlpha=1}
 ctx.textAlign='center';ctx.textBaseline='alphabetic';
 if(live)[[180,'-3:00'],[120,'-2:00'],[60,'-1:00'],[0,'NOW']].forEach(([s,l])=>ctx.fillText(l,Math.min(Math.max(X(t1-s),18*fs),cw-14*fs),H-5));
 else{const tf=t=>new Date(t*1000).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit'});const nk=W<500?2:4;for(let k=0;k<=nk;k++){const t=t0+(t1-t0)*k/nk;ctx.fillText(tf(t),Math.min(Math.max(X(t),30*fs),cw-30*fs),H-5)}}
 ctx.save();ctx.beginPath();ctx.rect(0,0,cw,H);ctx.clip();
 L.forEach((l,li)=>{const p=vis[li];if(!p.length)return;
  if(l.fill){ctx.beginPath();p.forEach((r,i)=>{i?ctx.lineTo(X(r[0]),Y(r[1])):ctx.moveTo(X(r[0]),Y(r[1]))});ctx.lineTo(X(p[p.length-1][0]),padT+ch);ctx.lineTo(X(p[0][0]),padT+ch);ctx.closePath();
   const g=ctx.createLinearGradient(0,padT,0,padT+ch);g.addColorStop(0,'rgba(182,242,58,.18)');g.addColorStop(1,'rgba(124,92,255,0)');ctx.fillStyle=g;ctx.fill()}
  ctx.beginPath();p.forEach((r,i)=>{i?ctx.lineTo(X(r[0]),Y(r[1])):ctx.moveTo(X(r[0]),Y(r[1]))});
  ctx.strokeStyle=l.color;ctx.lineWidth=l.w;ctx.lineJoin='round';ctx.shadowColor=l.color;ctx.shadowBlur=live||o.head?12:4;ctx.stroke();ctx.shadowBlur=0});
 ctx.restore();
 if(o.mark&&L[0]&&vis[0].length){const pk=vis[0].reduce((b,r)=>r[1]>b[1]?r:b),px=X(pk[0]),py=Y(pk[1]);
  ctx.fillStyle='#ffffff';ctx.beginPath();ctx.arc(px,py,5*fs,0,7);ctx.fill();ctx.font=F(13,1);ctx.textAlign=px>cw*.7?'right':'left';ctx.textBaseline='bottom';
  ctx.fillText('PEAK '+fmt(pk[1]),px+(px>cw*.7?-10:10)*fs,py-6*fs);ctx.textAlign='left'}
 // heads + end labels
 const ends=[];L.forEach((l,li)=>{const p=vis[li];if(!p.length)return;const r=p[p.length-1];ends.push({x:X(r[0]),y:Y(r[1]),v:r[1],c:l.color,label:l.label,logo:l.logo,ini:l.ini})});
 if(live||o.head){const ph=(Date.now()%1200)/1200;ends.forEach(e=>{ctx.beginPath();ctx.arc(e.x,e.y,4+ph*10,0,7);ctx.globalAlpha=(1-ph)*.5;ctx.fillStyle=e.c;ctx.fill();ctx.globalAlpha=1;ctx.beginPath();ctx.arc(e.x,e.y,4,0,7);ctx.fill()})}
 if(o.multi&&!o.nologo)ends.forEach(e=>headLogo(ctx,e,fs));
 ends.sort((a,b)=>a.y-b.y);let lastY=-99;ends.forEach(e=>{e.ly=Math.max(e.y,lastY+(o.multi?15:22)*fs);lastY=e.ly});
 ctx.textBaseline='middle';ctx.textAlign='left';
 ends.forEach(e=>{if(o.multi||L.length>1){ctx.fillStyle=e.c;ctx.font=F(12);ctx.fillText(fmt(e.v),cw+6,e.ly)}
  else{ctx.fillStyle=e.c;ctx.fillRect(cw+2,e.ly-10*fs,padR-4,20*fs);ctx.fillStyle='#0a0a14';ctx.font=F(12,1);ctx.fillText(fmt(e.v),cw+7,e.ly)}});
 if(o.markPeak&&vis[0]&&vis[0].length){const pk=vis[0].reduce((a,r)=>r[1]>a[1]?r:a);const px=X(pk[0]),py=Y(pk[1]);
  ctx.fillStyle='#ff4d5e';ctx.beginPath();ctx.arc(px,py,5*fs,0,7);ctx.fill();ctx.strokeStyle='#ff4d5e';ctx.setLineDash([3*fs,4*fs]);ctx.beginPath();ctx.moveTo(px,py);ctx.lineTo(px,padT+ch);ctx.stroke();ctx.setLineDash([]);
  const t=`PEAK ${fmt(pk[1])}`;ctx.font=F(12,1);const tw=ctx.measureText(t).width;ctx.textAlign='left';ctx.textBaseline='bottom';ctx.fillText(t,Math.min(Math.max(px-tw/2,0),cw-tw),py-8*fs)}
 if(o.hover!=null&&o.hover<cw){const tt=t0+(o.hover/cw)*(t1-t0),x=X(tt);ctx.strokeStyle=css('--muted');ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(x,padT);ctx.lineTo(x,padT+ch);ctx.stroke();ctx.setLineDash([]);
  const rowsH=L.map((l,li)=>{const p=vis[li];if(!p.length)return null;let b=p[0];for(const r of p)if(Math.abs(r[0]-tt)<Math.abs(b[0]-tt))b=r;return[l,b]}).filter(Boolean).sort((a,b)=>b[1][1]-a[1][1]);
  const lab=[new Date(tt*1000).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata'}),...rowsH.map(([l,b])=>`${l.label.slice(0,16)}: ${full(b[1])}`)];
  ctx.font='12px "Share Tech Mono",monospace';const w=Math.max(...lab.map(s=>ctx.measureText(s).width))+16,h=lab.length*16+8,bx=x+12+w>cw?x-12-w:x+12;
  ctx.fillStyle='rgba(13,10,38,.95)';ctx.strokeStyle=css('--line');ctx.fillRect(bx,padT,w,h);ctx.strokeRect(bx,padT,w,h);
  lab.forEach((s,i)=>{ctx.fillStyle=i?(rowsH[i-1][0].color):css('--muted');ctx.fillText(s,bx+8,padT+12+i*16)})}
 return{t0,t1,last:ends}
}
function drawHistCanvas(){const cv=document.getElementById('hc');if(!cv)return;const dpr=window.devicePixelRatio||1,W=cv.clientWidth,H=cv.clientHeight;
 cv.width=Math.round(W*dpr);cv.height=Math.round(H*dpr);const ctx=cv.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);drawHist(ctx,W,H,1)}
function hashc(n){let h=0;for(const c of n)h=(h*31+c.charCodeAt(0))|0;return PAL[Math.abs(h)%PAL.length]}
function race(){const el=document.getElementById('race');if(!el)return;const RR=D.roster||[];let R=RR.filter(r=>r.status==='live');const lv=R.length>0;if(!lv)R=RR.filter(r=>r.peak).sort((a,b)=>b.peak-a.peak);
 R=R.slice(0,5);const val=r=>lv?r.viewers:r.peak,max=Math.max(1,...R.map(val)),H=window.innerWidth<600?48:58;el.style.height=(R.length*H||60)+'px';
 if(!R.length){el.innerHTML='<div class="muted mono" style="padding:20px">WATCH PARTIES APPEAR HERE ONCE THEY GO LIVE</div>';return}
 el.querySelectorAll('.muted').forEach(x=>x.remove());const seen=new Set();
 R.forEach((r,i)=>{let row=[...el.children].find(x=>x.dataset.n===r.name);if(!row){row=document.createElement('div');row.className='rr';row.dataset.n=r.name;
   row.innerHTML=`<span class="rp"></span>${r.logo?`<img class="lg" src="${esc(r.logo)}" alt="" referrerpolicy="no-referrer">`:`<span class="lg ini">${esc(r.name.slice(0,2).toUpperCase())}</span>`}<div class="rb"><div class="rbf"><span class="rnm"></span></div></div><b class="rv"></b>`;
   row.style.transform=`translateY(${R.length*H}px)`;el.appendChild(row);void row.offsetWidth}
  const c=hashc(r.name);row.style.transform=`translateY(${i*H}px)`;row.style.height=(H-6)+'px';row.querySelector('.rp').textContent=i+1;row.querySelector('.rnm').textContent=r.name;
  const f=row.querySelector('.rbf');f.style.width=Math.max(18,100*val(r)/max)+'%';f.style.background=`linear-gradient(90deg,${c}33,${c})`;f.style.boxShadow=`0 0 14px ${c}55`;
  const v=row.querySelector('.rv');if(+v.dataset.v!==val(r)){v.classList.remove('bump');void v.offsetWidth;v.classList.add('bump');tween(v,val(r))}seen.add(r.name)});
 [...el.children].forEach(x=>{if(x.dataset.n&&!seen.has(x.dataset.n))x.remove()})}
function drawChart(){
 const useRace=V2&&view==='wp',rb=document.getElementById('race'),cb=document.getElementById('chartBox'),rg=document.getElementById('rg');
 if(rb){rb.hidden=!useRace;cb.style.display=useRace?'none':'';if(rg)rg.style.visibility=useRace?'hidden':'visible'}
 if(useRace){race();const h=document.getElementById('chh'),c=document.getElementById('cv'),R=(D.roster||[]).filter(r=>r.status==='live');
  h.textContent=R.length?'// watch party battle, live ranking':'// watch party battle, last broadcast peaks';c.innerHTML=R[0]?`${esc(R[0].name)}<small>LEADS WITH ${fmt(R[0].viewers)}</small>`:'';return}
 const cv=document.getElementById('c');if(!cv)return;
 const dpr=window.devicePixelRatio||1,W=cv.clientWidth,H=cv.clientHeight;
 if(cv.width!==Math.round(W*dpr)||cv.height!==Math.round(H*dpr)){cv.width=Math.round(W*dpr);cv.height=Math.round(H*dpr)}
 const ctx=cv.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);
 const L=lines(),live=range==='live';
 plot(ctx,W,H,L,{live,head:!!D.official_live,hover,multi:view==='wp',key:view+range,padR:view==='wp'?52:62});
 const h=document.getElementById('chh'),c=document.getElementById('cv'),LB=D.last_broadcast;
 const lastOf=l=>l.pts.length?l.pts[l.pts.length-1][1]:0,peakOf=l=>l.pts.reduce((a,r)=>Math.max(a,r[1]),0);
 const tag=live?'// live, last 3 minutes':(isOff()&&LB?`// ${LB.when}`:'// this broadcast, updating live');
 if(view==='total'){h.textContent=tag;const nowv=live||D.official_live;c.innerHTML=L[0]&&L[0].pts.length?`${full(nowv?lastOf(L[0]):peakOf(L[0]))}<small>${nowv?'WATCHING NOW':'PEAK'}</small>`:''}
 else if(view==='split'){h.textContent=tag;const nv=live||D.official_live;c.innerHTML=L[0].pts.length?`<span style="color:var(--orange)">${fmt(nv?lastOf(L[0]):peakOf(L[0]))}</span> <small>OFFICIAL</small> <span style="color:var(--cyan)">${fmt(nv?lastOf(L[1]):peakOf(L[1]))}</span> <small>WATCH PARTIES</small>`:''}
 else{h.textContent=tag+' // tap a name to hide it';const w=(D.wp||[])[0];c.innerHTML=w?`${esc(w.channel)}<small>#1 WATCH PARTY ${fmt(w.viewers)}</small>`:''}
}
let lf=0;function loop(t){if(!document.hidden&&(range==='live'||(D.official_live&&t-lf>50))){lf=t;drawChart()}requestAnimationFrame(loop)}
window.addEventListener('resize',()=>drawChart());
function mark(){document.querySelectorAll('#tabs button').forEach(b=>b.classList.toggle('on',b.dataset.v===view));
 document.querySelectorAll('#rg button').forEach(b=>{b.classList.toggle('on',b.dataset.r===range);if(b.dataset.r==='live')b.disabled=!D.official_live});
 document.querySelectorAll('#kf button').forEach(b=>b.classList.toggle('on',b.dataset.k===kind))}
// ---------- share cards ----------
function dayWin(){const LB=D.last_broadcast;if(isOff()&&LB)return[LB.start-60,LB.end+60];const n=nowS();return[Math.floor((n+19800)/86400)*86400-19800,n+60]}
function dayStreams(){const LB=D.last_broadcast||{};return(LB.streams||[])}
function logoOf(ch){const n=x=>String(x||'').toLowerCase().replace(/[^a-z0-9]/g,'');const r=(D.roster||[]).find(r=>r.logo&&(n(ch).includes(n(r.name))||n(r.name).includes(n(ch))));return r?r.logo:''}
function loadImg(u){return new Promise(r=>{if(!u)return r(null);const i=new Image();i.crossOrigin='anonymous';i.onload=()=>r(i);i.onerror=()=>r(null);i.src=u})}
function wpByPeak(){const live={};(D.live||[]).forEach(s=>live[s.vid]=s.viewers);
 return dayStreams().filter(s=>s.kind==='watch party').map(s=>({vid:s.vid,channel:s.channel,logo:s.logo||logoOf(s.channel),peak:s.viewers,avg:s.avg||0,at:s.at,now:D.official_live?(live[s.vid]||0):null})).sort((a,b)=>b.peak-a.peak)}
function histCard(){const W=1080,H=1350,SC=3,c=document.createElement('canvas');c.width=W*SC;c.height=H*SC;const x=c.getContext('2d');x.scale(SC,SC);
 const g=x.createRadialGradient(W*.8,0,40,W*.8,0,1200);g.addColorStop(0,'#2a1d5c');g.addColorStop(1,'#0b0b12');x.fillStyle=g;x.fillRect(0,0,W,H);
 const T=(t,X,Y,f,c,a)=>{x.font=f;x.fillStyle=c;x.textAlign=a||'left';x.textBaseline='top';x.fillText(t,X,Y)};const h=hist(),top=[...h].sort((a,b)=>b[2]-a[2]);
 T('letsgrowesports',80,70,'30px "Share Tech Mono",monospace','#b6f23a');T('BGMI VIEWERSHIP TILL DATE',80,110,'700 64px "Chakra Petch",sans-serif','#ffffff');
 T(`// ALL-TIME HIGH // ${HNAME[top[0][0]].toUpperCase()} 20${top[0][1]}`,80,200,'30px "Share Tech Mono",monospace','#ff4d5e');T(top[0][2]+'K',72,240,'700 150px "Chakra Petch",sans-serif','#ffffff');
 T(`${h.length} EVENTS // 2021 TO 2026`,W-80,300,'30px "Share Tech Mono",monospace','#b6f23a','right');
 x.save();x.translate(40,420);drawHist(x,W-80,420,2);x.restore();
 let y=880;T('// ALL-TIME RANKING',80,y,'26px "Share Tech Mono",monospace','#ff4d5e');y+=44;
 top.slice(0,8).forEach((r,i)=>{const col=i%2,row=Math.floor(i/2),X=80+col*470,Y=y+row*48,c=r[0]==='BMSD'&&r[1]==='26'?'#ff4d5e':i===0?'#b6f23a':'#eeeef5';
  T(`${i+1}. ${HNAME[r[0]].toUpperCase()} 20${r[1]}`.slice(0,26),X,Y,'700 28px "Chakra Petch",sans-serif',c);T(r[2]+'K',X+430,Y,'700 28px "Chakra Petch",sans-serif',c,'right')});
 x.fillStyle='#b6f23a';x.fillRect(0,H-130,W,130);T('LIVE.LETSGROWESPORTS.COM',80,H-108,'700 44px "Chakra Petch",sans-serif','#0a0a14');T('@letsgrowesports',80,H-52,'24px "Share Tech Mono",monospace','#0a0a14');return c}
function avatarAt(x,im,cx,cy,r,ring,name){x.save();x.beginPath();x.arc(cx,cy,r,0,7);x.closePath();x.fillStyle='#1a1a26';x.fill();x.clip();
 if(im)x.drawImage(im,cx-r,cy-r,2*r,2*r);else{x.fillStyle='#8d8ca3';x.font=`700 ${Math.round(r*.8)}px "Chakra Petch",sans-serif`;x.textAlign='center';x.textBaseline='middle';x.fillText(String(name||'').slice(0,2).toUpperCase(),cx,cy+2)}
 x.restore();x.beginPath();x.arc(cx,cy,r,0,7);x.lineWidth=Math.max(2,r/14);x.strokeStyle=ring;x.stroke();x.textBaseline='top';x.textAlign='left'}
let avs={};
function card(type,vid,avatar){if(type==='history')return histCard();
 const W=1080,H=1350,SC=3,c=document.createElement('canvas');c.width=W*SC;c.height=H*SC;const x=c.getContext('2d');x.scale(SC,SC);x.imageSmoothingQuality='high';
 const g=x.createRadialGradient(W*.8,0,40,W*.8,0,1200);g.addColorStop(0,'#1f1a3d');g.addColorStop(1,'#0b0b12');x.fillStyle=g;x.fillRect(0,0,W,H);
 x.fillStyle='rgba(255,255,255,.02)';for(let yy=0;yy<H;yy+=4)x.fillRect(0,yy,W,1);
 x.strokeStyle='#b6f23a';x.lineWidth=5;x.beginPath();x.moveTo(40,80);x.lineTo(40,40);x.lineTo(80,40);x.stroke();
 const LB=D.last_broadcast||{},wp=wpByPeak();
 const nowTot=(D.live||[]).reduce((a,s)=>a+s.viewers,0),live=!!D.official_live||nowTot>0;
 const T=(t,X,Y,font,col,al)=>{x.font=font;x.fillStyle=col;x.textAlign=al||'left';x.fillText(t,X,Y)};
 const M=s=>`${s}px "Share Tech Mono",monospace`,B=s=>`700 ${s}px "Chakra Petch",sans-serif`;
 x.textBaseline='top';
 T('letsgrowesports',80,78,M(30),'#b6f23a');
 T(`${TITLE} // ${LB.date||''}`.toUpperCase(),80,118,B(50),'#eeeef5');
 const box=(X,Y,w,h,lab,val,sub,col)=>{x.fillStyle='rgba(26,26,38,.9)';x.fillRect(X,Y,w,h);x.strokeStyle='#262636';x.lineWidth=2;x.strokeRect(X,Y,w,h);
  T(lab,X+22,Y+20,M(24),'#ff4d5e');T(val,X+22,Y+54,B(56),col||'#eeeef5');if(sub)T(sub,X+22,Y+122,M(22),'#8d8ca3')};
 let L,y0;
 if(type==='total'||type==='split'){
  if(type==='split'){const sp0=LB.split||{};T('// OFFICIAL VS WATCH PARTIES',80,205,M(30),'#ff4d5e');
   T('OFFICIAL',80,250,M(26),'#ff8a3d');T(fmt(LB.peak_official??D.peak_official),76,282,B(110),'#ff8a3d');T('WATCH PARTIES',560,250,M(26),'#4cc9f0');T(fmt(LB.peak_watch??D.peak_watch),556,282,B(110),'#4cc9f0');
   T('peak of each, all streams combined',80,410,M(24),'#8d8ca3')}else{
  T('// PEAK CONCURRENT VIEWERS',80,205,M(30),'#ff4d5e');
  x.shadowColor='rgba(182,242,58,.35)';x.shadowBlur=30;T(full(LB.peak||D.peak),72,245,B(170),'#ffffff');x.shadowBlur=0}
  const sp=LB.split||{},bw=(W-160-40)/3;
  if(live)box(80,490,bw,170,'WATCHING NOW',fmt(nowTot),'at time of sharing','#b6f23a');else box(80,490,bw,170,'AVERAGE',fmt(LB.avg??D.avg),'while live','#b6f23a');
  box(80+bw+20,490,bw,170,'OFFICIAL AT PEAK',fmt(sp.official),'official streams','#ff8a3d');
  box(80+2*(bw+20),490,bw,170,'WATCH PARTIES',fmt(sp.watch),'at peak','#4cc9f0');
  L=[{label:'Total',color:'#b6f23a',pts:dayTotal(),w:5,fill:true}];y0=700;
  if(type==='split')L=[{label:'Official',color:'#ff8a3d',pts:dayTotal(2),w:5},{label:'Watch parties',color:'#4cc9f0',pts:dayTotal(3),w:5}];
  x.save();x.translate(60,y0);plot(x,W-120,290,L,{live:false,multi:type==='split',nologo:true,key:'cardT'+type,padR:130,padT:40,fs:2,markPeak:type!=='split'});x.restore();
  let ly=1015;T('// WATCH PARTY LEADERS (PEAK)',80,ly,M(26),'#ff4d5e');ly+=42;
  wp.slice(0,3).forEach((w,j)=>{T(`${j+1}. ${w.channel.toUpperCase().slice(0,26)}`,80,ly,B(34),j?'#eeeef5':'#b6f23a');T(full(w.peak),W-80,ly,B(34),j?'#eeeef5':'#b6f23a','right');ly+=46});
 }else if(type==='streams'){
  const off=isOff(),S=(off?LB.streams||[]:D.live||[]).slice(0,10),tot=off?LB.peak:nowTot,top=Math.max(1,...S.map(s=>s.viewers)),KC={official:'#ff8a3d','watch party':'#4cc9f0'};
  T(off?'// STREAMS, PEAK PER STREAM':'// LIVE STREAMS, RIGHT NOW',80,205,M(30),'#ff4d5e');
  T(off?`combined peak ${full(tot||0)} at ${LB.peak_when||''}`:`${full(tot)} watching across ${(D.live||[]).length} live streams`,80,248,M(24),'#8d8ca3');
  S.forEach((s,j)=>{const y=300+j*88,c=KC[s.kind]||'#7c5cff';
   x.fillStyle=j%2?'rgba(255,255,255,.03)':'rgba(255,255,255,.06)';x.fillRect(60,y-8,W-120,78);x.fillStyle=c;x.fillRect(60,y-8,8,78);
   T(String(j+1),96,y+14,B(36),'#eeeef5');avatarAt(x,avs[s.vid],170,y+31,28,c,s.channel);
   T(s.channel.toUpperCase().slice(0,22),214,y+2,B(32),'#ffffff');
   T((s.kind==='official'?'OFFICIAL':s.kind==='watch party'?'WATCH PARTY':'STREAM')+(s.kind==='official'&&/\[([^\]]+)\]/.test(s.title)?' // '+s.title.match(/\[([^\]]+)\]/)[1].toUpperCase():''),214,y+40,M(22),c);
   x.fillStyle=c;x.globalAlpha=.8;x.fillRect(600,y+52,Math.max(6,(W-700)*s.viewers/top),5);x.globalAlpha=1;
   T(full(s.viewers),W-80,y+12,B(40),'#ffffff','right')});
 }else if(type==='board'){
  const R0=(D.roster||[]),lv=R0.some(r=>r.status==='live');let R=(lv?R0.filter(r=>r.status==='live'):R0.filter(r=>r.peak).sort((a,b)=>b.peak-a.peak)).slice(0,10);
  T(lv?'// WATCH PARTY LEADERBOARD, LIVE':'// WATCH PARTY LEADERBOARD',80,205,M(30),'#ff4d5e');
  T(lv?'concurrent viewers right now':'peak concurrent viewers',80,248,M(24),'#8d8ca3');
  if(!R.length){T('WATCH PARTIES GO LIVE WITH THE BROADCAST',80,330,B(40),'#eeeef5');R0.slice(0,10).forEach((r,j)=>T(r.name.toUpperCase(),80+(j%2)*470,420+Math.floor(j/2)*60,B(30),'#8d8ca3'))}
  const top=Math.max(1,...R.map(r=>lv?r.viewers:r.peak));
  R.forEach((r,j)=>{const y=300+j*88,v=lv?r.viewers:r.peak,c=j===0?'#f5c451':j<3?'#b6f23a':'#eeeef5';
   x.fillStyle=j%2?'rgba(255,255,255,.03)':'rgba(255,255,255,.06)';x.fillRect(60,y-8,W-120,78);
   x.fillStyle=j===0?'#f5c451':j<3?'#b6f23a':'#262636';x.fillRect(60,y-8,8,78);
   T(String(j+1),96,y+14,B(36),c);avatarAt(x,avs[r.vid]||avs[r.name],170,y+31,28,j===0?'#f5c451':'#262636',r.name);
   T(r.name.toUpperCase().slice(0,20),214,y+6,B(34),'#ffffff');
   x.fillStyle=c;x.globalAlpha=.85;x.fillRect(214,y+50,Math.max(8,(W-520)*v/top),6);x.globalAlpha=1;
   T(full(v),W-80,y+12,B(40),c,'right')});
 }else{
  let i=type==='streamer'?wp.findIndex(w=>w.vid===vid):0;if(i<0){const d=(D.wp||[]).find(w=>w.vid===vid);if(d){wp.push({vid:d.vid,channel:d.channel,logo:d.logo,peak:d.peak,avg:0});wp.sort((a,b)=>b.peak-a.peak);i=wp.findIndex(w=>w.vid===vid)}}
  if(i<0)i=0;const me=wp[i]||{channel:'-',peak:0,avg:0},champ=i===0,GOLD='#f5c451',acc=champ?GOLD:'#b6f23a';
  // spotlight behind the hero
  const sg=x.createRadialGradient(240,330,10,240,330,420);sg.addColorStop(0,champ?'rgba(245,196,81,.20)':'rgba(182,242,58,.14)');sg.addColorStop(1,'rgba(0,0,0,0)');x.fillStyle=sg;x.fillRect(0,150,W,500);
  T(champ?'// WATCH PARTY CHAMPION':`// #${i+1} WATCH PARTY OF THE DAY`,80,198,M(30),acc);
  const r=92,cx=80+r,cy=250+r;
  x.save();x.shadowColor=acc;x.shadowBlur=40;x.beginPath();x.arc(cx,cy,r+8,0,7);x.fillStyle=acc;x.fill();x.restore();
  avatarAt(x,avatar,cx,cy,r,acc,me.channel);
  x.beginPath();x.arc(cx+r*.72,cy+r*.72,30,0,7);x.fillStyle=acc;x.fill();T('#'+(i+1),cx+r*.72,cy+r*.72-18,B(30),'#0a0a14','center');
  const x0=80+2*r+46;let fsz=64;x.font=B(fsz);while(x.measureText(me.channel.toUpperCase()).width>W-80-x0&&fsz>34){fsz-=2;x.font=B(fsz)}
  T(me.channel.toUpperCase(),x0,262,B(fsz),'#ffffff');
  T('PEAK CONCURRENT VIEWERS',x0,262+fsz+14,M(24),'#8d8ca3');
  x.shadowColor=champ?'rgba(245,196,81,.45)':'rgba(182,242,58,.35)';x.shadowBlur=30;T(full(me.peak),x0-4,262+fsz+48,B(104),acc);x.shadowBlur=0;
  const bw=(W-160-40)/3;
  box(80,560,bw,140,'PEAK',fmt(me.peak),me.at?me.at+' IST':'',acc);
  box(80+bw+20,560,bw,140,'AVERAGE',me.avg?fmt(me.avg):'-','while live','#4cc9f0');
  box(80+2*(bw+20),560,bw,140,'RANK',`#${i+1}`,`of ${wp.length} watch parties`,'#eeeef5');
  const sv=D.wp_series||{};
  L=wp.slice(0,5).map((w,j)=>({label:w.channel,color:w.vid===me.vid?acc:'rgba(141,140,163,.55)',pts:sv[w.vid]||[],w:w.vid===me.vid?6:3}));
  const mi=L.findIndex(l=>l.label===me.channel);if(mi>=0)L.push(L.splice(mi,1)[0]);
  let ly=772;x.fillStyle='rgba(255,255,255,.08)';x.fillRect(80,740,W-160,2);T('// TOP 5 WATCH PARTIES',80,ly,M(26),'#ff4d5e');T('PEAK',W-250,ly,M(22),'#8d8ca3','right');T('AVG',W-80,ly,M(22),'#8d8ca3','right');ly+=56;
  wp.slice(0,5).forEach((w,j)=>{const hi=w.vid===me.vid,c=j===0?GOLD:hi?'#b6f23a':'#eeeef5';
   if(hi){x.fillStyle='rgba(182,242,58,.08)';x.fillRect(60,ly-10,W-120,60)}
   T(String(j+1),84,ly+6,B(28),c);avatarAt(x,avs[w.vid],142,ly+19,22,j===0?GOLD:'#262636',w.channel);
   T(w.channel.toUpperCase().slice(0,22),176,ly+4,B(30),c);T(full(w.peak),W-250,ly+4,B(30),c,'right');T(w.avg?full(w.avg):'-',W-80,ly+4,B(30),'#8d8ca3','right');ly+=64});
 }
 x.fillStyle='#b6f23a';x.fillRect(0,H-130,W,130);
 T('LIVE.LETSGROWESPORTS.COM',80,H-108,B(44),'#0a0a14');
 const when=new Date().toLocaleString('en-IN',{timeZone:'Asia/Kolkata',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'});
 T(`${when} IST // @letsgrowesports`,80,H-52,M(24),'#0a0a14');
 return c;
}
function dayTotal(col){col=col||1;const LB=D.last_broadcast;let src=(D.series_all||[]).concat((D.series_recent||[]));
 const m=new Map();src.forEach(r=>m.set(r[0],r));src=[...m.values()].sort((a,b)=>a[0]-b[0]);
 if(LB)src=src.filter(r=>r[0]>=LB.start-60&&r[0]<=LB.end+120);const step=Math.max(1,Math.floor(src.length/900));return src.filter((_,i)=>i%step===0).map(r=>[r[0],r[col]])}
let cur=null;
async function openShare(type,vid){
 const mi=document.getElementById('mimg');mi.removeAttribute('src');mi.alt='Making the image...';cur=null;document.getElementById('modal').classList.add('on');
 const big=u=>String(u||'').replace(/=s\d+-/,'=s240-');let av=null;avs={};
 if(type==='streams'){const S=(isOff()?(D.last_broadcast||{}).streams||[]:D.live||[]).slice(0,10);
  const ims=await Promise.all(S.map(s=>loadImg(big(s.logo))));S.forEach((s,k)=>{if(ims[k])avs[s.vid]=ims[k]})}
 if(type==='battle'||type==='streamer'||type==='board'){
  const w=wpByPeak(),list=type==='board'?(D.roster||[]).map(r=>({vid:r.vid,name:r.name,logo:r.logo})):w.slice(0,5).map(x=>({vid:x.vid,logo:x.logo||logoOf(x.channel)}));
  const me=type==='streamer'?(w.find(x=>x.vid===vid)||(D.wp||[]).find(x=>x.vid===vid)):w[0];
  const ims=await Promise.all(list.slice(0,12).map(l=>loadImg(big(l.logo))));list.slice(0,12).forEach((l,k)=>{if(ims[k]){avs[l.vid]=ims[k];if(l.name)avs[l.name]=ims[k]}});
  if(me&&type!=='board')av=avs[me.vid]||await loadImg(big(me.logo||logoOf(me.channel)))}
 let c=card(type,vid,av);const done=b=>{cur={blob:b,name:`bmsd-${type}.png`};document.getElementById('mimg').src=URL.createObjectURL(b)};
 try{c.toBlob(done,'image/png')}catch(e){avs={};c=card(type,vid,null);c.toBlob(done,'image/png')}
 const wp=D.wp||[],i=wp.findIndex(w=>w.vid===vid);
 const dpk=wp.slice().sort((a,b)=>b.peak-a.peak),today=(D.days||[]).slice(-1)[0]||{},nowT=(D.live||[]).reduce((a,s)=>a+s.viewers,0);
 const LB=D.last_broadcast||{},wpp=wpByPeak();let text;
 if(type==='history'){const t=[...hist()].sort((a,b)=>b[2]-a[2])[0];text=`BGMI viewership till date: all-time high ${t[2]}K (${HNAME[t[0]]} 20${t[1]}). BMSD 2026 so far: ${hist()[15][2]}K.`}else
 if(type==='streams'){const S=isOff()?LB.streams||[]:D.live||[],tt=isOff()?LB.peak:nowT;text=isOff()?`${TITLE}: ${full(tt||0)} combined peak across ${S.length} streams. Top: ${S.slice(0,3).map(s=>`${s.channel} ${fmt(s.viewers)}`).join(' | ')}.`:`${TITLE} live now: ${full(tt)} watching across ${S.length} streams. Top: ${S.slice(0,3).map(s=>`${s.channel} ${fmt(s.viewers)}`).join(' | ')}.`}else
 if(type==='board'){const R=(D.roster||[]).filter(r=>r.status==='live');text=R.length?`${TITLE} watch parties live now: ${R.slice(0,3).map((r,j)=>`${j+1}. ${r.name} ${fmt(r.viewers)}`).join(' | ')}.`:`${TITLE} official watch parties: ${(D.roster||[]).length} streamers.`}
 else if(type==='streamer'){const j=wpp.findIndex(w=>w.vid===vid),w=wpp[j]||{};text=`${w.channel} was the #${j+1} watch party of ${TITLE} on ${LB.date||'the day'}, peaking at ${full(w.peak)} concurrent viewers${w.avg?` (average ${full(w.avg)})`:''}.`}
 else if(type==='split')text=`${TITLE} ${LB.date||''}: official streams peaked at ${full(D.peak_official)}, watch parties at ${full(D.peak_watch)} concurrent viewers on YouTube.`;
 else if(type==='battle'){const w=wpp[0]||{};text=`${TITLE} watch party battle (${LB.date||''}): ${wpp.slice(0,3).map((x,j)=>`${j+1}. ${x.channel} ${fmt(x.peak)}`).join(' | ')}.`}
 else text=`${TITLE} peaked at ${full(LB.peak||D.peak)} concurrent viewers on YouTube on ${LB.date||'the day'} (${LB.peak_when||''})${D.official_live?`, ${full((D.live||[]).reduce((a,s)=>a+s.viewers,0))} watching right now`:''}.`;
 text+=' Live tracker:';
 document.getElementById('mt').textContent=type==='streamer'?'Share your rank':'Share';
 window._xurl='https://x.com/intent/post?text='+encodeURIComponent(text+' '+URLX+' via @letsgrowesports');
 document.getElementById('modal').classList.add('on');cur&&(cur.text=text);window._shareText=text;
}
document.getElementById('mclose').onclick=()=>document.getElementById('modal').classList.remove('on');
document.getElementById('modal').onclick=e=>{if(e.target.id==='modal')e.target.classList.remove('on')};
document.getElementById('mdl').onclick=()=>{if(!cur)return;const a=document.createElement('a');a.href=URL.createObjectURL(cur.blob);a.download=cur.name;a.click()};
async function shareTo(app){if(!cur)return;const f=new File([cur.blob],cur.name,{type:'image/png'}),t=window._shareText+' '+URLX+' @letsgrowesports';
 const mob=/Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
 if(mob&&navigator.canShare&&navigator.canShare({files:[f]})){try{await navigator.share({files:[f],text:t});return}catch(e){if(e&&e.name==='AbortError')return}}
 document.getElementById('mdl').click();
 if(app==='x')window.open(window._xurl,'_blank','noopener');
 else{window.open('https://www.instagram.com/','_blank','noopener');document.getElementById('mhint').textContent='Image downloaded. Upload it as a post or story on Instagram (on desktop: Create, then select the image).'}}
document.getElementById('mig').onclick=()=>shareTo('ig');document.getElementById('mxb').onclick=()=>shareTo('x');
// ---------- status + polling ----------
function countdown(){const el=document.getElementById('cd');if(!el)return null;
 const ns=D.next_start,left=ns?ns-nowS():0;if(D.official_live||!ns||left<=0){el.style.display='none';return null}
 el.style.display='block';const d=Math.floor(left/86400),h=Math.floor(left%86400/3600),m=Math.floor(left%3600/60),sec=Math.floor(left%60),p=n=>String(n).padStart(2,'0');
 document.getElementById('cdv').textContent=(d?d+'D ':'')+`${p(h)}:${p(m)}:${p(sec)}`;
 document.getElementById('cdw').textContent=new Date(ns*1000).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',weekday:'short',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'})+' IST';
 return left}
function status(){const cdl=countdown();
 const age=D.updated?Math.max(0,nowS()-D.updated):null;
 document.getElementById('ago').textContent=age===null?'-':age<60?`${age.toFixed(0)}s`:age<3600?`${Math.floor(age/60)}m`:age<86400?`${Math.floor(age/3600)}h`:`${Math.floor(age/86400)}d`;
 const st=document.getElementById('st'),t=document.getElementById('stt'),live=D.official_live&&(D.live||[]).length>0;
 if(!LIVE){st.className='pill off';t.textContent='SNAPSHOT'}
 else if(failing){st.className='pill warn';t.textContent='RECONNECTING'}
 else if(age!==null&&age>Math.max(15,D.every*6)&&live){st.className='pill warn';t.textContent='DELAYED'}
 else if(live){st.className='pill';t.textContent=`LIVE // EVERY ${D.every}S`}
 else if(cdl){st.className='pill';t.textContent='STARTS IN '+document.getElementById('cdv').textContent}
 else{st.className='pill off';t.textContent='OFFICIAL OFFLINE'}
 const nx=document.getElementById('nx');if(!LIVE||cdl){nx.style.display='none';return}nx.style.display="";
 const left=Math.max(0,EVERY-(Date.now()-lastFetch));document.getElementById('nxt').textContent=(left/1000).toFixed(1)+'s';
 document.getElementById('rp').setAttribute('stroke-dashoffset',44*(left/EVERY));
}
function merge(a,tail){a=a||[];const last=a.length?a[a.length-1][0]:0;for(const r of tail||[])if(r[0]>last)a.push(r);return a}
let lastSeries=Date.now();
let DM=null;
function demoInit(m){const now=Date.now()/1000;DM={mode:m,t0:now-2.5*3600,hist:{},tot:[],last:0};
 DM.off=[{vid:'o1',channel:'KRAFTON INDIA ESPORTS',title:'[HINDI] BMSD 2026 | Grand Finals #BGMILIVE',base:190000,ph:0,logo:DLOGO['KRAFTON INDIA ESPORTS']||''},{vid:'o2',channel:'KRAFTON INDIA ESPORTS',title:'[ENGLISH] BMSD 2026 | Grand Finals',base:14000,ph:1,logo:DLOGO['KRAFTON INDIA ESPORTS']||''},{vid:'o3',channel:'KRAFTON INDIA ESPORTS',title:'[MAP STREAM] BMSD 2026 | Grand Finals',base:3500,ph:2,logo:DLOGO['KRAFTON INDIA ESPORTS']||''}];
 DM.st=ROSTERN.map((n,i)=>({vid:'w'+i,channel:n,title:`BMSD 2026 Grand Finals watch party with ${n}`,base:i%5===4?0:Math.round(70000/Math.pow(i+1,.75)),ph:Math.random()*6,logo:DLOGO[n]||''}));
 for(let t=DM.t0;t<=now-200;t+=30)demoStep(t);for(let t=now-200;t<=now;t+=2)demoStep(t)}
function demoVal(s,t){const p=(t-DM.t0)/3600;return Math.max(0,Math.round(s.base*(.62+.38*Math.sin(p*2.4+s.ph))*(1+.06*Math.sin(t/7+s.ph))*(.97+.06*Math.random())))}
function demoStep(t){let o=0,w=0;DM.off.concat(DM.st).forEach(s=>{if(!s.base)return;const v=demoVal(s,t);(DM.hist[s.vid]=DM.hist[s.vid]||[]).push([Math.round(t),v]);s.cur=v;s.peak=Math.max(s.peak||0,v);if(s.vid[0]==='o')o+=v;else w+=v});DM.tot.push([Math.round(t),o+w,o,w,0]);DM.last=t}
function demoData(){const now=Date.now()/1000;if(!DM)demoInit('live');while(DM.last+2<=now)demoStep(DM.last+2);
 const liveM=DM.mode==='live',endM=DM.mode==='ended',all=DM.off.concat(DM.st).filter(s=>s.base),tf=t=>new Date(t*1000).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit'})+' IST';
 const pk=DM.tot.reduce((a,r)=>r[1]>a[1]?r:a),live=liveM?all.map(s=>({vid:s.vid,channel:s.channel,title:s.title,kind:s.vid[0]==='o'?'official':'watch party',viewers:s.cur,url:'#',logo:s.logo||''})).sort((a,b)=>b.viewers-a.viewers):[];
 const wp=DM.st.filter(s=>s.base).map(s=>({vid:s.vid,channel:s.channel,viewers:liveM?s.cur:0,url:'#',logo:s.logo||'',peak:s.peak})).sort((a,b)=>b.viewers-a.viewers||b.peak-a.peak).slice(0,8);
 const ws={};wp.forEach(w=>ws[w.vid]=DM.hist[w.vid]);
 const roster=DM.st.map(s=>({name:s.channel,logo:s.logo||'',url:'#',vid:s.base?s.vid:'',status:!s.base?'upcoming':liveM?'live':endM?'ended':'upcoming',viewers:liveM&&s.base?s.cur:0,peak:liveM||endM?s.peak||0:0})).sort((a,b)=>({live:0,ended:1,upcoming:2}[a.status]-{live:0,ended:1,upcoming:2}[b.status])||b.viewers-a.viewers||b.peak-a.peak||a.name.localeCompare(b.name));
 const LBs=all.map(s=>({vid:s.vid,channel:s.channel,title:s.title,kind:s.vid[0]==='o'?'official':'watch party',viewers:s.peak,avg:Math.round((DM.hist[s.vid]||[]).reduce((a,r)=>a+r[1],0)/Math.max(1,(DM.hist[s.vid]||[]).length)),at:tf(DM.t0+3600).replace(' IST',''),url:'#',logo:s.logo||''})).sort((a,b)=>b.viewers-a.viewers);
 return{name:'BMSD 2026',ticks:DM.tot.length,now,every:2,method:'demo data',updated:DM.last,official_live:liveM,next_start:liveM||endM?null:(Date.UTC(2026,9,16,9,0)/1000>now?Date.UTC(2026,9,16,9,0)/1000:now+5*3600),live,wp,wp_series:ws,roster,
  peak:pk[1],peak_when:tf(pk[0]),avg:Math.round(DM.tot.reduce((a,r)=>a+r[1],0)/DM.tot.length),peak_official:Math.max(...DM.tot.map(r=>r[2])),peak_watch:Math.max(...DM.tot.map(r=>r[3])),
  days:[{day:'Fri 16 Oct',peak:pk[1],at:tf(pk[0]).replace(' IST',''),avg:Math.round(pk[1]*.6)}],series_all:DM.tot.filter((_,i)=>i%5===0),series_recent:DM.tot.slice(),
  last_broadcast:{start:DM.t0,end:DM.last,peak:pk[1],peak_at:pk[0],peak_when:tf(pk[0]),split:{official:pk[2],watch:pk[3],community:0},streams:LBs,when:'Today, demo',day:'Today',date:'FRI 16 OCT',avg:Math.round(DM.tot.reduce((q,r)=>q+r[1],0)/Math.max(1,DM.tot.length)),peak_official:Math.max(0,...DM.tot.map(r=>r[2])),peak_watch:Math.max(0,...DM.tot.map(r=>r[3]))}}}
function demoBar(){if(!DEMO)return;const b=document.createElement('div');b.className='demo';b.innerHTML='DEMO <button data-m="countdown">COUNTDOWN</button><button data-m="live">LIVE</button><button data-m="ended">ENDED</button>';document.body.appendChild(b);
 const mk=()=>b.querySelectorAll('button').forEach(x=>x.classList.toggle('on',x.dataset.m===DM.mode));mk();
 b.querySelectorAll('button').forEach(x=>x.onclick=()=>{DM.mode=x.dataset.m;D=demoData();mode=null;document.getElementById('app').innerHTML='';render();mk()})}
async function tick(){
 if(DEMO){lastFetch=Date.now();D=demoData();render();return}
 if(document.hidden){lastFetch=Date.now();return}
 lastFetch=Date.now();
 try{const r=await fetch('data?t='+Math.floor(Date.now()/2000),{cache:'no-store'});if(!r.ok)throw 0;const j=await r.json();
  const sr=merge(D.series_recent,j.tail),sa=D.series_all||[];
  if(j.tail&&j.tail.length&&(!sa.length||j.tail[j.tail.length-1][0]-sa[sa.length-1][0]>60))sa.push(j.tail[j.tail.length-1]);
  const cut=(sr.length?sr[sr.length-1][0]:0)-6*3600;while(sr.length&&sr[0][0]<cut)sr.shift();
  const ws=D.wp_series||{};for(const [v,t] of Object.entries(j.wp_tail||{}))ws[v]=merge(ws[v],t);
  D={...j,series_recent:sr,series_all:sa,wp_series:ws};skew=Date.now()/1000-D.now;failing=false;render();
  const need=(D.wp||[]).some(w=>!ws[w.vid]);
  if(need||Date.now()-lastSeries>300000){lastSeries=Date.now();fetch('series?t='+Math.floor(Date.now()/60000),{cache:'no-store'}).then(x=>x.json()).then(x=>{D.series_all=x.series_all;D.series_recent=x.series_recent;
   const w2=x.wp_series||{};for(const [v,t] of Object.entries(D.wp_series||{}))w2[v]=merge(w2[v],t.filter(r=>!w2[v]||r[0]>w2[v][w2[v].length-1][0]));D.wp_series=w2}).catch(()=>{})}
 }catch(e){failing=true}
}
async function boot(){
 if(DEMO){D=demoData();demoBar()}
 else if(LIVE){document.getElementById('app').innerHTML='<div class="card" style="margin-top:12px;text-align:center;padding:40px" class="mono">LOADING LIVE NUMBERS...</div>';
  try{const t=Math.floor(Date.now()/2000);const [a,b]=await Promise.all([fetch('data?t='+t,{cache:'no-store'}).then(r=>r.json()),fetch('series?t='+Math.floor(Date.now()/60000),{cache:'no-store'}).then(r=>r.json())]);
   const ws=b.wp_series||{};for(const [v,tl] of Object.entries(a.wp_tail||{}))ws[v]=merge(ws[v],tl);
   D={...a,series_all:b.series_all,series_recent:merge(b.series_recent,a.tail),wp_series:ws};lastSeries=Date.now()}catch(e){}}
 skew=Date.now()/1000-(D.now||Date.now()/1000);
 render();setInterval(status,100);requestAnimationFrame(loop);lastFetch=Date.now();
 if(LIVE)setInterval(tick,EVERY);
}
boot();
(function(){let sid=null;try{sid=sessionStorage.getItem('lg_sid')}catch(e){}
 if(!sid){sid=Math.random().toString(36).slice(2)+Date.now().toString(36);try{sessionStorage.setItem('lg_sid',sid)}catch(e){}}
 let ref='';try{ref=document.referrer?new URL(document.referrer).hostname:''}catch(e){}
 const hit=()=>{if(document.hidden||!LIVE)return;try{fetch('hit',{method:'POST',keepalive:true,headers:{'Content-Type':'application/json'},body:JSON.stringify({sid,ref,w:window.innerWidth})}).catch(()=>{})}catch(e){}};
 hit();setInterval(hit,30000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)hit()})})();
</script></body></html>
"""


def chart_png(key: str = None):
    """PNG bytes of viewers over time, or None if matplotlib isn't installed / no data."""
    ev = events.get(key)
    if not ev:
        return None
    st = events.stats(ev["key"])
    if not st.get("series"):
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        return None
    xs = [datetime.fromtimestamp(s[0], events.REPORT_TZ) for s in st["series"]]
    fig, ax = plt.subplots(figsize=(10, 4.6), dpi=130)
    for idx, label, color, lw in ((1, "Total", "#141821", 2.2), (2, "Official", "#f5a524", 1.4),
                                  (3, "Watch parties", "#17c964", 1.4), (4, "Community", "#5b8cff", 1.4)):
        ax.plot(xs, [s[idx] for s in st["series"]], label=label, color=color, linewidth=lw)
    pk = max(st["series"], key=lambda s: s[1])
    ax.annotate(f"Peak {events.fmt_n(pk[1])} concurrent", (datetime.fromtimestamp(pk[0], events.REPORT_TZ), pk[1]),
                textcoords="offset points", xytext=(0, 8), ha="center", fontsize=9)
    ax.set_title(f"{ev['name']}: concurrent viewers on YouTube (IST)", fontsize=12, loc="left")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M", tz=events.REPORT_TZ))
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: events.fmt_n(v)))
    ax.grid(alpha=.25)
    ax.set_ylim(bottom=0)
    ax.legend(loc="upper left", fontsize=8, frameon=False)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()
