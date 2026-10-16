"""Analysis-ready exports, written inside the repo folder so the data lives with the code.

exports/<event>/            public YouTube numbers (safe to push to GitHub)
  viewership_2min.csv       one row every 2 minutes while the official stream was live
  streams_2min.csv          every live stream's viewers every 2 minutes (long format)
  daily_peaks.csv           per day: peak, time, official/watch-party split, average
  viewership.xlsx           the three tables above as sheets (if openpyxl is installed)
exports/predict/questions.csv   Predict & Win questions, answers, crowd split (no player data)
exports/private/            Predict & Win players and picks (Instagram IDs): git-ignored, never pushed

Only sqlite3 and the standard library are needed, so this also runs from a plain `python3`.
"""
import csv
import json
import os
import time
from datetime import datetime, timedelta, timezone

from core import store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "exports")
IST = timezone(timedelta(hours=5, minutes=30))
STEP = 120          # seconds per row
EVERY = 600         # regenerate at most this often from the live loop
_last = {}


def _t(ts):
    return datetime.fromtimestamp(ts, IST)


def _write(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    os.replace(tmp, path)


def viewership(key: str) -> dict:
    db = store.conn()
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='ev_ticks'").fetchone():
        return {"rows_2min": 0}
    with store._lock:
        ticks = db.execute("SELECT ts, total, official, watch, community FROM ev_ticks WHERE event=? ORDER BY ts",
                           (key,)).fetchall()
        streams = {r["vid"]: dict(r) for r in db.execute(
            "SELECT vid, channel, title, kind FROM ev_streams WHERE event=?", (key,))}
        fine = db.execute("SELECT 1 FROM sqlite_master WHERE name='ev_fine'").fetchone()
        samples = db.execute("SELECT ts, vid, viewers FROM ev_samples WHERE event=? ORDER BY ts", (key,)).fetchall()
        if fine:   # full-resolution readings exist from the finals on: use them, older days fall back to ev_samples
            fs = db.execute("SELECT ts, vid, viewers FROM ev_fine WHERE event=? ORDER BY ts", (key,)).fetchall()
            if fs:
                first = fs[0]["ts"]
                samples = [x for x in samples if x["ts"] < first] + list(fs)
    out_dir = os.path.join(OUT, key)
    # 2-minute rows: the reading at the end of each window, plus the highest total inside it
    rows, cur, hi = [], None, 0
    for t in ticks:
        b = int(t["ts"]) // STEP
        if cur is not None and b != cur[0]:
            rows.append(cur[1] + [hi])
            hi = 0
        tm = _t(int(t["ts"]))
        cur = (b, [tm.strftime("%Y-%m-%d"), tm.strftime("%H:%M:%S"), int(t["ts"]), t["total"], t["official"],
                   t["watch"], t["community"]])
        hi = max(hi, t["total"])
    if cur:
        rows.append(cur[1] + [hi])
    head = ["date_ist", "time_ist", "unix_ts", "total_viewers", "official", "watch_parties", "community",
            "max_total_in_2min"]
    _write(os.path.join(out_dir, "viewership_2min.csv"), head, rows)
    # streams: last reading per stream per 2-minute window
    last = {}
    for s in samples:
        last[(int(s["ts"]) // STEP, s["vid"])] = s
    srows = []
    for (b, vid), s in sorted(last.items()):
        st = streams.get(vid, {})
        tm = _t(int(s["ts"]))
        srows.append([tm.strftime("%Y-%m-%d"), tm.strftime("%H:%M:%S"), int(s["ts"]), st.get("channel", ""),
                      st.get("kind", ""), vid, s["viewers"], st.get("title", "")])
    shead = ["date_ist", "time_ist", "unix_ts", "channel", "kind", "video_id", "viewers", "title"]
    _write(os.path.join(out_dir, "streams_2min.csv"), shead, srows)
    # every reading (about every 2 seconds), one file per day
    byday = {}
    for x in samples:
        tm = _t(int(x["ts"]))
        st = streams.get(x["vid"], {})
        byday.setdefault(tm.strftime("%Y-%m-%d"), []).append(
            [tm.strftime("%H:%M:%S"), int(x["ts"]), st.get("channel", ""), st.get("kind", ""), x["vid"], x["viewers"]])
    for day, r in byday.items():
        _write(os.path.join(out_dir, "full", f"streams_{day}.csv"),
               ["time_ist", "unix_ts", "channel", "kind", "video_id", "viewers"], r)
    tday = {}
    for t in ticks:
        tm = _t(int(t["ts"]))
        tday.setdefault(tm.strftime("%Y-%m-%d"), []).append(
            [tm.strftime("%H:%M:%S"), int(t["ts"]), t["total"], t["official"], t["watch"], t["community"]])
    for day, r in tday.items():
        _write(os.path.join(out_dir, "full", f"viewership_{day}.csv"),
               ["time_ist", "unix_ts", "total_viewers", "official", "watch_parties", "community"], r)
    # daily peaks
    days = {}
    for t in ticks:
        d = _t(int(t["ts"])).strftime("%Y-%m-%d")
        x = days.setdefault(d, {"peak": 0, "at": 0, "off": 0, "wp": 0, "sum": 0, "n": 0, "op": 0, "wpk": 0})
        if t["total"] > x["peak"]:
            x.update(peak=t["total"], at=int(t["ts"]), off=t["official"], wp=t["watch"])
        x["op"] = max(x["op"], t["official"])
        x["wpk"] = max(x["wpk"], t["watch"])
        x["sum"] += t["total"]
        x["n"] += 1
    drows = [[d, x["peak"], _t(x["at"]).strftime("%H:%M:%S") if x["at"] else "", x["off"], x["wp"], x["op"], x["wpk"],
              round(x["sum"] / x["n"]) if x["n"] else 0] for d, x in sorted(days.items())]
    dhead = ["date_ist", "peak_total", "peak_time_ist", "official_at_peak", "watch_parties_at_peak",
             "official_peak", "watch_parties_peak", "average_total"]
    _write(os.path.join(out_dir, "daily_peaks.csv"), dhead, drows)
    try:
        from openpyxl import Workbook
        wb = Workbook()
        for i, (name, h, r) in enumerate([("Every 2 min", head, rows), ("Streams every 2 min", shead, srows),
                                          ("Daily peaks", dhead, drows)]):
            ws = wb.active if i == 0 else wb.create_sheet()
            ws.title = name
            ws.append(h)
            for row in r:
                ws.append(row)
            ws.freeze_panes = "A2"
        wb.save(os.path.join(out_dir, "viewership.xlsx"))
    except ImportError:
        pass
    return {"rows_2min": len(rows), "stream_rows": len(srows), "days": len(drows), "dir": out_dir}


def predict_data() -> dict:
    try:
        from core import predict
    except Exception:
        return {}
    qs = predict.questions()
    st = predict._qstats({q["id"]: q for q in qs})
    qrows = []
    for q in qs:
        s = st.get(q["id"]) or {"n": 0, "inc": {}, "names": {}}
        split = {s["names"].get(k, k): v for k, v in s["inc"].items()} if q["kind"] == "text" else s["inc"]
        qrows.append([q["id"], q["kind"], q["tag"], q["title"], _t(q["close_ts"]).strftime("%Y-%m-%d %H:%M"),
                      ", ".join(predict.ans_list(q)), "yes" if q["void"] else "", s["n"], json.dumps(split)])
    _write(os.path.join(OUT, "predict", "questions.csv"),
           ["id", "kind", "tag", "question", "closes_ist", "answer", "void", "players_answered", "picks_by_option"], qrows)
    with store._lock:
        players = store.conn().execute("SELECT id, handle, name, created, hidden FROM pw_players ORDER BY created").fetchall()
        picks = store.conn().execute("SELECT player_id, qid, option, ts FROM pw_picks ORDER BY ts").fetchall()
    _, sc, _, _ = predict._scores()
    priv = os.path.join(OUT, "private")
    _write(os.path.join(priv, "predict_players.csv"), ["id", "instagram", "name", "joined_ist", "hidden", "points", "correct"],
           [[p["id"], p["handle"], p["name"], _t(p["created"]).strftime("%Y-%m-%d %H:%M:%S"), p["hidden"],
             sc.get(p["id"], {}).get("all", [0, 0])[0], sc.get(p["id"], {}).get("all", [0, 0])[1]] for p in players])
    _write(os.path.join(priv, "predict_picks.csv"), ["player_id", "question_id", "pick", "time_ist"],
           [[k["player_id"], k["qid"], k["option"], _t(k["ts"]).strftime("%Y-%m-%d %H:%M:%S")] for k in picks])
    return {"questions": len(qrows), "players": len(players), "picks": len(picks)}


def tick(ev: dict, force: bool = False):
    """Called every minute from the tracker loop; regenerates the files every 10 minutes."""
    key = ev["key"]
    if not force and time.time() - _last.get(key, 0) < EVERY:
        return
    _last[key] = time.time()
    viewership(key)
    if key == "bmsd":
        predict_data()
