"""HTML for Predict & Win: the public page (/predict) and the owner admin page (localhost:8090/predict).

The public page is static; it loads state from /predict/api/board (cached a few seconds at the CDN) and the
player's own picks from /predict/api/me (token in a header, never cached). build_demo_html() makes a
self-contained preview with sample players that runs entirely in the browser.
"""
import json
import os

PUBLIC_URL = os.getenv("EVENT_PUBLIC_URL", "https://live.letsgrowesports.com").rstrip("/")


TLOGO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "teamlogos")


def team_logos(embed: bool = False) -> dict:
    import base64
    out = {}
    for f in sorted(os.listdir(TLOGO_DIR)) if os.path.isdir(TLOGO_DIR) else []:
        k = f.rsplit(".", 1)[0]
        out[k] = ("data:image/webp;base64," + base64.b64encode(open(os.path.join(TLOGO_DIR, f), "rb").read()).decode()
                  if embed else f"/tlogo/{f}")
    return out


def build_html(demo: bool = False, demo_seed: dict = None) -> str:
    return (PAGE.replace("__PUBLIC__", PUBLIC_URL).replace("__TLOGO__", json.dumps(team_logos(embed=demo)))
                .replace("__DEMO__", "true" if demo else "false")
                .replace("__SEED__", json.dumps(demo_seed or {})))


def build_demo_html() -> str:
    from core import predict
    s = predict.settings()
    seed = {"teams": s["teams"], "buckets": predict.bucket_labels(), "days": s["days"], "prize": s["prize"],
            "close": s["close"], "matches": s["matches"], "maps": s.get("maps", {})}
    return build_html(True, seed)


