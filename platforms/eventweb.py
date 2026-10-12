"""Public, read-only live dashboard for the tracked event (only public YouTube numbers, nothing about users).

Runs on its own port (EVENT_WEB_PORT, default 8092, this computer only) so the owner dashboard on 8090 is never
exposed. core/tunnel.py gives it a public https link that opens on any device.
"""
import gzip
import json
import logging
import os

from flask import Flask, Response, request

from core import eventpage, visitors

PORT = int(os.getenv("EVENT_WEB_PORT", "8092"))
app = Flask(__name__)


CACHE = {"/": 5, "/data": 2, "/series": 60}   # seconds Cloudflare (or any CDN) may reuse a response


@app.after_request
def _headers(resp):
    secs = CACHE.get(request.path)
    resp.headers["Cache-Control"] = f"public, max-age={secs}, s-maxage={secs}" if secs else "no-store"
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
        visitors.hit(str(j.get("sid", "")), request.headers.get("CF-IPCountry", ""), str(j.get("ref", "")),
                     request.headers.get("User-Agent", ""), int(j.get("w") or 0))
    except Exception:
        pass
    return Response(status=204)


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
