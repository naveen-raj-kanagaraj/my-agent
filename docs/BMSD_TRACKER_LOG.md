# BMSD live viewership tracker: build log

Public page: https://live.letsgrowesports.com (owner visitors page: http://localhost:8090/visitors)

## What it does
- Finds BMSD YouTube streams every 60s (search plus direct checks of known channels).
- Counts every live stream from YouTube's own live counter every 2s (falls back to the watch page; slows itself down if YouTube refuses).
- Counts only official KRAFTON INDIA ESPORTS streams plus permitted watch parties: Snax Gaming, Neyoo Gaming, LoLzZz Gaming, ZGOD Gaming.
- Records only while an official stream is live. When official is offline, the page shows the last broadcast.
- Saves every reading (totals every 2s, per stream every 30s), each stream's peak, the peak split and each day's peak.

## Timeline (Oct 2026)
- 11 Oct: Switched from search-result counts (lagging, 208K vs 237K) to the per-stream live counter.
- 11 Oct: Live-only list, concurrent viewers only, dashboard + Telegram /event.
- 12 Oct: Fixed 2.5M bug (ended streams report total views); cleaned history; official-live-only recording.
- 12 Oct: Public link via Cloudflare tunnel on live.letsgrowesports.com (domain moved to Cloudflare DNS).
- 12 Oct: Built for traffic: 2 KB updates, CDN caching, gzip, production server.
- 12 Oct: Heartbeat graph, then event theme; tabs: Total, Official vs watch parties, Watch party battle.
- 12 Oct: Visitor counting without cookies or IPs (/event visitors, localhost:8090/visitors).
- 12 Oct: Share cards (day peak, watching now, split, leaders) for Instagram and X, 3x resolution.
- 12 Oct: Allow-list of watch parties; history purged of other streams; channel logos.
- 12 Oct: Fixed frozen graph (Cloudflare 4h browser cache) and stale first load.
- 12 Oct: Blinking LIVE badge; spreadsheet export; automatic broadcast log.

## Logs and exports
- /event export in Telegram: spreadsheet (summary, by day, broadcasts, every stream's peak, watch parties, per-minute readings).
- Automatic: 45 min after a broadcast ends, the bot sends the day's summary and the spreadsheet on Telegram and saves both in data/logs/.

## Known limits
- YouTube only (Esports Charts covers all platforms, so its totals are higher).
- Runs on the owner's Mac until moved to Oracle (scripts/deploy_oracle.sh); offline Mac = no readings.
- Cloudflare setting needed: Caching > Configuration > Browser Cache TTL = Respect Existing Headers.