CSS = r"""
:root{color-scheme:dark;--bg:#0b0b12;--bg2:#121219;--card:#13131c;--card2:#1a1a26;--ink:#eeeef5;--muted:#8d8ca3;--line:#262636;
--lime:#b6f23a;--purple:#7c5cff;--cyan:#4cc9f0;--orange:#ff8a3d;--red:#ff4d5e;--gold:#f5c451}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 "Chakra Petch",system-ui,sans-serif;overflow-x:hidden}
body{background:radial-gradient(800px 380px at 80% -15%,rgba(124,92,255,.14),transparent 60%),var(--bg);min-height:100vh}
a{color:var(--cyan);text-decoration:none}a:hover{text-decoration:underline}
.mono{font-family:"Share Tech Mono",ui-monospace,monospace}.muted{color:var(--muted)}
.wrap{max-width:980px;margin:0 auto;padding:0 16px 96px}
.bar{position:sticky;top:0;z-index:20;background:rgba(11,11,18,.92);backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
.bar .in{max-width:980px;margin:0 auto;padding:10px 16px;display:flex;align-items:center;gap:10px}
.title{margin-right:auto;line-height:1.1;min-width:0}
.brand{display:block;font:12px "Share Tech Mono",monospace;color:var(--lime);letter-spacing:.04em}
.title h1{margin:2px 0 0;font-size:19px;font-weight:700;text-transform:uppercase;letter-spacing:.02em;white-space:nowrap}
.title h1 span{color:var(--muted);font-weight:600;font-size:13px}
.card{position:relative;background:var(--card);border:1px solid var(--line);padding:16px;min-width:0;margin-top:12px}
.card:before,.card:after{content:"";position:absolute;width:12px;height:12px;border:2px solid var(--lime);pointer-events:none}
.card:before{top:-1px;left:-1px;border-right:0;border-bottom:0}.card:after{bottom:-1px;right:-1px;border-left:0;border-top:0}
.lbl{font:12px "Share Tech Mono",monospace;color:var(--red);letter-spacing:.08em;text-transform:uppercase}
h2{font:700 15px "Chakra Petch",sans-serif;text-transform:uppercase;letter-spacing:.04em;margin:0}
.head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px}.head>div:first-child{margin-right:auto;min-width:0}
.btn{all:unset;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:9px 16px;font:700 13px "Chakra Petch",sans-serif;text-transform:uppercase;letter-spacing:.04em;background:var(--lime);color:#0a0a14;clip-path:polygon(8px 0,100% 0,100% calc(100% - 8px),calc(100% - 8px) 100%,0 100%,0 8px);box-sizing:border-box}
.btn:focus-visible{outline:2px solid var(--cyan);outline-offset:2px}
.btn.ghost{background:transparent;color:var(--ink);border:1px solid var(--line);clip-path:none}.btn.sm{padding:5px 10px;font-size:11px}
.btn[disabled]{opacity:.5;cursor:default}
.hero h2{font-size:30px;line-height:1.05;margin:8px 0 6px}.hero h2 b{color:var(--lime)}
.hero p{margin:0;color:var(--muted);max-width:620px}
.prize{display:flex;align-items:center;gap:12px;margin-top:14px;padding:12px 14px;border:1px solid rgba(245,196,81,.45);background:linear-gradient(90deg,rgba(245,196,81,.14),rgba(245,196,81,.02))}
.prize{flex-direction:column;align-items:flex-start;gap:2px}.prize .ic{flex:none;width:38px;height:38px;display:grid;place-items:center;background:var(--gold);color:#0a0a14;font:700 18px "Chakra Petch";clip-path:polygon(6px 0,100% 0,100% calc(100% - 6px),calc(100% - 6px) 100%,0 100%,0 6px)}
.prize b{color:var(--gold);display:block;font-size:15px;text-transform:uppercase}.prize span{font-size:13px;color:var(--muted)}
.stats{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.pill{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border:1px solid var(--line);background:var(--card2);font:12px "Share Tech Mono",monospace;white-space:nowrap}
.pill b{color:var(--lime);font-weight:400}.pill.red b{color:var(--red)}
.field{display:block;margin:10px 0 0}.field span{display:block;font:12px "Share Tech Mono",monospace;color:var(--muted);margin-bottom:4px}
.inp{width:100%;background:var(--bg2);border:1px solid var(--line);color:var(--ink);padding:10px 12px;font:16px "Chakra Petch",sans-serif;outline:none;border-radius:0}
.inp:focus{border-color:var(--lime)}.at{display:flex;align-items:stretch}.at i{font-style:normal;display:grid;place-items:center;padding:0 10px;border:1px solid var(--line);border-right:0;background:var(--card2);color:var(--muted)}
.chk{display:flex;gap:8px;align-items:flex-start;margin:12px 0;font-size:13px;color:var(--muted)}.chk input{margin-top:3px;accent-color:#b6f23a;width:16px;height:16px;flex:none}
.err{color:var(--red);font-size:13px;margin-top:8px;min-height:1em}
.me{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.me .who{margin-right:auto}.me .who b{font-size:18px;display:block}
.av{width:42px;height:42px;flex:none;display:grid;place-items:center;background:var(--purple);font:700 16px "Chakra Petch";clip-path:polygon(6px 0,100% 0,100% calc(100% - 6px),calc(100% - 6px) 100%,0 100%,0 6px)}
.tabs{display:flex;margin:0 0 12px;border-bottom:1px solid var(--line);overflow-x:auto;scrollbar-width:none}
.tabs button{all:unset;cursor:pointer;padding:9px 13px;font:700 13px "Chakra Petch",sans-serif;text-transform:uppercase;color:var(--muted);border-bottom:3px solid transparent;white-space:nowrap}
.tabs button.on{color:var(--ink);border-color:var(--lime);background:linear-gradient(0deg,rgba(182,242,58,.10),transparent)}
.tabs button small{font:11px "Share Tech Mono",monospace;color:var(--muted);margin-left:5px}
.qs{display:grid;grid-template-columns:1fr;gap:12px}
.q{background:var(--card2);border:1px solid var(--line);padding:14px;display:flex;flex-direction:column;gap:10px;min-width:0}
.q.res{border-color:rgba(182,242,58,.35)}.q.void{opacity:.55}
.qt{display:flex;justify-content:space-between;gap:8px;font:11px "Share Tech Mono",monospace;color:var(--muted);text-transform:uppercase}
.qt .tag{color:var(--purple)}.qt .cl.open{color:var(--lime)}.qt .cl.shut{color:var(--red)}
.q h3{margin:0;font:700 17px/1.2 "Chakra Petch",sans-serif}
.opts{display:grid;grid-template-columns:1fr 1fr;gap:8px}.opts.one{grid-template-columns:1fr}
.opt{all:unset;cursor:pointer;position:relative;overflow:hidden;padding:11px 12px;border:1px solid var(--line);background:var(--bg2);font:700 14px "Chakra Petch";display:flex;justify-content:space-between;gap:8px;min-height:20px}
.opt .fill{position:absolute;inset:0 auto 0 0;background:rgba(124,92,255,.22);z-index:0;transition:width .4s}.opt>span{position:relative;z-index:1}
.opt .pc{font:12px "Share Tech Mono",monospace;color:var(--muted)}
.opt.mine{border-color:var(--lime);box-shadow:inset 0 0 0 1px var(--lime)}.opt.mine .fill{background:rgba(182,242,58,.22)}
.opt.ok{border-color:var(--lime)}.opt.ok:after{content:"\2713";position:relative;z-index:1;color:var(--lime)}
.opt[disabled]{cursor:default}
.cb{position:relative}.cbb{all:unset;cursor:pointer;display:flex;justify-content:space-between;align-items:center;gap:8px;width:100%;box-sizing:border-box;padding:11px 12px;border:1px solid var(--line);background:var(--bg2);font:700 15px "Chakra Petch"}
.cbb.mine{border-color:var(--lime)}.cbb .ph{color:var(--muted);font-weight:500}.cbb:after{content:"\25BE";color:var(--muted)}
.cbp{position:absolute;left:0;right:0;top:calc(100% + 4px);z-index:30;background:var(--bg2);border:1px solid var(--lime);box-shadow:0 12px 30px rgba(0,0,0,.6)}
.cbp .inp{border:0;border-bottom:1px solid var(--line)}
.cbl{max-height:260px;overflow:auto}.cbl button{all:unset;cursor:pointer;display:block;width:100%;box-sizing:border-box;padding:11px 12px;font:600 15px "Chakra Petch";border-bottom:1px solid var(--line)}
.cbl button:hover,.cbl button:focus{background:rgba(182,242,58,.1)}.cbl button.sel{color:var(--lime)}
.crowd{display:flex;flex-direction:column;gap:5px}.cr{display:grid;grid-template-columns:1fr auto;gap:8px;align-items:center;font-size:13px;position:relative;padding:5px 8px;background:var(--bg2);overflow:hidden}
.cr .fill{position:absolute;inset:0 auto 0 0;background:rgba(124,92,255,.25)}.cr>span{position:relative}.cr .pc{font:12px "Share Tech Mono",monospace;color:var(--muted)}
.cr.mine .fill{background:rgba(182,242,58,.25)}.cr.ok{outline:1px solid var(--lime)}.cr.ok>span:first-child:after{content:" \2713";color:var(--lime)}
.qf{display:flex;justify-content:space-between;gap:8px;font:12px "Share Tech Mono",monospace;color:var(--muted);flex-wrap:wrap}
.qf .good{color:var(--lime)}.qf .bad{color:var(--red)}.qf .saved{color:var(--lime)}
table{width:100%;border-collapse:collapse}th{font:11px "Share Tech Mono",monospace;color:#0a0a14;background:var(--lime);text-align:left;padding:6px 8px;text-transform:uppercase}
td{padding:9px 8px;border-bottom:1px solid var(--line);font-size:14px;vertical-align:middle}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
td.rk{width:40px;font:700 16px "Chakra Petch";text-align:center}tr.r1 td.rk{color:var(--gold)}tr.r2 td.rk,tr.r3 td.rk{color:var(--lime)}
tr.top5 td.rk{box-shadow:inset 3px 0 0 var(--gold)}
.nm{all:unset;cursor:pointer;font-weight:700;display:block;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.nm:hover{color:var(--lime)}
.hd{font:12px "Share Tech Mono",monospace}
tr.you td{background:rgba(182,242,58,.08)}tr.pin td{border-top:2px dashed var(--line)}
.rules{font-size:13px;color:var(--muted)}.rules b{color:var(--ink)}.rules p{margin:6px 0}
.modal{position:fixed;inset:0;z-index:60;background:rgba(3,2,12,.85);display:none;align-items:center;justify-content:center;padding:16px}
.modal.on{display:flex}.mbox{background:var(--bg2);border:1px solid var(--line);padding:14px;max-width:460px;width:100%;max-height:92vh;overflow:auto}
.mbox img{width:100%;display:block;border:1px solid var(--line);margin:10px 0;min-height:120px;background:var(--card)}
.mrow{display:grid;grid-template-columns:1fr 1fr;gap:8px}.mrow .btn{width:100%}
.toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:var(--lime);color:#0a0a14;padding:8px 14px;font:700 13px "Chakra Petch";z-index:80;display:none}
.demo{position:fixed;right:10px;top:64px;z-index:70;font:11px "Share Tech Mono",monospace;display:flex;flex-direction:column;align-items:flex-end;gap:6px}
.demo .dt{all:unset;cursor:pointer;background:var(--card2);color:var(--muted);border:1px solid var(--line);padding:5px 9px}
.demo .dp{display:none;background:var(--bg2);border:1px solid var(--line);padding:8px;gap:6px;flex-wrap:wrap;max-width:300px}.demo.on .dp{display:flex}
.demo select,.demo .dp button{font:11px "Share Tech Mono",monospace;background:var(--card2);color:var(--ink);border:1px solid var(--line);padding:4px 6px;max-width:100%}
.btn.go{position:relative;overflow:hidden}.btn.go.run{background:#0a0a14;color:var(--lime);box-shadow:inset 0 0 0 2px var(--lime)}
.btn.go.run:before{content:"";position:absolute;inset:0;background:linear-gradient(90deg,transparent,rgba(182,242,58,.35),transparent);animation:sweep .7s linear infinite}
.btn.go .gt{position:relative;z-index:1;letter-spacing:.12em}.btn.go.tick .gt{animation:pop .38s ease-out}
@keyframes sweep{from{transform:translateX(-100%)}to{transform:translateX(100%)}}@keyframes pop{0%{transform:scale(1.8);opacity:0}60%{transform:scale(.95);opacity:1}100%{transform:scale(1)}}
.tp{font:11px "Share Tech Mono",monospace;color:var(--muted);font-style:normal}.mo.on .tp{color:var(--lime)}
.pk{display:flex;flex-direction:column;gap:6px}.pk .row{display:flex;justify-content:space-between;gap:8px;padding:8px;background:var(--card2);font-size:13px}
.pk .row b{font-weight:700}.pk .ok{color:var(--lime)}.pk .no{color:var(--red)}
.btn.wide{width:100%;padding:13px 16px;font-size:15px}
.pn b{font-size:18px}.pn .hd{color:var(--muted);margin-left:4px}.rkbox{text-align:right}.hd2{font:700 15px "Chakra Petch";color:var(--ink)}
.pl{display:flex;align-items:baseline;gap:6px;min-width:0}.pl .nm{display:inline;flex:0 1 auto}.pl .hd{color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:0 1 auto;min-width:0}
.qsec{grid-column:1/-1;font:12px "Share Tech Mono",monospace;color:var(--red);letter-spacing:.08em;text-transform:uppercase;margin-top:4px}
.q.ev{border-color:rgba(124,92,255,.45)}
.mgrid{display:grid;grid-template-columns:1fr 1fr;gap:6px}.mo{all:unset;cursor:pointer;padding:10px 10px;border:1px solid var(--line);background:var(--bg2);font:700 13px "Chakra Petch";text-align:center;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;-webkit-tap-highlight-color:transparent}
.mo.on{border-color:var(--lime);background:rgba(182,242,58,.16);color:var(--lime)}
.mbar{display:flex;justify-content:space-between;align-items:center;gap:8px;font-size:12px;color:var(--muted)}
.tlb{flex:none;width:44px;height:24px;display:inline-flex;align-items:center;justify-content:center;margin-right:10px}.tlb img{max-width:44px;max-height:24px;object-fit:contain;display:block}
.mgrid{grid-template-columns:repeat(8,1fr)}.mo{position:relative;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;text-align:center;padding:10px 4px;font-size:13px;white-space:normal;line-height:1.15;min-height:64px}
.mo .tlb{margin:0;width:60px;height:30px}.mo .tlb img{max-width:60px;max-height:30px}.mo>span:last-child{white-space:normal;overflow:visible}
.nmx{display:flex;align-items:center;min-width:0}.nmx>span:last-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cbl button{display:flex;align-items:center}.how{font-size:13px;color:var(--muted);margin-top:-4px}.ch{font-size:12px;margin-bottom:2px}
.rules ul{margin:8px 0 0;padding-left:18px}.rules li{margin:5px 0;font-size:14px;color:var(--ink)}
.tx{display:flex;gap:8px}.cq{padding:12px 0;border-top:1px solid var(--line)}.cq:first-child{border-top:0;padding-top:0}.cqt{font:700 15px 'Chakra Petch',sans-serif;margin:4px 0 8px}.cr.mine{outline:1px solid var(--lime)}.qbadge{height:44px;display:block}
.sbar{position:fixed;left:50%;transform:translateX(-50%);width:min(948px,calc(100% - 20px));bottom:10px;z-index:65;display:none;align-items:center;justify-content:space-between;gap:10px;padding:10px 12px;background:rgba(18,18,25,.96);border:1px solid var(--lime);box-shadow:0 8px 30px rgba(0,0,0,.6)}
.sbar .mono{font-size:13px;color:var(--muted)}.sbar .btn[disabled]{background:var(--card2);color:var(--muted);opacity:1}.tx .inp{flex:1;min-width:0}
@view-transition{navigation:auto}
.pwin{position:fixed;inset:0;z-index:999;pointer-events:none;background:#0b0b12;display:grid;place-items:center;animation:pwout .5s .35s cubic-bezier(.7,0,.3,1) forwards}
.pwin b{font:700 22px "Chakra Petch",sans-serif;letter-spacing:.2em;color:#f5c451;animation:pwfade .25s .3s forwards}
@keyframes pwout{to{clip-path:inset(0 0 100% 0)}}@keyframes pwfade{to{opacity:0;transform:translateY(-8px)}}
.wrap>.card{animation:pwup .5s both}.wrap>.card:nth-child(2){animation-delay:.08s}.wrap>.card:nth-child(3){animation-delay:.16s}.wrap>.card:nth-child(n+4){animation-delay:.24s}
@keyframes pwup{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
@media(prefers-reduced-motion:reduce){.pwin{display:none}.wrap>.card{animation:none}}
@media(max-width:600px){.mgrid{grid-template-columns:repeat(4,1fr);gap:5px}.mo{font-size:11px;padding:8px 2px;min-height:60px;gap:5px}.mo .tlb{width:50px;height:26px}.mo .tlb img{max-width:50px;max-height:26px}.wrap{padding:0 10px 90px}.bar .in{padding:8px 10px}.title h1{font-size:16px}.hero h2{font-size:24px}
 .card{padding:12px}.qs{grid-template-columns:1fr}.tabs button{padding:8px 10px;font-size:12px}td{padding:8px 5px}.hide-m{display:none}
 .prize{padding:10px}.prize b{font-size:14px}}
.mo{position:relative}.mo .rk{position:absolute;top:4px;left:5px;font:700 12px "Chakra Petch";color:#0a0a14;background:var(--lime);padding:0 5px;line-height:17px}
.mo[disabled]{cursor:default}.mo.ok{border-color:var(--gold);box-shadow:inset 0 0 0 1px var(--gold)}.mo.ok:after{content:"\2713 RESULT";position:absolute;top:4px;right:5px;font:10px "Share Tech Mono";color:var(--gold)}
"""

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Predict & Win | BMSD 2026 | letsgrowesports</title>
<meta name="description" content="Pick the champion, top 3, BMIC qualifiers, MVPs, best IGL and the peak viewership for the BMSD 2026 Grand Finals. Free to play. Top 5 win a gift card.">
<meta property="og:type" content="website"><meta property="og:site_name" content="letsgrowesports">
<meta property="og:title" content="BMSD 2026 · Predict & Win"><meta property="og:description" content="Pick the champion, top 3, BMIC qualifiers, MVPs, best IGL and the peak viewership for the BMSD 2026 Grand Finals. Free to play. Top 5 win a gift card.">
<meta property="og:url" content="__PUBLIC__/predict"><meta property="og:image" content="__PUBLIC__/predict/og.png?v=2">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:description" content="Pick the champion, top 3, BMIC qualifiers, MVPs, best IGL and the peak viewership for the BMSD 2026 Grand Finals. Free to play. Top 5 win a gift card."><meta name="twitter:title" content="BMSD 2026 · Predict & Win"><meta name="twitter:image" content="__PUBLIC__/predict/og.png?v=2">
<meta name="theme-color" content="#0b0b12">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@500;600;700&family=Share+Tech+Mono&display=swap" rel="stylesheet">
<style>__CSS__</style></head><body>
<div class="pwin" id="pwin"><b>PREDICT &amp; WIN</b></div>
<div class="bar"><div class="in">
 <div class="title"><a class="brand" href="https://www.instagram.com/letsgrowesports.igc/" target="_blank" rel="noopener">letsgrowesports</a><h1>Predict & Win <span>// BMSD 2026</span></h1></div>
 <a class="btn ghost sm" href="/">&larr; Live viewers</a>
