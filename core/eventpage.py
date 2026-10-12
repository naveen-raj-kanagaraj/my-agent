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


BRAND = os.getenv("EVENT_BRAND", "Let's Grow Esports")
BRAND_URL = os.getenv("EVENT_BRAND_URL", "https://letsgrowesports.com")


def live_data(key: str = None) -> dict:
    """What the page polls every few seconds: numbers + live streams + the last ~3 minutes of the chart (~2-5 KB)."""
    d = data(key)
    out = {k: v for k, v in d.items() if k not in ("series_all", "series_recent")}
    out["tail"] = (d.get("series_recent") or [])[-90:]
    return out


def series_data(key: str = None) -> dict:
    d = data(key)
    return {"series_all": d.get("series_all", []), "series_recent": d.get("series_recent", [])}


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
                "peak": lb["peak"], "peak_when": tf(lb["peak_at"]).strftime("%I:%M %p IST"),
                "split": lb["split"],
                "streams": [{"vid": x["vid"], "channel": x["channel"], "title": x["title"], "kind": x["kind"],
                             "viewers": x["peak"], "at": tf(x["peak_at"]).strftime("%I:%M %p"), "url": events.yt_link(x["vid"])}
                            for x in lb["streams"][:100]]}
    with _cache_lock:
        _cache[ev["key"]] = (time.time(), out)
    return out


