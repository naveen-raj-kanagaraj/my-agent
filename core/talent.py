"""Talent agency tracker (owner only): creators, deals and the pipeline.

Stages: lead -> pitched -> negotiating -> signed -> live -> paid (or lost).
Creator status: prospect, contacted, in talks, signed, passed.
"""
import os
from datetime import datetime, timedelta, timezone

from core import store

STAGES = ["lead", "pitched", "negotiating", "signed", "live", "paid", "lost"]
CREATOR_STATUSES = ["prospect", "contacted", "in talks", "signed", "passed"]
WEEKLY_TIME = os.getenv("PIPELINE_WEEKLY_TIME", "09:00")  # Mondays, owner's local time
STALE_DAYS = 7


def _age_days(ts: str) -> int:
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(ts.replace("Z", "+00:00"))).days
    except Exception:
        return 0


def save_creator(name: str, **fields) -> str:
    if not name.strip():
        return "Need the creator's name."
    if fields.get("status") and fields["status"].lower() not in CREATOR_STATUSES:
        fields["status"] = fields["status"].lower()
    cid, created = store.upsert_creator(name, **fields)
    return f"{'Added' if created else 'Updated'} creator {name} (#{cid})."


def creator_line(c: dict) -> str:
    bits = [c["name"]]
    for k in ("platform", "handle", "followers", "niche", "rate", "status"):
        if c.get(k):
            bits.append(f"{k}: {c[k]}")
    if c.get("contact"):
        bits.append(f"contact: {c['contact']}")
    line = " | ".join(bits)
    if c.get("notes"):
        line += f"\n   notes: {c['notes'][-300:]}"
    return line


def find(query: str = "", status: str = "") -> str:
    rows = store.find_creators(query, status)
    if not rows:
        return "No creators matched."
    return "\n".join(f"#{c['id']} " + creator_line(c) for c in rows)


def save_deal(creator: str, brand: str, deal_id: int = None, **fields) -> str:
    if fields.get("stage"):
        fields["stage"] = fields["stage"].lower().strip()
        if fields["stage"] not in STAGES:
            return f"Stage must be one of: {', '.join(STAGES)}."
    if not deal_id and not (creator and brand):
        return "Need the creator and brand (or a deal ID to update)."
    did, created = store.upsert_deal(creator or "", brand or "", deal_id, **fields)
    return f"{'Added' if created else 'Updated'} deal #{did}."


def deal_line(d: dict) -> str:
    s = f"#{d['id']} {d['creator']} x {d['brand']} [{d['stage']}]"
    if d.get("value"):
        s += f" {d['value']}"
    if d.get("due"):
        s += f", due {d['due']}"
    age = _age_days(d["updated_at"])
    if age >= STALE_DAYS and d["stage"] not in ("paid", "lost"):
        s += f" (no update in {age} days)"
    if d.get("notes"):
        s += f"\n   {d['notes'][-200:]}"
    return s


def pipeline_text() -> str:
    deals = store.all_deals()
    creators = store.all_creators()
    if not deals and not creators:
        return ("Your pipeline is empty. Tell me things like: 'add creator Riya, 250K on Instagram, beauty, ₹40K per "
                "reel' or 'new deal: Riya x Mamaearth, ₹1.2L, pitched, due Oct 20'.")
    out = []
    if deals:
        out.append(f"OPEN DEALS ({len(deals)})")
        for stage in STAGES[:-2]:
            ds = [d for d in deals if d["stage"] == stage]
            if ds:
                out.append(f"\n{stage.upper()}")
                out += [deal_line(d) for d in ds]
        today = datetime.now().date()
        due = []
        for d in deals:
            try:
                dd = datetime.fromisoformat(d["due"]).date()
                if dd <= today + timedelta(days=7):
                    due.append((dd, d))
            except Exception:
                pass
        if due:
            out.append("\nDUE WITHIN 7 DAYS")
            out += [f"{dd:%b %d}: #{d['id']} {d['creator']} x {d['brand']}" for dd, d in sorted(due, key=lambda x: x[0])]
        stale = [d for d in deals if _age_days(d["updated_at"]) >= STALE_DAYS]
        if stale:
            out.append(f"\nNEEDS A FOLLOW-UP ({len(stale)} untouched for {STALE_DAYS}+ days)")
            out += [f"#{d['id']} {d['creator']} x {d['brand']}" for d in stale]
    if creators:
        counts = {}
        for c in creators:
            counts[c.get("status") or "prospect"] = counts.get(c.get("status") or "prospect", 0) + 1
        out.append("\nCREATORS: " + ", ".join(f"{v} {k}" for k, v in counts.items()))
    return "\n".join(out)


def send_weekly(send):
    deals = store.all_deals()
    if not deals and not store.all_creators():
        return
    send("WEEKLY PIPELINE\n\n" + pipeline_text())
