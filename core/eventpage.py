"""Event dashboard (Esports-Charts style) as one self-contained HTML page, plus a PNG chart for Telegram."""
import html
import io
import json
from datetime import datetime

from core import events


def _fmt_ts(ts):
    return datetime.fromtimestamp(ts, events.REPORT_TZ).strftime("%d %b %H:%M")


def build_html(key: str = None) -> str:
    ev = events.get(key)
    if not ev:
        return "<p>No event.</p>"
    st = events.stats(ev["key"])
    n = events.fmt_n
    if not st.get("ticks"):
        body = "<p class='muted'>No data yet. Numbers appear once a live stream is found.</p>"
        return _page(ev["name"], body, "[]")
    series = [{"t": _fmt_ts(ts), "total": tot, "official": o, "watch": w, "community": c}
              for ts, tot, o, w, c in st["series"]]
    # thin long series so the chart stays fast on phones
    step = max(1, len(series) // 1500)
    series = series[::step]
    live_total = sum(s["viewers"] for s in st["live_now"])
    esc = html.escape
    link = lambda vid, text: (f"<a href='{events.yt_link(vid)}' target='_blank' rel='noopener'>{esc(text)}</a>")
    tag = lambda k: f"<span class='tag {k[:4]}'>{k}</span>"
    clock = lambda ts: datetime.fromtimestamp(ts, events.REPORT_TZ).strftime("%d %b, %I:%M %p")
    kpis = [("Peak concurrent viewers", n(st["peak"]), events._when(st["peak_at"])),
            ("Average concurrent", n(st["avg_broadcast"]), "while the official broadcast was live"),
            ("Official peak", n(st["peak_official"]), f"average {n(st['avg_official'])}"),
            ("Watch parties peak", n(st["peak_watch"]), "all watch parties combined"),
            ("Watching now", n(live_total) if st["live_now"] else "Offline",
             f"{len(st['live_now'])} live streams" if st["live_now"] else "")]
    kpi_html = "".join(f"<div class='kpi'><div class='k'>{esc(a)}</div><div class='v'>{esc(b)}</div>"
                       f"<div class='s'>{esc(c)}</div></div>" for a, b, c in kpis)
    pk_total = st["peak"] or 1
    at_peak = "".join(f"<tr><td>{i}</td><td>{esc(s['channel'])}</td><td class='title'>{link(s['vid'], s['title'][:80])}</td>"
                      f"<td>{tag(s['kind'])}</td><td><b>{n(s['viewers'])}</b></td><td>{100 * s['viewers'] / pk_total:.1f}%</td></tr>"
                      for i, s in enumerate(st["at_peak"][:25], 1) if s["viewers"] > 0)
    peaks = "".join(f"<tr><td>{i}</td><td>{esc(p['channel'])}</td><td class='title'>{link(p['vid'], p['title'][:80])}</td>"
                    f"<td>{tag(p['kind'])}</td><td><b>{n(p['peak'])}</b></td><td>{clock(p['peak_at']) if p['peak_at'] else ''}</td></tr>"
                    for i, p in enumerate(st["stream_peaks"][:100], 1))
    live = "".join(f"<tr><td>{esc(s['channel'])}</td><td class='title'>{link(s['vid'], s['title'][:90])}</td>"
                   f"<td>{tag(s['kind'])}</td><td><b>{n(s['viewers'])}</b></td></tr>" for s in st["live_now"][:40]) or \
        "<tr><td colspan=4 class='muted'>Nothing live right now</td></tr>"
    days = "".join(f"<tr><td>{esc(d['day'])}</td><td><b>{n(d['peak'])}</b></td>"
                   f"<td>{datetime.fromtimestamp(d['peak_at'], events.REPORT_TZ).strftime('%I:%M %p') if d.get('peak_at') else ''}</td>"
                   f"<td>{n(d['avg_broadcast'])}</td></tr>" for d in st["days"])
    sp = st["peak_split"]
    body = f"""
<div class="kpis">{kpi_html}</div>
<div class="card"><h2>Concurrent viewers over time (IST)</h2><div class="chart"><canvas id="c"></canvas></div></div>
<div class="card"><h2>At the peak: {n(st['peak'])} concurrent at {esc(events._when(st['peak_at']))}</h2>
<p class="muted">Official {n(sp['official'])}, watch parties {n(sp['watch'])}, community {n(sp['community'])}</p>
<table><tr><th>#</th><th>Channel</th><th>Stream</th><th>Type</th><th>Concurrent</th><th>Share</th></tr>{at_peak}</table></div>
<div class="card"><h2>Watching now</h2><table><tr><th>Channel</th><th>Stream</th><th>Type</th><th>Concurrent</th></tr>{live}</table></div>
<div class="card"><h2>Peak concurrent viewers by stream</h2><table><tr><th>#</th><th>Channel</th><th>Stream</th><th>Type</th><th>Peak</th><th>When (IST)</th></tr>{peaks}</table></div>
<div class="card"><h2>By day</h2><table><tr><th>Day (IST)</th><th>Peak concurrent</th><th>At</th><th>Average concurrent (broadcast)</th></tr>{days}</table></div>
{"".join(f'<p><a href="{esc(u, quote=True)}" target="_blank" rel="noopener">{esc(l)}</a></p>' for l, u in (ev.get("links") or {}).items())}
<p class="muted">YouTube only. Concurrent viewers = people watching at the same moment, summed across every live stream
(official, watch parties, community), checked every {events.POLL_SEC}s. Updated {events._when(st['last']['ts'])}.</p>"""
    return _page(ev["name"], body, json.dumps(series))


def _page(title: str, body: str, data: str) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)} concurrent viewers</title>
<style>
:root{{--bg:#0f1115;--card:#171a21;--ink:#e8eaf0;--muted:#8b93a7;--line:#262b36;--acc:#5b8cff;--o:#f5a524;--w:#17c964;--c:#5b8cff}}
@media (prefers-color-scheme: light){{:root{{--bg:#f6f7fb;--card:#fff;--ink:#141821;--muted:#5d6577;--line:#e3e6ee}}}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;padding:16px;max-width:1100px;margin:auto}}
h1{{font-size:20px;margin:4px 0 14px}} h2{{font-size:14px;margin:0 0 10px;color:var(--muted);font-weight:600}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:12px}}
.kpi,.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px;min-width:0}}
.kpi .k{{color:var(--muted);font-size:12px}} .kpi .v{{font-size:24px;font-weight:700;margin:2px 0}} .kpi .s{{color:var(--muted);font-size:12px}}
.card{{margin-bottom:12px;overflow-x:auto}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}}
.chart{{position:relative;height:300px}} table{{width:100%;border-collapse:collapse}} th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}}
th{{color:var(--muted);font-weight:600;font-size:12px}} td.title{{white-space:normal;min-width:180px}} .muted{{color:var(--muted)}}
a{{color:var(--acc);text-decoration:none}} .tag{{font-size:11px;padding:2px 6px;border-radius:6px;background:var(--line)}} .tag.offi{{color:var(--o)}} .tag.watc{{color:var(--w)}} .tag.comm{{color:var(--c)}}
</style></head><body><h1>{html.escape(title)}: concurrent viewers</h1>{body}
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>
const d={data};
if(window.Chart&&d.length){{
 const css=getComputedStyle(document.documentElement);
 new Chart(document.getElementById('c'),{{type:'line',data:{{labels:d.map(x=>x.t),datasets:[
  {{label:'Total',data:d.map(x=>x.total),borderColor:css.getPropertyValue('--ink'),borderWidth:2,pointRadius:0,tension:.2}},
  {{label:'Official',data:d.map(x=>x.official),borderColor:'#f5a524',borderWidth:1.5,pointRadius:0,tension:.2}},
  {{label:'Watch parties',data:d.map(x=>x.watch),borderColor:'#17c964',borderWidth:1.5,pointRadius:0,tension:.2}},
  {{label:'Community',data:d.map(x=>x.community),borderColor:'#5b8cff',borderWidth:1.5,pointRadius:0,tension:.2}}]}},
  options:{{responsive:true,maintainAspectRatio:false,interaction:{{mode:'index',intersect:false}},
   scales:{{x:{{ticks:{{maxTicksLimit:8,color:css.getPropertyValue('--muted')}}}},y:{{beginAtZero:true,ticks:{{color:css.getPropertyValue('--muted')}}}}}},
   plugins:{{legend:{{labels:{{color:css.getPropertyValue('--ink')}}}}}}}}}});
}}
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
