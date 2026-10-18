"""Freeze a finished tournament's site into archive/<event>/ so it can be kept in the repo and opened offline.

    venv/bin/python scripts/archive_site.py            # current event (bmsd)
    venv/bin/python scripts/archive_site.py bmsd

Writes:
  archive/<event>/index.html        the live tracker as a self-contained snapshot (all numbers, graphs, by-day data)
  archive/<event>/predict.html      "What the community predicted" with logos and player photos embedded
  archive/<event>/data/*.csv|xlsx   the public viewership exports (never the private Predict & Win player files)
  archive/<event>/days/<date>.json  every stream and watch party per day (what "By day" shows when tapped)

Run it after the last broadcast, then commit archive/<event>/ (nothing in it is private).
"""
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import dataexport, eventpage, events  # noqa: E402


def main(key: str = "bmsd"):
    ev = events.get(key)
    if not ev:
        sys.exit(f"No event '{key}'.")
    out = os.path.join(ROOT, "archive", key)
    os.makedirs(os.path.join(out, "data"), exist_ok=True)
    os.makedirs(os.path.join(out, "days"), exist_ok=True)

    st = events.stats(key)
    days = {}
    for d in st.get("days", []):
        if d.get("peak_at"):
            date = events.datetime.fromtimestamp(d["peak_at"], events.REPORT_TZ).strftime("%Y-%m-%d")
            days[date] = events.day_streams(key, date)
    page = eventpage.build_html(key, live=False).replace("const DAYC={};", "const DAYC=" + json.dumps(days).replace("</", "<\\/") + ";", 1)
    with open(os.path.join(out, "index.html"), "w") as f:
        f.write(page)
    print("index.html")

    if key == "bmsd":
        from core import crowdpage
        with open(os.path.join(out, "predict.html"), "w") as f:
            f.write(crowdpage.build_html(embed_logos=True))
        print("predict.html")

    dataexport.viewership(key)
    src = os.path.join(ROOT, "exports", key)
    for name in ("viewership_2min.csv", "streams_2min.csv", "daily_peaks.csv", "viewership.xlsx"):
        if os.path.isfile(os.path.join(src, name)):
            shutil.copy2(os.path.join(src, name), os.path.join(out, "data", name))
            print("data/" + name)

    for date, j in days.items():
        with open(os.path.join(out, "days", f"{date}.json"), "w") as f:
            json.dump(j, f, indent=1)
        print(f"days/{date}.json")
    print(f"Done: {out}")


if __name__ == "__main__":
    main(*(sys.argv[1:2] or ["bmsd"]))
