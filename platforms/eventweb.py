"""Public, read-only live dashboard for the tracked event (only public YouTube numbers, nothing about users).

Runs on its own port (EVENT_WEB_PORT, default 8092, this computer only) so the owner dashboard on 8090 is never
exposed. core/tunnel.py gives it a public https link that opens on any device.
"""
import gzip
import json
import logging
import os
import threading
import time
import queue

from flask import Flask, Response, request

from core import eventpage, predict, predictpage, visitors

PORT = int(os.getenv("EVENT_WEB_PORT", "8092"))
app = Flask(__name__)


CACHE = {"/": 5, "/data": 2, "/series": 60, "/predict": 30, "/predict/api/board": 5, "/predict/og.png": 3600}   # seconds Cloudflare (or any CDN) may reuse a response



@app.before_request
def _predict_closed():
    # Predict & Win is off the public site unless PREDICT_OPEN=1. Players' data stays in the database and the
    # 10-minute exports (exports/predict, exports/private); only the pages and API are hidden.
    if request.path.startswith("/predict") and os.getenv("PREDICT_OPEN", "0") != "1":
        if os.getenv("PREDICT_SPLIT", "1") == "1" and request.method == "GET":
            if request.path in ("/predict", "/predict/"):      # the game is closed: show what the community predicted
                from core import crowdpage
                try:
                    r = _memo("/predict-results", 60, crowdpage.build_html, "text/html")
                except Exception as e:
                    print(f"Predict results page failed: {str(e)[:150]}")
                    return Response("Not found", status=404, mimetype="text/plain")
                r.headers["Cache-Control"] = "public, max-age=30, s-maxage=30"
                return r
            if request.path == "/predict/og.png":
                return None
        return Response("Not found", status=404, mimetype="text/plain")

@app.after_request
def _headers(resp):
    secs = CACHE.get(request.path)
    if request.path.startswith("/predict/api/profile/") and request.method == "GET":
        secs = 15
    if request.method != "GET" or resp.status_code >= 400:
        secs = None                       # POSTs, personal and error responses are never cached
    if request.path.startswith(("/elogo/", "/tlogo/")):
        return resp
    resp.headers["Cache-Control"] = f"public, max-age={secs}, s-maxage={secs}" if secs else "no-store"
    if secs:   # Cloudflare's Browser Cache TTL can override max-age; this one it passes through for its own cache
        resp.headers["CDN-Cache-Control"] = f"max-age={secs}"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    if (resp.status_code == 200 and not resp.direct_passthrough and "Content-Encoding" not in resp.headers and "gzip" in request.headers.get("Accept-Encoding", "")
            and len(resp.get_data()) > 1024):
        resp.set_data(gzip.compress(resp.get_data(), 5))
        resp.headers["Content-Encoding"] = "gzip"
        resp.headers["Vary"] = "Accept-Encoding"
    return resp


# ---- in-memory response cache: thousands of viewers poll the same numbers, so each response is built once
# per TTL (one thread builds it, the rest wait for that copy) and handed out as ready-made gzip bytes.
_MEMO, _MLOCK = {}, {}


def _memo(key, ttl, build, mimetype):
    hit = _MEMO.get(key)
    if not (hit and time.time() - hit[0] < ttl):
        lock = _MLOCK.setdefault(key, threading.Lock())
        with lock:
            hit = _MEMO.get(key)
            if not (hit and time.time() - hit[0] < ttl):
                body = build()
                if isinstance(body, str):
                    body = body.encode()
                hit = (time.time(), body, gzip.compress(body, 5) if len(body) > 1024 else None)
                _MEMO[key] = hit
    _, body, gz = hit
    if gz is not None and "gzip" in request.headers.get("Accept-Encoding", ""):
        r = Response(gz, mimetype=mimetype)
        r.headers["Content-Encoding"] = "gzip"
        r.headers["Vary"] = "Accept-Encoding"
        return r
    return Response(body, mimetype=mimetype)


def _jdump(fn):
    return lambda: json.dumps(fn(), separators=(",", ":"))


def _file(path):
    return lambda: open(path, "rb").read()


def _json(obj):
    return Response(json.dumps(obj, separators=(",", ":")), mimetype="application/json")


@app.route("/")
def index():
    return _memo("/", 5, lambda: eventpage.build_html(live=True), "text/html")


@app.route("/data")
def data():
    return _memo("/data", 1, _jdump(eventpage.live_data), "application/json")


@app.route("/series")
def series():
    return _memo("/series", 20, _jdump(eventpage.series_data), "application/json")


