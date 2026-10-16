"""Public, read-only live dashboard for the tracked event (only public YouTube numbers, nothing about users).

Runs on its own port (EVENT_WEB_PORT, default 8092, this computer only) so the owner dashboard on 8090 is never
exposed. core/tunnel.py gives it a public https link that opens on any device.
"""
import gzip
import json
import logging
import os

from flask import Flask, Response, request

from core import eventpage, predict, predictpage, visitors

PORT = int(os.getenv("EVENT_WEB_PORT", "8092"))
app = Flask(__name__)


CACHE = {"/": 5, "/data": 2, "/series": 60, "/predict": 30, "/predict/api/board": 5, "/predict/og.png": 3600}   # seconds Cloudflare (or any CDN) may reuse a response


@app.after_request
def _headers(resp):
    secs = CACHE.get(request.path)
    if request.path.startswith("/predict/api/profile/") and request.method == "GET":
        secs = 15
    if request.method != "GET" or resp.status_code >= 400:
        secs = None                       # POSTs, personal and error responses are never cached
    if request.path.startswith("/elogo/"):
        return resp
    resp.headers["Cache-Control"] = f"public, max-age={secs}, s-maxage={secs}" if secs else "no-store"
    if secs:   # Cloudflare's Browser Cache TTL can override max-age; this one it passes through for its own cache
        resp.headers["CDN-Cache-Control"] = f"max-age={secs}"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    if (resp.status_code == 200 and not resp.direct_passthrough and "gzip" in request.headers.get("Accept-Encoding", "")
            and len(resp.get_data()) > 1024):
        resp.set_data(gzip.compress(resp.get_data(), 5))
        resp.headers["Content-Encoding"] = "gzip"
        resp.headers["Vary"] = "Accept-Encoding"
    return resp


def _json(obj):
    return Response(json.dumps(obj, separators=(",", ":")), mimetype="application/json")


@app.route("/")
def index():
    return Response(eventpage.build_html(live=True), mimetype="text/html")


@app.route("/data")
def data():
    return _json(eventpage.live_data())


@app.route("/series")
def series():
    return _json(eventpage.series_data())


@app.route("/hit", methods=["POST"])
def hit():
    j = request.get_json(silent=True) or {}
    try:
        from urllib.parse import unquote
        visitors.hit(str(j.get("sid", "")), request.headers.get("CF-IPCountry", ""), str(j.get("ref", "")),
                     request.headers.get("User-Agent", ""), int(j.get("w") or 0),
                     unquote(request.headers.get("cf-ipcity", "")), unquote(request.headers.get("cf-region", "")))
    except Exception:
        pass
    return Response(status=204)


@app.route("/elogo/<name>")
def elogo(name):
    import re as _re
    if not _re.fullmatch(r"[A-Z0-9]+\.webp", name):
        return Response(status=404)
    path = os.path.join(eventpage.ELOGO_DIR, name)
    if not os.path.isfile(path):
        return Response(status=404)
    r = Response(open(path, "rb").read(), mimetype="image/webp")
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
    return Response(predictpage.build_html(), mimetype="text/html")


@app.route("/predict/og.png")
def predict_og():
    path = os.path.join(os.path.dirname(eventpage.ELOGO_DIR), "predict_og.png")
    if not os.path.isfile(path):
        return Response(status=404)
    return Response(open(path, "rb").read(), mimetype="image/png")


@app.route("/predict/api/board")
def predict_board():
    return _json(predict.board())


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
        return _json(predict.join(str(j.get("handle", "")), str(j.get("name", "")), bool(j.get("consent"))))
    except predict.GameError as e:
        return _err(e)


@app.route("/predict/api/me", methods=["POST"])
def predict_me():
    try:
        return _json(predict.me(_tok()))
    except predict.GameError as e:
        return _err(e)


@app.route("/predict/api/pick", methods=["POST"])
def predict_pick():
    j = request.get_json(silent=True) or {}
    try:
        return _json(predict.pick(_tok(), int(j.get("qid") or 0), str(j.get("option", ""))))
    except predict.GameError as e:
        return _err(e)
    except (TypeError, ValueError):
        return _err(predict.GameError("Bad request."))


@app.route("/robots.txt")
def robots():
    return Response("User-agent: *\nDisallow: /\n", mimetype="text/plain")


def run():
    print(f"Event dashboard: http://localhost:{PORT}")
    try:
        from waitress import serve   # production server if installed (pip install waitress)
        serve(app, host="127.0.0.1", port=PORT, threads=16, channel_timeout=30, _quiet=True)
    except ImportError:
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False, threaded=True)
