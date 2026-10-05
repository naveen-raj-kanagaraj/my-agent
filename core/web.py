"""Reading links: web pages, PDFs and YouTube transcripts."""
import ipaddress
import re
import socket
from urllib.parse import urlparse, parse_qs

import requests

MAX_CHARS = 15000
MAX_BYTES = 5 * 1024 * 1024
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def _is_public_host(host: str) -> bool:
    """Block localhost, LAN and other private addresses so nobody can make the bot
    fetch pages from the owner's own network."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


def youtube_id(url: str):
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if host.endswith("youtu.be"):
        return p.path.strip("/").split("/")[0] or None
    if "youtube.com" in host:
        if p.path == "/watch":
            return parse_qs(p.query).get("v", [None])[0]
        m = re.match(r"^/(shorts|live|embed)/([\w-]{6,})", p.path)
        if m:
            return m.group(2)
    return None


def youtube_transcript(video_id: str) -> str:
    from youtube_transcript_api import YouTubeTranscriptApi
    api = YouTubeTranscriptApi()
    try:
        fetched = api.fetch(video_id, languages=["en", "en-IN", "hi", "ta"])
    except Exception:
        # Fall back to whatever language exists, translated to English if possible.
        tl = api.list(video_id)
        t = next(iter(tl))
        try:
            t = t.translate("en")
        except Exception:
            pass
        fetched = t.fetch()
    return " ".join(s.text for s in fetched).strip()


def _html_to_text(html: str) -> tuple:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "form", "aside", "svg"]):
        tag.decompose()
    main = soup.find("article") or soup.find("main") or soup.body or soup
    text = main.get_text("\n", strip=True)
    text = re.sub(r"\n{2,}", "\n", text)
    desc = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    if desc and desc.get("content"):
        text = desc["content"].strip() + "\n\n" + text
    return title, text


def read_url(url: str) -> str:
    url = url.strip()
    if not re.match(r"^https?://", url):
        url = "https://" + url
    host = urlparse(url).hostname or ""
    if not host or not _is_public_host(host):
        return "I can't open that address (only public websites are allowed)."

    vid = youtube_id(url)
    if vid:
        try:
            text = youtube_transcript(vid)
            return f"YouTube transcript ({len(text.split())} words):\n{text[:MAX_CHARS]}"
        except Exception as e:
            return f"No transcript available for that YouTube video ({str(e)[:120]})."

    try:
        current = url
        for _ in range(6):  # follow redirects manually, checking every hop
            r = requests.get(current, headers={"User-Agent": UA, "Accept-Language": "en"}, timeout=20,
                             stream=True, allow_redirects=False)
            if r.is_redirect or r.status_code in (301, 302, 303, 307, 308):
                nxt = requests.compat.urljoin(current, r.headers.get("location", ""))
                if not _is_public_host(urlparse(nxt).hostname or ""):
                    return "That link redirects to a private address, so I won't open it."
                current = nxt
                continue
            break
        data = b""
        for chunk in r.iter_content(65536):
            data += chunk
            if len(data) > MAX_BYTES:
                break
    except requests.RequestException as e:
        return f"Couldn't open the link: {str(e)[:150]}"

    if r.status_code >= 400:
        return f"The site returned an error ({r.status_code}). It may need a login or block bots."

    ctype = r.headers.get("content-type", "").lower()
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        try:
            import fitz
            doc = fitz.open(stream=data, filetype="pdf")
            text = "".join(page.get_text() for page in doc)
            return f"PDF ({doc.page_count} pages):\n{text[:MAX_CHARS]}"
        except Exception as e:
            return f"Couldn't read that PDF: {str(e)[:150]}"

    if "html" in ctype or "xml" in ctype or not ctype:
        title, text = _html_to_text(data.decode(r.encoding or "utf-8", errors="ignore"))
        if len(text) < 200:
            return (f"Title: {title}\nThe page had almost no readable text. It probably needs a login "
                    f"(common for LinkedIn, Instagram and X) or loads with JavaScript.\n{text}")
        return f"Title: {title}\nURL: {r.url}\n\n{text[:MAX_CHARS]}"

    if ctype.startswith("text/"):
        return data.decode("utf-8", errors="ignore")[:MAX_CHARS]
    return f"That link is a {ctype or 'binary'} file, which I can't read."
