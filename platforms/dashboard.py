"""Owner dashboard: who's active, what each user has used, and where the money goes.

Runs inside the agent at http://localhost:8090 (only reachable from this computer by default).
Settings: DASHBOARD_PORT, DASHBOARD_HOST (127.0.0.1), DASHBOARD_TOKEN (required if you expose it).
"""
import os
import time
from datetime import datetime, timezone

from flask import Flask, abort, jsonify, request

from core import alerts, llm, models, sources, store

app = Flask(__name__)
PORT = int(os.getenv("DASHBOARD_PORT", "8090"))
HOST = os.getenv("DASHBOARD_HOST", "127.0.0.1")
TOKEN = os.getenv("DASHBOARD_TOKEN", "")
DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", "20"))


def _authorised() -> bool:
    if not TOKEN:
        return request.remote_addr in ("127.0.0.1", "::1")
    return request.args.get("token") == TOKEN or request.cookies.get("token") == TOKEN


def _provider(model_id: str) -> str:
    for m in models.registry().values():
        if model_id == m["id"]:
            return {"anthropic": "Claude", "openai": "ChatGPT", "gemini": "Gemini"}[m["provider"]]
    if model_id.startswith("claude"):
        return "Claude"
    if model_id.startswith("gpt") or model_id.startswith("o"):
        return "ChatGPT"
    if model_id.startswith("gemini"):
        return "Gemini"
    return model_id or "other"


def _label(model_id: str) -> str:
    k = models.key_for_id(model_id)
    return models.registry()[k]["label"] if k else model_id


def _age_seconds(ts: str):
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(ts.replace("Z", "+00:00"))).total_seconds()
    except Exception:
        return None


@app.route("/api/stats")
def stats():
    if not _authorised():
        abort(403)
    users = store.dashboard_users()
    for u in users:
        u["seconds_ago"] = _age_seconds(u["last_seen"])
        u["display"] = "You (owner)" if u["uid"] == "owner" else (
            f"@{u['username']}" if u["username"] else (u["name"] or u["uid"]))
        u["limit"] = None if u["uid"] == "owner" else DAILY_LIMIT
    active_now = [u for u in users if u["seconds_ago"] is not None and u["seconds_ago"] < 15 * 60]
    active_today = [u for u in users if u["seconds_ago"] is not None and u["seconds_ago"] < 24 * 3600]

    series = {}
    for r in store.spend_series(14):
        p = _provider(r["model"])
        series.setdefault(r["day"], {}).setdefault(p, 0)
        series[r["day"]][p] += r["cost"]
    by_model = [{"model": _label(r["k"]), "provider": _provider(r["k"]), "cost": r["cost"], "calls": r["calls"],
                 "tokens_in": r["tin"], "tokens_out": r["tout"]} for r in store.spend_by("model", 7)]
    by_feature = store.spend_by("feature", 7)
    recent = [{**r, "model": _label(r["model"]), "seconds_ago": _age_seconds(r["created_at"])}
              for r in store.recent_calls(30)]
    tick = store.kv_get("scheduler_tick")
    health = []
    for kind, h in sources.HEALTH.items():
        health.append({"source": sources.SOURCE_NAMES.get(kind, kind), "ok": not h.get("fails"),
                       "fails": h.get("fails", 0), "error": h.get("err", "") if h.get("fails") else "",
                       "last_ok_ago": time.time() - h["ok"] if h.get("ok") else None})
    week = store.spend_breakdown(7)["total"]
    return jsonify({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kpis": {
            "spend_today": store.spend_today(), "spend_today_owner": store.spend_today(owner=True),
            "spend_today_public": store.spend_today(owner=False), "public_budget": llm.PUBLIC_DAILY_BUDGET,
            "spend_week": week, "projected_month": week / 7 * 30,
            "users_total": len(users), "active_now": len(active_now), "active_today": len(active_today),
            "requests_today": sum(u["requests_today"] for u in users),
            "serper_today": store.counter("serper"), "serper_week": store.counter("serper", 7),
            "credits": store.credit_estimate(),
            "uptime_s": time.time() - alerts.STARTED,
            "scheduler_ago": time.time() - tick if tick else None,
            "models_available": [m["label"] for m in models.available().values()],
        },
        "users": users,
        "series": series,
        "by_model": by_model,
        "by_feature": by_feature,
        "recent": recent,
        "health": health,
    })