def build_html(key: str = None, live: bool = False) -> str:
    """live=True: the page re-reads ./data every REFRESH_SEC seconds. Otherwise a snapshot (e.g. a file sent on Telegram)."""
    d = data(key)
    payload = json.dumps(d).replace("</", "<\\/")
    return (PAGE.replace("__TITLE__", html.escape(d.get("name", "Event")))
                .replace("__DATA__", payload)
                .replace("__LIVE__", "true" if live else "false")
                .replace("__REFRESH__", str(REFRESH_SEC))
                .replace("__BRAND__", html.escape(BRAND)).replace("__BRANDURL__", html.escape(BRAND_URL, quote=True)))


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>__TITLE__ live viewers</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500&display=swap" rel="stylesheet">
<style>
:root{--bg:#0b0d12;--card:#141821;--card2:#1a1f2b;--ink:#eef0f6;--muted:#8a93a8;--line:#242a37;--acc:#7c9cff;
--off:#f5a524;--wp:#22c55e;--com:#7c9cff;--up:#22c55e;--down:#ef4444;--live:#ef4444;--warn:#f59e0b}
@media (prefers-color-scheme: light){:root:not([data-theme="dark"]){--bg:#f4f5f9;--card:#fff;--card2:#f7f8fb;--ink:#121620;--muted:#5f6779;--line:#e3e6ee;--acc:#3b5bdb}}
*{box-sizing:border-box}html,body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 Inter,system-ui,-apple-system,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:0 16px 40px}
.bar{position:sticky;top:0;z-index:10;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
.bar .in{max-width:1180px;margin:0 auto;padding:10px 16px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.title{font-weight:800;font-size:16px;letter-spacing:-.01em;margin-right:auto}
.pill{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:999px;background:var(--card);border:1px solid var(--line);font-size:12px;font-weight:600;white-space:nowrap}
.dot{width:8px;height:8px;border-radius:50%;background:var(--live);box-shadow:0 0 0 0 var(--live);animation:pulse 1.6s infinite}
.pill.off .dot{background:var(--muted);animation:none}.pill.warn{color:var(--warn)}.pill.warn .dot{background:var(--warn)}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(239,68,68,.6)}70%{box-shadow:0 0 0 8px rgba(239,68,68,0)}100%{box-shadow:0 0 0 0 rgba(239,68,68,0)}}
.mono{font-family:"JetBrains Mono",ui-monospace,monospace}
.ring{width:16px;height:16px}.ring circle{fill:none;stroke:var(--line);stroke-width:3}.ring .p{stroke:var(--acc);stroke-linecap:round;transform:rotate(-90deg);transform-origin:50% 50%}
.hero{display:grid;grid-template-columns:1.4fr 1fr;gap:12px;margin:16px 0 12px}
@media(max-width:760px){.hero{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;min-width:0}
.big .k{color:var(--muted);font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.06em}
.big .v{font-size:52px;font-weight:800;letter-spacing:-.03em;line-height:1.05;margin:6px 0 4px;font-variant-numeric:tabular-nums}
.delta{font-size:13px;font-weight:700}.delta.up{color:var(--up)}.delta.down{color:var(--down)}.delta.flat{color:var(--muted)}
.split{display:flex;height:10px;border-radius:6px;overflow:hidden;background:var(--line);margin:12px 0 8px}
.split div{transition:width .6s ease}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--muted)}.legend b{color:var(--ink);font-variant-numeric:tabular-nums}
.sw{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:5px}
.kpis{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.kpi{background:var(--card2);border:1px solid var(--line);border-radius:12px;padding:10px 12px}
.kpi .k{color:var(--muted);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em}
.kpi .v{font-size:22px;font-weight:700;font-variant-numeric:tabular-nums;margin-top:2px}.kpi .s{color:var(--muted);font-size:11px}
h2{font-size:13px;margin:0;color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:.05em}
.head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px}.head h2{margin-right:auto}
.seg{display:inline-flex;background:var(--card2);border:1px solid var(--line);border-radius:10px;padding:2px}
.seg button{all:unset;cursor:pointer;padding:5px 10px;border-radius:8px;font-size:12px;font-weight:600;color:var(--muted)}
.seg button.on{background:var(--card);color:var(--ink);box-shadow:0 1px 2px rgba(0,0,0,.2)}
input.q{background:var(--card2);border:1px solid var(--line);border-radius:10px;padding:6px 10px;color:var(--ink);font:inherit;font-size:12px;width:170px;max-width:100%}
.chart{position:relative;height:340px}.cv{margin-top:4px;font-size:26px;font-weight:800;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.cv .delta{font-size:14px;margin-left:6px}@media(max-width:600px){.chart{height:260px}}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:8px;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.05em}
td.t{white-space:normal;min-width:200px}td.num{text-align:right;font-variant-numeric:tabular-nums;font-weight:700}th.num{text-align:right}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
.tag{font-size:11px;padding:2px 7px;border-radius:6px;font-weight:600}.tag.official{color:var(--off);background:rgba(245,165,36,.12)}
.tag.watch{color:var(--wp);background:rgba(34,197,94,.12)}.tag.community{color:var(--com);background:rgba(124,156,255,.12)}
.mini{height:4px;border-radius:3px;background:var(--acc);opacity:.75;margin-top:5px;transition:width .6s ease}
tr.fu td.num{animation:fu 1.2s}tr.fd td.num{animation:fd 1.2s}tr.new td{animation:nw 2s}
@keyframes fu{0%{color:var(--up)}100%{}}@keyframes fd{0%{color:var(--down)}100%{}}@keyframes nw{0%{background:rgba(124,156,255,.18)}100%{}}
.brand{display:block;font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--acc);margin-bottom:1px}
.disc{font-size:11px;color:var(--muted);border-top:1px solid var(--line);margin-top:14px;padding-top:10px}.ch{font-weight:600}.muted{color:var(--muted)}.scroll{overflow-x:auto}.foot{font-size:12px;color:var(--muted);margin-top:14px}
.grid2{display:grid;grid-template-columns:1fr;gap:12px;margin-top:12px}
.mt{display:none;margin-left:6px}
@media(max-width:600px){.big .v{font-size:42px}.hide-m{display:none}.mt{display:inline}th,td{padding:8px 5px}td.t{min-width:0}
 .bar .in{gap:6px}.title{width:100%}.pill{font-size:11px;padding:3px 8px}input.q{width:100%}}
</style></head><body>
<div class="bar"><div class="in">
 <div class="title"><a class="brand" href="__BRANDURL__" target="_blank" rel="noopener">__BRAND__</a>__TITLE__ <span class="muted" style="font-weight:600">live viewership</span></div>
 <span id="st" class="pill"><span class="dot"></span><span id="stt">Live</span></span>
 <span class="pill mono" title="Time since the newest reading">Updated <span id="ago">-</span></span>
 <span class="pill mono" id="nx" title="The page checks for new numbers every few seconds">
  <svg class="ring" viewBox="0 0 20 20"><circle cx="10" cy="10" r="7"/><circle class="p" id="rp" cx="10" cy="10" r="7" stroke-dasharray="44" stroke-dashoffset="0"/></svg>
  Next in <span id="nxt">-</span></span>