</div></div>
<div class="wrap">
 <div class="card hero">
  <div class="lbl">// free to play · points only</div>
  <h2>Predict the <b>BMSD 2026</b> Grand Finals</h2>
  <p>Pick the winners. Get points when you're right. The top 5 win a gift card of their choice.</p>
  <div class="stats"><span class="pill red" id="nl">PICKS LOCK <b id="nlt">-</b></span></div>
 </div>
 <div class="card" id="joinCard"></div>
 <div class="card" id="qcard"><div class="lbl">// step 2</div><h2 style="margin:4px 0 12px">Make your picks</h2>
  <div class="tabs" id="dtabs"></div><div class="qs" id="qs"></div>
  <div class="sbar" id="sbar"><span id="sbt" class="mono"></span><button class="btn" id="sbb" disabled>Submit my picks</button></div></div>
 <div class="card" id="crowdCard" style="display:none"><div class="lbl">// what everyone picked</div><h2 style="margin:4px 0 4px">Crowd picks</h2>
  <div class="muted" style="font-size:13px;margin-bottom:10px">Updates live. The leaderboard and winners are revealed after the finals on Sun 18 Oct.</div><div id="crowd"></div></div>
 <div class="card" id="lbCard" style="display:none"><div class="head"><div><div class="lbl">// leaderboard</div><h2>Top 10</h2></div><button class="btn sm" id="shareLb">Share</button></div>
  <div class="tabs" id="ltabs"></div>
  <table><thead><tr><th>#</th><th>Player</th><th class="num">Points</th></tr></thead><tbody id="lb"></tbody></table>
  <div class="muted" style="font-size:12px;margin-top:8px">Gold = gift card zone. Tap a name to see their picks.</div></div>
 <div class="card rules"><div class="lbl">// rules</div>
  <ul>
   <li>Free to play. No money, no bets.</li>
   <li>Right pick = 100 points. If few people got it right, you get up to 100 bonus points.</li>
   <li>Top 3 and BMIC: you get points for each team you got right.</li>
   <li>Answer every question, then submit. Picks can't be changed after.</li>
   <li>Top 5 on the leaderboard after the finals (Sun 18 Oct) win a gift card. Ties go to whoever joined first.</li>
   <li>One account per person and per internet connection. Fake accounts are removed.</li>
   <li>Fan-made game. Not linked to KRAFTON or Instagram.</li>
  </ul>
 </div>
</div>
<div class="modal" id="smodal"><div class="mbox"><div class="head"><div><h2 id="smt">Share</h2></div><button class="btn ghost sm" data-close>Close</button></div>
 <img id="simg" alt="Share image"><div class="mrow"><button class="btn" id="sNative">Share</button><button class="btn ghost" id="sCopy">Copy link</button><button class="btn ghost" id="sX">X</button><button class="btn ghost" id="sWa">WhatsApp</button><button class="btn ghost" id="sDl" style="grid-column:1/-1">Download image</button></div>
 <div class="muted" style="font-size:12px;margin-top:8px">Instagram: download the image, then post it to your story and tag @letsgrowesports.igc.</div></div></div>
<div class="modal" id="pmodal"><div class="mbox"><div class="head"><div><h2 id="pmt">Player</h2><div class="muted mono" id="pms" style="font-size:12px"></div></div><button class="btn ghost sm" data-close>Close</button></div><div class="pk" id="pmb"></div></div></div>
<div class="toast" id="toast"></div>
<script>
const DEMO=__DEMO__, SEED=__SEED__, TLOGO=__TLOGO__, SITE='__PUBLIC__', URLP=SITE+'/predict';
let DB=null, B=null, ME=null, TOKEN=null, dayTab=null, lbTab='all', openCb=null, busy={};
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const nowS=()=>Date.now()/1000;
try{TOKEN=localStorage.getItem('pw_token')}catch(e){}
function saveTok(t){TOKEN=t;try{t?localStorage.setItem('pw_token',t):localStorage.removeItem('pw_token')}catch(e){}}
function toast(t){const el=$('toast');el.textContent=t;el.style.display='block';clearTimeout(toast.h);toast.h=setTimeout(()=>el.style.display='none',2200)}
async function api(path,body){
 if(DEMO)return demoApi(path,body);
 const o={headers:{}};if(TOKEN)o.headers['X-PW-Token']=TOKEN;
 if(body!==undefined){o.method='POST';o.headers['Content-Type']='application/json';o.body=JSON.stringify(body)}
 const r=await fetch('/predict/api/'+path+(body===undefined&&path==='board'?'?_='+Math.floor(Date.now()/5000):''),o);
 const j=await r.json().catch(()=>({error:'Network error'}));if(!r.ok)throw Object.assign(new Error(j.error||'Error'),{code:r.status});return j}
const ist=ts=>new Date(ts*1000).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',weekday:'short',day:'numeric',month:'short',hour:'numeric',minute:'2-digit'}).replace(/\s?(am|pm)/i,m=>' '+m.trim().toUpperCase());
const istT=ts=>new Date(ts*1000).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour:'numeric',minute:'2-digit'}).replace(/\s?(am|pm)/i,m=>' '+m.trim().toUpperCase());
function left(s){s=Math.max(0,Math.round(s));const d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60);return d?`${d}d ${h}h`:h?`${h}h ${m}m`:m?`${m}m`:`${s}s`}
function closeTxt(q){if(q.void)return['Cancelled','shut'];if(q.answer)return['Settled','shut'];if(q.closed||nowS()>=q.close_ts)return['Closed '+istT(q.close_ts)+' IST','shut'];
 return[`Closes ${istT(q.close_ts)} IST · in ${left(q.close_ts-nowS())}`,'open']}
const dayName=d=>{const s=(B&&B.days||{})[d];return s?new Date(s+'T12:00:00+05:30').toLocaleDateString('en-IN',{weekday:'short',day:'numeric',timeZone:'Asia/Kolkata'}):''};

// ---------- join / me ----------
const disp=p=>p.name&&p.name!==p.handle?p.name:'@'+p.handle;
function nameHtml(p){return p.name&&p.name!==p.handle?`<b>${esc(p.name)}</b> <span class="hd">@${esc(p.handle)}</span>`:`<b>@${esc(p.handle)}</b>`}
function renderJoin(){const c=$('joinCard');
 if(ME){const r=(ME.ranks||{}).all||{},p=ME.player;
  c.innerHTML=`<div class="me"><div class="av">${esc((p.name||p.handle).slice(0,1).toUpperCase())}</div><div class="who"><div class="lbl">// playing as</div><div class="pn">${nameHtml(p)}</div></div>
   ${B&&B.leaderboard?`<div class="mono rkbox"><div style="font-size:22px;color:var(--lime)">${r.pts?'#'+r.rank:'-'}</div><div class="muted" style="font-size:12px">${r.pts||0} PTS</div></div><button class="btn sm" id="shareMe">Share my rank</button>`:`<div class="mono rkbox" style="font-size:13px;color:${Object.keys(ME.picks||{}).length?'var(--lime)':'var(--muted)'}">${Object.keys(ME.picks||{}).length?'✓ PICKS SUBMITTED':'NOT SUBMITTED YET'}</div>`}</div>`;
  const sm=$('shareMe');if(sm)sm.onclick=()=>share('me');renderCrowd();return}
 c.innerHTML=`<div class="lbl">// step 1</div><h2 style="margin-top:4px">Enter your Instagram ID</h2>
  <div class="muted" style="font-size:13px;margin-top:4px">If you finish in the top 5, we'll DM you on Instagram. No password needed.<br><b style="color:var(--ink)">Answer every question, then press Submit. You can't change picks after submitting.</b></div>
  <div id="jf"><label class="field"><span>INSTAGRAM ID</span><div class="at"><i>@</i><input class="inp" id="jh" maxlength="80" placeholder="yourhandle" autocapitalize="none" autocorrect="off" spellcheck="false" inputmode="email" required></div></label>
  <label class="field"><span>NAME (OPTIONAL)</span><input class="inp" id="jn" maxlength="32" placeholder="Shown on the leaderboard"></label>
  <div class="muted" style="font-size:12px;margin:10px 0">Your Instagram ID and picks will show on the leaderboard.</div>
  <button class="btn wide go" type="button" id="jb"><span class="gt">Start playing</span></button><div class="err" id="je"></div></div>`;
 const start=async()=>{const b=$('jb');if(b.disabled)return;$('je').textContent='';if(!$('jh').value.trim()){$('je').textContent='Enter your Instagram ID first.';$('jh').focus();return}
  b.disabled=true;b.classList.add('run');const gt=b.querySelector('.gt');gt.textContent='LOADING';
  try{const j=await api('join',{handle:$('jh').value,name:$('jn').value,consent:true});
   for(const t of ['3','2','1','GO!']){gt.textContent=t;b.classList.remove('tick');void b.offsetWidth;b.classList.add('tick');await new Promise(r=>setTimeout(r,t==='GO!'?520:380))}
   saveTok(j.token);await loadMe();await loadBoard();$('qcard').scrollIntoView({behavior:'smooth'})}
  catch(err){$('je').textContent=err.message;b.disabled=false;b.classList.remove('run','tick');gt.textContent='Start playing'}};
 $('jb').onclick=start;['jh','jn'].forEach(id=>$(id).onkeydown=e=>{if(e.key==='Enter')start()})}
async function loadMe(){if(!TOKEN){ME=null;renderJoin();return}
 try{ME=await api('me',{})}catch(e){if(e.code===401){saveTok(null);ME=null}}renderJoin();if(B){renderQs();sbar()}}

// ---------- questions ----------
let draft={},cardHtml={};
function dayTabs(){const ds=[...new Set(B.questions.filter(q=>q.day).map(q=>q.day))].sort();if(!ds.length)ds.push(1);$('dtabs').style.display=ds.length>1?'':'none';if(dayTab!==null&&!ds.includes(dayTab))dayTab=null;
 if(dayTab===null){const open=B.questions.filter(q=>q.day&&!q.closed&&!q.void).sort((a,b)=>a.close_ts-b.close_ts)[0];dayTab=open?open.day:ds[0]}
 $('dtabs').innerHTML=ds.map(d=>`<button data-d="${d}" class="${d===dayTab?'on':''}">Day ${d}<small>${dayName(d)}</small></button>`).join('');
 $('dtabs').querySelectorAll('button').forEach(b=>b.onclick=()=>{dayTab=+b.dataset.d;openCb=null;cardHtml={};renderQs();dayTabs()})}
