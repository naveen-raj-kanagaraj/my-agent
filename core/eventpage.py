"""Event dashboard (Esports-Charts style): one self-contained page that updates itself, plus a PNG chart for Telegram.

Only streams that are live right now are listed; ended streams only count toward the historical totals (peak, by day).
"""
import html
import io
import json
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
           "links": ev.get("links") or {}}
    if st.get("ticks"):
        live = [{"vid": s["vid"], "channel": s.get("channel", ""), "title": s.get("title", ""), "kind": s["kind"],
                 "viewers": s["viewers"], "url": events.yt_link(s["vid"])} for s in st["live_now"]]
        series = [list(t) for t in st["series"]]
        recent = [t for t in series if t[0] >= series[-1][0] - 6 * 3600]
        out.update(
            live=live, method=st.get("method", ""), updated=st["last"]["ts"],
            peak=st["peak"], peak_when=events._when(st["peak_at"]), avg=round(st["avg_broadcast"]),
            peak_official=st["peak_official"], peak_watch=st["peak_watch"],
            days=[{"day": d["day"], "peak": d["peak"], "avg": round(d["avg_broadcast"]),
                   "at": datetime.fromtimestamp(d["peak_at"], events.REPORT_TZ).strftime("%I:%M %p") if d.get("peak_at") else ""}
                  for d in st["days"]],
            series_all=_thin(series, 1500),
            series_recent=_thin([t for t in recent if t[0] < series[-1][0] - 200], 2400) + [t for t in recent if t[0] >= series[-1][0] - 200], official_live=st.get("official_live", False))
        lb = st.get("last_broadcast")
        if lb:
            tf = lambda ts: datetime.fromtimestamp(ts, events.REPORT_TZ)
            out["last_broadcast"] = {
                "when": f"{tf(lb['start']).strftime('%a %d %b, %I:%M %p')} to {tf(lb['end']).strftime('%I:%M %p')} IST",
                "start": lb["start"], "end": lb["end"],
                "peak": lb["peak"], "peak_when": tf(lb["peak_at"]).strftime("%I:%M %p IST"),
                "split": lb["split"],
                "streams": [{"vid": x["vid"], "channel": x["channel"], "title": x["title"], "kind": x["kind"],
                             "viewers": x["peak"], "at": tf(x["peak_at"]).strftime("%I:%M %p"), "url": events.yt_link(x["vid"])}
                            for x in lb["streams"][:100]]}
    if out.get("ticks"):
        if out.get("official_live"):
            pool = [x for x in out["live"] if x["kind"] == "watch party"] or [x for x in out["live"] if x["kind"] != "official"]
            t1 = time.time() + 5
            t0 = (out.get("series_recent") or [[t1 - 6 * 3600]])[0][0]
        elif out.get("last_broadcast"):
            lb = out["last_broadcast"]
            pool = [x for x in lb["streams"] if x["kind"] == "watch party"] or [x for x in lb["streams"] if x["kind"] != "official"]
            t0, t1 = lb["start"] - 60, lb["end"] + 60
        else:
            pool, t0, t1 = [], 0, 0
        wp = sorted(pool, key=lambda x: -x["viewers"])[:8]
        ser = events.stream_series(ev["key"], [w["vid"] for w in wp], t0, t1)
        peaks = {v: max(p[1] for p in pts) for v, pts in ser.items()}
        out["wp"] = [{"vid": w["vid"], "channel": w["channel"], "viewers": w["viewers"], "url": w["url"],
                      "peak": max(peaks.get(w["vid"], 0), w["viewers"])} for w in wp]
        out["wp_series"] = ser
    with _cache_lock:
        _cache[ev["key"]] = (time.time(), out)
    return out


def _social() -> str:
    return "".join(f'<a class="soc" href="{html.escape(u, quote=True)}" target="_blank" rel="noopener">'
                   f'<b>{html.escape(n.upper())}</b><span>{html.escape(h)}</span></a>' for n, u, h in SOCIAL)