</div></div>
<div class="wrap" id="app"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>
const LIVE=__LIVE__, EVERY=__REFRESH__*1000;
let split=localGet('split')==='1', D=__DATA__, prev={}, prevTotal=null, chart=null, range=localGet('range')||'1h', kind=localGet('kind')||'all', q='', skew=0, lastFetch=Date.now(), failing=false;
function localGet(k){try{return localStorage.getItem('ev_'+k)}catch(e){return null}}
function localSet(k,v){try{localStorage.setItem('ev_'+k,v)}catch(e){}}
const fmt=n=>{n=+n||0;return n>=1e6?(n/1e6).toFixed(2)+'M':n>=1e4?(n/1e3).toFixed(1)+'K':Math.round(n).toLocaleString('en-IN')};
const full=n=>Math.round(+n||0).toLocaleString('en-IN');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const K={official:'official','watch party':'watch',community:'community'};
const css=v=>getComputedStyle(document.documentElement).getPropertyValue(v).trim();
function tween(el,to){const from=+el.dataset.v||0;el.dataset.v=to;if(from===to){el.textContent=full(to);return}
 const t0=performance.now();const step=t=>{const k=Math.min(1,(t-t0)/600);el.textContent=full(from+(to-from)*(1-Math.pow(1-k,3)));if(k<1)requestAnimationFrame(step)};requestAnimationFrame(step)}