const cnt=(q,o)=>(q.pct||{})[o]||0;
function pct(q,o){return cnt(q,o)}
const tkey=o=>String(o).toUpperCase().replace(/[^A-Z0-9]/g,'');
const tl=o=>TLOGO[tkey(o)]?`<span class="tlb"><img src="${TLOGO[tkey(o)]}" alt="" decoding="async"></span>`:'';
const isAns=(q,o)=>Array.isArray(q.answer)?q.answer.includes(o):q.answer===o;
const myOf=q=>ME?ME.picks[q.id]:undefined;
const shutQ=q=>q.closed||q.void||nowS()>=q.close_ts;
function crowdBars(q,limit){const my=myOf(q),mine=Array.isArray(my)?my:[my];const ent=Object.entries(q.pct||{}).sort((a,b)=>b[1]-a[1]);let top=ent.slice(0,limit);
 (Array.isArray(q.answer)?q.answer:q.answer?[q.answer]:[]).forEach(a=>{if(!top.some(e=>e[0]===a))top.push([a,cnt(q,a)])});
 const rest=q.kind==='multi'?0:ent.slice(limit).reduce((a,e)=>a+e[1],0);
 return `<div class="crowd"><div class="muted ch">What everyone picked</div>${top.map(([o,n])=>`<div class="cr ${mine.includes(o)?'mine':''} ${isAns(q,o)?'ok':''}"><div class="fill" style="width:${n}%"></div><span class="nmx">${tl(o)}<span>${esc(o)}</span></span><span class="pc">${n}%</span></div>`).join('')}${rest?`<div class="cr"><div class="fill" style="width:${rest}%"></div><span class="nmx"><span>Others</span></span><span class="pc">${rest}%</span></div>`:''}${!ent.length?'<div class="muted" style="font-size:13px">Crowd % shows once 20 players have picked.</div>':''}</div>`}
function tiles(q,sel,attr,showPct,locked,ranked){return `<div class="mgrid">${q.options.map(o=>{const i=sel.indexOf(o);return `<button class="mo ${i>=0?'on':''} ${isAns(q,o)?'ok':''}" ${attr}="${q.id}" data-o="${esc(o)}" ${locked?'disabled':''}>${ranked&&i>=0?`<b class="rk">#${i+1}</b>`:''}${tl(o)}<span>${esc(o)}</span>${showPct?`<em class="tp">${pct(q,o)}%</em>`:''}</button>`}).join('')}</div>`}
const openQs=()=>B.questions.filter(q=>!q.void&&!shutQ(q)&&myOf(q)===undefined);
const isDone=(q,v)=>v!==undefined&&(q.kind==='multi'?Array.isArray(v)&&v.length===q.pick:String(v).trim().length>0);
function qBody(q,shut){const my=myOf(q),done=shut||my!==undefined,dv=draft[q.id];
 if(q.kind==='multi'){const sel=my?[...my]:(dv||[]);const t=tiles(q,sel,'data-mq',done&&q.picked,done,q.ranked);
  return done?t:t+`<div class="mbar"><span class="mono">${sel.length} of ${q.pick} picked</span></div>`}
 if(q.style==='grid')return tiles(q,my!==undefined?[my]:dv!==undefined?[dv]:[],'data-gq',done&&q.picked,done);
 if(q.kind==='text'){if(shut)return crowdBars(q,5);return `<div class="tx"><input class="inp" data-tq="${q.id}" maxlength="40" placeholder="Type a player name" value="${esc(dv??my??'')}" ${my!==undefined?'disabled':''}></div>`}
 if(q.style==='dropdown')return crowdBars(q,5);
 const cur=my!==undefined?my:dv;
 return `<div class="opts ${q.options.length>4||q.options.some(o=>o.length>14)?'one':''}">${q.options.map(o=>`<button class="opt ${o===cur?'mine':''} ${isAns(q,o)?'ok':''}" data-q="${q.id}" data-o="${esc(o)}" ${done?'disabled':''}><div class="fill" style="width:${done&&q.picked?pct(q,o):0}%"></div><span>${esc(o)}</span><span class="pc">${done&&q.picked?pct(q,o)+'%':''}</span></button>`).join('')}</div>`}
const HOW={text:()=>'Type a player name.',multi:q=>q.ranked?`Tap ${q.pick} teams in order: first tap is #1, then #2, then #3. Tap a team again to remove it.`:`Tap ${q.pick} teams. Tap a team again to remove it.`,grid:()=>'Tap a team.',buttons:()=>'Tap one.'};
function qCard(q){const [ct,cc]=closeTxt(q),my=myOf(q),shut=shutQ(q),has=my!==undefined;
 let foot='';const got=ME&&ME.pts?ME.pts[q.id]:undefined;const ans=Array.isArray(q.answer)?q.answer.join(', '):q.answer;
 if(q.answer&&has)foot=got>0?`<span class="good">Correct · +${got} points</span>`:`<span class="bad">Missed · Answer: ${esc(ans)}</span>`;
 else if(q.answer)foot=`<span>Answer: ${esc(ans)}</span>`;
 else if(has)foot=`<span class="saved">✓ Submitted</span><span>${q.picked?'% = share of players who picked each team':'Crowd % shows once 20 players have picked'}</span>`;
 else if(!shut)foot=isDone(q,draft[q.id])?'<span class="saved">✓ Answered</span>':'<span class="bad">Not answered yet</span>';
 const how=!shut&&!has?`<div class="how">${(HOW[q.kind==='multi'?'multi':q.kind==='text'?'text':q.style]||HOW.buttons)(q)}</div>`:'';
 return `<div class="q ${q.answer?'res':''} ${q.void?'void':''} ${q.day?'':'ev'}" data-id="${q.id}"><div class="qt"><span class="tag">${q.tag==='BMIC'&&TLOGO.BMIC26?`<img class="qbadge" src="${TLOGO.BMIC26}" alt="BMIC">`:esc(q.tag||q.kind)}</span><span class="cl ${cc}" data-cl="${q.id}">${ct}</span></div><h3>${esc(q.title)}</h3>${how}${qBody(q,shut)}<div class="qf">${foot}</div></div>`}
function sbar(){const el=$('sbar');if(!el||!B)return;const oq=openQs(),n=oq.filter(q=>isDone(q,draft[q.id])).length;
 if(!oq.length){el.style.display='none';return}el.style.display='flex';
 $('sbt').textContent=`${n} of ${oq.length} answered`;const b=$('sbb');b.disabled=n<oq.length;b.textContent=n<oq.length?`Answer all ${oq.length} to submit`:'Submit my picks'}
function saveDraft(){try{localStorage.setItem('pw_draft',JSON.stringify(draft))}catch(e){}}
try{draft=JSON.parse(localStorage.getItem('pw_draft')||'{}')||{}}catch(e){}
function visibleQs(){const ev=B.questions.filter(q=>!q.day),dq=B.questions.filter(q=>q.day===dayTab);return{ev:dayTab===1?ev:ev.filter(q=>!shutQ(q)||q.answer),dq}}
function renderQs(){const {ev,dq}=visibleQs(),ids=[...ev,...dq].map(q=>q.id).join(',');const box=$('qs');
 if(box.dataset.ids===ids){[...ev,...dq].forEach(q=>{const h=qCard(q);if(cardHtml[q.id]!==h){cardHtml[q.id]=h;const el=box.querySelector(`.q[data-id="${q.id}"]`);if(el)el.outerHTML=h}});if(openCb)toggleCb(openCb,true);return}
 box.dataset.ids=ids;cardHtml={};
 box.innerHTML=(ev.length&&dq.length?`<div class="qsec">Whole tournament</div>`:'')+(ev.length?``+ev.map(q=>(cardHtml[q.id]=qCard(q))).join(''):'')+
  (dq.length?`<div class="qsec">Day ${dayTab} · ${dayName(dayTab)}</div>`+dq.map(q=>(cardHtml[q.id]=qCard(q))).join(''):'');
 if(openCb)toggleCb(openCb,true)}
function updCard(id){const q=B.questions.find(x=>x.id===id),el=$('qs').querySelector(`.q[data-id="${id}"]`);if(!q||!el)return renderQs();const h=qCard(q);cardHtml[id]=h;el.outerHTML=h}
$('qs').addEventListener('click',e=>{const b=e.target.closest('button');if(!b||b.disabled)return;const d=b.dataset;
 if(d.gq){draft[+d.gq]=d.o;saveDraft();updCard(+d.gq);sbar();return}
 if(d.mq){const id=+d.mq,q=B.questions.find(x=>x.id===id);if(myOf(q)!==undefined)return;const sel=draft[id]||[];const i=sel.indexOf(d.o);
  if(i>=0)sel.splice(i,1);else if(sel.length<q.pick)sel.push(d.o);else{toast(`You already picked ${q.pick}. Tap one to remove it.`);return}draft[id]=sel;saveDraft();updCard(id);sbar();return}
 if(d.q&&b.classList.contains('opt')){draft[+d.q]=d.o;saveDraft();updCard(+d.q);sbar()}});
$('qs').addEventListener('input',e=>{const t=e.target;if(t.dataset.tq){draft[+t.dataset.tq]=t.value;saveDraft();sbar()}});
function toggleCb(qid,force){document.querySelectorAll('.cbp').forEach(p=>p.remove());if(openCb===qid&&!force){openCb=null;return}
 const q=B.questions.find(x=>x.id===qid),host=document.querySelector(`.cb[data-q="${qid}"]`);if(!q||!host){openCb=null;return}openCb=qid;
 const my=myOf(q),p=document.createElement('div');p.className='cbp';
 p.innerHTML=`<input class="inp" placeholder="Search" aria-label="Search"><div class="cbl" role="listbox"></div>`;host.appendChild(p);
 const inp=p.querySelector('input'),list=p.querySelector('.cbl');
 const draw=()=>{const f=inp.value.trim().toLowerCase();list.innerHTML=q.options.filter(o=>!f||o.toLowerCase().includes(f)).map(o=>`<button role="option" class="${o===my?'sel':''}" data-o="${esc(o)}">${tl(o)}<span>${esc(o)}</span></button>`).join('')||'<div class="muted" style="padding:10px">No match</div>';
  list.querySelectorAll('button').forEach(b=>b.onclick=e=>{e.stopPropagation();openCb=null;p.remove();draft[qid]=b.dataset.o;saveDraft();updCard(qid);sbar()})};
 draw();inp.oninput=draw;p.onclick=e=>e.stopPropagation();if(window.innerWidth>600)inp.focus();
 inp.onkeydown=e=>{if(e.key==='Escape'){openCb=null;p.remove()}if(e.key==='Enter'){const b=list.querySelector('button');if(b)b.click()}}}
