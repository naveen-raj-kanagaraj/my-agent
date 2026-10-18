"""Public "community predictions" split for the live site: what share of Predict & Win players picked each option.

Only percentages leave this module (no player names, IDs or counts). Typed answers (MVP, IGL, Eliminator) are
grouped: team prefixes, spelling variants and nicknames of the same player count as one name.
"""
import difflib
import re
import time

from core import predict

# canonical display name -> spellings seen (compared after removing team prefixes, spaces and symbols)
PLAYERS = {
    "Ninjaboi": ["ninjaboi", "ninjaboy", "ninjaboii", "ninjaboiii", "nijaboi", "nijaboy", "ninjabio", "ninzaboi",
                 "ningaboi", "ningaboy", "ninjboi", "ninja", "ninjaboyy"],
    "Hydro": ["hydro", "hydroo", "haydro", "hudro", "hydro8"],
    "Jonathan": ["jonathan", "johnathan", "jonthan", "jonathon", "jonathangaming", "jonathanamaral", "jonathan16"],
    "Legit": ["legit", "ligit", "legitt"],
    "Spower": ["spower", "spowerr"],
    "Hunterz": ["hunterz", "hunterzz", "hunterzzz", "hunter", "hunters", "hunterss"],
    "Goblin": ["goblin"],
    "Justin": ["justin"],
    "Sarang": ["sarang"],
    "Taurus": ["taurus", "tauras", "tarus", "touras", "tarous", "tauruss", "taurous", "torous", "taurus06"],
    "Slug": ["slug"],
    "Joker": ["joker"],
    "Pain": ["pain"],
    "Admino": ["admino"],
    "Trace": ["trace", "tracegod"],
    "Harsh": ["harsh"],
    "Knight": ["knight"],
    "Kratos": ["kratos"],
    "Knowme": ["knowme"],
    "Phoenix": ["phoenix", "pheonix"],
    "Shubh": ["shubh", "subh"],
    "Spraygod": ["spraygod"],
    "Jelly": ["jelly", "jally", "jilly", "jellythemonster", "jeelly"],
    "Nakul": ["nakul", "naku"],
    "Omega": ["omega", "omegaa", "omaga"],
    "Aadi": ["aadi", "adi", "adii", "aadii", "adiii", "aadiii", "addi"],
    "Manya": ["manya", "manyaa"],
    "Neyo": ["neyo", "neyoo", "neyooo"],
    "Areeb": ["areeb"],
    "Juicy": ["juicy", "juice"],
    "Saumraj": ["saumraj", "somraj"],
    "Gravity": ["gravity"],
    "Punk": ["punk", "punkk"],
    "Ninjajod": ["ninjajod"],
    "Shadow": ["shadow", "shadow7"],
    "Detrox": ["detrox"],
    "Eggy": ["eggy"],
    "Sensei": ["sensei"],
}
# team names / sponsors people type in front of a player's name
PREFIXES = sorted(["iqoosoul", "iqoorntx", "iqoo", "soul", "tag", "outrage", "or", "gdr", "godlike", "godl", "k9",
                   "8bit", "nebula", "rntx", "genesis", "gens", "gen", "blitz", "eg", "wf", "myth", "metaninza",
                   "team"], key=len, reverse=True)
_LOOK = {s: name for name, ss in PLAYERS.items() for s in ss}
_CACHE = {}


def canon(raw: str) -> str:
    k = re.sub(r"[^a-z0-9]", "", str(raw or "").lower().replace("×", "x"))
    for _ in range(2):
        for p in PREFIXES:
            if k.startswith(p) and len(k) > len(p) + 2:
                k = k[len(p):]
                k = k[1:] if k.startswith("x") and len(k) > 3 and k[1:] in _LOOK else k
                break
    if k in _LOOK:
        return _LOOK[k]
    k2 = re.sub(r"\d+$", "", k)
    if k2 in _LOOK:
        return _LOOK[k2]
    m = difflib.get_close_matches(k2 or k, list(_LOOK), n=1, cutoff=0.84)
    if m:
        return _LOOK[m[0]]
    return (str(raw).strip()[:20] or "?").title()


def split(top: int = 6, all_teams: bool = False) -> dict:
    """{'questions': [{tag, title, kind, rows: [{label, pct}], note}]}; cached for 60s."""
    ck = (top, all_teams)
    hit = _CACHE.get(ck)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    qs = {q["id"]: q for q in predict.questions()}
    st = predict._qstats(qs)
    out = []
    for q in sorted(qs.values(), key=lambda q: q["id"]):
        s = st.get(q["id"]) or {}
        n = s.get("n", 0)
        if not n:
            continue
        inc = s.get("inc", {})
        if q["kind"] == "text":
            agg = {}
            for k, v in inc.items():
                name = canon(s["names"].get(k, k))
                agg[name] = agg.get(name, 0) + v
            ranked = sorted(agg.items(), key=lambda x: -x[1])
            rows = [{"label": k, "pct": round(100 * v / n, 1)} for k, v in ranked[:top]]
            rest = sum(v for _, v in ranked[top:])
            if rest:
                rows.append({"label": "Others", "pct": round(100 * rest / n, 1), "other": True})
            note = "share of all picks"
        elif q["kind"] == "peak":
            order = q.get("options") or list(inc)
            rows = [{"label": o, "pct": round(100 * inc.get(o, 0) / n, 1)} for o in order]
            note = "share of all picks"
        else:
            ranked = sorted(inc.items(), key=lambda x: -x[1])
            lim = 99 if (all_teams and q["kind"] == "multi") else \
                {"multi": 8 if int((q.get("meta") or {}).get("pick", 3)) > 3 else 6}.get(q["kind"], top)
            rows = [{"label": k, "pct": round(100 * v / n, 1), "team": True} for k, v in ranked[:lim]]
            if q["kind"] != "multi":
                rest = sum(v for _, v in ranked[lim:])
                if rest:
                    rows.append({"label": "Others", "pct": round(100 * rest / n, 1), "other": True})
                note = "share of all picks"
            else:
                note = f"% of players who put them in their {(q.get('meta') or {}).get('pick', 3)}"
        out.append({"tag": q["tag"], "title": q["title"], "kind": q["kind"], "rows": rows, "note": note,
                    "answer": (_canon_answer(predict.ans_list(q)) if q["kind"] == "text" else predict.ans_list(q))
                    if q.get("answer") else []})
    data = {"questions": out, "ts": int(time.time()), "winners": winners(), "peak_actual": predict.settings().get("peak_actual", ""),
            "podium": predict.settings().get("podium", [])}
    _CACHE[ck] = (time.time(), data)
    return data


def winners(n: int = 10) -> list:
    """Top players once the owner has turned the leaderboard on (Instagram handle and points only)."""
    if not predict.settings().get("show_leaderboard"):
        return []
    players, sc, _, _ = predict._scores()
    return [{"rank": r["rank"], "handle": r["handle"], "pts": r["pts"], "correct": r["correct"]}
            for r in predict._ranked(players, sc, "all")[:n] if r["pts"] > 0]


def _canon_answer(accepted: list) -> list:
    """Accepted spellings -> the player's display name (misspellings collapse into the known name)."""
    names = {canon(a) for a in accepted}
    known = sorted(n for n in names if n in PLAYERS)
    return known or sorted(names)[:1]