let mode=null;
function render(){
 const app=document.getElementById('app');
 if(!D.ticks){app.innerHTML='<div class="card" style="margin-top:16px">No data yet. Numbers are recorded only while the official broadcast is live.</div>';return}
 const off=!D.official_live&&D.last_broadcast, LB=D.last_broadcast||{};
 const m=off?'off':'on'; if(mode!==m){mode=m;app.innerHTML='';if(chart){chart.destroy();chart=null}prev={};prevTotal=null}
 const live=off?LB.streams:(D.live||[]), tot=off?LB.peak:live.reduce((a,s)=>a+s.viewers,0);
 const by=off?{official:LB.split.official,'watch party':LB.split.watch,community:LB.split.community}:{official:0,'watch party':0,community:0};
 if(!off)live.forEach(s=>by[s.kind]=(by[s.kind]||0)+s.viewers);
 if(!document.getElementById('big')){
  app.innerHTML=`
  <div class="hero">
   <div class="card big"><div class="k" id="bk"></div>
    <div class="v" id="big" data-v="0">0</div><div><span id="dl" class="delta flat"></span> <span class="muted" id="nlive"></span></div>
    <div class="split" id="split"></div><div class="legend" id="leg"></div></div>
   <div class="kpis">
    <div class="kpi"><div class="k">Peak concurrent</div><div class="v" id="kp"></div><div class="s" id="kpw"></div></div>
    <div class="kpi"><div class="k">Average concurrent</div><div class="v" id="ka"></div><div class="s">while the official broadcast was live</div></div>
    <div class="kpi"><div class="k">Official peak</div><div class="v" id="ko"></div><div class="s">official broadcasts combined</div></div>
    <div class="kpi"><div class="k">Watch parties peak</div><div class="v" id="kw"></div><div class="s">all watch parties combined</div></div>
   </div></div>
  <div class="card"><div class="head"><div style="margin-right:auto"><h2>Total concurrent (IST)</h2>
    <div class="cv"><span id="cv"></span> <span id="cc" class="delta"></span></div></div>
   <div class="seg" id="sp"><button data-s="0">Total</button><button data-s="1">Split</button></div>
   <div class="seg" id="rg">${['15m','1h','6h','all'].map(r=>`<button data-r="${r}">${r==='all'?'All':r.toUpperCase()}</button>`).join('')}</div></div>
   <div class="chart"><canvas id="c"></canvas></div></div>
  <div class="grid2">
  <div class="card"><div class="head"><h2 id="lh">Live streams</h2>
   <div class="seg" id="kf">${[['all','All'],['official','Official'],['watch party','Watch parties'],['community','Community']].map(([k,l])=>`<button data-k="${k}">${l}</button>`).join('')}</div>
   <input class="q" id="q" placeholder="Search channel or title"></div>
   <div class="scroll"><table><thead><tr><th>#</th><th>Channel / stream</th><th class="hide-m">Type</th><th class="num" id="cth">Concurrent</th><th class="num hide-m" id="sth">Share</th></tr></thead><tbody id="rows"></tbody></table></div></div>
  <div class="card"><div class="head"><h2>By day</h2></div><div class="scroll"><table><thead><tr><th>Day (IST)</th><th class="num">Peak</th><th>At</th><th class="num">Average</th></tr></thead><tbody id="days"></tbody></table></div></div>
  </div>
  <div class="foot" id="foot"></div>`;
  document.getElementById('bk').textContent=off?`Official broadcast offline. Last broadcast peak (${LB.when})`:'Watching now, all live streams';
  document.getElementById('cth').textContent=off?'Peak concurrent':'Concurrent';
  document.getElementById('sth').textContent=off?'At (IST)':'Share';
  document.querySelectorAll('#rg button').forEach(b=>b.onclick=()=>{range=b.dataset.r;localSet('range',range);drawChart();mark()});
  document.querySelectorAll('#sp button').forEach(b=>b.onclick=()=>{split=b.dataset.s==='1';localSet('split',split?'1':'0');if(chart){chart.destroy();chart=null}drawChart();mark()});
  document.querySelectorAll('#kf button').forEach(b=>b.onclick=()=>{kind=b.dataset.k;localSet('kind',kind);rows();mark()});
  document.getElementById('q').oninput=e=>{q=e.target.value.toLowerCase();rows()};
 }
 tween(document.getElementById('big'),tot);
 const dl=document.getElementById('dl');
 if(off){dl.className='delta flat';dl.textContent='at '+LB.peak_when}
 else if(prevTotal!==null&&prevTotal!==tot){const d=tot-prevTotal;dl.className='delta '+(d>0?'up':'down');dl.textContent=(d>0?'▲ +':'▼ ')+full(d)+' since last reading'}
 else if(prevTotal===null)dl.textContent='';
 prevTotal=tot;
 document.getElementById('nlive').textContent=off?`across ${live.length} streams (official + watch parties)`:live.length?`across ${live.length} live streams`:'Nothing live right now';
 const cols={official:css('--off'),'watch party':css('--wp'),community:css('--com')};
 document.getElementById('split').innerHTML=Object.keys(by).map(k=>`<div style="width:${tot?100*by[k]/tot:0}%;background:${cols[k]}"></div>`).join('');
 document.getElementById('leg').innerHTML=Object.keys(by).map(k=>`<span><span class="sw" style="background:${cols[k]}"></span>${k==='watch party'?'Watch parties':k[0].toUpperCase()+k.slice(1)} <b>${fmt(by[k])}</b>${tot?` (${(100*by[k]/tot).toFixed(0)}%)`:''}</span>`).join('');
 document.getElementById('kp').textContent=fmt(D.peak);document.getElementById('kpw').textContent=D.peak_when;
 document.getElementById('ka').textContent=fmt(D.avg);document.getElementById('ko').textContent=fmt(D.peak_official);
 document.getElementById('kw').textContent=fmt(D.peak_watch);
 document.getElementById('days').innerHTML=(D.days||[]).map(d=>`<tr><td>${esc(d.day)}</td><td class="num">${fmt(d.peak)}</td><td>${esc(d.at)}</td><td class="num">${fmt(d.avg)}</td></tr>`).join('');
 const links=Object.entries(D.links||{}).map(([l,u])=>`<a href="${esc(u)}" target="_blank" rel="noopener">${esc(l)}</a>`).join(' &middot; ');
 document.getElementById('foot').innerHTML=`<div class="disc">Unofficial tracker by <a href="__BRANDURL__" target="_blank" rel="noopener">__BRAND__</a>. Not affiliated with or endorsed by KRAFTON. YouTube only; other platforms are not included, so totals are lower than all-platform figures.</div>`+`YouTube only. Concurrent viewers = people watching at the same moment, summed across every live stream. Recorded only while the official broadcast is live (watch parties included). Counted from: ${esc(D.method)}.${links?'<br>'+links:''}`;
 rows();drawChart();mark();
}
function rows(){
 const off=!D.official_live&&D.last_broadcast, src=off?D.last_broadcast.streams:(D.live||[]);
 const live=src.filter(s=>(kind==='all'||s.kind===kind)&&(!q||(s.channel+' '+s.title).toLowerCase().includes(q)));
 const tot=src.reduce((a,s)=>a+s.viewers,0)||1, top=Math.max(1,...live.map(s=>s.viewers));
 document.getElementById('lh').textContent=off?`Streams in the last broadcast (${live.length})`:`Live streams (${live.length})`;
 document.getElementById('rows').innerHTML=live.map((s,i)=>{const p=prev[s.vid];const cl=p===undefined&&Object.keys(prev).length?'new':p<s.viewers?'fu':p>s.viewers?'fd':'';
  return `<tr class="${cl}"><td class="muted">${i+1}</td><td class="t"><div class="ch">${esc(s.channel)}<span class="tag mt ${K[s.kind]}">${esc(s.kind)}</span></div><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title.slice(0,100))}</a><div class="mini" style="width:${100*s.viewers/top}%"></div></td>
  <td class="hide-m"><span class="tag ${K[s.kind]}">${esc(s.kind)}</span></td><td class="num">${full(s.viewers)}</td><td class="num muted hide-m">${off?esc(s.at):(100*s.viewers/tot).toFixed(1)+'%'}</td></tr>`}).join('')||'<tr><td colspan=5 class="muted">Nothing live right now</td></tr>';
 prev={};src.forEach(s=>prev[s.vid]=s.viewers);
}
const cross={id:'cross',afterDraw(c){const a=c.tooltip&&c.tooltip.getActiveElements();if(!a||!a.length)return;const x=a[0].element.x,ctx=c.ctx,ar=c.chartArea;
 ctx.save();ctx.setLineDash([4,4]);ctx.strokeStyle=css('--muted');ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x,ar.top);ctx.lineTo(x,ar.bottom);ctx.stroke();ctx.restore()}};