document.addEventListener('click',()=>{if(openCb){openCb=null;document.querySelectorAll('.cbp').forEach(p=>p.remove())}});
async function submitAll(){if(!ME){toast('Enter your Instagram ID first (step 1)');$('joinCard').scrollIntoView({behavior:'smooth'});return}
 const oq=openQs();if(oq.some(q=>!isDone(q,draft[q.id]))){const f=oq.find(q=>!isDone(q,draft[q.id]));toast('Answer every question first');const el=$('qs').querySelector(`.q[data-id="${f.id}"]`);if(el)el.scrollIntoView({behavior:'smooth',block:'center'});return}
 if(!confirmSubmit())return;const b=$('sbb');b.disabled=true;b.textContent='Submitting...';
 const picks={};oq.forEach(q=>picks[q.id]=draft[q.id]);
 try{await api('submit',{picks});oq.forEach(q=>{ME.picks[q.id]=picks[q.id];delete draft[q.id]});saveDraft();toast('Submitted. Good luck!');await loadMe();await loadBoard();renderQs();renderCrowd();$('crowdCard').scrollIntoView({behavior:'smooth'})}
 catch(e){toast(e.message);await loadMe();await loadBoard()}finally{sbar()}}
function confirmSubmit(){if(DEMO)return true;try{return window.confirm('Submit your picks? You can\'t change them after.')}catch(e){return true}}
// ---------- crowd picks (only for players who submitted) ----------
let crowdSig='';
function renderCrowd(){const card=$('crowdCard');if(!card||!B)return;const has=ME&&Object.keys(ME.picks||{}).length;card.style.display=has?'':'none';if(!has)return;
 const sig=JSON.stringify(ME.crowd||{})+JSON.stringify(ME.picks);if(sig===crowdSig)return;crowdSig=sig;
 $('crowd').innerHTML=B.questions.filter(q=>ME.picks[q.id]!==undefined).map(q=>{const pc=(ME.crowd||{})[q.id]||{},my=ME.picks[q.id],mine=Array.isArray(my)?my:[my];
  const ent=Object.entries(pc).sort((a,b)=>b[1]-a[1]).slice(0,q.kind==='multi'?Math.max(q.pick,6):5);
  const tag=q.tag==='BMIC'&&TLOGO.BMIC26?`<img class="qbadge" style="height:30px" src="${TLOGO.BMIC26}" alt="BMIC">`:esc(q.tag);
  return `<div class="cq"><div class="qt"><span class="tag">${tag}</span></div><div class="cqt">${esc(q.title)}</div>${ent.length?`<div class="crowd">${ent.map(([o,n])=>`<div class="cr ${mine.includes(o)||mine.map(tn0).includes(tn0(o))?'mine':''}"><div class="fill" style="width:${n}%"></div><span class="nmx">${tl(o)}<span>${esc(o)}</span></span><span class="pc">${n}%</span></div>`).join('')}</div>`:'<div class="muted" style="font-size:13px">Results show once 20 players have submitted.</div>'}</div>`}).join('')}
const tn0=x=>String(x||'').toLowerCase().replace(/[^a-z0-9]/g,'');
// ---------- leaderboard ----------
function lbTabs(){const ds=[...new Set(B.questions.filter(q=>q.day).map(q=>String(q.day)))].sort();const t=[['all','Overall'],...ds.map(d=>[d,'Day '+d])];$('ltabs').style.display=t.length>2?'':'none';
 $('ltabs').innerHTML=t.map(([k,l])=>`<button data-k="${k}" class="${k===lbTab?'on':''}">${l}</button>`).join('');
 $('ltabs').querySelectorAll('button').forEach(b=>b.onclick=()=>{lbTab=b.dataset.k;lbSig='';lbTabs();renderLb()})}
function lbRow(r,cls){return `<tr class="${cls} ${r.rank<=3?'r'+r.rank:''} ${lbTab==='all'&&r.rank<=5?'top5':''}"><td class="rk">${r.rank}</td><td style="max-width:0;width:100%"><div class="pl"><button class="nm" data-h="${esc(r.handle)}">${esc(disp(r))}</button>${r.name&&r.name!==r.handle?`<a class="hd" href="https://www.instagram.com/${esc(r.handle)}/" target="_blank" rel="noopener nofollow">@${esc(r.handle)}</a>`:''}</div></td><td class="num"><b>${r.pts}</b></td></tr>`}
function renderLb(){const rows=(B.boards[lbTab]||[]);const meH=ME&&ME.player.handle;
 let h=rows.map(r=>lbRow(r,r.handle===meH?'you':'')).join('')||'<tr><td colspan=3 class="muted">No points yet. Points appear after each result.</td></tr>';
 const mr=ME&&ME.ranks&&ME.ranks[lbTab];
 if(mr&&!rows.some(r=>r.handle===meH)&&rows.length)h+=`<tr class="you pin"><td class="rk">${mr.rank}</td><td colspan=2><b>You: #${mr.rank} · ${mr.pts} points</b></td></tr>`;
 $('lb').innerHTML=h;$('lb').querySelectorAll('.nm').forEach(b=>b.onclick=()=>showProfile(b.dataset.h))}
async function showProfile(h){$('pmt').textContent='@'+h;$('pms').textContent='Loading...';$('pmb').innerHTML='';$('pmodal').classList.add('on');
 try{const p=await api('profile/'+encodeURIComponent(h));$('pmt').textContent=disp(p);
  $('pms').innerHTML=`<a href="https://www.instagram.com/${esc(p.handle)}/" target="_blank" rel="noopener nofollow">@${esc(p.handle)}</a> · ${p.rank?'#'+p.rank+' · ':''}${p.pts} pts · ${p.correct} correct`;
  $('pmb').innerHTML=p.picks.map(k=>`<div class="row"><span><span class="muted mono" style="font-size:11px">${esc(k.tag)}</span><br>${esc(k.title)}</span><span style="text-align:right"><b>${esc(k.pick)}</b><br>${k.void?'<span class="muted">cancelled</span>':k.correct===null?'<span class="muted">awaiting result</span>':k.correct?`<span class="ok">+${k.pts}</span>`:'<span class="no">0</span>'}</span></div>`).join('')||'<div class="muted">No closed picks yet. Picks become public when a question closes.</div>'}
 catch(e){$('pms').textContent=e.message}}

// ---------- share images ----------
const FONTS=document.fonts?document.fonts.ready:Promise.resolve();
function cardBase(){const W=1080,H=1350,c=document.createElement('canvas');c.width=W*2;c.height=H*2;const x=c.getContext('2d');x.scale(2,2);
 const g=x.createRadialGradient(W*.85,0,40,W*.85,0,1200);g.addColorStop(0,'#231c46');g.addColorStop(1,'#0b0b12');x.fillStyle=g;x.fillRect(0,0,W,H);
 x.fillStyle='rgba(255,255,255,.02)';for(let y=0;y<H;y+=4)x.fillRect(0,y,W,1);
 x.strokeStyle='#b6f23a';x.lineWidth=5;x.beginPath();x.moveTo(40,80);x.lineTo(40,40);x.lineTo(80,40);x.stroke();x.beginPath();x.moveTo(W-40,H-210);x.lineTo(W-40,H-170);x.lineTo(W-80,H-170);x.stroke();
 x.textBaseline='top';const T=(t,X,Y,f,col,al,mw)=>{x.font=f;if(mw){const w=x.measureText(t).width;if(w>mw){const m=f.match(/(\d+)px/);x.font=f.replace(/\d+px/,Math.max(10,Math.floor(+m[1]*mw/w))+'px')}}x.fillStyle=col;x.textAlign=al||'left';x.fillText(t,X,Y)};
 const M=s=>`${s}px "Share Tech Mono",monospace`,F=s=>`700 ${s}px "Chakra Petch",sans-serif`;
 T('letsgrowesports',80,78,M(30),'#b6f23a');T('BMSD 2026 · PREDICT & WIN',80,118,F(54),'#eeeef5',null,W-160);
 x.fillStyle='#b6f23a';x.fillRect(0,H-130,W,130);T('LIVE.LETSGROWESPORTS.COM/PREDICT',80,H-108,F(44),'#0a0a14',null,W-160);T('Free to play · top 5 win a gift card · @letsgrowesports.igc',80,H-52,M(24),'#0a0a14',null,W-160);
 return{c,x,T,M,F,W,H}}
function lbCard(){const {c,x,T,M,F,W}=cardBase(),rows=(B.boards[lbTab]||[]).slice(0,10);
 T(lbTab==='all'?'// OVERALL LEADERBOARD':`// DAY ${lbTab} LEADERBOARD`,80,205,M(30),'#ff4d5e');T(`updated ${istT(nowS())} IST`,80,248,M(24),'#8d8ca3');
 if(!rows.length)T('THE BOARD FILLS UP AS QUESTIONS ARE SETTLED',80,330,F(36),'#eeeef5');
 rows.forEach((r,j)=>{const y=300+j*84,gold=lbTab==='all'&&r.rank<=5,c=r.rank===1?'#f5c451':gold?'#f5c451':r.rank<=3?'#b6f23a':'#eeeef5';
  x.fillStyle=j%2?'rgba(255,255,255,.03)':'rgba(255,255,255,.06)';x.fillRect(60,y-8,W-120,74);if(gold){x.fillStyle='#f5c451';x.fillRect(60,y-8,8,74)}
  T(String(r.rank),110,y+12,F(38),c,'center');if(r.name&&r.name!==r.handle){T(r.name.toUpperCase(),160,y,F(34),'#ffffff',null,W-160-300);T('@'+r.handle,160,y+40,M(22),'#8d8ca3',null,W-160-300)}else T('@'+r.handle,160,y+12,F(34),'#ffffff',null,W-160-300);
  T(r.pts+' PTS',W-90,y+10,F(38),c,'right')});return c}
