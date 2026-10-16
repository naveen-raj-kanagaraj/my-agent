# Predict & Win (BMSD 2026 Grand Finals)

Free, points-only prediction game at `live.letsgrowesports.com/predict`.

- **Code:** `core/predict.py` (game logic), `core/predictpage.py` (public page + admin page), routes in `platforms/eventweb.py` (public) and `platforms/dashboard.py` (admin, this computer only).
- **Setup data:** `config/predict_bmsd2026.json` (teams, days, close time, peak ranges, prize text, rules, rollout order).
- **Team logos:** `static/teamlogos/*.webp` (light versions, file name = team name in capitals without spaces).
- **Previews (sample data, open in any browser):** `docs/previews/predict-and-win-preview.html`, `docs/previews/live-tracker-preview.html`.
- **Tests:** `python -m unittest tests.test_predict`.

## Roll out
1. `bash scripts/autostart.sh restart`
2. Create questions, either way:
   - admin page `http://localhost:8090/predict`: **Create tournament questions**, then **Create day questions** (Day 1), or
   - `python scripts/predict_setup.py config/predict_bmsd2026.json`
3. Test on your phone at `/predict`, then delete the test player in the admin page.
4. Add `PREDICT_OPEN=1` to `.env` and restart to show the banner on the live site.
5. Next days: `python scripts/predict_setup.py config/predict_bmsd2026.json --day 2` (then `--day 3`).
6. Settle each question in the admin page as results come in. Peak viewers settles itself 30 minutes after the stream ends.

## Rules that matter
- Picks save automatically and can't be changed (enforced by the server).
- Top 3 is ranked by tap order (#1, #2, #3); points are given per correct team.
- Public data never shows the number of players, only percentages and the top 10.
- Player data (Instagram IDs, picks) stays in `data/agent.db` on the Mac. It is never committed.

## Data for analysis
The tracker rewrites these every 10 minutes (or run `python3 scripts/export_data.py`):
- `exports/bmsd/viewership_2min.csv`: total, official, watch parties, community every 2 minutes while the official stream is live, plus the highest total inside each 2-minute window.
- `exports/bmsd/streams_2min.csv`: every live stream's viewers every 2 minutes.
- `exports/bmsd/daily_peaks.csv`: peak, peak time, official/watch-party split, average, per day.
- `exports/bmsd/viewership.xlsx`: the three tables as sheets.
- `exports/predict/questions.csv`: questions, answers and the crowd split.
- `exports/private/`: Predict & Win players and picks (Instagram IDs). Git-ignored; never pushed to the public repo.