def build_html(key: str = None, live: bool = False) -> str:
    """live=True: the page re-reads ./data every REFRESH_SEC seconds. Otherwise a snapshot (e.g. a file sent on Telegram)."""
    d = data(key)
    payload = json.dumps(d).replace("</", "<\\/")
    return (PAGE.replace("__TITLE__", html.escape(d.get("name", "Event")))
                .replace("__DATA__", payload)
                .replace("__LIVE__", "true" if live else "false")
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
:root{--bg:#07051a;--bg2:#0d0a26;--card:rgba(18,14,48,.78);--card2:rgba(28,22,70,.7);--ink:#ecebff;--muted:#8f8ac0;--line:#2b2566;
--lime:#b6f23a;--purple:#7c5cff;--cyan:#4cc9f0;--orange:#ff8a3d;--red:#ff4d5e;--up:#b6f23a;--down:#ff4d5e}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 "Chakra Petch",system-ui,sans-serif}
body{background:radial-gradient(900px 500px at 70% -10%,rgba(124,92,255,.28),transparent 60%),radial-gradient(700px 400px at -10% 30%,rgba(76,201,240,.10),transparent 60%),var(--bg);min-height:100vh}
body:before{content:"";position:fixed;inset:0;pointer-events:none;z-index:50;background:repeating-linear-gradient(0deg,rgba(255,255,255,.025) 0 1px,transparent 1px 3px)}
a{color:var(--cyan);text-decoration:none}a:hover{text-decoration:underline}
.mono{font-family:"Share Tech Mono",ui-monospace,monospace}
.wrap{max-width:1180px;margin:0 auto;padding:0 16px 40px}
.bar{position:sticky;top:0;z-index:20;background:rgba(7,5,26,.86);backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
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
.big .v{font:700 58px/1 "Chakra Petch",sans-serif;letter-spacing:-.01em;margin:8px 0 6px;font-variant-numeric:tabular-nums;text-shadow:0 0 24px rgba(124,92,255,.55)}
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
td.t{white-space:normal;min-width:0}td.num{font:700 15px "Chakra Petch",sans-serif;font-variant-numeric:tabular-nums}
.rk{font:700 14px "Chakra Petch",sans-serif;color:#0a0a14;text-align:center;width:34px}
.rk.official{background:var(--orange)}.rk.watch{background:var(--cyan)}.rk.community{background:var(--purple);color:#fff}
.ch{font-weight:700;text-transform:uppercase;letter-spacing:.02em}.st{color:var(--muted);font-size:12px;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:520px}
.tag{font:11px "Share Tech Mono",monospace;padding:1px 6px;margin-left:6px;border:1px solid currentColor}
.tag.official{color:var(--orange)}.tag.watch{color:var(--cyan)}.tag.community{color:#a78bfa}
.mini{height:3px;background:linear-gradient(90deg,var(--purple),var(--lime));margin-top:5px;transition:width .6s}
tr.fu td.num{animation:fu 1.2s}tr.fd td.num{animation:fd 1.2s}@keyframes fu{0%{color:var(--up)}}@keyframes fd{0%{color:var(--down)}}
.q{background:var(--card2);border:1px solid var(--line);padding:6px 10px;color:var(--ink);font:12px "Share Tech Mono",monospace;width:180px;max-width:100%}
.more{all:unset;cursor:pointer;display:block;margin:8px auto 0;padding:6px 14px;border:1px solid var(--line);font:12px "Share Tech Mono",monospace;color:var(--muted)}
.grid2{display:grid;grid-template-columns:1fr;gap:12px;margin-top:12px}
.muted{color:var(--muted)}.scroll{overflow-x:auto}
.foot{font-size:12px;color:var(--muted);margin-top:14px}.disc{font-size:11px;border-top:1px solid var(--line);margin-top:10px;padding-top:10px}
@media(max-width:600px){.hide-m{display:none}.st{max-width:56vw}td{padding:7px 5px}.title h1{font-size:16px}.bar .in{gap:6px}.title{width:100%}}
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
<div class="wrap"><div class="follow"><span>// FOLLOW FOR LIVE ESPORTS NUMBERS</span>__SOCIAL__</div></div>
<div class="wrap" id="app"></div>
<div class="modal" id="modal"><div class="mbox"><div class="head"><div><h2 id="mt">Share</h2></div><button class="btn ghost sm" id="mclose">Close</button></div>
 <img id="mimg" alt="Share card"><div class="mrow"><button class="btn" id="mshare">Share</button><button class="btn ghost" id="mdl">Download</button><a class="btn ghost" id="mx" target="_blank" rel="noopener">Post on X</a></div>
 <p class="muted" style="font-size:12px;margin:10px 0 0">Instagram: tap Share on your phone and pick Instagram (Story or Post), or download and upload it.</p></div></div>
<script>
const LIVE=__LIVE__, EVERY=__REFRESH__*1000, URLX='https://live.letsgrowesports.com', BRAND='__BRAND__', TITLE='__TITLE__';
let D=__DATA__, prev={}, prevTotal=null, view='total', range='live', kind='all', q='', skew=0, lastFetch=Date.now(), failing=false, mode=null, showAll=false, hover=null, hidden={};
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
function render(){
 const app=document.getElementById('app');
 if(!D.ticks){app.innerHTML='<div class="card" style="margin-top:12px">No data yet. Numbers are recorded only while the official broadcast is live.</div>';return}
 const off=isOff(),LB=D.last_broadcast||{};
 const m=off?'off':'on';if(mode!==m){mode=m;app.innerHTML='';prev={};prevTotal=null;showAll=false;range=off?'full':'live'}
 const live=off?LB.streams:(D.live||[]),tot=off?LB.peak:live.reduce((a,s)=>a+s.viewers,0);
 const by=off?{official:LB.split.official,'watch party':LB.split.watch,community:LB.split.community}:{official:0,'watch party':0,community:0};
 if(!off)live.forEach(s=>by[s.kind]=(by[s.kind]||0)+s.viewers);
 if(!document.getElementById('big')){
  app.innerHTML=`
  <div class="hero"><div class="card big"><div class="lbl" id="bk"></div><div class="v" id="big" data-v="0">0</div>
    <div><span id="dl" class="delta flat"></span> <span class="muted" id="nlive"></span></div>
    <div class="split" id="split"></div><div class="legend" id="leg"></div></div>
   <div class="kpis">
    <div class="card kpi"><div class="lbl">Peak concurrent</div><div class="v" id="kp"></div><div class="s" id="kpw"></div></div>
    <div class="card kpi"><div class="lbl">Average concurrent</div><div class="v" id="ka"></div><div class="s">while the official broadcast was live</div></div>
    <div class="card kpi"><div class="lbl">Official peak</div><div class="v" id="ko"></div><div class="s">official broadcasts combined</div></div>
    <div class="card kpi"><div class="lbl">Watch parties peak</div><div class="v" id="kw"></div><div class="s">all watch parties combined</div></div></div></div>
  <div class="card"><div class="tabs" id="tabs"><button data-v="total">Total viewers</button><button data-v="split">Official vs watch parties</button><button data-v="wp">Watch party battle</button></div>
   <div class="head"><div><div class="lbl" id="chh"></div><div class="cv" id="cv"></div></div>
    <div class="seg" id="rg"><button data-r="live">LIVE</button><button data-r="full">FULL BROADCAST</button></div>
    <button class="btn sm" id="shareChart">Share</button></div>
   <div class="chart"><canvas id="c"></canvas></div><div class="chips" id="chips"></div></div>
  <div class="grid2">
   <div class="card" id="wpCard"><div class="head"><div><h2 id="wph">Watch party leaderboard</h2><div class="muted" style="font-size:12px">Streamers: share your rank card.</div></div></div>
    <div class="scroll"><table><thead><tr><th>#</th><th>Streamer</th><th class="num" id="wpth">Live</th><th class="num hide-m">Peak</th><th></th></tr></thead><tbody id="wprows"></tbody></table></div></div>
   <div class="card"><div class="head"><div><h2 id="lh">Live streams</h2></div>
    <div class="seg" id="kf">${[['all','ALL'],['official','OFFICIAL'],['watch party','WATCH PARTIES'],['community','COMMUNITY']].map(([k,l])=>`<button data-k="${k}">${l}</button>`).join('')}</div>
    <input class="q" id="q" placeholder="Search channel or title"></div>
    <div class="scroll"><table><thead><tr><th>#</th><th>Channel / stream</th><th class="num" id="cth">Concurrent</th><th class="num hide-m" id="sth">Share</th></tr></thead><tbody id="rows"></tbody></table></div>
    <button class="more" id="more"></button></div>
   <div class="card"><div class="head"><div><h2>By day</h2></div></div><div class="scroll"><table><thead><tr><th>Day (IST)</th><th class="num">Peak</th><th>At</th><th class="num">Average</th></tr></thead><tbody id="days"></tbody></table></div></div>
  </div><div class="foot" id="foot"></div>`;
  document.querySelectorAll('#tabs button').forEach(b=>b.onclick=()=>{view=b.dataset.v;hover=null;drawChart();mark()});
  document.querySelectorAll('#rg button').forEach(b=>b.onclick=()=>{if(b.disabled)return;range=b.dataset.r;hover=null;ys={};drawChart();mark()});
  document.querySelectorAll('#kf button').forEach(b=>b.onclick=()=>{kind=b.dataset.k;rows();mark()});
  document.getElementById('q').oninput=e=>{q=e.target.value.toLowerCase();rows()};
  document.getElementById('more').onclick=()=>{showAll=!showAll;rows()};
  document.getElementById('shareChart').onclick=()=>openShare(view==='wp'?'battle':'total');
  const cv=document.getElementById('c');
  const mv=e=>{const r=cv.getBoundingClientRect(),p=e.touches?e.touches[0]:e;hover=p.clientX-r.left;if(range!=='live')drawChart()};
  cv.addEventListener('mousemove',mv);cv.addEventListener('touchstart',mv,{passive:true});cv.addEventListener('touchmove',mv,{passive:true});
  cv.addEventListener('mouseleave',()=>{hover=null;if(range!=='live')drawChart()});
 }
 document.getElementById('bk').textContent=off?`// Official offline. Last broadcast peak (${LB.when})`:'// Watching now, all live streams';
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
 document.getElementById('leg').innerHTML=Object.keys(by).map(k=>`<span><span class="sw" style="background:${cols[k]}"></span>${k==='watch party'?'WATCH PARTIES':k.toUpperCase()} <b>${fmt(by[k])}</b>${tot?` (${(100*by[k]/tot).toFixed(0)}%)`:''}</span>`).join('');
 document.getElementById('kp').textContent=fmt(D.peak);document.getElementById('kpw').textContent=D.peak_when;
 document.getElementById('ka').textContent=fmt(D.avg);document.getElementById('ko').textContent=fmt(D.peak_official);document.getElementById('kw').textContent=fmt(D.peak_watch);
 document.getElementById('days').innerHTML=(D.days||[]).map(d=>`<tr><td>${esc(d.day)}</td><td class="num">${fmt(d.peak)}</td><td>${esc(d.at)}</td><td class="num">${fmt(d.avg)}</td></tr>`).join('');
 document.getElementById('foot').innerHTML=`Concurrent viewers = people watching at the same moment, summed across every live YouTube stream (official, watch parties, community). Recorded only while the official broadcast is live. Counted from: ${esc(D.method)}.
  <div class="follow"><span>FOLLOW __BRAND__</span>__SOCIAL__</div>
  <div class="disc">Unofficial fan tracker by <a href="__BRANDURL__" target="_blank" rel="noopener">__BRAND__</a>. Not affiliated with or endorsed by KRAFTON. YouTube only; other platforms are not included.</div>`;
 rows();wpRows();chips();drawChart();mark();
}
function wpRows(){
 const off=isOff(),wp=D.wp||[];
 document.getElementById('wph').textContent=off?'Watch party leaderboard, last broadcast':'Watch party leaderboard, live';
 document.getElementById('wprows').innerHTML=wp.map((w,i)=>`<tr><td class="rk watch">${i+1}</td><td class="t"><span class="sw" style="background:${PAL[i%8]}"></span><a class="ch" href="${esc(w.url)}" target="_blank" rel="noopener" style="color:var(--ink)">${esc(w.channel)}</a></td>
  <td class="num">${full(w.viewers)}</td><td class="num hide-m muted">${fmt(w.peak)}</td><td style="text-align:right"><button class="btn sm ghost" data-share="${esc(w.vid)}">Share</button></td></tr>`).join('')||'<tr><td colspan=5 class="muted">No watch parties yet</td></tr>';
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
  return `<tr class="${cl}"><td class="rk ${K[s.kind]}">${i+1}</td><td class="t"><span class="ch">${esc(s.channel)}</span><span class="tag ${K[s.kind]}">${esc(s.kind)}</span>
  <a class="st" href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title.slice(0,100))}</a><div class="mini" style="width:${100*s.viewers/top}%"></div></td>
  <td class="num">${full(s.viewers)}</td><td class="num muted hide-m">${off?esc(s.at):(100*s.viewers/tot).toFixed(1)+'%'}</td></tr>`}).join('')||'<tr><td colspan=4 class="muted">Nothing live right now</td></tr>';
 prev={};src.forEach(s=>prev[s.vid]=s.viewers);
}
function chips(){
 const el=document.getElementById('chips');
 if(view!=='wp'){el.innerHTML='';return}
 el.innerHTML=(D.wp||[]).map((w,i)=>`<button class="chip ${hidden[w.vid]?'offc':''}" data-vid="${esc(w.vid)}"><i style="background:${PAL[i%8]}"></i>${esc(w.channel.slice(0,18))} <b>${fmt(w.viewers)}</b></button>`).join('');
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
 return(D.wp||[]).map((w,i)=>({label:w.channel,color:PAL[i%8],pts:(D.wp_series||{})[w.vid]||[],w:2,vid:w.vid})).filter(l=>!hidden[l.vid]);
}
const WIN=180,LAG=4;let ys={};
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
 else{const tf=t=>new Date(t*1000).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit'});for(let k=0;k<=4;k++){const t=t0+(t1-t0)*k/4;ctx.fillText(tf(t),Math.min(Math.max(X(t),30*fs),cw-30*fs),H-5)}}
 ctx.save();ctx.beginPath();ctx.rect(0,0,cw,H);ctx.clip();
 L.forEach((l,li)=>{const p=vis[li];if(!p.length)return;
  if(l.fill){ctx.beginPath();p.forEach((r,i)=>{i?ctx.lineTo(X(r[0]),Y(r[1])):ctx.moveTo(X(r[0]),Y(r[1]))});ctx.lineTo(X(p[p.length-1][0]),padT+ch);ctx.lineTo(X(p[0][0]),padT+ch);ctx.closePath();
   const g=ctx.createLinearGradient(0,padT,0,padT+ch);g.addColorStop(0,'rgba(124,92,255,.45)');g.addColorStop(1,'rgba(124,92,255,0)');ctx.fillStyle=g;ctx.fill()}
  ctx.beginPath();p.forEach((r,i)=>{i?ctx.lineTo(X(r[0]),Y(r[1])):ctx.moveTo(X(r[0]),Y(r[1]))});
  ctx.strokeStyle=l.color;ctx.lineWidth=l.w;ctx.lineJoin='round';ctx.shadowColor=l.color;ctx.shadowBlur=live?12:4;ctx.stroke();ctx.shadowBlur=0});
 ctx.restore();
 // heads + end labels
 const ends=[];L.forEach((l,li)=>{const p=vis[li];if(!p.length)return;const r=p[p.length-1];ends.push({x:X(r[0]),y:Y(r[1]),v:r[1],c:l.color,label:l.label})});
 if(live){const ph=(Date.now()%1200)/1200;ends.forEach(e=>{ctx.beginPath();ctx.arc(e.x,e.y,4+ph*10,0,7);ctx.globalAlpha=(1-ph)*.5;ctx.fillStyle=e.c;ctx.fill();ctx.globalAlpha=1;ctx.beginPath();ctx.arc(e.x,e.y,4,0,7);ctx.fill()})}
 ends.sort((a,b)=>a.y-b.y);let lastY=-99;ends.forEach(e=>{e.ly=Math.max(e.y,lastY+(o.multi?15:22)*fs);lastY=e.ly});
 ctx.textBaseline='middle';ctx.textAlign='left';
 ends.forEach(e=>{if(o.multi||L.length>1){ctx.fillStyle=e.c;ctx.font=F(12);ctx.fillText(fmt(e.v),cw+6,e.ly)}
  else{ctx.fillStyle=e.c;ctx.fillRect(cw+2,e.ly-10*fs,padR-4,20*fs);ctx.fillStyle='#0a0a14';ctx.font=F(12,1);ctx.fillText(fmt(e.v),cw+7,e.ly)}});
 if(o.hover!=null&&o.hover<cw){const tt=t0+(o.hover/cw)*(t1-t0),x=X(tt);ctx.strokeStyle=css('--muted');ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(x,padT);ctx.lineTo(x,padT+ch);ctx.stroke();ctx.setLineDash([]);
  const rowsH=L.map((l,li)=>{const p=vis[li];if(!p.length)return null;let b=p[0];for(const r of p)if(Math.abs(r[0]-tt)<Math.abs(b[0]-tt))b=r;return[l,b]}).filter(Boolean).sort((a,b)=>b[1][1]-a[1][1]);
  const lab=[new Date(tt*1000).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata'}),...rowsH.map(([l,b])=>`${l.label.slice(0,16)}: ${full(b[1])}`)];
  ctx.font='12px "Share Tech Mono",monospace';const w=Math.max(...lab.map(s=>ctx.measureText(s).width))+16,h=lab.length*16+8,bx=x+12+w>cw?x-12-w:x+12;
  ctx.fillStyle='rgba(13,10,38,.95)';ctx.strokeStyle=css('--line');ctx.fillRect(bx,padT,w,h);ctx.strokeRect(bx,padT,w,h);
  lab.forEach((s,i)=>{ctx.fillStyle=i?(rowsH[i-1][0].color):css('--muted');ctx.fillText(s,bx+8,padT+12+i*16)})}
 return{t0,t1,last:ends}
}
function drawChart(){
 const cv=document.getElementById('c');if(!cv)return;
 const dpr=window.devicePixelRatio||1,W=cv.clientWidth,H=cv.clientHeight;
 if(cv.width!==Math.round(W*dpr)||cv.height!==Math.round(H*dpr)){cv.width=Math.round(W*dpr);cv.height=Math.round(H*dpr)}
 const ctx=cv.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);
 const L=lines(),live=range==='live';
 plot(ctx,W,H,L,{live,hover,multi:view==='wp',key:view+range,padR:view==='wp'?52:62});
 const h=document.getElementById('chh'),c=document.getElementById('cv'),LB=D.last_broadcast;
 const lastOf=l=>l.pts.length?l.pts[l.pts.length-1][1]:0,peakOf=l=>l.pts.reduce((a,r)=>Math.max(a,r[1]),0);
 const tag=live?'// live, last 3 minutes':(isOff()&&LB?`// last broadcast, ${LB.when}`:'// last 6 hours');
 if(view==='total'){h.textContent=tag;c.innerHTML=L[0]&&L[0].pts.length?`${full(live?lastOf(L[0]):peakOf(L[0]))}<small>${live?'TOTAL WATCHING':'PEAK'}</small>`:''}
 else if(view==='split'){h.textContent=tag;c.innerHTML=L[0].pts.length?`<span style="color:var(--orange)">${fmt(live?lastOf(L[0]):peakOf(L[0]))}</span> <small>OFFICIAL</small> <span style="color:var(--cyan)">${fmt(live?lastOf(L[1]):peakOf(L[1]))}</span> <small>WATCH PARTIES</small>`:''}
 else{h.textContent=tag+' // tap a name to hide it';const w=(D.wp||[])[0];c.innerHTML=w?`${esc(w.channel)}<small>#1 WATCH PARTY ${fmt(w.viewers)}</small>`:''}
}
function loop(){if(range==='live'&&!document.hidden)drawChart();requestAnimationFrame(loop)}
window.addEventListener('resize',()=>drawChart());
function mark(){document.querySelectorAll('#tabs button').forEach(b=>b.classList.toggle('on',b.dataset.v===view));
 document.querySelectorAll('#rg button').forEach(b=>{b.classList.toggle('on',b.dataset.r===range);if(b.dataset.r==='live')b.disabled=!D.official_live});
 document.querySelectorAll('#kf button').forEach(b=>b.classList.toggle('on',b.dataset.k===kind))}
// ---------- share cards ----------
function card(type,vid){
 const W=1080,H=1350,c=document.createElement('canvas');c.width=W;c.height=H;const x=c.getContext('2d');
 const g=x.createRadialGradient(W*.75,0,50,W*.75,0,1100);g.addColorStop(0,'#2a1a7a');g.addColorStop(1,'#07051a');x.fillStyle=g;x.fillRect(0,0,W,H);
 x.fillStyle='rgba(255,255,255,.03)';for(let yy=0;yy<H;yy+=4)x.fillRect(0,yy,W,1);
 const br=(X0,Y0,X1,Y1)=>{x.strokeStyle='#b6f23a';x.lineWidth=5;x.beginPath();x.moveTo(X0,Y0+40);x.lineTo(X0,Y0);x.lineTo(X0+40,Y0);x.moveTo(X1,Y1-40);x.lineTo(X1,Y1);x.lineTo(X1-40,Y1);x.stroke()};
 br(40,40,W-40,H-40);
 x.fillStyle='#b6f23a';x.font='30px "Share Tech Mono",monospace';x.textBaseline='top';x.fillText(BRAND,80,80);
 x.fillStyle='#ecebff';x.font='700 56px "Chakra Petch",sans-serif';x.fillText((TITLE+' LIVE VIEWERSHIP').toUpperCase(),80,125);
 const off=isOff(),LB=D.last_broadcast||{},wp=D.wp||[];
 const when=new Date().toLocaleString('en-IN',{timeZone:'Asia/Kolkata',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'})+' IST';
 x.fillStyle='#ff4d5e';x.font='30px "Share Tech Mono",monospace';
 let big,label,L,sub='';
 if(type==='streamer'){const i=wp.findIndex(w=>w.vid===vid),w=wp[i];big=w.viewers;label=off?`#${i+1} WATCH PARTY, LAST BROADCAST`:`#${i+1} WATCH PARTY RIGHT NOW`;sub=w.channel;
  L=wp.map((v,j)=>({label:v.channel,color:j===i?'#b6f23a':'rgba(143,138,192,.55)',pts:(D.wp_series||{})[v.vid]||[],w:j===i?6:2.5}));L.push(L.splice(i,1)[0])}
 else if(type==='battle'){big=wp[0]?wp[0].viewers:0;label='WATCH PARTY BATTLE';sub=wp[0]?wp[0].channel+' leads':'';L=wp.map((v,j)=>({label:v.channel,color:PAL[j%8],pts:(D.wp_series||{})[v.vid]||[],w:4}))}
 else{big=off?LB.peak:(D.live||[]).reduce((a,s)=>a+s.viewers,0);label=off?'PEAK CONCURRENT, LAST BROADCAST':'WATCHING RIGHT NOW';
  const src=D.series_recent||[];L=[{label:'Total',color:'#b6f23a',pts:src.map(r=>[r[0],r[1]]),w:6,fill:true}]}
 x.fillText('// '+label,80,230);
 if(sub){x.fillStyle='#ecebff';x.font='700 64px "Chakra Petch",sans-serif';x.fillText(sub.toUpperCase().slice(0,26),80,275)}
 x.fillStyle='#ffffff';x.font='700 190px "Chakra Petch",sans-serif';x.shadowColor='rgba(124,92,255,.8)';x.shadowBlur=40;x.fillText(full(big),72,sub?350:285);x.shadowBlur=0;
 x.fillStyle='#8f8ac0';x.font='30px "Share Tech Mono",monospace';x.fillText('CONCURRENT VIEWERS ON YOUTUBE',80,sub?560:495);
 const cy=sub?620:560,chH=type==='total'?420:400;
 x.save();x.translate(60,cy);plot(x,W-120,chH,L,{live:false,multi:type!=='total',key:'card'+type,padR:130,padT:10,fs:2.2});x.restore();
 let ly=cy+chH+30;
 if(type!=='total'){x.font='28px "Share Tech Mono",monospace';wp.slice(0,5).forEach((w,j)=>{x.fillStyle=type==='streamer'&&w.vid===vid?'#b6f23a':'#ecebff';x.fillText(`${j+1}. ${w.channel.slice(0,24).toUpperCase()}`,80,ly);x.textAlign='right';x.fillText(full(w.viewers),W-80,ly);x.textAlign='left';ly+=40})}
 else{x.font='30px "Share Tech Mono",monospace';x.fillStyle='#ff8a3d';x.fillText(`PEAK ${fmt(D.peak)}  //  ${D.peak_when}`.toUpperCase(),80,ly)}
 x.fillStyle='#b6f23a';x.fillRect(0,H-120,W,120);x.fillStyle='#0a0a14';x.font='700 40px "Chakra Petch",sans-serif';x.fillText('LIVE.LETSGROWESPORTS.COM',80,H-95);
 x.font='26px "Share Tech Mono",monospace';x.fillText(`${when}  //  @letsgrowesports`,80,H-48);
 return c;
}
let cur=null;
function openShare(type,vid){
 const c=card(type,vid);c.toBlob(b=>{cur={blob:b,name:`bmsd-${type}.png`};document.getElementById('mimg').src=URL.createObjectURL(b)},'image/png');
 const wp=D.wp||[],i=wp.findIndex(w=>w.vid===vid);
 let text;if(type==='streamer'){const w=wp[i];text=`${w.channel} is the #${i+1} watch party at ${TITLE} with ${full(w.viewers)} watching${isOff()?'':' live'}. Track it live:`}
 else if(type==='battle')text=`${TITLE} watch party battle: ${wp.slice(0,3).map((w,j)=>`${j+1}. ${w.channel} ${fmt(w.viewers)}`).join(' | ')}. Live:`;
 else text=`${full(isOff()?D.last_broadcast.peak:(D.live||[]).reduce((a,s)=>a+s.viewers,0))} watching ${TITLE} across YouTube${isOff()?' at the peak':' right now'}. Live tracker:`;
 document.getElementById('mt').textContent=type==='streamer'?'Share your rank':'Share';
 document.getElementById('mx').href='https://x.com/intent/post?text='+encodeURIComponent(text+' '+URLX+' via @letsgrowesports');
 document.getElementById('modal').classList.add('on');cur&&(cur.text=text);window._shareText=text;
}
document.getElementById('mclose').onclick=()=>document.getElementById('modal').classList.remove('on');
document.getElementById('modal').onclick=e=>{if(e.target.id==='modal')e.target.classList.remove('on')};
document.getElementById('mdl').onclick=()=>{if(!cur)return;const a=document.createElement('a');a.href=URL.createObjectURL(cur.blob);a.download=cur.name;a.click()};
document.getElementById('mshare').onclick=async()=>{if(!cur)return;const f=new File([cur.blob],cur.name,{type:'image/png'});
 try{if(navigator.canShare&&navigator.canShare({files:[f]}))await navigator.share({files:[f],text:window._shareText+' '+URLX});
  else if(navigator.share)await navigator.share({text:window._shareText,url:URLX});else document.getElementById('mdl').click()}catch(e){}};
// ---------- status + polling ----------
function status(){
 const age=D.updated?Math.max(0,nowS()-D.updated):null;
 document.getElementById('ago').textContent=age===null?'-':age<60?`${age.toFixed(0)}s`:`${Math.floor(age/60)}m`;
 const st=document.getElementById('st'),t=document.getElementById('stt'),live=D.official_live&&(D.live||[]).length>0;
 if(!LIVE){st.className='pill off';t.textContent='SNAPSHOT'}
 else if(failing){st.className='pill warn';t.textContent='RECONNECTING'}
 else if(age!==null&&age>Math.max(15,D.every*6)&&live){st.className='pill warn';t.textContent='DELAYED'}
 else if(live){st.className='pill';t.textContent=`LIVE // EVERY ${D.every}S`}
 else{st.className='pill off';t.textContent='OFFICIAL OFFLINE'}
 const nx=document.getElementById('nx');if(!LIVE){nx.style.display='none';return}
 const left=Math.max(0,EVERY-(Date.now()-lastFetch));document.getElementById('nxt').textContent=(left/1000).toFixed(1)+'s';
 document.getElementById('rp').setAttribute('stroke-dashoffset',44*(left/EVERY));
}
function merge(a,tail){a=a||[];const last=a.length?a[a.length-1][0]:0;for(const r of tail||[])if(r[0]>last)a.push(r);return a}
let lastSeries=Date.now();
async function tick(){
 if(document.hidden){lastFetch=Date.now();return}
 lastFetch=Date.now();
 try{const r=await fetch('data');if(!r.ok)throw 0;const j=await r.json();
  const sr=merge(D.series_recent,j.tail),sa=D.series_all||[];
  if(j.tail&&j.tail.length&&(!sa.length||j.tail[j.tail.length-1][0]-sa[sa.length-1][0]>60))sa.push(j.tail[j.tail.length-1]);
  const cut=(sr.length?sr[sr.length-1][0]:0)-6*3600;while(sr.length&&sr[0][0]<cut)sr.shift();
  const ws=D.wp_series||{};for(const [v,t] of Object.entries(j.wp_tail||{}))ws[v]=merge(ws[v],t);
  D={...j,series_recent:sr,series_all:sa,wp_series:ws};skew=Date.now()/1000-D.now;failing=false;render();
  const need=(D.wp||[]).some(w=>!ws[w.vid]);
  if(need||Date.now()-lastSeries>300000){lastSeries=Date.now();fetch('series').then(x=>x.json()).then(x=>{D.series_all=x.series_all;D.series_recent=x.series_recent;
   const w2=x.wp_series||{};for(const [v,t] of Object.entries(D.wp_series||{}))w2[v]=merge(w2[v],t.filter(r=>!w2[v]||r[0]>w2[v][w2[v].length-1][0]));D.wp_series=w2}).catch(()=>{})}
 }catch(e){failing=true}
}
skew=Date.now()/1000-(D.now||Date.now()/1000);
render();setInterval(status,100);loop();
if(LIVE)setInterval(tick,EVERY);
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
