"""Dashboard (Esports-Charts style): one self-contained HTML page, plus a PNG chart for Telegram."""
import html
import io
import json
from datetime import datetime

import tracker as T


def _t(ts):
    return datetime.fromtimestamp(ts, T.TZ).strftime("%d %b %H:%M:%S")


def build_html(refresh: int = 0) -> str:
    cfg = T.config()
    st = T.stats()
    n = T.fmt_n
    links = "".join(f'<a class="pill" href="{html.escape(u, quote=True)}" target="_blank" rel="noopener">{html.escape(k)}</a>'
                    for k, u in cfg.get("links", {}).items())
    if not st.get("ticks"):
        return _page(cfg["name"], f"<p class='muted'>No data yet. Numbers start when a stream goes live.</p>{links}",
                     "[]", refresh)
    series = [{"t": _t(ts), "total": a, "official": o, "watch": w, "community": c} for ts, a, o, w, c in st["series"]]
    step = max(1, len(series) // 2000)
    series = series[::step]
    live_total = sum(s["viewers"] for s in st["live"])
    kpis = [("Peak viewers", n(st["peak"]), T.when(st["peak_at"])), ("Average viewers", n(st["avg"]), "over airtime"),
            ("Hours watched", n(st["hw"]), "all streams"), ("Airtime", f"{st['air_h']:.1f} h", f"{len(st['channels'])} channels"),
            ("Live now", n(live_total) if st["live"] else "Offline", f"{len(st['live'])} streams" if st["live"] else "")]
    kpi = "".join(f"<div class='kpi'><div class='k'>{html.escape(a)}</div><div class='v'>{html.escape(b)}</div>"
                  f"<div class='s'>{html.escape(c)}</div></div>" for a, b, c in kpis)
    sp, kh = st["peak_split"], st["kinds_hw"]
    tot = sum(kh.values()) or 1
    split = "".join(f"<tr><td>{k}</td><td>{n(sp[k])}</td><td>{n(kh[k])} ({100 * kh[k] / tot:.0f}%)</td></tr>"
                    for k in ("official", "watch party", "community"))
    days = "".join(f"<tr><td>{html.escape(d['day'])}</td><td>{n(d['peak'])}</td><td>{n(d['avg'])}</td><td>{n(d['hw'])}</td>"
                   f"<td>{d['air'] / 3600:.1f} h</td></tr>" for d in st["days"])
    chans = "".join(f"<tr><td>{i}</td><td><a href='{html.escape(c['url'], quote=True)}' target='_blank' rel='noopener'>"
                    f"{html.escape(c['channel'])}</a></td><td><span class='tag {c['kind'][:4]}'>{c['kind']}</span></td>"
                    f"<td>{n(c['peak'])}</td><td>{n(c['avg'])}</td><td>{n(c['hw'])}</td></tr>"
                    for i, c in enumerate(st["channels"][:150], 1))
    live = "".join(f"<tr><td>{html.escape(s['channel'])}</td><td class='title'><a href='{T.yt(s['vid'])}' target='_blank' "
                   f"rel='noopener'>{html.escape(s['title'][:90])}</a></td><td>{n(s['viewers'])}</td></tr>"
                   for s in st["live"][:40]) or "<tr><td colspan=3 class='muted'>Nothing live right now</td></tr>"
    body = f"""<div class="kpis">{kpi}</div>
<div class="card"><h2>Viewers over time (IST)</h2><div class="chart"><canvas id="c"></canvas></div></div>
<div class="grid"><div class="card"><h2>Live now</h2><table><tr><th>Channel</th><th>Stream</th><th>Viewers</th></tr>{live}</table></div>
<div class="card"><h2>By stream type</h2><table><tr><th>Type</th><th>At peak</th><th>Hours watched</th></tr>{split}</table></div></div>
<div class="card"><h2>By day</h2><table><tr><th>Day (IST)</th><th>Peak</th><th>Average</th><th>Hours watched</th><th>Airtime</th></tr>{days}</table></div>
<div class="card"><h2>Channels</h2><table><tr><th>#</th><th>Channel</th><th>Type</th><th>Peak</th><th>Average</th><th>Hours watched</th></tr>{chans}</table></div>
<p>{links}</p><p class="muted">YouTube only. Every live stream counted every {T.FAST_SEC}s; new streams found every
{T.DISCOVER_SEC}s. Average viewers = hours watched / airtime. Updated {T.when(st['last_ts'])}.</p>"""
    return _page(cfg["name"], body, json.dumps(series), refresh)


def _page(title, body, data, refresh):
    meta = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">{meta}
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)} viewership</title>
<style>
:root{{--bg:#0f1115;--card:#171a21;--ink:#e8eaf0;--muted:#8b93a7;--line:#262b36;--acc:#7aa2ff}}
@media (prefers-color-scheme: light){{:root{{--bg:#f6f7fb;--card:#fff;--ink:#141821;--muted:#5d6577;--line:#e3e6ee;--acc:#2f5bd3}}}}
*{{box-sizing:border-box}} body{{margin:0 auto;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;padding:16px;max-width:1100px}}
h1{{font-size:20px;margin:4px 0 14px}} h2{{font-size:14px;margin:0 0 10px;color:var(--muted);font-weight:600}} a{{color:var(--acc);text-decoration:none}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:12px}}
.kpi,.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px;min-width:0}}
.kpi .k,.kpi .s{{color:var(--muted);font-size:12px}} .kpi .v{{font-size:24px;font-weight:700;margin:2px 0}}
.card{{margin-bottom:12px;overflow-x:auto}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}}
.chart{{position:relative;height:320px}} table{{width:100%;border-collapse:collapse}}
th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}} th{{color:var(--muted);font-size:12px}}
td.title{{white-space:normal;min-width:180px}} .muted{{color:var(--muted)}} .pill{{display:inline-block;margin:0 8px 8px 0}}
.tag{{font-size:11px;padding:2px 6px;border-radius:6px;background:var(--line)}} .tag.offi{{color:#f5a524}} .tag.watc{{color:#17c964}} .tag.comm{{color:#7aa2ff}}
</style></head><body><h1>{html.escape(title)} viewership</h1>{body}
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>
const d={data};
if(window.Chart&&d.length){{const css=getComputedStyle(document.documentElement),ink=css.getPropertyValue('--ink'),mut=css.getPropertyValue('--muted');
 new Chart(document.getElementById('c'),{{type:'line',data:{{labels:d.map(x=>x.t),datasets:[
  {{label:'Total',data:d.map(x=>x.total),borderColor:ink,borderWidth:2,pointRadius:0,tension:.15}},
  {{label:'Official',data:d.map(x=>x.official),borderColor:'#f5a524',borderWidth:1.4,pointRadius:0,tension:.15}},
  {{label:'Watch parties',data:d.map(x=>x.watch),borderColor:'#17c964',borderWidth:1.4,pointRadius:0,tension:.15}},
  {{label:'Community',data:d.map(x=>x.community),borderColor:'#7aa2ff',borderWidth:1.4,pointRadius:0,tension:.15}}]}},
  options:{{responsive:true,maintainAspectRatio:false,animation:false,interaction:{{mode:'index',intersect:false}},
   scales:{{x:{{ticks:{{maxTicksLimit:8,color:mut}}}},y:{{beginAtZero:true,ticks:{{color:mut}}}}}},plugins:{{legend:{{labels:{{color:ink}}}}}}}}}});}}
</script></body></html>"""


def chart_png():
    cfg = T.config()
    st = T.stats()
    if not st.get("series"):
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    xs = [datetime.fromtimestamp(s[0], T.TZ) for s in st["series"]]
    fig, ax = plt.subplots(figsize=(10, 4.6), dpi=130)
    for i, label, color, lw in ((1, "Total", "#141821", 2.2), (2, "Official", "#f5a524", 1.3),
                                (3, "Watch parties", "#17c964", 1.3), (4, "Community", "#5b8cff", 1.3)):
        ax.plot(xs, [s[i] for s in st["series"]], label=label, color=color, linewidth=lw)
    ax.annotate(f"Peak {T.fmt_n(st['peak'])}", (datetime.fromtimestamp(st["peak_at"], T.TZ), st["peak"]),
                textcoords="offset points", xytext=(0, 8), ha="center", fontsize=9)
    ax.set_title(f"{cfg['name']}: YouTube viewers (IST)", fontsize=12, loc="left")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M", tz=T.TZ))
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: T.fmt_n(v)))
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