@app.route("/api/activity")
def activity():
    if not _authorised():
        abort(403)
    uid = request.args.get("uid") or None
    kind = request.args.get("kind") or None
    rows = store.get_activity(uid=uid, kind=kind, limit=200)
    names = {}
    for u in store.all_users():
        names[u["uid"]] = "You" if u["uid"] == "owner" else (f"@{u['username']}" if u.get("username") else (u.get("name") or u["uid"]))
    for r in rows:
        r["seconds_ago"] = _age_seconds(r["ts"])
        r["who"] = names.get(r["uid"], r["uid"])
    return jsonify({"rows": rows, "top_searches": store.top_searches(7)})


@app.route("/")
def index():
    if not _authorised():
        abort(403)
    resp = app.response_class(PAGE, mimetype="text/html")
    if TOKEN and request.args.get("token") == TOKEN:
        resp.set_cookie("token", TOKEN, httponly=True, samesite="Strict")
    return resp


def run_dashboard():
    if HOST not in ("127.0.0.1", "localhost") and not TOKEN:
        print("Dashboard: refusing to listen beyond this computer without DASHBOARD_TOKEN; using 127.0.0.1")
        host = "127.0.0.1"
    else:
        host = HOST
    print(f"Dashboard: http://localhost:{PORT}")
    app.run(host=host, port=PORT, debug=False, use_reloader=False)


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root{--bg:#f6f5f2;--card:#fff;--ink:#17171a;--muted:#6b6b73;--line:#e6e4df;--accent:#2f6fed;
--claude:#d97757;--chatgpt:#10a37f;--gemini:#4b7bec;--ok:#1f9d55;--warn:#d97706;--bad:#dc2626}
@media (prefers-color-scheme:dark){:root{--bg:#111114;--card:#1a1a1f;--ink:#ececf0;--muted:#9b9ba6;--line:#2a2a31;--accent:#6b9bff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 Inter,system-ui,sans-serif}
header{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap;padding:24px 24px 8px;max-width:1280px;margin:auto}
h1{font-size:20px;margin:0;font-weight:700;letter-spacing:-.01em}.sub{color:var(--muted);font-size:13px}
main{max-width:1280px;margin:auto;padding:8px 24px 40px;display:grid;gap:16px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;min-width:0}
main>*,.grid2>*{min-width:0}
@media(max-width:600px){header{padding:16px 16px 4px}main{padding:8px 16px 32px}.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.kpi .v{font-size:20px}}
.kpi .v{font-size:24px;font-weight:700;letter-spacing:-.02em;font-variant-numeric:tabular-nums}.kpi .l{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.kpi .s{color:var(--muted);font-size:12px;margin-top:2px}
.grid2{display:grid;grid-template-columns:2fr 1fr;gap:16px}@media(max-width:900px){.grid2{grid-template-columns:1fr}}
h2{font-size:14px;margin:0 0 12px;font-weight:600}
table{width:100%;border-collapse:collapse;font-size:13px}th{text-align:left;color:var(--muted);font-weight:500;font-size:12px;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:8px;border-bottom:1px solid var(--line);vertical-align:top;font-variant-numeric:tabular-nums}tr:last-child td{border-bottom:none}
.scroll{overflow-x:auto}.num{text-align:right}.mono{font-family:"JetBrains Mono",monospace;font-size:12px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:middle}
.live{background:var(--ok);box-shadow:0 0 0 3px color-mix(in srgb,var(--ok) 25%,transparent)}.idle{background:var(--line)}
.bar{height:6px;background:var(--line);border-radius:3px;overflow:hidden;min-width:60px}.bar>i{display:block;height:100%;background:var(--accent)}
.tag{display:inline-block;padding:1px 7px;border-radius:999px;font-size:11px;border:1px solid var(--line);color:var(--muted);margin:1px}
.bad{color:var(--bad)}.ok{color:var(--ok)}.warn{color:var(--warn)}canvas{max-height:260px}
.empty{color:var(--muted);padding:12px 0}
.filters{display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap}select{background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:6px 8px;font:inherit}
.kind{font-size:11px;padding:1px 7px;border-radius:999px;background:color-mix(in srgb,var(--accent) 12%,transparent);color:var(--accent);white-space:nowrap}
</style></head><body>
<header><div><h1>Agent dashboard</h1><div class="sub" id="sub">Loading...</div></div><div class="sub">Refreshes every 30 s</div></header>
<main>
<section class="kpis" id="kpis"></section>
<section class="grid2">
  <div class="card"><h2>Spend per day (last 14 days)</h2><canvas id="daily"></canvas></div>
  <div class="card"><h2>Spend by model (7 days)</h2><canvas id="models"></canvas></div>
</section>
<section class="card"><h2>Sessions and usage by user</h2><div class="scroll"><table id="users"></table></div></section>
<section class="grid2">
  <div class="card"><h2>What people are asking and searching</h2>
    <div class="filters"><select id="fuser"><option value="">Everyone</option></select>
    <select id="fkind"><option value="">Everything</option><option value="message">Messages</option>
    <option value="tool:web_search">Web searches</option><option value="tool:scan_sources">Buzz scans</option>
    <option value="tool:read_url">Links opened</option><option value="download">Downloads</option><option value="tool:">All tool use</option></select></div>
    <div class="scroll" style="max-height:520px;overflow-y:auto"><table id="activity"></table></div></div>
  <div class="card"><h2>Top searches (7 days)</h2><table id="topsearch"></table></div>
</section>
<section class="grid2">
  <div class="card"><h2>Recent AI calls</h2><div class="scroll"><table id="recent"></table></div></div>
  <div class="card"><h2>Where the money goes (7 days)</h2><table id="features"></table>
    <h2 style="margin-top:20px">Health</h2><table id="health"></table></div>
</section>
</main>
<script>
const $=id=>document.getElementById(id), usd=v=>v==null?'-':(v>0&&v<0.0001)?'<$0.0001':'$'+(v<0.01&&v>0?v.toFixed(4):v.toFixed(2));
const ago=s=>s==null?'never':s<60?Math.round(s)+'s ago':s<3600?Math.round(s/60)+'m ago':s<86400?Math.round(s/3600)+'h ago':Math.round(s/86400)+'d ago';
const esc=t=>String(t??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const colors=()=>({Claude:css('--claude'),ChatGPT:css('--chatgpt'),Gemini:css('--gemini'),other:css('--muted')});
let daily,modelsChart;
function kpi(l,v,s){return `<div class="card kpi"><div class="l">${l}</div><div class="v">${v}</div>${s?`<div class="s">${s}</div>`:''}</div>`}
var load=async function(){
  const r=await fetch('api/stats'+location.search); if(!r.ok){$('sub').textContent='Not authorised';return}
  const d=await r.json(), k=d.kpis;
  $('sub').textContent=`Up ${Math.floor(k.uptime_s/3600)}h ${Math.floor(k.uptime_s%3600/60)}m · scheduler ${ago(k.scheduler_ago)} · models: ${k.models_available.join(', ')}`;
  const cr=k.credits?kpi('Anthropic credits left',usd(k.credits.left),`estimate from ${usd(k.credits.entered)} entered`):kpi('Anthropic credits left','?','send /credits 6.54 to track');
  $('kpis').innerHTML=kpi('Active now',k.active_now,`${k.active_today} today · ${k.users_total} users`)+
    kpi('Spend today',usd(k.spend_today),`you ${usd(k.spend_today_owner)} · others ${usd(k.spend_today_public)} / ${usd(k.public_budget)}`)+
    kpi('Last 7 days',usd(k.spend_week),`~${usd(k.projected_month)} / month`)+cr+
    kpi('Requests today',k.requests_today,'counted against daily limits')+
    kpi('Serper searches',k.serper_today,`${k.serper_week} this week`);
  const maxSpend=Math.max(...d.users.map(u=>u.spend_week),0.0001);
  $('users').innerHTML='<tr><th>User</th><th>Last active</th><th>Platform / timezone</th><th>Last model</th><th class="num">Requests today</th><th class="num">Spend today</th><th>7 days</th><th class="num">All time</th><th class="num">Messages</th><th>Extras</th></tr>'+
   (d.users.map(u=>{const live=u.seconds_ago!=null&&u.seconds_ago<900;
     return `<tr><td><span class="dot ${live?'live':'idle'}"></span><b>${esc(u.display)}</b><div class="sub mono">${esc(u.uid)}</div></td>
     <td>${ago(u.seconds_ago)}</td><td>${esc(u.platform)}<div class="sub">${esc(u.timezone||'-')}</div></td><td>${esc(u.last_model||'-')}</td>
     <td class="num">${u.requests_today}${u.limit?` / ${u.limit}`:''}</td><td class="num">${usd(u.spend_today)}</td>
     <td><div class="bar"><i style="width:${Math.round(100*u.spend_week/maxSpend)}%"></i></div><span class="sub">${usd(u.spend_week)}</span></td>
     <td class="num">${usd(u.spend_total)}</td><td class="num">${u.messages}</td>
     <td>${u.blocked?'<span class="tag bad">blocked</span>':''}${u.news_on?'<span class="tag">news</span>':''}${u.alerts?`<span class="tag">${u.alerts} alerts</span>`:''}${u.state!=='active'?`<span class="tag">${esc(u.state)}</span>`:''}${(u.interests||[]).slice(0,3).map(i=>`<span class="tag">${esc(i)}</span>`).join('')}</td></tr>`}).join('')||'<tr><td class="empty" colspan="10">No users yet</td></tr>');
  $('recent').innerHTML='<tr><th>When</th><th>User</th><th>Feature</th><th>Model</th><th class="num">Tokens in/out</th><th class="num">Cost</th></tr>'+
   (d.recent.map(r=>`<tr><td>${ago(r.seconds_ago)}</td><td class="mono">${esc(r.uid)}</td><td>${esc(r.feature)}</td><td>${esc(r.model)}</td><td class="num">${r.input_tokens}/${r.output_tokens}</td><td class="num">${usd(r.cost)}</td></tr>`).join('')||'<tr><td class="empty" colspan="6">No calls yet</td></tr>');
  $('features').innerHTML='<tr><th>Feature</th><th class="num">Calls</th><th class="num">Cost</th></tr>'+
   (d.by_feature.map(f=>`<tr><td>${esc(f.k)}</td><td class="num">${f.calls}</td><td class="num">${usd(f.cost)}</td></tr>`).join('')||'<tr><td class="empty" colspan="3">Nothing yet</td></tr>');
  $('health').innerHTML='<tr><th>Source</th><th>Status</th></tr>'+
   (d.health.map(h=>`<tr><td>${esc(h.source)}</td><td class="${h.ok?'ok':'bad'}">${h.ok?'ok, '+ago(h.last_ok_ago):'failing x'+h.fails+' <span class="sub">'+esc(h.error)+'</span>'}</td></tr>`).join('')||'<tr><td class="empty" colspan="2">No source checks yet</td></tr>');
  try{ if(!window.Chart) throw new Error('Chart.js not loaded');
  const days=Object.keys(d.series).sort(), provs=['Claude','ChatGPT','Gemini','other'], C=colors();
  const ds=provs.filter(p=>days.some(x=>d.series[x][p])).map(p=>({label:p,data:days.map(x=>d.series[x][p]||0),backgroundColor:C[p]||C.other,borderRadius:4}));
  const opts={responsive:true,plugins:{legend:{labels:{color:css('--muted')}}},scales:{x:{stacked:true,ticks:{color:css('--muted')},grid:{display:false}},y:{stacked:true,ticks:{color:css('--muted'),callback:v=>'$'+v},grid:{color:css('--line')}}}};
  daily?(daily.data.labels=days,daily.data.datasets=ds,daily.update()):daily=new Chart($('daily'),{type:'bar',data:{labels:days,datasets:ds},options:opts});
  const ml=d.by_model.map(m=>m.model), mv=d.by_model.map(m=>m.cost), mc=d.by_model.map(m=>C[m.provider]||C.other);
  modelsChart?(modelsChart.data.labels=ml,modelsChart.data.datasets[0].data=mv,modelsChart.data.datasets[0].backgroundColor=mc,modelsChart.update()):
    modelsChart=new Chart($('models'),{type:'bar',data:{labels:ml,datasets:[{data:mv,backgroundColor:mc,borderRadius:4}]},options:{indexAxis:'y',plugins:{legend:{display:false}},scales:{x:{ticks:{color:css('--muted'),callback:v=>'$'+v},grid:{color:css('--line')}},y:{ticks:{color:css('--muted')},grid:{display:false}}}}});
  }catch(e){for(const id of ['daily','models']){const c=$(id);c.replaceWith(Object.assign(document.createElement('div'),{className:'empty',id,textContent:'Charts need internet access to load Chart.js; the numbers below are complete.'}))}}
}
async function loadActivity(){
  const q=new URLSearchParams(location.search); if($('fuser').value)q.set('uid',$('fuser').value); if($('fkind').value)q.set('kind',$('fkind').value);
  const r=await fetch('api/activity?'+q); if(!r.ok)return; const d=await r.json();
  const label=k=>({message:'asked','tool:web_search':'searched','tool:scan_sources':'buzz scan','tool:read_url':'opened link',download:'downloaded','tool:download_video':'downloaded','tool:remember':'remembered','tool:set_reminder':'reminder','tool:watch_keyword':'alert','tool:generate_image':'image','tool:save_note':'note'})[k]||k.replace('tool:','').replace(/_/g,' ');
  $('activity').innerHTML='<tr><th>When</th><th>User</th><th>What</th><th>Detail</th></tr>'+
   (d.rows.map(x=>`<tr><td style="white-space:nowrap">${ago(x.seconds_ago)}</td><td>${esc(x.who)}<div class="sub mono">${esc(x.uid)}</div></td><td><span class="kind">${esc(label(x.kind))}</span></td><td>${esc(x.detail)}</td></tr>`).join('')||'<tr><td class="empty" colspan="4">Nothing yet</td></tr>');
  $('topsearch').innerHTML='<tr><th>Search</th><th class="num">Times</th><th class="num">Users</th></tr>'+
   (d.top_searches.map(t=>`<tr><td>${esc(t.q)}</td><td class="num">${t.n}</td><td class="num">${t.users}</td></tr>`).join('')||'<tr><td class="empty" colspan="3">No searches yet</td></tr>');
}
let usersFilled=false;
const _load=load; load=async function(){await _load(); if(!usersFilled){const r=await fetch('api/stats'+location.search); if(r.ok){const d=await r.json();
  $('fuser').innerHTML='<option value="">Everyone</option>'+d.users.map(u=>`<option value="${esc(u.uid)}">${esc(u.display)}</option>`).join(''); usersFilled=true}} loadActivity();};
$('fuser').onchange=loadActivity; $('fkind').onchange=loadActivity;
load();setInterval(load,30000);
</script></body></html>"""