function meCard(){const {c,x,T,M,F,W}=cardBase(),r=(ME.ranks||{}).all||{},h='@'+ME.player.handle;
 T('// MY RANK',80,205,M(30),'#ff4d5e');
 x.save();x.shadowColor='rgba(182,242,58,.45)';x.shadowBlur=40;T(r.rank?'#'+r.rank:'-',72,250,F(260),'#b6f23a');x.restore();
 T(h,80,540,F(64),'#ffffff',null,W-160);T(`is #${r.rank||'-'} on Predict & Win · ${r.pts||0} pts`,80,620,F(40),'#eeeef5',null,W-160);
 T(`${r.correct||0} correct calls · ${Object.keys(ME.picks).length} picks`,80,682,M(28),'#8d8ca3',null,W-160);
 x.fillStyle='rgba(245,196,81,.12)';x.fillRect(80,770,W-160,150);x.fillStyle='#f5c451';x.fillRect(80,770,8,150);
 T('TOP 5 WIN A GIFT CARD',112,800,F(44),'#f5c451');T('Think you can beat me? Make your calls before they lock.',112,858,M(26),'#eeeef5',null,W-220);
 const top=(B.boards.all||[]).slice(0,3);T('// CURRENT TOP 3',80,970,M(26),'#ff4d5e');
 top.forEach((t,j)=>{T(`${t.rank}. ${disp(t).toUpperCase()}`,80,1012+j*44,F(32),j?'#eeeef5':'#f5c451',null,700);T(t.pts+' PTS',W-80,1012+j*44,F(32),j?'#eeeef5':'#f5c451','right')});return c}
let shared=null;
async function share(type){await FONTS;const c=type==='me'?meCard():lbCard();$('smt').textContent=type==='me'?'Share my rank':'Share leaderboard';$('simg').removeAttribute('src');$('smodal').classList.add('on');
 const r=(ME&&ME.ranks.all)||{};
 const text=type==='me'?`@${ME.player.handle} is #${r.rank||'-'} on Predict & Win · ${r.pts||0} pts. BMSD 2026 Grand Finals: call the winners, top 5 win a gift card.`:`BMSD 2026 Predict & Win leaderboard${lbTab==='all'?'':' (Day '+lbTab+')'}: ${(B.boards[lbTab]||[]).slice(0,3).map(x=>`${x.rank}. ${disp(x)} ${x.pts}`).join(' | ')}. Free to play, top 5 win a gift card.`;
 $('simg').src=c.toDataURL('image/png');c.toBlob(b=>{shared={blob:b,text,name:type==='me'?'predict-my-rank.png':'predict-leaderboard.png'}},'image/png')}
$('sNative').onclick=async()=>{if(!shared)return;const f=new File([shared.blob],shared.name,{type:'image/png'});
 try{if(navigator.canShare&&navigator.canShare({files:[f]}))await navigator.share({files:[f],text:shared.text+' '+URLP});else if(navigator.share)await navigator.share({text:shared.text,url:URLP});else{dl();toast('Image downloaded')}}catch(e){}};
$('sCopy').onclick=async()=>{try{await navigator.clipboard.writeText(URLP);toast('Link copied')}catch(e){toast(URLP)}};
$('sX').onclick=()=>window.open('https://twitter.com/intent/tweet?text='+encodeURIComponent(shared?shared.text:'')+'&url='+encodeURIComponent(URLP),'_blank','noopener');
$('sWa').onclick=()=>window.open('https://wa.me/?text='+encodeURIComponent((shared?shared.text+' ':'')+URLP),'_blank','noopener');
function dl(){if(!shared)return;const a=document.createElement('a');a.href=URL.createObjectURL(shared.blob);a.download=shared.name;document.body.appendChild(a);a.click();a.remove()}
$('sDl').onclick=dl;$('shareLb').onclick=()=>share('lb');$('sbb').onclick=submitAll;
document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>b.closest('.modal').classList.remove('on'));
document.querySelectorAll('.modal').forEach(m=>m.onclick=e=>{if(e.target===m)m.classList.remove('on')});

// ---------- refresh ----------
function header(){
 const nx=B.questions.filter(q=>!q.closed&&!q.void&&q.close_ts>nowS()).sort((a,b)=>a.close_ts-b.close_ts)[0];
 $('nlt').textContent=nx?`${istT(nx.close_ts)} IST · ${left(nx.close_ts-nowS())}`:'ALL LOCKED';
}
let lbSig='';async function loadBoard(){try{B=await api('board')}catch(e){return}header();dayTabs();renderQs();sbar();$('lbCard').style.display=B.leaderboard?'':'none';const sg=JSON.stringify(B.boards)+lbTab;if(sg!==lbSig){lbSig=sg;lbTabs();renderLb()}}
function tick(){if(!B)return;B.questions.forEach(q=>{if(!q.closed&&nowS()>=q.close_ts){q.closed=true;if(openCb===q.id)openCb=null;updCard(q.id)}});
 document.querySelectorAll('[data-cl]').forEach(el=>{const q=B.questions.find(x=>x.id===+el.dataset.cl);if(q)el.textContent=closeTxt(q)[0]});header()}
setTimeout(()=>{const p=$('pwin');if(p)p.remove()},1100);
(async()=>{if(DEMO)demoInit();await loadBoard();await loadMe();renderLb();setInterval(tick,15000);
 setInterval(()=>{if(!document.hidden&&!openCb)loadBoard()},DEMO?4000:20000);setInterval(()=>{if(!document.hidden&&TOKEN)loadMe().then(renderLb)},DEMO?5000:20000)})();

// ---------- preview engine (DEMO only: everything below runs in the browser, nothing is saved) ----------
function demoInit(){const t0=nowS(),d=SEED.days,cl=k=>Date.parse(d[k]+'T'+SEED.close+':00+05:30')/1000,T=SEED.teams;
 const names=['Aarav','Ishaan','Kabir','Vihaan','Rohan','Arjun','Neha','Priya','Sneha','Ananya','Rahul','Karan','Dev','Aditya','Tanvi','Meera','Yash','Om','Riya','Zoya','Sahil','Varun','Manav','Nikhil','Pooja','Kriti','Harsh','Siddh','Tara','Ira','Aryan','Ayaan','Diya','Jay','Laksh','Mihir','Nisha','Parth','Rehan','Veer'];
 DB={players:names.map((n,i)=>({id:i+1,handle:(n+'_'+['gg','op','x','bgmi','yt','fps'][i%6]).toLowerCase(),name:i%4?n+(i%3?'':' OP'):'',created:t0-9000+i*60,hidden:false})),qs:[],picks:{},me:null,seq:1};
 const add=(kind,title,opts,close,day,tag,style,extra)=>DB.qs.push(Object.assign({id:DB.seq++,kind,title,options:opts,close_ts:close,day,tag,style,locked:false,answer:null,void:false},extra||{}));
 add('team','Who will win the BMSD 2026 Grand Finals?',T,cl('1'),0,'CHAMPION','grid');
 add('multi','Which teams will finish in the top 3?',T,cl('1'),0,'TOP 3','multi',{pick:3,ranked:true});
 add('multi','Which 6 teams will qualify for BMIC?',T,cl('1'),0,'BMIC','multi',{pick:6});
 add('text','Final MVP',[],cl('1'),0,'FINAL MVP','text');add('text','MVP of the Tournament',[],cl('1'),0,'TOURNAMENT MVP','text');
 add('text','Best IGL',[],cl('1'),0,'BEST IGL','text');add('text','The Eliminator',[],cl('1'),0,'THE ELIMINATOR','text');
 add('peak',"What will the tournament's peak viewership be?",SEED.buckets,cl('1'),0,'PEAK VIEWERS','buttons');
 const pw=o=>{const ws=o.map((v,i)=>[v,1/Math.pow(i+1,.8)]),s=ws.reduce((a,b)=>a+b[1],0);let r=Math.random()*s;for(const [v,x] of ws){r-=x;if(r<=0)return v}return o[0]};
 const elim=['Jonathan','Jonathan','Goblin','Spower','jonathan ','Aditya','Neyoo','Clutchgod'];
 DB.players.forEach(p=>DB.qs.forEach(q=>{if(Math.random()>.8)return;let v;
  if(q.kind==='multi'){const s=new Set();while(s.size<q.pick)s.add(pw(q.options));v=[...s]}else if(q.kind==='text')v=elim[Math.floor(Math.random()*elim.length)];else v=pw(q.options);DB.picks[p.id+':'+q.id]=v}));
 DB.bonus={};DB.players.forEach((p,i)=>{if(i<14)DB.bonus[p.id]=Math.round(420-i*22-Math.random()*15)})}
const dClosed=q=>q.locked||nowS()>=q.close_ts;
const tn=s=>String(s||'').toLowerCase().replace(/[^a-z0-9]/g,'');
function dStats(q){const s={n:0,inc:{},names:{}};DB.players.forEach(p=>{if(p.hidden)return;const v=DB.picks[p.id+':'+q.id];if(v===undefined)return;s.n++;
 if(q.kind==='multi')v.forEach(t=>s.inc[t]=(s.inc[t]||0)+1);else if(q.kind==='text'){const k=tn(v);s.inc[k]=(s.inc[k]||0)+1;s.names[k]=s.names[k]||v.trim()}else s.inc[v]=(s.inc[v]||0)+1});return s}
const dAns=q=>!q.answer?[]:Array.isArray(q.answer)?q.answer:[q.answer];
function dPts(q,s,v){if(!q.answer||q.void||v===undefined)return 0;const n=Math.max(1,s.n),A=dAns(q);
 if(q.kind==='multi')return Math.round(v.filter(t=>A.includes(t)).reduce((a,t)=>a+(100+100*(1-(s.inc[t]||1)/n))/q.pick,0));
 if(q.kind==='text'){const acc=A.map(tn);if(!acc.includes(tn(v)))return 0;const c=Object.entries(s.inc).filter(([k])=>acc.includes(k)).reduce((a,e)=>a+e[1],0)||1;return 100+Math.round(100*(1-c/n))}
 return v===q.answer?100+Math.round(100*(1-(s.inc[v]||1)/n)):0}
function dBest(q,s){if(!q.answer||q.void)return null;const n=Math.max(1,s.n),A=dAns(q);
 if(q.kind==='multi')return Math.round(A.reduce((a,t)=>a+100+100*(1-(s.inc[t]||1)/n),0)/q.pick);
 if(q.kind==='text'){const acc=A.map(tn),c=Object.entries(s.inc).filter(([k])=>acc.includes(k)).reduce((a,e)=>a+e[1],0)||1;return 100+Math.round(100*(1-c/n))}
 return 100+Math.round(100*(1-(s.inc[q.answer]||1)/n))}
function dRank(b){const S={};DB.qs.forEach(q=>S[q.id]=dStats(q));
 const rows=DB.players.filter(p=>!p.hidden).map(p=>{let pts=b==='all'||b===1?(DB.bonus[p.id]||0):0,c=pts?1:0;DB.qs.forEach(q=>{if(b!=='all'&&q.day!==b)return;const x=dPts(q,S[q.id],DB.picks[p.id+':'+q.id]);if(x){pts+=x;c++}});return{id:p.id,handle:p.handle,name:p.name,pts,correct:c,created:p.created}})
  .sort((a,b)=>b.pts-a.pts||b.correct-a.correct||a.created-b.created);rows.forEach((r,i)=>r.rank=i+1);return rows}
