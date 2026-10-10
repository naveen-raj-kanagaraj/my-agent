"""Act for people without touching their accounts: the bot writes the email / event / message and gives buttons that
open it, pre-filled, in their own Gmail, Outlook, Google Calendar, Apple Calendar (.ics) or WhatsApp. They press
send themselves. Nothing is stored and no login is needed.
"""
import os
import re
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode

from core import context, store

MAX_URL = 1900          # keep button links comfortably inside URL limits


def _clip(text: str, room: int) -> tuple:
    """Shorten text so the URL fits; returns (text, was_cut)."""
    text = text or ""
    if len(quote(text)) <= room:
        return text, False
    cut = text
    while cut and len(quote(cut + "…")) > room:
        cut = cut[: int(len(cut) * 0.9)]
    return cut.rstrip() + "…", True


def _button(label: str, url: str):
    context.get().buttons.append((label, url))


def compose_email(to: str = "", subject: str = "", body: str = "", cc: str = "", bcc: str = "") -> str:
    to = ",".join(a.strip() for a in re.split(r"[,;\s]+", to or "") if a.strip())
    base_g = "https://mail.google.com/mail/?" + urlencode({"view": "cm", "fs": "1", "to": to, "cc": cc, "bcc": bcc,
                                                            "su": subject}, quote_via=quote)
    body_g, cut = _clip(body, MAX_URL - len(base_g) - 8)
    _button("Open in Gmail", base_g + "&body=" + quote(body_g))
    base_o = "https://outlook.live.com/mail/0/deeplink/compose?" + urlencode(
        {"to": to, "cc": cc, "subject": subject}, quote_via=quote)
    body_o, _ = _clip(body, MAX_URL - len(base_o) - 8)
    _button("Open in Outlook", base_o + "&body=" + quote(body_o))
    note = (" The email is long, so the buttons carry a shortened body: paste the full text from my message."
            if cut else "")
    return ("Draft ready. Buttons 'Open in Gmail' and 'Open in Outlook' will appear under your reply; they open the "
            "person's own mail app with this filled in and they press send." + note +
            " In your reply, show the subject and the full email text so they can read or copy it.")


def _parse_when(s: str, tz) -> datetime:
    s = (s or "").strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=tz)


def calendar_event(title: str, start: str, end: str = "", location: str = "", details: str = "",
                   all_day: bool = False) -> str:
    ctx = context.get()
    tz = store.user_tz(store.get_user(ctx.uid) or {})
    try:
        st = _parse_when(start, tz)
        en = _parse_when(end, tz) if end else st + (timedelta(days=1) if all_day else timedelta(hours=1))
    except ValueError:
        return "I need the start time as an ISO date-time, like 2026-10-16T13:00 (in the user's timezone)."
    if en <= st:
        en = st + timedelta(hours=1)
    utc = lambda d: d.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dates = f"{st:%Y%m%d}/{en:%Y%m%d}" if all_day else f"{utc(st)}/{utc(en)}"
    det, _ = _clip(details, 900)
    g = "https://calendar.google.com/calendar/render?" + urlencode(
        {"action": "TEMPLATE", "text": title, "dates": dates, "details": det, "location": location}, quote_via=quote)
    _button("Add to Google Calendar", g)
    o = "https://outlook.live.com/calendar/0/deeplink/compose?" + urlencode(
        {"subject": title, "startdt": st.isoformat(), "enddt": en.isoformat(), "location": location, "body": det,
         "allday": "true" if all_day else "false", "path": "/calendar/action/compose", "rru": "addevent"},
        quote_via=quote)
    _button("Add to Outlook", o)
    # .ics file: opens in Apple Calendar on iPhone/Mac, and in most calendar apps
    esc = lambda t: (t or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    ics = "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//assistant//EN", "BEGIN:VEVENT", f"UID:{uuid.uuid4()}",
        f"DTSTAMP:{utc(datetime.now(timezone.utc))}",
        (f"DTSTART;VALUE=DATE:{st:%Y%m%d}" if all_day else f"DTSTART:{utc(st)}"),
        (f"DTEND;VALUE=DATE:{en:%Y%m%d}" if all_day else f"DTEND:{utc(en)}"),
        f"SUMMARY:{esc(title)}", f"LOCATION:{esc(location)}", f"DESCRIPTION:{esc(details)}",
        "END:VEVENT", "END:VCALENDAR", ""])
    name = re.sub(r"[^A-Za-z0-9 _-]", "", title)[:40].strip().replace(" ", "_") or "event"
    path = os.path.join(tempfile.mkdtemp(), name + ".ics")
    with open(path, "w", newline="") as f:  # calendar files need CRLF line endings
        f.write(ics)
    ctx.outbox.append({"kind": "document", "path": path, "caption": "Tap to add to Apple Calendar or any calendar app"})
    when = st.strftime("%a %d %b, %I:%M %p") if not all_day else st.strftime("%a %d %b (all day)")
    return (f"Event ready: '{title}', {when} ({tz.key}). Buttons for Google Calendar and Outlook, plus an .ics file "
            "for Apple Calendar, will be sent with your reply. Confirm the details in one or two lines.")


def whatsapp_message(text: str, phone: str = "") -> str:
    digits = re.sub(r"\D", "", phone or "")
    base = f"https://wa.me/{digits}?text=" if digits else "https://api.whatsapp.com/send?text="
    t, cut = _clip(text, MAX_URL - len(base))
    _button("Send on WhatsApp" if digits else "Share on WhatsApp", base + quote(t))
    return ("WhatsApp button ready: it opens WhatsApp with the message filled in" +
            (" for that number" if digits else "; they pick the chat") + ". Show the message in your reply." +
            (" It was long, so the button carries a shortened version." if cut else ""))
