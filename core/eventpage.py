"""Event dashboard (Esports-Charts style): one self-contained page that updates itself, plus a PNG chart for Telegram.

Only streams that are live right now are listed; ended streams only count toward the historical totals (peak, by day).
"""
import html
import io
import json
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
            series_all=_thin(series, 1500), series_recent=_thin(recent, 2500))
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
                .replace("__REFRESH__", str(REFRESH_SEC)))


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
.chart{position:relative;height:300px}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:8px;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.05em}
td.t{white-space:normal;min-width:200px}td.num{text-align:right;font-variant-numeric:tabular-nums;font-weight:700}th.num{text-align:right}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
.tag{font-size:11px;padding:2px 7px;border-radius:6px;font-weight:600}.tag.official{color:var(--off);background:rgba(245,165,36,.12)}
.tag.watch{color:var(--wp);background:rgba(34,197,94,.12)}.tag.community{color:var(--com);background:rgba(124,156,255,.12)}
.mini{height:4px;border-radius:3px;background:var(--acc);opacity:.75;margin-top:5px;transition:width .6s ease}
tr.fu td.num{animation:fu 1.2s}tr.fd td.num{animation:fd 1.2s}tr.new td{animation:nw 2s}
@keyframes fu{0%{color:var(--up)}100%{}}@keyframes fd{0%{color:var(--down)}100%{}}@keyframes nw{0%{background:rgba(124,156,255,.18)}100%{}}
.ch{font-weight:600}.muted{color:var(--muted)}.scroll{overflow-x:auto}.foot{font-size:12px;color:var(--muted);margin-top:14px}
.grid2{display:grid;grid-template-columns:1fr;gap:12px;margin-top:12px}
.mt{display:none;margin-left:6px}
@media(max-width:600px){.big .v{font-size:42px}.hide-m{display:none}.mt{display:inline}th,td{padding:8px 5px}td.t{min-width:0}
 .bar .in{gap:6px}.title{width:100%}.pill{font-size:11px;padding:3px 8px}input.q{width:100%}}
</style></head><body>
<div class="bar"><div class="in">
 <div class="title">__TITLE__ <span class="muted" style="font-weight:600">concurrent viewers</span></div>
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
let D=__DATA__, prev={}, prevTotal=null, chart=null, range=localGet('range')||'1h', kind=localGet('kind')||'all', q='', skew=0, lastFetch=Date.now(), failing=false;
function localGet(k){try{return localStorage.getItem('ev_'+k)}catch(e){return null}}
function localSet(k,v){try{localStorage.setItem('ev_'+k,v)}catch(e){}}
const fmt=n=>{n=+n||0;return n>=1e6?(n/1e6).toFixed(2)+'M':n>=1e4?(n/1e3).toFixed(1)+'K':Math.round(n).toLocaleString('en-IN')};
const full=n=>Math.round(+n||0).toLocaleString('en-IN');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const K={official:'official','watch party':'watch',community:'community'};
const css=v=>getComputedStyle(document.documentElement).getPropertyValue(v).trim();
function tween(el,to){const from=+el.dataset.v||0;el.dataset.v=to;if(from===to){el.textContent=full(to);return}
 const t0=performance.now();const step=t=>{const k=Math.min(1,(t-t0)/600);el.textContent=full(from+(to-from)*(1-Math.pow(1-k,3)));if(k<1)requestAnimationFrame(step)};requestAnimationFrame(step)}