async function demoApi(path,body){await new Promise(r=>setTimeout(r,100));const err=(m,c)=>{throw Object.assign(new Error(m),{code:c||400})};
 if(path==='board'){return{now:nowS(),leaderboard:false,prize:SEED.prize,days:SEED.days,
  questions:DB.qs.map(q=>{const s=dStats(q),cl=dClosed(q);let counts=s.inc;if(q.kind==='text'){counts={};if(cl)Object.entries(s.inc).sort((a,b)=>b[1]-a[1]).slice(0,5).forEach(([k,v])=>counts[s.names[k]]=v)}
   const pct={};if(cl&&s.n>=20)for(const k in counts)pct[k]=Math.round(100*counts[k]/s.n);
   return{id:q.id,kind:q.kind,tag:q.tag,title:q.title,day:q.day,style:q.style,options:q.options,close_ts:q.close_ts,closed:cl,void:q.void,answer:q.answer,pick:q.pick,ranked:!!q.ranked,pct,picked:cl&&s.n>=20,worth:dBest(q,s)}}),
  boards:Object.fromEntries(['all','1','2','3'].map(b=>[b,dRank(b==='all'?'all':+b).filter(r=>r.pts>0).slice(0,10).map(({rank,handle,name,pts,correct})=>({rank,handle,name,pts,correct}))]))}}
 if(path==='join'){let h=(body.handle||'').trim();const m=h.match(/instagram\.com\/([^/?#\s]+)/i);if(m)h=m[1];h=h.replace(/^@/,'').toLowerCase();
  if(!/^[a-z0-9._]{1,30}$/.test(h))err('Enter a valid Instagram ID (letters, numbers, . and _ only).');
  if(!body.consent)err('Please tick the box to agree your ID, name and closed picks are shown publicly.');
  if(DB.players.some(p=>p.handle===h))err("That Instagram ID is already playing on another device. If it's yours, DM @letsgrowesports.igc to release it.",409);
  const p={id:DB.players.length+1,handle:h,name:(body.name||'').trim().slice(0,32),created:nowS(),hidden:false};DB.players.push(p);DB.me=p.id;return{token:'demo',player:p}}
 if(path==='me'){if(!DB.me)err('Not joined',401);const p=DB.players[DB.me-1],picks={},pts={};DB.qs.forEach(q=>{const v=DB.picks[p.id+':'+q.id];if(v!==undefined){picks[q.id]=v;if(q.answer)pts[q.id]=dPts(q,dStats(q),v)}});
  const ranks={};['all','1','2','3'].forEach(b=>{const r=dRank(b==='all'?'all':+b).find(r=>r.id===p.id);ranks[b]={rank:r.rank,pts:r.pts,correct:r.correct}});
  const crowd={};DB.qs.forEach(q=>{if(picks[q.id]===undefined)return;const st=dStats(q),c={};if(st.n>=20){const src=q.kind==='text'?Object.fromEntries(Object.entries(st.inc).map(([k,v])=>[st.names[k],v])):st.inc;for(const k in src)c[k]=Math.round(100*src[k]/st.n)}crowd[q.id]=c});
  return{player:{handle:p.handle,name:p.name},picks,pts,ranks:{},crowd}}
 if(path==='pick'){if(!DB.me)err('Join first.',401);const q=DB.qs.find(q=>q.id===body.qid);if(!q)err('No such question',404);if(q.void)err('This question was cancelled.',409);if(dClosed(q))err('Picks for this question are closed.',409);if(DB.picks[DB.me+':'+q.id]!==undefined)err("You've already made this pick. Picks can't be changed.",409);
  if(q.kind==='multi'&&(!Array.isArray(body.option)||new Set(body.option).size!==q.pick))err(`Pick exactly ${q.pick} teams.`);
  DB.picks[DB.me+':'+q.id]=body.option;return{ok:true}}
 if(path==='submit'){if(!DB.me)err('Join first.',401);const open=DB.qs.filter(q=>!q.void&&!dClosed(q)&&DB.picks[DB.me+':'+q.id]===undefined);
  for(const q of open){const v=body.picks[q.id];if(v===undefined||(q.kind==='multi'&&(!Array.isArray(v)||new Set(v).size!==q.pick)))err('Answer every question before submitting.')}
  open.forEach(q=>DB.picks[DB.me+':'+q.id]=body.picks[q.id]);return{ok:true}}
 if(path.startsWith('profile/')){const h=decodeURIComponent(path.slice(8)),p=DB.players.find(p=>p.handle===h);if(!p)err('No such player',404);const r=dRank('all').find(r=>r.id===p.id);
  return{handle:p.handle,name:p.name,rank:r.rank,pts:r.pts,correct:r.correct,picks:DB.qs.filter(q=>dClosed(q)&&DB.picks[p.id+':'+q.id]!==undefined).map(q=>{const k=DB.picks[p.id+':'+q.id],x=dPts(q,dStats(q),k);return{qid:q.id,title:q.title,tag:q.tag,day:q.day,pick:Array.isArray(k)?k.join(', '):k,answer:dAns(q).join(', '),void:q.void,correct:q.answer&&!q.void?x>0:null,pts:x}})}}
 err('Unknown',404)}
if(DEMO){const bar=document.createElement('div');bar.className='demo';
 bar.innerHTML='<div class="dp">Owner test: <select id="dq"></select><select id="da"></select><button id="dlock">Lock</button><button id="dset">Settle</button><button id="dme">Reset me</button></div><button class="dt" id="dtg">Preview tools</button>';document.body.appendChild(bar);$('dtg').onclick=()=>bar.classList.toggle('on');
 const fill=()=>{$('dq').innerHTML=DB.qs.map(q=>`<option value="${q.id}">${esc(q.tag)}${q.answer?' ✓':dClosed(q)?' (locked)':''}</option>`).join('');fillA()};
 const fillA=()=>{const q=DB.qs.find(q=>q.id===+$('dq').value)||DB.qs[0];
  $('da').innerHTML=q.kind==='multi'?'<option value="auto">crowd favourites</option>':q.kind==='text'?'<option>Jonathan</option><option>Goblin</option>':q.options.map(o=>`<option>${esc(o)}</option>`).join('')};
 setTimeout(()=>{fill();$('dq').onchange=fillA},0);
 bar.addEventListener('click',async e=>{const id=e.target.id,q=DB.qs.find(q=>q.id===+$('dq').value);if(!q)return;
  if(id==='dlock'){q.locked=true;toast('Locked: crowd picks are now public')}
  if(id==='dset'){q.locked=true;if(q.kind==='multi'){const s=dStats(q);q.answer=Object.entries(s.inc).sort((a,b)=>b[1]-a[1]).slice(0,q.pick).map(e=>e[0])}else q.answer=q.kind==='text'?[$('da').value]:$('da').value;toast('Settled: '+dAns(q).join(', '))}
  if(id==='dme'){for(const k in DB.picks)if(k.startsWith(DB.me+':'))delete DB.picks[k];DB.me=null;saveTok(null);ME=null;renderJoin();renderQs();toast('Reset. Join again to test.')}
  if(['dlock','dset'].includes(id)){const v=q.id;fill();$('dq').value=v;fillA();await loadBoard();if(DB.me){TOKEN='demo';await loadMe();renderLb()}}});
 }
</script></body></html>""".replace("__CSS__", CSS)


ADMIN = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Predict & Win admin</title><style>__CSS__
.wrap{max-width:1200px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
textarea.inp{min-height:150px;font:13px "Share Tech Mono",monospace}select.inp{padding:8px}
td{font-size:13px;vertical-align:top}.cnt{font:11px "Share Tech Mono",monospace;color:var(--muted);max-width:280px}
.acts{display:flex;gap:4px;flex-wrap:wrap}.acts .btn{padding:4px 8px;font-size:11px}.ok{color:var(--lime)}.no{color:var(--red)}
.row2{display:flex;gap:8px;flex-wrap:wrap;align-items:end}.row2>*{flex:1;min-width:120px}</style></head><body>
<div class="bar"><div class="in"><div class="title"><span class="brand">owner only · localhost</span><h1>Predict & Win <span>// admin</span></h1></div>
<a class="btn ghost sm" href="/predict/preview" target="_blank">Public preview</a></div></div>
<div class="wrap">
<div class="grid">
 <div class="card"><div class="lbl">// create questions</div><div class="row2"><label class="field"><span>DAY</span><select class="inp" id="mdDay"><option>1</option><option>2</option><option>3</option></select></label>
  <label class="field"><span>CLOSE (IST)</span><input class="inp" id="mdClose" type="datetime-local"></label></div>
  <p class="muted" style="font-size:12px">Tournament questions (once): champion (closes Day 3), top 3, BMIC 6 (close at the time above). Day questions: chicken dinner for matches 1-6, most chicken dinners, and peak viewers for the chosen day. Nothing is duplicated.</p>
  <div class="acts"><button class="btn" data-a="eventset">Create tournament questions</button><button class="btn" data-a="dayset">Create day questions</button><button class="btn ghost" data-a="peak">+ Peak viewers (auto)</button><button class="btn ghost" data-a="mvpday">+ Day MVP</button><button class="btn ghost" data-a="mvpevent">+ Event MVP</button><button class="btn ghost" data-a="record">+ Beat 730K?</button></div></div>
 <div class="card"><div class="lbl">// custom question</div><label class="field"><span>TITLE</span><input class="inp" id="cqT" placeholder="Which team gets the most finishes on Day 1?"></label>
  <div class="row2"><label class="field"><span>TAG</span><input class="inp" id="cqTag" value="BONUS"></label><label class="field"><span>DAY (0 = event)</span><select class="inp" id="cqD"><option>0</option><option selected>1</option><option>2</option><option>3</option></select></label><label class="field"><span>STYLE</span><select class="inp" id="cqS"><option>buttons</option><option>dropdown</option></select></label></div>
  <label class="field"><span>OPTIONS (one per line)</span><textarea class="inp" id="cqO" style="min-height:90px"></textarea></label>
  <label class="field"><span>CLOSE (IST)</span><input class="inp" id="cqC" type="datetime-local"></label><div style="margin-top:10px"><button class="btn" data-a="custom">Add question</button></div></div>
 <div class="card"><div class="lbl">// settings</div>
  <label class="field"><span>TEAMS (one per line)</span><textarea class="inp" id="sTeams"></textarea></label>
  <label class="field"><span>MVP CANDIDATES (one per line, e.g. Jonathan (GodLike))</span><textarea class="inp" id="sMvp"></textarea></label>
  <label class="field"><span>PEAK BUCKETS (thousands, comma separated)</span><input class="inp" id="sBuckets"></label>
  <div class="row2"><label class="field"><span>DAY 1</span><input class="inp" id="sD1" type="date"></label><label class="field"><span>DAY 2</span><input class="inp" id="sD2" type="date"></label><label class="field"><span>DAY 3</span><input class="inp" id="sD3" type="date"></label></div>
  <div class="row2"><label class="field"><span>DEFAULT CLOSE (IST)</span><input class="inp" id="sClose" type="time"></label><label class="field"><span>MATCHES / DAY</span><input class="inp" id="sMatches" type="number" min="1" max="12"></label></div>
  <label class="field"><span>PRIZE TEXT (shown on the page)</span><input class="inp" id="sPrize"></label>
  <label class="chk"><input type="checkbox" id="sLb"> <span>Show the public leaderboard (turn on after the finals)</span></label>
  <div style="margin-top:10px"><button class="btn" data-a="settings">Save settings</button></div></div>
</div>
<div class="card"><div class="head"><div><div class="lbl">// questions</div><h2 id="qh">Questions</h2></div><button class="btn ghost sm" data-a="reload">Refresh</button></div><div style="overflow-x:auto"><table><thead><tr><th>#</th><th>Question</th><th>Closes (IST)</th><th>Status</th><th>Picks</th><th>Actions</th></tr></thead><tbody id="qt"></tbody></table></div></div>
<div class="card"><div class="head"><div><div class="lbl">// players</div><h2 id="ph">Players</h2></div><input class="inp" id="pf" placeholder="Filter" style="max-width:220px"></div><div style="overflow-x:auto"><table><thead><tr><th>Handle</th><th>Name</th><th>Joined</th><th class="num">Picks</th><th class="num">Pts</th><th>Status</th><th></th></tr></thead><tbody id="pt"></tbody></table></div></div>
</div><div class="toast" id="toast"></div>
<script>
const $=id=>document.getElementById(id),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const TK=new URLSearchParams(location.search).get('token');
async function api(p,b){const r=await fetch('/api/predict/'+p+(TK?'?token='+encodeURIComponent(TK):''),b===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});const j=await r.json().catch(()=>({error:'Error '+r.status}));if(!r.ok){toast(j.error||'Error');throw new Error(j.error)}return j}
function toast(t){const e=$('toast');e.textContent=t;e.style.display='block';clearTimeout(toast.h);toast.h=setTimeout(()=>e.style.display='none',2500)}
// datetime-local inputs are treated as IST
const toTs=v=>v?Date.parse(v+':00+05:30')/1000:null;
const toLocal=ts=>{const d=new Date((ts+19800)*1000);return d.toISOString().slice(0,16)};
const ist=ts=>new Date(ts*1000).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',weekday:'short',day:'numeric',month:'short',hour:'numeric',minute:'2-digit'});
let S={},Q=[],P=[];
async function load(){const j=await api('state');S=j.settings;Q=j.questions;P=j.players;
 $('sTeams').value=S.teams.join('\n');$('sMvp').value=S.mvp.join('\n');$('sBuckets').value=S.buckets.join(', ');$('sD1').value=S.days['1'];$('sD2').value=S.days['2'];$('sD3').value=S.days['3'];
 $('sClose').value=S.close;$('sMatches').value=S.matches;$('sPrize').value=S.prize;$('sLb').checked=!!S.show_leaderboard;
 if(!$('mdClose').value)$('mdClose').value=S.days[$('mdDay').value]+'T'+S.close;if(!$('cqC').value)$('cqC').value=S.days['1']+'T'+S.close;
 const now=Date.now()/1000;$('qh').textContent=`Questions (${Q.length})`;
 $('qt').innerHTML=Q.map(q=>{const cl=q.locked||now>=q.close_ts,st=q.void?'<span class="no">VOID</span>':q.answer&&q.answer.length?`<span class="ok">SETTLED: ${esc(Array.isArray(q.answer)?q.answer.join(', '):q.answer)}</span>`:cl?'<span class="no">LOCKED</span>':'<span class="ok">OPEN</span>';
  const cnt=Object.entries(q.counts).sort((a,b)=>b[1]-a[1]).map(([o,n])=>`${esc(o)}: ${n}`).join(' · ');
  return `<tr><td>${q.id}</td><td><b>${esc(q.title)}</b><div class="cnt">${esc(q.tag)} · day ${q.day||'event'} · ${q.kind}${q.meta&&q.meta.auto?' · auto-resolve':''}</div></td>
  <td><input class="inp" type="datetime-local" value="${toLocal(q.close_ts)}" data-close="${q.id}" style="padding:4px;font-size:12px;width:180px"></td><td>${st}</td><td class="cnt">${q.total} picks<br>${cnt}</td>
  <td><div class="acts">${q.kind==='text'?`<input class="inp" data-ans="${q.id}" placeholder="Accepted names, comma separated" value="${esc((q.answer||[]).join(', '))}" style="padding:4px;font-size:12px;max-width:220px">`:`<select class="inp" data-ans="${q.id}" ${q.kind==='multi'?'multiple size="6"':''} style="padding:4px;font-size:12px;max-width:190px">${q.options.map(o=>`<option ${(Array.isArray(q.answer)?q.answer.includes(o):o===q.answer)?'selected':''}>${esc(o)}</option>`).join('')}</select>`}
  <button class="btn" data-q="answer" data-id="${q.id}">Mark answer</button>${['peak','yesno'].includes(q.kind)?`<button class="btn ghost" data-q="tracker" data-id="${q.id}">From tracker</button>`:''}
  ${cl?`<button class="btn ghost" data-q="reopen" data-id="${q.id}">Reopen</button>`:`<button class="btn ghost" data-q="lock" data-id="${q.id}">Lock now</button>`}
  ${q.answer&&q.answer.length?`<button class="btn ghost" data-q="unresolve" data-id="${q.id}">Unsettle</button>`:''}<button class="btn ghost" data-q="${q.void?'unvoid':'void'}" data-id="${q.id}">${q.void?'Unvoid':'Void'}</button><button class="btn ghost" data-q="delete" data-id="${q.id}">Delete</button></div></td></tr>`}).join('')||'<tr><td colspan=6 class="muted">No questions yet. Use "Create match day".</td></tr>';
 drawP()}
function drawP(){const f=$('pf').value.toLowerCase();$('ph').textContent=`Players (${P.length})`;
 $('pt').innerHTML=P.filter(p=>!f||(p.handle+' '+p.name).toLowerCase().includes(f)).map(p=>`<tr><td><a href="https://www.instagram.com/${esc(p.handle)}/" target="_blank" rel="noopener nofollow">@${esc(p.handle)}</a></td><td>${esc(p.name)}</td><td class="cnt">${ist(p.created)}</td><td class="num">${p.picks}</td><td class="num">${p.pts}</td>
 <td>${p.hidden?'<span class="no">HIDDEN</span>':'visible'}${p.bound?'':' · <span class="ok">released</span>'}</td><td><div class="acts"><button class="btn ghost" data-p="${p.hidden?'unhide':'hide'}" data-id="${p.id}">${p.hidden?'Unhide':'Hide'}</button>${p.bound?`<button class="btn ghost" data-p="release" data-id="${p.id}">Release</button>`:''}<button class="btn ghost" data-p="delete" data-id="${p.id}">Delete</button></div></td></tr>`).join('')}
$('pf').oninput=drawP;$('mdDay').onchange=()=>{$('mdClose').value=S.days[$('mdDay').value]+'T'+S.close};
document.addEventListener('change',async e=>{const id=e.target.dataset.close;if(id){await api('q/'+id,{action:'close_ts',value:toTs(e.target.value)});toast('Close time saved');load()}});
document.addEventListener('click',async e=>{const b=e.target.closest('button');if(!b)return;const a=b.dataset.a,q=b.dataset.q,p=b.dataset.p,id=b.dataset.id;
 try{
 if(a==='reload')return load();
 if(a==='eventset'){const j=await api('eventset',{close_ts:toTs($('mdClose').value)});toast(`Created ${j.created.length} tournament questions`)}
 if(a==='dayset'){const j=await api('dayset',{day:+$('mdDay').value,close_ts:toTs($('mdClose').value)});toast(`Created ${j.created.length} day questions`)}
 if(a==='matchday'){const j=await api('matchday',{day:+$('mdDay').value,close_ts:toTs($('mdClose').value)});toast(`Created ${j.created.length} questions`)}
 if(a==='peak'){await api('add',{type:'peak',day:+$('mdDay').value,close_ts:toTs($('mdClose').value)});toast('Peak question added')}
 if(a==='mvpday'){await api('add',{type:'mvp',day:+$('mdDay').value,close_ts:toTs($('mdClose').value)});toast('MVP question added')}
 if(a==='mvpevent'){await api('add',{type:'mvp',day:0,close_ts:toTs($('mdClose').value)});toast('Event MVP question added')}
 if(a==='record'){await api('add',{type:'record',close_ts:toTs($('mdClose').value)});toast('Record question added')}
 if(a==='custom'){await api('add',{type:'custom',title:$('cqT').value,tag:$('cqTag').value,day:+$('cqD').value,style:$('cqS').value,options:$('cqO').value.split('\n'),close_ts:toTs($('cqC').value)});toast('Question added');$('cqT').value='';$('cqO').value=''}
 if(a==='settings'){await api('settings',{teams:$('sTeams').value.split('\n').map(s=>s.trim()).filter(Boolean),mvp:$('sMvp').value.split('\n').map(s=>s.trim()).filter(Boolean),
  buckets:$('sBuckets').value.split(',').map(s=>parseInt(s)).filter(n=>n>0),days:{'1':$('sD1').value,'2':$('sD2').value,'3':$('sD3').value},close:$('sClose').value,matches:+$('sMatches').value,prize:$('sPrize').value,show_leaderboard:$('sLb').checked});toast('Settings saved')}
 if(q){if(q==='delete'&&!confirm('Delete this question and all its picks?'))return;
  if(q==='answer'){const el=document.querySelector(`[data-ans="${id}"]`);const v=el.multiple?[...el.selectedOptions].map(o=>o.value):el.value;if(!confirm('Settle with: '+(Array.isArray(v)?v.join(', '):v)+' ?'))return;await api('q/'+id,{action:'answer',value:v});toast('Settled')}
  else if(q==='tracker'){const j=await api('q/'+id+'/tracker',{});toast('Settled from tracker: '+j.answer)}
  else await api('q/'+id,{action:q});}
 if(p){if(p==='delete'&&!confirm('Delete this player and all their picks? Use this for test entries.'))return;await api('player/'+id,{action:p});toast('Done')}
 if(a||q||p)load()}catch(err){}});
load();setInterval(load,30000);
</script></body></html>""".replace("__CSS__", CSS)