function drawChart(){
 if(!window.Chart||!document.getElementById('c'))return;
 const src=range==='all'?(D.series_all||[]):(D.series_recent||[]);const span={'15m':900,'1h':3600,'6h':21600}[range];
 const last=src.length?src[src.length-1][0]:0;const s=span?src.filter(r=>r[0]>=last-span):src;
 const first=s.length?s[0][1]:0,cur=s.length?s[s.length-1][1]:0,ch=cur-first,up=ch>=0;
 const col=up?css('--up'):css('--down');
 document.getElementById('cv').textContent=full(cur);
 const cc=document.getElementById('cc');cc.className='delta '+(ch>0?'up':ch<0?'down':'flat');
 cc.textContent=`${ch>=0?'+':'\u2212'}${fmt(Math.abs(ch))} (${first?(100*ch/first).toFixed(2):'0.00'}%) ${range==='all'?'event':'past '+range.toUpperCase()}`;
 const lab=s.map(r=>r[0]*1000);
 const tf=t=>new Date(t).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit',
  second:range==='15m'?'2-digit':undefined,day:range==='all'?'2-digit':undefined,month:range==='all'?'short':undefined});
 const grad=c=>{const {ctx,chartArea:a}=c.chart;if(!a)return col+'33';const g=ctx.createLinearGradient(0,a.top,0,a.bottom);g.addColorStop(0,col+'55');g.addColorStop(1,col+'00');return g};
 const n=s.length;
 const ds=[{label:'Total',data:s.map(r=>r[1]),borderColor:col,backgroundColor:grad,fill:true,borderWidth:2,tension:.15,
   pointRadius:s.map((_,i)=>i===n-1?4:0),pointBackgroundColor:col,pointBorderColor:css('--card'),pointBorderWidth:2,pointHoverRadius:5}];
 if(split)[['Official',2,css('--off')],['Watch parties',3,css('--wp')],['Community',4,css('--com')]].forEach(([l,i,c])=>
   ds.push({label:l,data:s.map(r=>r[i]),borderColor:c,borderWidth:1.3,pointRadius:0,pointHoverRadius:3,tension:.15,fill:false}));
 if(chart){chart.data.labels=lab;chart.data.datasets.forEach((d,i)=>{Object.assign(d,ds[i])});chart.update('none');return}
 chart=new Chart(document.getElementById('c'),{type:'line',data:{labels:lab,datasets:ds},plugins:[cross],options:{responsive:true,maintainAspectRatio:false,animation:false,
  interaction:{mode:'index',intersect:false},layout:{padding:{top:6}},
  plugins:{legend:{display:split,position:'bottom',labels:{color:css('--muted'),boxWidth:8,boxHeight:8,usePointStyle:true}},
   tooltip:{backgroundColor:css('--card2'),borderColor:css('--line'),borderWidth:1,titleColor:css('--muted'),bodyColor:css('--ink'),padding:10,displayColors:split,
    callbacks:{title:i=>tf(i[0].parsed.x!==undefined?lab[i[0].dataIndex]:0),label:c=>`${c.dataset.label}: ${full(c.parsed.y)}`}}},
  scales:{x:{type:'category',ticks:{maxTicksLimit:6,color:css('--muted'),maxRotation:0,callback:(v,i)=>tf(lab[i])},grid:{display:false},border:{display:false}},
   y:{position:'right',grace:'8%',ticks:{color:css('--muted'),maxTicksLimit:6,callback:v=>fmt(v)},grid:{color:css('--line'),drawTicks:false},border:{display:false,dash:[3,4]}}}}});
}
function mark(){document.querySelectorAll('#sp button').forEach(b=>b.classList.toggle('on',(b.dataset.s==='1')===split));document.querySelectorAll('#rg button').forEach(b=>b.classList.toggle('on',b.dataset.r===range));
 document.querySelectorAll('#kf button').forEach(b=>b.classList.toggle('on',b.dataset.k===kind))}