function render(){
 const app=document.getElementById('app');
 if(!D.ticks){app.innerHTML='<div class="card" style="margin-top:16px">No data yet. Numbers appear once a live stream is found.</div>';return}
 const live=D.live||[], tot=live.reduce((a,s)=>a+s.viewers,0);
 const by={official:0,'watch party':0,community:0};live.forEach(s=>by[s.kind]=(by[s.kind]||0)+s.viewers);
 if(!document.getElementById('big')){
  app.innerHTML=`
  <div class="hero">
   <div class="card big"><div class="k">Watching now, all live streams</div>
    <div class="v" id="big" data-v="0">0</div><div><span id="dl" class="delta flat"></span> <span class="muted" id="nlive"></span></div>
    <div class="split" id="split"></div><div class="legend" id="leg"></div></div>
   <div class="kpis">
    <div class="kpi"><div class="k">Peak concurrent</div><div class="v" id="kp"></div><div class="s" id="kpw"></div></div>
    <div class="kpi"><div class="k">Average concurrent</div><div class="v" id="ka"></div><div class="s">while the official broadcast was live</div></div>
    <div class="kpi"><div class="k">Official peak</div><div class="v" id="ko"></div><div class="s">official broadcasts combined</div></div>
    <div class="kpi"><div class="k">Watch parties peak</div><div class="v" id="kw"></div><div class="s">all watch parties combined</div></div>
   </div></div>
  <div class="card"><div class="head"><h2>Concurrent viewers over time (IST)</h2>
   <div class="seg" id="rg">${['15m','1h','6h','all'].map(r=>`<button data-r="${r}">${r==='all'?'All':r}</button>`).join('')}</div></div>
   <div class="chart"><canvas id="c"></canvas></div></div>
  <div class="grid2">
  <div class="card"><div class="head"><h2 id="lh">Live streams</h2>
   <div class="seg" id="kf">${[['all','All'],['official','Official'],['watch party','Watch parties'],['community','Community']].map(([k,l])=>`<button data-k="${k}">${l}</button>`).join('')}</div>
   <input class="q" id="q" placeholder="Search channel or title"></div>
   <div class="scroll"><table><thead><tr><th>#</th><th>Channel / stream</th><th class="hide-m">Type</th><th class="num">Concurrent</th><th class="num hide-m">Share</th></tr></thead><tbody id="rows"></tbody></table></div></div>
  <div class="card"><div class="head"><h2>By day</h2></div><div class="scroll"><table><thead><tr><th>Day (IST)</th><th class="num">Peak</th><th>At</th><th class="num">Average</th></tr></thead><tbody id="days"></tbody></table></div></div>
  </div>
  <div class="foot" id="foot"></div>`;
  document.querySelectorAll('#rg button').forEach(b=>b.onclick=()=>{range=b.dataset.r;localSet('range',range);drawChart();mark()});
  document.querySelectorAll('#kf button').forEach(b=>b.onclick=()=>{kind=b.dataset.k;localSet('kind',kind);rows();mark()});
  document.getElementById('q').oninput=e=>{q=e.target.value.toLowerCase();rows()};
 }
 tween(document.getElementById('big'),tot);
 const dl=document.getElementById('dl');
 if(prevTotal!==null&&prevTotal!==tot){const d=tot-prevTotal;dl.className='delta '+(d>0?'up':'down');dl.textContent=(d>0?'▲ +':'▼ ')+full(d)+' since last reading'}
 else if(prevTotal===null)dl.textContent='';
 prevTotal=tot;
 document.getElementById('nlive').textContent=live.length?`across ${live.length} live streams`:'Nothing live right now';
 const cols={official:css('--off'),'watch party':css('--wp'),community:css('--com')};
 document.getElementById('split').innerHTML=Object.keys(by).map(k=>`<div style="width:${tot?100*by[k]/tot:0}%;background:${cols[k]}"></div>`).join('');
 document.getElementById('leg').innerHTML=Object.keys(by).map(k=>`<span><span class="sw" style="background:${cols[k]}"></span>${k==='watch party'?'Watch parties':k[0].toUpperCase()+k.slice(1)} <b>${fmt(by[k])}</b>${tot?` (${(100*by[k]/tot).toFixed(0)}%)`:''}</span>`).join('');
 document.getElementById('kp').textContent=fmt(D.peak);document.getElementById('kpw').textContent=D.peak_when;
 document.getElementById('ka').textContent=fmt(D.avg);document.getElementById('ko').textContent=fmt(D.peak_official);
 document.getElementById('kw').textContent=fmt(D.peak_watch);
 document.getElementById('days').innerHTML=(D.days||[]).map(d=>`<tr><td>${esc(d.day)}</td><td class="num">${fmt(d.peak)}</td><td>${esc(d.at)}</td><td class="num">${fmt(d.avg)}</td></tr>`).join('');
 const links=Object.entries(D.links||{}).map(([l,u])=>`<a href="${esc(u)}" target="_blank" rel="noopener">${esc(l)}</a>`).join(' &middot; ');
 document.getElementById('foot').innerHTML=`YouTube only. Concurrent viewers = people watching at the same moment, summed across every live stream. Ended streams are not listed. Counted from: ${esc(D.method)}.${links?'<br>'+links:''}`;
 rows();drawChart();mark();
}
function rows(){
 const live=(D.live||[]).filter(s=>(kind==='all'||s.kind===kind)&&(!q||(s.channel+' '+s.title).toLowerCase().includes(q)));
 const tot=(D.live||[]).reduce((a,s)=>a+s.viewers,0)||1, top=Math.max(1,...live.map(s=>s.viewers));
 document.getElementById('lh').textContent=`Live streams (${live.length})`;
 document.getElementById('rows').innerHTML=live.map((s,i)=>{const p=prev[s.vid];const cl=p===undefined&&Object.keys(prev).length?'new':p<s.viewers?'fu':p>s.viewers?'fd':'';
  return `<tr class="${cl}"><td class="muted">${i+1}</td><td class="t"><div class="ch">${esc(s.channel)}<span class="tag mt ${K[s.kind]}">${esc(s.kind)}</span></div><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title.slice(0,100))}</a><div class="mini" style="width:${100*s.viewers/top}%"></div></td>
  <td class="hide-m"><span class="tag ${K[s.kind]}">${esc(s.kind)}</span></td><td class="num">${full(s.viewers)}</td><td class="num muted hide-m">${(100*s.viewers/tot).toFixed(1)}%</td></tr>`}).join('')||'<tr><td colspan=5 class="muted">Nothing live right now</td></tr>';
 prev={};(D.live||[]).forEach(s=>prev[s.vid]=s.viewers);
}
function drawChart(){
 if(!window.Chart||!document.getElementById('c'))return;
 const src=range==='all'?(D.series_all||[]):(D.series_recent||[]);const span={'15m':900,'1h':3600,'6h':21600}[range];
 const last=src.length?src[src.length-1][0]:0;const s=span?src.filter(r=>r[0]>=last-span):src;
 const lab=s.map(r=>new Date(r[0]*1000).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit',second:range==='15m'?'2-digit':undefined,day:range==='all'?'2-digit':undefined,month:range==='all'?'short':undefined}));
 const ds=[['Total',1,css('--ink'),2.2],['Official',2,css('--off'),1.4],['Watch parties',3,css('--wp'),1.4],['Community',4,css('--com'),1.4]]
  .map(([l,i,c,w])=>({label:l,data:s.map(r=>r[i]),borderColor:c,backgroundColor:i===1?c+'14':'transparent',fill:i===1,borderWidth:w,pointRadius:0,tension:.25}));
 if(chart){chart.data.labels=lab;chart.data.datasets.forEach((d,i)=>{d.data=ds[i].data});chart.update('none');return}
 chart=new Chart(document.getElementById('c'),{type:'line',data:{labels:lab,datasets:ds},options:{responsive:true,maintainAspectRatio:false,animation:false,
  interaction:{mode:'index',intersect:false},plugins:{legend:{labels:{color:css('--ink'),boxWidth:10}},tooltip:{callbacks:{label:c=>`${c.dataset.label}: ${full(c.parsed.y)}`}}},
  scales:{x:{ticks:{maxTicksLimit:7,color:css('--muted')},grid:{display:false}},y:{beginAtZero:true,ticks:{color:css('--muted'),callback:v=>fmt(v)},grid:{color:css('--line')}}}}});
}
function mark(){document.querySelectorAll('#rg button').forEach(b=>b.classList.toggle('on',b.dataset.r===range));
 document.querySelectorAll('#kf button').forEach(b=>b.classList.toggle('on',b.dataset.k===kind))}
function status(){
 const now=Date.now()/1000-skew, age=D.updated?Math.max(0,now-D.updated):null;
 document.getElementById('ago').textContent=age===null?'-':age<60?`${age.toFixed(0)}s ago`:`${Math.floor(age/60)}m ago`;
 const st=document.getElementById('st'),t=document.getElementById('stt');
 const live=(D.live||[]).length>0;
 if(!LIVE){st.className='pill off';t.textContent='Snapshot'}
 else if(failing){st.className='pill warn';t.textContent='Connection lost, retrying'}
 else if(age!==null&&age>Math.max(15,D.every*6)&&live){st.className='pill warn';t.textContent='Delayed'}
 else if(live){st.className='pill';t.textContent=`Live, counting every ${D.every}s`}
 else{st.className='pill off';t.textContent='Nothing live'}
 const nx=document.getElementById('nx');
 if(!LIVE){nx.style.display='none';return}
 const left=Math.max(0,EVERY-(Date.now()-lastFetch));document.getElementById('nxt').textContent=(left/1000).toFixed(1)+'s';
 document.getElementById('rp').setAttribute('stroke-dashoffset',44*(left/EVERY));
}
async function tick(){
 if(document.hidden){lastFetch=Date.now();return}
 lastFetch=Date.now();
 try{const r=await fetch('data',{cache:'no-store'});if(!r.ok)throw 0;D=await r.json();skew=Date.now()/1000-D.now;failing=false;render()}
 catch(e){failing=true}
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