@app.route("/hit", methods=["POST"])
def hit():
    j = request.get_json(silent=True) or {}
    try:
        from urllib.parse import unquote
        _HITS.put_nowait((str(j.get("sid", "")), request.headers.get("CF-IPCountry", ""), str(j.get("ref", "")),
                          request.headers.get("User-Agent", ""), int(j.get("w") or 0),
                          unquote(request.headers.get("cf-ipcity", "")), unquote(request.headers.get("cf-region", ""))))
    except Exception:
        pass                                  # queue full: drop the visit count, never slow the page
    return Response(status=204)


_HITS = queue.Queue(maxsize=20000)


def _hit_writer():   # visitor counts are written here, one at a time, so page requests never wait on the database
    while True:
        a = _HITS.get()
        try:
            visitors.hit(*a)
        except Exception:
            pass


threading.Thread(target=_hit_writer, daemon=True).start()


@app.route("/elogo/<name>")
def elogo(name):
    import re as _re
    if not _re.fullmatch(r"[A-Z0-9]+\.webp", name):
        return Response(status=404)
    path = os.path.join(eventpage.ELOGO_DIR, name)
    if not os.path.isfile(path):
        return Response(status=404)
    r = _memo(path, 3600, _file(path), "image/webp")
    r.headers["Cache-Control"] = "public, max-age=86400"
    return r


# ---------------- Predict & Win ----------------
_joins = {}   # in-memory only (never written to disk): hashed client address -> recent join attempts


def _throttle(limit=8, window=600) -> bool:
    import hashlib
    import time as _t
    who = hashlib.sha256((request.headers.get("CF-Connecting-IP") or request.remote_addr or "").encode()).hexdigest()[:16]
    now = _t.time()
    hits = [t for t in _joins.get(who, []) if now - t < window]
    if len(_joins) > 5000:
        _joins.clear()
    _joins[who] = hits + [now]
    return len(hits) >= limit


def _err(e):
    return Response(json.dumps({"error": str(e)}), status=getattr(e, "code", 400), mimetype="application/json")


def _tok():
    return request.headers.get("X-PW-Token", "")


@app.route("/predict")
def predict_page():
    return _memo("/predict", 20, predictpage.build_html, "text/html")


@app.route("/predict/og.png")
def predict_og():
    path = os.path.join(os.path.dirname(eventpage.ELOGO_DIR), "predict_og.png")
    if not os.path.isfile(path):
        return Response(status=404)
    return _memo(path, 3600, _file(path), "image/png")


@app.route("/predict/api/board")
def predict_board():
    return _memo("/board", 3, _jdump(predict.board), "application/json")


@app.route("/predict/api/profile/<handle>")
def predict_profile(handle):
    try:
        return _json(predict.profile(handle))
    except predict.GameError as e:
        return _err(e)


@app.route("/predict/api/join", methods=["POST"])
def predict_join():
    if _throttle():
        return _err(predict.GameError("Too many attempts. Try again in a few minutes.", 429))
    j = request.get_json(silent=True) or {}
    try:
        ip = request.headers.get("CF-Connecting-IP") or request.remote_addr or ""
        return _json(predict.join(str(j.get("handle", "")), str(j.get("name", "")), bool(j.get("consent")), ip))
    except predict.GameError as e:
        return _err(e)


@app.route("/predict/api/me", methods=["POST"])
def predict_me():
    try:
        return _json(predict.me(_tok()))
    except predict.GameError as e:
        return _err(e)


@app.route("/predict/api/submit", methods=["POST"])
def predict_submit():
    j = request.get_json(silent=True) or {}
    picks = j.get("picks") if isinstance(j.get("picks"), dict) else {}
    clean = {}
    for k, v in list(picks.items())[:50]:
        clean[str(k)] = [str(x) for x in v][:20] if isinstance(v, list) else str(v)[:60]
    try:
        return _json(predict.submit_all(_tok(), clean))
    except predict.GameError as e:
        return _err(e)


@app.route("/tlogo/<name>")
def tlogo(name):
    import re as _re
    if not _re.fullmatch(r"[A-Z0-9]+\.webp", name):
        return Response(status=404)
    path = os.path.join(predictpage.TLOGO_DIR, name)
    if not os.path.isfile(path):
        return Response(status=404)
    r = _memo(path, 3600, _file(path), "image/webp")
    r.headers["Cache-Control"] = "public, max-age=86400"
    return r


@app.route("/robots.txt")
def robots():
    return Response("User-agent: *\nDisallow: /\n", mimetype="text/plain")


def run():
    print(f"Event dashboard: http://localhost:{PORT}")
    try:
        from waitress import serve   # production server if installed (pip install waitress)
        serve(app, host="127.0.0.1", port=PORT, threads=48, connection_limit=2000, channel_timeout=30, _quiet=True)
    except ImportError:
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False, threaded=True)