function status(){
 const now=Date.now()/1000-skew, age=D.updated?Math.max(0,now-D.updated):null;
 document.getElementById('ago').textContent=age===null?'-':age<60?`${age.toFixed(0)}s ago`:`${Math.floor(age/60)}m ago`;
 const st=document.getElementById('st'),t=document.getElementById('stt');
 const live=D.official_live&&(D.live||[]).length>0;
 if(!LIVE){st.className='pill off';t.textContent='Snapshot'}
 else if(failing){st.className='pill warn';t.textContent='Connection lost, retrying'}
 else if(age!==null&&age>Math.max(15,D.every*6)&&live){st.className='pill warn';t.textContent='Delayed'}
 else if(live){st.className='pill';t.textContent=`Live, counting every ${D.every}s`}
 else{st.className='pill off';t.textContent='Official offline, showing last broadcast'}
 const nx=document.getElementById('nx');
 if(!LIVE){nx.style.display='none';return}
 const left=Math.max(0,EVERY-(Date.now()-lastFetch));document.getElementById('nxt').textContent=(left/1000).toFixed(1)+'s';
 document.getElementById('rp').setAttribute('stroke-dashoffset',44*(left/EVERY));
}
function merge(arr,tail){if(!arr)arr=[];const last=arr.length?arr[arr.length-1][0]:0;for(const r of tail||[])if(r[0]>last)arr.push(r);return arr}
let lastSeries=Date.now();
async function tick(){
 if(document.hidden){lastFetch=Date.now();return}
 lastFetch=Date.now();
 try{const r=await fetch('data');if(!r.ok)throw 0;const j=await r.json();
  const sr=merge(D.series_recent,j.tail), sa=D.series_all||[];
  if(j.tail&&j.tail.length&&(!sa.length||j.tail[j.tail.length-1][0]-sa[sa.length-1][0]>60))sa.push(j.tail[j.tail.length-1]);
  const cut=(sr.length?sr[sr.length-1][0]:0)-6*3600;while(sr.length&&sr[0][0]<cut)sr.shift();
  D={...j,series_recent:sr,series_all:sa};skew=Date.now()/1000-D.now;failing=false;render();
  if(Date.now()-lastSeries>300000){lastSeries=Date.now();fetch('series').then(x=>x.json()).then(x=>{D.series_all=x.series_all;D.series_recent=x.series_recent}).catch(()=>{})}
 }catch(e){failing=true}
}
skew=Date.now()/1000-(D.now||Date.now()/1000);
render();setInterval(status,100);
if(LIVE)setInterval(tick,EVERY);
</script></body></html>"""


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
