# New tournament from the BMSD 2026 base

The BMSD 2026 site is the template. The code as it ran for the finals is kept on the branch **`bmsd-2026`** on GitHub
(`git checkout bmsd-2026` to see it exactly; never commit to that branch), and the finished site is frozen in `archive/bmsd/` (see the end).

Everything a new tournament needs is below, in the order to do it. Search the file for the text in quotes.

## 1. Tracker: what to count (`core/events.py`, `PRESETS`)

Copy the `"bmsd"` block, give it a new key (e.g. `"bgis26"`), then change:

| Field | What it is |
|---|---|
| `name` | Shown everywhere, e.g. `"BGIS 2026"` |
| `match` | Words a stream title must contain to count (lowercase) |
| `queries` | YouTube searches run every minute |
| `official` | Official channel names (lowercase) |
| `official_channels` | Official channel IDs (`UC...`). Every live stream on them is tracked (Hindi, English, map) |
| `allowed` | Watch-party streamers permitted to restream (lowercase name tokens). Everyone else is ignored |
| `always_check` | `@handles` checked directly every minute even if search misses them |
| `videos_extra` | Specific video IDs to always track |
| `next_start` | First broadcast, IST, `"YYYY-MM-DD HH:MM"` (shown as the countdown) |
| `links` | Extra links shown on the site |

Also in `core/events.py`:
- `ROSTER`: the watch-party list shown before and during the broadcast (token, display name, @handle).

Turn it on: in Telegram `/event start <key>` (or set the event active the way BMSD was).

Between days, no code change is needed:
- countdown: `sqlite3 data/agent.db "INSERT INTO kv(key,value) VALUES('event_next:<key>','\"2026-10-18 13:00\"') ON CONFLICT(key) DO UPDATE SET value=excluded.value;"`
- stop recording after the show (post-show streams don't count) until an epoch time:
  `... VALUES('event_stop:<key>','<epoch>') ...`
- Run these on the Mac with the sqlite3 command. Never write the database from another machine over a shared folder.

## 2. Site text (`core/eventpage.py`)

- `<meta name="description"`, `og:title`, `og:description`, `twitter:description`: tournament name and wording
- `"BMSD 2026 tournament peak"`: the tournament peak tile label
- `"Grand finals go live in"` / `"Grand finals continue in"`: countdown labels
- `if ev["key"] == "bmsd":` (watch-party roster): change to the new key
- `HIST` and `HNAME`: the "BGMI viewership till date" history. **Add the finished BMSD 2026 peak** as a fixed entry
  (`['BMSD','26',<peak in K>]`) and add the new event as the live one. The row whose key/year matches the current
  event is the one that updates live (search `'BMSD'&&` / `'26'` and change both).
- `"Not affiliated with or endorsed by KRAFTON"`: keep, or change for a non-KRAFTON event
- Share cards: `bmsd-${type}` file names

`core/eventlog.py`: `if ev.get("key") != "bmsd":` (Telegram NOT LIVE alert): change to the new key.

## 3. Assets (`static/`)

The `bmsd-2026` base branch keeps only `static/eventlogos/`. Team logos, team marks, player photos and the
Predict preview image are per tournament: add new ones for each event.

| Folder | Used for | Format |
|---|---|---|
| `static/eventlogos/` | History chart logos (one per event: `BMSD26.webp` etc.) | webp, transparent |
| `static/teamlogos/` | Team logos (file name = team name in capitals, letters/numbers only: `TAG.webp`, `RNTXESPORTS.webp`) | webp, transparent |
| `static/teammarks/` | Team-only marks for sponsor-prefixed logos (`iQOO \| Soul` -> just Soul) | webp |
| `static/players/` | `<Name>.webp` = cutout photo, `<Name>_h.webp` = square headshot | webp |
| `static/predict_og.png` | Link preview image for /predict | 1200x630 png |

Player photos: take the official cutout PNGs (transparent background) and crop them the same way as BMSD
(cutout = trimmed figure, 520x700 max; headshot = top of head to collar, 160x160). The crop code is in the
commit "Predict results: square headshots instead of circle crops".

## 4. Predict & Win (optional)

- `core/predict.py`: `EVENT_KEY`, and the question text in `event_spec()` ("Who will win the BMSD 2026 Grand Finals?" etc.)
- `config/predict_bmsd2026.json`: copy and edit teams, close time, peak buckets
- `core/predictpage.py` and `core/crowdpage.py`: titles and meta text ("BMSD 2026")
- `core/crowd.py`: `PLAYERS` (spelling variants per player) and `PREFIXES` (team tags typed before names)
- `.env`: `PREDICT_OPEN=1` while voting is open; `PREDICT_OPEN=0` + `PREDICT_SPLIT=1` afterwards shows the results page
- Player data stays in `exports/private/` (git-ignored). Never commit it.

## 5. Archive the finished tournament

After the last broadcast, on the Mac:

```
cd ~/my-agent && venv/bin/python scripts/archive_site.py bmsd
git add archive/bmsd && git commit -m "Archive BMSD 2026" && git push
```

`archive/bmsd/index.html` is the full tracker frozen as it ended (numbers, graphs, By day with every stream),
`predict.html` the community predictions, `data/` the public CSV/Excel exports, `days/` per-day stream data.
They open offline in any browser. Nothing private is included.
