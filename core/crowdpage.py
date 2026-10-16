"""/predict once the game is closed: what the community predicted (percentages only, no players or counts)."""
import json
import os

from core.predictpage import PUBLIC_URL, team_logos


PDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "players")


def player_imgs(embed: bool = False) -> dict:
    """{name: {"f": full cutout url, "h": head url}} from static/players/<Name>.webp and <Name>_h.webp."""
    import base64
    out = {}
    for f in sorted(os.listdir(PDIR)) if os.path.isdir(PDIR) else []:
        if not f.endswith(".webp"):
            continue
        name, kind = (f[:-7], "h") if f.endswith("_h.webp") else (f[:-5], "f")
        url = ("data:image/webp;base64," + base64.b64encode(open(os.path.join(PDIR, f), "rb").read()).decode()) if embed \
            else f"/pimg/{f}"
        out.setdefault(name, {})[kind] = url
    return out


def build_html(data: dict = None, embed_logos: bool = False) -> str:
    if data is None:
        from core import crowd
        data = crowd.split(top=6, all_teams=True)
    return (PAGE.replace("__PUBLIC__", PUBLIC_URL)
                .replace("__TLOGO__", json.dumps(team_logos(embed=embed_logos)))
                .replace("__PIMG__", json.dumps(player_imgs(embed=embed_logos)))
                .replace("__DATA__", json.dumps(data).replace("</", "<\\/")))


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>What the community predicted | BMSD 2026 | letsgrowesports</title>
<meta name="description" content="BMSD 2026 Grand Finals: who the community backed for champion, top 3, BMIC, MVPs, best IGL and peak viewership.">
<meta property="og:title" content="BMSD 2026: what the community predicted | letsgrowesports">
<meta property="og:description" content="Who the community backed for champion, top 3, BMIC, MVPs, best IGL and peak viewership.">
<meta property="og:url" content="__PUBLIC__/predict"><meta property="og:image" content="__PUBLIC__/predict/og.png?v=2">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630"><meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#07051a">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@500;600;700&family=Share+Tech+Mono&display=swap" rel="stylesheet">
<style>
:root{color-scheme:dark;--bg:#0b0b12;--card:#13131c;--card2:#1a1a26;--ink:#eeeef5;--muted:#8d8ca3;--line:#262636;
--lime:#b6f23a;--purple:#7c5cff;--cyan:#4cc9f0;--orange:#ff8a3d;--red:#ff4d5e;--gold:#f5c451}
*{box-sizing:border-box}html,body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 "Chakra Petch",system-ui,sans-serif}
body{background:radial-gradient(800px 380px at 80% -15%,rgba(124,92,255,.14),transparent 60%),var(--bg);min-height:100vh}
body:before{content:"";position:fixed;inset:0;pointer-events:none;z-index:50;background:repeating-linear-gradient(0deg,rgba(255,255,255,.012) 0 1px,transparent 1px 3px)}
a{color:var(--cyan);text-decoration:none}.mono{font-family:"Share Tech Mono",monospace}
.bar{position:sticky;top:0;z-index:20;background:rgba(11,11,18,.9);backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
.bar .in{max-width:1180px;margin:0 auto;padding:10px 16px;display:flex;align-items:center;gap:10px}
.brand{display:block;font:12px "Share Tech Mono",monospace;color:var(--lime);letter-spacing:.04em}
h1{margin:2px 0 0;font-size:19px;text-transform:uppercase;letter-spacing:.02em;line-height:1.1}h1 span{color:var(--muted);font-weight:600}
.back{margin-left:auto;font:12px "Share Tech Mono",monospace;border:1px solid var(--line);padding:6px 10px;color:var(--ink);background:var(--card);white-space:nowrap}
.back:hover{border-color:var(--lime);color:var(--lime)}
.wrap{max-width:1180px;margin:0 auto;padding:0 16px 40px}
.hero{margin-top:18px}.hero .lbl{font:13px "Share Tech Mono",monospace;color:var(--red);letter-spacing:.06em}
.hero h2{margin:4px 0 2px;font-size:clamp(26px,5vw,40px);text-transform:uppercase;line-height:1.05}
.hero p{margin:0;color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:12px;margin-top:16px}
.c{position:relative;background:var(--card);border:1px solid var(--line);padding:16px;grid-column:span 6;min-width:0;opacity:0;transform:translateY(10px);transition:opacity .5s,transform .5s}
.c.in{opacity:1;transform:none}.c.s4{grid-column:span 4}.c.s8{grid-column:span 8}.c.s12{grid-column:1/-1}
.c:before{content:"";position:absolute;left:-1px;top:-1px;width:14px;height:14px;border-left:3px solid var(--lime);border-top:3px solid var(--lime)}
.t{font:12px "Share Tech Mono",monospace;color:var(--red);letter-spacing:.05em}.c h3{margin:2px 0 12px;font-size:17px}
.ft{font:11px "Share Tech Mono",monospace;color:var(--muted);margin-top:10px}
@media(max-width:900px){.c,.c.s4,.c.s8{grid-column:1/-1}}
.lg{width:26px;height:26px;border-radius:50%;object-fit:cover;background:var(--card2);border:1px solid var(--line);flex:none;display:inline-grid;place-items:center;font:700 10px "Chakra Petch",sans-serif;color:var(--muted)}
.ok:after{content:" \2713";color:var(--lime)}
/* donut */
.dn{display:flex;gap:18px;align-items:center;flex-wrap:wrap}.dn svg{flex:none;width:210px;height:210px}
.leg{flex:1;min-width:180px;display:flex;flex-direction:column;gap:7px}
.leg div{display:flex;align-items:center;gap:8px;font-weight:600;font-size:14px}.leg i{width:10px;height:10px;flex:none}
.leg span.p{margin-left:auto;font:15px "Share Tech Mono",monospace}
/* rings */
.rings{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.ring{text-align:center}.ring svg{width:100%;max-width:96px}
.ring b{display:block;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.ring span{font:13px "Share Tech Mono",monospace;color:var(--muted)}
/* heat tiles */
.tiles{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px}
.tile{position:relative;padding:10px 8px;border:1px solid var(--line);display:flex;flex-direction:column;align-items:center;gap:4px;text-align:center;min-width:0}
.tile b{font-size:12px;line-height:1.15;max-width:100%}
@media(max-width:640px){.tile{padding:8px 3px}.tile b{font-size:10.5px}.tile span{font-size:15px}}.tile span{font:18px "Share Tech Mono",monospace}
.tile.cut{outline:2px solid var(--lime);outline-offset:-2px}
.keyrow{display:flex;align-items:center;gap:8px;margin-top:10px;font:11px "Share Tech Mono",monospace;color:var(--muted)}
.keyrow i{flex:1;max-width:160px;height:6px;background:linear-gradient(90deg,rgba(182,242,58,.04),rgba(182,242,58,.9))}
/* hero stat */
.big{display:flex;align-items:center;gap:16px;flex-wrap:wrap}.big .n{font:700 clamp(54px,9vw,84px)/1 "Chakra Petch",sans-serif;color:var(--lime);text-shadow:0 0 24px rgba(182,242,58,.35)}
.big .who{font-size:22px;font-weight:700;text-transform:uppercase}.big .who small{display:block;font:12px "Share Tech Mono",monospace;color:var(--muted);text-transform:none}
.pills{display:flex;flex-wrap:wrap;gap:6px;margin-top:14px}.pills span{border:1px solid var(--line);background:var(--card2);padding:5px 10px;font-size:13px;font-weight:600}
.pills span em{font:normal 13px "Share Tech Mono",monospace;color:var(--muted);margin-left:6px}
/* stacked */
.stk{display:flex;height:44px;overflow:hidden;border:1px solid var(--line)}.stk div{height:100%;transform-origin:left;transition:flex-grow 1s}
.stk div+div{border-left:2px solid var(--bg)}
.sleg{display:grid;grid-template-columns:repeat(2,1fr);gap:6px 14px;margin-top:12px}.sleg div{display:flex;align-items:center;gap:8px;font-size:14px;font-weight:600}
.sleg i{width:10px;height:10px;flex:none}.sleg span{margin-left:auto;font:14px "Share Tech Mono",monospace}
/* treemap */
.tm{position:relative;height:280px}.tm div{position:absolute;border:2px solid var(--card);padding:8px;overflow:hidden;display:flex;flex-direction:column;justify-content:flex-end}
.tm b{font-size:14px;line-height:1.1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.tm span{font:20px "Share Tech Mono",monospace}
/* gauge */
.gg{display:flex;gap:16px;align-items:center;flex-wrap:wrap}.gg svg{width:220px;flex:none}
.rk{flex:1;min-width:170px}.rk div{display:flex;align-items:center;gap:10px;padding:5px 0;border-bottom:1px dashed var(--line);font-weight:600}.rk div:last-child{border:0}
.rk em{font:normal 13px "Share Tech Mono",monospace;color:var(--muted);width:22px;display:inline-block;flex:none}.rk span{margin-left:auto;font:14px "Share Tech Mono",monospace}
/* players */
.av{width:24px;height:24px;border-radius:50%;object-fit:cover;object-position:top;background:var(--card2);border:1px solid var(--line);flex:none;display:inline-grid;place-items:center;font:700 9px "Chakra Petch",sans-serif;color:var(--muted)}
.c.ph{overflow:hidden}.cut{position:absolute;right:-6px;bottom:0;height:88%;max-height:330px;width:auto;pointer-events:none;
 -webkit-mask-image:linear-gradient(to top,transparent 0,#000 34%);mask-image:linear-gradient(to top,transparent 0,#000 34%);filter:saturate(.95) contrast(1.03)}
.c.ph>*:not(.cut){position:relative;z-index:1}
.heroP .pills{max-width:64%}.heroP .big{min-height:190px;align-items:flex-start;flex-direction:column;gap:6px;max-width:62%}
.heroP .cut{height:100%;max-height:360px;opacity:.95}
.heroP:after{content:"";position:absolute;inset:0;background:linear-gradient(90deg,var(--card) 34%,transparent 75%);z-index:0;pointer-events:none}
.elimP .gtop{display:flex;align-items:flex-end;justify-content:space-between;min-height:150px}
.elimP .cut{position:relative;right:auto;bottom:auto;height:170px;margin-right:-8px}
.tm .tc{position:absolute;right:0;bottom:0;height:92%;width:auto;-webkit-mask-image:linear-gradient(to top,transparent 0,#000 30%);mask-image:linear-gradient(to top,transparent 0,#000 30%);pointer-events:none}
.tm b{display:flex;align-items:center;gap:6px}.tav{width:30px;height:30px;border-color:rgba(0,0,0,.25)}
.pills span{display:inline-flex;align-items:center;gap:6px;padding:3px 10px 3px 3px}
/* curve */
.cv svg{width:100%;height:auto;display:block}
.foot{margin-top:22px;font:12px "Share Tech Mono",monospace;color:var(--muted);display:flex;gap:12px;flex-wrap:wrap}
@media(prefers-reduced-motion:reduce){.c{opacity:1;transform:none;transition:none}}
</style></head><body>
<div class="bar"><div class="in"><div><span class="brand">letsgrowesports</span><h1>BMSD 2026 <span>// Predict &amp; Win</span></h1></div><a class="back" href="/">LIVE VIEWERSHIP &rarr;</a></div></div>
<div class="wrap"><div class="hero"><div class="lbl">// THE COMMUNITY HAS SPOKEN</div><h2>What the community predicted</h2><p>Predictions closed 4 PM IST, 16 Oct. Results after the grand finals.</p></div>
<div class="grid" id="g"></div>
<div class="foot"><span>Percentages of everyone who played. Typed names are grouped (spellings and team tags).</span></div></div>
<script>
const C=__DATA__,TL=__TLOGO__,PI=__PIMG__,G=document.getElementById('g');
const COL=['#b6f23a','#4cc9f0','#7c5cff','#ff8a3d','#ff4d5e','#f5c451','#3fd6a4','#e070ff'],OTH='#3a3a4e';
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const key=s=>String(s).toUpperCase().replace(/[^A-Z0-9]/g,'');
const pc=v=>(v>=10?Math.round(v):(+v).toFixed(1)).toString().replace(/\.0$/,'')+'%';
const logo=(r,cls)=>{const src=TL[key(r.label)];return src?`<img class="lg ${cls||''}" src="${src}" alt="">`:`<span class="lg ${cls||''}">${r.other?'+':esc(r.label.slice(0,2).toUpperCase())}</span>`};
const PK=n=>Object.keys(PI).find(k=>k.toLowerCase()===String(n).toLowerCase()),ph=(n,k)=>{const x=PI[PK(n)];return x&&x[k||'h']},
 av=r=>{const u=!r.other&&ph(r.label);return u?`<img class="av" src="${u}" alt="" loading="lazy">`:`<span class="av">${r.other?'+':esc(r.label.slice(0,2).toUpperCase())}</span>`},
 cut=(n,cls)=>{const u=ph(n,'f');return u?`<img class="cut ${cls||''}" src="${u}" alt="${esc(n)}">`:''};
const Q=t=>C.questions.find(q=>q.tag===t),ok=(q,l)=>(q.answer||[]).map(a=>a.toLowerCase()).includes(String(l).toLowerCase())?'ok':'';
const card=(q,cls,inner)=>q?`<section class="c ${cls}"><div class="t">// ${esc(q.tag)}</div><h3>${esc(q.title)}</h3>${inner}<div class="ft">${esc(q.note)}</div></section>`:'';
const arc=(cx,cy,r,a0,a1)=>{const p=a=>[cx+r*Math.cos(a),cy+r*Math.sin(a)],[x0,y0]=p(a0),[x1,y1]=p(a1);return `M${x0} ${y0}A${r} ${r} 0 ${a1-a0>Math.PI?1:0} 1 ${x1} ${y1}`};
// 1. champion: donut
function donut(q){let a=-Math.PI/2;const tot=q.rows.reduce((s,r)=>s+r.pct,0)||1,L=q.rows[0];
 const segs=q.rows.map((r,i)=>{const da=r.pct/tot*2*Math.PI,d=arc(105,105,80,a+.012,a+da-.012);a+=da;return `<path d="${d}" stroke="${r.other?OTH:COL[i]}" stroke-width="30" fill="none" class="seg" style="--d:${i*90}ms"/>`}).join('');
 const lg=TL[key(L.label)];
 return card(q,'s4',`<div class="dn"><svg viewBox="0 0 210 210">${segs}${lg?`<image href="${lg}" x="75" y="52" width="60" height="60"/>`:''}<text x="105" y="140" text-anchor="middle" fill="#b6f23a" font-family="Share Tech Mono,monospace" font-size="28">${pc(L.pct)}</text><text x="105" y="160" text-anchor="middle" fill="#8d8ca3" font-family="Share Tech Mono,monospace" font-size="11">${esc(L.label.toUpperCase())}</text></svg>
 <div class="leg">${q.rows.map((r,i)=>`<div class="${ok(q,r.label)}"><i style="background:${r.other?OTH:COL[i]}"></i>${logo(r)}${esc(r.label)}<span class="p">${pc(r.pct)}</span></div>`).join('')}</div></div>`)}
// 2. top 3: rings
function rings(q){const rows=q.rows.slice(0,8);
 return card(q,'s8',`<div class="rings">${rows.map((r,i)=>{const L=2*Math.PI*40,src=TL[key(r.label)];return `<div class="ring ${ok(q,r.label)}"><svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="40" stroke="#262636" stroke-width="8" fill="none"/><circle cx="50" cy="50" r="40" stroke="${i<3?'#b6f23a':'#8d8ca3'}" stroke-width="8" fill="none" stroke-linecap="round" transform="rotate(-90 50 50)" stroke-dasharray="${L}" stroke-dashoffset="${L}" data-off="${L*(1-r.pct/100)}" class="rg" ${i<3?'style="filter:drop-shadow(0 0 4px rgba(182,242,58,.6))"':''}/>${src?`<image href="${src}" x="30" y="30" width="40" height="40"/>`:''}</svg><b>${esc(r.label)}</b><span>${pc(r.pct)}</span></div>`}).join('')}</div>`)}
// 3. BMIC: heat tiles
function heat(q){const k=6;
 return card(q,'s12',`<div class="tiles">${q.rows.map((r,i)=>`<div class="tile ${i<k?'cut':''} ${ok(q,r.label)}" style="background:rgba(182,242,58,${(.04+.5*r.pct/100).toFixed(3)})">${logo(r)}<b>${esc(r.label)}</b><span style="color:${r.pct>=50?'#eeeef5':'#8d8ca3'}">${pc(r.pct)}</span></div>`).join('')}</div><div class="keyrow">0%<i></i>100%<span style="margin-left:12px">outlined: the community's top 6</span></div>`)}
// 4. tournament MVP: hero stat + pills
function hero(q){const L=q.rows[0],sub=L.pct>=50?'picked by more than half':L.pct>=33?'about one in '+Math.round(100/L.pct):'the top pick';
 return card(q,'s4 ph heroP',`${cut(L.label)}<div class="big"><div class="n" data-n="${L.pct}">0%</div><div class="who ${ok(q,L.label)}">${esc(L.label)}<small>${sub}</small></div></div><div class="pills">${q.rows.slice(1).map(r=>`<span class="${ok(q,r.label)}">${av(r)}${esc(r.label)}<em>${pc(r.pct)}</em></span>`).join('')}</div>`)}
// 5. final MVP: 100% stacked bar
function stacked(q){
 return card(q,'s4',`<div class="stk">${q.rows.map((r,i)=>`<div style="flex:0 0 0;background:${r.other?OTH:COL[i]}" data-g="${r.pct}" title="${esc(r.label)} ${pc(r.pct)}"></div>`).join('')}</div><div class="sleg">${q.rows.map((r,i)=>`<div class="${ok(q,r.label)}"><i style="background:${r.other?OTH:COL[i]}"></i>${av(r)}${esc(r.label)}<span>${pc(r.pct)}</span></div>`).join('')}</div>`)}
// 6. best IGL: squarified treemap
function squarify(items,x,y,w,h){const out=[],tot=items.reduce((a,r)=>a+r.pct,0),sc=w*h/tot;let rest=items.map(r=>({...r,a:r.pct*sc}));
 const worst=(row,len)=>{const s=row.reduce((a,r)=>a+r.a,0);return Math.max(...row.map(r=>Math.max(len*len*r.a/(s*s),s*s/(len*len*r.a))))};
 while(rest.length){const len=Math.min(w,h);let row=[rest[0]],k=1;while(k<rest.length&&worst(row.concat(rest[k]),len)<=worst(row,len)){row.push(rest[k]);k++}
  const s=row.reduce((a,r)=>a+r.a,0);if(w>=h){const cw=s/h;let yy=y;row.forEach(r=>{const ch=r.a/cw;out.push({...r,x,y:yy,w:cw,h:ch});yy+=ch});x+=cw;w-=cw}
  else{const ch=s/w;let xx=x;row.forEach(r=>{const cw=r.a/ch;out.push({...r,x:xx,y,w:cw,h:ch});xx+=cw});y+=ch;h-=ch}rest=rest.slice(k)}return out}
function tree(q){const W=400,H=280,cells=squarify(q.rows.map((r,i)=>({...r,c:r.other?OTH:COL[i]})),0,0,W,H);
 return card(q,'s4',`<div class="tm">${cells.map(r=>{const dark=['#b6f23a','#f5c451','#3fd6a4','#4cc9f0'].includes(r.c),small=r.w<70||r.h<48;
  return `<div class="${ok(q,r.label)}" style="left:${r.x/W*100}%;top:${r.y/H*100}%;width:${r.w/W*100}%;height:${r.h/H*100}%;background:${r.c};color:${dark?'#0b0b12':'#eeeef5'}" title="${esc(r.label)} ${pc(r.pct)}">${small?'':`<b>${!r.other&&r.w>=120&&ph(r.label)?`<img class="av tav" src="${ph(r.label)}" alt="">`:''}${esc(r.label)}</b>`}<span style="${small?'font-size:13px':''}">${small?esc(r.label.slice(0,4))+' ':''}${pc(r.pct)}</span></div>`}).join('')}</div>`)}
// 7. eliminator: gauge + ranking
function gauge(q){const L=q.rows[0],a1=Math.PI+Math.PI*L.pct/100;
 return card(q,'s4 elimP',`<div class="gtop"><svg viewBox="0 0 220 130" style="width:62%;max-width:230px"><path d="${arc(110,115,90,Math.PI,2*Math.PI-.0001)}" stroke="#262636" stroke-width="18" fill="none"/><path d="${arc(110,115,90,Math.PI,a1)}" stroke="#ff4d5e" stroke-width="18" fill="none" class="gp" style="filter:drop-shadow(0 0 6px rgba(255,77,94,.6))"/><text x="110" y="100" text-anchor="middle" fill="#eeeef5" font-family="Chakra Petch,sans-serif" font-weight="700" font-size="34">${pc(L.pct)}</text><text x="110" y="122" text-anchor="middle" fill="#8d8ca3" font-family="Share Tech Mono,monospace" font-size="12">${esc(L.label.toUpperCase())}</text></svg>${cut(L.label)}</div>
 <div class="rk">${q.rows.map((r,i)=>`<div class="${ok(q,r.label)}"><em>${r.other?'':'#'+(i+1)}</em>${av(r)}${esc(r.label)}<span>${pc(r.pct)}</span></div>`).join('')}</div>`)}
// 8. peak viewers: smooth distribution curve
function curve(q){const sm=innerWidth<640,n=q.rows.length,W=sm?440:1000,H=sm?320:420,pl=10,pr=10,pt=50,pb=sm?66:50,fs=sm?1.25:1,lab=l=>sm?l.replace('Under ','<').replace(/K/g,''):l.replace('Under ','<'),mx=Math.max(...q.rows.map(r=>r.pct))*1.15,
 X=i=>pl+(W-pl-pr)*(i+.5)/n,Y=v=>pt+(H-pt-pb)*(1-v/mx),P=q.rows.map((r,i)=>[X(i),Y(r.pct)]);
 let d=`M${pl} ${Y(0)}L${P[0][0]} ${P[0][1]}`;for(let i=1;i<n;i++){const [x0,y0]=P[i-1],[x1,y1]=P[i],cx=(x0+x1)/2;d+=`C${cx} ${y0} ${cx} ${y1} ${x1} ${y1}`}
 const line=d+`L${W-pr} ${Y(0)}`,top=q.rows.reduce((a,r,i)=>r.pct>q.rows[a].pct?i:a,0);
 return card(q,'s8',`<div class="cv"><svg viewBox="0 0 ${W} ${H}"><defs><linearGradient id="ag" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#4cc9f0" stop-opacity=".45"/><stop offset="1" stop-color="#4cc9f0" stop-opacity="0"/></linearGradient><clipPath id="rv"><rect class="rv" x="0" y="0" width="0" height="${H}"/></clipPath></defs>
 <g clip-path="url(#rv)"><path d="${line}Z" fill="url(#ag)"/><path d="${d}" fill="none" stroke="#4cc9f0" stroke-width="3" style="filter:drop-shadow(0 0 6px rgba(76,201,240,.7))"/></g>
 <line x1="${P[top][0]}" x2="${P[top][0]}" y1="${P[top][1]}" y2="${Y(0)}" stroke="#b6f23a" stroke-dasharray="4 4"/>
 ${q.rows.map((r,i)=>`<circle cx="${P[i][0]}" cy="${P[i][1]}" r="${i===top?7:4}" fill="${i===top?'#b6f23a':'#0b0b12'}" stroke="${i===top?'#b6f23a':'#4cc9f0'}" stroke-width="2"/><text x="${P[i][0]}" y="${P[i][1]-14}" text-anchor="middle" fill="${i===top?'#b6f23a':'#eeeef5'}" font-family="Share Tech Mono,monospace" font-size="${(i===top?20:16)*fs}">${pc(r.pct)}</text><text x="${P[i][0]}" y="${H-(sm?32:18)}" text-anchor="middle" fill="${ok(q,r.label)?'#b6f23a':'#8d8ca3'}" font-family="Share Tech Mono,monospace" font-size="${sm?13:15}">${sm&&r.label.includes('-')?`<tspan x="${P[i][0]}" dy="-8">${esc(lab(r.label.split('-')[0]))}</tspan><tspan x="${P[i][0]}" dy="15">-${esc(lab(r.label.split('-')[1]))}</tspan>`:esc(lab(r.label))}</text>`).join('')}
 <line x1="${pl}" x2="${W-pr}" y1="${Y(0)}" y2="${Y(0)}" stroke="#262636"/>${sm?`<text x="${W-pr}" y="${H-2}" text-anchor="end" fill="#8d8ca3" font-family="Share Tech Mono,monospace" font-size="11">thousands of viewers</text>`:''}</svg></div>`)}
G.innerHTML=[donut(Q('CHAMPION')),rings(Q('TOP 3')),heat(Q('BMIC')),hero(Q('TOURNAMENT MVP')),stacked(Q('FINAL MVP')),tree(Q('BEST IGL')),gauge(Q('THE ELIMINATOR')),curve(Q('PEAK VIEWERS'))].join('');
// animate in as cards scroll into view
const run=c=>{c.classList.add('in');
 c.querySelectorAll('.rg').forEach((e,i)=>{e.style.transition=`stroke-dashoffset 1.1s cubic-bezier(.2,.8,.2,1) ${i*70}ms`;requestAnimationFrame(()=>e.style.strokeDashoffset=e.dataset.off)});
 c.querySelectorAll('.stk div').forEach(e=>requestAnimationFrame(()=>e.style.flex=`${e.dataset.g} 0 0`));
 c.querySelectorAll('.rv').forEach(e=>{e.style.transition='width 1.4s ease-out';requestAnimationFrame(()=>e.setAttribute('width','2000'))});
 c.querySelectorAll('.gp').forEach(e=>{const l=e.getTotalLength();e.style.strokeDasharray=l;e.style.strokeDashoffset=l;e.getBoundingClientRect();e.style.transition='stroke-dashoffset 1.2s ease-out';e.style.strokeDashoffset=0});
 c.querySelectorAll('.seg').forEach(e=>{const l=e.getTotalLength();e.style.strokeDasharray=l;e.style.strokeDashoffset=l;e.getBoundingClientRect();e.style.transition=`stroke-dashoffset .8s ease-out ${e.style.getPropertyValue('--d')}`;e.style.strokeDashoffset=0});
 c.querySelectorAll('[data-n]').forEach(e=>{const t=+e.dataset.n,t0=performance.now();const f=n=>{const k=Math.min(1,(n-t0)/1100),v=t*(1-Math.pow(1-k,3));e.textContent=pc(k<1?Math.round(v):t);if(k<1)requestAnimationFrame(f)};requestAnimationFrame(f)})};
const io='IntersectionObserver' in window?new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){io.unobserve(e.target);run(e.target)}}),{threshold:.2}):null;
document.querySelectorAll('.c').forEach(c=>io?io.observe(c):run(c));
</script></body></html>"""
